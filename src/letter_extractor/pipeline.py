"""Page and folder processing. No GUI or CLI code here: both front ends call process_folder()."""
from __future__ import annotations

import multiprocessing
import os
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import cv2

from . import io_utils, report
from .config import Config
from .lines import LineLayout, detect_lines, line_image, lines_overlay
from .prepare import PreparedPage, ink_overlay, prepare_page
from .report import PageResult

ProgressFn = Callable[[int, int, PageResult], None]


def process_page(rgb, cfg: Config) -> Tuple[PreparedPage, Optional[LineLayout]]:
    """Every step for one page: ink masks (C1), then lines (C2). Later chunks add letter cutting."""
    page = prepare_page(rgb, cfg)
    return page, detect_lines(page, cfg)


def _png(img, path: Path) -> None:
    io_utils.save_image(img, path, io_utils.ImageMeta(format="PNG"))


def process_file(src: Path, out_dir: Path, cfg: Config) -> PageResult:
    """Process one page. Never raises: a failing page is recorded in its result (FR-1)."""
    t0 = time.time()
    res = PageResult(file=src.name)
    try:
        rgb, meta = io_utils.load_image(src)
        res.height, res.width = rgb.shape[:2]
        page, layout = process_page(rgb, cfg)
        if page.block is None:
            res.status = report.STATUS_NO_TEXT
            res.message = "no text block found"
        else:
            res.block_x, res.block_y, res.block_w, res.block_h = (str(v) for v in page.block)
        res.black_px, res.red_px = int(page.black.sum()), int(page.red.sum())
        if layout is not None and layout.lines:
            res.lines = len(layout.lines)
            res.line_spacing = layout.spacing
            lines_dir = out_dir / "lines"
            lines_dir.mkdir(exist_ok=True)
            for line in layout.lines:
                _png(line_image(page, line, cfg), lines_dir / f"{src.stem}_L{line.index:02d}.png")
        elif page.block is not None:
            res.status = report.STATUS_NO_TEXT
            res.message = "no text lines found"
        if meta.notes:
            res.message = "; ".join(filter(None, [res.message, *meta.notes]))
        if cfg.debug:
            debug_dir = out_dir / "debug"
            debug_dir.mkdir(exist_ok=True)
            _png(ink_overlay(page), debug_dir / f"{src.stem}_ink.png")
            _png(lines_overlay(page, layout), debug_dir / f"{src.stem}_lines.png")
    except Exception as e:  # one page failing never stops the batch
        res.status = report.STATUS_FAILED
        res.message = f"{type(e).__name__}: {e}"
        if cfg.debug:
            res.message += " | " + traceback.format_exc().splitlines()[-3].strip()
    res.seconds = time.time() - t0
    return res


# --------------------------------------------------------------------------------------
# folder
# --------------------------------------------------------------------------------------
_W_CFG: Optional[Config] = None


def _init_worker(cfg: Config) -> None:
    global _W_CFG
    _W_CFG = cfg
    cv2.setNumThreads(1)


def _work(src: str, out_dir: str) -> PageResult:
    return process_file(Path(src), Path(out_dir), _W_CFG)


def default_workers() -> int:
    return max(1, min((os.cpu_count() or 2) - 1, 6))


def process_folder(input_dir: Path, output_dir: Path, cfg: Optional[Config] = None,
                   progress: Optional[ProgressFn] = None,
                   cancel: Optional[Callable[[], bool]] = None) -> List[PageResult]:
    """Process every supported image in `input_dir` (name order) and write report.csv to `output_dir`."""
    cfg = cfg or Config()
    input_dir, output_dir = Path(input_dir), Path(output_dir)
    io_utils.validate_folders(input_dir, output_dir)
    images, ignored = io_utils.scan_folder(input_dir)
    if not images:
        raise io_utils.FolderError(f"No supported images ({', '.join(sorted(io_utils.SUPPORTED_EXTENSIONS))}) "
                                   f"found in {input_dir}")
    workers = min(cfg.workers if cfg.workers > 0 else default_workers(), len(images))
    results: dict = {}
    total = len(images)

    if workers <= 1:
        for i, p in enumerate(images, 1):
            if cancel and cancel():
                break
            r = process_file(p, output_dir, cfg)
            results[p.name] = r
            if progress:
                progress(i, total, r)
    else:
        done = 0
        # 'spawn' on every OS: same behaviour as Windows, and no fork-after-threads deadlocks with OpenCV
        ctx = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=workers, mp_context=ctx, initializer=_init_worker,
                                 initargs=(cfg,)) as ex:
            futs = {ex.submit(_work, str(p), str(output_dir)): p for p in images}
            for fut in as_completed(futs):
                p = futs[fut]
                try:
                    r = fut.result()
                except Exception as e:
                    r = PageResult(file=p.name, status=report.STATUS_FAILED, message=f"worker error: {e}")
                results[p.name] = r
                done += 1
                if progress:
                    progress(done, total, r)
                if cancel and cancel():
                    for f in futs:
                        f.cancel()
                    break
    ordered = [results[p.name] for p in images if p.name in results]
    report.write_report(ordered, ignored, output_dir)
    return ordered

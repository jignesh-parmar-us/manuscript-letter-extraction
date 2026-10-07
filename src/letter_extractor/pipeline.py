"""Page and folder processing. No GUI or CLI code here: both front ends call process_folder()."""
from __future__ import annotations

import multiprocessing
import os
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from PIL import Image

from . import io_utils, report
from .config import Config
from .features import fingerprint, fingerprint_size
from .grouping import group_samples, write_group_folders, write_groups_html
from .letters import Letter, letter_image, letters_overlay, make_letters
from .lines import LineLayout, detect_lines, line_image, lines_overlay
from .pieces import Piece, pieces_overlay, split_lines
from .prepare import PreparedPage, ink_overlay, prepare_page
from .report import PageResult

ProgressFn = Callable[[int, int, PageResult], None]


@dataclass
class PageData:
    page: PreparedPage
    layout: Optional[LineLayout]
    pieces: List[Piece]
    specks: int
    letters: List[Letter]


def process_page(rgb, cfg: Config) -> PageData:
    """Every step for one page: ink masks (C1), lines (C2), stroke pieces (C3a), letters (C3b); with
    `cut_method = "tesseract"` the letters are cut by Tesseract's reading of each line (C12c); with
    `bar_fix` (printed books) aa bars cut onto the next letter go back to theirs (bars.py)."""
    if cfg.cut_method not in ("shapes", "tesseract"):
        raise ValueError(f"Unknown cut_method '{cfg.cut_method}' (shapes or tesseract)")
    page = prepare_page(rgb, cfg)
    layout = detect_lines(page, cfg)
    if layout is None:
        return PageData(page, None, [], 0, [])
    pieces, specks = split_lines(page, layout, cfg)
    letters = make_letters(page, layout, pieces, cfg)
    if cfg.cut_method == "tesseract":
        from .ocr.cut import tesseract_letters
        letters = tesseract_letters(page, layout.lines, letters, cfg)
    if cfg.bar_fix:                                   # printed books: aa bars cut onto the next letter
        from .bars import move_bars
        letters = move_bars(letters, cfg)
    return PageData(page, layout, pieces, specks, letters)


def _png(img, path: Path) -> None:
    io_utils.save_image(img, path, io_utils.ImageMeta(format="PNG"))


def _write_letters(page: PreparedPage, letters: List[Letter], spacing: float, stem: str, out_dir: Path,
                   cfg: Config, res: PageResult) -> None:
    """letters/<page>/L01_003.png for every letter, the page's rows for samples.csv and the letters'
    fingerprints for grouping."""
    folder = out_dir / "letters" / stem
    folder.mkdir(parents=True, exist_ok=True)
    for pattern in ("L[0-9][0-9]_[0-9][0-9][0-9].png", "L[0-9][0-9]_[0-9][0-9][0-9]_mask.png"):
        for old in folder.glob(pattern):              # letters of an earlier run
            old.unlink()
    for L in letters:
        name = f"L{L.line:02d}_{L.pos:03d}.png"
        _png(letter_image(page, L, cfg), folder / name)
        x, y, w, h = L.box
        row = {"page": res.file, "line": L.line, "pos": L.pos, "x": x, "y": y, "w": w, "h": h,
               "ink": L.ink, "kind": L.kind, "pieces": L.pieces, "rules": " ".join(L.rules),
               "image": f"letters/{stem}/{name}", "text": L.text}
        if cfg.save_masks:
            mask_name = f"L{L.line:02d}_{L.pos:03d}_mask.png"
            Image.fromarray(L.mask.astype(np.uint8) * 255).save(folder / mask_name)
            row["mask"] = f"letters/{stem}/{mask_name}"
        res.samples.append(row)
    res.features = (np.stack([fingerprint(L.mask, spacing, cfg) for L in letters]) if letters
                    else np.zeros((0, fingerprint_size(cfg)), np.float32))
    res.letters = len(letters)
    res.dandas = sum(L.kind == "danda" for L in letters)
    res.digits = sum(L.kind == "digit" for L in letters)


def process_file(src: Path, out_dir: Path, cfg: Config) -> PageResult:
    """Process one page. Never raises: a failing page is recorded in its result (FR-1)."""
    t0 = time.time()
    res = PageResult(file=src.name)
    try:
        rgb, meta = io_utils.load_image(src)
        res.height, res.width = rgb.shape[:2]
        data = process_page(rgb, cfg)
        page, layout, pieces = data.page, data.layout, data.pieces
        if page.block is None:
            res.status = report.STATUS_NO_TEXT
            res.message = "no text block found"
        else:
            res.block_x, res.block_y, res.block_w, res.block_h = (str(v) for v in page.block)
        res.black_px, res.red_px = int(page.black.sum()), int(page.red.sum())
        if layout is not None and layout.lines:
            res.lines = len(layout.lines)
            res.line_spacing = layout.spacing
            res.pieces = len(pieces)
            res.specks = data.specks
            lines_dir = out_dir / "lines"
            lines_dir.mkdir(exist_ok=True)
            for line in layout.lines:
                _png(line_image(page, line, cfg), lines_dir / f"{src.stem}_L{line.index:02d}.png")
                lx, ly, lw, lh = line.box
                res.lines_info.append({"number": line.index, "x": lx, "y": ly, "w": lw, "h": lh, "ink": line.ink,
                                       "image": f"lines/{src.stem}_L{line.index:02d}.png"})
            _write_letters(page, data.letters, layout.spacing, src.stem, out_dir, cfg, res)
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
            if layout is not None:
                _png(pieces_overlay(page, layout, pieces, cfg), debug_dir / f"{src.stem}_pieces.png")
                _png(letters_overlay(page, data.letters), debug_dir / f"{src.stem}_letters.png")
    except Exception as e:  # one page failing never stops the batch
        res.samples, res.features, res.lines_info = [], None, []   # a failed page contributes nothing
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
                   cancel: Optional[Callable[[], bool]] = None,
                   summary: Optional[dict] = None, files: Optional[Sequence[str]] = None,
                   finish: bool = True) -> List[PageResult]:
    """Process every supported image in `input_dir` (name order), then group the letters of all pages,
    and write report.csv, samples.csv, groups/, unsure/ and groups.html to `output_dir`.
    `summary`, if given, receives the run totals (samples, groups, unsure).
    `files` limits the run to these file names; `finish=False` skips grouping and the reports (the
    app adds pages to a book that way and matches their letters to the book's own groups)."""
    cfg = cfg or Config()
    input_dir, output_dir = Path(input_dir), Path(output_dir)
    io_utils.validate_folders(input_dir, output_dir)
    images, ignored = io_utils.scan_folder(input_dir)
    if files is not None:
        wanted = set(files)
        images = [p for p in images if p.name in wanted]
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
    if not finish:
        return ordered
    report.write_report(ordered, ignored, output_dir)
    totals = _group_letters(ordered, output_dir, cfg)
    report.write_samples(ordered, output_dir)
    if summary is not None:
        summary.update(totals)
    return ordered


def _group_letters(results: List[PageResult], out_dir: Path, cfg: Config) -> dict:
    """Group the letters of all pages (C4) and write the group folders and groups.html."""
    usable = [r for r in results if r.features is not None and len(r.features) == len(r.samples) > 0]
    rows = [row for r in usable for row in r.samples]
    feats = [r.features for r in usable]
    if not rows:
        return {"samples": 0, "groups": 0, "unsure": 0}
    X = np.concatenate(feats).astype(np.float32)
    grouping = group_samples(X, [row["kind"] for row in rows], cfg)
    for row, gid, d in zip(rows, grouping.group_id, grouping.distance):
        row["group_id"] = gid
        row["distance"] = "" if np.isnan(d) else f"{d:.3f}"
    if cfg.write_groups:
        write_group_folders(out_dir, rows, grouping)
        write_groups_html(out_dir, rows, grouping, cfg)
    return {"samples": len(rows), "groups": len(grouping.groups), "unsure": len(grouping.unsure)}

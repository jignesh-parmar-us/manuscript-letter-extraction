"""Export of a book (C5g, FR-9 and FR-10): the dataset for OCR training, from the book's database.

```
<export folder>/
  dataset/<category>/<safe name>/   every sample of each labelled letter (class), label.txt = Gujarati label
  lines/<page>_L01.png + .txt       each line and its Gujarati text from the labelled letters ([?] = unlabelled)
  unsure/                           samples without a label (in no group, or in a group without label)
  letters.csv                       one row per class
  samples.csv                       one row per sample (traceable to page, line and box)
  overview.html                     one example per class in alphabet order, few-sample classes highlighted
  summary.txt                       the run summary (FR-10)
```

A class is a label: groups with the same label are one class. Deleted samples are left out.
Reading order within a line is the x position of the sample's box, so samples cut, joined or split by
hand (C5f) fall into place. The export never writes outside its folder, and a chosen folder must be
new or empty.
"""
from __future__ import annotations

import csv
import html
import shutil
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np
from PIL import Image
from sqlalchemy import select

from .. import io_utils
from ..features import normalize
from ..mapping import CATEGORIES, category, code_points, mapping_for, safe_name, sort_key, transliterate, unmapped
from .db import Book, LetterGroup, Line, Page, Sample
from .library import Library, LibraryError, NotFound

IMAGE_MODES = ("original", "normalized", "fixed64")
LETTER_COLUMNS = ["gujarati", "devanagari", "code_points", "transliteration", "category", "samples", "folder",
                  "example_image"]
SAMPLE_COLUMNS = ["page", "line", "pos", "x", "y", "w", "h", "ink", "kind", "source", "group", "label_gujarati",
                  "label_devanagari", "group_status", "distance", "image", "letter_image"]


@dataclass
class _Class:
    label_dev: str
    label_guj: str
    folder: str
    samples: List[Sample]


def _write_image(lib: Library, book: Book, smp: Sample, target: Path, mode: str) -> None:
    folder = lib.book_dir(book)
    if mode == "original":
        shutil.copyfile(folder / smp.image, target)
        return
    with Image.open(folder / smp.mask) as im:
        mask = np.asarray(im.convert("L")) > 127
    if mode == "fixed64":
        img = 255 - normalize(mask, 64)                        # black ink on white, 64 x 64, aspect kept
    else:
        img = np.where(np.pad(mask, 4), 0, 255).astype(np.uint8)   # black on white, original size + margin
    Image.fromarray(img).save(target)


def _reading_order(samples: List[Sample]) -> List[Sample]:
    return sorted(samples, key=lambda x: (x.page_id or 0, x.line_number, x.x))


def export_book(lib: Library, book_id: int, folder: Optional[Path] = None, image: Optional[str] = None) -> Dict:
    """Write the export and return its summary (with the folder)."""
    with lib.session() as s:
        book = s.get(Book, book_id)
        if book is None:
            raise NotFound(f"No book with id {book_id}.")
        cfg = lib.book_config(book)
        mode = image or cfg.dataset_image
        if mode not in IMAGE_MODES:
            raise LibraryError(f"Image mode must be one of {', '.join(IMAGE_MODES)}, not '{mode}'.")
        m = mapping_for(cfg)
        if folder is None:
            folder = lib.book_dir(book) / "exports" / datetime.now().strftime("%Y-%m-%d_%H%M%S")
        folder = Path(folder).expanduser()
        if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
            raise LibraryError(f"The export folder must be new or empty: {folder}")
        pages = {p.id: p for p in s.scalars(select(Page).where(Page.book_id == book_id))}
        groups = {g.id: g for g in s.scalars(select(LetterGroup).where(LetterGroup.book_id == book_id))}
        samples = _reading_order(list(s.scalars(select(Sample).where(Sample.book_id == book_id,
                                                                    Sample.deleted.is_(False)))))
        lines = list(s.scalars(select(Line).join(Page).where(Page.book_id == book_id)
                               .order_by(Line.page_id, Line.number)))

        # ---- classes: one per label --------------------------------------------------------------------
        by_label: Dict[str, List[Sample]] = defaultdict(list)
        unsure: List[Sample] = []
        for smp in samples:
            g = groups.get(smp.group_id) if smp.group_id else None
            if g is not None and g.label_dev:
                by_label[g.label_dev].append(smp)
            else:
                unsure.append(smp)
        classes = [_Class(dev, m.gujarati(dev), safe_name(dev, m), by_label[dev])
                   for dev in sorted(by_label, key=sort_key)]

        folder.mkdir(parents=True, exist_ok=True)
        exported: Dict[int, str] = {}                           # sample id -> exported image path
        for cls in classes:
            target = folder / "dataset" / category(cls.label_dev) / cls.folder
            target.mkdir(parents=True, exist_ok=True)
            (target / "label.txt").write_text(cls.label_guj + "\n", encoding="utf-8")
            for smp in cls.samples:
                stem = Path(pages[smp.page_id].file).stem if smp.page_id in pages else "uploaded"
                name = f"{stem}_L{smp.line_number:02d}_{smp.id:06d}.png"
                _write_image(lib, book, smp, target / name, mode)
                exported[smp.id] = (target / name).relative_to(folder).as_posix()
        (folder / "unsure").mkdir(exist_ok=True)
        for smp in unsure:
            stem = Path(pages[smp.page_id].file).stem if smp.page_id in pages else "uploaded"
            name = f"{stem}_L{smp.line_number:02d}_{smp.id:06d}.png"
            shutil.copyfile(lib.book_dir(book) / smp.image, folder / "unsure" / name)
            exported[smp.id] = f"unsure/{name}"

        # ---- lines with their Gujarati text ---------------------------------------------------------------
        (folder / "lines").mkdir(exist_ok=True)
        on_line: Dict[int, List[Sample]] = defaultdict(list)
        for smp in samples:
            if smp.line_id is not None:
                on_line[smp.line_id].append(smp)
        n_unknown = 0
        for ln in lines:
            stem = f"{Path(pages[ln.page_id].file).stem}_L{ln.number:02d}"
            src = lib.book_dir(book) / ln.image
            if src.is_file():
                shutil.copyfile(src, folder / "lines" / f"{stem}.png")
            text = []
            for smp in sorted(on_line[ln.id], key=lambda x: x.x):
                g = groups.get(smp.group_id) if smp.group_id else None
                if g is not None and g.label_dev:
                    text.append(m.gujarati(g.label_dev))
                else:
                    text.append("[?]")
                    n_unknown += 1
            (folder / "lines" / f"{stem}.txt").write_text("".join(text) + "\n", encoding="utf-8")

        # ---- letters.csv, samples.csv -----------------------------------------------------------------------
        with open(folder / "letters.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(LETTER_COLUMNS)
            for cls in classes:
                w.writerow([cls.label_guj, cls.label_dev, code_points(cls.label_guj), transliterate(cls.label_dev),
                            category(cls.label_dev), len(cls.samples),
                            f"dataset/{category(cls.label_dev)}/{cls.folder}", exported[cls.samples[0].id]])
        pos_in_line: Dict[int, int] = {}
        for smps in on_line.values():
            for k, smp in enumerate(sorted(smps, key=lambda x: x.x), 1):
                pos_in_line[smp.id] = k
        with open(folder / "samples.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(SAMPLE_COLUMNS)
            for smp in samples:
                g = groups.get(smp.group_id) if smp.group_id else None
                page = pages.get(smp.page_id)
                w.writerow([page.file if page else "", smp.line_number or "", pos_in_line.get(smp.id, ""),
                            smp.x, smp.y, smp.w, smp.h, smp.ink, smp.kind, smp.source, g.code if g else "",
                            m.gujarati(g.label_dev) if g and g.label_dev else "", g.label_dev if g else "",
                            g.status if g else "", "" if smp.distance is None else f"{smp.distance:.3f}",
                            exported[smp.id], smp.image])

        # ---- overview.html, summary.txt ------------------------------------------------------------------------
        warn = cfg.min_samples_warn
        _write_overview(folder, book.name, classes, exported, warn, len(unsure))
        kept = sorted({ch for cls in classes for ch in unmapped(cls.label_dev, m)})
        few = [cls for cls in classes if len(cls.samples) < warn]
        skipped = [p.file for p in pages.values() if p.status != "OK"]
        summary = {
            "folder": str(folder), "image": mode, "pages": len(pages), "lines": len(lines),
            "letters": len(samples), "classes": len(classes), "few_samples": len(few),
            "labelled_samples": sum(len(c.samples) for c in classes), "unsure": len(unsure),
            "unlabelled_in_lines": n_unknown, "skipped_pages": skipped, "kept_in_devanagari": kept,
            "uploaded": sum(smp.source == "uploaded" for smp in samples),
        }
        lines_txt = [
            f"Book: {book.name}", f"Exported: {datetime.now().isoformat(timespec='seconds')}",
            f"Pages: {len(pages)}", f"Lines: {len(lines)}", f"Letters (samples): {len(samples)}",
            f"Classes (labelled letters): {len(classes)}",
            f"Classes with fewer than {warn} samples: {len(few)}"
            + (f" ({' '.join(c.label_guj for c in few)})" if few else ""),
            f"Unsure (no label): {len(unsure)}", f"Uploaded samples: {summary['uploaded']}",
            f"Skipped pages: {len(skipped)}" + (f" ({', '.join(skipped)})" if skipped else ""),
            f"Characters kept in Devanagari: {' '.join(kept) if kept else 'none'}",
            f"Dataset images: {mode}",
        ]
        (folder / "summary.txt").write_text("\n".join(lines_txt) + "\n", encoding="utf-8")
        return summary


def _write_overview(folder: Path, book_name: str, classes: List[_Class], exported: Dict[int, str], warn: int,
                    n_unsure: int) -> None:
    css = """
:root { --bg:#faf8f5; --fg:#222; --muted:#666; --line:#e3ded6; --card:#fff; --warn:#b54708; --accent:#8a3b12; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#1d1c1a; --fg:#eee; --muted:#aaa; --line:#3a3732; --card:#262522; --warn:#f79009; --accent:#e0915f; }
}
body { margin:0; padding:24px 16px; background:var(--bg); color:var(--fg);
       font:15px/1.45 system-ui, -apple-system, "Segoe UI", "Noto Sans Gujarati", sans-serif; }
h1 { font-size:22px; margin:0 0 4px; } h2 { font-size:17px; margin:24px 0 8px; }
.sub { color:var(--muted); margin:0 0 16px; }
.grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(120px, 1fr)); gap:10px; }
.cls { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:8px; text-align:center; }
.cls.few { border-color:var(--warn); box-shadow:0 0 0 1px var(--warn) inset; }
.cls img { height:56px; max-width:100%; object-fit:contain; background:#fff; border-radius:3px; }
.label { font-size:26px; line-height:1.2; }
.meta { color:var(--muted); font-size:12px; }
.cls.few .meta { color:var(--warn); }
"""
    parts = ["<!doctype html><html lang='gu'><head><meta charset='utf-8'>",
             "<meta name='viewport' content='width=device-width, initial-scale=1'>",
             f"<title>Letters of {html.escape(book_name)}</title><style>{css}</style></head><body>",
             f"<h1>Letters of {html.escape(book_name)}</h1>",
             f"<p class='sub'>{len(classes)} letters, {sum(len(c.samples) for c in classes)} labelled samples, "
             f"{n_unsure} unsure. Letters with fewer than {warn} samples are outlined.</p>"]
    for cat in CATEGORIES:
        mine = [c for c in classes if category(c.label_dev) == cat]
        if not mine:
            continue
        parts.append(f"<h2>{cat.capitalize()} ({len(mine)})</h2><div class='grid'>")
        for c in mine:
            few = " few" if len(c.samples) < warn else ""
            parts.append(
                f"<div class='cls{few}'><img src='{html.escape(exported[c.samples[0].id])}' alt=''>"
                f"<div class='label'>{html.escape(c.label_guj)}</div>"
                f"<div class='meta'>{html.escape(c.label_dev)} · {len(c.samples)} samples</div></div>")
        parts.append("</div>")
    parts.append("</body></html>")
    (folder / "overview.html").write_text("\n".join(parts), encoding="utf-8")

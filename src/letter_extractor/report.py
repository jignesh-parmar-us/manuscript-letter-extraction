"""Per-page results and the CSV report (FR-1, FR-10)."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

STATUS_OK = "OK"
STATUS_NO_TEXT = "NO_TEXT"
STATUS_FAILED = "FAILED"
STATUS_IGNORED = "IGNORED"

CSV_COLUMNS = ["file", "status", "message", "width", "height",
               "block_x", "block_y", "block_w", "block_h", "black_px", "red_px",
               "lines", "line_spacing", "pieces", "specks", "letters", "dandas", "digits", "seconds"]

SAMPLE_COLUMNS = ["page", "line", "pos", "x", "y", "w", "h", "ink", "kind", "pieces", "rules", "image",
                  "group_id", "distance", "text"]          # text: Tesseract's reading when cut by it (C12c)


@dataclass
class PageResult:
    file: str
    status: str = STATUS_OK
    message: str = ""
    width: int = 0
    height: int = 0
    block_x: str = ""                 # text block (empty when none was found)
    block_y: str = ""
    block_w: str = ""
    block_h: str = ""
    black_px: int = 0
    red_px: int = 0
    lines: int = 0
    line_spacing: float = 0.0         # line pitch found on the page (px)
    pieces: int = 0                   # stroke pieces after the first cut at headline breaks
    specks: int = 0                   # pieces dropped as too small
    letters: int = 0                  # letter samples after the join and split rules (all kinds)
    dandas: int = 0                   # ...of which dandas (single or double)
    digits: int = 0                   # ...of which verse-number digits
    seconds: float = 0.0
    samples: List[Dict] = field(default_factory=list, repr=False)   # one row per letter (samples.csv)
    features: Optional[np.ndarray] = field(default=None, repr=False)  # one fingerprint per sample (C4)
    lines_info: List[Dict] = field(default_factory=list, repr=False)  # one entry per line (for the app)


def write_report(results: List[PageResult], ignored: List[Path], out_dir: Path) -> Path:
    path = Path(out_dir) / "report.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig: opens cleanly in Excel
        w = csv.writer(f)
        w.writerow(CSV_COLUMNS)
        for r in results:
            d = {f.name: getattr(r, f.name) for f in fields(r)}
            w.writerow([f"{d[c]:.3f}" if isinstance(d[c], float) else d[c] for c in CSV_COLUMNS])
        for p in ignored:
            row = dict.fromkeys(CSV_COLUMNS, "")
            row.update(file=p.name, status=STATUS_IGNORED, message="not a supported image file")
            w.writerow([row[c] for c in CSV_COLUMNS])
    return path


def write_samples(results: List[PageResult], out_dir: Path) -> Path:
    """samples.csv: one row per letter sample, in page and reading order (FR-6). `image` is the
    letter image relative to the output folder; `rules` lists the join / split rules applied;
    `group_id` is the letter group (or "unsure") and `distance` the distance to its group's centre."""
    path = Path(out_dir) / "samples.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=SAMPLE_COLUMNS, restval="", extrasaction="ignore")
        w.writeheader()
        for r in results:
            w.writerows(r.samples)
    return path

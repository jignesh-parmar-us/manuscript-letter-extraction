"""Per-page results and the CSV report (FR-1, FR-10)."""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List

STATUS_OK = "OK"
STATUS_NO_TEXT = "NO_TEXT"
STATUS_FAILED = "FAILED"
STATUS_IGNORED = "IGNORED"

CSV_COLUMNS = ["file", "status", "message", "width", "height",
               "block_x", "block_y", "block_w", "block_h", "black_px", "red_px",
               "lines", "line_spacing", "seconds"]


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
    seconds: float = 0.0


def write_report(results: List[PageResult], ignored: List[Path], out_dir: Path) -> Path:
    path = Path(out_dir) / "report.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig: opens cleanly in Excel
        w = csv.writer(f)
        w.writerow(CSV_COLUMNS)
        for r in results:
            d = asdict(r)
            w.writerow([f"{d[c]:.3f}" if isinstance(d[c], float) else d[c] for c in CSV_COLUMNS])
        for p in ignored:
            row = dict.fromkeys(CSV_COLUMNS, "")
            row.update(file=p.name, status=STATUS_IGNORED, message="not a supported image file")
            w.writerow([row[c] for c in CSV_COLUMNS])
    return path

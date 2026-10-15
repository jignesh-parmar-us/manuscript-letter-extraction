"""Metrics (F3): where each glyph sits on the line, how wide it is, and the spacing between letters.

From the library only (sample and line boxes, labels): no image is opened, so it is cheap to run each time.

  - **Baseline of each line:** the bottom edge of the letters without a part below the line (no ु ू ृ ्
    …), fitted as a straight line `y = a + b·x`. Scanned pages are often a little tilted (book 6: about
    40 px over a line, as much as a letter's height), so one flat baseline per line would be wrong at the
    ends. The fit is made twice: letters far from the first fit are left out of the second.
  - **A glyph's place:** for each copy it was made from, the ink's bottom and top against the baseline at
    the ink's x; the median over the copies. Positive = below the baseline (in page pixels).
  - **Width:** the median ink width of those copies.
  - **Letter gap and word space:** the gaps between neighbouring samples on a line (by x), over every cut
    letter of the Training Data pages, labelled or not (with labelled ones only, an unlabelled letter
    between two others looked like a word space: book 6 gave 94 px). A gap narrower than LETTER_GAP_MAX of
    the line height is between letters, a wider one is a word space; the median of each.
  - **Estimated place:** a glyph made only from letters the system generated has no line. It gets the
    median place of the measured glyphs with the same signs below the line (ु, ू, ृ, … or none), and is
    marked `placed: "estimated"`.
  - **Line height:** the median line height, which F5 turns into the font's size (one scale for the font).

Every value is in page pixels; F5 converts them to font units.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import select

from letter_extractor.app.db import LetterGroup, Line, Sample

from .store import Store

BELOW = set("ुूृॄ्ॢॣ")          # signs drawn below the line (a virama also stands for a conjunct's lower part)
LETTER_GAP_MAX = 0.15           # of the line height: a wider gap between neighbours is a word space
OUTLIER = 0.08                  # of the line height: farther from the first fit, left out of the second
MIN_FIT = 3                     # fewer clean letters on a line: their median is used, flat


def has_below(label: str) -> bool:
    return any(ch in BELOW for ch in label)


@dataclass
class Baseline:
    a: float                    # y at x = 0
    b: float                    # slope (pixels down per pixel to the right)

    def at(self, x: float) -> float:
        return self.a + self.b * x


def fit(points: Sequence[Tuple[float, float]], tolerance: float) -> Baseline:
    """A straight line through (x, bottom) points, made twice: far points are left out of the second fit."""
    def least_squares(pts):
        n = len(pts)
        mx = sum(p[0] for p in pts) / n
        my = sum(p[1] for p in pts) / n
        sxx = sum((p[0] - mx) ** 2 for p in pts)
        b = sum((p[0] - mx) * (p[1] - my) for p in pts) / sxx if sxx else 0.0
        return Baseline(my - b * mx, b)

    if len(points) < MIN_FIT:
        return Baseline(median(p[1] for p in points), 0.0)
    first = least_squares(points)
    near = [p for p in points if abs(p[1] - first.at(p[0])) <= tolerance]
    return least_squares(near) if len(near) >= MIN_FIT else first


@dataclass
class Box:
    sample: int
    line: int
    x: int
    y: int
    w: int
    h: int
    label: str


def baselines(boxes: Iterable[Box], line_height: Dict[int, int]) -> Dict[int, Baseline]:
    by_line: Dict[int, List[Box]] = {}
    for b in boxes:
        by_line.setdefault(b.line, []).append(b)
    out = {}
    for line, bs in by_line.items():
        clean = [(b.x + b.w / 2, b.y + b.h) for b in bs if not has_below(b.label)]
        points = clean if len(clean) >= MIN_FIT else [(b.x + b.w / 2, b.y + b.h) for b in bs]
        out[line] = fit(points, OUTLIER * line_height.get(line, 100))
    return out


def gaps(boxes: Iterable[Box], line_px: float) -> Tuple[Optional[float], Optional[float]]:
    """(letter gap, word space): medians of the gaps between neighbours on a line, sorted by x."""
    by_line: Dict[int, List[Box]] = {}
    for b in boxes:
        by_line.setdefault(b.line, []).append(b)
    letter, space = [], []
    for bs in by_line.values():
        bs.sort(key=lambda b: b.x)
        for left, right in zip(bs, bs[1:]):
            g = right.x - (left.x + left.w)
            (letter if g < LETTER_GAP_MAX * line_px else space).append(max(g, 0))
    return (median(letter) if letter else None), (median(space) if space else None)


def below_key(label: str) -> str:
    return "".join(sorted({c for c in label if c in BELOW and c != "्"}))


def estimate(glyphs: List[Dict], scale: int) -> None:
    """Give glyphs without a measured place the median bottom of measured glyphs with the same signs below
    the line (0 when there is none); top and width come from the glyph image (enlarged `scale` times)."""
    by_key: Dict[str, List[float]] = {}
    for g in glyphs:
        if g.get("bottom") is not None:
            by_key.setdefault(below_key(g["label_dev"]), []).append(g["bottom"])
    for g in glyphs:
        if g.get("bottom") is not None:
            g["placed"] = "measured"
            continue
        known = by_key.get(below_key(g["label_dev"]))
        bottom = round(median(known), 1) if known else 0.0
        g.update(bottom=bottom, top=round(bottom - g["size"][1] / scale, 1), width=round(g["size"][0] / scale, 1),
                 placed="estimated")


def place(ink: Dict[str, List[int]], boxes: Dict[int, Box], lines: Dict[int, Baseline]) -> Dict:
    """A glyph's bottom, top (against the baseline, + = below) and width, from its copies' ink boxes
    `{sample id: [top, bottom, left, right]}` inside the sample box (bottom and right exclusive)."""
    bottoms, tops, widths = [], [], []
    for sid, (t, btm, l, r) in ink.items():
        b = boxes.get(int(sid))
        if b is None or b.line not in lines:
            continue
        base = lines[b.line].at(b.x + (l + r) / 2)
        bottoms.append(b.y + btm - base)
        tops.append(b.y + t - base)
        widths.append(r - l)
    if not bottoms:
        return {"bottom": None, "top": None, "width": None}
    return {"bottom": round(median(bottoms), 1), "top": round(median(tops), 1), "width": round(median(widths), 1)}


class Lines:
    """The measured lines of a font's books: baselines, sample boxes and the font-wide numbers."""

    def __init__(self, boxes: Dict[int, Box], baselines: Dict[int, Baseline], summary: Dict):
        self.boxes, self.baselines, self.summary = boxes, baselines, summary

    def place(self, ink: Dict[str, List[int]]) -> Dict:
        return place(ink, self.boxes, self.baselines)


def measure(store: Store, sources: List[int]) -> Lines:
    """Two queries: every labelled sample on a line in the font's books with its line's height (baselines,
    places), and every cut letter of the Training Data pages (gaps)."""
    with store.session() as s:
        rows = s.execute(select(Sample.id, Sample.line_id, Sample.x, Sample.y, Sample.w, Sample.h,
                                LetterGroup.label_dev, Line.h)
                         .join(LetterGroup, LetterGroup.id == Sample.group_id)
                         .join(Line, Line.id == Sample.line_id)
                         .where(Sample.book_id.in_(sources), Sample.deleted.is_(False),
                                LetterGroup.label_dev != "")).all()
        every = s.execute(select(Sample.id, Sample.line_id, Sample.x, Sample.w)
                          .where(Sample.book_id.in_(sources), Sample.deleted.is_(False), Sample.part == "training",
                                 Sample.line_id.is_not(None))).all()
    boxes = {r[0]: Box(r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in rows}
    heights = {r[1]: r[7] for r in rows}
    line_px = float(median(heights.values())) if heights else 0.0
    letter, space = gaps((Box(r[0], r[1], r[2], 0, r[3], 0, "") for r in every), line_px)
    summary = {"lines": len(heights), "line_height": line_px, "letter_gap": letter, "word_space": space}
    return Lines(boxes, baselines(boxes.values(), heights), summary)

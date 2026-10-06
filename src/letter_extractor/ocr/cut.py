"""Cutting a line into letters by Tesseract's reading, for printed books (C12c).

The other way to cut (C3a, C3b) goes by the shapes of the ink. On print it often leaves two letters in
one sample or cuts a vowel bar off. Here Phase 1 still finds the lines (C2), with each line's own ink;
Tesseract reads the line image, and the line is cut into exactly the aksharas it read:

- between two aksharas, the cut goes to the column with the least ink (the headline rows left out)
  within `recut_window` x the median akshara width of Tesseract's boundary (its boxes are rough);
- cuts closer together than `tesseract_cut_min_gap` x that width are not made: the aksharas between
  them stay in one sample, with their text together (a word sample), rather than giving slivers;
- an akshara without a usable box is kept with its neighbour the same way.

Splits only fall between aksharas (ocr/aksharas.py), so conjuncts, reph and vowel signs stay with
their letter. Each letter keeps the akshara(s) it was cut as in `Letter.text`: the review app stores
them as readings, so suggestions are there right after capture. A line Tesseract cannot read, or
reads as fewer than half as many aksharas as the shape cut finds letters, is cut the other way.
"""
from __future__ import annotations

import os
import unicodedata
from statistics import median
from typing import Callable, List, Optional

import numpy as np

from ..config import Config
from ..letters import Letter
from ..lines import Line, line_image
from ..prepare import PreparedPage
from .aksharas import line_aksharas
from .align import akshara_spans
from .tesseract import Engine, TesseractError, find_tesseract, read_line

DANDAS = {"।", "॥"}

_ENGINE: Optional[Engine] = None


def engine(cfg: Config) -> Engine:
    """The installed Tesseract, found once per process (pages are cut in worker processes)."""
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = find_tesseract(os.environ.get("LETTER_EXTRACTOR_TESSERACT", ""))
        _ENGINE.check_langs(cfg.ocr_langs)
    return _ENGINE


def best_cut(mask: np.ndarray, at: int, window: int) -> Optional[int]:
    """The column near `at` with the least ink below and above the headline (the headline joins the
    letters of a word, so its rows are left out). Ties go to the nearest column."""
    h, w = mask.shape
    lo, hi = max(1, at - window), min(w - 1, at + window)
    if lo > hi:
        return None
    rows = mask.sum(axis=1)
    head = int(np.argmax(rows[: max(1, h // 2)]))
    band = max(2, h // 12)
    keep = np.ones(h, bool)
    keep[max(0, head - band): head + band + 1] = False
    profile = mask[keep].sum(axis=0)
    return min(range(lo, hi + 1), key=lambda c: (int(profile[c]), abs(c - at)))


def _kind(text: str) -> str:
    if text and all(ch in DANDAS for ch in text):
        return "danda"
    if text and all(unicodedata.category(ch) == "Nd" for ch in text):
        return "digit"
    return "letter"


def cut_line(page: PreparedPage, line: Line, aksharas, x0: int, cfg: Config) -> List[Letter]:
    """The line's ink cut into its aksharas. `aksharas` have boxes in the line image, whose left edge
    is page column `x0`."""
    lx, ly, lw, lh = line.box
    spans = [None if sp is None else (sp[0] - lx, sp[1] - lx) for sp in akshara_spans(aksharas, x0)]
    known = [b - a for sp in spans if sp is not None for a, b in [sp]]
    if not known:
        return []
    width = median(known)
    units: List[List[int]] = [[0]]                     # akshara indices per letter
    cuts: List[int] = []
    for k in range(len(aksharas) - 1):
        cut = None
        if spans[k] is not None and spans[k + 1] is not None:
            at = (spans[k][1] + spans[k + 1][0]) // 2
            cut = best_cut(line.mask, at, max(4, int(cfg.recut_window * width)))
        last = cuts[-1] if cuts else 0
        if cut is None or cut - last < cfg.tesseract_cut_min_gap * width or cut >= lw:
            units[-1].append(k + 1)                    # no clear boundary: one sample for both
        else:
            cuts.append(cut)
            units.append([k + 1])
    edges = [0] + cuts + [lw]
    letters: List[Letter] = []
    for unit, a, b in zip(units, edges, edges[1:]):
        part = line.mask[:, a:b]
        ys, xs = np.nonzero(part)
        if ys.size < 15:
            continue
        y0, y1, c0, c1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        mask = part[y0:y1, c0:c1].copy()
        box = (lx + a + int(c0), ly + int(y0), int(c1 - c0), int(y1 - y0))
        page_red = page.red[box[1]:box[1] + box[3], box[0]:box[0] + box[2]]
        ink = "red" if 2 * int((page_red & mask).sum()) > int(mask.sum()) else "black"
        text = unicodedata.normalize("NFC", "".join(aksharas[i].text for i in unit))
        letters.append(Letter(line=line.index, pos=len(letters) + 1, box=box, mask=mask, ink=ink, kind=_kind(text),
                              pieces=1, rules=["tesseract"], text=text))
    return letters


def tesseract_letters(page: PreparedPage, lines: List[Line], shape_letters: List[Letter], cfg: Config,
                      reader: Optional[Callable] = None) -> List[Letter]:
    """Every line cut by Tesseract's reading; a line it cannot read keeps the shape cut. `reader`
    replaces Tesseract (tests): reader(line image) -> LineReading."""
    if reader is None:
        eng = engine(cfg)

        def reader(img):
            return read_line(img, eng, langs=cfg.ocr_langs, psm=cfg.ocr_psm, target_height=cfg.ocr_letter_height,
                             env={"OMP_THREAD_LIMIT": "1"})
    by_line = {}
    for L in shape_letters:
        by_line.setdefault(L.line, []).append(L)
    out: List[Letter] = []
    for line in lines:
        fallback = by_line.get(line.index, [])
        try:
            reading = reader(line_image(page, line, cfg))
            aks = line_aksharas(reading.words)
        except (TesseractError, OSError, ValueError):
            aks = []
        letters = cut_line(page, line, aks, max(0, line.box[0] - cfg.line_margin_px), cfg) if aks else []
        if len(letters) < 0.5 * len(fallback):
            letters = fallback                         # Tesseract could not read this line
        out += letters
    return out

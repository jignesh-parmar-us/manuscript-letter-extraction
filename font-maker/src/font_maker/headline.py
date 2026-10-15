"""One even headline (F8): every glyph's headline (शिरोरेखा) at the same height and thickness.

Each akshara glyph is cut and averaged on its own (F2), so its headline sits a pixel or two higher or lower
and is a little thicker or thinner than its neighbour's, and in a word the line steps. Here:

  1. `find`: the headline of a glyph image: in the top half, the run of rows nearly as full as the fullest
     row (NEAR_PEAK of it, and at least MIN_FILL of the width); none when no row is that full.
  2. `font_headline`: the font's headline: the median top (against the baseline) and the median thickness
     over the glyphs that have one, each glyph once.
  3. `even`: the glyph's band is wiped and drawn again as a straight bar at the font's height and thickness,
     **only in the columns that are the bar** (ink in most of the band's rows, `bar_columns`): a gap in the
     headline is what tells भ from म, थ from प and ध from घ, so gaps and the strokes under them stay exactly as
     printed (the first version drew one bar across and turned भ into म, थ into प, ध into घ). An end of
     the bar within EDGE of the glyph's edge is drawn to the edge, so neighbours' bars touch (F3 measured a
     letter gap of 0 for book 6). Strokes that met the old band are drawn on to the new bar. Marks above the
     headline (े ं, the hook of ि) are kept where they are.

Images are glyph images (True = ink, glyphs.SCALE times the page size); heights in page pixels. The setting
`clean_headline` (on by default) and a per-glyph opt-out (`headline_off`) are in font.json. Only the headline
is evened; strokes keep their weight (decided 2026-10-16).
"""
from __future__ import annotations

from statistics import median
from typing import Dict, Iterable, Optional, Tuple

import numpy as np

VERSION = 3              # in the outline file names: raised when `even` changes, so outlines are traced again
MIN_FILL = 0.6           # of the glyph's width: a row this full is part of a headline
NEAR_PEAK = 0.85         # the band: the rows at least this share of its fullest row (book 6: thick headlines,
                         # and the strokes of थ भ ध reach into them, so "more than half full" took 27 px for थ)
COL_FILL = 0.6           # a column is part of the bar when it is ink in this share of the band's rows
TOP_PART = 0.5           # the headline is looked for in the top half of the glyph
EDGE = 0.12              # of the width: a bar ending this close to the edge is drawn to it


def find(img: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    """(y0, y1, x0, x1) of the headline band in the image (y1, x1 exclusive), or None."""
    h, w = img.shape
    if h < 4 or w < 4:
        return None
    fill = img[: max(2, int(h * TOP_PART))].mean(axis=1)
    best = int(np.argmax(fill))
    if fill[best] < MIN_FILL:
        return None
    edge = max(MIN_FILL, NEAR_PEAK * fill[best])
    y0 = best
    while y0 > 0 and fill[y0 - 1] >= edge:
        y0 -= 1
    y1 = best + 1
    while y1 < len(fill) and fill[y1] >= edge:
        y1 += 1
    cols = np.nonzero(bar_columns(img, y0, y1))[0]
    if not len(cols):
        return None
    return y0, y1, int(cols.min()), int(cols.max()) + 1


def bar_columns(img: np.ndarray, y0: int, y1: int) -> np.ndarray:
    """The columns that are the bar: ink in most of the band's rows. A gap (भ थ ध) and a letter's stroke
    reaching up into the band are not."""
    return img[y0:y1].mean(axis=0) >= COL_FILL


def font_headline(bands: Iterable[Tuple[float, float]]) -> Optional[Dict[str, float]]:
    """The font's headline from each glyph's (top, thickness) in page pixels: their medians."""
    bands = list(bands)
    if not bands:
        return None
    return {"top": round(median(b[0] for b in bands), 2), "thickness": round(median(b[1] for b in bands), 2),
            "glyphs": len(bands)}


def even(img: np.ndarray, glyph_top: float, target: Dict[str, float], scale: int) -> Tuple[np.ndarray, int]:
    """The image with its headline at the font's; and how many rows were added on top (when the bar moved
    above the image), so the caller can keep the glyph where it was."""
    band = find(img)
    if band is None:
        return img, 0
    y0, y1, x0, x1 = band
    h, w = img.shape
    t0 = int(round((target["top"] - glyph_top) * scale))        # the font's bar in this image's rows
    t1 = t0 + max(1, int(round(target["thickness"] * scale)))
    pad = max(0, -t0)
    out = np.zeros((h + pad + max(0, t1 - h), w), bool)
    out[pad:pad + h] = img
    y0, y1, t0, t1 = y0 + pad, y1 + pad, t0 + pad, t1 + pad
    cols = bar_columns(out, y0, y1)                                      # the bar only: gaps and strokes stay
    below = (out[y1] if y1 < out.shape[0] else np.zeros(w, bool)) & cols  # strokes leaving the bar downwards
    above = (out[y0 - 1] if y0 > 0 else np.zeros(w, bool)) & cols         # and upwards (marks joined to it)
    out[y0:y1, cols] = False
    if x0 <= w * EDGE and cols[x0]:
        cols[:x0] = True
    if x1 >= w * (1 - EDGE) and cols[x1 - 1]:
        cols[x1:] = True
    out[t0:t1, cols] = True
    for col in np.nonzero(below)[0]:                                    # join the strokes to the new bar
        out[min(t1, y1):max(t1, y1), col] = True
    for col in np.nonzero(above)[0]:
        out[min(y0, t0):max(y0, t0), col] = True
    return out, pad

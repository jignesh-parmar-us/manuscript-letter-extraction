"""Letters made from parts of other letters (printed books): a consonant with a vowel sign taken from
another letter of the same book that has it.

All work is on ink masks (True = ink), so paper and ink colour do not matter. The parts are lined up on
the headline (the busiest band of rows in the upper part of a letter):

- **above** (े ै ं ँ): the donor's ink above its headline, placed over the base at the same distance from
  the right edge of the letter body;
- **right** (ा ो ौ ी): the bar after the donor's letter (with any hook above the headline), placed after
  the base with the same gap; the headline is carried over the gap;
- **below** (ु ू): the donor's ink below the height of its consonant alone, hung under the base's foot
  where it joined the donor's.

`parts` keeps only the sign parts whose size (and gap) is near the typical one of all the donors, so a
donor cut badly or read wrongly gives nothing. The i sign (ि, written before its letter), ृ and the
halant (small marks that a few pixels off cut away) are not made.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

import cv2
import numpy as np

ABOVE = ("े", "ै", "ं", "ँ")
RIGHT = ("ा", "ो", "ौ", "ी")
BELOW = ("ु", "ू")
SIGNS = ABOVE + RIGHT + BELOW
OVERLAP = 3            # rows of the letter's foot kept with a sign below, so the two join
SPREAD = (0.6, 1.6)    # a sign part is typical if its size is within this share of the median


def place(sign: str) -> Optional[str]:
    return "above" if sign in ABOVE else "right" if sign in RIGHT else "below" if sign in BELOW else None


def _longest_runs(m: np.ndarray) -> np.ndarray:
    """Per row, the longest unbroken run of ink."""
    out = np.zeros(m.shape[0])
    for y, row in enumerate(m):
        if row.any():
            d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
            out[y] = (np.nonzero(d == -1)[0] - np.nonzero(d == 1)[0]).max()
    return out


def headline(m: np.ndarray) -> Tuple[int, int]:
    """Top and bottom row of the headline: the topmost band of rows in the upper 60 % of the mask whose
    longest unbroken run of ink is nearly as long as the longest. The headline is one long run; the middle
    bar of भ can be as long but lies lower, and signs above the headline (the two strokes of ै) are short."""
    prof = _longest_runs(m)
    upper = prof[:max(1, int(0.6 * len(prof)))]
    thr = 0.6 * upper.max()
    y0 = y1 = int(np.nonzero(upper >= thr)[0][0])
    while y1 + 1 < len(prof) and prof[y1 + 1] >= thr:
        y1 += 1
    return y0, y1


def body_right(m: np.ndarray, hy1: int) -> int:
    """Right edge of the ink below the headline."""
    cols = np.nonzero(m[hy1 + 1:].any(0))[0]
    return int(cols.max()) if cols.size else m.shape[1] - 1


def _bar_start(m: np.ndarray, hy1: int) -> Optional[int]:
    """First column of the bar at the right, below the headline, after a gap; None if there is none (the
    bar joined to the letter) or it is too wide for a bar."""
    cols = m[hy1 + 3:].any(0)
    xs = np.nonzero(cols)[0]
    if xs.size == 0:
        return None
    x = int(xs.max())
    while x > 0 and cols[x - 1]:
        x -= 1
    if not cols[:x].any() or m.shape[1] - x > 0.4 * m.shape[1]:
        return None
    return x


def _foot_x(m: np.ndarray, rows: slice) -> Optional[float]:
    """Centre of the rightmost run of ink in these rows (where a sign below joins the letter)."""
    cols = m[rows].any(0)
    xs = np.nonzero(cols)[0]
    if xs.size == 0:
        return None
    x1 = x0 = int(xs.max())
    while x0 > 0 and cols[x0 - 1]:
        x0 -= 1
    return (x0 + x1) / 2


@dataclass
class Part:
    """A vowel sign cut from a donor letter, in the donor's coordinates."""
    sign: str
    mask: np.ndarray        # the donor's size, True on the sign's ink
    anchor_x: float         # donor column the base's anchor column goes to (see `compose`)
    anchor_y: int           # donor row the base's anchor row goes to
    gap: int = 0            # right: columns between the letter body and the bar
    source: str = ""        # what it was cut from, for the record

    @property
    def size(self) -> Tuple[int, int, int]:
        ys, xs = np.nonzero(self.mask)
        return int(ys.size), int(np.ptp(xs)) + 1, int(np.ptp(ys)) + 1

    @property
    def pieces(self) -> int:
        """Separate pieces of ink (8-connected), not counting specks."""
        n, _, st, _ = cv2.connectedComponentsWithStats(self.mask.astype(np.uint8), connectivity=8)
        return int((st[1:, cv2.CC_STAT_AREA] >= 6).sum())


def cut(donor: np.ndarray, sign: str, letter_height: Optional[float] = None, source: str = "") -> Optional[Part]:
    """The sign's part of a donor letter (consonant + sign). `letter_height` (below only): the median
    height of the donor's consonant alone, from its headline top to its foot."""
    hy0, hy1 = headline(donor)
    where = place(sign)
    if where == "above":
        part = donor.copy()
        part[max(0, hy0 - 1):] = False
        if part.sum() < 15:
            return None
        return Part(sign, part, body_right(donor, hy1), hy0, source=source)
    if where == "right":
        bx = _bar_start(donor, hy1)
        if bx is None:
            return None
        part = np.zeros_like(donor)
        part[:, bx:] = donor[:, bx:]
        part[:max(0, hy0 - 1)] |= donor[:max(0, hy0 - 1)]        # the hook above the headline (ो ौ ी)
        left = np.nonzero(donor[hy1 + 3:, :bx].any(0))[0]
        right = int(left.max())
        return Part(sign, part, right, hy0, gap=bx - right, source=source)
    if where == "below":
        if not letter_height:
            return None
        y = int(round(hy0 + letter_height)) - OVERLAP
        if y <= hy1 or donor.shape[0] - y < OVERLAP + 4:
            return None
        part = np.zeros_like(donor)
        part[y:] = donor[y:]
        fx = _foot_x(donor, slice(y, y + OVERLAP))
        if part[y + OVERLAP:].sum() < 15 or fx is None:
            return None
        return Part(sign, part, fx, y, source=source)
    return None


def typical(parts: Iterable[Part]) -> List[Part]:
    """The parts with the most common number of pieces (a dot of ं left on a ी donor makes two) whose ink,
    width, height (and gap, for bars) are within `SPREAD` of the medians."""
    parts = list(parts)
    if len(parts) < 3:
        return parts
    pieces = np.array([p.pieces for p in parts])
    usual = np.bincount(pieces).argmax()
    sizes = np.array([p.size for p in parts], float)
    med = np.median(sizes[pieces == usual], axis=0)
    ok = (pieces == usual) & np.all((sizes >= SPREAD[0] * med) & (sizes <= SPREAD[1] * med), axis=1)
    if parts[0].sign in RIGHT:
        gaps = np.array([p.gap for p in parts], float)
        g = max(2.0, float(np.median(gaps)))
        ok &= (gaps >= 0) & (gaps <= 2.5 * g)
    return [p for p, k in zip(parts, ok) if k]


def typical_bases(masks: List[np.ndarray]) -> List[int]:
    """Indexes of the base letters whose width and height are within `SPREAD` of the medians (a piece or a
    wrong letter in the base's group would put the sign in the wrong place)."""
    if len(masks) < 3:
        return list(range(len(masks)))
    hw = np.array([m.shape for m in masks], float)
    med = np.median(hw, axis=0)
    ok = np.all((hw >= SPREAD[0] * med) & (hw <= SPREAD[1] * med), axis=1)
    return [i for i, k in enumerate(ok) if k]


def compose(base: np.ndarray, part: Part) -> Optional[np.ndarray]:
    """The base letter with the part put on it; None if the base has no place for it."""
    H, W = base.shape
    bhy0, bhy1 = headline(base)
    where = place(part.sign)
    if where == "below":
        fx = _foot_x(base, slice(H - OVERLAP, H))
        if fx is None:
            return None
        dx, dy = int(round(fx - part.anchor_x)), (H - OVERLAP) - part.anchor_y
    else:
        right = body_right(base, bhy1)
        dx, dy = int(round(right - part.anchor_x)), bhy0 - part.anchor_y
    ys, xs = np.nonzero(part.mask)
    ys, xs = ys + dy, xs + dx
    if where == "right" and abs(int(ys.max()) - (H - 1)) > 0.15 * H:
        return None                                      # a bar ends where its letter ends
    x0, y0 = min(0, int(xs.min())), min(0, int(ys.min()))
    x1, y1 = max(W, int(xs.max()) + 1), max(H, int(ys.max()) + 1)
    out = np.zeros((y1 - y0, x1 - x0), bool)
    out[-y0:-y0 + H, -x0:-x0 + W] = base
    out[ys - y0, xs - x0] = True
    if where == "right":                                 # carry the headline over the gap to the bar
        bar = xs[ys > bhy1 + 2]                          # the bar (the hook above may reach further left)
        if bar.size:
            out[bhy0 - y0:bhy1 + 1 - y0, right - x0:int(bar.min()) - x0 + 1] = True
    if out.sum() < base.sum() * 1.04:                    # the sign added (almost) nothing
        return None
    return out

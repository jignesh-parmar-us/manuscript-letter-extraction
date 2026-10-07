"""Vowel bars cut onto the wrong letter (printed books).

The aa sign (ा, in Gujarati ા) is a bar to the right of its letter: ना is न + bar. Both cutting methods
sometimes cut between the letter and its bar and join the bar to the next letter instead: नार comes
out as न + ार. `stray_bar` finds a letter that starts with such a bar, and `move_bars` gives the bar back
to the letter before it.

What must stay where it is: the i sign (ि), a bar written BEFORE its letter (रवि is र + ि-bar + व).
It has a hook above the headline that starts over the bar and arches over the letter, touching
the bar or not. So a bar with a wide mark above the headline starting over it is never moved; that
also leaves alone some real aa bars whose next letter has an e sign (तारे), which is the safe side.

A stray aa bar, in the sample's mask:
- the headline is the busiest row of the upper half (and the rows around it nearly as busy);
- the first ink below it is a tall stroke (ink in `bar_fill` of the rows below the headline), at
  most `bar_max_width` x the book's letter width, with no letter body to its left;
- then a gap (ink in at most `bar_gap_fill` of those rows) within `bar_max_width` letter widths,
  and a letter body after it (at least `bar_min_rest` letter widths of inked columns);
- no wide mark above the headline starting over the bar (the i hook);
- the letter before it ends close by (`bar_max_gap` letter widths) on the same line, and does not
  end with a bar itself (two bars in a row are not one letter and its aa).
Handwriting is left alone: its bars and the left strokes of letters look too much alike.
"""
from __future__ import annotations

from dataclasses import replace
from typing import List, Optional, Tuple

import cv2
import numpy as np

from .config import Config

AA = "\u093E"   # ा


def _headline(mask: np.ndarray) -> Tuple[int, int]:
    """First and last row of the headline: the busiest row of the upper half and the rows next to it
    with at least half as much ink."""
    h = mask.shape[0]
    rows = mask.sum(axis=1)
    head = int(np.argmax(rows[: max(1, h // 2)]))
    top = bot = head
    while top > 0 and rows[top - 1] >= 0.5 * rows[head]:
        top -= 1
    while bot + 1 < h and rows[bot + 1] >= 0.5 * rows[head]:
        bot += 1
    return top, bot


def _bar_run(frac: np.ndarray, cols, fill: float) -> Optional[Tuple[int, int]]:
    """The first run of columns (in the order of `cols`) with ink in at least `fill` of the rows."""
    start = next((c for c in cols if frac[c] >= fill), None)
    if start is None:
        return None
    end = start
    step = 1 if cols.step is None or cols.step > 0 else -1
    while 0 <= end + step < frac.size and frac[end + step] >= fill:
        end += step
    return (start, end + 1) if step > 0 else (end, start + 1)


def stray_bar(mask: np.ndarray, width: float, cfg: Config) -> Optional[int]:
    """The column where a stray aa bar at the start of this letter ends (the gap after it), or None."""
    h, w = mask.shape
    top, bot = _headline(mask)
    body = mask[bot + 1:]
    if body.shape[0] < 5 or w < 3:
        return None
    frac = body.mean(axis=0)
    reach = max(3, int(cfg.bar_max_width * width))
    run = _bar_run(frac, range(min(w, reach)), cfg.bar_fill)
    if run is None:
        return None
    start, end = run
    if end - start > cfg.bar_max_width * width:
        return None
    if body[:, :start].sum() > 0.1 * body.shape[0]:           # a letter body left of the bar
        return None
    gap = next((c for c in range(end, min(w, end + reach)) if frac[c] <= cfg.bar_gap_fill), None)
    if gap is None or (body[:, gap:].sum(axis=0) > 0).sum() < cfg.bar_min_rest * width:
        return None
    above = mask[:max(0, top - 1)].astype(np.uint8)            # the i hook: a wide mark starting over the bar
    if above.any():
        n, _, stats, _ = cv2.connectedComponentsWithStats(above, connectivity=8)
        for k in range(1, n):
            x0, _, ww, _, area = stats[k]
            if x0 <= end + 0.15 * width and ww >= 0.4 * width and area >= cfg.mark_min_px:
                return None
    return gap


def ends_with_bar(mask: np.ndarray, width: float, cfg: Config) -> bool:
    """The letter ends with a bar of its own (its aa, o, ii...): a tall stroke at its right end with a gap
    before it and a letter body before that."""
    h, w = mask.shape
    _, bot = _headline(mask)
    body = mask[bot + 1:]
    if body.shape[0] < 5 or w < 3:
        return False
    frac = body.mean(axis=0)
    last = int(np.flatnonzero(frac > 0)[-1]) if (frac > 0).any() else -1
    if last < 0:
        return False
    reach = max(3, int(cfg.bar_max_width * width))
    run = _bar_run(frac, range(last, max(-1, last - reach), -1), cfg.bar_fill)
    if run is None or run[1] - run[0] > cfg.bar_max_width * width:
        return False
    # a bar of its own stands apart from the letter's body (ना); the stem of न or त does not
    gap = next((c for c in range(run[0] - 1, max(-1, run[0] - 1 - reach), -1) if frac[c] <= cfg.bar_gap_fill), None)
    return gap is not None and bool((frac[:gap] > 0).any())


def split_bar(mask: np.ndarray, gap: int) -> Tuple[np.ndarray, np.ndarray]:
    """The bar (columns before `gap`) and the rest. Marks above the headline that start on the bar's
    side (the bar's own top) go with the bar, other marks above or below the main zone whole to the
    side their centre is on, so a mark is never cut in two."""
    top, bot = _headline(mask)
    bar = np.zeros_like(mask)
    bar[:, :gap] = mask[:, :gap]
    marks = mask.copy()
    marks[top:bot + 1] = False                                 # the headline joins everything: leave it out
    n, lab, stats, cents = cv2.connectedComponentsWithStats(marks.astype(np.uint8), connectivity=8)
    for k in range(1, n):
        y0, hh = stats[k, 1], stats[k, 3]
        if y0 + hh <= top:                                     # wholly above the headline
            bar[lab == k] = stats[k, 0] < gap
        elif y0 > bot + 0.75 * (mask.shape[0] - bot):          # low below it
            bar[lab == k] = cents[k][0] < gap
    return bar, mask & ~bar


def _tight(mask: np.ndarray, x: int, y: int) -> Optional[Tuple[Tuple[int, int, int, int], np.ndarray]]:
    rows, cols = np.flatnonzero(mask.any(axis=1)), np.flatnonzero(mask.any(axis=0))
    if rows.size == 0:
        return None
    m = mask[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]
    return (x + int(cols[0]), y + int(rows[0]), m.shape[1], m.shape[0]), m


def joined(a_box, a_mask, b_box, b_mask):
    """Two masks in page coordinates as one (box, mask), trimmed to the ink."""
    x0, y0 = min(a_box[0], b_box[0]), min(a_box[1], b_box[1])
    x1 = max(a_box[0] + a_box[2], b_box[0] + b_box[2])
    y1 = max(a_box[1] + a_box[3], b_box[1] + b_box[3])
    m = np.zeros((y1 - y0, x1 - x0), bool)
    for (bx, by, bw, bh), mm in ((a_box, a_mask), (b_box, b_mask)):
        m[by - y0:by - y0 + bh, bx - x0:bx - x0 + bw] |= mm
    return _tight(m, x0, y0)


def plan_pair(prev_box, prev_mask, box, mask, width: float, cfg: Config):
    """For a letter and the one before it on the line: the two new (box, mask) pairs when the letter
    starts with the stray aa bar of the one before, else None."""
    if box[0] - (prev_box[0] + prev_box[2]) > cfg.bar_max_gap * width:
        return None
    gap = stray_bar(mask, width, cfg)
    if gap is None or ends_with_bar(prev_mask, width, cfg):
        return None
    bar, rest = split_bar(mask, gap)
    left = joined(prev_box, prev_mask, box, bar)
    right = _tight(rest, box[0], box[1])
    if left is None or right is None:
        return None
    return left, right


def move_bars(letters, cfg: Config):
    """Capture (printed books): give each stray aa bar back to the letter before it on its line."""
    lets = [x for x in letters if x.kind == "letter"]
    if len(lets) < 2:
        return letters
    width = float(np.median([x.box[2] for x in lets]))
    out: List = []
    for x in sorted(letters, key=lambda x: (x.line, x.pos)):
        prev = out[-1] if out else None
        if prev is not None and prev.kind == x.kind == "letter" and prev.line == x.line:
            found = plan_pair(prev.box, prev.mask, x.box, x.mask, width, cfg)
            if found is not None:
                (lbox, lmask), (rbox, rmask) = found
                # Tesseract's texts (cut by its reading): the aa goes along if it was read with the bar
                ptext, text = (prev.text + AA, x.text[1:]) if x.text.startswith(AA) else ("", "")
                out[-1] = replace(prev, box=lbox, mask=lmask, rules=prev.rules + ["aa-bar-back"], text=ptext)
                x = replace(x, box=rbox, mask=rmask, rules=x.rules + ["aa-bar-given"], text=text)
        out.append(x)
    return out

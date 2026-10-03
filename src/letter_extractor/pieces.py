"""First cut (FR-4): split each line into stroke pieces at the breaks in its headline.

The headline is drawn letter by letter. Between two letters there is either a gap or, where the
strokes overlap, a sharp thinning of the headline (on these pages the red headlines are nearly
continuous, but thin out to 1-3 px at every join). So a break is a run of columns where the
headline is thinner than `break_soft_frac` of the line's typical headline thickness (measured in a
band around the traced headline) and somewhere thinner than `break_max_frac`. Runs narrower than
`min_break_px` are ignored (pen texture), as are specks with less ink than `min_piece_ink_px`.

Inside a break the cut goes through every empty column run of the main zone, otherwise through
the column with the least ink. So a danda or digit standing in a gap becomes a piece of its own.

Each piece takes the line's ink in its columns, from just above the headline to the bottom of the
main zone. Ink above or below that (upper and lower matras) is left for the join rules (C3b).
Pieces are not classified here: each one records the width of its headline ink and of its stems,
which the join rules use to tell dandas (headline no wider than the stroke) from vowel bars and
letters.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import cv2
import numpy as np

from .config import Config, InkParams
from .lines import Line, LineLayout
from .prepare import PreparedPage

Box = Tuple[int, int, int, int]


@dataclass
class Piece:
    line: int                         # line number (1-based)
    index: int                        # 1-based, left to right within the line
    x0: int                           # columns [x0, x1) between two cuts (page coordinates)
    x1: int
    box: Box                          # bounding box of the piece's ink (page coordinates)
    mask: np.ndarray                  # bool, inside `box`: the piece's ink
    ink_px: int
    ink: str                          # "black" | "red" (majority of its pixels)
    head_width: int                   # widest run of ink columns in the headline band (0 = none)
    stem_width: float                 # median width of the ink rows in the lower main zone


def _runs(flags: np.ndarray) -> List[Tuple[int, int]]:
    """[start, end) runs of True."""
    padded = np.concatenate([[False], flags, [False]])
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return list(zip(edges[::2], edges[1::2]))


def _params(cfg: Config, red: bool) -> InkParams:
    return cfg.red if red else cfg.black


def zones(line: Line, layout: LineLayout, cfg: Config):
    """Line-local masks: the headline band, and the piece zone (headline top to main zone bottom)."""
    x, y, w, h = line.box
    hy = line.headline_y[x:x + w] - y
    rows = np.arange(h, dtype=np.float32)[:, None]
    d = rows - hy[None, :]
    band = (d >= -cfg.headline_above_px) & (d <= cfg.headline_below_px)
    top = cfg.piece_top_frac * layout.spacing
    zone = (rows >= hy[None, :] - top) & (rows <= hy[None, :] + layout.main_zone)
    return band, zone


def find_cuts(thickness: np.ndarray, col_ink: np.ndarray, col_red: np.ndarray, cfg: Config) -> List[int]:
    """Cut columns (line-local) from the headline thickness and the main-zone ink per column."""
    w = thickness.size
    inked = thickness[thickness > 0]
    typical = float(np.median(inked)) if inked.size else 0.0
    # hysteresis: a break is a run of thin headline (soft limit) that gets really thin (hard limit)
    # somewhere; a join is often only 1 px at its thinnest but a few px wide at the soft limit
    hard = np.where(col_red, cfg.red.break_max_frac, cfg.black.break_max_frac) * typical
    soft = np.where(col_red, cfg.red.break_soft_frac, cfg.black.break_soft_frac) * typical
    cuts: List[int] = []
    for a, b in _runs(thickness <= soft):
        if not (thickness[a:b] <= hard[a:b]).any():
            continue
        # ink colour of the headline on either side decides the minimum break width
        side = np.r_[col_red[max(0, a - 4):a], col_red[b:b + 4]]
        params = _params(cfg, side.size > 0 and side.mean() > 0.5)
        if a > 0 and b < w and b - a < params.min_break_px:
            continue
        inner = col_ink[a:b]
        empty = _runs(inner == 0)
        if empty:
            cuts.extend(a + (s + e) // 2 for s, e in empty)
        else:
            low = np.flatnonzero(inner == inner.min())
            cuts.append(a + int(np.median(low)))
    return sorted(set(c for c in cuts if 0 < c < w))


def split_line(page: PreparedPage, line: Line, layout: LineLayout, cfg: Config) -> Tuple[List[Piece], int]:
    """Stroke pieces of one line, left to right, and the number of specks dropped."""
    x, y, w, h = line.box
    band, zone = zones(line, layout, cfg)
    red = page.red[y:y + h, x:x + w] & line.mask
    body = line.mask & zone
    thickness = (line.mask & band).sum(axis=0)
    head_cols = thickness > 0
    lower = zone & ~band & (np.arange(h)[:, None] > line.headline_y[x:x + w][None, :] - y)
    col_ink = body.sum(axis=0)
    col_red = (red & band).sum(axis=0) > (line.mask & ~red & band).sum(axis=0)
    cuts = [0, *find_cuts(thickness, col_ink, col_red, cfg), w]

    pieces: List[Piece] = []
    specks = 0
    for s, e in zip(cuts[:-1], cuts[1:]):
        m = body[:, s:e]
        n = int(m.sum())
        if n == 0:
            continue
        n_red = int((red[:, s:e] & m).sum())
        is_red = n_red * 2 > n
        if n < _params(cfg, is_red).min_piece_ink_px:
            specks += 1
            continue
        ys, xs = np.nonzero(m)
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        head_runs = _runs(head_cols[s:e])
        row_w = (m & lower[:, s:e]).sum(axis=1)
        pieces.append(Piece(line=line.index, index=len(pieces) + 1, x0=int(x + s), x1=int(x + e),
                            box=(int(x + s + x0), int(y + y0), int(x1 - x0), int(y1 - y0)),
                            mask=m[y0:y1, x0:x1].copy(), ink_px=n, ink="red" if is_red else "black",
                            head_width=max((b - a for a, b in head_runs), default=0),
                            stem_width=float(np.median(row_w[row_w > 0])) if (row_w > 0).any() else 0.0))
    return pieces, specks


def split_lines(page: PreparedPage, layout: LineLayout, cfg: Config) -> Tuple[List[Piece], int]:
    pieces: List[Piece] = []
    specks = 0
    for line in layout.lines:
        p, s = split_line(page, line, layout, cfg)
        pieces.extend(p)
        specks += s
    return pieces, specks


def pieces_overlay(page: PreparedPage, layout: LineLayout, pieces: List[Piece], cfg: Config) -> np.ndarray:
    """Debug view: pieces in alternating colours, ink outside the piece zone (upper and lower marks)
    in light purple, a thin red line at every cut, piece numbers above."""
    out = (0.25 * page.rgb.astype(np.float32) + 0.75 * 245).astype(np.uint8)
    colours = [(0, 90, 200), (0, 150, 60), (200, 120, 0)]
    for line in layout.lines:
        x, y, w, h = line.box
        region = out[y:y + h, x:x + w]
        region[line.mask] = (190, 160, 220)
    by_line = {}
    for p in pieces:
        by_line.setdefault(p.line, []).append(p)
    for line in layout.lines:
        top = int(line.headline_y[line.box[0]] - cfg.piece_top_frac * layout.spacing)
        for k, p in enumerate(by_line.get(line.index, [])):
            x, y, w, h = p.box
            out[y:y + h, x:x + w][p.mask] = colours[k % 3]
            cv2.putText(out, str(p.index), (x, top - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (60, 60, 60), 1)
        for p in by_line.get(line.index, [])[1:]:
            hy = int(line.headline_y[p.x0])
            cv2.line(out, (p.x0, int(hy - cfg.piece_top_frac * layout.spacing)),
                     (p.x0, int(hy + layout.main_zone)), (230, 0, 0), 1)
    return out

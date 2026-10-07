"""Line detection (FR-3): find every text line, trace its headline, give every ink blob to a line.

1. Only horizontal runs of ink are used to find headlines (stems, dandas and matras drop out). Their
   row profile has one strong peak per line: the headline. Line spacing comes from the profile's
   autocorrelation (or the config), and peaks closer than ~0.6 spacing are merged.
2. Each headline is traced in column windows, from its strongest window outward, each window
   searched near the one before it, so slope (a page scanned at a slant) and waves are followed to
   the line's ends. Two traces that end on the same headline are one line.
3. Between two headlines the boundary runs along the emptiest rows below the main zone.
4. Ink blobs are assigned whole: a blob touching one headline belongs to that line; a blob touching
   two headlines (touching matras of two lines) is split at the boundary; a detached blob (anusvara,
   dots, a loose matra) goes to the nearer of "just above the headline below" (upper mark) and
   "just below the main zone above" (lower mark).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np

from .config import Config
from .prepare import PreparedPage

Box = Tuple[int, int, int, int]


@dataclass
class Line:
    index: int                        # 1-based, top to bottom
    box: Box                          # x, y, w, h of the line's ink (page coordinates)
    mask: np.ndarray                  # bool (h x w): ink of this line only, inside `box`
    headline_y: np.ndarray            # headline row for every page column (follows slope and waves)
    ink: str                          # "black" | "red" | "mixed"
    red_px: int = 0
    black_px: int = 0

    @property
    def top(self) -> int:
        return self.box[1]

    @property
    def bottom(self) -> int:
        return self.box[1] + self.box[3]


@dataclass
class LineLayout:
    lines: List[Line]
    spacing: float                    # line pitch used (px)
    main_zone: float                  # headline to bottom of the main zone (px)
    boundaries: List[np.ndarray]      # boundary row for every page column, between line i and i+1


def _smooth(v: np.ndarray, k: int) -> np.ndarray:
    k = max(1, int(k))
    return np.convolve(v.astype(np.float32), np.ones(k, np.float32) / k, mode="same")


def horizontal_runs(ink: np.ndarray, cfg: Config) -> np.ndarray:
    """Ink that is part of a horizontal run at least `headline_min_run_px` long."""
    k = max(1, cfg.headline_min_run_px)
    return cv2.morphologyEx(ink.astype(np.uint8), cv2.MORPH_OPEN, np.ones((1, k), np.uint8)) > 0


def estimate_spacing(profile: np.ndarray, cfg: Config) -> float:
    """Line pitch from the autocorrelation of the row profile."""
    if cfg.line_spacing_px > 0:
        return float(cfg.line_spacing_px)
    a = _smooth(profile, 5)
    a = a - a.mean()
    ac = np.correlate(a, a, mode="full")[a.size - 1:]
    lo, hi = cfg.line_min_spacing_px, min(cfg.line_max_spacing_px, ac.size - 1)
    if hi <= lo:
        return float(cfg.line_min_spacing_px)
    return float(lo + np.argmax(ac[lo:hi]))


def find_headline_rows(profile: np.ndarray, spacing: float, cfg: Config) -> List[int]:
    """Headline rows: local maxima of the row profile, strongest first, at least ~0.6 spacing apart."""
    s = _smooth(profile, 5)
    if s.size < 3 or s.max() <= 0:
        return []
    is_max = (s[1:-1] >= s[:-2]) & (s[1:-1] > s[2:])
    cands = np.flatnonzero(is_max) + 1
    chosen: List[int] = []
    for i in cands[np.argsort(-s[cands])]:
        if all(abs(i - j) > cfg.line_min_gap_frac * spacing for j in chosen):
            chosen.append(int(i))
    if not chosen:
        return []
    ref = np.median(sorted((s[i] for i in chosen), reverse=True)[:max(3, len(chosen) // 2)])
    return sorted(i for i in chosen if s[i] >= cfg.line_peak_frac * ref)


def _window_row(runs: np.ndarray, x0: int, x1: int, centre: float, reach: int,
                cfg: Config) -> Optional[Tuple[float, float]]:
    """The headline row in columns x0..x1 within `reach` of `centre`, and its strength; None when the
    window has no clear headline (a gap, dandas) or its strongest row is the edge of the search,
    which means the headline lies beyond it."""
    h = runs.shape[0]
    c = int(round(centre))
    y0, y1 = max(0, c - reach), min(h, c + reach + 1)
    prof = _smooth(runs[y0:y1, x0:x1].sum(axis=1), 3)
    if prof.size == 0 or prof.max() < cfg.headline_min_ink_frac * (x1 - x0):
        return None
    i = int(np.argmax(prof))
    if (i == 0 and y0 > 0) or (i == prof.size - 1 and y1 < h):
        return None
    return y0 + float(i), float(prof[i])


def trace_headline(runs: np.ndarray, row: int, spacing: float, cfg: Config) -> np.ndarray:
    """Headline row for every column of `runs` (horizontal ink runs, block coordinates). The search
    starts at the window with the strongest headline near `row` and follows the headline from window
    to window in both directions, so a sloping line (a page scanned at a slant) is followed to its
    ends even where it is far from `row`. Windows without a clear headline (gaps, dandas) are
    interpolated."""
    h, w = runs.shape
    win = max(10, cfg.headline_window_px)
    reach = int(cfg.headline_search_frac * spacing)
    windows = []
    for x0 in range(0, w, win // 2):                          # half-overlapping windows
        x1 = min(w, x0 + win)
        windows.append((x0, x1))
        if x1 == w:
            break
    near = [_window_row(runs, x0, x1, row, reach, cfg) for x0, x1 in windows]
    if not any(near):
        return np.full(w, float(row), np.float32)
    start = max((i for i, r in enumerate(near) if r), key=lambda i: near[i][1])
    found = {start: near[start][0]}
    for step in (1, -1):                                      # right, then left of the start
        last = found[start]
        i = start + step
        while 0 <= i < len(windows):
            r = _window_row(runs, *windows[i], last, reach, cfg)
            if r:
                found[i] = last = r[0]
            i += step
    order = sorted(found)
    centres = [(windows[i][0] + windows[i][1]) / 2 for i in order]
    cx, ys = np.array(centres, np.float64), np.array([found[i] for i in order], np.float64)
    # A headline bends only gently, so a window far from a smooth curve through all windows has
    # locked onto something else (dandas, a run of big matras, a letter's bottom stroke).
    if ys.size >= 3:
        wave = cfg.headline_max_wave_frac * spacing
        deg = 2 if ys.size >= 6 else 1
        keep = np.ones(ys.size, bool)
        for _ in range(3):
            fit = np.polyval(np.polyfit(cx[keep], ys[keep], deg), cx)
            new_keep = np.abs(ys - fit) <= wave
            if new_keep.sum() <= deg or (new_keep == keep).all():
                break
            keep = new_keep
        ys = np.where(np.abs(ys - fit) <= wave, ys, fit)
    return np.interp(np.arange(w), cx, ys).astype(np.float32)


def estimate_main_zone(ink: np.ndarray, heads: List[np.ndarray], spacing: float, cfg: Config) -> float:
    """Distance from the headline to the bottom of the main zone: where the ink below the headlines
    (aligned on the traced headline) drops to a small share of the letter-body ink."""
    h, w = ink.shape
    depth = int(spacing)
    cols = np.arange(w)
    rows = np.zeros(depth, np.float64)
    for hy in heads:
        base = np.round(hy).astype(int)
        for d in range(depth):
            r = base + d
            ok = r < h
            rows[d] += ink[r[ok], cols[ok]].sum()
    body = rows[int(0.1 * depth):int(0.4 * depth)].mean()
    if body <= 0:
        return cfg.main_zone_frac * spacing
    low = np.flatnonzero(rows[int(0.3 * depth):] < cfg.main_zone_drop * body)
    return float(int(0.3 * depth) + low[0]) if low.size else cfg.main_zone_frac * spacing


def find_boundary(ink: np.ndarray, upper: np.ndarray, lower: np.ndarray, main_zone: float,
                  cfg: Config) -> np.ndarray:
    """Row between two lines for every column: the emptiest row between the main zone of the upper
    line and the headline of the lower line, per window, then interpolated."""
    h, w = ink.shape
    win = max(10, cfg.headline_window_px)
    centres, ys = [], []
    for x0 in range(0, w, win // 2):
        x1 = min(w, x0 + win)
        c = (x0 + x1) // 2
        a = int(round(upper[c] + 0.8 * main_zone))
        b = int(round(lower[c] - 0.1 * (lower[c] - upper[c])))
        a, b = max(0, min(a, h - 1)), max(0, min(b, h))
        if b - a < 2:
            y = (upper[c] + lower[c]) / 2
        else:
            prof = _smooth(ink[a:b, x0:x1].sum(axis=1), 5)
            quiet = np.flatnonzero(prof <= prof.min() + 0.5)  # middle of the emptiest run of rows
            y = a + float(np.median(quiet))
        centres.append(c)
        ys.append(y)
        if x1 == w:
            break
    return np.interp(np.arange(w), centres, ys).astype(np.float32)


def assign_ink(ink: np.ndarray, heads: List[np.ndarray], bounds: List[np.ndarray], main_zone: float,
               cfg: Config) -> np.ndarray:
    """Line number (1-based) for every ink pixel of `ink` (block coordinates), 0 for no ink."""
    h, w = ink.shape
    n = len(heads)
    yy = np.arange(h, dtype=np.float32)[:, None]
    band = np.ones((h, w), np.int32)                          # line by position alone
    for b in bounds:
        band += (yy >= b[None, :]).astype(np.int32)
    head_map = np.zeros((h, w), np.int32)                     # pixels on a headline
    tol = cfg.headline_tol_px
    for i, hy in enumerate(heads, 1):
        head_map[np.abs(yy - hy[None, :]) <= tol] = i

    count, labels = cv2.connectedComponents(ink.astype(np.uint8), connectivity=8)
    out = np.zeros((h, w), np.int32)
    on = labels > 0
    comp, line_px = labels[on], band[on]
    # which headlines each component touches
    touch = np.zeros((count, n + 1), bool)
    hm = head_map[on]
    touch[comp[hm > 0], hm[hm > 0]] = True
    touch = touch[:, 1:]
    n_touch = touch.sum(axis=1)

    result = np.zeros(comp.size, np.int32)
    one = n_touch[comp] == 1
    result[one] = np.argmax(touch, axis=1)[comp[one]] + 1
    many = n_touch[comp] >= 2
    result[many] = line_px[many]                              # two lines' letters touching: split
    loose = ~(one | many)
    if loose.any():
        ys, xs = np.nonzero(on)
        ys, xs = ys[loose], xs[loose]
        lc = comp[loose]
        top = np.full(count, h, np.int64)
        bot = np.zeros(count, np.int64)
        np.minimum.at(top, lc, ys)
        np.maximum.at(bot, lc, ys)
        cx_sum = np.zeros(count)
        cnt = np.zeros(count)
        np.add.at(cx_sum, lc, xs)
        np.add.at(cnt, lc, 1)
        line_of = {}
        for c in np.unique(lc):
            cx = int(round(cx_sum[c] / cnt[c]))
            heads_at = np.array([hy[cx] for hy in heads])
            below = np.flatnonzero(heads_at > bot[c])         # headlines under the blob
            above = np.flatnonzero(heads_at <= bot[c])
            if below.size == 0:
                line_of[c] = n
            elif above.size == 0:
                line_of[c] = 1
            else:
                j_below, j_above = below[0], above[-1]
                d_up_mark = heads_at[j_below] - bot[c]                    # gap to the headline below
                d_low_mark = top[c] - (heads_at[j_above] + main_zone)     # gap below the main zone above
                line_of[c] = (j_below if d_up_mark < max(0.0, d_low_mark) else j_above) + 1
        result[loose] = np.array([line_of[c] for c in lc], np.int32)
    out[on] = result
    return out


def detect_lines(page: PreparedPage, cfg: Config) -> Optional[LineLayout]:
    if page.block is None:
        return None
    bx, by, bw, bh = page.block
    ink = page.ink[by:by + bh, bx:bx + bw]
    red = page.red[by:by + bh, bx:bx + bw]
    runs = horizontal_runs(ink, cfg)
    profile = runs.sum(axis=1)
    spacing = estimate_spacing(profile, cfg)
    rows = find_headline_rows(profile, spacing, cfg)
    if not rows:
        return None
    heads = [trace_headline(runs, r, spacing, cfg) for r in rows]
    # on a slanted page one line can give two peaks in the row profile; followed along the line both
    # traces end on the same headline: keep one
    heads.sort(key=lambda hy: float(np.median(hy)))
    unique: List[np.ndarray] = []
    for hy in heads:
        if unique and float(np.median(np.abs(hy - unique[-1]))) < cfg.line_min_gap_frac * spacing:
            continue
        unique.append(hy)
    heads = unique
    main_zone = estimate_main_zone(ink, heads, spacing, cfg)
    bounds = [find_boundary(ink, heads[i], heads[i + 1], main_zone, cfg) for i in range(len(heads) - 1)]
    owner = assign_ink(ink, heads, bounds, main_zone, cfg)

    W = page.ink.shape[1]
    lines: List[Line] = []
    for i, hy in enumerate(heads, 1):
        m = owner == i
        if not m.any():
            continue
        ys, xs = np.nonzero(m)
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        mask = m[y0:y1, x0:x1]
        red_px = int((red[y0:y1, x0:x1] & mask).sum())
        black_px = int(mask.sum()) - red_px
        share = red_px / max(1, red_px + black_px)
        kind = "red" if share >= cfg.line_red_share else "black" if share <= 1 - cfg.line_red_share else "mixed"
        full = np.empty(W, np.float32)                        # headline in page coordinates
        full[:bx] = hy[0]
        full[bx:bx + bw] = hy
        full[bx + bw:] = hy[-1]
        lines.append(Line(index=len(lines) + 1, box=(int(bx + x0), int(by + y0), int(x1 - x0), int(y1 - y0)),
                          mask=mask, headline_y=full + by, ink=kind, red_px=red_px, black_px=black_px))
    page_bounds = []
    for b in bounds:
        full = np.empty(W, np.float32)
        full[:bx], full[bx:bx + bw], full[bx + bw:] = b[0], b, b[-1]
        page_bounds.append(full + by)
    return LineLayout(lines=lines, spacing=spacing, main_zone=main_zone, boundaries=page_bounds)


def line_image(page: PreparedPage, line: Line, cfg: Config) -> np.ndarray:
    """Crop of one line from the original page with a small margin. Ink of other lines inside the
    crop is filled in from the paper around it, so only this line's ink is left."""
    H, W = page.ink.shape
    x, y, w, h = line.box
    m = cfg.line_margin_px
    x0, y0, x1, y1 = max(0, x - m), max(0, y - m), min(W, x + w + m), min(H, y + h + m)
    crop = page.rgb[y0:y1, x0:x1].copy()
    own = np.zeros((y1 - y0, x1 - x0), bool)
    own[y - y0:y - y0 + h, x - x0:x - x0 + w] = line.mask
    other = page.ink[y0:y1, x0:x1] & ~own
    if other.any():
        # grow the foreign ink over its faint anti-aliased edge, but never over this line's ink
        g = 2 * cfg.line_erase_grow_px + 1
        near = cv2.dilate(other.astype(np.uint8), np.ones((g, g), np.uint8)) > 0
        near &= ~(cv2.dilate(own.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0)
        crop = cv2.inpaint(crop, near.astype(np.uint8), 5, cv2.INPAINT_TELEA)
    return crop


_COLOURS = [(230, 25, 75), (60, 180, 75), (0, 130, 200), (245, 130, 48), (145, 30, 180),
            (70, 160, 160), (240, 50, 230), (128, 128, 0), (0, 0, 128), (170, 110, 40)]


def lines_overlay(page: PreparedPage, layout: Optional[LineLayout]) -> np.ndarray:
    """Debug view: each line's ink in its own colour (so wrongly assigned matras stand out), traced
    headlines as thin dark lines, boundaries between lines dashed grey, line numbers on the left."""
    H, W = page.ink.shape
    out = (0.25 * page.rgb.astype(np.float32) + 0.75 * 245).astype(np.uint8)
    if layout is None:
        return out
    bx, by, bw, bh = page.block
    xs = np.arange(bx, bx + bw)
    for line in layout.lines:
        c = _COLOURS[(line.index - 1) % len(_COLOURS)]
        x, y, w, h = line.box
        region = out[y:y + h, x:x + w]
        region[line.mask] = c
        pts = np.stack([xs, line.headline_y[xs]], axis=1).astype(np.int32)
        cv2.polylines(out, [pts], False, (20, 20, 20), 1)
        cv2.putText(out, f"L{line.index:02d}", (max(0, bx - 110), int(line.headline_y[bx]) + 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, c, 2)
    for b in layout.boundaries:
        for x0 in range(bx, bx + bw - 10, 20):
            pts = np.stack([np.arange(x0, x0 + 10), b[x0:x0 + 10]], axis=1).astype(np.int32)
            cv2.polylines(out, [pts], False, (120, 120, 120), 1)
    return out

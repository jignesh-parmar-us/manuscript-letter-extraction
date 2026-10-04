"""Join and split rules (FR-5) and letter samples (FR-6): from stroke pieces to letters.

Each line is handled as a label image: every ink pixel of the line carries the number of the
letter it belongs to. Pieces start as their own labels, the rules relabel them, and the ink that is
not in any piece (upper and lower marks, specks) is attached last.

Rules, in order:
1. Narrow pieces (narrower than `min_letter_width_ratio` x the line's typical piece width) are sorted out:
   - a tall, continuous stroke with an upper mark touching it is an i-matra bar: if the mark leans
     right it is the short-i hook (written before its consonant) and joins the piece on its RIGHT,
     otherwise it is long-i and joins LEFT;
   - a tall stroke whose headline runs through the cut into its left neighbour (ink on both sides
     of the cut), or whose headline is clearly wider than its stem, is a vowel bar (aa, o, au) and
     joins LEFT;
   - any other tall stroke stands in empty columns with a headline no wider than itself: a danda;
     two dandas next to each other are one double danda;
   - anything else (broken strokes, visarga dots) joins the neighbour it touches most across the
     cut, or the left one if it touches neither.
2. A short-i stem whose headline touches the letter before it has no break and sits at the right end
   of that letter; its curl rising from there and arching over the next letter moves it across.
   Then letters wider than `split_width_ratio` x the page's typical letter width may hold letters
   whose headlines touch: they are cut into round(width / typical) parts, each cut at the column with
   the least ink below the headline near its expected place, but only where that column is nearly
   empty (a wide single letter is solid there), unless wider than `split_force_ratio` x typical.
3. Marks above and below the main zone, and specks, go to the letter they touch most, otherwise
   to the letter they overlap most horizontally, otherwise to the nearest one.
4. Up to two short letters between two dandas are a verse number: kind "digit".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import cv2
import numpy as np

from .config import Config
from .lines import Line, LineLayout
from .pieces import Piece, zones
from .prepare import PreparedPage

Box = Tuple[int, int, int, int]


@dataclass
class Letter:
    line: int                         # line number (1-based)
    pos: int                          # 1-based, reading order within the line
    box: Box                          # x, y, w, h (page coordinates)
    mask: np.ndarray                  # bool, inside `box`: this letter's ink only
    ink: str                          # "black" | "red"
    kind: str                         # "letter" | "danda" | "digit"
    pieces: int                       # stroke pieces joined into it
    rules: List[str] = field(default_factory=list)   # rules applied (for tuning)


@dataclass
class _Group:
    x0: int                           # line-local column span of the group's piece ink
    x1: int
    pieces: int = 1
    kind: str = "letter"
    rules: List[str] = field(default_factory=list)
    keep_until: int = -1              # a short-i stem ends here: never split at or left of it
    protect: List[Tuple[int, int]] = field(default_factory=list)   # joined bars: never split inside


def _contact(body: np.ndarray, col: int) -> int:
    """Rows where ink crosses the boundary between column col-1 and col (line-local)."""
    if col <= 0 or col >= body.shape[1]:
        return 0
    a, b = body[:, col - 1], body[:, col]
    near = b | np.r_[b[1:], False] | np.r_[False, b[:-1]]
    return int((a & near).sum())


def _is_tall_stroke(mask: np.ndarray, zone_h: float, cfg: Config) -> bool:
    """A vertical stroke through most of the main zone (bar, danda): ink in nearly every row and
    about equally wide all the way down. The two dots of a visarga often almost touch, but pinch to
    a narrow waist between them."""
    rows = mask.any(axis=1)
    if rows.size < cfg.stroke_min_height_frac * zone_h or rows.mean() < cfg.stroke_min_fill:
        return False
    width = mask.sum(axis=1)
    k = int(0.1 * width.size)
    middle = width[k:width.size - k] if width.size - 2 * k > 0 else width
    return middle.min() >= cfg.stroke_min_waist * float(np.median(width[width > 0]))


def _upper_lean(lab_cc: np.ndarray, piece_px: np.ndarray, above: np.ndarray,
                centre: float, min_px: int) -> float:
    """Horizontal offset of the upper-mark ink connected to a piece from the piece's centre;
    NaN when no mark touches the piece."""
    comps = np.unique(lab_cc[piece_px])
    comps = comps[comps > 0]
    if comps.size == 0:
        return float("nan")
    up = above & np.isin(lab_cc, comps)
    if up.sum() < min_px:
        return float("nan")
    return float(np.nonzero(up)[1].mean() - centre)


def _move_i_stems(label: np.ndarray, line_mask: np.ndarray, groups: Dict[int, _Group], live: List[int],
                  lower: np.ndarray, typical: float, cfg: Config) -> List[int]:
    rest = line_mask & (label == 0)
    cnt, marks, stats, _ = cv2.connectedComponentsWithStats(rest.astype(np.uint8), connectivity=8)
    if cnt <= 1:
        return live
    spans = {}
    for g in live:
        c = np.flatnonzero((label == g).any(axis=0))
        if c.size:
            spans[g] = (int(c[0]), int(c[-1]) + 1)
    order = sorted(spans, key=lambda g: spans[g][0])
    nxt = {a: b for a, b in zip(order[:-1], order[1:])}
    # roots: mark pixels with a letter pixel directly below them (the stroke continues down)
    below = np.zeros_like(label)
    below[:-1] = label[1:]
    roots = (marks > 0) & (below > 0)
    for c in range(1, cnt):
        mx, my, mw, mh = stats[c, :4]
        if stats[c, cv2.CC_STAT_AREA] < cfg.mark_min_px:
            continue
        r = roots[my:my + mh + 1, mx:mx + mw] & (marks[my:my + mh + 1, mx:mx + mw] == c)
        if not r.any():
            continue
        rcols = np.flatnonzero(r.any(axis=0)) + mx
        first = int(rcols[0])
        a = int(below[my:my + mh + 1, first][r[:, first - mx]][0])     # letter under the left root
        if a not in spans or a not in nxt or groups[a].kind != "letter":
            continue
        b = nxt[a]
        a0, a1 = spans[a]
        b0, b1 = spans[b]
        over_b = min(mx + mw, b1) - max(mx, b0)
        if first < a1 - cfg.i_stem_edge_ratio * typical or over_b < cfg.i_curl_cover * min(b1 - b0, typical):
            continue
        if groups[b].kind != "letter" or first - a0 < cfg.split_search_ratio * typical:
            continue
        # cut at the emptiest column between the letter body and the stem
        lo, hi = a0 + int(cfg.split_search_ratio * typical), first
        ink = (lower & (label == a))[:, lo:hi].sum(axis=0)
        cut = lo + int(np.flatnonzero(ink == ink.min())[-1])
        moved = (label == a)
        moved[:, :cut] = False
        label[moved] = b
        groups[b].rules = groups[b].rules + ["i-stem-right"]
        stem_end = first
        while stem_end + 1 in set(rcols.tolist()):
            stem_end += 1
        groups[b].keep_until = max(groups[b].keep_until, stem_end + 2)
        spans[a] = (a0, cut)
        spans[b] = (min(b0, cut), b1)
    return live


def letters_of_line(page: PreparedPage, line: Line, layout: LineLayout, pieces: List[Piece],
                    typical_letter: float, cfg: Config) -> List[Letter]:
    """Letters of one line. `typical_letter` is the page's typical letter width: a per-line value
    is unreliable on lines where many letters are merged."""
    if not pieces:
        return []
    x, y, w, h = line.box
    band, zone = zones(line, layout, cfg)
    body = line.mask & zone
    hy = line.headline_y[x:x + w] - y
    above = line.mask & (np.arange(h)[:, None] < hy[None, :] - cfg.piece_top_frac * layout.spacing)
    _, lab_cc = cv2.connectedComponents(line.mask.astype(np.uint8), connectivity=8)
    zone_h = layout.main_zone + cfg.piece_top_frac * layout.spacing

    # label image: piece number (1-based) on every piece pixel
    label = np.zeros((h, w), np.int32)
    for i, p in enumerate(pieces, 1):
        px, py, pw, ph = p.box
        label[py - y:py - y + ph, px - x:px - x + pw][p.mask] = i
    # ink above the headline band is matra ink that the column cut of C3a may have handed to the
    # wrong piece; it is attached by contact with the rest of its mark in rule 3
    label[np.arange(h)[:, None] < hy[None, :] - cfg.headline_above_px] = 0
    groups: Dict[int, _Group] = {i: _Group(p.x0 - x, p.x1 - x) for i, p in enumerate(pieces, 1)}
    typical = float(np.median([p.box[2] for p in pieces]))

    # ---- rule 1: narrow pieces -----------------------------------------------------------
    n = len(pieces)
    parent = list(range(n + 1))                      # union-find over piece numbers

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(i: int, j: int, rule: str) -> None:
        a, b = find(i), find(j)
        if a != b:
            parent[b] = a
            groups[a].x0, groups[a].x1 = min(groups[a].x0, groups[b].x0), max(groups[a].x1, groups[b].x1)
            groups[a].pieces += groups[b].pieces
            groups[a].rules += groups[b].rules + [rule]
            groups[a].keep_until = max(groups[a].keep_until, groups[b].keep_until)
            groups[a].protect += groups[b].protect

    danda = [False] * (n + 1)
    actions: List[Tuple[int, int, str]] = []
    for i, p in enumerate(pieces, 1):
        if p.box[2] > cfg.min_letter_width_ratio * typical:
            continue
        px = label == i
        left = i - 1 if i > 1 else 0
        right = i + 1 if i < n else 0
        c_left = _contact(body, p.x0 - x) if left and pieces[left - 1].x1 == p.x0 else 0
        c_right = _contact(body, p.x1 - x) if right and pieces[right - 1].x0 == p.x1 else 0
        if _is_tall_stroke(p.mask, zone_h, cfg):
            lean = _upper_lean(lab_cc, px, above, (p.box[0] + p.box[2] / 2) - x, cfg.mark_min_px)
            if not np.isnan(lean):
                if lean > 0 and right:
                    actions.append((i, right, "i-hook-right"))
                elif left:
                    actions.append((left, i, "ii-bar-left"))
            elif left and (c_left > 0 or p.head_width >= p.stem_width + cfg.bar_head_extra_px):
                actions.append((left, i, "bar-left"))
            else:
                danda[i] = True
        else:
            if left and (c_left >= c_right or not right):
                actions.append((left, i, "broken-left"))
            elif right:
                actions.append((i, right, "broken-right"))
    for a, b, rule in actions:
        if danda[a] or danda[b]:
            continue                                  # never glue a letter to a danda
        if rule == "i-hook-right":                    # the hook stays with the letter after it
            groups[a].keep_until = max(groups[a].keep_until, pieces[a - 1].x1 - x)
        elif rule in ("bar-left", "ii-bar-left"):     # the bar stays with the letter before it
            bar = pieces[b - 1]
            groups[b].protect.append((bar.x0 - x - cfg.bar_protect_px, bar.x1 - x))
        join(a, b, rule)
    for i in range(1, n + 1):                         # double danda
        if danda[i]:
            groups[i].kind = "danda"
            if i > 1 and danda[i - 1] and find(i - 1) == i - 1 and \
                    pieces[i - 1].box[0] - (pieces[i - 2].box[0] + pieces[i - 2].box[2]) <= cfg.double_danda_gap_ratio * typical:
                join(i - 1, i, "double-danda")
    for i in range(1, n + 1):
        label[label == i] = find(i)
    live = sorted({find(i) for i in range(1, n + 1)}, key=lambda g: groups[g].x0)

    # ---- rule 2: split wide letters ----------------------------------------------------------
    # letter bodies, clear of the headline's lower edge: where touching letters show their gap
    lower = body & (np.arange(h)[:, None] > hy[None, :] + cfg.split_body_top_frac * layout.main_zone)

    # short-i stems hidden at the right end of the previous letter: when the stem's headline touches
    # the letter before it there is no break, and the stem ends up in that letter. Its curl gives it
    # away: it rises from a stem near the letter's right edge and arches over the next letter.
    # Done before splitting, so a letter that receives a stem can still be split afterwards.
    live = _move_i_stems(label, line.mask, groups, live, lower, typical_letter, cfg)

    next_id = n + 1
    split_live = []
    for g in live:
        grp = groups[g]
        px = label == g
        cols = np.flatnonzero(px.any(axis=0))
        width = cols[-1] - cols[0] + 1 if cols.size else 0
        split_live.append(g)
        if grp.kind != "letter" or width <= cfg.split_width_ratio * typical_letter:
            continue
        # cut into as many letters as fit, each cut at the emptiest column near its expected place.
        # Below the headline two touching letters have (almost) no ink between their bodies, while a
        # wide single letter (shri, svaa) is solid: so a cut needs such a gap, unless the letter is
        # too wide to be one letter at all.
        a = cols[0]
        # a short-i stem belongs to the letter after it: count and cut only from the stem on
        start = max(a, grp.keep_until + 1)
        span = a + width - start
        blocked = np.zeros(width, bool)               # joined vowel bars: no cut inside or just before
        for c0, c1 in grp.protect:
            blocked[max(0, c0 - a):max(0, c1 - a)] = True
        parts = int(round((span - blocked[start - a:].sum()) / typical_letter))
        if parts < 2:
            continue
        reach = int(cfg.split_search_ratio * typical_letter)
        ink_cols = (lower & px).sum(axis=0)
        inked = ink_cols[ink_cols > 0]
        gap_limit = cfg.split_gap_frac * (float(np.median(inked)) if inked.size else 0.0)
        forced = width >= cfg.split_force_ratio * typical_letter
        cuts = []
        for k in range(1, parts):
            centre = start + int(round(k * span / parts))
            lo, hi = max(start + 1, centre - reach), min(a + width - 1, centre + reach + 1)
            seg = ink_cols[lo:hi].astype(np.float64)
            seg[blocked[lo - a:hi - a]] = np.inf
            if np.isinf(seg.min()):
                continue
            if seg.min() <= gap_limit or forced:
                cuts.append(lo + int(np.median(np.flatnonzero(seg == seg.min()))))
        # every part must hold a letter body, not just a vowel bar whose headline touched the letter
        # before it: count the columns with body ink in each part
        min_body = cfg.min_letter_width_ratio * typical_letter
        cuts = sorted(cuts)
        while cuts:
            edges = [a, *cuts, a + width]
            body_w = [int((ink_cols[e0:e1] > 0).sum()) for e0, e1 in zip(edges[:-1], edges[1:])]
            worst = int(np.argmin(body_w))
            if body_w[worst] >= min_body:
                break
            cuts.pop(min(worst, len(cuts) - 1))       # drop the cut next to the thinnest part
        if not cuts:
            continue
        grp.rules = grp.rules + ["split"]
        for cut in sorted(cuts, reverse=True):         # peel off parts from the right
            new = next_id
            next_id += 1
            part = (label == g)
            part[:, :cut] = False
            label[part] = new
            groups[new] = _Group(cut, grp.x1, rules=list(grp.rules))
            grp.x1 = cut
            split_live.append(new)
    live = sorted(split_live, key=lambda g: groups[g].x0)

    # ---- rule 3: marks and specks --------------------------------------------------------------
    rest = line.mask & (label == 0)
    if rest.any():
        cnt, marks, stats, _ = cv2.connectedComponentsWithStats(rest.astype(np.uint8), connectivity=8)
        spans = {g: (np.flatnonzero((label == g).any(axis=0))) for g in live}
        spans = {g: (c[0], c[-1] + 1) for g, c in spans.items() if c.size}
        ring_k = np.ones((3, 3), np.uint8)
        for c in range(1, cnt):
            mx, my, mw, mh = stats[c, :4]
            x0, y0, x1, y1 = max(0, mx - 1), max(0, my - 1), min(w, mx + mw + 1), min(h, my + mh + 1)
            m = marks[y0:y1, x0:x1] == c
            # letter pixels right next to the mark, counted per letter
            ring = (cv2.dilate(m.astype(np.uint8), ring_k) > 0) & ~m
            touching = label[y0:y1, x0:x1][ring]
            touching = touching[touching > 0]
            if touching.size:
                ids, counts = np.unique(touching, return_counts=True)
                label[y0:y1, x0:x1][m] = ids[np.argmax(counts)]
                continue
            a, b = mx, mx + mw
            overlap = {g: min(b, s[1]) - max(a, s[0]) for g, s in spans.items()}
            best = max(overlap, key=overlap.get) if overlap else None
            if best is None:
                continue
            if overlap[best] <= 0:
                mid = (a + b) / 2
                best = min(spans, key=lambda g: abs((spans[g][0] + spans[g][1]) / 2 - mid))
            label[y0:y1, x0:x1][m] = best

    # ---- build letters, rule 4: digits between dandas ------------------------------------------
    red = page.red[y:y + h, x:x + w]
    out: List[Letter] = []
    for g in live:
        m = label == g
        if not m.any():
            continue
        ys, xs = np.nonzero(m)
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        mm = m[y0:y1, x0:x1]
        n_red = int((red[y0:y1, x0:x1] & mm).sum())
        grp = groups[g]
        out.append(Letter(line=line.index, pos=0, box=(int(x + x0), int(y + y0), int(x1 - x0), int(y1 - y0)),
                          mask=mm, ink="red" if 2 * n_red > mm.sum() else "black", kind=grp.kind,
                          pieces=grp.pieces, rules=list(grp.rules)))
    out.sort(key=lambda L: L.box[0])
    dandas = [k for k, L in enumerate(out) if L.kind == "danda"]
    for a, b in zip(dandas[:-1], dandas[1:]):
        inner = out[a + 1:b]
        if 1 <= len(inner) <= 2 and sum(L.box[2] for L in inner) <= cfg.digit_max_width_ratio * typical_letter:
            for L in inner:
                L.kind = "digit"
    for k, L in enumerate(out, 1):
        L.pos = k
    return out


def make_letters(page: PreparedPage, layout: LineLayout, pieces: List[Piece], cfg: Config) -> List[Letter]:
    by_line: Dict[int, List[Piece]] = {}
    for p in pieces:
        by_line.setdefault(p.line, []).append(p)
    widths = np.array([p.box[2] for p in pieces], np.float32)
    if widths.size == 0:
        return []
    # typical letter width: median of the pieces that are not narrow (bars, hooks, dandas)
    typical_letter = float(np.median(widths[widths >= cfg.min_letter_width_ratio * np.median(widths)]))
    out: List[Letter] = []
    for line in layout.lines:
        out.extend(letters_of_line(page, line, layout, by_line.get(line.index, []), typical_letter, cfg))
    return out


def letter_image(page: PreparedPage, letter: Letter, cfg: Config) -> np.ndarray:
    """Crop of one letter from the original page with a small margin; ink of neighbouring letters
    inside the crop is filled in from the paper around it, so only this letter is left (FR-6)."""
    H, W = page.ink.shape
    x, y, w, h = letter.box
    m = cfg.letter_margin_px
    x0, y0, x1, y1 = max(0, x - m), max(0, y - m), min(W, x + w + m), min(H, y + h + m)
    crop = page.rgb[y0:y1, x0:x1].copy()
    own = np.zeros((y1 - y0, x1 - x0), bool)
    own[y - y0:y - y0 + h, x - x0:x - x0 + w] = letter.mask
    other = page.ink[y0:y1, x0:x1] & ~own
    if other.any():
        g = 2 * cfg.line_erase_grow_px + 1
        near = cv2.dilate(other.astype(np.uint8), np.ones((g, g), np.uint8)) > 0
        near &= ~(cv2.dilate(own.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0)
        crop = cv2.inpaint(crop, near.astype(np.uint8), 3, cv2.INPAINT_TELEA)
    return crop


_KIND_COLOURS = {"danda": (120, 120, 120), "digit": (200, 0, 160)}
_LETTER_COLOURS = [(0, 90, 200), (0, 150, 60), (200, 120, 0), (150, 40, 180)]


def letters_overlay(page: PreparedPage, letters: List[Letter]) -> np.ndarray:
    """Debug view: each letter's ink in a colour cycling along the line, a box around it, dandas
    grey and digits magenta; letters made by a split get a dashed red box."""
    out = (0.25 * page.rgb.astype(np.float32) + 0.75 * 245).astype(np.uint8)
    for L in letters:
        x, y, w, h = L.box
        c = _KIND_COLOURS.get(L.kind, _LETTER_COLOURS[L.pos % len(_LETTER_COLOURS)])
        out[y:y + h, x:x + w][L.mask] = c
    for L in letters:
        x, y, w, h = L.box
        c = _KIND_COLOURS.get(L.kind, _LETTER_COLOURS[L.pos % len(_LETTER_COLOURS)])
        if "split" in L.rules:
            for xx in range(x, x + w, 6):
                cv2.line(out, (xx, y - 2), (min(x + w, xx + 3), y - 2), (230, 0, 0), 1)
                cv2.line(out, (xx, y + h + 1), (min(x + w, xx + 3), y + h + 1), (230, 0, 0), 1)
        else:
            cv2.rectangle(out, (x - 1, y - 2), (x + w, y + h + 1), c, 1)
    return out

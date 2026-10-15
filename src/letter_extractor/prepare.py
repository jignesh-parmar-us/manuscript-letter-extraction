"""Page preparation (FR-2): paper mask, flattened paper tone, red and black ink masks, text block.

Works on raw scans and on pages already cleaned by the border remover. Ruled border lines are
removed from the ink masks by shape (long straight runs), and the margin folio numbers, scanner
background and tape marks fall outside the text block. Faint, broken side borders that survive as
dashes limit the text block (vertical_borders), so nothing outside them is cut.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np

from .config import Config, InkParams

Box = Tuple[int, int, int, int]       # x, y, w, h


@dataclass
class PreparedPage:
    rgb: np.ndarray                   # the page as loaded (never modified)
    paper: np.ndarray                 # bool: page paper (False on the scanner background)
    black: np.ndarray                 # bool: black ink inside the text block
    red: np.ndarray                   # bool: red ink inside the text block
    rules: np.ndarray                 # bool: ruled-line pixels removed from the ink masks
    block: Optional[Box]              # text block, None if no text was found
    borders: Tuple[Optional[int], Optional[int]] = (None, None)   # inner columns of the left and right
                                                                   # border lines found (vertical_borders)

    @property
    def ink(self) -> np.ndarray:
        return self.black | self.red


def _odd(n: int) -> int:
    n = max(3, int(round(n)))
    return n if n % 2 else n + 1


def paper_mask(L: np.ndarray, cfg: Config) -> np.ndarray:
    """Paper = everything except dark areas connected to the image edge (the scanner background).
    Black ink is dark too, but it lies inside the page and never touches the edge."""
    typical = float(np.percentile(L, 75))
    dark = (L < cfg.scanner_rel_l * typical).astype(np.uint8)
    n, labels = cv2.connectedComponents(dark, connectivity=8)
    edge = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    scanner = np.isin(labels, edge[edge > 0])
    return ~scanner


def paper_tone(chan: np.ndarray, paper: np.ndarray, cfg: Config) -> np.ndarray:
    """Local paper value of one Lab channel at every pixel: median filter on a small copy.
    Thin ink strokes are a minority in every window, so the median follows the paper, including
    uneven tone and stains. Scanner pixels are replaced by the paper median first."""
    H, W = chan.shape
    filled = chan.copy()
    filled[~paper] = np.median(chan[paper]) if paper.any() else np.median(chan)
    s = cfg.work_scale
    small = cv2.resize(filled, (max(1, int(W * s)), max(1, int(H * s))), interpolation=cv2.INTER_AREA)
    # Lab channels are 0-255, and medianBlur needs 8-bit input for windows larger than 5
    small = cv2.medianBlur(np.clip(small, 0, 255).astype(np.uint8), _odd(cfg.paper_blur_px * s))
    return cv2.resize(small, (W, H), interpolation=cv2.INTER_LINEAR).astype(np.float32)


def _headlines(h: np.ndarray, ink: np.ndarray, cfg: Config) -> np.ndarray:
    """The horizontal runs of `h` that are the headline of printed words, not rules: a long word's
    headline is as straight and long as a rule, but its letters hang from it, so most of its columns have
    ink just below it. A rule has nothing hanging from it (the text keeps a gap)."""
    H = ink.shape[0]
    n, lab, st, _ = cv2.connectedComponentsWithStats(h, connectivity=8)
    keep = np.zeros(n, bool)
    for i in range(1, n):
        x, y, w, hh = st[i, :4]
        y0 = y + hh + cfg.rule_below_gap_px
        below = ink[y0:min(H, y0 + cfg.rule_below_px), x:x + w]
        keep[i] = below.size > 0 and below.any(axis=0).mean() >= cfg.rule_headline_frac
    return keep[lab]


def ruled_lines(ink: np.ndarray, cfg: Config) -> np.ndarray:
    """Pixels of long straight vertical or horizontal runs (border rules). Letters are far shorter
    than `rule_min_frac` of the page, so only the rules survive the openings; a word's headline can be
    as long, so a horizontal run with letters hanging from it is kept (`_headlines`)."""
    H, W = ink.shape
    m = ink.astype(np.uint8)
    slant = max(1, cfg.rule_slant_px)
    vlen, hlen = int(cfg.rule_min_frac * H), int(cfg.rule_min_frac * W)
    # widen first so a slightly slanted rule still contains a straight 1 px run
    v = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_RECT, (slant, 1)))
    v = cv2.morphologyEx(v, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, vlen)))
    h = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_RECT, (1, slant)))
    h = cv2.morphologyEx(h, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (hlen, 1)))
    h[_headlines(h, ink, cfg)] = 0
    lines = cv2.dilate(v | h, np.ones((3, 3), np.uint8))
    return (lines > 0) & ink


def _runs(active: np.ndarray, max_gap: int):
    """[start, end) runs of True, with gaps up to max_gap merged."""
    idx = np.flatnonzero(active)
    if idx.size == 0:
        return []
    runs, start, prev = [], idx[0], idx[0]
    for i in idx[1:]:
        if i - prev > max_gap + 1:
            runs.append((start, prev + 1))
            start = i
        prev = i
    runs.append((start, prev + 1))
    return runs


def _main_run(profile: np.ndarray, frac: float, cfg: Config):
    k = _odd(cfg.block_smooth_px)
    smooth = np.convolve(profile.astype(np.float32), np.ones(k, np.float32) / k, mode="same")
    ref = np.percentile(smooth[smooth > 0], 95) if (smooth > 0).any() else 0.0
    if ref <= 0:
        return None
    runs = _runs(smooth >= frac * ref, cfg.block_gap_px)
    return max(runs, key=lambda r: profile[r[0]:r[1]].sum()) if runs else None


def text_block(ink: np.ndarray, cfg: Config) -> Optional[Box]:
    """The densest rectangle of text. Margin numbers cover only a few lines, so their columns hold
    far less ink than text columns and drop out of the column run."""
    H, W = ink.shape
    cols = _main_run(ink.sum(axis=0), cfg.block_col_frac, cfg)
    if cols is None:
        return None
    rows = _main_run(ink[:, cols[0]:cols[1]].sum(axis=1), cfg.block_row_frac, cfg)
    if rows is None:
        return None
    p = cfg.block_pad_px
    x0, x1 = max(0, cols[0] - p), min(W, cols[1] + p)
    y0, y1 = max(0, rows[0] - p), min(H, rows[1] + p)
    return int(x0), int(y0), int(x1 - x0), int(y1 - y0)


def _longest_runs(m: np.ndarray) -> np.ndarray:
    """Longest vertical run of True in every column."""
    best = np.zeros(m.shape[1], np.int32)
    cur = np.zeros(m.shape[1], np.int32)
    for row in m:
        cur = np.where(row, cur + 1, 0)
        np.maximum(best, cur, out=best)
    return best


def vertical_borders(faint: np.ndarray, block: Box, cfg: Config) -> Tuple[Optional[int], Optional[int]]:
    """Inner columns of the left and right border lines next to the text block, or None. Faint, broken
    borders survive `ruled_lines` as dashes; here a border is a column whose (lightly thresholded) ink
    runs for `border_min_run_frac` of the page height once small breaks are bridged. Text never runs
    that long: its strokes stop between lines. Only columns outside the block or up to
    `border_search_px` inside its edge count, so a rule between two text columns never clips text."""
    H, W = faint.shape
    x, _, w, _ = block
    m = cv2.dilate(faint.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_RECT, (max(1, cfg.rule_slant_px), 1)))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (1, cfg.border_max_break_px + 1)))
    min_run = cfg.border_min_run_frac * H
    a = max(0, min(W, x + cfg.border_search_px))
    left = np.flatnonzero(_longest_runs(m[:, :a] > 0) >= min_run)
    b = max(0, min(W, x + w - cfg.border_search_px))
    right = np.flatnonzero(_longest_runs(m[:, b:] > 0) >= min_run) + b
    return (int(left[-1]) if left.size else None), (int(right[0]) if right.size else None)


def clip_to_borders(block: Box, borders: Tuple[Optional[int], Optional[int]]) -> Box:
    """The block narrowed to lie between the borders (never widened)."""
    x, y, w, h = block
    x0, x1 = x, x + w
    if borders[0] is not None:
        x0 = max(x0, borders[0] + 1)
    if borders[1] is not None:
        x1 = min(x1, borders[1])
    return x0, y, max(0, x1 - x0), h


def remove_specks(mask: np.ndarray, params: InkParams) -> np.ndarray:
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    keep = stats[:, cv2.CC_STAT_AREA] >= params.min_speck_px
    keep[0] = False
    return keep[labels]


def prepare_page(rgb: np.ndarray, cfg: Config) -> PreparedPage:
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    L = lab[..., 0].astype(np.float32)
    A = lab[..., 1].astype(np.float32)
    paper = paper_mask(L, cfg)
    paper_L = np.maximum(paper_tone(L, paper, cfg), 1.0)
    paper_A = paper_tone(A, paper, cfg)

    red = paper & (A - paper_A >= cfg.red_min_da) & (paper_L - L >= cfg.red_min_dl)
    black = paper & ~red & (L < cfg.black_max_rel_l * paper_L)

    rules = ruled_lines(red | black, cfg)
    red &= ~rules
    black &= ~rules

    block = text_block(red | black, cfg)
    borders: Tuple[Optional[int], Optional[int]] = (None, None)
    if block is not None and cfg.border_clip:
        faint = (paper & (L < cfg.border_max_rel_l * paper_L)) | red | black | rules
        borders = vertical_borders(faint, block, cfg)
        block = clip_to_borders(block, borders)
    inside = np.zeros_like(paper)
    if block is not None:
        x, y, w, h = block
        inside[y:y + h, x:x + w] = True
    red = remove_specks(red & inside, cfg.red)
    black = remove_specks(black & inside, cfg.black)
    return PreparedPage(rgb=rgb, paper=paper, black=black, red=red, rules=rules, block=block, borders=borders)


def ink_overlay(page: PreparedPage) -> np.ndarray:
    """Debug view: black ink in black, red ink in red, removed ruled lines in blue, everything
    outside the text block or the paper greyed out, text block outlined in green, page borders that
    limit the cut (vertical_borders) as orange lines."""
    H, W = page.paper.shape
    out = np.full((H, W, 3), 245, np.uint8)
    faded = (0.35 * page.rgb.astype(np.float32) + 0.65 * 160).astype(np.uint8)
    outside = np.ones((H, W), bool)
    if page.block is not None:
        x, y, w, h = page.block
        outside[y:y + h, x:x + w] = False
    outside |= ~page.paper
    out[outside] = faded[outside]
    out[page.rules] = (60, 120, 230)
    out[page.black] = (0, 0, 0)
    out[page.red] = (220, 30, 30)
    if page.block is not None:
        x, y, w, h = page.block
        cv2.rectangle(out, (x, y), (x + w - 1, y + h - 1), (0, 170, 0), 3)
    for bx in page.borders:
        if bx is not None:
            cv2.line(out, (bx, 0), (bx, H - 1), (240, 140, 0), 3)
    return out

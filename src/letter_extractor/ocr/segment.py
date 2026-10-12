"""Reading a line without Tesseract, by searching along it (segmentation by recognition).

Plan: `docs/SEGMENTATION_PLAN.md`. Measured on the 73 checked lines of the printed 1933 book (stage 3,
2026-10-11): 11.1% of the characters wrong; as a second opinion beside Tesseract its disagreements mark
19.4% of the aksharas and 88% of the remaining mistakes (stage 4). With the defaults below (a boundary every
9 px, unlikely windows dropped; stage 5): 10.2% wrong, about 7 s per line.

1. **Candidate boundaries:** a column every `step` pixels, plus the empty columns' edges and the thin
   points of the ink below the headline (the headline joins the letters, so its rows are left out).
2. **Windows:** every stretch between two candidates that is `min_width` to `max_width` x the book's
   typical letter width and holds ink, cropped to its ink.
3. **Reading the windows** with a letter reader that has a "not a letter" class (its last class); a window
   whose best letter is unlikely is dropped (`min_prob`), and each kept window offers its `top_k` letters.
4. **Beam search** from left to right (states: position, last two aksharas; `beam` kept per position).
   A step scores log p(label) + `bonus` - `width_weight` x (log(width / the label's usual width))^2 /
   (2 x 0.3^2) + `lm_weight` x log P(label | last two). Empty stretches are skipped (a space if wide);
   an "unknown" step (-12) makes sure a path always exists.

Before the search, `clear_borders` removes a page border caught at the start or end of the line (the
user's observation, 2026-10-12): thin pieces of ink at the edge, peeled one by one, that are taller than
the line's letters, broken and reaching above or below the letters' band, or tiny specks. A danda is solid
and stays within the band, so it is kept (checked on every line edge of the printed 1933 book).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .features import features_batch
from .language import LanguageModel, tokens


@dataclass
class SearchSettings:
    step: int = 9                       # a candidate boundary every `step` pixels (stage 5: 9 as good as 6)
    min_width: float = 0.2              # windows from this...
    max_width: float = 2.4              # ...to this x the typical letter width
    top_k: int = 4                      # letters each window offers
    beam: int = 10
    bonus: float = 4.0                  # per letter (else the search prefers few, wide windows)
    width_weight: float = 1.0
    lm_weight: float = 0.5
    min_prob: float = 0.05              # windows whose best letter is less likely than this are dropped
    unknown: float = -12.0


@dataclass
class Step:
    x0: int                             # columns of the line mask
    x1: int
    label: str                          # "" for a skipped empty stretch, "?" for unknown
    space: bool = False                 # an empty stretch: a word gap; a letter (as returned): a gap before it


def _crop(mask: np.ndarray, a: int, b: int) -> Optional[np.ndarray]:
    part = mask[:, max(0, a):min(mask.shape[1], b)]
    ys, xs = np.nonzero(part)
    if ys.size < 10:
        return None
    return part[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def _ink_runs(mask: np.ndarray, join: float) -> List[Tuple[int, int]]:
    """Stretches of columns with ink, those closer than `join` px joined."""
    cols = mask.any(axis=0)
    edges = np.flatnonzero(np.diff(np.concatenate([[0], cols.astype(np.int8), [0]])))
    out: List[Tuple[int, int]] = []
    for a, b in zip(edges[::2], edges[1::2]):
        if out and a - out[-1][1] < join:
            out[-1] = (out[-1][0], int(b))
        else:
            out.append((int(a), int(b)))
    return out


def clear_borders(mask: np.ndarray, typical_width: float, letter_height: float, band: Tuple[float, float],
                  most: int = 6) -> Tuple[np.ndarray, int]:
    """The mask without border pieces at its two edges (see the module notes), and how many were removed.
    `letter_height`: the line's usual letter height; `band`: the rows its letters usually span."""
    T, h_ref = typical_width, letter_height

    def border_like(a: int, b: int) -> bool:
        ys = np.flatnonzero(mask[:, a:b].any(axis=1))
        top, bot = int(ys.min()), int(ys.max())
        h, w = bot - top + 1, b - a
        if w > 0.45 * T:
            return False
        if h >= 1.1 * h_ref:                                        # taller than the letters
            return True
        filled = mask[top:bot + 1, a:b].any(axis=1).mean()
        if (top < band[0] - 0.2 * h_ref or bot > band[1] + 0.2 * h_ref) and filled < 0.9:
            return True                                             # broken, reaching out of the letters' band
        return h <= 0.3 * h_ref and w <= 0.15 * T                   # a speck

    runs = _ink_runs(mask, 0.15 * T)
    out, removed = mask, 0
    for side in (0, -1):
        for _ in range(most):
            if len(runs) < 2 or not border_like(*runs[side]):
                break
            a, b = runs.pop(side)
            if out is mask:
                out = mask.copy()
            out[:, a:b] = False
            removed += 1
    return out, removed


def candidates(mask: np.ndarray, step: int) -> List[int]:
    """Columns where a letter may start or end."""
    h, w = mask.shape
    cols = np.flatnonzero(mask.any(axis=0))
    if cols.size == 0:
        return []
    head = int(np.argmax(mask[:max(1, h // 2)].sum(axis=1)))
    band = max(2, h // 12)
    keep = np.ones(h, bool)
    keep[max(0, head - band):head + band + 1] = False
    prof = mask[keep].sum(axis=0).astype(float)
    sm = np.convolve(prof, np.ones(3) / 3, mode="same")
    pos_med = float(np.median(prof[prof > 0])) if (prof > 0).any() else 1.0
    cand = {int(cols[0]), int(cols[-1]) + 1}
    empty = ~mask.any(axis=0)
    for i in range(1, w):
        if empty[i] != empty[i - 1]:
            cand.add(i)
        if 0 < i < w - 1 and sm[i] <= sm[i - 1] and sm[i] <= sm[i + 1] and sm[i] <= 0.35 * pos_med:
            cand.add(i)
    cand |= set(range(int(cols[0]), int(cols[-1]) + 1, max(1, step)))
    merged: List[int] = []
    for x in sorted(cand):
        if not merged or x - merged[-1] >= 2:
            merged.append(x)
    return merged


@dataclass
class Windows:
    """A line cut into windows, before reading them: the candidate boundaries, the empty stretches
    (edges to a later candidate with nothing to read) and each window with ink (its features)."""
    cand: List[int]
    empty_edges: List[Tuple[int, int, int]]          # (i, j, width) between candidates i < j
    meta: List[Tuple[int, int, int]]                 # per window: (i, j, width)
    X: np.ndarray                                    # per window: its features


def line_windows(mask: np.ndarray, spacing: float, typical_width: float,
                 s: SearchSettings = SearchSettings()) -> Optional[Windows]:
    """Steps 1 and 2 (see the module notes): the line's windows and their features; None for no line."""
    cand = candidates(mask, s.step)
    n = len(cand)
    if n < 2:
        return None
    empty = ~mask.any(axis=0)
    T = typical_width
    empty_edges, crops, meta = [], [], []
    for i in range(n):
        for j in range(i + 1, n):
            width = cand[j] - cand[i]
            if width > s.max_width * T:
                break
            if empty[cand[i]:cand[j]].all():
                empty_edges.append((i, j, width))
                continue
            if width < s.min_width * T:
                continue
            m = _crop(mask, cand[i], cand[j])
            if m is not None:
                crops.append(m)
                meta.append((i, j, width))
    return Windows(cand, empty_edges, meta, features_batch(crops, spacing))


def read_line(mask: np.ndarray, spacing: float, reader, typical_width: float, widths: Dict[str, float],
              lm: Optional[LanguageModel], s: SearchSettings = SearchSettings()) -> Tuple[str, List[Step], Dict]:
    """The text of one line's ink mask (rows x columns of the line), and the steps of the best path.
    `reader`: a LetterReader whose last class is "not a letter"; `widths`: each label's usual width (px)."""
    win = line_windows(mask, spacing, typical_width, s)
    if win is None:
        return "", [], {"candidates": len(candidates(mask, s.step)), "windows": 0, "kept": 0}
    return search(win, reader.probabilities(win.X) if len(win.X) else None, reader.classes, typical_width,
                  widths, lm, s)


def search(win: Windows, P: Optional[np.ndarray], classes: Sequence[str], typical_width: float,
           widths: Dict[str, float], lm: Optional[LanguageModel],
           s: SearchSettings = SearchSettings()) -> Tuple[str, List[Step], Dict]:
    """Steps 3 and 4: the best path through the windows, given each window's class probabilities `P`
    (the last class "not a letter")."""
    cand = win.cand
    n = len(cand)
    T = typical_width
    stats = {"candidates": n, "windows": len(win.meta), "kept": 0}
    edges: Dict[int, List[Tuple[int, str, float, int]]] = {i: [] for i in range(n)}
    for i, j, width in win.empty_edges:
        edges[i].append((j, "", 0.0, width))
    if P is not None and len(P):
        letters = P[:, :-1]                                       # the last class is "not a letter"
        best = letters.max(axis=1)
        keep = np.flatnonzero(best >= s.min_prob)
        stats["kept"] = int(keep.size)
        lp = np.log(np.maximum(letters[keep], 1e-9))
        top = np.argsort(-lp, axis=1)[:, :s.top_k]
        for row, ks, q in zip(lp, top, keep):
            i, j, width = win.meta[q]
            for k in ks:
                edges[i].append((j, classes[int(k)], float(row[k]), width))
    for i in range(n - 1):
        edges[i].append((i + 1, "?", s.unknown, cand[i + 1] - cand[i]))

    lm_cache: Dict[Tuple[str, str, str], Tuple[float, str, str]] = {}

    def lm_step(p2: str, p1: str, label: str) -> Tuple[float, str, str]:
        key = (p2, p1, label)
        if key not in lm_cache:
            lm_cache[key] = lm.logprob(tokens(label), p2, p1) if lm is not None else (0.0, p1, label)
        return lm_cache[key]

    width_pen: Dict[Tuple[str, int], float] = {}
    states: List[Dict] = [dict() for _ in range(n)]
    states[0][("<s>", "<s>")] = (0.0, None)
    for i in range(n):
        if not states[i]:
            continue
        best_states = sorted(states[i].items(), key=lambda kv: -kv[1][0])[:s.beam]
        states[i] = dict(best_states)
        for (p2, p1), (score, _) in best_states:
            for j, label, lpv, width in edges[i]:
                if label == "":
                    key, add, step = (p2, p1), 0.0, ("", width >= 0.5 * T)
                elif label == "?":
                    key, add, step = (p1, "?"), lpv, ("?", False)
                else:
                    pen = 0.0
                    if s.width_weight and label in widths:
                        wk = (label, width)
                        if wk not in width_pen:
                            width_pen[wk] = s.width_weight * math.log(width / widths[label]) ** 2 / (2 * 0.3 ** 2)
                        pen = width_pen[wk]
                    lmp, n2, n1 = lm_step(p2, p1, label)
                    key, add, step = (n2, n1), lpv + s.bonus - pen + s.lm_weight * lmp, (label, False)
                new = score + add
                if key not in states[j] or new > states[j][key][0]:
                    states[j][key] = (new, (i, (p2, p1), step))
    end = states[n - 1]
    if not end:
        return "", [], stats
    key = max(end, key=lambda k: end[k][0])
    steps: List[Step] = []
    node = n - 1
    while True:
        _, back = states[node][key]
        if back is None:
            break
        prev, key, (label, space) = back
        steps.append(Step(cand[prev], cand[node], label, space))
        node = prev
    steps.reverse()
    text = "".join((" " if st.space and st.label == "" else st.label) for st in steps)
    letters, gap = [], False
    for st in steps:                                        # a letter's `space`: a word gap before it
        if st.label:
            letters.append(Step(st.x0, st.x1, st.label, gap and bool(letters)))
            gap = False
        else:
            gap = gap or st.space
    return " ".join(text.split()), letters, stats


def align(win: Optional[Windows], P: Optional[np.ndarray], classes: Sequence[str], typical_width: float,
          aksharas: Sequence[str]) -> Tuple[Optional[List[Tuple[int, str]]], Optional[float]]:
    """Forced alignment (learning from checked lines): the best way to cut the line into exactly the
    `aksharas` of its checked text, empty stretches free. A known akshara scores log p of its window plus
    half the width term; one the reader has no class for scores the window being a letter at all and
    the width term (wider tolerance), minus 2. Returns [(window index, akshara)] and the mean score per
    akshara, or (None, None) when the line cannot be cut so."""
    if win is None or P is None or not len(P) or not aksharas:
        return None, None
    n, m, T = len(win.cand), len(aksharas), typical_width
    ci = {c: i for i, c in enumerate(classes)}
    letter = 1.0 - P[:, -1]
    out_edges: List[List[Tuple[int, int, int]]] = [[] for _ in range(n)]
    for q, (i, j, w) in enumerate(win.meta):
        out_edges[i].append((j, q, w))
    empty: List[List[int]] = [[] for _ in range(n)]
    for i, j, _ in win.empty_edges:
        empty[i].append(j)
    NEG = -1e18
    best = np.full((n, m + 1), NEG)
    back: Dict[Tuple[int, int], Tuple[int, int, Optional[int]]] = {}
    best[0, 0] = 0.0
    for i in range(n):
        for t in range(m + 1):
            sc = best[i, t]
            if sc <= NEG / 2:
                continue
            for j in empty[i]:
                if sc > best[j, t]:
                    best[j, t] = sc
                    back[(j, t)] = (i, t, None)
            if t == m:
                continue
            k = ci.get(aksharas[t])
            for j, q, w in out_edges[i]:
                wp = -math.log(w / T) ** 2 / (2 * 0.6 ** 2)
                s = (math.log(max(float(P[q, k]), 1e-6)) + 0.5 * wp if k is not None
                     else math.log(max(float(letter[q]), 1e-6)) + wp - 2.0)
                if sc + s > best[j, t + 1]:
                    best[j, t + 1] = sc + s
                    back[(j, t + 1)] = (i, t, q)
    if best[n - 1, m] <= NEG / 2:
        return None, None
    path: List[Tuple[int, str]] = []
    node = (n - 1, m)
    while node in back:
        i, t, q = back[node]
        if q is not None:
            path.append((q, aksharas[t]))
        node = (i, t)
    path.reverse()
    return path, float(best[n - 1, m] / m)

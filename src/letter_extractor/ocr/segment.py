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
    space: bool = False                 # a word gap before the next letter


def _crop(mask: np.ndarray, a: int, b: int) -> Optional[np.ndarray]:
    part = mask[:, max(0, a):min(mask.shape[1], b)]
    ys, xs = np.nonzero(part)
    if ys.size < 10:
        return None
    return part[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


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


def read_line(mask: np.ndarray, spacing: float, reader, typical_width: float, widths: Dict[str, float],
              lm: Optional[LanguageModel], s: SearchSettings = SearchSettings()) -> Tuple[str, List[Step], Dict]:
    """The text of one line's ink mask (rows x columns of the line), and the steps of the best path.
    `reader`: a LetterReader whose last class is "not a letter"; `widths`: each label's usual width (px)."""
    cand = candidates(mask, s.step)
    n = len(cand)
    stats = {"candidates": n, "windows": 0, "kept": 0}
    if n < 2:
        return "", [], stats
    empty = ~mask.any(axis=0)
    T = typical_width
    edges: Dict[int, List[Tuple[int, str, float, int]]] = {i: [] for i in range(n)}
    crops, meta = [], []
    for i in range(n):
        for j in range(i + 1, n):
            width = cand[j] - cand[i]
            if width > s.max_width * T:
                break
            if empty[cand[i]:cand[j]].all():
                edges[i].append((j, "", 0.0, width))
                continue
            if width < s.min_width * T:
                continue
            m = _crop(mask, cand[i], cand[j])
            if m is not None:
                crops.append(m)
                meta.append((i, j, width))
    stats["windows"] = len(crops)
    if crops:
        P = reader.probabilities(features_batch(crops, spacing))
        letters = P[:, :-1]                                       # the last class is "not a letter"
        best = letters.max(axis=1)
        keep = np.flatnonzero(best >= s.min_prob)
        stats["kept"] = int(keep.size)
        lp = np.log(np.maximum(letters[keep], 1e-9))
        top = np.argsort(-lp, axis=1)[:, :s.top_k]
        for row, ks, q in zip(lp, top, keep):
            i, j, width = meta[q]
            for k in ks:
                edges[i].append((j, reader.classes[int(k)], float(row[k]), width))
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
    return " ".join(text.split()), [st for st in steps if st.label], stats

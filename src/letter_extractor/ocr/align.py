"""Match the aksharas Tesseract read in a line to the samples Phase 1 cut from it (C11).

Only x positions are compared: within one line, letters follow each other from left to right.
Tesseract's character boxes are rough: most are narrow and in reading order, but some (often vowel
signs) span a whole word. So an akshara's span is the union of its characters' *plausible* boxes,
and an akshara without one gets the gap between its neighbours.

The two sequences are aligned by dynamic programming (like a text diff). One akshara may cover
several samples (Phase 1 cut a conjunct in two: no reading for them) and several aksharas may fall
on one sample (a word that was not cut: its reading is the word). A match is kept only when the
overlap is clear: at least `min_overlap` and the same pair is also each other's best overlap, or at
least `sure_overlap`. Unclear samples stay unmatched, which is better than a wrong reading.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import List, Optional, Sequence, Tuple

from .aksharas import Akshara

Span = Tuple[int, int]               # x0, x1 (x1 exclusive)

SKIP = 0.5                           # cost of leaving an akshara or a sample unmatched
GROUP_PENALTY = 0.1                  # extra cost per additional item in a 1:k or k:1 step
MAX_GROUP = 3                        # at most this many aksharas on one sample, or samples under one akshara
WIDE_CHAR = 2.5                      # a character box wider than this x the line's median is not trusted


@dataclass
class Match:
    sample: int                      # index into the samples
    aksharas: Tuple[int, ...]        # indices into the aksharas, in order
    text: str
    conf: float                      # lowest confidence of the aksharas
    overlap: float
    alternatives: List = field(default_factory=list)   # per character, Tesseract's (text, confidence) choices


@dataclass
class LineAlignment:
    matches: List[Match]
    spans: List[Optional[Span]]      # the aksharas' spans used for matching
    refused: bool = False            # too few samples matched: the line is not used
    steps: List[Tuple[int, int, int, int]] = field(default_factory=list)
    # the alignment path: (first akshara, first sample, aksharas, samples) per step; (i, j, 0, 1) skips
    # sample j, (i, j, 1, 0) skips akshara i, (i, j, 2, 1) puts 2 aksharas on sample j (C12b splits it),
    # (i, j, 1, 2) puts akshara i over 2 samples (C12b joins them)


def akshara_spans(aksharas: Sequence[Akshara], dx: int = 0) -> List[Optional[Span]]:
    """Each akshara's x span from its characters' plausible boxes, shifted by `dx`; aksharas without
    one get the gap between their neighbours (None if there is no gap)."""
    widths = [c.box[2] for a in aksharas for c in a.chars if c.box[2] > 0]
    limit = WIDE_CHAR * median(widths) if widths else 0
    spans: List[Optional[Span]] = []
    for a in aksharas:
        good = [c.box for c in a.chars if 0 < c.box[2] <= limit]
        if not good:
            spans.append(None)
            continue
        x0, x1 = min(b[0] for b in good) + dx, max(b[0] + b[2] for b in good) + dx
        base = a.chars[0].box if a.chars else (0, 0, 0, 0)
        prev = spans[-1] if spans else None
        if not (0 < base[2] <= limit) and prev is not None and prev[1] < x0:
            x0 = prev[1]             # the base letter's box is not trusted: it starts where the last akshara ends
        spans.append((x0, x1))
    for i, sp in enumerate(spans):
        if sp is None:
            left = next((spans[k][1] for k in range(i - 1, -1, -1) if spans[k] is not None), None)
            right = next((spans[k][0] for k in range(i + 1, len(spans)) if spans[k] is not None), None)
            if left is not None and right is not None and right > left:
                spans[i] = (left, right)
    return spans


def overlap(a: Optional[Span], b: Optional[Span]) -> float:
    """Shared x range as a share of the narrower span (0 to 1)."""
    if a is None or b is None:
        return 0.0
    inter = min(a[1], b[1]) - max(a[0], b[0])
    narrow = min(a[1] - a[0], b[1] - b[0])
    return max(0.0, inter) / narrow if narrow > 0 else 0.0


def inside(part: Optional[Span], whole: Optional[Span]) -> float:
    """Share of `part` that lies within `whole` (0 to 1)."""
    if part is None or whole is None or part[1] <= part[0]:
        return 0.0
    return max(0, min(part[1], whole[1]) - max(part[0], whole[0])) / (part[1] - part[0])


def _union(spans: Sequence[Optional[Span]]) -> Optional[Span]:
    known = [s for s in spans if s is not None]
    if len(known) < len(spans) or not known:
        return None
    return (min(s[0] for s in known), max(s[1] for s in known))


def _fit(parts: Sequence[Optional[Span]], whole: Optional[Span]) -> float:
    """How well one item matches several on the other side: for one, their overlap; for several,
    the least share of any of them that lies within the one (each must really be inside it)."""
    if len(parts) == 1:
        return overlap(parts[0], whole)
    return min(inside(p, whole) for p in parts)


def _best(row: List[float]) -> int:
    """Index of the largest value, or -1 when all are 0."""
    i = max(range(len(row)), key=row.__getitem__, default=-1)
    return i if i >= 0 and row[i] > 0 else -1


def align_line(aksharas: Sequence[Akshara], samples: Sequence[Span], dx: int = 0, min_overlap: float = 0.6,
               sure_overlap: float = 0.8, min_matched: float = 0.5) -> LineAlignment:
    """Align a line's OCR aksharas (boxes in line-image pixels, `dx` = line image's x on the page)
    with its samples (page x spans, in reading order)."""
    spans = akshara_spans(aksharas, dx)
    n, m = len(spans), len(samples)
    ov = [[overlap(spans[i], samples[j]) for j in range(m)] for i in range(n)]
    best_s = [_best(ov[i]) for i in range(n)]                          # each akshara's best sample
    best_a = [_best([ov[i][j] for i in range(n)]) for j in range(m)]   # each sample's best akshara

    INF = float("inf")
    cost = [[INF] * (m + 1) for _ in range(n + 1)]
    back: List[List[Optional[Tuple[int, int]]]] = [[None] * (m + 1) for _ in range(n + 1)]
    cost[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            c = cost[i][j]
            if c == INF:
                continue

            def step(di: int, dj: int, add: float) -> None:
                if c + add < cost[i + di][j + dj]:
                    cost[i + di][j + dj] = c + add
                    back[i + di][j + dj] = (di, dj)
            if i < n:
                step(1, 0, SKIP)
            if j < m:
                step(0, 1, SKIP)
            for k in range(1, MAX_GROUP + 1):
                if i + k <= n and j < m:                               # k aksharas on one sample
                    step(k, 1, 1 - _fit(spans[i:i + k], samples[j]) + GROUP_PENALTY * (k - 1))
                if k > 1 and i < n and j + k <= m:                     # one akshara over k samples
                    step(1, k, 1 - _fit(samples[j:j + k], spans[i]) + GROUP_PENALTY * (k - 1))

    steps: List[Tuple[int, int, int, int]] = []                      # (i, j, aksharas, samples)
    i, j = n, m
    while i or j:
        di, dj = back[i][j]
        i, j = i - di, j - dj
        steps.append((i, j, di, dj))
    steps.reverse()

    matches: List[Match] = []
    for i, j, di, dj in steps:
        if di == 0 or dj != 1:
            continue                                       # skipped, or one akshara over several samples
        idx = tuple(range(i, i + di))
        o = _fit(spans[i:i + di], samples[j])
        agree = all(best_s[a] == j for a in idx) and (di > 1 or best_a[j] == i)
        if o >= sure_overlap or (o >= min_overlap and agree):
            aks = [aksharas[a] for a in idx]
            matches.append(Match(sample=j, aksharas=idx, text="".join(a.text for a in aks),
                                 conf=min(a.conf for a in aks), overlap=round(o, 3),
                                 alternatives=[alt for a in aks for alt in a.alternatives]))
    refused = m > 0 and len(matches) < min_matched * m
    return LineAlignment(matches=[] if refused else matches, spans=spans, refused=refused, steps=steps)

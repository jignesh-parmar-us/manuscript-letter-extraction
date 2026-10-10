"""A language model of aksharas, and correcting a line's uncertain letters with it (C15).

**The model** counts akshara sequences (trigrams, backing off to bigrams and single aksharas, with
Witten-Bell smoothing) in text the book is known to contain: the labels of its Training Data letters in
reading order, its proofread lines and imported text files. Spaces are left out: the manuscripts are
written without them, and the letter sequence is what the readers get wrong.

**Correcting a line** (`correct_line`): every letter has one or more candidate readings with a weight
(the readers' opinion); a sure letter has one. A search over the line (beam of `beam` states, each the
last two aksharas) finds the readings with the best total of `lm_weight` x the model's log probability
plus the log of the candidates' weights. A letter's reading changes only if the change gains at least
`min_gain` (in log probability) for the whole line; every changed letter is reported, so the screen
can show what the language model did.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .aksharas import split_aksharas

START = "<s>"


def tokens(text: str) -> List[str]:
    """The aksharas of a text, without spaces and line breaks."""
    return [a for a in split_aksharas(text.replace(" ", "").replace("\n", "")) if a.strip()]


class LanguageModel:
    """An akshara trigram model with Witten-Bell smoothing."""

    def __init__(self):
        self.c3: Counter = Counter()
        self.c2: Counter = Counter()
        self.c1: Counter = Counter()
        self.ctx2: Counter = Counter()          # count of (a, b) as a context
        self.ctx1: Counter = Counter()
        self.next2: Dict[Tuple[str, str], set] = defaultdict(set)
        self.next1: Dict[str, set] = defaultdict(set)
        self.total = 0
        self.lines = 0

    def add(self, text_or_tokens) -> None:
        """Count one line (a text, or its aksharas)."""
        seq = tokens(text_or_tokens) if isinstance(text_or_tokens, str) else list(text_or_tokens)
        if not seq:
            return
        self.lines += 1
        prev2, prev1 = START, START
        for a in seq:
            self.c3[(prev2, prev1, a)] += 1
            self.ctx2[(prev2, prev1)] += 1
            self.next2[(prev2, prev1)].add(a)
            self.c2[(prev1, a)] += 1
            self.ctx1[prev1] += 1
            self.next1[prev1].add(a)
            self.c1[a] += 1
            self.total += 1
            prev2, prev1 = prev1, a

    def add_all(self, lines: Iterable) -> "LanguageModel":
        for line in lines:
            self.add(line)
        return self

    def _p1(self, a: str) -> float:
        vocab = len(self.c1) + 1                  # +1: an akshara never seen
        return (self.c1.get(a, 0) + 1) / (self.total + vocab)

    def _p2(self, prev1: str, a: str) -> float:
        n, t = self.ctx1.get(prev1, 0), len(self.next1.get(prev1, ()))
        if not n:
            return self._p1(a)
        return (self.c2.get((prev1, a), 0) + t * self._p1(a)) / (n + t)

    def prob(self, prev2: str, prev1: str, a: str) -> float:
        """P(a | prev2 prev1)."""
        n, t = self.ctx2.get((prev2, prev1), 0), len(self.next2.get((prev2, prev1), ()))
        if not n:
            return self._p2(prev1, a)
        return (self.c3.get((prev2, prev1, a), 0) + t * self._p2(prev1, a)) / (n + t)

    def logprob(self, seq: Sequence[str], prev2: str = START, prev1: str = START) -> Tuple[float, str, str]:
        """log P of the aksharas `seq` after (prev2, prev1); and the new last two aksharas."""
        lp = 0.0
        for a in seq:
            lp += math.log(self.prob(prev2, prev1, a))
            prev2, prev1 = prev1, a
        return lp, prev2, prev1

    def __len__(self) -> int:
        return self.total


@dataclass
class Change:
    index: int                                   # the letter's position in the line
    old: str
    new: str
    gain: float                                  # log-probability gain of the line


def _score(lm: LanguageModel, options: Sequence[Sequence[Tuple[str, float]]], pick: Sequence[int],
           lm_weight: float) -> float:
    prev2, prev1, total = START, START, 0.0
    for opts, k in zip(options, pick):
        text, weight = opts[k]
        lp, prev2, prev1 = lm.logprob(tokens(text), prev2, prev1)
        total += lm_weight * lp + math.log(max(weight, 1e-6))
    return total


def correct_line(lm: LanguageModel, options: Sequence[Sequence[Tuple[str, float]]], lm_weight: float = 1.0,
                 min_gain: float = 2.0, beam: int = 20) -> Tuple[List[int], List[Change]]:
    """The best reading of each letter of a line. `options[i]` lists letter i's candidate readings
    (text, weight 0 to 1), the current reading first; a sure letter has only its reading. Returns the
    chosen candidate per letter and the changes (letters whose reading is not the first candidate)."""
    # beam search: state = (last two aksharas) -> (score, picks)
    states: Dict[Tuple[str, str], Tuple[float, List[int]]] = {(START, START): (0.0, [])}
    for opts in options:
        nxt: Dict[Tuple[str, str], Tuple[float, List[int]]] = {}
        for (p2, p1), (score, picks) in states.items():
            for k, (text, weight) in enumerate(opts):
                lp, n2, n1 = lm.logprob(tokens(text), p2, p1)
                s = score + lm_weight * lp + math.log(max(weight, 1e-6))
                if (n2, n1) not in nxt or s > nxt[(n2, n1)][0]:
                    nxt[(n2, n1)] = (s, picks + [k])
        states = dict(sorted(nxt.items(), key=lambda kv: -kv[1][0])[:beam])
    best = max(states.values(), key=lambda v: v[0])[1] if states else []
    # keep only the changes that pay for themselves on their own
    pick = list(best)
    changes: List[Change] = []
    for i, k in enumerate(best):
        if k == 0:
            continue
        back = list(pick)
        back[i] = 0
        gain = _score(lm, options, pick, lm_weight) - _score(lm, options, back, lm_weight)
        if gain >= min_gain:
            changes.append(Change(i, options[i][0][0], options[i][k][0], round(gain, 2)))
        else:
            pick[i] = 0
    return pick, changes


def candidates(current: str, uncertain: bool, tesseract: Optional[Tuple[str, float]],
               reader_top: Sequence[Tuple[str, float]], groups: Sequence[Tuple[str, float]], group_distance: float,
               weights: Tuple[float, float, float] = (1.0, 1.0, 0.5), most: int = 5) -> List[Tuple[str, float]]:
    """A letter's candidate readings for `correct_line`, its current reading first. A sure letter keeps
    only its reading; an uncertain one also gets what the readers saw (Tesseract with its confidence,
    the letter reader's best three, the two nearest groups), weighted by `weights` and normalised."""
    if not uncertain:
        return [(current, 1.0)]
    wt, wr, wg = weights
    score: Counter = Counter()
    if tesseract and tesseract[0]:
        score[tesseract[0]] += wt * tesseract[1] / 100
    for label, p in reader_top:
        score[label] += wr * p
    for label, d in groups:
        if d <= group_distance:
            score[label] += wg * max(0.0, 1 - d)
    total = sum(score.values()) or 1.0
    out = [(current, max(score.get(current, 0.0), 1e-3) / total)]
    out += [(c, v / total) for c, v in score.most_common() if c and c != current][:most - 1]
    return out

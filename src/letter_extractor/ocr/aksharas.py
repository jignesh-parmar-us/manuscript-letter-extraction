"""Split Devanagari text into aksharas, the letter units that Phase 1 cuts (C10).

An akshara is a consonant cluster (consonants joined by virama, each with an optional nukta) with its
vowel signs and marks (candrabindu, anusvara, visarga), or an independent vowel with its marks.
Digits, danda, double danda, avagraha and ॐ are units of their own. A vowel sign or mark with nothing
to attach to (Tesseract produces these) is kept as its own unit and marked `orphan`.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import List, Sequence, Tuple

from .tesseract import Box, Char

VIRAMA = "्"
NUKTA = "़"
JOINERS = {"‌", "‍"}                                  # ZWNJ, ZWJ: kept with the cluster


def _r(a: int, b: int) -> set:
    return {chr(c) for c in range(a, b + 1)}


CONSONANTS = _r(0x0915, 0x0939) | _r(0x0958, 0x095F) | _r(0x0978, 0x097F)
VOWELS = _r(0x0904, 0x0914) | {"ॠ", "ॡ"} | _r(0x0972, 0x0977)
VOWEL_SIGNS = _r(0x093A, 0x093B) | _r(0x093E, 0x094C) | _r(0x094E, 0x094F) | _r(0x0955, 0x0957) | {"ॢ", "ॣ"}
MARKS = _r(0x0900, 0x0903) | _r(0x0951, 0x0954)              # candrabindu, anusvara, visarga, accents
SIGNS = {"।", "॥", "ऽ", "ॐ", "॰"} | _r(0x0966, 0x096F)   # danda, ॥, ऽ, ॐ, ॰, digits


def kind_of(ch: str) -> str:
    if ch in CONSONANTS:
        return "consonant"
    if ch in VOWELS:
        return "vowel"
    if ch in VOWEL_SIGNS:
        return "sign"
    if ch in MARKS:
        return "mark"
    if ch == VIRAMA:
        return "virama"
    if ch == NUKTA:
        return "nukta"
    if ch in JOINERS:
        return "joiner"
    if ch.isspace():
        return "space"
    return "other"                                           # danda, digits, ॐ, Latin, punctuation


def split_spans(text: str) -> List[Tuple[int, int, bool]]:
    """(start, end, orphan) of each akshara in `text` (spaces are skipped). `text` should be NFC."""
    spans: List[Tuple[int, int, bool]] = []
    i, n = 0, len(text)
    while i < n:
        k = kind_of(text[i])
        if k == "space":
            i += 1
            continue
        start = i
        if k == "consonant":
            i += 1
            while i < n:
                k2 = kind_of(text[i])
                if k2 in ("nukta", "joiner"):
                    i += 1
                elif k2 == "virama":
                    i += 1
                    while i < n and kind_of(text[i]) == "joiner":
                        i += 1
                    if i < n and kind_of(text[i]) == "consonant":
                        i += 1                               # a conjunct continues
                    else:
                        break                                # a final halant ends the akshara
                else:
                    break
            while i < n and kind_of(text[i]) in ("sign", "mark", "nukta"):
                i += 1
            spans.append((start, i, False))
        elif k == "vowel" or text[i] == "ॐ":            # independent vowel or ॐ, with its marks
            i += 1
            while i < n and kind_of(text[i]) in ("sign", "mark"):
                i += 1                                       # (sign: ऑ written as अ + ॉ, for example)
            spans.append((start, i, False))
        elif k in ("sign", "mark", "virama", "nukta", "joiner"):
            i += 1                                           # nothing to attach to
            while i < n and kind_of(text[i]) in ("sign", "mark"):
                i += 1
            spans.append((start, i, True))
        else:
            i += 1
            spans.append((start, i, False))
    return spans


def split_aksharas(text: str) -> List[str]:
    text = unicodedata.normalize("NFC", text)
    return [text[a:b] for a, b, _ in split_spans(text)]


@dataclass
class Akshara:
    text: str
    box: Box                     # union of its characters' boxes (x, y, w, h); (0, 0, 0, 0) if none had one
    conf: float                  # lowest confidence of its characters
    orphan: bool = False
    chars: List[Char] = field(default_factory=list)

    @property
    def alternatives(self) -> List[List[Tuple[str, float]]]:
        """Per character, Tesseract's alternatives (for the dictionary step, C15)."""
        return [c.alternatives for c in self.chars]


def union_box(boxes: Sequence[Box]) -> Box:
    boxes = [b for b in boxes if b[2] > 0 or b[3] > 0]
    if not boxes:
        return (0, 0, 0, 0)
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    return (x0, y0, x1 - x0, y1 - y0)


def group_chars(chars: Sequence[Char]) -> List[Akshara]:
    """Aksharas from OCR characters, each with the box and confidence of the characters in it.

    A Tesseract character is usually one code point but can be several; the text is split as a whole
    and every code point remembers which character it came from. The text is not NFC-normalised here,
    so positions stay valid; NFC is applied to each akshara's text."""
    text, owner = "", []
    for idx, c in enumerate(chars):
        text += c.text
        owner += [idx] * len(c.text)
    out: List[Akshara] = []
    for a, b, orphan in split_spans(text):
        idxs: List[int] = sorted(set(owner[a:b]))
        cs = [chars[i] for i in idxs]
        out.append(Akshara(text=unicodedata.normalize("NFC", text[a:b]), box=union_box([c.box for c in cs]),
                           conf=min((c.conf for c in cs), default=0.0), orphan=orphan, chars=cs))
    return out


def line_aksharas(words) -> List[Akshara]:
    """Aksharas of a whole line, word by word (an akshara never spans a space)."""
    out: List[Akshara] = []
    for w in words:
        out += group_chars(w.chars)
    return out


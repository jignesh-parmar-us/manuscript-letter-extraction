"""Reading a page's letters into text (C16b): the rules, without the database or Tesseract.

Each cut letter can have two readings:
- **Tesseract's** (printed books): the akshara its line reading puts on the letter (C11's alignment),
  with Tesseract's confidence (0 to 100);
- **the nearest labelled group** of the book (the C13 method on the book's own groups): its label and
  the distance of the letter's fingerprint to the group's centre.

`choose` decides the letter's text, a confidence from 0 to 1 and whether it is uncertain:
- both agree: sure (0.99);
- they disagree: when the group is not close (distance above `text_group_close`, 0.45) and Tesseract
  is very sure (at least `text_tesseract_trust`, 95), Tesseract's reading stands, as if alone (measured
  on the printed book: right in 10 of 11 such cases). Otherwise uncertain (0.4): Tesseract's reading is
  kept when its confidence is at least `text_tesseract_sure` (90), otherwise the group's;
- only Tesseract: 0.8 x its confidence / 100 (unconfirmed by the book's own letters);
- only a group within `group_distance`: 1 - its distance;
- neither: unknown (no text, 0).
A letter is uncertain when its confidence is below `text_min_confidence` (0.6) or the readers disagree.

`line_text` joins a line's letters; printed books get a space where the gap between two letters is wider
than `text_space_gap` x the line's median letter width (handwriting gets none: FR-12).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import List, Optional, Sequence, Tuple

from ..config import Config

UNKNOWN = ""                                   # a letter no reader could read


@dataclass
class LetterText:
    sample_id: int
    line: int
    box: Tuple[int, int, int, int]             # page coordinates
    text: str                                  # Devanagari NFC; "" when unknown
    conf: float                                # 0 to 1
    source: str                                # both | tesseract | groups | none
    uncertain: bool
    space_before: bool = False
    readings: List[Tuple[str, str, float]] = field(default_factory=list)   # (source, text, score) seen


def choose(tesseract: Optional[Tuple[str, float]], group: Optional[Tuple[str, float]], cfg: Config,
           kind: str = "letter") -> Tuple[str, float, str, bool]:
    """(text, confidence 0 to 1, source, uncertain) of one letter from its readings: `tesseract` is
    (text, confidence 0 to 100), `group` is (label, distance); either may be None."""
    t = tesseract if tesseract and tesseract[0] else None
    g = group if group and group[0] and group[1] <= cfg.group_distance else None
    if t and g:
        if t[0] == g[0]:
            return t[0], 0.99, "both", False
        if g[1] > cfg.text_group_close and t[1] >= cfg.text_tesseract_trust:
            conf = 0.8 * t[1] / 100
            return t[0], round(conf, 3), "tesseract", conf < cfg.text_min_confidence
        text = t[0] if t[1] >= cfg.text_tesseract_sure else g[0]
        return text, 0.4, ("tesseract" if text == t[0] else "groups"), True
    if t:
        conf = 0.8 * t[1] / 100
        return t[0], round(conf, 3), "tesseract", conf < cfg.text_min_confidence
    if g:
        conf = max(0.0, 1.0 - g[1])
        return g[0], round(conf, 3), "groups", conf < cfg.text_min_confidence
    if kind == "danda":                                    # a danda's shape is plain: keep it
        return "।", 0.7, "none", False
    return UNKNOWN, 0.0, "none", True


def mark_spaces(letters: Sequence[LetterText], cfg: Config, printed: bool) -> None:
    """Set `space_before` on letters that follow a word gap (printed books only)."""
    if not printed or len(letters) < 2:
        return
    widths = [x.box[2] for x in letters if x.box[2] > 0]
    if not widths:
        return
    gap = cfg.text_space_gap * median(widths)
    for a, b in zip(letters, letters[1:]):
        b.space_before = b.box[0] - (a.box[0] + a.box[2]) > gap


def shown(letter: LetterText, marker: str) -> str:
    """The letter as written in a text file: its text, or the uncertain-letter marker."""
    if letter.text == UNKNOWN:
        return "[?]" if marker != "none" else "?"
    if not letter.uncertain or marker == "none":
        return letter.text
    if marker == "guess":
        return f"[?{letter.text}]"
    return "[?]"


def line_text(letters: Sequence[LetterText], marker: str = "none") -> str:
    """A line's Devanagari text, with spaces where `mark_spaces` found word gaps."""
    return "".join((" " if x.space_before else "") + shown(x, marker) for x in letters)

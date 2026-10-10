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

`vote` is used instead when the book has a **letter reader** (C14), which reads every letter with a
probability, and the letter is one the reader was taught (`taught`): a reader knows only the labels of
the groups it learned from (reviewed ones, by default), and reads any other letter confidently as the
nearest one it knows. Those letters keep `choose`. The three readers vote (measured on the printed
book, each page read by a reader and group centres that never saw it, TUNING_PHASE2.md: on reviewed
letters CER 10.4% -> 9.8%, 11% of the letters marked; letters wrong 8.6% where the reader knows every
label, so it gains as more groups are reviewed):
- Tesseract and the reader agree: sure;
- the reader and the nearest group agree against Tesseract: the reader's, uncertain unless it is at
  least `text_reader_sure` (0.95) sure;
- Tesseract and the group agree against the reader: Tesseract's, uncertain if the reader was sure;
- nobody agrees: the reader's if it is sure, otherwise Tesseract's; uncertain either way.
Without Tesseract (handwriting) the reader and the group decide alone (not measured yet).

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


def taught(tesseract: Optional[Tuple[str, float]], group: Optional[Tuple[str, float]], classes, cfg: Config) -> bool:
    """Whether the letter reader may vote on this letter: what Tesseract read (or, where it read nothing,
    the nearest group) is a label the reader knows."""
    if tesseract and tesseract[0]:
        return tesseract[0] in classes
    return not (group and group[0] and group[1] <= cfg.group_distance) or group[0] in classes


def vote(tesseract: Optional[Tuple[str, float]], reader: Tuple[str, float], group: Optional[Tuple[str, float]],
         cfg: Config) -> Tuple[str, float, str, bool]:
    """(text, confidence 0 to 1, source, uncertain) of one letter read by the letter reader too:
    `reader` is (label, probability 0 to 1); the others as in `choose`."""
    tt = tesseract[0] if tesseract and tesseract[0] else ""
    rl, p = reader
    gl = group[0] if group and group[0] and group[1] <= cfg.group_distance else ""
    sure = p >= cfg.text_reader_sure
    if tt and tt == rl:
        return rl, 0.99, "tesseract+reader", False
    if not tt:                                              # handwriting, or Tesseract read nothing here
        if gl == rl:
            return rl, round(p, 3), "reader+groups", not sure
        return rl, round(p, 3), "reader", not sure or bool(gl)       # a group that disagrees: uncertain
    if gl and gl == rl:
        return rl, round(p, 3), "reader+groups", not sure
    if gl and gl == tt:
        return tt, 0.5 if sure else 0.8, "tesseract+groups", sure
    if sure:
        return rl, 0.5, "reader", True
    return tt, 0.4, "tesseract", True


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

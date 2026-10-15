"""Try it (F6, F7): how the newest build draws a typed text, akshara by akshara.

Each akshara (split as the reading app does, `ocr.aksharas.split_aksharas`) is covered the way the font's
rules cover it: the longest group label it starts with is the book's akshara glyph (कि in किं), and the rest
is taken letter by letter (the book's letter, a filled one, or a missing box). The akshara is then:

  book     one glyph of the book's own
  pieced   put together from several of the book's glyphs (no group of its own, e.g. a conjunct without a group)
  filled   holds a letter filled from the normal font (always marked)
  missing  holds a letter the font has only as a box
  other    not Devanagari (Latin, Gujarati, …): this font does not draw it

Each piece has its `start` in the (NFC) text, so the screen can select it, and a non-book akshara its
`detail`: the letters that are filled or missing in it (F7's check line). Only the build's report is read;
no font file is opened.
"""
from __future__ import annotations

import unicodedata
from typing import Dict, List

from letter_extractor.ocr.aksharas import split_spans

KINDS = ("book", "pieced", "filled", "missing", "other")
ZERO_WIDTH = ("‌", "‍")                    # ZWNJ, ZWJ: invisible


def _devanagari(ch: str) -> bool:
    return "ऀ" <= ch <= "ॿ" or ch in ZERO_WIDTH


def classify(text: str, report: Dict) -> Dict:
    labels = set(report.get("labels", []))
    filled = set(report.get("filled", []))
    longest = max((len(label) for label in labels), default=1)
    text = unicodedata.normalize("NFC", text)
    out: List[Dict] = []
    pos = 0
    for start, end, _ in split_spans(text):
        if start > pos:
            out.append({"text": text[pos:start], "kind": "space", "start": pos})
        ak = text[start:end]
        pos = end
        if not all(_devanagari(c) for c in ak):
            if out and out[-1]["kind"] == "other":           # one piece for a Latin (or other) word
                out[-1]["text"] += ak
            else:
                out.append({"text": ak, "kind": "other", "start": start})
            continue
        parts, rest, detail = [], ak, []
        while rest:
            n = next((k for k in range(min(longest, len(rest)), 0, -1) if rest[:k] in labels), 0)
            if n:
                parts.append("book")
                rest = rest[n:]
                continue
            ch, rest = rest[0], rest[1:]
            if ch in ZERO_WIDTH:
                continue
            part = "filled" if ch in filled else "missing"
            parts.append(part)
            detail.append({"char": ch, "kind": part})
        kind = ("missing" if "missing" in parts else "filled" if "filled" in parts
                else "book" if len(parts) == 1 else "pieced")
        piece = {"text": ak, "kind": kind, "start": start}
        if kind != "book":
            piece["detail"] = detail
        out.append(piece)
    if pos < len(text):
        out.append({"text": text[pos:], "kind": "space", "start": pos})
    counts = {k: sum(1 for a in out if a["kind"] == k) for k in KINDS}
    return {"aksharas": out, "counts": counts, "build": report.get("build")}

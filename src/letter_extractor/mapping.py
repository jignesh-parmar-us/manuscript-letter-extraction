"""Devanagari <-> Gujarati mapping and letter labels (C5b, Section 4 of the requirements).

Labels are stored in one canonical form, **Devanagari** (NFC), whichever script the user typed them
in; the Gujarati form is derived from it.

Mapping rule: a Devanagari character maps to the Gujarati character at code point + 0x180, but only
when Unicode gives that character the same name (with GUJARATI for DEVANAGARI). The +0x180 position
is not always the same letter: for U+0971 it is the Gujarati rupee sign, for U+097A-U+097F Gujarati
nukta signs. Everything else comes from the editable table `data/mapping_dev_guj.csv`:
- danda and double danda stay Devanagari (Gujarati has none);
- letters with no Gujarati letter but a nukta form (ऩ ऱ ऴ, क़ ... य़) are written as letter + nukta;
- the rest (short vowels, Vedic signs, ...) is kept in Devanagari and can be listed with `unmapped()`.

A label must be **one akshara**: an independent vowel, or a consonant cluster (consonants joined by
halant, so conjuncts and reph) with at most one vowel sign or a final halant, then optional
chandrabindu / anusvara / visarga; or a digit, danda, double danda, avagraha or Om. The review app
also allows a **word**: up to `MAX_WORD` such aksharas in a row (`words=True`), for samples that are
a whole word (a cut that could not be split, an abbreviation); they form the category `words`.
"""
from __future__ import annotations

import csv
import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DATA = Path(__file__).resolve().parent / "data" / "mapping_dev_guj.csv"
OFFSET = 0x180
DEV_BLOCK = range(0x0900, 0x0980)
GUJ_BLOCK = range(0x0A80, 0x0B00)

ZERO_WIDTH = {"​", "‌", "‍", "⁠", "﻿"}

# ---- character classes (Devanagari, after NFD) ------------------------------------------------
VOWELS = "अआइईउऊऋॠऌॡऍऎएऐऑऒ" \
         "ओऔऄॲॳॴॵॶॷ"      # in alphabet order
CONSONANTS = "".join(chr(c) for c in range(0x0915, 0x093A)) + "".join(chr(c) for c in range(0x0978, 0x0980))
NUKTA = "़"
HALANT = "्"
MATRAS = "".join(chr(c) for c in (0x093A, 0x093B, *range(0x093E, 0x094D), 0x094E, 0x094F,
                                  0x0955, 0x0956, 0x0957, 0x0962, 0x0963))
MARKS = "ऀँंः॒॑॓॔"          # (inverted) chandrabindu, anusvara,
                                                                     # visarga, stress signs
DIGITS = "".join(chr(c) for c in range(0x0966, 0x0970))
PUNCTUATION = "।॥ऽॐ॰"                      # । ॥ ऽ ॐ ॰

CATEGORIES = ("vowels", "consonants", "conjuncts", "digits", "punctuation", "words")
MAX_WORD = 12                       # aksharas in a word label
_MATRA_SET = frozenset(MATRAS)
_CONSONANT_SET = frozenset(CONSONANTS)


def _cls(ch: str) -> str:
    if ch in VOWELS:
        return "V"
    if ch in CONSONANTS:
        return "C"
    if ch == NUKTA:
        return "N"
    if ch == HALANT:
        return "H"
    if ch in MATRAS:
        return "M"
    if ch in MARKS:
        return "B"
    if ch in DIGITS:
        return "D"
    if ch in PUNCTUATION:
        return "P"
    return "?"


_AKSHARA = re.compile(r"VB{0,2}|CN?(?:HCN?)*(?:M|H)?B{0,2}|D|P")
_TOKEN = re.compile(r"VB{0,2}|CN?(?:HCN?)*(?:M|H)?B{0,2}|D|P|.")


class LabelError(ValueError):
    """The text is not a single letter (the message says why)."""


@dataclass
class Mapping:
    """The Devanagari -> Gujarati table (rule + exceptions) and its reverse."""
    to_guj: Dict[str, str] = field(default_factory=dict)   # one Devanagari character -> Gujarati text
    to_dev: Dict[str, str] = field(default_factory=dict)   # one Gujarati character -> Devanagari text
    kept: List[str] = field(default_factory=list)          # Devanagari characters with no Gujarati form
    digits: str = "gujarati"                                # or "western"

    def gujarati(self, dev: str) -> str:
        out = []
        for ch in unicodedata.normalize("NFC", dev):
            if self.digits == "western" and ch in DIGITS:
                out.append(str(ord(ch) - 0x0966))
            else:
                out.append(self.to_guj.get(ch, ch))
        return "".join(out)

    def devanagari(self, text: str) -> str:
        """Gujarati (and Western digits) to Devanagari; Devanagari passes unchanged."""
        out = []
        for ch in unicodedata.normalize("NFC", text):
            if "0" <= ch <= "9":
                out.append(chr(0x0966 + int(ch)))
            elif ord(ch) in GUJ_BLOCK:
                if ch not in self.to_dev:
                    raise LabelError(f"'{ch}' ({_cp(ch)}) has no Devanagari equivalent")
                out.append(self.to_dev[ch])
            else:
                out.append(ch)
        return unicodedata.normalize("NFC", "".join(out))


def _same_name(dev: str, guj: str) -> bool:
    try:
        return unicodedata.name(dev).replace("DEVANAGARI", "GUJARATI", 1) == unicodedata.name(guj)
    except ValueError:
        return False


def _read_table(path: Path) -> List[Tuple[str, str]]:
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        lines = [ln for ln in f if not ln.startswith("#")]
    for row in csv.DictReader(lines):
        # keys as written: U+0958-U+095F (क़ ...) are one character here, while normalized text holds
        # them as letter + nukta, which the default rule already maps; their rows document the rule
        dev = (row.get("devanagari") or "").strip()
        guj = unicodedata.normalize("NFC", (row.get("gujarati") or "").strip())
        if len(dev) != 1 or ord(dev) not in DEV_BLOCK:
            raise ValueError(f"{path}: '{dev}' is not one Devanagari character")
        rows.append((dev, guj))
    return rows


@lru_cache(maxsize=8)
def load_mapping(path: Optional[str] = None, digits: str = "gujarati") -> Mapping:
    """The mapping from the built-in table, or from the user's copy at `path`."""
    if digits not in ("gujarati", "western"):
        raise ValueError(f"digits must be 'gujarati' or 'western', not '{digits}'")
    m = Mapping(digits=digits)
    for cp in DEV_BLOCK:
        dev, guj = chr(cp), chr(cp + OFFSET)
        if _same_name(dev, guj):
            m.to_guj[dev] = guj
    for dev, guj in _read_table(Path(path) if path else DATA):
        if guj:
            m.to_guj[dev] = guj
        else:
            m.to_guj.pop(dev, None)
            m.kept.append(dev)
    for dev, guj in m.to_guj.items():
        if len(guj) == 1 and ord(guj) in GUJ_BLOCK and guj not in m.to_dev:
            m.to_dev[guj] = dev
    return m


def mapping_for(cfg) -> Mapping:
    """The mapping a book's settings ask for (`digits`, `mapping_file`)."""
    return load_mapping(cfg.mapping_file or None, cfg.digits)


def _cp(text: str) -> str:
    return " ".join(f"U+{ord(c):04X}" for c in text)


def code_points(text: str) -> str:
    """'U+0915 U+093F' for कि."""
    return _cp(text)


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFC", text.strip())
    return "".join(ch for ch in text if ch not in ZERO_WIDTH and not ch.isspace())


def _split(dev: str) -> List[str]:
    """Split Devanagari text into aksharas (and single stray characters)."""
    nfd = unicodedata.normalize("NFD", dev)
    classes = "".join(_cls(c) for c in nfd)
    return [unicodedata.normalize("NFC", nfd[m.start():m.end()]) for m in _TOKEN.finditer(classes)]


def canonical_label(text: str, mapping: Optional[Mapping] = None, words: bool = False) -> str:
    """The canonical (Devanagari, NFC) form of a label typed in Devanagari or Gujarati.
    Raises LabelError with a readable reason if the text is not one letter (with `words`: not one
    letter or a word of whole letters)."""
    m = mapping or load_mapping()
    t = _clean(text)
    if not t:
        raise LabelError("the label is empty")
    for ch in t:
        cp = ord(ch)
        if not (cp in DEV_BLOCK or cp in GUJ_BLOCK or "0" <= ch <= "9"):
            raise LabelError(f"'{ch}' is neither Devanagari nor Gujarati")
    dev = m.devanagari(t)
    nfd = unicodedata.normalize("NFD", dev)
    classes = "".join(_cls(c) for c in nfd)
    if "?" in classes:
        bad = nfd[classes.index("?")]
        raise LabelError(f"'{bad}' ({_cp(bad)}) cannot be part of a letter")
    if _AKSHARA.fullmatch(classes):
        return dev
    parts = _split(dev)
    if classes[0] in "MBHN":
        raise LabelError(f"'{parts[0]}' needs a letter before it")
    if not words:
        raise LabelError("more than one letter: " + " + ".join(parts))
    for i, part in enumerate(parts):
        if not _AKSHARA.fullmatch("".join(_cls(c) for c in unicodedata.normalize("NFD", part))):
            raise LabelError(f"'{part}' needs a letter before it (after '{parts[i - 1]}')")
    if len(parts) > MAX_WORD:
        raise LabelError(f"a word label can have at most {MAX_WORD} letters, this one has {len(parts)}")
    return dev


def letters(label: str) -> List[str]:
    """The aksharas of a label (one for a letter, several for a word)."""
    return _split(label)


def is_label(text: str, mapping: Optional[Mapping] = None, words: bool = False) -> bool:
    try:
        canonical_label(text, mapping, words)
        return True
    except LabelError:
        return False


def to_gujarati(dev: str, mapping: Optional[Mapping] = None) -> str:
    return (mapping or load_mapping()).gujarati(dev)


def to_devanagari(text: str, mapping: Optional[Mapping] = None) -> str:
    return (mapping or load_mapping()).devanagari(text)


def category(label: str) -> str:
    """Dataset category of a canonical label (FR-9)."""
    if len(_split(label)) > 1:
        return "words"
    nfd = unicodedata.normalize("NFD", label)
    classes = "".join(_cls(c) for c in nfd)
    if classes.startswith("D"):
        return "digits"
    if classes.startswith("P"):
        return "punctuation"
    if classes.startswith("V"):
        return "vowels"
    return "conjuncts" if classes.count("C") >= 2 else "consonants"


def sort_key(label: str) -> Tuple:
    """Alphabet order: vowels, consonants (ક to હ, then by matra), conjuncts, digits, punctuation."""
    nfd = unicodedata.normalize("NFD", label)

    def rank(ch: str) -> int:
        if ch in VOWELS:
            return VOWELS.index(ch)
        return 100 + ord(ch)

    return (CATEGORIES.index(category(label)), tuple(rank(c) for c in nfd))


# ---- transliteration (readable ASCII for folder names) -------------------------------------
_TR_VOWEL = {"अ": "a", "आ": "aa", "इ": "i", "ई": "ii", "उ": "u", "ऊ": "uu", "ऋ": "ri", "ॠ": "rii", "ऌ": "li",
             "ॡ": "lii", "ऍ": "ae", "ए": "e", "ऐ": "ai", "ऑ": "ao", "ओ": "o", "औ": "au"}
_TR_CONS = {"क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ng", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh",
            "ञ": "ny", "ट": "tt", "ठ": "tth", "ड": "dd", "ढ": "ddh", "ण": "nn", "त": "t", "थ": "th", "द": "d",
            "ध": "dh", "न": "n", "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r",
            "ल": "l", "ळ": "ll", "व": "v", "श": "sh", "ष": "ss", "स": "s", "ह": "h"}
_TR_MATRA = {"ा": "aa", "ि": "i", "ी": "ii", "ु": "u", "ू": "uu", "ृ": "ri",
             "ॄ": "rii", "ॢ": "li", "ॣ": "lii", "ॅ": "ae", "े": "e", "ै": "ai",
             "ॉ": "ao", "ो": "o", "ौ": "au"}
_TR_MARK = {"ँ": "n", "ं": "m", "ः": "h"}
_TR_PUNCT = {"।": "danda", "॥": "double-danda", "ऽ": "avagraha", "ॐ": "om",
             "॰": "abbreviation"}


def transliterate(label: str) -> str:
    """Lower-case ASCII, for reading only (कि -> ki, क्ष -> kssa, श्री -> shrii)."""
    nfd = unicodedata.normalize("NFD", label)
    out: List[str] = []
    for i, ch in enumerate(nfd):
        nxt = nfd[i + 1] if i + 1 < len(nfd) else ""
        nukta = nxt == NUKTA and ch in _CONSONANT_SET
        if nukta:
            nxt = nfd[i + 2] if i + 2 < len(nfd) else ""
        inherent = nxt not in _MATRA_SET and nxt != HALANT      # (sets: "" is "in" every string)
        if ch in _CONSONANT_SET:
            out.append(_TR_CONS.get(ch, f"u{ord(ch):04x}") + ("x" if nukta else ""))
            if inherent:
                out.append("a")                      # inherent vowel
        elif ch == NUKTA:
            if not (i and nfd[i - 1] in _CONSONANT_SET):
                out.append("x")
        elif ch == HALANT:
            pass
        elif ch in _TR_VOWEL:
            out.append(_TR_VOWEL[ch])
        elif ch in _TR_MATRA:
            out.append(_TR_MATRA[ch])
        elif ch in _TR_MARK:
            out.append(_TR_MARK[ch])
        elif ch in DIGITS:
            out.append(str(ord(ch) - 0x0966))
        elif ch in _TR_PUNCT:
            out.append(_TR_PUNCT[ch])
        else:
            out.append(f"u{ord(ch):04x}")
    return "".join(out)


def safe_name(label: str, mapping: Optional[Mapping] = None) -> str:
    """Folder name valid on Windows and macOS: transliteration + Gujarati code points
    (कि -> ki__U0A95-U0ABF). The code points make it unique. Long labels (words) would make paths
    too long for Windows, so above 8 code points a short hash of them replaces the list."""
    guj = to_gujarati(label, mapping)
    if len(guj) > 8:
        digest = hashlib.sha1(guj.encode("utf-8")).hexdigest()[:10]
        return f"{transliterate(label)[:40]}__h{digest}"
    return f"{transliterate(label)}__" + "-".join(f"U{ord(c):04X}" for c in guj)


def unmapped(text: str, mapping: Optional[Mapping] = None) -> List[str]:
    """Devanagari characters of `text` that have no Gujarati form and stay Devanagari (except dandas,
    which Gujarati uses as they are)."""
    m = mapping or load_mapping()
    return [ch for ch in unicodedata.normalize("NFC", text) if ch in m.kept]


def describe(text: str, mapping: Optional[Mapping] = None, words: bool = False) -> Dict:
    """Everything the screens show for a label being typed: canonical form, both scripts, code
    points, category, its letters; or the reason it is not a letter."""
    m = mapping or load_mapping()
    try:
        dev = canonical_label(text, m, words)
    except LabelError as e:
        return {"ok": False, "error": str(e)}
    guj = m.gujarati(dev)
    return {"ok": True, "devanagari": dev, "gujarati": guj, "code_points_devanagari": code_points(dev),
            "code_points_gujarati": code_points(guj), "category": category(dev),
            "transliteration": transliterate(dev), "safe_name": safe_name(dev, m),
            "kept_in_devanagari": unmapped(dev, m), "letters": len(_split(dev))}

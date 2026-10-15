"""Generated letters (F9, F10): vowel signs, marks, the virama, half forms, the reph and the rakar, cut from the
book's own aksharas.

A printed book never prints a vowel sign alone, so every akshara the book did not print fell back to a box
or a Noto letter. Here a sign S is cut out of the book's aksharas:

  1. **Pairs:** every consonant glyph C whose akshara C+S is also a glyph (क / का, ख / खा …), at most MAX_PAIRS,
     each pair once (fairness rule: never by group size or how often it is printed).
  2. **Line up:** C is placed inside C+S where it overlaps most (`cv2.matchTemplate`), searched only near
     where their measured places (F3) put it, so a lookalike part elsewhere cannot win.
  3. **Subtract:** what is left of C+S when C (grown by GROW) is taken away, in the place where S belongs:
     right of C (ा ी ो ौ ॉ ः, and their hooks above the headline), left of it (ि, with its hook), above its
     top (े ै ं ँ) or below its foot (ु ू ृ ् ़). Specks are dropped.
  4. **Average** the pieces as F2 averages copies, after leaving out a piece unlike all the others (ODD:
     the pair was not this sign); the median overlap of every pair of pieces is the agreement; fewer than FEW pairs is marked "few examples". Below MIN_AGREE the pieces are not one shape
     and the sign is **not** generated (book 6: ृ 0.27 from 5 pairs, ् 0.02 from 2): fill or draw it instead.
  5. **Where it sits:** the median offset from C: for signs right of C and marks, from C's right edge; for ि
     (drawn before C), its right end from C's left edge. Heights against the baseline, and against C's
     headline (F8), so with an even headline the sign meets the font's headline.

F10 cuts the joined forms the same way, so conjuncts the book did not print join as print does:
  - **half form** of X (key `half:X`): from X्Y − Y, for every consonant Y with both glyphs (Y not र);
    what is left of Y, drawn before it (like ि);
  - **reph** (key `reph`): from र्Y − Y: what is above Y, a mark over the end of the glyph before it;
  - **rakar** (key `rakar`): from X्र − X: what is below X, a mark under the glyph before it.

Each sign is marked **generated** on Font Maker's screens (not in the font, decided 2026-10-16). Its image is
in `glyphs/generated/`, its numbers in `glyphs/generated/<code>.json`; `key` (the pairs' glyph fingerprints)
tells when the book's glyphs changed and the sign must be cut again.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from statistics import median
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from .glyphs import SCALE, align, crop, iou

VIRAMA = "्"
RA = "र"

SIGN_KIND = {
    "ा": "right", "ी": "right", "ो": "right", "ौ": "right", "ॉ": "right", "ः": "right",
    "ि": "left",
    "े": "above", "ै": "above", "ं": "above", "ँ": "above",
    "ु": "below", "ू": "below", "ृ": "below", "्": "below", "़": "below",
}
CONSONANTS = {chr(c) for c in range(0x0915, 0x093A)}
MAX_PAIRS = 24
FEW = 3
MIN_AGREE = 0.45        # pieces agreeing less than this are not one sign: it is not generated
GROW = 2.0              # page pixels: C is grown this much before it is taken away
SEARCH = 3.0            # page pixels: how far from its measured place C is looked for, up and down
SPECK = 0.1             # of the sign's largest piece: smaller pieces are dropped (slivers where the
                        # letter's averaged edge differs a little from the akshara's)
ODD = 0.3               # a piece overlapping the others less than this (median) is not the same sign: left
                        # out before averaging (book 6: र्य is printed with another form, not a reph)


def code(key: str) -> str:
    """A file name for a sign or form: 093E, half-0915, reph, rakar."""
    if key.startswith("half:"):
        return f"half-{ord(key[5]):04X}"
    if key in ("reph", "rakar"):
        return key
    return "-".join(f"{ord(c):04X}" for c in key)


def glyph_name(key: str) -> str:
    """The glyph's name in the font: uni093E for a sign, half_0915, reph, rakar for the joined forms."""
    if key.startswith("half:"):
        return f"half_{ord(key[5]):04X}"
    if key in ("reph", "rakar"):
        return key
    return f"uni{ord(key):04X}"


def read(folder: Path, glyph: Dict) -> Optional[np.ndarray]:
    img = cv2.imread(str(folder / glyph["image"]), cv2.IMREAD_GRAYSCALE)
    return None if img is None else img < 128


def kind_of(key: str) -> str:
    """Where a form's piece is: right / left / above / below of the glyph it is cut from (F9, F10)."""
    if key.startswith("half:"):
        return "half"
    if key == "reph":
        return "reph"
    if key == "rakar":
        return "rakar"
    return SIGN_KIND[key]


REGION = {"half": "left_only", "reph": "above", "rakar": "all"}   # the rakar crosses the letter's foot
SPECIAL = {"क्ष", "ज्ञ", "त्र", "श्र"}  # joined shapes of their own, not "half form + letter": never cut from
MIN_FORM_PAIRS = 2      # a joined form (F10) needs this many different conjuncts: from one, a shape of its own
                        # (book 6: half क from क्ष, half ह from ह्म) cannot be told from a half form


def pairs_for(key: str, glyphs: List[Dict]) -> List[Tuple[Dict, Dict]]:
    """(base, whole) glyph pairs the form is cut from, each once, in label order, at most MAX_PAIRS:
    a sign S from (C, C+S); `half:X` from (Y, X्Y); `reph` from (Y, र्Y); `rakar` from (X, X्र)."""
    by_label = {g["label_dev"]: g for g in glyphs if not g.get("left_out")}
    out = []
    for c in sorted(CONSONANTS):
        if key.startswith("half:"):
            whole = key[5:] + VIRAMA + c
            if c == RA:
                continue
        elif key == "reph":
            whole = RA + VIRAMA + c
        elif key == "rakar":
            whole = c + VIRAMA + RA
        else:
            whole = c + key
        if c in by_label and whole in by_label and whole not in SPECIAL:
            out.append((by_label[c], by_label[whole]))
    return out[:MAX_PAIRS]


def available(glyphs: List[Dict]) -> List[str]:
    """The joined forms (F10) the book gives at least one pair for: half forms, reph, rakar."""
    keys = [f"half:{c}" for c in sorted(CONSONANTS) if c != RA] + ["reph", "rakar"]
    return [k for k in keys if pairs_for(k, glyphs)]


def is_form(key: str) -> bool:
    return key.startswith("half:") or key in ("reph", "rakar")


def place_inside(base: np.ndarray, whole: np.ndarray, dy: int, search: int) -> Tuple[int, int]:
    """Where `base` sits inside `whole` (its top-left in `whole`'s pixels): most overlap, with its top within
    `search` rows of `dy`."""
    ph, pw = base.shape
    padded = np.zeros((whole.shape[0] + 2 * ph, whole.shape[1] + 2 * pw), np.float32)
    padded[ph:ph + whole.shape[0], pw:pw + whole.shape[1]] = whole
    score = cv2.matchTemplate(padded, base.astype(np.float32), cv2.TM_CCORR)
    lo = max(0, dy + ph - search)
    hi = min(score.shape[0], dy + ph + search + 1)
    window = score[lo:hi]
    y, x = np.unravel_index(int(np.argmax(window)), window.shape)
    return int(y + lo - ph), int(x - pw)


def cut(base: np.ndarray, whole: np.ndarray, at: Tuple[int, int], kind: str) -> Optional[Tuple[np.ndarray, Tuple[int, int, int, int]]]:
    """The sign: `whole` without `base` (placed `at`, grown), in the sign's place. Returns the piece and its
    box (x0, y0, x1, y1) in `whole`'s pixels, or None."""
    y, x = at
    h, w = whole.shape
    placed = np.zeros_like(whole)
    ys, xs = slice(max(0, y), min(h, y + base.shape[0])), slice(max(0, x), min(w, x + base.shape[1]))
    placed[ys, xs] = base[ys.start - y:ys.stop - y, xs.start - x:xs.stop - x]
    k = max(1, int(round(GROW * SCALE)))
    grown = cv2.dilate(placed.astype(np.uint8), np.ones((2 * k + 1, 2 * k + 1), np.uint8)) > 0
    rest = whole & ~grown
    cx0, cy0 = max(0, x), max(0, y)
    cx1, cy1 = min(w, x + base.shape[1]), min(h, y + base.shape[0])
    yy, xx = np.mgrid[0:h, 0:w]
    m = k
    region = {
        "right": (xx >= cx1 - m) | (yy < cy0 - m),
        "left": (xx <= cx0 + m) | (yy < cy0 - m),
        "above": yy < cy0 + m,
        "below": yy > cy1 - m,
        "left_only": xx <= cx0 + m,                          # a half form: left of the full letter
        "all": np.ones_like(rest),
    }[REGION.get(kind, kind)]
    rest &= region
    rest = cv2.morphologyEx(rest.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8)) > 0   # no slivers
    n, labels, stats, _ = cv2.connectedComponentsWithStats(rest.astype(np.uint8), connectivity=8)
    if n <= 1:
        return None
    areas = stats[1:, cv2.CC_STAT_AREA]
    keep = [i + 1 for i, a in enumerate(areas) if a >= max(4, SPECK * areas.max())]
    if kind == "rakar":                                        # one stroke, in the lower half (no slivers above)
        low = [i for i in keep if stats[i, cv2.CC_STAT_TOP] + stats[i, cv2.CC_STAT_HEIGHT] / 2 > 0.45 * h]
        keep = [max(low, key=lambda i: stats[i, cv2.CC_STAT_AREA])] if low else []
    if not keep:                                              # only specks: no piece from this pair
        return None
    piece = np.isin(labels, keep)
    ys_, xs_ = np.nonzero(piece)
    box = (int(xs_.min()), int(ys_.min()), int(xs_.max()) + 1, int(ys_.max()) + 1)
    return piece[box[1]:box[3], box[0]:box[2]], box


def make_sign(sign: str, glyphs: List[Dict], folder: Path) -> Optional[Tuple[Dict, np.ndarray]]:
    """Cut a sign or joined form (its key: ा, half:क, reph, rakar) out of the font's aksharas: (its numbers,
    its image), or None when no pair gives a piece."""
    kind = kind_of(sign)
    pieces, offsets, used = [], [], []
    pairs = pairs_for(sign, glyphs)
    for c, cs in pairs:
        base, whole = read(folder, c), read(folder, cs)
        if base is None or whole is None or c.get("top") is None or cs.get("top") is None:
            continue
        dy = int(round((c["top"] - cs["top"]) * SCALE))      # C's top in C+S's rows, from their places
        at = place_inside(base, whole, dy, int(SEARCH * SCALE))
        got = cut(base, whole, at, kind)
        if got is None:
            continue
        piece, (x0, y0, x1, y1) = got
        cx0, cx1 = at[1], at[1] + base.shape[1]
        top = cs["top"] + y0 / SCALE                                         # the piece's top, vs baseline
        c_head = (cs["top"] + at[0] / SCALE + c["headline"][0]) if c.get("headline") else None   # C's headline
        offsets.append({
            "left": (x0 - cx1) / SCALE,                                      # from C's right edge
            "right": (x1 - cx0) / SCALE,                                     # (ि: its right end from C's left)
            "top": top,
            "top_head": None if c_head is None else top - c_head,           # from C's headline top
        })
        pieces.append(piece)
        used.append({"base": c["label_dev"], "akshara": cs["label_dev"], "fp": cs.get("fp", "")})
    if not pieces:
        return None
    stack = align(pieces) > 0.5
    odd = []
    if len(stack) >= 3:                                       # leave out pieces unlike all the others
        like = [float(np.median([iou(stack[i], stack[j]) for j in range(len(stack)) if j != i])) for i in range(len(stack))]
        keep = [i for i, v in enumerate(like) if v >= ODD]
        if len(keep) >= 2:
            odd = [used[i]["akshara"] for i in range(len(stack)) if i not in keep]
            stack, offsets, used = stack[keep], [offsets[i] for i in keep], [used[i] for i in keep]
    agree = 1.0 if len(stack) == 1 else float(np.median(
        [iou(stack[i], stack[j]) for i in range(len(stack)) for j in range(i + 1, len(stack))]))
    img = crop(stack.mean(axis=0) >= 0.5)
    med = {k: round(median(o[k] for o in offsets), 2) for k in ("left", "right", "top")}
    heads = [o["top_head"] for o in offsets if o["top_head"] is not None]
    med["top_head"] = round(median(heads), 2) if heads else None
    return {"char": sign, "kind": kind, "pairs": used, "n": len(used), "few": len(used) < FEW, "odd": odd,
            "agree": round(agree, 3), "size": [int(img.shape[1]), int(img.shape[0])], **med,
            "key": current_key(sign, glyphs)}, img


VERSION = 4              # in every sign's key: raised when cutting changes, so every sign is cut again


def key_of(used: List[Dict]) -> str:
    return hashlib.sha1(json.dumps([VERSION] + [[u["akshara"], u["fp"]] for u in used]).encode()).hexdigest()[:12]


def current_key(sign: str, glyphs: List[Dict]) -> str:
    """The key the sign would have now (no image is opened): changed when the book's pairs changed."""
    return key_of([{"akshara": cs["label_dev"], "fp": cs.get("fp", "")} for _, cs in pairs_for(sign, glyphs)])


def can_generate(ch: str) -> bool:
    return ch in SIGN_KIND or ch.startswith("half:") or ch in ("reph", "rakar")


def why_not(entry: Optional[Dict]) -> Optional[str]:
    """Why a cut sign is not used, or None when it is."""
    if entry is None:
        return "the book has no pair to cut it from"
    if is_form(entry["char"]) and entry["n"] < MIN_FORM_PAIRS:
        return f"cut from one conjunct only ({' '.join(p['akshara'] for p in entry['pairs'])}): needs {MIN_FORM_PAIRS}"
    if entry["n"] > 1 and entry["agree"] < MIN_AGREE:
        return f"its {entry['n']} examples do not agree ({entry['agree']:.2f})"
    return None

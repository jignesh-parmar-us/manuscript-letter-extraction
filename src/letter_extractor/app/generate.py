"""Missing letters made by the system (printed books): a group for each letter of the letter table that the
book has no group for, with letters composed from the book's own labelled letters (compose.py).

- `missing(s, book)`  the letters of the table (vowels, consonants with every vowel sign and mark) that no
  labelled group has and no group is suggested as, each with how it can be made or why it cannot
- `generate(lib, book_id)`  makes them, as one undoable action

A generated letter is a sample with source "generated" and no page (like an uploaded one); `rules` says
what it was made from. Each made letter gets a new group with its label, not reviewed. A group is "system
generated" while all its letters are generated (`is_generated`); it stays so when reviewed, and stops
being so once a real letter joins it. Generated letters are used to train the letter reader, to read pages
and in the export only when their group is reviewed (readers.py, centres.py, export.py).
"""
from __future__ import annotations

import random
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image
from sqlalchemy import select

from .. import compose as C
from .. import io_utils
from ..features import fingerprint
from ..mapping import mapping_for
from .actions import ActionError, _Change, _result
from .db import GENERATED, Book, LetterGroup, Page, Sample
from .library import Cancelled, Library
from .samples import _sample_mask
from .suggest import LineDone, group_suggestions

PER_LETTER = 6          # letters made for each missing letter...
AT_LEAST = 5            # ...and no group when fewer can be made
BASES = 12              # base letters used: the ones nearest their group's centre
DONORS = 4              # samples of each donor letter

# the letter table of the Review tab (frontend/src/screens/LetterOverview.tsx: rowsOf without extras)
CONSONANTS = "क ख ग घ ङ च छ ज झ ञ ट ठ ड ढ ण त थ द ध न प फ ब भ म य र ल ळ व श ष स ह".split()
TABLE_SIGNS = ["", "ा", "ि", "ी", "ु", "ू", "ृ", "े", "ै", "ो", "ौ", "्", "ं", "ः", "ँ", "़"]
VOWELS = "अ आ इ ई उ ऊ ऋ ए ऐ ओ औ अं अः अँ".split()
# vowels drawn as another vowel with a sign: आ is अ with the aa bar, ऐ is ए with the e stroke
VOWEL_PARTS = {"आ": ("अ", "ा"), "ओ": ("अ", "ो"), "औ": ("अ", "ौ"), "ऐ": ("ए", "े"), "अं": ("अ", "ं"),
               "अँ": ("अ", "ँ")}
# signs below that these consonants take in a shape of their own (रु, हु, दु) or at no clear foot (ट ड)
OWN_SHAPE_BELOW = set("र ह द ट ठ ड ढ".split())


def table_letters() -> List[str]:
    return VOWELS + [c + sg for c in CONSONANTS for sg in TABLE_SIGNS]


def is_generated(n_samples: int, n_generated: int) -> bool:
    return n_samples > 0 and n_generated == n_samples


def _recipe(letter: str) -> Tuple[Optional[str], Optional[str], str]:
    """(base, sign, why not) for a letter."""
    if letter in VOWEL_PARTS:
        return VOWEL_PARTS[letter] + ("",)
    if letter in VOWELS:
        return None, None, "a vowel of its own shape"
    base, sign = letter[0], letter[1:]
    if not sign:
        return None, None, "a consonant of its own shape"
    if sign not in C.SIGNS:
        return None, None, {"ि": "the i sign is written before its letter (not made yet)",
                            "ृ": "ृ is too small to place well (not made yet)",
                            "्": "the halant is too small to place well (not made yet)"}.get(sign, f"the sign {sign} is not made")
    if sign in C.BELOW and base in OWN_SHAPE_BELOW:
        return None, None, f"{letter} has a shape of its own"
    return base, sign, ""


def missing(s, book: Book, cfg) -> List[Dict]:
    """Every letter of the table that no labelled group has and no group is suggested as."""
    labelled = set(s.scalars(select(LetterGroup.label_dev).where(LetterGroup.book_id == book.id,
                                                                 LetterGroup.label_dev != "")))
    suggested = {e["suggestion"]["label_dev"] for e in group_suggestions(s, book, cfg).values()
                 if e.get("suggestion")}
    out = []
    for letter in table_letters():
        if letter in labelled:
            continue
        if letter in suggested:
            out.append({"letter": letter, "base": None, "sign": None, "why": "a group is suggested as it: review that"})
            continue
        base, sign, why = _recipe(letter)
        if base is not None and base not in labelled:
            base, sign, why = None, None, f"no labelled {base} to start from"
        out.append({"letter": letter, "base": base, "sign": sign, "why": why})
    return out


def _samples_of(s, book_id: int, label: str, n: int) -> List[Tuple[Sample, Optional[float]]]:
    """Real letters of the label's groups, nearest their centre first, with their page's line spacing."""
    q = (select(Sample, Page.line_spacing).join(LetterGroup, Sample.group_id == LetterGroup.id)
         .outerjoin(Page, Sample.page_id == Page.id)
         .where(LetterGroup.book_id == book_id, LetterGroup.label_dev == label, Sample.deleted.is_(False),
                Sample.mask != "", Sample.source != GENERATED)
         .order_by(Sample.distance).limit(n))
    return [(x, sp) for x, sp in s.execute(q).all()]


def _letter_height(lib, book, s, consonant: str, cache: Dict) -> Optional[float]:
    if consonant not in cache:
        hs = []
        for x, _ in _samples_of(s, book.id, consonant, 15):
            m = _sample_mask(lib, book, x)
            hs.append(m.shape[0] - C.headline(m)[0])
        cache[consonant] = float(np.median(hs)) if hs else None
    return cache[consonant]


def _parts(lib, book, s, sign: str, labels: List[str], heights: Dict) -> List[C.Part]:
    """The sign cut from every labelled consonant + sign of the book, typical ones only."""
    found = []
    for label in labels:
        if len(label) != 2 or label[1] != sign or label[0] not in CONSONANTS:
            continue
        if sign in C.BELOW and label[0] in OWN_SHAPE_BELOW:
            continue
        height = _letter_height(lib, book, s, label[0], heights) if sign in C.BELOW else None
        if sign in C.BELOW and height is None:
            continue
        for x, _ in _samples_of(s, book.id, label, DONORS):
            p = C.cut(_sample_mask(lib, book, x), sign, height, source=f"{label} #{x.id}")
            if p is not None:
                found.append(p)
    return C.typical(found)


def _image(mask: np.ndarray, margin: int) -> np.ndarray:
    """What a generated letter looks like on screen: its ink, dark on white."""
    m = np.pad(mask, margin)
    return np.where(m[..., None], np.uint8(35), np.uint8(250)).repeat(3, axis=2)


def generate(lib: Library, book_id: int, progress=None, cancel: Optional[Callable[[], bool]] = None,
             per_letter: int = PER_LETTER) -> Dict:
    t0 = time.time()
    with lib.session() as s:
        book = s.get(Book, book_id)
        if book is None:
            raise ActionError(f"No book with id {book_id}.")
        cfg = lib.book_config(book)
        m = mapping_for(cfg)
        todo = missing(s, book, cfg)
        makeable = [t for t in todo if t["base"]]
        labels = list(s.scalars(select(LetterGroup.label_dev).where(LetterGroup.book_id == book_id,
                                                                    LetterGroup.label_dev != "").distinct()))
        ch = _Change(s, book_id)
        folder = lib.book_dir(book) / "letters" / "_generated"
        folder.mkdir(parents=True, exist_ok=True)
        parts: Dict[str, List[C.Part]] = {}
        heights: Dict[str, Optional[float]] = {}
        made: List[Dict] = []
        skipped: List[Dict] = [{"letter": t["letter"], "why": t["why"]} for t in todo if not t["base"]]
        for n, t in enumerate(makeable):
            if cancel and cancel():
                raise Cancelled("Cancelled; no letters were made.")
            if progress:
                progress(n, len(makeable), LineDone(t["letter"], "OK", f"{len(made)} letters made so far", time.time() - t0))
            letter, base, sign = t["letter"], t["base"], t["sign"]
            if sign not in parts:
                parts[sign] = _parts(lib, book, s, sign, labels, heights)
            donors = parts[sign]
            if not donors:
                skipped.append({"letter": letter, "why": f"no letter with {sign} to take it from"})
                continue
            bases = _samples_of(s, book_id, base, BASES)
            base_masks = [_sample_mask(lib, book, x) for x, _ in bases]
            keep = C.typical_bases(base_masks)
            bases, base_masks = [bases[i] for i in keep], [base_masks[i] for i in keep]
            rng = random.Random(letter)
            pairs = [(b, d) for b in range(len(bases)) for d in range(len(donors))]
            rng.shuffle(pairs)
            builds = []
            used_b, used_d = defaultdict(int), defaultdict(int)
            most_d = max(2, -(-per_letter // len(donors)))                  # variety: each base at most twice,
            for bi, di in pairs:                                            # each sign as evenly as it can
                if len(builds) >= per_letter:
                    break
                if used_b[bi] >= 2 or used_d[di] >= most_d:
                    continue
                bs, sp = bases[bi]
                out = C.compose(base_masks[bi], donors[di])
                if out is None:
                    continue
                used_b[bi] += 1
                used_d[di] += 1
                builds.append((out, bs, sp, donors[di]))
            if len(builds) < AT_LEAST:
                skipped.append({"letter": letter, "why": f"only {len(builds)} good letters could be made"})
                continue
            g = ch.new_group("letter")
            g.label_dev, g.label_guj, g.status = letter, m.gujarati(letter), "auto"
            for mask, bs, sp, part in builds:
                name = f"gen_{uuid.uuid4().hex[:10]}"
                io_utils.save_image(_image(mask, cfg.letter_margin_px), folder / f"{name}.png",
                                    io_utils.ImageMeta(format="PNG"))
                Image.fromarray(mask.astype(np.uint8) * 255).save(folder / f"{name}_mask.png")
                h, w = mask.shape
                smp = Sample(book_id=book_id, page_id=None, line_id=None, line_number=0, pos=0, x=0, y=0, w=w, h=h,
                             ink=bs.ink, kind="letter", pieces=1, source=GENERATED,
                             rules=f"generated: {base} #{bs.id} + {sign} from {part.source}",
                             image=f"letters/_generated/{name}.png", mask=f"letters/_generated/{name}_mask.png",
                             fingerprint=fingerprint(mask, float(sp or 1.6 * bs.h), cfg).tobytes(),
                             deleted=True, part="training")
                s.add(smp)
                s.flush()
                ch.created(smp)
                smp.deleted, smp.group_id = False, g.id
            made.append({"letter": letter, "label_guj": g.label_guj, "group": g.code, "samples": len(builds)})
        if not made:                                                        # nothing was added
            return {"letters": 0, "samples": 0, "made": [], "skipped": skipped, "seconds": round(time.time() - t0, 1)}
        a = ch.finish("generate", {"letters": len(made), "samples": sum(x["samples"] for x in made)})
        if progress:
            progress(len(makeable), len(makeable), LineDone("", "OK", f"{len(made)} letters made", time.time() - t0))
        return {**_result(a), "made": made, "skipped": skipped, "seconds": round(time.time() - t0, 1)}

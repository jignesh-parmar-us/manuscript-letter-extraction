"""Missing letters made by the system (printed books): a group for each letter of the letter table that the
book has no group for, with letters composed from the book's own labelled letters (compose.py).

- `missing(s, book)`  the letters of the table (vowels, consonants with every vowel sign and mark) that no
  labelled group has and no group is suggested as, each with how it can be made or why it cannot
- `generate(lib, book_id)`  makes them, as one undoable action
- `variants(lib, book_id, group_id)`  "Make variants" in a group with few letters: up to `TOP_UP` letters in all,
  at most `PER_REAL` per real letter; built from parts where the letter allows it (printed books), otherwise
  slightly changed copies of its own letters (ocr.features.varied, as the reader varies letters in training)
- `top_up(lib, book_id)`  the same for every labelled, unlocked group with fewer letters, as one action

A generated letter is a sample with source "generated" and no page (like an uploaded one); `rules` says
what it was made from. Each made letter gets a new group with its label, not reviewed. A group is "system
generated" while all its letters are generated (`is_generated`); it stays so when reviewed, and stops
being so once a real letter joins it. Generated letters are used to train the letter reader, to read pages
and in the export only when their group is reviewed (readers.py, centres.py, export.py); so variants put a
reviewed group back to not reviewed, to be looked at again.
"""
from __future__ import annotations

import random
import time
import uuid
import zlib
from collections import defaultdict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image
from sqlalchemy import func, select

from .. import compose as C
from .. import io_utils
from ..features import fingerprint
from ..ocr.features import varied
from ..mapping import mapping_for
from .actions import ActionError, _Change, _result
from .db import GENERATED, Book, LetterGroup, Page, Sample
from .library import Cancelled, Library
from .samples import _sample_mask
from .suggest import LineDone, group_suggestions

PER_LETTER = 6          # letters made for each missing letter...
AT_LEAST = 5            # ...and no group when fewer can be made
BASES = 12              # base letters used: the ones nearest their group's centre
TOP_UP = 10             # variants fill a group up to this many letters...
PER_REAL = 3            # ...with at most this many per real letter
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


def _tight(mask: np.ndarray) -> np.ndarray:
    ys, xs = np.nonzero(mask)
    return mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


class _Maker:
    """Makes letters for one book: from parts of others (printed books), or as slightly changed copies of a
    group's own letters; and stores them as samples of a group. Parts are cut once per sign."""

    def __init__(self, lib: Library, s, book: Book):
        self.lib, self.s, self.book = lib, s, book
        self.cfg = lib.book_config(book)
        self.labels = list(s.scalars(select(LetterGroup.label_dev).where(LetterGroup.book_id == book.id,
                                                                         LetterGroup.label_dev != "").distinct()))
        self.parts: Dict[str, List[C.Part]] = {}
        self.heights: Dict[str, Optional[float]] = {}
        self.folder = lib.book_dir(book) / "letters" / "_generated"
        self.folder.mkdir(parents=True, exist_ok=True)

    def donors(self, sign: str) -> List[C.Part]:
        if sign not in self.parts:
            self.parts[sign] = _parts(self.lib, self.book, self.s, sign, self.labels, self.heights)
        return self.parts[sign]

    def combine(self, letter: str, base: str, sign: str, n: int, seed: str) -> List[Tuple[np.ndarray, float, str, str]]:
        """Up to `n` letters: a base letter of the book with the sign of another; (mask, spacing, ink, rules)."""
        donors = self.donors(sign)
        if not donors or n <= 0:
            return []
        bases = _samples_of(self.s, self.book.id, base, BASES)
        masks = [_sample_mask(self.lib, self.book, x) for x, _ in bases]
        keep = C.typical_bases(masks)
        bases, masks = [bases[i] for i in keep], [masks[i] for i in keep]
        rng = random.Random(seed)
        pairs = [(b, d) for b in range(len(bases)) for d in range(len(donors))]
        rng.shuffle(pairs)
        out = []
        used_b, used_d = defaultdict(int), defaultdict(int)
        most_d = max(2, -(-n // len(donors)))                  # variety: each base at most twice, each sign
        for bi, di in pairs:                                   # as evenly as it can
            if len(out) >= n:
                break
            if used_b[bi] >= 2 or used_d[di] >= most_d:
                continue
            mask = C.compose(masks[bi], donors[di])
            if mask is None:
                continue
            used_b[bi] += 1
            used_d[di] += 1
            bs, sp = bases[bi]
            out.append((mask, float(sp or 1.6 * bs.h), bs.ink, f"generated: {base} #{bs.id} + {sign} from {donors[di].source}"))
        return out

    def copies(self, real: List[Tuple[Sample, Optional[float]]], n: int, seed: str) -> List[Tuple[np.ndarray, float, str, str]]:
        """`n` slightly changed copies of the group's own letters, in turn (a little rotation and slant, strokes
        a pixel thicker or thinner, sometimes an edge trimmed: as the reader varies letters in training)."""
        rng = np.random.default_rng(zlib.crc32(seed.encode()))
        out = []
        for k in range(n):
            x, sp = real[k % len(real)]
            mask = _tight(varied(_sample_mask(self.lib, self.book, x), rng))
            out.append((mask, float(sp or 1.6 * x.h), x.ink, f"generated: a varied copy of #{x.id}"))
        return out

    def store(self, ch: _Change, group_id: int, made: List[Tuple[np.ndarray, float, str, str]], kind: str) -> None:
        for mask, spacing, ink, rules in made:
            name = f"gen_{uuid.uuid4().hex[:10]}"
            io_utils.save_image(_image(mask, self.cfg.letter_margin_px), self.folder / f"{name}.png",
                                io_utils.ImageMeta(format="PNG"))
            Image.fromarray(mask.astype(np.uint8) * 255).save(self.folder / f"{name}_mask.png")
            h, w = mask.shape
            smp = Sample(book_id=self.book.id, page_id=None, line_id=None, line_number=0, pos=0, x=0, y=0, w=w, h=h,
                         ink=ink, kind=kind, pieces=1, source=GENERATED, rules=rules,
                         image=f"letters/_generated/{name}.png", mask=f"letters/_generated/{name}_mask.png",
                         fingerprint=fingerprint(mask, spacing, self.cfg).tobytes(), deleted=True, part="training")
            self.s.add(smp)
            self.s.flush()
            ch.created(smp)
            smp.deleted, smp.group_id = False, group_id


def generate(lib: Library, book_id: int, progress=None, cancel: Optional[Callable[[], bool]] = None,
             per_letter: int = PER_LETTER) -> Dict:
    t0 = time.time()
    with lib.session() as s:
        book = s.get(Book, book_id)
        if book is None:
            raise ActionError(f"No book with id {book_id}.")
        maker = _Maker(lib, s, book)
        m = mapping_for(maker.cfg)
        todo = missing(s, book, maker.cfg)
        makeable = [t for t in todo if t["base"]]
        ch = _Change(s, book_id)
        made: List[Dict] = []
        skipped: List[Dict] = [{"letter": t["letter"], "why": t["why"]} for t in todo if not t["base"]]
        for n, t in enumerate(makeable):
            if cancel and cancel():
                raise Cancelled("Cancelled; no letters were made.")
            if progress:
                progress(n, len(makeable), LineDone(t["letter"], "OK", f"{len(made)} letters made so far", time.time() - t0))
            letter, base, sign = t["letter"], t["base"], t["sign"]
            if not maker.donors(sign):
                skipped.append({"letter": letter, "why": f"no letter with {sign} to take it from"})
                continue
            builds = maker.combine(letter, base, sign, per_letter, letter)
            if len(builds) < AT_LEAST:
                skipped.append({"letter": letter, "why": f"only {len(builds)} good letters could be made"})
                continue
            g = ch.new_group("letter")
            g.label_dev, g.label_guj, g.status = letter, m.gujarati(letter), "auto"
            maker.store(ch, g.id, builds, "letter")
            made.append({"letter": letter, "label_guj": g.label_guj, "group": g.code, "samples": len(builds)})
        if not made:                                                        # nothing was added
            return {"letters": 0, "samples": 0, "made": [], "skipped": skipped, "seconds": round(time.time() - t0, 1)}
        a = ch.finish("generate", {"letters": len(made), "samples": sum(x["samples"] for x in made)})
        if progress:
            progress(len(makeable), len(makeable), LineDone("", "OK", f"{len(made)} letters made", time.time() - t0))
        return {**_result(a), "made": made, "skipped": skipped, "seconds": round(time.time() - t0, 1)}


# ---- variants of the letters a group has (one group, or every small group of the book) ----------------------
def _real(s, group_id: int) -> List[Tuple[Sample, Optional[float]]]:
    q = (select(Sample, Page.line_spacing).outerjoin(Page, Sample.page_id == Page.id)
         .where(Sample.group_id == group_id, Sample.deleted.is_(False), Sample.mask != "", Sample.source != GENERATED)
         .order_by(Sample.distance))
    return [(x, sp) for x, sp in s.execute(q).all()]


def _variants_of(maker: _Maker, ch: _Change, g: LetterGroup, top: int) -> Optional[Dict]:
    """Variants for one labelled group, up to `top` letters in all and `PER_REAL` per real letter: built from
    parts first (printed books, letters with a vowel sign), then changed copies of its own letters. A reviewed
    group goes back to not reviewed, so the new letters are looked at before they are used."""
    real = _real(maker.s, g.id)
    have = maker.s.scalar(select(func.count(Sample.id)).where(Sample.group_id == g.id, Sample.deleted.is_(False))) or 0
    need = min(top - have, PER_REAL * len(real) - (have - len(real)))
    if not real or need <= 0:
        return None
    seed = f"{g.label_dev}-{have}"
    made = []
    base, sign, _ = _recipe(g.label_dev)
    if maker.book.writing == "printed" and base and base in maker.labels:
        made = maker.combine(g.label_dev, base, sign, need, seed)
    made += maker.copies(real, need - len(made), seed)
    ch.group(g.id)
    if g.status != "auto":
        g.status = "auto"
    maker.store(ch, g.id, made, g.kind)
    return {"group": g.code, "label_guj": g.label_guj, "made": len(made),
            "built": sum(not r[3].startswith("generated: a varied copy") for r in made)}


def variants(lib: Library, book_id: int, group_id: int, top: int = TOP_UP) -> Dict:
    """"Make variants" in a group: one action."""
    with lib.session() as s:
        book = s.get(Book, book_id)
        g = s.get(LetterGroup, group_id)
        if book is None or g is None or g.book_id != book_id:
            raise ActionError("No such group in this book.")
        if not g.label_dev:
            raise ActionError("Label the group first: variants are made of a known letter.")
        if g.locked:
            raise ActionError(f"Group {g.code} is locked; unlock it first.")
        ch = _Change(s, book_id)
        got = _variants_of(_Maker(lib, s, book), ch, g, top)
        if got is None:
            raise ActionError(f"The group has {top} letters or more, or no real letter to start from "
                              f"(at most {PER_REAL} variants per real letter).")
        a = ch.finish("variants", got)
        return _result(a, group_id=g.id)


def top_up(lib: Library, book_id: int, progress=None, cancel: Optional[Callable[[], bool]] = None,
           top: int = TOP_UP) -> Dict:
    """"Top up small groups": variants for every labelled, unlocked group with fewer than `top` letters, as one
    action."""
    t0 = time.time()
    with lib.session() as s:
        book = s.get(Book, book_id)
        if book is None:
            raise ActionError(f"No book with id {book_id}.")
        maker = _Maker(lib, s, book)
        ch = _Change(s, book_id)
        groups = s.scalars(select(LetterGroup).where(LetterGroup.book_id == book_id, LetterGroup.label_dev != "",
                                                     LetterGroup.locked.is_(False)).order_by(LetterGroup.code)).all()
        done: List[Dict] = []
        for n, g in enumerate(groups):
            if cancel and cancel():
                raise Cancelled("Cancelled; no letters were made.")
            if progress and n % 10 == 0:
                progress(n, len(groups), LineDone(g.code, "OK", f"{len(done)} groups topped up", time.time() - t0))
            got = _variants_of(maker, ch, g, top)
            if got:
                done.append(got)
        if not done:
            return {"groups": 0, "samples": 0, "topped": [], "seconds": round(time.time() - t0, 1)}
        a = ch.finish("top_up", {"groups": len(done), "samples": sum(d["made"] for d in done)})
        return {**_result(a), "topped": done, "seconds": round(time.time() - t0, 1)}

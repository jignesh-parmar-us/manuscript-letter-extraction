"""Giving aa bars back in a captured book (printed books): the review screens' "Fix ા bars".

The same rule as at capture (`bars.py`), on the stored samples: a letter that starts with the aa bar
of the letter before it (नार cut as न + ार) is cut after the bar, and the bar is joined to the letter
before (ना + र). Tesseract's readings of the book, if it was read, let a bar under the e sign of the next
letter move too (तारे, bars.py). A letter that is only a bar with a piece of headline (the stem of ण
cut off on its own, or an aa bar) is joined to the letter before. Letters in locked groups are left
alone. All changes are one undoable action.

The new letters go where their shape says, not where the old ones were (the old letter before is
now another letter, न became ना):
- the letter before into the labelled group of its old label with the aa (न -> ना), and the other one
  into the labelled group of its old label (र), when the shape is within `group_distance` of that
  group's centre;
- otherwise into the nearest labelled group, when within `group_distance`;
- otherwise Unsure, where they show a suggested group.
"""
from __future__ import annotations

import time
from statistics import median
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
from sqlalchemy import select

from ..bars import AA, plan_pair
from ..mapping import LabelError, canonical_label, mapping_for
from .actions import _Change, _result
from .db import Book, LetterGroup, OcrReading, Page, Sample
from .library import Cancelled, Library, LibraryError
from .recut import _labelled_centres
from .suggest import LineDone, _run_id
from .samples import _new_sample, _sample_mask, page_ink

Plan = Tuple[int, int, Tuple, Optional[Tuple]]   # letter before, letter, (box, mask) of each new letter (one when
                                                 # the letter was only a bar: the stem of ण, an aa bar on its own)

# signs that end an akshara: no aa after them
_ENDS = set("ािीुूृॄेैोौंःँ")


def plan_book(lib: Library, book_id: int, progress=None, cancel: Optional[Callable[[], bool]] = None) -> List[Plan]:
    book = lib.get_book(book_id)
    if book.writing != "printed":
        raise LibraryError("Fixing aa bars is for printed books: in handwriting bars and the left strokes "
                           "of letters look too much alike.")
    cfg = lib.book_config(book)
    plans: List[Plan] = []
    with lib.session() as s:
        locked = set(s.scalars(select(LetterGroup.id).where(LetterGroup.book_id == book_id, LetterGroup.locked)))
        smps = s.scalars(select(Sample).where(Sample.book_id == book_id, Sample.deleted.is_(False),
                                              Sample.page_id.is_not(None))
                         .order_by(Sample.page_id, Sample.line_number, Sample.x, Sample.pos)).all()
        letters = [x for x in smps if x.kind == "letter"]
        if len(letters) < 2:
            return []
        width = float(median(x.w for x in letters))
        files = dict(s.execute(select(Page.id, Page.file).where(Page.book_id == book_id)).all())
        run = _run_id(s, book_id)                                 # Tesseract's readings tell an e sign from an i hook
        reading = dict(s.execute(select(OcrReading.sample_id, OcrReading.text_dev)
                                 .where(OcrReading.run_id == run)).all()) if run else {}
        pages = sorted({x.page_id for x in smps})
        prev: Optional[Sample] = None
        prev_mask = None
        done_pages, t, page_id = 0, time.time(), smps[0].page_id if smps else None

        def page_done(pid: int) -> None:
            nonlocal done_pages, t
            done_pages += 1
            if progress:
                progress(done_pages, len(pages), LineDone(files.get(pid, ""), "OK", f"{len(plans)} bars so far",
                                                          time.time() - t))
            t = time.time()

        cache: Dict[int, np.ndarray] = {}

        def mask_of(smp: Sample) -> np.ndarray:
            if smp.id not in cache:
                cache.clear() if len(cache) > 8 else None
                cache[smp.id] = _sample_mask(lib, book, smp)
            return cache[smp.id]

        for i, x in enumerate(smps):
            if x.page_id != page_id:
                page_done(page_id)
                page_id = x.page_id
                if cancel and cancel():
                    raise Cancelled("Cancelled; no letter was changed.")
            usable = x.kind == "letter" and x.mask and x.group_id not in locked
            if not usable:
                prev = prev_mask = None
                continue
            mask = mask_of(x)
            if prev is not None and prev.page_id == x.page_id and prev.line_number == x.line_number:
                after = smps[i + 1] if i + 1 < len(smps) else None
                if after is None or after.page_id != x.page_id or after.line_number != x.line_number \
                        or not after.mask:
                    after = None
                found = plan_pair((prev.x, prev.y, prev.w, prev.h), prev_mask, (x.x, x.y, x.w, x.h), mask, width, cfg,
                                  reading.get(x.id, ""),
                                  (mask_of(after), reading.get(after.id, "")) if after is not None else None,
                                  reading.get(prev.id, ""))
                if found is not None:
                    plans.append((prev.id, x.id, found[0], found[1]))
                    prev = prev_mask = None              # this letter changes: not the one before the next
                    continue
            prev, prev_mask = x, mask
        if page_id is not None:
            page_done(page_id)
    return plans


def _nearest(fp: np.ndarray, targets: Dict[str, Tuple[int, np.ndarray]], cfg,
             prefer: Optional[str]) -> Optional[int]:
    if prefer and prefer in targets:
        gid, centre = targets[prefer]
        if float(np.linalg.norm(fp - centre)) <= cfg.group_distance:
            return gid
    best, best_d = None, cfg.group_distance
    for gid, centre in targets.values():
        d = float(np.linalg.norm(fp - centre))
        if d <= best_d:
            best, best_d = gid, d
    return best


def fix_bars(lib: Library, book_id: int, progress=None, cancel: Optional[Callable[[], bool]] = None) -> Dict:
    """Plan and apply as one action; nothing changes when nothing is found."""
    t0 = time.time()
    plans = plan_book(lib, book_id, progress, cancel)
    if not plans:
        return {"bars": 0, "placed": 0, "unsure": 0, "seconds": round(time.time() - t0, 1)}
    with lib.session() as s:
        book = s.get(Book, book_id)
        cfg = lib.book_config(book)
        mapping = mapping_for(cfg)
        targets = _labelled_centres(s, book_id)                  # before anything moves
        ch = _Change(s, book_id)
        old = {x.id: x for x in ch.samples([i for p in plans for i in p[:2]])}
        label_of = {x.id: (x.group.label_dev if x.group is not None else "") for x in old.values()}
        prepared: Dict[int, object] = {}
        placed = unsure = 0
        for before_id, letter_id, left, right in plans:
            first = old[before_id]
            page = s.get(Page, first.page_id)
            if page.id not in prepared:
                prepared[page.id] = page_ink(lib, book, page)
            # what each new letter probably is: the old label with the aa, and the old label (र of ार)
            lb, ll = label_of[before_id], label_of[letter_id]
            want_left = None
            if lb and lb[-1] not in _ENDS:
                try:
                    want_left = canonical_label(lb + AA, mapping)
                except LabelError:
                    want_left = None
            want_right = ll[1:] if ll.startswith(AA) else ll
            if right is None:                                   # a bar on its own, joined to the letter before:
                # an aa bar makes न ना; the stem of ण makes it whole, and may have carried its label
                want_left = want_left if ll.startswith(AA) else (ll or lb or None)
            for sid in (before_id, letter_id):
                old[sid].deleted, old[sid].group_id = True, None
            for (box, mask), want in ((left, want_left), (right or (None, None), want_right or None)):
                if box is None:
                    continue
                smp = _new_sample(s, ch, lib, book, page, prepared[page.id], box, mask, "bar", kind="letter")
                gid = _nearest(np.frombuffer(smp.fingerprint, np.float32), targets, cfg, want)
                if gid is not None:
                    smp.group_id = ch.group(gid).id
                    placed += 1
                else:
                    unsure += 1
        joined = sum(p[3] is None for p in plans)
        a = ch.finish("fix_bars", {"bars": len(plans), "joined": joined, "placed": placed, "unsure": unsure})
        return {**_result(a), "bars": len(plans), "joined": joined, "placed": placed, "unsure": unsure,
                "seconds": round(time.time() - t0, 1)}

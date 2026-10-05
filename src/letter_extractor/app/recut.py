"""Fixing cuts with Tesseract's readings, for printed books (C12b).

Phase 1 cuts letters by their ink; on print it often leaves two or three letters in one sample (अम,
केव) or cuts one letter in two. The Tesseract run of C11 knows how many aksharas each stretch of a
line holds. Its readings (the kept hOCR) are aligned with the line's current samples again
(ocr/align.py), and:

- **split:** a sample that holds 2 or 3 aksharas is cut between them. Tesseract's boxes are rough, so
  each cut goes to the column with the least ink (the headline rows left out) within
  `recut_window` x the line's median sample width around the boundary Tesseract gives.
- **join:** 2 or 3 samples that lie inside one akshara become one sample, when only one of them is
  letter-sized and the others are fragments (a vowel bar cut off, an i-hook): Tesseract's box of an
  akshara often reaches into the next letter, so two letter-sized samples are never joined.

Splits happen only between aksharas, so a conjunct, a reph or a letter with its vowel signs is never
cut. A change is kept only when every new sample looks like a letter of the book: its fingerprint is
within `group_distance` of the centre of a group with at least `recut_min_group` samples, and it
is at least `recut_min_width` x the line's median sample width wide (a vowel bar alone is not a
letter). Samples of locked groups, dandas and digits are left alone.

All changes are one action, so one undo takes them all back. New samples go to Unsure (as with the
Pages tab's split and join, C5f) and get their akshara as their reading, so they show it at once.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
from sqlalchemy import select

from ..features import fingerprint
from ..mapping import LabelError, canonical_label, mapping_for
from ..ocr.aksharas import line_aksharas
from ..ocr.align import align_line, inside
from ..ocr.tesseract import reading_from_hocr
from .actions import _Change, _result
from .centres import centres, members
from .db import Book, LetterGroup, Line, OcrReading, Page, Sample
from .library import Cancelled, Library, LibraryError
from .samples import _new_sample, _sample_mask, _tight, page_ink
from .suggest import LineDone, _run_id


@dataclass
class Piece:
    box: Tuple[int, int, int, int]     # page coordinates
    mask: np.ndarray
    text: str                          # the akshara it should be (Devanagari NFC)
    conf: float
    alternatives: List = field(default_factory=list)


@dataclass
class Change:
    kind: str                          # split | join
    sample_ids: List[int]              # the samples it replaces
    pieces: List[Piece]


def best_cut(mask: np.ndarray, at: int, window: int) -> Optional[int]:
    """The column near `at` (mask coordinates) with the least ink below and above the headline: the
    headline joins all letters of a word, so its rows are left out. Ties go to the nearest column."""
    h, w = mask.shape
    lo, hi = max(1, at - window), min(w - 1, at + window)
    if lo > hi:
        return None
    rows = mask.sum(axis=1)
    head = int(np.argmax(rows[: max(1, h // 2)]))
    band = max(2, h // 12)
    keep = np.ones(h, bool)
    keep[max(0, head - band): head + band + 1] = False
    profile = mask[keep].sum(axis=0)
    return min(range(lo, hi + 1), key=lambda c: (int(profile[c]), abs(c - at)))


class _Shapes:
    """Is a piece of ink shaped like a letter the book has? (near the centre of a big enough group)"""

    def __init__(self, s, book: Book, cfg, min_group: int):
        groups, C = centres(s, book.id)
        keep = [i for i, g in enumerate(groups) if len(members(s, g.id)) >= min_group]
        self.C = C[keep] if keep else np.zeros((0, 0), np.float32)
        self.cfg = cfg

    def distance(self, mask: np.ndarray, spacing: float) -> float:
        if self.C.size == 0:
            return float("inf")
        v = fingerprint(mask, spacing, self.cfg)
        return float(np.min(np.linalg.norm(self.C - v, axis=1)))


def plan_line(aksharas, samples: Sequence[Sample], masks: Callable[[Sample], np.ndarray], dx: int, cfg,
              shapes: _Shapes, spacing: float, mapping) -> Tuple[List[Change], int]:
    """The checked changes of one line, and how many candidates were refused."""
    spans_s = [(x.x, x.x + x.w) for x in samples]
    al = align_line(aksharas, spans_s, dx=dx, min_overlap=cfg.align_min_overlap,
                    sure_overlap=cfg.align_sure_overlap, min_matched=cfg.align_min_matched)
    if al.refused or not samples:
        return [], 0
    width = median(b - a for a, b in spans_s)
    matched = {m.sample: m for m in al.matches}
    changes, refused = [], 0

    def label(text: str) -> Optional[str]:
        try:
            return canonical_label(text, mapping)                  # one letter, not a word
        except LabelError:
            return None

    def check(pieces: List[Piece]) -> bool:
        return all(p.box[2] >= cfg.recut_min_width * width and label(p.text) is not None
                   and shapes.distance(p.mask, spacing) <= cfg.group_distance for p in pieces)

    for i, j, di, dj in al.steps:
        if di >= 2 and dj == 1 and j in matched and len(matched[j].aksharas) == di:
            smp = samples[j]
            if smp.kind != "letter":
                continue
            mask = masks(smp)
            bounds = [(al.spans[i + k][1] + al.spans[i + k + 1][0]) // 2 for k in range(di - 1)]
            cuts = [best_cut(mask, b - smp.x, max(4, int(cfg.recut_window * width))) for b in bounds]
            if any(c is None for c in cuts) or sorted(set(cuts)) != cuts:
                refused += 1
                continue
            edges = [0] + cuts + [mask.shape[1]]
            pieces = []
            for k, (a, b) in enumerate(zip(edges, edges[1:])):
                part = np.zeros_like(mask)
                part[:, a:b] = mask[:, a:b]
                tight = _tight(part, smp.x, smp.y)
                if tight is None:
                    break
                ak = aksharas[i + k]
                pieces.append(Piece(tight[0], tight[1], label(ak.text) or ak.text, ak.conf, ak.alternatives))
            if len(pieces) == di and check(pieces):
                changes.append(Change("split", [smp.id], pieces))
            else:
                refused += 1
        elif di == 1 and dj >= 2:
            group = samples[j:j + dj]
            if any(x.kind != "letter" for x in group) or len({x.page_id for x in group}) != 1:
                continue
            if min(inside(sp, al.spans[i]) for sp in spans_s[j:j + dj]) < cfg.align_sure_overlap:
                continue
            # a letter and its fragments (a vowel bar, an i-hook, a mark), never two letters: Tesseract's
            # box of an akshara often reaches into the next letter
            if sum(x.w >= cfg.recut_min_width * width for x in group) > 1:
                continue
            x0, y0 = min(x.x for x in group), min(x.y for x in group)
            x1, y1 = max(x.x + x.w for x in group), max(x.y + x.h for x in group)
            mask = np.zeros((y1 - y0, x1 - x0), bool)
            for x in group:
                mask[x.y - y0:x.y - y0 + x.h, x.x - x0:x.x - x0 + x.w] |= masks(x)
            tight = _tight(mask, x0, y0)
            ak = aksharas[i]
            piece = Piece(tight[0], tight[1], label(ak.text) or ak.text, ak.conf, ak.alternatives) if tight else None
            if piece is not None and check([piece]):
                changes.append(Change("join", [x.id for x in group], [piece]))
            else:
                refused += 1
    return changes, refused


def fix_cuts(lib: Library, book_id: int, progress=None, cancel: Optional[Callable[[], bool]] = None) -> Dict:
    """Plan the checked splits and joins of every line read by the newest Tesseract run, then apply
    them as one action. Nothing changes when it is cancelled or nothing passes the checks."""
    t0 = time.time()
    book = lib.get_book(book_id)
    if book.writing != "printed":
        raise LibraryError("Fixing cuts with Tesseract is for printed books: on handwriting it reads too many "
                           "letters wrong.")
    cfg = lib.book_config(book)
    mapping = mapping_for(cfg)
    book_dir = lib.book_dir(book)
    plans: List[Change] = []
    refused = lines_done = 0
    with lib.session() as s:
        if _run_id(s, book_id) is None:
            raise LibraryError("Read the book with Tesseract first (Suggest labels).")
        shapes = _Shapes(s, book, cfg, cfg.recut_min_group)
        locked = set(s.scalars(select(LetterGroup.id).where(LetterGroup.book_id == book_id, LetterGroup.locked)))
        lines = s.execute(select(Line, Page.line_spacing).join(Page, Line.page_id == Page.id)
                          .where(Page.book_id == book_id).order_by(Page.id, Line.number)).all()
        mask_cache: Dict[int, np.ndarray] = {}

        def masks(smp: Sample) -> np.ndarray:
            if smp.id not in mask_cache:
                mask_cache[smp.id] = _sample_mask(lib, book, smp)
            return mask_cache[smp.id]

        for n, (line, spacing) in enumerate(lines, 1):
            if cancel and cancel():
                raise Cancelled("Cancelled; no cut was changed.")
            t = time.time()
            hocr = book_dir / "ocr" / (Path(line.image).stem + ".hocr")
            smps = s.scalars(select(Sample).where(Sample.line_id == line.id, Sample.deleted.is_(False))
                             .order_by(Sample.x, Sample.pos)).all()
            smps = [x for x in smps if x.group_id not in locked and x.mask]
            if hocr.is_file() and smps:
                reading = reading_from_hocr(hocr.read_text(encoding="utf-8"))
                found, bad = plan_line(line_aksharas(reading.words), smps, masks,
                                       max(0, line.x - cfg.line_margin_px), cfg, shapes,
                                       float(spacing or 1.6 * line.h), mapping)
                plans += found
                refused += bad
                lines_done += 1
            if progress:
                progress(n, len(lines), LineDone(Path(line.image).name, "OK",
                                                 f"{len(plans)} changes so far", time.time() - t))
    result = {"lines": lines_done, "splits": sum(c.kind == "split" for c in plans),
              "joins": sum(c.kind == "join" for c in plans), "refused": refused, "samples_new": 0}
    if plans:
        result.update(_apply(lib, book_id, plans))
    result["seconds"] = round(time.time() - t0, 1)
    return result


def _apply(lib: Library, book_id: int, plans: List[Change]) -> Dict:
    """All changes as one action; the new samples get their akshara as a reading of the newest run."""
    with lib.session() as s:
        book = s.get(Book, book_id)
        run_id = _run_id(s, book_id)
        ch = _Change(s, book_id)
        old = ch.samples([sid for c in plans for sid in c.sample_ids])
        by_id = {x.id: x for x in old}
        prepared: Dict[int, object] = {}
        new_ids = []
        for c in plans:
            first = by_id[c.sample_ids[0]]
            page = s.get(Page, first.page_id)
            if page.id not in prepared:
                prepared[page.id] = page_ink(lib, book, page)
            for sid in c.sample_ids:
                by_id[sid].deleted, by_id[sid].group_id = True, None
            for p in c.pieces:
                smp = _new_sample(s, ch, lib, book, page, prepared[page.id], p.box, p.mask,
                                  "ocr-split" if c.kind == "split" else "ocr-joined", kind=first.kind)
                s.add(OcrReading(run_id=run_id, sample_id=smp.id, text_dev=p.text, confidence=round(p.conf, 1),
                                 alternatives=json.dumps(p.alternatives, ensure_ascii=False), overlap=1.0))
                new_ids.append(smp.id)
        a = ch.finish("fix_cuts", {"splits": sum(c.kind == "split" for c in plans),
                                   "joins": sum(c.kind == "join" for c in plans), "samples": len(new_ids)})
        return {**_result(a), "samples_new": len(new_ids)}

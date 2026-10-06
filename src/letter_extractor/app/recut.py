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
- **vowel bar:** a letter read with a bar on its right (ा ो ौ ी, or the vowels आ ओ औ written as अ with
  a bar) whose bar Phase 1 cut off or joined to the next letter (अ | ावे): when the next sample
  starts with a tall stroke and a gap (`left_bar`), that stroke moves to the letter. Tesseract's box
  of the bar is too far left to show this, so the bar's shape decides, together with the reading.

Splits happen only between aksharas, so a conjunct, a reph or a letter with its vowel signs is never
cut. A change is kept only when every new sample looks like a letter of the book: its fingerprint is
within `group_distance` of the centre of a group with at least `recut_min_group` samples, and it
is at least `recut_min_width` x the line's median sample width wide (a vowel bar alone is not a
letter). Samples of locked groups, dandas and digits are left alone.

All changes are one action, so one undo takes them all back. New samples get their akshara as their
reading and go where it says when their shape agrees (`_place`): into the labelled group with that
label, or a new group with that label (labelled, not reviewed) when at least 3 alike samples share
the reading; the rest go to Unsure.
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
from ..ocr.cut import best_cut
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


# what ends in a bar drawn on the right: the vowel signs ा ो ौ ी, and the vowels आ ओ औ (written as अ
# with that bar; they are characters of their own in Unicode)
BAR_SIGNS = ("\u093E", "\u094B", "\u094C", "\u0940", "\u0906", "\u0913", "\u0914")
I_SIGN = "\u093F"


def _body_rows(mask: np.ndarray) -> np.ndarray:
    """Rows below the headline (the busiest row of the upper half and a few rows around it)."""
    h = mask.shape[0]
    rows = mask.sum(axis=1)
    head = int(np.argmax(rows[: max(1, h // 2)]))
    return np.arange(min(h, head + max(2, h // 12) + 1), h)


def left_bar(mask: np.ndarray, letter_width: float) -> Optional[int]:
    """If the sample starts with a vowel bar that belongs to the letter before it (Phase 1 cut it off
    or joined it to this letter): the column after the bar and its gap; the mask width if the sample
    is only the bar. A bar is a tall stroke (ink in 60% of the rows below the headline) at the left
    edge, at most 0.35 letter widths wide, followed by a gap (ink in at most 15% of those rows)."""
    h, w = mask.shape
    body = _body_rows(mask)
    if body.size < 5 or w < 2:
        return None
    frac = mask[body].mean(axis=0)
    start = next((c for c in range(min(w, max(3, int(0.25 * letter_width)))) if frac[c] >= 0.6), None)
    if start is None:
        return None
    end = start
    while end < w and frac[end] >= 0.6:
        end += 1
    if end - start > 0.35 * letter_width:
        return None
    if end >= w or mask[:, end:].sum() < 15:
        return w                                               # only the bar
    for c in range(end, min(w, end + max(2, int(0.25 * letter_width)))):
        if frac[c] <= 0.15:
            return c
    return None


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

    done: set = set()                       # samples already in a change of this line
    for i, j, di, dj in al.steps:
        # a letter read with its vowel bar (आ) whose bar is the next sample, or the start of it
        if di == 1 and dj == 1 and j in matched and j + 1 < len(samples) and j not in done \
                and matched[j].text.endswith(BAR_SIGNS):
            cur, nxt = samples[j], samples[j + 1]
            nxt_text = matched[j + 1].text if j + 1 in matched else ""
            # a letter that starts with a bar itself carries the bar of the letter before it: left alone
            if cur.kind == nxt.kind == "letter" and cur.page_id == nxt.page_id and I_SIGN not in nxt_text \
                    and left_bar(masks(cur), width) is None:
                nmask = masks(nxt)
                cut = left_bar(nmask, width)
                if cut is not None:
                    change = _move_bar(cur, nxt, masks(cur), nmask, cut, matched[j], nxt_text, label)
                    # the letter with its bar is vouched for by the reading and the bar's shape; the rest of
                    # the next sample must still look like a letter of the book
                    if change is not None and change.pieces[0].box[2] >= cfg.recut_min_width * width \
                            and change.pieces[0].box[2] <= cur.w + 0.6 * width and all(
                            p.box[2] >= cfg.recut_min_width * width
                            and shapes.distance(p.mask, spacing) <= cfg.group_distance for p in change.pieces[1:]):
                        changes.append(change)
                        done.update((j, j + 1))
                    else:
                        refused += 1
            continue
        if j in done:
            continue
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


def _move_bar(cur: Sample, nxt: Sample, cmask: np.ndarray, nmask: np.ndarray, cut: int, match, nxt_text: str,
              label) -> Optional[Change]:
    """The letter with the bar columns of the next sample; the rest of the next sample, if any."""
    text = label(match.text)
    if text is None:
        return None
    x0, y0 = min(cur.x, nxt.x), min(cur.y, nxt.y)
    x1, y1 = max(cur.x + cur.w, nxt.x + nxt.w), max(cur.y + cur.h, nxt.y + nxt.h)
    joined = np.zeros((y1 - y0, x1 - x0), bool)
    joined[cur.y - y0:cur.y - y0 + cur.h, cur.x - x0:cur.x - x0 + cur.w] |= cmask
    bar = nmask.copy()
    bar[:, cut:] = False
    joined[nxt.y - y0:nxt.y - y0 + nxt.h, nxt.x - x0:nxt.x - x0 + nxt.w] |= bar
    tight = _tight(joined, x0, y0)
    if tight is None:
        return None
    pieces = [Piece(tight[0], tight[1], text, match.conf, match.alternatives)]
    if cut < nmask.shape[1]:
        rest = nmask.copy()
        rest[:, :cut] = False
        t2 = _tight(rest, nxt.x, nxt.y)
        if t2 is None:
            return None
        pieces.append(Piece(t2[0], t2[1], label(nxt_text) or "", 0.0))
    return Change("bar", [cur.id, nxt.id], pieces)


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
              "joins": sum(c.kind == "join" for c in plans), "bars": sum(c.kind == "bar" for c in plans),
              "refused": refused, "samples_new": 0, "placed": 0, "new_groups": []}
    if plans:
        result.update(_apply(lib, book_id, plans))
    result["seconds"] = round(time.time() - t0, 1)
    return result


SOURCES = {"split": "ocr-split", "join": "ocr-joined", "bar": "ocr-bar"}


def _apply(lib: Library, book_id: int, plans: List[Change]) -> Dict:
    """All changes as one action. Each new sample gets its akshara as a reading of the newest run and
    goes where its reading says (see `_place`); the rest go to Unsure."""
    with lib.session() as s:
        book = s.get(Book, book_id)
        cfg = lib.book_config(book)
        run_id = _run_id(s, book_id)
        targets = _labelled_centres(s, book_id)                  # before anything moves
        ch = _Change(s, book_id)
        old = ch.samples([sid for c in plans for sid in c.sample_ids])
        by_id = {x.id: x for x in old}
        prepared: Dict[int, object] = {}
        made: List[Tuple[Sample, str]] = []
        for c in plans:
            first = by_id[c.sample_ids[0]]
            page = s.get(Page, first.page_id)
            if page.id not in prepared:
                prepared[page.id] = page_ink(lib, book, page)
            for sid in c.sample_ids:
                by_id[sid].deleted, by_id[sid].group_id = True, None
            for p in c.pieces:
                smp = _new_sample(s, ch, lib, book, page, prepared[page.id], p.box, p.mask, SOURCES[c.kind],
                                  kind=first.kind)
                if p.text:
                    s.add(OcrReading(run_id=run_id, sample_id=smp.id, text_dev=p.text, confidence=round(p.conf, 1),
                                     alternatives=json.dumps(p.alternatives, ensure_ascii=False), overlap=1.0))
                made.append((smp, p.text))
        placed, new_groups = _place(s, ch, cfg, targets, made)
        counts = {k: sum(c.kind == k for c in plans) for k in ("split", "join", "bar")}
        a = ch.finish("fix_cuts", {"splits": counts["split"], "joins": counts["join"], "bars": counts["bar"],
                                   "samples": len(made), "placed": placed, "new_groups": new_groups})
        return {**_result(a), "samples_new": len(made)}


def _labelled_centres(s, book_id: int) -> Dict[str, Tuple[int, np.ndarray]]:
    """label -> (group id, centre) of the book's labelled groups that are not locked."""
    groups, C = centres(s, book_id, labelled_only=True)
    return {g.label_dev: (g.id, C[i]) for i, g in enumerate(groups) if not g.locked}


def _place(s, ch: _Change, cfg, targets: Dict[str, Tuple[int, np.ndarray]],
           made: List[Tuple[Sample, str]]) -> Tuple[int, List[str]]:
    """Put new samples where their reading says, when their shape agrees:
    - into the labelled group with that label, if the sample is within `group_distance` of its centre;
    - when no group has the label: into a new group with it, if at least `suggest_min_votes` new
      samples share the reading and look alike (within `group_distance` of their own centre). The
      group is labelled but not reviewed (the "Not reviewed" filter shows it), since only Tesseract
      and the cut say so.
    Everything else stays in Unsure. Returns the number placed and the labels of the new groups."""
    taken = set(s.scalars(select(LetterGroup.label_dev).where(LetterGroup.book_id == ch.book_id,
                                                              LetterGroup.label_dev != "")))
    mapping = mapping_for(cfg)
    placed, waiting = 0, {}
    for smp, text in made:
        if not text:
            continue
        if text in targets:
            gid, centre = targets[text]
            if float(np.linalg.norm(np.frombuffer(smp.fingerprint, np.float32) - centre)) <= cfg.group_distance:
                g = ch.group(gid)
                smp.group_id, smp.kind = g.id, g.kind
                placed += 1
        elif text not in taken:
            waiting.setdefault(text, []).append(smp)
    new_groups = []
    for text, smps in waiting.items():
        # only samples that look alike: within group_distance of their own centre
        if len(smps) >= cfg.suggest_min_votes:
            X = np.stack([np.frombuffer(x.fingerprint, np.float32) for x in smps])
            c = X.mean(axis=0)
            c /= max(float(np.linalg.norm(c)), 1e-9)
            smps = [x for x, d in zip(smps, np.linalg.norm(X - c, axis=1)) if d <= cfg.group_distance]
        if len(smps) < cfg.suggest_min_votes:
            continue
        g = ch.new_group(smps[0].kind)
        g.label_dev, g.label_guj, g.status = text, mapping.gujarati(text), "auto"
        for smp in smps:
            smp.group_id = g.id
        placed += len(smps)
        new_groups.append(text)
    return placed, new_groups

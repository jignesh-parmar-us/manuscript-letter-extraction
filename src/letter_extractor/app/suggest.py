"""Label suggestions (C11).

A Tesseract run reads every line image of a book, matches the aksharas it read to the line's samples
(ocr/align.py) and stores one reading per matched sample. Only readings that are valid labels (one
letter, or a word of whole letters) are kept, in Devanagari NFC like labels.

Group suggestions are not stored: they are voted from the readings of a group's current samples
whenever they are asked for (`group_readings`), so they follow every move, merge and split. Only a rejection is stored
on the group (`rejected_dev`). A suggestion never sets a label; accepting one is a normal label action.
"""
from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from sqlalchemy import delete, select

from .. import io_utils
from ..config import Config
from ..mapping import LabelError, canonical_label, mapping_for
from ..ocr.aksharas import line_aksharas
from ..ocr.align import align_line
from ..ocr.tesseract import LineReading, TesseractError, find_tesseract, read_line
from .db import Book, LetterGroup, Line, OcrReading, OcrRun, Page, Sample, now
from .library import Cancelled, Library, LibraryError

LineReader = Callable[[np.ndarray], LineReading]


@dataclass
class LineDone:
    """Progress of one line, in the shape the job's progress callback expects."""
    file: str
    status: str
    message: str
    seconds: float


def tesseract_reader(cfg: Config, tesseract_path: str = "") -> LineReader:
    """Read lines with the installed Tesseract and the book's settings (one thread per process,
    because several lines are read at once)."""
    try:
        engine = find_tesseract(tesseract_path)
        engine.check_langs(cfg.ocr_langs)
    except TesseractError as e:
        raise LibraryError(str(e)) from e
    return lambda rgb: read_line(rgb, engine, langs=cfg.ocr_langs, psm=cfg.ocr_psm,
                                 target_height=cfg.ocr_letter_height, env={"OMP_THREAD_LIMIT": "1"})


def _workers() -> int:
    return max(1, min(8, (os.cpu_count() or 2) - 1))


def run_tesseract(lib: Library, book_id: int, progress=None, cancel: Optional[Callable[[], bool]] = None,
                  reader: Optional[LineReader] = None, tesseract_path: str = "", workers: int = 0) -> Dict:
    """Read every line of the book and store the readings as the book's new Tesseract run. Nothing
    is stored when it is cancelled. `reader` replaces Tesseract (tests)."""
    t0 = time.time()
    book = lib.get_book(book_id)
    cfg = lib.book_config(book)
    if reader is None:
        reader = tesseract_reader(cfg, tesseract_path)
    book_dir = lib.book_dir(book)
    ocr_dir = book_dir / "ocr"
    ocr_dir.mkdir(exist_ok=True)

    with lib.session() as s:
        lines = s.execute(select(Line.id, Line.x, Line.image).join(Page, Line.page_id == Page.id)
                          .where(Page.book_id == book_id).order_by(Page.id, Line.number)).all()
        samples = s.execute(select(Sample.id, Sample.line_id, Sample.x, Sample.w)
                            .where(Sample.book_id == book_id, Sample.deleted.is_(False),
                                   Sample.line_id.is_not(None))
                            .order_by(Sample.x, Sample.pos)).all()
    by_line: Dict[int, List] = defaultdict(list)
    for sid, line_id, x, w in samples:
        by_line[line_id].append((sid, (x, x + w)))
    tasks = [(lid, lx, img) for lid, lx, img in lines if by_line.get(lid)]

    def read(task):
        line_id, line_x, image = task
        t = time.time()
        rgb, _ = io_utils.load_image(book_dir / image)
        reading = reader(rgb)
        (ocr_dir / (Path(image).stem + ".hocr")).write_text(reading.hocr, encoding="utf-8")
        spans = [sp for _, sp in by_line[line_id]]
        # the line image is the line's box with a margin (lines.line_image), cut off at the page edge
        dx = max(0, line_x - cfg.line_margin_px)
        al = align_line(line_aksharas(reading.words), spans, dx=dx, min_overlap=cfg.align_min_overlap,
                        sure_overlap=cfg.align_sure_overlap, min_matched=cfg.align_min_matched)
        return line_id, image, al, time.time() - t

    results, failed = [], []
    with ThreadPoolExecutor(max_workers=workers or _workers()) as pool:
        pending = {pool.submit(read, t): t for t in tasks}
        while pending:
            done, _ = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
            if cancel and cancel():
                for f in pending:
                    f.cancel()
                raise Cancelled("Cancelled; no suggestions were stored.")
            for f in done:
                task = pending.pop(f)
                name = Path(task[2]).name
                try:
                    line_id, image, al, secs = f.result()
                except (TesseractError, OSError, ValueError) as e:
                    failed.append(name)
                    status, message, secs = "FAILED", str(e), 0.0
                else:
                    results.append((line_id, al))
                    status = "REFUSED" if al.refused else "OK"
                    message = (f"{len(al.matches)} of {len(by_line[line_id])} letters matched"
                               + (", too few: line not used" if al.refused else ""))
                if progress:
                    progress(len(results) + len(failed), len(tasks), LineDone(name, status, message, secs))
    if tasks and not results:
        raise LibraryError(f"Tesseract could not read any line of the book ({failed[0]}…).")

    mapping = mapping_for(cfg)
    rows, invalid = [], 0
    for line_id, al in results:
        ids = [sid for sid, _ in by_line[line_id]]
        for mt in al.matches:
            try:
                text = canonical_label(mt.text, mapping, words=True)
            except LabelError:
                invalid += 1                 # a stray sign, a Latin letter, punctuation: not a label
                continue
            rows.append({"sample_id": ids[mt.sample], "text_dev": text, "confidence": round(mt.conf, 1),
                         "alternatives": json.dumps(mt.alternatives, ensure_ascii=False), "overlap": mt.overlap})
    result = {"lines": len(tasks), "lines_read": sum(not al.refused for _, al in results),
              "lines_refused": sum(al.refused for _, al in results), "lines_failed": len(failed),
              "samples": len(samples), "samples_matched": len(rows), "readings_not_labels": invalid}
    settings = {k: getattr(cfg, k) for k in ("ocr_langs", "ocr_psm", "ocr_letter_height", "align_min_overlap",
                                             "align_sure_overlap", "align_min_matched")}
    with lib.session() as s:
        s.execute(delete(OcrRun).where(OcrRun.book_id == book_id, OcrRun.engine == "tesseract"))
        run = OcrRun(book_id=book_id, engine="tesseract", settings=json.dumps(settings), finished_at=now())
        s.add(run)
        s.flush()
        for r in rows:
            s.add(OcrReading(run_id=run.id, **r))
        s.flush()
        result["groups_with_suggestion"] = sum(
            v["suggestion"] is not None for v in group_readings(s, s.get(Book, book_id), cfg).values())
        result["seconds"] = round(time.time() - t0, 1)
        run.result = json.dumps(result)
    return result


# ---- votes --------------------------------------------------------------------------------------

def vote(readings: Sequence[Tuple[str, float]], min_votes: int, min_share: float) -> Optional[Dict]:
    """The winning reading of a group, weighted by confidence, or None: too few readings, a tie, or
    a winner below `min_share`."""
    if len(readings) < min_votes:
        return None
    weight: Dict[str, float] = defaultdict(float)
    count: Dict[str, int] = defaultdict(int)
    for text, conf in readings:
        weight[text] += max(conf, 1.0)
        count[text] += 1
    ranked = sorted(weight.items(), key=lambda kv: -kv[1])
    total = sum(weight.values())
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None
    text, w = ranked[0]
    share = w / total
    if share < min_share:
        return None
    return {"label_dev": text, "share": round(share, 3), "count": count[text], "read": len(readings)}


def latest_runs(s, book_id: int) -> List[OcrRun]:
    return s.scalars(select(OcrRun).where(OcrRun.book_id == book_id, OcrRun.finished_at.is_not(None))
                     .order_by(OcrRun.id.desc())).all()


def _run_id(s, book_id: int, engine: str = "tesseract") -> Optional[int]:
    return s.scalar(select(OcrRun.id).where(OcrRun.book_id == book_id, OcrRun.engine == engine,
                                            OcrRun.finished_at.is_not(None)).order_by(OcrRun.id.desc()))


def group_readings(s, book: Book, cfg: Config, group_ids: Optional[Iterable[int]] = None) -> Dict[int, Dict]:
    """Per group of the book (or of `group_ids`) with readings in the newest Tesseract run:
    `read` (samples with a reading), `readings` (the 3 most common, with counts: a mixed group shows
    as two strong readings) and `suggestion` (the vote's winner, or None). Labelled groups, and
    groups whose winning reading the user rejected, get no suggestion."""
    run_id = _run_id(s, book.id)
    if run_id is None:
        return {}
    q = (select(Sample.group_id, OcrReading.text_dev, OcrReading.confidence)
         .join(OcrReading, OcrReading.sample_id == Sample.id)
         .where(OcrReading.run_id == run_id, Sample.deleted.is_(False), Sample.group_id.is_not(None)))
    if group_ids is not None:
        q = q.where(Sample.group_id.in_(list(group_ids)))
    per_group: Dict[int, List[Tuple[str, float]]] = defaultdict(list)
    for gid, text, conf in s.execute(q):
        per_group[gid].append((text, conf))
    if not per_group:
        return {}
    groups = {g.id: g for g in s.scalars(select(LetterGroup).where(LetterGroup.id.in_(list(per_group))))}
    by_label = {g.label_dev: g for g in s.scalars(select(LetterGroup).where(LetterGroup.book_id == book.id,
                                                                            LetterGroup.label_dev != ""))}
    mapping = mapping_for(cfg)
    out: Dict[int, Dict] = {}
    for gid, readings in per_group.items():
        g = groups.get(gid)
        if g is None:
            continue
        counts: Dict[str, int] = defaultdict(int)
        for text, _ in readings:
            counts[text] += 1
        top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
        suggestion = None
        if not g.label_dev:
            v = vote(readings, cfg.suggest_min_votes, cfg.suggest_min_share)
            if v is not None and v["label_dev"] != g.rejected_dev:
                other = by_label.get(v["label_dev"])
                suggestion = {**v, "label_guj": mapping.gujarati(v["label_dev"]), "engine": "tesseract",
                              "merge_into": {"id": other.id, "code": other.code} if other is not None else None}
        out[gid] = {"read": len(readings), "suggestion": suggestion,
                    "readings": [{"label_dev": t, "label_guj": mapping.gujarati(t), "count": n} for t, n in top]}
    return out


def sample_readings(s, book: Book, cfg: Config, sample_ids: Sequence[int], unsure: bool = True) -> Dict[int, Dict]:
    """Each sample's own Tesseract reading.

    For unsure samples (`unsure`), only readings at or above `suggest_min_confidence`, and none on
    handwritten books: there they would be offered for accepting, and Tesseract's confidence stays
    high when it is wrong (C10). For samples in a group, every reading: they are shown as badges
    where they differ from the group (C12), which is how mixed groups are found."""
    run_id = _run_id(s, book.id)
    if run_id is None or not sample_ids or (unsure and book.writing != "printed"):
        return {}
    mapping = mapping_for(cfg)
    q = select(OcrReading.sample_id, OcrReading.text_dev, OcrReading.confidence).where(
        OcrReading.run_id == run_id, OcrReading.sample_id.in_(list(sample_ids)))
    if unsure:
        q = q.where(OcrReading.confidence >= cfg.suggest_min_confidence)
    return {sid: {"label_dev": text, "label_guj": mapping.gujarati(text), "confidence": conf, "engine": "tesseract"}
            for sid, text, conf in s.execute(q)}


def samples_read_as(s, book: Book, group_id: int, text: str) -> List[int]:
    """The group's samples (not deleted) that the newest Tesseract run read as `text` (C12: select
    them, to split a mixed group)."""
    run_id = _run_id(s, book.id)
    if run_id is None:
        return []
    return list(s.scalars(select(Sample.id).join(OcrReading, OcrReading.sample_id == Sample.id)
                          .where(OcrReading.run_id == run_id, Sample.group_id == group_id,
                                 Sample.deleted.is_(False), OcrReading.text_dev == text).order_by(Sample.id)))


BANDS = [(0.9, "90% or more"), (0.75, "75 to 90%"), (0.0, "below 75%")]


def suggestion_accuracy(s, book: Book, cfg: Config) -> Dict:
    """How the suggestions compare with the user's labels (C12): each labelled group is voted as if
    it had no label. Right / wrong per share band, groups without a suggestion, the most common
    wrong pairs. Only meaningful once a good part of the book is labelled."""
    run_id = _run_id(s, book.id)
    groups = s.scalars(select(LetterGroup).where(LetterGroup.book_id == book.id, LetterGroup.label_dev != "")).all()
    out: Dict = {"labelled": len(groups), "suggested": 0, "right": 0, "none": 0,
                 "bands": [{"band": name, "right": 0, "wrong": 0} for _, name in BANDS], "wrong": []}
    if run_id is None or not groups:
        out["none"] = len(groups)
        return out
    per_group: Dict[int, List[Tuple[str, float]]] = defaultdict(list)
    for gid, text, conf in s.execute(
            select(Sample.group_id, OcrReading.text_dev, OcrReading.confidence)
            .join(OcrReading, OcrReading.sample_id == Sample.id)
            .where(OcrReading.run_id == run_id, Sample.deleted.is_(False),
                   Sample.group_id.in_([g.id for g in groups]))):
        per_group[gid].append((text, conf))
    wrong: Dict[Tuple[str, str], int] = defaultdict(int)
    for g in groups:
        v = vote(per_group.get(g.id, []), cfg.suggest_min_votes, cfg.suggest_min_share)
        if v is None:
            out["none"] += 1
            continue
        out["suggested"] += 1
        band = next(i for i, (low, _) in enumerate(BANDS) if v["share"] >= low)
        if v["label_dev"] == g.label_dev:
            out["right"] += 1
            out["bands"][band]["right"] += 1
        else:
            out["bands"][band]["wrong"] += 1
            wrong[(g.label_dev, v["label_dev"])] += 1
    mapping = mapping_for(cfg)
    out["wrong"] = [{"label": mapping.gujarati(a), "suggested": mapping.gujarati(b), "groups": n}
                    for (a, b), n in sorted(wrong.items(), key=lambda kv: -kv[1])[:10]]
    return out

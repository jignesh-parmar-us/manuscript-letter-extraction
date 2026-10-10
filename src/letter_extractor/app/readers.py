"""Training letter readers (C14) and using them on a book.

`train_reader`:
1. **letters:** every letter of the chosen books' Training Data in a labelled group, reviewed only unless
   `include_unreviewed`; word labels (several aksharas) only with `include_words`; labels with fewer than
   `min_samples` letters are left out and listed;
2. **pages kept aside:** about 15% of the pages are test pages (never trained on: the accuracy is
   measured on their letters) and about 10% validation pages (decide when training stops). A label
   with no letter left for training is trained on all its letters and shown as "not measured";
3. **training:** shape features (`ocr.features`), three varied copies of every training letter (more for
   rare labels), a linear reader and a network with one hidden layer (`ocr.reader`); the one with the
   better validation accuracy is kept;
4. **report:** overall accuracy and accuracy per label on the test pages, the most confused pairs;
5. **"Check these":** every training letter read by a reader that did not learn from its page (four
   folds by page) and every letter of a labelled but unreviewed group read by the final reader: those
   the reader is at least `check_sure` sure belong to another label than their group's;
6. the final reader is trained on all pages, saved in <library>/readers/<folder>/, recorded as a `Reader`
   and made the books' active reader.
`read_with_reader` then reads every Training Data letter of a book: its run of engine "reader" (votes,
badges and suggestions as with Tesseract).
"""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
from sqlalchemy import delete, select

from ..ocr.aksharas import split_aksharas
from ..ocr.features import features, varied
from ..ocr.reader import LetterReader
from .db import Book, LetterGroup, OcrReading, OcrRun, Page, Reader, Sample, now
from .library import Cancelled, Library, LibraryError
from .samples import _sample_mask

CHECK_SURE = 0.9
FOLDS = 4


class Step:
    """Progress in the form the app's jobs show (file, status, message, seconds)."""
    def __init__(self, what: str, message: str = "", seconds: float = 0.0):
        self.file, self.status, self.message, self.seconds = what, "OK", message, seconds


def _letters(lib: Library, book_ids: Sequence[int], include_unreviewed: bool, include_words: bool):
    """(sample id, book id, page id, label, group status, features) of the training letters."""
    out = []
    with lib.session() as s:
        for bid in book_ids:
            book = s.get(Book, bid)
            if book is None:
                raise LibraryError(f"No book with id {bid}.")
            q = (select(Sample, LetterGroup.label_dev, LetterGroup.status, Page.line_spacing)
                 .join(LetterGroup, Sample.group_id == LetterGroup.id).join(Page, Sample.page_id == Page.id)
                 .where(Sample.book_id == bid, Sample.deleted.is_(False), Sample.part == "training",
                        LetterGroup.label_dev != ""))
            if not include_unreviewed:
                q = q.where(LetterGroup.status != "auto")
            for x, label, status, spacing in s.execute(q).all():
                if not include_words and len(split_aksharas(label)) > 1:
                    continue
                mask = _sample_mask(lib, book, x)
                out.append((x.id, bid, x.page_id, label, status, mask, float(spacing or 1.6 * x.h)))
    return out


class _Features:
    """Every letter's features and those of its varied copies, computed once and reused by the six
    trainings (the reader, the check folds, the final reader)."""
    def __init__(self, items, ci: Dict[str, int], copies: Dict[str, int], rng):
        self.ci = ci
        self.base = {it[0]: features(it[5], it[6]) for it in items}
        self.extra = {it[0]: [features(varied(it[5], rng), it[6]) for _ in range(copies.get(it[3], 0))] for it in items}

    def rows(self, items, with_copies: bool = True, at_most: int = 99) -> Tuple[np.ndarray, np.ndarray]:
        X, y = [], []
        for it in items:
            X.append(self.base[it[0]])
            y.append(self.ci[it[3]])
            if with_copies:
                for v in self.extra[it[0]][:at_most]:
                    X.append(v)
                    y.append(self.ci[it[3]])
        dim = len(next(iter(self.base.values())))
        return (np.array(X, np.float32).reshape(-1, dim), np.array(y, np.int64))


def _fit(classes, X, y, Xv, yv, cancel=None) -> Tuple[LetterReader, str, float]:
    """Train a linear reader and a network; keep the one with the better validation accuracy."""
    best = None
    for hidden, kind in ((0, "features-linear"), (384, "features-mlp")):
        if cancel and cancel():
            raise Cancelled("Training cancelled; no reader was saved.")
        r = LetterReader(classes, X.shape[1], hidden=hidden)
        r.train(X, y, Xv if len(Xv) else None, yv if len(yv) else None, epochs=60 if len(Xv) else 12, cancel=cancel)
        acc = float((r.probabilities(Xv).argmax(axis=1) == yv).mean()) if len(Xv) else 0.0
        if best is None or acc > best[2]:
            best = (r, kind, acc)
    return best


def train_reader(lib: Library, book_ids: Sequence[int], min_samples: int = 5, include_unreviewed: bool = False,
                 include_words: bool = False, name: str = "", progress=None,
                 cancel: Optional[Callable[[], bool]] = None, activate: Sequence[int] = ()) -> Dict:
    t0 = time.time()
    rng = np.random.default_rng(0)
    if min_samples < 1:
        raise LibraryError("A label needs at least one letter.")

    def step(n, total, what, msg=""):
        if progress:
            progress(n, total, Step(what, msg, time.time() - t0))
    step(0, 6, "letters")
    items = _letters(lib, book_ids, include_unreviewed, include_words)
    counts = Counter(it[3] for it in items)
    kept = sorted(lab for lab, n in counts.items() if n >= min_samples)
    left_out = sorted(((lab, n) for lab, n in counts.items() if n < min_samples), key=lambda kv: -kv[1])
    items = [it for it in items if it[3] in set(kept)]
    if len(kept) < 2:
        raise LibraryError("Too few labelled letters to train a reader: label and review more groups first "
                           f"(labels with at least {min_samples} letters: {len(kept)}).")
    ci = {c: i for i, c in enumerate(kept)}
    pages = sorted({it[2] for it in items})
    test_pages = set(pages[3::7]) if len(pages) >= 7 else set(pages[-1:]) if len(pages) > 1 else set()
    val_pages = (set(pages[5::9]) if len(pages) >= 9 else set(pages[:1]) if len(pages) > 2 else set()) - test_pages
    held = test_pages | val_pages
    # a label with no letter outside the held-out pages is trained on all its letters
    outside = {it[3] for it in items if it[2] not in held}
    train = [it for it in items if it[2] not in held or it[3] not in outside]
    val = [it for it in items if it[2] in val_pages and it[3] in outside]
    test = [it for it in items if it[2] in test_pages and it[3] in outside]
    copies = {lab: max(3, min(30, -(-20 // max(1, n)))) for lab, n in counts.items() if lab in ci}   # rare: more
    step(1, 6, "features", f"{len(items)} letters, {len(kept)} labels")
    feats = _Features(items, ci, copies, rng)
    X, y = feats.rows(train)
    Xv, yv = feats.rows(val, with_copies=False)
    Xt, yt = feats.rows(test, with_copies=False)
    step(2, 6, "training", f"{len(X)} training rows")
    reader, kind, val_acc = _fit(kept, X, y, Xv, yv, cancel)

    # ---- report on the test pages
    per: Dict[str, List[int]] = defaultdict(lambda: [0, 0])
    confusions: Counter = Counter()
    pred_t = reader.probabilities(Xt).argmax(axis=1) if len(Xt) else np.zeros(0, np.int64)
    for a, b in zip(yt, pred_t):
        per[kept[a]][0] += 1
        per[kept[a]][1] += int(a == b)
        if a != b:
            confusions[(kept[a], kept[b])] += 1
    overall = float((pred_t == yt).mean()) if len(yt) else None
    big = [i for i, a in enumerate(yt) if counts[kept[a]] >= 20]
    big_acc = float((pred_t[big] == yt[big]).mean()) if big else None
    per_label = [{"label": lab, "letters": counts[lab], "tested": per[lab][0],
                  "accuracy": round(per[lab][1] / per[lab][0], 3) if per[lab][0] else None} for lab in kept]
    per_label.sort(key=lambda r: (r["accuracy"] is None, r["accuracy"] if r["accuracy"] is not None else 0, -r["letters"]))

    # ---- "Check these": each training letter read by a reader that did not learn from its page
    step(3, 6, "checking", "letters probably in the wrong group")
    check: List[Dict] = []
    fold_of = {p: i % FOLDS for i, p in enumerate(pages)}
    for f in range(FOLDS):
        if cancel and cancel():
            raise Cancelled("Training cancelled; no reader was saved.")
        inside = [it for it in items if fold_of[it[2]] != f]
        out = [it for it in items if fold_of[it[2]] == f]
        if not out or len({it[3] for it in inside}) < 2:
            continue
        Xi, yi = feats.rows(inside, at_most=1)
        r = LetterReader(kept, Xi.shape[1], hidden=reader.hidden)
        r.train(Xi, yi, epochs=12)
        Xo, yo = feats.rows(out, with_copies=False)
        p = r.probabilities(Xo)
        for it, row, truth in zip(out, p, yo):
            k = int(row.argmax())
            if k != truth and row[k] >= CHECK_SURE:
                check.append({"sample_id": it[0], "book_id": it[1], "label": it[3], "read": kept[k],
                              "prob": round(float(row[k]), 3), "reviewed": it[4] != "auto"})

    # ---- the final reader, on every page
    step(4, 6, "final reader", "all pages")
    Xa, ya = feats.rows(items)
    final = LetterReader(kept, Xa.shape[1], hidden=reader.hidden)
    final.train(Xa, ya, epochs=12, cancel=cancel)
    if cancel and cancel():
        raise Cancelled("Training cancelled; no reader was saved.")
    # letters of labelled groups not reviewed (not trained on unless asked): read by the final reader
    if not include_unreviewed:
        extra = _letters(lib, book_ids, True, include_words)
        extra = [it for it in extra if it[4] == "auto" and it[3] in ci]
        if extra:
            Xe = np.stack([features(it[5], it[6]) for it in extra])
            ye = np.array([ci[it[3]] for it in extra])
            p = final.probabilities(Xe)
            for it, row, truth in zip(extra, p, ye):
                k = int(row.argmax())
                if k != truth and row[k] >= CHECK_SURE:
                    check.append({"sample_id": it[0], "book_id": it[1], "label": it[3], "read": kept[k],
                                  "prob": round(float(row[k]), 3), "reviewed": False})
    check.sort(key=lambda c: -c["prob"])

    # ---- saved, recorded, made active
    step(5, 6, "saving")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    with lib.session() as s:
        n = (s.scalar(select(Reader.id).order_by(Reader.id.desc())) or 0) + 1
        names = [s.get(Book, b).name for b in book_ids]
        rec = Reader(name=name.strip() or f"Reader {n} ({', '.join(names)})", folder=f"{n:04d}-{stamp}", kind=kind,
                     classes=json.dumps(kept, ensure_ascii=False))
        s.add(rec)
        s.flush()
        final.save(lib.root / "readers" / rec.folder / "reader.npz")
        rec.trained_on = json.dumps({"books": list(book_ids), "book_names": names, "letters": len(items),
                                     "labels": len(kept), "min_samples": min_samples,
                                     "include_unreviewed": include_unreviewed, "include_words": include_words,
                                     "left_out": left_out, "test_pages": len(test_pages), "test_letters": len(test)},
                                    ensure_ascii=False)
        rec.accuracy = json.dumps({"overall": overall, "labels_20": big_acc, "validation": val_acc,
                                   "per_label": per_label}, ensure_ascii=False)
        rec.report = json.dumps({"confusions": [[a, b, n] for (a, b), n in confusions.most_common(30)],
                                 "check": check, "seconds": round(time.time() - t0, 1)}, ensure_ascii=False)
        for bid in activate or book_ids:
            s.get(Book, bid).reader_id = rec.id
        rid = rec.id
    step(6, 6, "done")
    return {"reader": rid, "kind": kind, "labels": len(kept), "letters": len(items), "accuracy": overall,
            "accuracy_20": big_acc, "check": len(check), "left_out": len(left_out),
            "seconds": round(time.time() - t0, 1)}


def load_reader(lib: Library, reader_id: int) -> Tuple[Reader, LetterReader]:
    with lib.session() as s:
        rec = s.get(Reader, reader_id)
        if rec is None:
            raise LibraryError(f"No reader with id {reader_id}.")
    return rec, LetterReader.load(lib.root / "readers" / rec.folder / "reader.npz")


def read_with_reader(lib: Library, book_id: int, reader_id: Optional[int] = None) -> Dict:
    """Read every Training Data letter of a book with its active reader (or `reader_id`) and store it
    as the book's run of engine "reader": groups then vote with these readings."""
    t0 = time.time()
    book = lib.get_book(book_id)
    rid = reader_id or book.reader_id
    if not rid:
        raise LibraryError("This book has no letter reader yet: train one first.")
    rec, reader = load_reader(lib, rid)
    with lib.session() as s:
        smps = s.execute(select(Sample, Page.line_spacing).join(Page, Sample.page_id == Page.id)
                         .where(Sample.book_id == book_id, Sample.deleted.is_(False), Sample.part == "training",
                                Sample.mask != "")).all()
        rows = [(x.id, features(_sample_mask(lib, book, x), float(sp or 1.6 * x.h))) for x, sp in smps]
    if not rows:
        return {"samples": 0}
    P = reader.probabilities(np.stack([r[1] for r in rows]))
    with lib.session() as s:
        s.execute(delete(OcrRun).where(OcrRun.book_id == book_id, OcrRun.engine == "reader"))
        run = OcrRun(book_id=book_id, engine="reader", finished_at=now(),
                     settings=json.dumps({"reader": rid, "name": rec.name}, ensure_ascii=False))
        s.add(run)
        s.flush()
        for (sid, _), p in zip(rows, P):
            k = int(p.argmax())
            s.add(OcrReading(run_id=run.id, sample_id=sid, text_dev=reader.classes[k], confidence=round(float(p[k]) * 100, 1),
                             alternatives="[]", overlap=1.0))
        result = {"samples": len(rows), "reader": rid, "seconds": round(time.time() - t0, 1)}
        run.result = json.dumps(result)
    return result


def check_list(lib: Library, book_id: int) -> List[Dict]:
    """The active reader's "Check these" letters of this book that are still where they were (same label,
    not deleted): each with the label its group has and the one the reader read."""
    book = lib.get_book(book_id)
    if not book.reader_id:
        return []
    with lib.session() as s:
        rec = s.get(Reader, book.reader_id)
        items = [c for c in json.loads(rec.report or "{}").get("check", []) if c["book_id"] == book_id]
        out = []
        for c in items:
            x = s.get(Sample, c["sample_id"])
            if x is None or x.deleted or x.group_id is None:
                continue
            g = s.get(LetterGroup, x.group_id)
            if g is None or g.label_dev != c["label"]:
                continue
            out.append({**c, "group_id": g.id, "locked": g.locked})
        return out


def delete_reader(lib: Library, reader_id: int) -> None:
    import shutil
    with lib.session() as s:
        rec = s.get(Reader, reader_id)
        if rec is None:
            raise LibraryError(f"No reader with id {reader_id}.")
        folder = lib.root / "readers" / rec.folder
        for b in s.scalars(select(Book).where(Book.reader_id == reader_id)):
            b.reader_id = None
        s.delete(rec)
    shutil.rmtree(folder, ignore_errors=True)

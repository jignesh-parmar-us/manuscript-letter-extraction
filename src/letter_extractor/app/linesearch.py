"""A second opinion on lines read whole: the line search (`ocr.segment`) reads each line again without
Tesseract, and the aksharas where the two readings differ are marked uncertain (docs/SEGMENTATION_PLAN.md,
stages 4 and 5). Measured on 73 hand-checked lines of the printed 1933 book (2026-10-11): the marks fall
on 19.4% of the aksharas and on 88% of the aksharas still wrong after Tesseract + language model
(Tesseract's own confidence marks 0.2%). The text itself stays Tesseract's.

The line search needs its own reader, trained on the book's reviewed Training Data letters with a
"not a letter" class (`train_line_reader`, as in stage 2):
- **letters:** each reviewed single-akshara letter, as its mask and as the window of its columns cut from
  its whole line (the neighbours' overhanging ink included), the window shifted by 3-10% either way, and
  varied copies (more for rare labels): all count as the letter (a tolerance band);
- **not a letter:** its two halves, the letter with its close next neighbour, the window shifted 25-45%;
- every label weighs the same in total; all negatives together weigh a quarter of a label per label.
It is kept in the book folder (line-search/) with each label's usual width, and used until trained again
(Retrain in Whole lines (our reader)); `reader_info` says when the reviewed letters changed since.

Its reading is kept per line (`search_dev`) with each akshara's place on the page (`search_aksharas`), so
Text → Whole lines (our reader) can show it like Tesseract's. `measure` scores it fold-fair on the checked
lines (Line truth): the Read Book pages are also Training Data pages, so for each fold of pages the reader
and the language model are rebuilt without them (as in stages 3 and 4).
"""
from __future__ import annotations

import difflib
import hashlib
import json
import time
import unicodedata
from collections import Counter, defaultdict
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np
from sqlalchemy import and_, or_, select

from ..ocr.aksharas import split_aksharas
from ..ocr.features import features, varied
from ..ocr.reader import LetterReader
from ..ocr.segment import SearchSettings, align, clear_borders, line_windows, read_line
from .db import Book, LetterGroup, Line, Page, Sample, WholeLine, now
from .library import Cancelled, Library, LibraryError, NotFound
from .samples import _sample_mask
from .suggest import LineDone

NOT_A_LETTER = "<not a letter>"
NEG_WEIGHT = 0.25
EPOCHS = 40                 # 15 before learning from corrections; 40 measured better (TUNING_PHASE2.md)
BASE_EPOCHS = 15            # the reader that cuts the checked lines into their aksharas
MIN_ALIGN = -3.0            # a checked line whose cut scores less per akshara is not learned from


def _folder(lib: Library, book: Book):
    return lib.book_dir(book) / "line-search"


def _signature(s, book_id: int) -> str:
    """What the reader learns from (each reviewed Training Data letter: its label and place; each checked
    line of the Read Book pages and its text), as a hash."""
    from .db import LineTruth
    checked = s.execute(select(LineTruth.line_id, LineTruth.text_dev).join(Line, LineTruth.line_id == Line.id)
                        .join(Page, Line.page_id == Page.id)
                        .where(Page.book_id == book_id, Page.part == "read", LineTruth.text_dev != "")
                        .order_by(LineTruth.line_id)).all()
    rows = s.execute(select(Sample.id, LetterGroup.label_dev, LetterGroup.status, Sample.x, Sample.w)
                     .join(LetterGroup, Sample.group_id == LetterGroup.id).outerjoin(Page, Sample.page_id == Page.id)
                     .where(Sample.book_id == book_id, Sample.deleted.is_(False), LetterGroup.label_dev != "",
                            LetterGroup.status != "auto",
                            or_(and_(Page.part == "training", Sample.line_id.is_not(None)),
                                and_(Sample.line_id.is_(None), Sample.mask != "")))   # also letters on no line
                     .order_by(Sample.id)).all()
    return hashlib.sha1(json.dumps([[list(r) for r in rows], [list(r) for r in checked]],
                                   ensure_ascii=False).encode()).hexdigest()


def line_reader_info(lib: Library, book_id: int) -> Optional[Dict]:
    """What the book's line-search reader was trained on, or None if it has none; `changed`: the reviewed
    letters or the checked lines changed since (retrain to use them)."""
    meta = _folder(lib, lib.get_book(book_id)) / "meta.json"
    if not meta.is_file():
        return None
    info = json.loads(meta.read_text(encoding="utf-8"))
    with lib.session() as s:
        changed = info.get("signature") != _signature(s, book_id)
    return {**{k: info[k] for k in ("letters", "labels", "trained_at", "seconds")}, "lines": info.get("lines", 0),
            "changed": changed}


def _paste(lib: Library, book: Book, smps: Sequence[Sample]):
    """The line's ink: every sample's mask pasted at its place. (mask, left column, masks by sample id)."""
    x0 = min(m.x for m in smps)
    y0 = min(m.y for m in smps)
    x1 = max(m.x + m.w for m in smps)
    y1 = max(m.y + m.h for m in smps)
    c = np.zeros((y1 - y0, x1 - x0), bool)
    masks = {}
    for m in smps:
        mk = _sample_mask(lib, book, m)
        masks[m.id] = mk
        c[m.y - y0:m.y - y0 + mk.shape[0], m.x - x0:m.x - x0 + mk.shape[1]] |= mk
    return c, x0, masks


def _crop(c: np.ndarray, a: int, b: int) -> Optional[np.ndarray]:
    part = c[:, max(0, a):min(c.shape[1], b)]
    ys, xs = np.nonzero(part)
    return None if ys.size < 10 else part[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def train_line_reader(lib: Library, book_id: int, progress: Optional[Callable[[str], None]] = None,
                      cancel: Optional[Callable[[], bool]] = None, seed: int = 0) -> Dict:
    """Train and keep the book's line-search reader (see the module notes)."""
    t0 = time.time()
    book = lib.get_book(book_id)
    with lib.session() as s:
        signature = _signature(s, book_id)
    reader, meta = _train(lib, book_id, (), progress, cancel, seed)
    folder = _folder(lib, book)
    folder.mkdir(parents=True, exist_ok=True)
    reader.save(folder / "reader.npz")
    info = {"lines": 0, **meta, "trained_at": now().isoformat(), "seconds": round(time.time() - t0, 1),
            "signature": signature}
    (folder / "meta.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    return {k: info[k] for k in ("letters", "labels", "lines", "trained_at", "seconds")}


def _train(lib: Library, book_id: int, skip_files: Sequence[str] = (), progress=None, cancel=None, seed: int = 0):
    """The reader and its meta (letters, labels, checked lines learned, typical width, each label's
    width), trained on the reviewed letters of the Training Data pages and on the checked lines of the
    Read Book pages (learning from corrections), those of the pages `skip_files` left out."""
    data = _training_set(lib, book_id, skip_files, progress, cancel, seed)
    if progress:
        progress(f"training on {len(data['X'])} windows")
    base = _fit(data, cancel, epochs=BASE_EPOCHS)
    learned = _learn_corrections(lib, book_id, data, base, skip_files, progress, cancel)
    if learned["lines"]:
        data = _with_corrections(data, learned)
    reader = _fit(data, cancel)
    return reader, {**data["meta"], "lines": learned["lines"]}


def _checked_lines(lib: Library, book_id: int, skip_files: Sequence[str] = ()) -> List[tuple]:
    """(line id, page file, line spacing, checked text) of the checked lines of the Read Book pages."""
    from .db import LineTruth
    with lib.session() as s:
        q = (select(Line.id, Page.file, Page.line_spacing, LineTruth.text_dev)
             .join(LineTruth, LineTruth.line_id == Line.id).join(Page, Line.page_id == Page.id)
             .where(Page.book_id == book_id, Page.part == "read", LineTruth.text_dev != ""))
        if skip_files:
            q = q.where(Page.file.not_in(list(skip_files)))
        return [tuple(r) for r in s.execute(q.order_by(Page.number, Page.id, Line.number)).all()]


def _line_ink(lib: Library, book: Book, line_id: int, typical_width: float):
    """A line's ink (its cut letters' masks pasted together, a page border at its edges cleared), with its
    top left corner on the page; None for a line without letters."""
    with lib.session() as s:
        smps = s.scalars(select(Sample).where(Sample.line_id == line_id, Sample.deleted.is_(False))).all()
        if not smps:
            return None
        c, x0, _ = _paste(lib, book, smps)
        y0 = min(m.y for m in smps)
        band = (float(np.median([m.y - y0 for m in smps])), float(np.median([m.y + m.h - y0 for m in smps])))
        c, _ = clear_borders(c, typical_width, float(np.median([m.h for m in smps])), band)
    return c, x0, y0


def _learn_corrections(lib: Library, book_id: int, data: Dict, base: LetterReader, skip_files: Sequence[str] = (),
                       progress=None, cancel=None) -> Dict:
    """Learning from corrections: each checked line is cut into the aksharas of its checked text
    (`segment.align`, with the reader trained on the letters), and each of its windows becomes a training
    example of its akshara, also of aksharas no group has yet."""
    book = lib.get_book(book_id)
    T = data["meta"]["typical_width"]
    X, labels, widths, used = [], [], defaultdict(list), 0
    rows = _checked_lines(lib, book_id, skip_files)
    for n, (lid, _, spacing, text) in enumerate(rows, 1):
        if cancel and cancel():
            raise Cancelled("Cancelled; the line search reader was not changed.")
        if progress and n % 10 == 1:
            progress(f"learning from the checked lines: {n} of {len(rows)}")
        ink = _line_ink(lib, book, lid, T)
        if ink is None:
            continue
        win = line_windows(ink[0], spacing or 100.0, T)
        if win is None or not len(win.X):
            continue
        aks = [a for a in split_aksharas(_chars(text)) if a.strip() and a != "?"]
        path, score = align(win, base.probabilities(win.X), base.classes, T, aks)
        if path is None or score < MIN_ALIGN:
            continue
        used += 1
        for q, a in path:
            X.append(win.X[q])
            labels.append(a)
            widths[a].append(win.meta[q][2])
    return {"lines": used, "X": X, "labels": labels, "widths": widths}


def _with_corrections(data: Dict, learned: Dict) -> Dict:
    """The training set with the checked lines' windows added (new labels get a class); weights again so
    that every label weighs the same in total."""
    old = data["classes"]
    labels = sorted(set(old[:-1]) | set(learned["labels"]))
    classes = labels + [NOT_A_LETTER]
    ci = {c: i for i, c in enumerate(classes)}
    y = np.concatenate([np.array([ci[old[k]] for k in data["y"]], np.int64),
                        np.array([ci[a] for a in learned["labels"]], np.int64)])
    X = np.concatenate([data["X"], np.array(learned["X"], np.float32)])
    per = Counter(y.tolist())
    notl = ci[NOT_A_LETTER]
    weights = np.array([(NEG_WEIGHT * (len(per) - 1) if k == notl else 1.0) / per[int(k)] for k in y], np.float32)
    weights *= len(weights) / weights.sum()
    meta = dict(data["meta"])
    meta["widths"] = {**{a: float(np.median(v)) for a, v in learned["widths"].items()}, **meta["widths"]}
    meta["labels"] = len(labels)
    return {"X": X, "y": y, "weights": weights, "classes": classes, "meta": meta}


def _fit(data: Dict, cancel=None, hidden: int = 0, epochs: int = EPOCHS) -> LetterReader:
    reader = LetterReader(data["classes"], data["X"].shape[1], hidden=hidden)
    reader.train(data["X"], data["y"], weights=data["weights"], epochs=epochs, cancel=cancel)
    if cancel and cancel():
        raise Cancelled("Cancelled; the line search reader was not changed.")
    return reader


def _training_set(lib: Library, book_id: int, skip_files: Sequence[str] = (), progress=None, cancel=None,
                  seed: int = 0, unlined: bool = True) -> Dict:
    """The training windows (X, y, weights), the classes and the meta, before fitting. With `unlined`, the
    reviewed letters that are on no line (System generated, uploaded) are learned from their picture alone
    (and its varied copies): there is no line to cut windows or "not a letter" pieces from."""
    rng = np.random.default_rng(seed)
    book = lib.get_book(book_id)
    letters = []
    with lib.session() as s:
        q = (select(Sample, LetterGroup.label_dev, Page.line_spacing)
             .join(LetterGroup, Sample.group_id == LetterGroup.id).join(Page, Sample.page_id == Page.id)
             .where(Sample.book_id == book_id, Sample.deleted.is_(False), Page.part == "training",
                    Sample.line_id.is_not(None), LetterGroup.label_dev != ""))
        if skip_files:
            q = q.where(Page.file.not_in(list(skip_files)))
        rows = s.execute(q).all()
        status = dict(s.execute(select(LetterGroup.id, LetterGroup.status)
                                .where(LetterGroup.book_id == book_id)).all())
        by_line = defaultdict(list)
        for smp, lab, spacing in rows:
            by_line[smp.line_id].append((smp, lab, spacing))
        for items in by_line.values():
            if cancel and cancel():
                raise Cancelled("Cancelled; the line search reader was not changed.")
            # the line's ink from all its letters, labelled or not
            line_smps = s.scalars(select(Sample).where(Sample.line_id == items[0][0].line_id,
                                                       Sample.deleted.is_(False))).all()
            c, x0, masks = _paste(lib, book, line_smps)
            order = sorted(line_smps, key=lambda m: m.x)
            nxt_of = {a.id: b for a, b in zip(order, order[1:])}
            for smp, lab, spacing in items:
                if status.get(smp.group_id) == "auto" or len(split_aksharas(lab)) != 1:
                    continue
                nxt = nxt_of.get(smp.id)
                letters.append(dict(label=lab, x=smp.x, w=smp.w, mask=masks[smp.id], c=c, x0=x0,
                                    sp=spacing or 1.6 * smp.h, nxt=(nxt.x, nxt.w) if nxt is not None else None))
        if unlined:
            spacings = [v for v in s.scalars(select(Page.line_spacing).where(Page.book_id == book_id,
                                                                             Page.part == "training")) if v]
            usual = float(np.median(spacings)) if spacings else 0.0
            alone = s.execute(select(Sample, LetterGroup.label_dev)
                              .join(LetterGroup, Sample.group_id == LetterGroup.id)
                              .where(Sample.book_id == book_id, Sample.deleted.is_(False), Sample.line_id.is_(None),
                                     Sample.mask != "", LetterGroup.label_dev != "",
                                     LetterGroup.status != "auto")).all()
            for smp, lab in alone:
                if len(split_aksharas(lab)) != 1:
                    continue
                letters.append(dict(label=lab, x=smp.x, w=smp.w, mask=_sample_mask(lib, book, smp), c=None, x0=0,
                                    sp=usual or 1.6 * smp.h, nxt=None))
    if len(letters) < 20 or len({L["label"] for L in letters}) < 2:
        raise LibraryError("The line search learns the letters from this book's reviewed Training Data: review "
                           "and label more groups first (at least 20 letters).")
    if progress:
        progress(f"{len(letters)} reviewed letters; their windows")
    freq = Counter(L["label"] for L in letters)
    for n, L in enumerate(letters):
        if cancel and n % 500 == 0 and cancel():
            raise Cancelled("Cancelled; the line search reader was not changed.")
        x, w, c, x0, sp = L["x"], L["w"], L["c"], L["x0"], L["sp"]
        if c is None:                                       # on no line: its picture and its varied copies
            L["pos"] = [features(L["mask"], sp)] + [features(varied(L["mask"], rng), sp)
                                                    for _ in range(max(3, min(30, -(-20 // freq[L["label"]]))))]
            L["negs"] = []
            continue

        def win(a, b):
            m = _crop(c, a - x0, b - x0)
            return features(m, sp) if m is not None else None
        pos = [features(L["mask"], sp), win(x, x + w)]
        for sign in (-1, 1):
            shift = sign * max(1, int(round(rng.uniform(0.03, 0.10) * w)))
            pos.append(win(x + shift, x + w + shift))
        pos += [features(varied(L["mask"], rng), sp) for _ in range(max(3, min(30, -(-20 // freq[L["label"]]))))]
        negs = [win(x, x + w // 2), win(x + w // 2, x + w)]
        if L["nxt"] is not None and L["nxt"][0] - (x + w) < 0.5 * w:
            negs.append(win(x, L["nxt"][0] + L["nxt"][1]))
        for sign in (-1, 1):
            shift = sign * int(round(rng.uniform(0.25, 0.45) * w))
            negs.append(win(x + shift, x + w + shift))
        L["pos"] = [f for f in pos if f is not None]
        L["negs"] = [f for f in negs if f is not None]
        del L["c"]
    classes = sorted(freq) + [NOT_A_LETTER]
    ci = {c_: i for i, c_ in enumerate(classes)}
    X, y = [], []
    for L in letters:
        for f in L["pos"]:
            X.append(f)
            y.append(ci[L["label"]])
        for f in L["negs"]:
            X.append(f)
            y.append(ci[NOT_A_LETTER])
    X, y = np.array(X, np.float32), np.array(y, np.int64)
    per = Counter(y.tolist())
    weights = np.array([(NEG_WEIGHT * (len(per) - 1) if k == ci[NOT_A_LETTER] else 1.0) / per[int(k)] for k in y],
                       np.float32)
    weights *= len(weights) / weights.sum()
    widths = defaultdict(list)
    for L in letters:
        widths[L["label"]].append(L["w"])
    return {"X": X, "y": y, "weights": weights, "classes": classes,
            "meta": {"letters": len(letters), "labels": len(freq),
                     "typical_width": float(np.median([L["w"] for L in letters])),
                     "widths": {k: float(np.median(v)) for k, v in widths.items()}}}


def _load(lib: Library, book: Book):
    folder = _folder(lib, book)
    if not (folder / "meta.json").is_file():
        return None
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    return LetterReader.load(folder / "reader.npz"), meta


def _read_lines(lib: Library, book: Book, line_ids: Sequence[int], spacing: float, model, lm,
                settings: SearchSettings = SearchSettings()) -> Dict[int, tuple]:
    """{line id: (text, aksharas)} for the lines with cut letters (their ink); aksharas as `search_aksharas`."""
    reader, meta = model
    found = {}
    for lid in line_ids:
        ink = _line_ink(lib, book, lid, meta["typical_width"])
        if ink is None:
            continue
        c, x0, y0 = ink
        text, steps, _ = read_line(c, spacing, reader, meta["typical_width"], meta["widths"], lm, settings)
        aks = []
        for st in steps:
            rows = np.flatnonzero(c[:, st.x0:st.x1].any(axis=1))
            box = [int(x0 + st.x0), int(y0 + rows.min()), int(st.x1 - st.x0), int(rows.max() - rows.min() + 1)] \
                if rows.size else None
            aks.append([unicodedata.normalize("NFC", st.label), bool(st.space), box])
        found[lid] = (unicodedata.normalize("NFC", text), aks)
    return found


def search_page(lib: Library, page_id: int, model, lm, settings: SearchSettings = SearchSettings()) -> Dict:
    """Read every line of a page that was read whole again with the line search, and keep its reading."""
    with lib.session() as s:
        page = s.get(Page, page_id)
        if page is None:
            raise NotFound(f"No page with id {page_id}.")
        book = s.get(Book, page.book_id)
        spacing = page.line_spacing or 100.0
        line_ids = list(s.scalars(select(Line.id).join(WholeLine, WholeLine.line_id == Line.id)
                                  .where(Line.page_id == page_id).order_by(Line.number)))
        file = page.file
    found = _read_lines(lib, book, line_ids, spacing, model, lm, settings)
    with lib.session() as s:
        for lid, (text, aks) in found.items():
            row = s.scalar(select(WholeLine).where(WholeLine.line_id == lid))
            if row is not None:
                row.search_dev, row.search_at = text, now()
                row.search_aksharas = json.dumps(aks, ensure_ascii=False)
    return {"page": file, "lines": len(found)}


def search_book(lib: Library, book_id: int, page_ids: Optional[Sequence[int]] = None, part: str = "read",
                retrain: bool = False, progress=None, cancel: Optional[Callable[[], bool]] = None) -> Dict:
    """The second opinion on the pages read whole (or the given ones): the reader is trained first when the
    book has none (or `retrain`), then each page is searched and stored when done."""
    t0 = time.time()
    book = lib.get_book(book_id)
    with lib.session() as s:
        q = (select(Page.id).join(Line, Line.page_id == Page.id).join(WholeLine, WholeLine.line_id == Line.id)
             .where(Page.book_id == book_id).distinct())
        q = q.where(Page.id.in_(list(page_ids))) if page_ids else q.where(Page.part == part)
        ids = list(s.scalars(q.order_by(Page.number, Page.id)))
    if not ids:
        raise LibraryError("No pages read whole yet: read the pages first (Read all pages).")
    trained = None
    if retrain or _load(lib, book) is None:
        t = time.time()
        if progress:
            progress(0, len(ids), LineDone("training the line search reader", "OK", "", 0.0))
        trained = train_line_reader(lib, book_id, cancel=cancel)
        if progress:
            progress(0, len(ids), LineDone("line search reader", "OK",
                                           f"trained on {trained['letters']} letters", time.time() - t))
    model = _load(lib, book)
    lm = None
    if lib.book_config(book).language_model:
        from .dictionary import book_model
        lm = book_model(lib, book_id)
        lm = lm if len(lm) else None
    lines = 0
    for n, pid in enumerate(ids, 1):
        if cancel and cancel():
            raise Cancelled(f"Stopped after {n - 1} pages; those have their second opinion.")
        t = time.time()
        r = search_page(lib, pid, model, lm)
        lines += r["lines"]
        if progress:
            progress(n, len(ids), LineDone(r["page"], "OK", f"{r['lines']} lines", time.time() - t))
    return {"pages": len(ids), "lines": lines, "trained": trained, "seconds": round(time.time() - t0, 1)}


def disagreements(aksharas: Sequence[str], search_dev: str) -> List[Optional[str]]:
    """Per akshara of Tesseract's reading: None where the line search agrees, else what it read there
    ("" where it read nothing)."""
    other = [a for a in split_aksharas(search_dev.replace(" ", "")) if a.strip()]
    out: List[Optional[str]] = [None] * len(aksharas)
    sm = difflib.SequenceMatcher(None, list(aksharas), other, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        for k, i in enumerate(range(i1, i2)):
            out[i] = other[j1 + k] if op == "replace" and i2 - i1 == j2 - j1 else ""
    return out


def _chars(text: str) -> str:
    """As scored: NFC code points, spaces, the border "|" and the invisible joiners (ZWNJ, ZWJ: typed text
    may have them, no reader writes them) left out (docs/TUNING_PHASE2.md)."""
    return "".join(ch for ch in unicodedata.normalize("NFC", text)
                   if not ch.isspace() and ch not in "|\u200c\u200d")


def _distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _wrong_aksharas(aksharas: Sequence[str], truth: str) -> List[bool]:
    """Per akshara of a reading: whether it is not matched by the checked text."""
    right = [a for a in split_aksharas(_chars(truth)) if a.strip()]
    out = [True] * len(aksharas)
    for op, i1, i2, _, _ in difflib.SequenceMatcher(None, list(aksharas), right, autojunk=False).get_opcodes():
        if op == "equal":
            for i in range(i1, i2):
                out[i] = False
    return out


def _measure_file(lib: Library, book: Book) -> "Path":
    return _folder(lib, book) / "measure.json"


def last_measure(lib: Library, book_id: int) -> Optional[Dict]:
    f = _measure_file(lib, lib.get_book(book_id))
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None


def measure(lib: Library, book_id: int, folds: int = 4, progress=None, cancel: Optional[Callable[[], bool]] = None,
            settings: SearchSettings = SearchSettings()) -> Dict:
    """Score the line search on the checked lines (Line truth) of the Read Book pages, fold-fair: the pages
    with checked lines are split into `folds` folds; for each, the reader and the language model are
    rebuilt without those pages (they are also Training Data pages) and its lines are read. Beside it:
    Tesseract alone and Tesseract + language model as read whole (that language model knows every page),
    and the second opinion's marks on Tesseract + language model. Kept in line-search/measure.json."""
    from .db import LineTruth
    from .dictionary import book_model_without
    from .wholelines import trim_edges
    t0 = time.time()
    book = lib.get_book(book_id)
    use_lm = lib.book_config(book).language_model
    with lib.session() as s:
        rows = s.execute(select(Page.id, Page.file, Page.number, Page.line_spacing, Line.id, Line.number,
                                LineTruth.text_dev, WholeLine.aksharas)
                         .join(Line, Line.page_id == Page.id).join(LineTruth, LineTruth.line_id == Line.id)
                         .join(WholeLine, WholeLine.line_id == Line.id)
                         .where(Page.book_id == book_id, Page.part == "read", LineTruth.text_dev != "")
                         .order_by(Page.number, Page.id, Line.number)).all()
    if not rows:
        raise LibraryError("No checked lines yet: correct lines in Whole lines and mark them reviewed (✓), "
                           "or check lines in Line truth.")
    pages = sorted({(r[2], r[0], r[1], r[3]) for r in rows})
    n_folds = max(1, min(folds, len(pages)))
    lines = []
    for k in range(n_folds):
        if cancel and cancel():
            raise Cancelled(f"Stopped after {k} of {n_folds} folds; nothing was kept.")
        fold = pages[k::n_folds]
        files = [p[2] for p in fold]
        t = time.time()
        reader, meta = _train(lib, book_id, files, cancel=cancel, seed=k)
        lm = book_model_without(lib, book_id, files) if use_lm else None
        lm = lm if lm is not None and len(lm) else None
        for _, pid, file, spacing in fold:
            mine = [r for r in rows if r[0] == pid]
            got = _read_lines(lib, book, [r[4] for r in mine], spacing or 100.0, (reader, meta), lm, settings)
            for r in mine:
                if r[4] not in got:
                    continue
                aks = trim_edges(json.loads(r[7]))
                tess = "".join((" " if a[2] else "") + a[0] for a in aks)
                tess_lm_aks = [a[3] if len(a) > 3 and a[3] else a[0] for a in aks]
                tess_lm = "".join((" " if a[2] else "") + x for a, x in zip(aks, tess_lm_aks))
                ours = got[r[4]][0]
                wrong = _wrong_aksharas(tess_lm_aks, r[6])
                marked = [o is not None for o in disagreements(tess_lm_aks, ours)]
                truth = _chars(r[6])
                lines.append({"page": file, "line": r[5], "truth": r[6], "ours": ours, "tesseract": tess,
                              "tesseract_lm": tess_lm, "chars": len(truth),
                              "wrong": {"ours": _distance(_chars(ours), truth),
                                        "tesseract": _distance(_chars(tess), truth),
                                        "tesseract_lm": _distance(_chars(tess_lm), truth)},
                              "aksharas": len(tess_lm_aks), "marked": sum(marked), "mistakes": sum(wrong),
                              "caught": sum(m and w for m, w in zip(marked, wrong))})
        if progress:
            progress(k + 1, n_folds, LineDone(f"fold {k + 1}: {', '.join(files)}", "OK",
                                              f"trained on {meta['letters']} letters", time.time() - t))
    chars = sum(x["chars"] for x in lines) or 1
    aksharas = sum(x["aksharas"] for x in lines) or 1
    mistakes = sum(x["mistakes"] for x in lines)
    result = {
        "measured_at": now().isoformat(), "seconds": round(time.time() - t0, 1), "folds": n_folds,
        "pages": len(pages), "lines": len(lines), "chars": chars,
        "cer": {e: round(100 * sum(x["wrong"][e] for x in lines) / chars, 2)
                for e in ("ours", "tesseract", "tesseract_lm")},
        "marked": round(100 * sum(x["marked"] for x in lines) / aksharas, 1),
        "mistakes": mistakes, "caught": sum(x["caught"] for x in lines),
        "line_results": lines,
    }
    f = _measure_file(lib, book)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return {k: v for k, v in result.items() if k != "line_results"}

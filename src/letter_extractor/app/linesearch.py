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
lines (Line truth): for each fold of pages the reader and the language model are rebuilt without them and without
the pages of the book's datasets that are the same pages by content (`Library.left_out`, C24; as in stages 3 and 4).
"""
from __future__ import annotations

import difflib
import hashlib
import json
import time
import unicodedata
from collections import Counter, defaultdict
from typing import Callable, Dict, List, Optional, Sequence

import cv2
import numpy as np
from sqlalchemy import and_, or_, select

from ..ocr.aksharas import split_aksharas
from ..ocr.features import FEATURE_VERSION, features, varied
from ..ocr.reader import LetterReader
from ..ocr.segment import LinePool, SearchSettings, align, clear_borders, narrow, pool_workers, read_line
from .db import Book, LetterGroup, Line, Page, Sample, WholeLine, now
from .library import Cancelled, Library, LibraryError, NotFound
from .linestore import Entry, FeatureStore, MaskPack
from .samples import _sample_mask
from .suggest import LineDone

NOT_A_LETTER = "<not a letter>"
NEG_WEIGHT = 0.25
EPOCHS = 40                 # 15 before learning from corrections; 40 measured better (TUNING_PHASE2.md)
BASE_EPOCHS = 15            # the reader that cuts the checked lines into their aksharas (Config.line_base_epochs)
SCALE_TOLERANCE = 0.2       # a page whose line spacing is within this share of the training pages' is read as it is
MIN_ALIGN = -3.0            # a checked line whose cut scores less per akshara is not learned from


def _folder(lib: Library, book: Book):
    """Where the reader is kept: the book's reading model folder (C23; a dataset's own line-search/)."""
    return lib.model_dir(book)


def _sources(lib: Library, book: Book) -> List[int]:
    """The rows whose reviewed Training Data letters the book's reader learns: the datasets of its reading model
    (C23; the row itself for a dataset, as before)."""
    src = lib.training_sources(book)
    if not src:
        raise LibraryError(f"'{book.name}' learns from no dataset yet: our reader needs the reviewed letters of a "
                           "dataset. Choose one in Reading setup.")
    return src


def _masks(lib: Library, book: Book) -> MaskPack:
    """The reader's mask pack (in its folder); each letter's mask is read from its own row's folder."""
    return MaskPack(lib.book_dir(book), lib.folder_of, features=_folder(lib, book) / "features")


def _store(lib: Library, book: Book) -> FeatureStore:
    return FeatureStore(features=_folder(lib, book) / "features")


def _signature(s, book: Book) -> str:
    """What the reader learns from (each reviewed Training Data letter of its dataset: its label and place;
    each checked line of the book's Read Book pages and its text), as a hash."""
    from .db import LineTruth
    checked = s.execute(select(LineTruth.line_id, LineTruth.text_dev).join(Line, LineTruth.line_id == Line.id)
                        .join(Page, Line.page_id == Page.id)
                        .where(Page.book_id == book.id, Page.part == "read", LineTruth.text_dev != "", Page.excluded.is_not(True))
                        .order_by(LineTruth.line_id)).all()
    src = Library.sources_in(s, book)
    rows = [] if not src else s.execute(
        select(Sample.id, LetterGroup.label_dev, LetterGroup.status, Sample.x, Sample.w)
        .join(LetterGroup, Sample.group_id == LetterGroup.id).outerjoin(Page, Sample.page_id == Page.id)
        .where(Sample.book_id.in_(src), Sample.deleted.is_(False), LetterGroup.label_dev != "",
               LetterGroup.status != "auto", Page.excluded.is_not(True),
               or_(and_(Page.part == "training", Sample.line_id.is_not(None)),
                   and_(Sample.line_id.is_(None), Sample.mask != "")))   # also letters on no line
        .order_by(Sample.id)).all()
    return hashlib.sha1(json.dumps([[list(r) for r in rows], [list(r) for r in checked]],
                                   ensure_ascii=False).encode()).hexdigest()


def line_reader_info(lib: Library, book_id: int) -> Optional[Dict]:
    """What the book's line-search reader was trained on, or None if it has none; `changed`: the reviewed
    letters or the checked lines changed since (retrain to use them)."""
    book = lib.get_book(book_id)
    meta = _folder(lib, book) / "meta.json"
    if not meta.is_file():
        return None
    info = json.loads(meta.read_text(encoding="utf-8"))
    with lib.session() as s:
        changed = info.get("signature") != _signature(s, book)
    return {**{k: info[k] for k in ("letters", "labels", "trained_at", "seconds")}, "lines": info.get("lines", 0),
            "changed": changed}


def _paste(lib: Library, book: Book, smps: Sequence[Sample], masks: Optional[MaskPack] = None):
    """The line's ink: every sample's mask pasted at its place. (mask, left column, masks by sample id).
    `masks`: the book's mask pack (one file) instead of a PNG per letter."""
    x0 = min(m.x for m in smps)
    y0 = min(m.y for m in smps)
    x1 = max(m.x + m.w for m in smps)
    y1 = max(m.y + m.h for m in smps)
    c = np.zeros((y1 - y0, x1 - x0), bool)
    pack, masks = masks, {}
    for m in smps:
        mk = _sample_mask(lib, book, m) if pack is None else pack.get(m)
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
        signature = _signature(s, book)
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
    Read Book pages (learning from corrections), those of the pages `skip_files` left out (with the same pages of
    the datasets: Library.left_out, C24)."""
    book = lib.get_book(book_id)
    cfg, masks = lib.book_config(book), _masks(lib, book)
    data = _training_set(lib, book_id, skip_files, progress, cancel, seed, masks=masks)
    if progress:
        progress(f"training on {len(data['X'])} windows")
    base = _fit(data, cancel, epochs=cfg.line_base_epochs, batch=cfg.line_batch)
    learned = _learn_corrections(lib, book_id, data, base, skip_files, progress, cancel, masks)
    masks.save()
    if learned["lines"]:
        data = _with_corrections(data, learned)
    reader = _fit(data, cancel, batch=cfg.line_batch)
    return reader, {**data["meta"], "lines": learned["lines"]}


def _checked_lines(lib: Library, book_id: int, skip_files: Sequence = ()) -> List[tuple]:
    """(line id, page file, line spacing, checked text) of the checked lines of the Read Book pages, those of the
    pages `skip_files` (file names or a LeftOut) left out."""
    return [r[1:] for r in _checked_rows(lib, book_id, skip_files)]


def _checked_rows(lib: Library, book_id: int, skip_files: Sequence = ()) -> List[tuple]:
    """`_checked_lines` with the page id first."""
    from .db import LineTruth
    skip = lib.left_out(book_id, skip_files)
    with lib.session() as s:
        q = (select(Page.id, Line.id, Page.file, Page.line_spacing, LineTruth.text_dev)
             .join(LineTruth, LineTruth.line_id == Line.id).join(Page, Line.page_id == Page.id)
             .where(Page.book_id == book_id, Page.part == "read", LineTruth.text_dev != "", Page.excluded.is_not(True)))
        if skip:
            q = q.where(Page.id.not_in(list(skip)))
        return [tuple(r) for r in s.execute(q.order_by(Page.number, Page.id, Line.number)).all()]


def usual_spacing(lib: Library, book_id: int) -> float:
    """The training pages' usual line spacing (px), of the book's dataset: the scale the reader's widths (typical
    width, each label's width) are in; 0 when there are no Training Data pages with lines."""
    src = lib.training_sources(lib.get_book(book_id))
    if not src:
        return 0.0
    with lib.session() as s:
        sp = [v for v in s.scalars(select(Page.line_spacing).where(Page.book_id.in_(src), Page.part == "training",
                                                                    Page.excluded.is_not(True))) if v]
    return float(np.median(sp)) if sp else 0.0


def page_scale(page_spacing: Optional[float], usual: Optional[float]) -> float:
    """How much to enlarge (or shrink) a page's ink to the scale the reader was trained at: the ratio of the
    training pages' line spacing to the page's. 1 for a page near the training scale (a photo of a card, a
    book in a smaller print and a scan at another resolution differ; the windows and widths of the reader are
    in training pixels and would not fit them)."""
    if not page_spacing or not usual:
        return 1.0
    f = usual / page_spacing
    return f if abs(f - 1.0) > SCALE_TOLERANCE else 1.0


def _scaled(mask: np.ndarray, f: float) -> np.ndarray:
    """A mask enlarged (shrunk) by `f`, strokes kept smooth: resized as a picture and thresholded again."""
    if f == 1.0:
        return mask
    h, w = mask.shape
    big = cv2.resize(mask.astype(np.uint8) * 255, (max(1, int(round(w * f))), max(1, int(round(h * f)))),
                     interpolation=cv2.INTER_CUBIC)
    return big > 127


def _line_ink(lib: Library, book: Book, line_id: int, typical_width: float, scale: float = 1.0,
              masks: Optional[MaskPack] = None):
    """A line's ink (its cut letters' masks pasted together, scaled by `scale` to the reader's scale, a page
    border at its edges cleared), with its top left corner on the page (in page pixels); None for a line
    without letters."""
    with lib.session() as s:
        smps = s.scalars(select(Sample).where(Sample.line_id == line_id, Sample.deleted.is_(False))).all()
        if not smps:
            return None
        c, x0, _ = _paste(lib, book, smps, masks)
        y0 = min(m.y for m in smps)
        band = (float(np.median([m.y - y0 for m in smps])) * scale,
                float(np.median([m.y + m.h - y0 for m in smps])) * scale)
        c, _ = clear_borders(_scaled(c, scale), typical_width, float(np.median([m.h for m in smps])) * scale, band)
    return c, x0, y0


def _learn_corrections(lib: Library, book_id: int, data: Dict, base: LetterReader, skip_files: Sequence[str] = (),
                       progress=None, cancel=None, masks: Optional[MaskPack] = None) -> Dict:
    """Learning from corrections: each checked line is cut into the aksharas of its checked text
    (`segment.align`, with the reader trained on the letters), and each of its windows becomes a training
    example of its akshara, also of aksharas no group has yet."""
    return _learn_folds(lib, book_id, {0: (base, data["meta"], lib.left_out(book_id, skip_files))}, progress, cancel,
                        masks)[0]


def _learn_folds(lib: Library, book_id: int, folds: Dict[int, tuple], progress=None, cancel=None,
                 masks: Optional[MaskPack] = None) -> Dict[int, Dict]:
    """`_learn_corrections` for several folds at once ({fold: (base reader, its meta, its left-out pages: file
    names or a LeftOut)}):
    each checked line is cut into windows once, with the widest range of window widths of the folds that learn
    from it, and each fold takes its own windows from them (`segment.narrow`): the same windows and rows as one
    fold at a time (docs/SPEED_PLAN.md, S3b)."""
    book = lib.get_book(book_id)
    out = {k: {"lines": 0, "X": [], "labels": [], "widths": defaultdict(list)} for k in folds}
    skips = {k: lib.left_out(book_id, skip) for k, (_, _, skip) in folds.items()}
    rows = _checked_rows(lib, book_id)
    todo = []                                      # (line, its aksharas, the folds that learn from this ink, job)
    for n, (pid, lid, file, spacing, text) in enumerate(rows, 1):
        if cancel and cancel():
            raise Cancelled("Cancelled; the line search reader was not changed.")
        ks = [k for k in folds if pid not in skips[k]]
        if not ks:
            continue
        inks = {}                                  # the line's ink per (scale, typical width): usually all equal
        for k in ks:
            meta = folds[k][1]
            f = page_scale(spacing, meta.get("spacing"))
            ink = _line_ink(lib, book, lid, meta["typical_width"], f, masks)
            if ink is None:
                continue
            c = ink[0]
            same = (f, c.shape, hashlib.sha1(np.packbits(c).tobytes()).hexdigest())
            inks.setdefault(same, (c, f, []))[2].append(k)
        aks = [a for a in split_aksharas(_chars(text)) if a.strip() and a != "?"]
        for c, f, group in inks.values():
            Ts = [folds[k][1]["typical_width"] for k in group]
            todo.append((n, aks, group, (c, (spacing or 100.0) * f, min(Ts), max(Ts), SearchSettings())))
    with LinePool(pool_workers(lib.book_config(book).line_workers)) as pool:      # S4b: cut in parallel, in order
        for (n, aks, group, _), every in zip(todo, pool.windows([t[3] for t in todo])):
            if cancel and cancel():
                raise Cancelled("Cancelled; the line search reader was not changed.")
            if progress and n % 10 == 1:
                progress(f"learning from the checked lines: {n} of {len(rows)}")
            for k in group:
                base, meta, _ = folds[k]
                T = meta["typical_width"]
                win = narrow(every, T)
                if win is None or not len(win.X):
                    continue
                path, score = align(win, base.probabilities(win.X), base.classes, T, aks)
                if path is None or score < MIN_ALIGN:
                    continue
                got = out[k]
                got["lines"] += 1
                for q, a in path:
                    got["X"].append(win.X[q].copy())     # not a view: it would keep the line's windows in memory
                    got["labels"].append(a)
                    got["widths"][a].append(win.meta[q][2])
            del every
    return out


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


def _fit(data: Dict, cancel=None, hidden: int = 0, epochs: int = EPOCHS, batch: int = 128) -> LetterReader:
    reader = LetterReader(data["classes"], data["X"].shape[1], hidden=hidden)
    reader.train(data["X"], data["y"], weights=data["weights"], epochs=epochs, batch=batch, cancel=cancel)
    if cancel and cancel():
        raise Cancelled("Cancelled; the line search reader was not changed.")
    return reader


def _vary_count(n: int) -> int:
    """Varied copies of each letter of a label with `n` letters (fairness rule: small labels topped up)."""
    return max(3, min(30, -(-20 // n)))


def _letter_key(seed: int, sp: float, line_sig: str, smp) -> str:
    """What a letter's rows are computed from: the feature version, the seed, its line spacing, its box and the
    letters of its line (their boxes and mask contents: their ink is in its windows)."""
    return hashlib.sha1(json.dumps([FEATURE_VERSION, seed, round(float(sp), 6), line_sig, smp.id, smp.x, smp.w],
                                   ensure_ascii=False).encode()).hexdigest()


def _line_signature(smps, masks: MaskPack) -> str:
    return hashlib.sha1(json.dumps(sorted([m.id, m.x, m.y, m.w, m.h, masks.digest(m.id)] for m in smps))
                        .encode()).hexdigest()


def _letter_rows(L: Dict, seed: int) -> Entry:
    """A letter's rows, from its own random numbers (seed, sample id, which copy): the same in every fold and
    every run (docs/SPEED_PLAN.md, S3a). Varied copies are added by `_varied_rows`."""
    sp, mask = L["sp"], L["mask"]
    if L["c"] is None:                                      # on no line: its picture (and varied copies)
        return Entry(L["key"], [features(mask, sp)], [], [])
    x, w, c, x0 = L["x"], L["w"], L["c"], L["x0"]
    rng = np.random.default_rng([seed, L["sid"], 0])

    def win(a, b):
        m = _crop(c, a - x0, b - x0)
        return features(m, sp) if m is not None else None
    pos = [features(mask, sp), win(x, x + w)]
    for sign in (-1, 1):
        shift = sign * max(1, int(round(rng.uniform(0.03, 0.10) * w)))
        pos.append(win(x + shift, x + w + shift))
    negs = [win(x, x + w // 2), win(x + w // 2, x + w)]
    if L["nxt"] is not None and L["nxt"][0] - (x + w) < 0.5 * w:
        negs.append(win(x, L["nxt"][0] + L["nxt"][1]))
    for sign in (-1, 1):
        shift = sign * int(round(rng.uniform(0.25, 0.45) * w))
        negs.append(win(x + shift, x + w + shift))
    return Entry(L["key"], [f for f in pos if f is not None], [f for f in negs if f is not None], [])


def _varied_rows(e: Entry, mask: np.ndarray, sp: float, sid: int, seed: int, n: int) -> int:
    """Make the letter's varied copies up to `n` (copy k always from the same seed); how many were made."""
    made = 0
    for k in range(len(e.varied), n):
        e.varied.append(features(varied(mask, np.random.default_rng([seed, sid, 1 + k])), sp))
        made += 1
    return made


def _training_set(lib: Library, book_id: int, skip_files: Sequence[str] = (), progress=None, cancel=None,
                  seed: int = 0, unlined: bool = True, store: Optional[FeatureStore] = None,
                  masks: Optional[MaskPack] = None) -> Dict:
    """The training windows (X, y, weights), the classes and the meta, before fitting. With `unlined`, the
    reviewed letters that are on no line (System generated, uploaded) are learned from their picture alone
    (and its varied copies): there is no line to cut windows or "not a letter" pieces from.

    The rows come from the feature store (kept in the book folder, made only for the letters that changed;
    pass `store` and `masks` to share them between the folds of a Measure); the labels and the review status
    always come from the database."""
    book = lib.get_book(book_id)
    src = _sources(lib, book)                         # the letters: of the book's datasets (C23)
    own_store, own_masks = store is None, masks is None
    store = _store(lib, book) if store is None else store
    masks = _masks(lib, book) if masks is None else masks
    skip = lib.left_out(book_id, skip_files)          # page ids (C24: the same pages by content)
    letters, every = [], []
    with lib.session() as s:
        q = (select(Sample, LetterGroup.label_dev, Page.line_spacing, Page.id)
             .join(LetterGroup, Sample.group_id == LetterGroup.id).join(Page, Sample.page_id == Page.id)
             .where(Sample.book_id.in_(src), Sample.deleted.is_(False), Page.part == "training", Page.excluded.is_not(True),
                    Sample.line_id.is_not(None), LetterGroup.label_dev != ""))
        rows = s.execute(q).all()
        status = dict(s.execute(select(LetterGroup.id, LetterGroup.status)
                                .where(LetterGroup.book_id.in_(src))).all())
        by_line = defaultdict(list)
        for smp, lab, spacing, pid in rows:
            if status.get(smp.group_id) == "auto" or len(split_aksharas(lab)) != 1:
                continue
            every.append(smp.id)
            if pid not in skip:
                by_line[smp.line_id].append((smp, lab, spacing))
        for items in by_line.values():
            if cancel and cancel():
                raise Cancelled("Cancelled; the line search reader was not changed.")
            # the line's letters, labelled or not: their ink is in the windows
            line_smps = s.scalars(select(Sample).where(Sample.line_id == items[0][0].line_id,
                                                       Sample.deleted.is_(False))).all()
            for m in line_smps:
                masks.get(m)
            line_sig = _line_signature(line_smps, masks)
            order = sorted(line_smps, key=lambda m: m.x)
            nxt_of = {a.id: b for a, b in zip(order, order[1:])}
            pasted = None
            for smp, lab, spacing in items:
                sp = spacing or 1.6 * smp.h
                L = dict(sid=smp.id, label=lab, x=smp.x, w=smp.w, sp=sp, key=_letter_key(seed, sp, line_sig, smp))
                if store.get(smp.id, L["key"]) is None:          # its rows are computed below, from its line
                    if pasted is None:
                        pasted = _paste(lib, book, line_smps, masks)
                    nxt = nxt_of.get(smp.id)
                    L.update(mask=pasted[2][smp.id], c=pasted[0], x0=pasted[1],
                             nxt=(nxt.x, nxt.w) if nxt is not None else None)
                letters.append(L)
        if unlined:
            spacings = [v for v in s.scalars(select(Page.line_spacing).where(Page.book_id.in_(src),
                                                                             Page.part == "training",
                                                                             Page.excluded.is_not(True))) if v]
            usual = float(np.median(spacings)) if spacings else 0.0
            alone = s.execute(select(Sample, LetterGroup.label_dev)
                              .join(LetterGroup, Sample.group_id == LetterGroup.id)
                              .where(Sample.book_id.in_(src), Sample.deleted.is_(False), Sample.line_id.is_(None),
                                     Sample.mask != "", LetterGroup.label_dev != "",
                                     LetterGroup.status != "auto")).all()
            for smp, lab in alone:
                if len(split_aksharas(lab)) != 1:
                    continue
                every.append(smp.id)
                sp = usual or 1.6 * smp.h
                masks.get(smp)
                letters.append(dict(sid=smp.id, label=lab, x=smp.x, w=smp.w, sp=sp, c=None, nxt=None,
                                    key=_letter_key(seed, sp, masks.digest(smp.id), smp)))
    if len(letters) < 20 or len({L["label"] for L in letters}) < 2:
        raise LibraryError("The line search learns the letters from the reviewed Training Data of the book's "
                           "datasets: review and label more groups there first (at least 20 letters).")
    if progress:
        progress(f"{len(letters)} reviewed letters; their windows")
    freq = Counter(L["label"] for L in letters)
    entries = []
    with lib.session() as s:
        for n, L in enumerate(letters):
            if cancel and n % 500 == 0 and cancel():
                raise Cancelled("Cancelled; the line search reader was not changed.")
            e = store.get(L["sid"], L["key"])
            if e is None:
                if "mask" not in L:                                 # on no line
                    L["mask"] = masks.get(s.get(Sample, L["sid"]))
                e = _letter_rows(L, seed)
                store.put(L["sid"], e)
                store.computed += 1
            need = _vary_count(freq[L["label"]])
            if len(e.varied) < need:
                mask = L.get("mask")
                if mask is None:
                    mask = masks.get(s.get(Sample, L["sid"]))
                store.copies += _varied_rows(e, mask, L["sp"], L["sid"], seed, need)
                store.dirty = True
            entries.append((L, e, need))
    classes = sorted(freq) + [NOT_A_LETTER]
    ci = {c_: i for i, c_ in enumerate(classes)}
    X, y = [], []
    for L, e, need in entries:
        for f in e.base + e.varied[:need]:
            X.append(f)
            y.append(ci[L["label"]])
        for f in e.negs:
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
    if own_store:
        if unlined:
            store.keep_only(every)
        store.save()
    if own_masks:
        masks.save()
    return {"X": X, "y": y, "weights": weights, "classes": classes,
            "meta": {"letters": len(letters), "labels": len(freq),
                     "typical_width": float(np.median([L["w"] for L in letters])),
                     "spacing": usual_spacing(lib, book_id),
                     "widths": {k: float(np.median(v)) for k, v in widths.items()}}}


def _load(lib: Library, book: Book):
    folder = _folder(lib, book)
    if not (folder / "meta.json").is_file():
        return None
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    meta.setdefault("spacing", usual_spacing(lib, book.id))      # readers trained before the page scale existed
    return LetterReader.load(folder / "reader.npz"), meta


def _read_lines(lib: Library, book: Book, line_ids: Sequence[int], spacing: float, model, lm,
                settings: SearchSettings = SearchSettings(), masks: Optional[MaskPack] = None,
                pool: Optional[LinePool] = None) -> Dict[int, tuple]:
    """{line id: (text, aksharas)} for the lines with cut letters (their ink); aksharas as `search_aksharas`.
    `pool`: read the lines in its worker processes (it holds this reader and language model)."""
    return _read_many(lib, book, [(lid, spacing) for lid in line_ids], model, lm, settings, masks, pool)


def _read_many(lib: Library, book: Book, lines: Sequence[tuple], model, lm,
               settings: SearchSettings = SearchSettings(), masks: Optional[MaskPack] = None,
               pool: Optional[LinePool] = None) -> Dict[int, tuple]:
    """`_read_lines` of (line id, its page's line spacing) of several pages at once: Measure gives a fold's checked
    lines together, so that the workers get enough lines (most pages have fewer than 8 checked lines)."""
    reader, meta = model
    found = {}
    inks = []
    for lid, spacing in lines:
        f = page_scale(spacing, meta.get("spacing"))
        ink = _line_ink(lib, book, lid, meta["typical_width"], f, masks=masks)
        if ink is not None:
            inks.append((lid, f, spacing, ink))
    jobs = [(ink[0], spacing * f, meta["typical_width"], meta["widths"], settings) for _, f, spacing, ink in inks]
    if pool is not None and pool.parallel(len(jobs)):
        readings = pool.read(jobs)
    else:
        readings = (read_line(c, sp, reader, T, w, lm, s) for c, sp, T, w, s in jobs)
    for (lid, f, _, (c, x0, y0)), (text, steps, _) in zip(inks, readings):
        aks = []
        for st in steps:
            rows = np.flatnonzero(c[:, st.x0:st.x1].any(axis=1))
            box = [int(x0 + st.x0 / f), int(y0 + rows.min() / f), int(round((st.x1 - st.x0) / f)),
                   int(round((rows.max() - rows.min() + 1) / f))] if rows.size else None
            aks.append([unicodedata.normalize("NFC", st.label), bool(st.space), box])
        found[lid] = (unicodedata.normalize("NFC", text), aks)
    return found


def search_page(lib: Library, page_id: int, model, lm, settings: SearchSettings = SearchSettings(),
                pool: Optional[LinePool] = None) -> Dict:
    """Read every line of a page with the line search, and keep its reading. Tesseract need not have read
    the page: a line without a whole-line row gets one of engine "search" (no Tesseract text, so the Tesseract
    views leave it out)."""
    with lib.session() as s:
        page = s.get(Page, page_id)
        if page is None:
            raise NotFound(f"No page with id {page_id}.")
        book = s.get(Book, page.book_id)
        spacing = page.line_spacing or 100.0
        line_ids = list(s.scalars(select(Line.id).where(Line.page_id == page_id).order_by(Line.number)))
        file = page.file
    found = _read_lines(lib, book, line_ids, spacing, model, lm, settings, pool=pool)
    with lib.session() as s:
        for lid, (text, aks) in found.items():
            row = s.scalar(select(WholeLine).where(WholeLine.line_id == lid))
            if row is None:
                row = WholeLine(line_id=lid, engine="search", aksharas="[]")
                s.add(row)
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
        q = (select(Page.id).join(Line, Line.page_id == Page.id).join(Sample, Sample.line_id == Line.id)
             .where(Page.book_id == book_id, Sample.deleted.is_(False), Page.excluded.is_not(True)).distinct())
        q = q.where(Page.id.in_(list(page_ids))) if page_ids else q.where(Page.part == part)
        ids = list(s.scalars(q.order_by(Page.number, Page.id)))
    if not ids:
        raise LibraryError("No pages with cut letters on their lines yet: cut the Read Book pages first.")
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
    with LinePool(pool_workers(lib.book_config(book).line_workers), model[0], lm) as pool:   # S4b
        for n, pid in enumerate(ids, 1):
            if cancel and cancel():
                raise Cancelled(f"Stopped after {n - 1} pages; those have their second opinion.")
            t = time.time()
            r = search_page(lib, pid, model, lm, pool=pool)
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


def _measure_file(lib: Library, book: Book, quick: bool = False) -> "Path":
    return _folder(lib, book) / ("measure-quick.json" if quick else "measure.json")


def last_measure(lib: Library, book_id: int, quick: bool = False) -> Optional[Dict]:
    f = _measure_file(lib, lib.get_book(book_id), quick)
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None


def measure(lib: Library, book_id: int, folds: int = 4, progress=None, cancel: Optional[Callable[[], bool]] = None,
            settings: SearchSettings = SearchSettings(), quick: bool = False) -> Dict:
    """Score the line search on the checked lines (Line truth) of the Read Book pages, fold-fair: the pages
    with checked lines are split into `folds` folds; for each, the reader and the language model are
    rebuilt without those pages and without the same pages of the book's datasets (by `sha256`, C24) and its
    lines are read. Beside it:
    Tesseract alone and Tesseract + language model as read whole (that language model knows every page),
    and the second opinion's marks on Tesseract + language model. Kept in the reader's folder (measure.json).

    The letters' rows come from the feature store (each computed once, kept); the base readers of all folds
    are trained first, so that each checked line is cut into windows once for learning from corrections and
    once to be read (docs/SPEED_PLAN.md, S3). `quick`: only the first half of the folds (2 of 4) are read (about
    half the time):
    for screening ideas only, never a result to quote."""
    from .db import LineTruth
    from .dictionary import book_model_without
    from .wholelines import trim_edges
    t0 = time.time()
    book = lib.get_book(book_id)
    cfg = lib.book_config(book)
    use_lm = cfg.language_model
    with lib.session() as s:
        rows = s.execute(select(Page.id, Page.file, Page.number, Page.line_spacing, Line.id, Line.number,
                                LineTruth.text_dev, WholeLine.aksharas)
                         .join(Line, Line.page_id == Page.id).join(LineTruth, LineTruth.line_id == Line.id)
                         .join(WholeLine, WholeLine.line_id == Line.id)
                         .where(Page.book_id == book_id, Page.part == "read", LineTruth.text_dev != "",
                                WholeLine.engine != "search", Page.excluded.is_not(True))
                         .order_by(Page.number, Page.id, Line.number)).all()
    if not rows:
        raise LibraryError("No checked lines yet: correct lines in Whole lines and mark them reviewed (✓), "
                           "or check lines in Line truth.")
    pages = sorted({(r[2], r[0], r[1], r[3]) for r in rows})
    n_folds = max(1, min(folds, len(pages)))
    tested = list(range(max(1, n_folds // 2) if quick else n_folds))
    files = {k: [p[2] for p in pages[k::n_folds]] for k in tested}
    # C24: a fold leaves out its pages and the datasets' pages with the same content (sha256), not the same name
    skips = {k: lib.left_out(book_id, [p[1] for p in pages[k::n_folds]]) for k in tested}
    store, masks = _store(lib, book), _masks(lib, book)

    def stop(k):
        if cancel and cancel():
            raise Cancelled(f"Stopped after {k} of {len(tested)} folds; nothing was kept.")

    def say(msg):
        if progress:
            progress(0, len(tested), LineDone(msg, "OK", "", time.time() - t0))
    # 1. each fold's base reader, from the letters of the other pages (their rows from the store)
    bases = {}
    for k in tested:
        stop(0)
        say(f"fold {k + 1}: the reader that cuts the checked lines")
        data = _training_set(lib, book_id, skips[k], cancel=cancel, store=store, masks=masks)
        bases[k] = (_fit(data, cancel, epochs=cfg.line_base_epochs, batch=cfg.line_batch), data["meta"], skips[k])
        del data
    store.save()
    masks.save()
    # 2. learning from corrections: every checked line cut into windows once, for all the folds that learn from it
    say("learning from the checked lines")
    learned = _learn_folds(lib, book_id, bases, cancel=cancel, masks=masks)
    masks.save()
    lines = []
    # 3. each fold's reader reads its pages
    for k in tested:
        stop(k)
        t = time.time()
        data = _training_set(lib, book_id, skips[k], cancel=cancel, store=store, masks=masks)
        if learned[k]["lines"]:
            data = _with_corrections(data, learned[k])
        reader, meta = _fit(data, cancel, batch=cfg.line_batch), {**data["meta"], "lines": learned[k]["lines"]}
        del data
        lm = book_model_without(lib, book_id, skips[k]) if use_lm else None
        lm = lm if lm is not None and len(lm) else None
        pool = LinePool(pool_workers(cfg.line_workers), reader, lm)              # S4b: this fold's reader
        try:                                                             # the fold's lines in one batch
            read = _read_many(lib, book, [(r[4], spacing or 100.0) for _, pid, _, spacing in pages[k::n_folds]
                                          for r in rows if r[0] == pid], (reader, meta), lm, settings, masks, pool)
        finally:
            pool.close()
        got = {pid: {r[4]: read[r[4]] for r in rows if r[0] == pid and r[4] in read}
               for _, pid, _, _ in pages[k::n_folds]}
        for _, pid, file, spacing in pages[k::n_folds]:
            mine = [r for r in rows if r[0] == pid]
            for r in mine:
                if r[4] not in got[pid]:
                    continue
                aks = trim_edges(json.loads(r[7]))
                tess = "".join((" " if a[2] else "") + a[0] for a in aks)
                tess_lm_aks = [a[3] if len(a) > 3 and a[3] else a[0] for a in aks]
                tess_lm = "".join((" " if a[2] else "") + x for a, x in zip(aks, tess_lm_aks))
                ours = got[pid][r[4]][0]
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
            progress(k + 1, len(tested), LineDone(f"fold {k + 1}: {', '.join(files[k])}", "OK",
                                                  f"trained on {meta['letters']} letters", time.time() - t))
    masks.save()
    chars = sum(x["chars"] for x in lines) or 1
    aksharas = sum(x["aksharas"] for x in lines) or 1
    mistakes = sum(x["mistakes"] for x in lines)
    result = {
        "measured_at": now().isoformat(), "seconds": round(time.time() - t0, 1), "folds": n_folds,
        "quick": quick, "tested_folds": len(tested),
        "pages": len(pages), "lines": len(lines), "chars": chars,
        "cer": {e: round(100 * sum(x["wrong"][e] for x in lines) / chars, 2)
                for e in ("ours", "tesseract", "tesseract_lm")},
        "marked": round(100 * sum(x["marked"] for x in lines) / aksharas, 1),
        "mistakes": mistakes, "caught": sum(x["caught"] for x in lines),
        "line_results": lines,
    }
    f = _measure_file(lib, book, quick)                     # a quick one never replaces the last full measure
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return {k: v for k, v in result.items() if k != "line_results"}

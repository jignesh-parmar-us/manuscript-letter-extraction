"""Converting pages into text (C16b), and the texts' downloads.

For each page (Read Book pages, or training pages to measure against their labels):
1. its letters, line by line in reading order;
2. **printed books:** Tesseract reads each line image (several lines at once); its aksharas are put on
   the cut letters with C11's alignment, and a letter the alignment could not place takes the characters
   Tesseract read over it (measured: 13.1% -> 10.8% CER, TUNING_PHASE2.md);
3. every letter is compared with the book's **labelled groups** (nearest centre, C13's method), and read
   by the book's active **letter reader** (C14) if it has one;
4. `ocr.convert.choose` (or `vote`, with a letter reader) decides each letter's text, confidence and
   whether it is uncertain; then the book's **language model** (C15, `dictionary.book_model`) may change
   uncertain letters of each line to readings that make more likely text (`ocr.language.correct_line`);
   a changed letter stays uncertain and keeps what it was in `lm_from`;
5. the page's text is joined line by line (spaces at word gaps on printed books), mapped to Gujarati,
   stored as a `PageText` row and written to `text/<part>/<page>.txt` (with the uncertain-letter
   marker) and `.json` (every letter with its sample and box: traceable to the page).
A conversion job stores each page when it is done, so a cancel keeps the pages already converted.

**Proofreading (C17).** The stored letters are the conversion's reading; what the Text view and the
downloads show is that reading brought up to date with the page's samples (`live_lines`):
- a letter whose sample is in a labelled group shows the label: correcting a letter labels its sample
  (an undoable action), so undo, Review and the next training of the reader all see the correction;
- letters whose sample was split, joined or deleted give way to the samples made since.
A line can be marked proofread: its text at that moment is kept, its letters count as sure, and
converting again keeps the line's letters as they were. Proofread lines are the ground truth for
measuring the conversion (`proofread_stats`).
"""
from __future__ import annotations

import json
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
from sqlalchemy import select

from .. import io_utils
from ..mapping import mapping_for
from ..ocr.align import align_line
from ..ocr.aksharas import line_aksharas
from ..ocr.convert import LetterText, choose, line_text, mark_spaces, taught, vote
from ..ocr.language import candidates, correct_line
from .centres import centres
from .db import Book, LetterGroup, Line, Page, PageText, Sample, now
from .library import Cancelled, Library, LibraryError
from .suggest import LineDone, book_tesseract_reader, _workers

LineReader = Callable[[np.ndarray], object]


def _nearest(fp: Optional[bytes], groups, C: np.ndarray, k: int = 1) -> List[Tuple[str, float]]:
    """The `k` nearest labelled groups (label, distance), nearest first."""
    if fp is None or C.size == 0:
        return []
    d = np.linalg.norm(C - np.frombuffer(fp, np.float32), axis=1)
    return [(groups[i].label_dev, float(d[i])) for i in np.argsort(d)[:k]]


def _read_lines(lib: Library, book: Book, cfg, lines: Sequence[Line], letters: Dict[int, List[Sample]],
                reader: LineReader) -> Dict[int, Tuple[str, float]]:
    """Tesseract's reading of each letter of these lines: sample id -> (text, confidence 0 to 100). A letter
    the alignment did not place (or a line it refused) gets the characters Tesseract read over the
    letter (their box centres inside its x span), with the lowest of their confidences."""
    book_dir = lib.book_dir(book)

    def read(line: Line):
        smps = letters.get(line.id, [])
        if not smps:
            return {}
        rgb, _ = io_utils.load_image(book_dir / line.image)
        reading = reader(rgb)
        dx = max(0, line.x - cfg.line_margin_px)
        al = align_line(line_aksharas(reading.words), [(x.x, x.x + x.w) for x in smps],
                        dx=dx, min_overlap=cfg.align_min_overlap,
                        sure_overlap=cfg.align_sure_overlap, min_matched=cfg.align_min_matched)
        got = {} if al.refused else {smps[m.sample].id: (m.text, m.conf) for m in al.matches}
        chars = [c for w in reading.words for c in w.chars if c.box[2] > 0]
        for x in smps:
            if x.id in got:
                continue
            over = [c for c in chars if x.x <= c.box[0] + c.box[2] / 2 + dx < x.x + x.w]
            text = unicodedata.normalize("NFC", "".join(c.text for c in over))
            if text.strip():
                got[x.id] = (text.strip(), min(c.conf for c in over))
        return got

    out: Dict[int, Tuple[str, float]] = {}
    with ThreadPoolExecutor(max_workers=_workers()) as pool:
        for got in pool.map(read, lines):
            out.update(got)
    return out


T_FIELDS = ("t_text_dev", "t_text_guj", "t_conf", "t_uncertain")


def _letters(dicts: Sequence[Dict], readers: str = "both") -> List[LetterText]:
    """Stored (or live) letter dicts as LetterText, as one set of readers sees them."""
    t = readers == "tesseract"
    return [LetterText(x["sample_id"], 0, tuple(x["box"]),
                       x["t_text_dev"] if t and "t_text_dev" in x else x["text_dev"], x["conf"], x["source"],
                       x["t_uncertain"] if t and "t_uncertain" in x else x["uncertain"], x["space"])
            for x in dicts]


def _line_numbers(s, page_id: int) -> List[int]:
    return list(s.scalars(select(Line.number).where(Line.page_id == page_id).order_by(Line.number)))


def live_lines(s, page_id: int, stored: List[List[Dict]], mapping, proofread: Optional[Dict] = None) -> List[List[Dict]]:
    """The stored letters of a page brought up to date with its samples: a Read Book sample in a labelled
    group shows its label (source "label", sure; the reading it replaced stays in `read_dev`), letters of
    samples that are gone (split, joined, deleted) give way to the samples made since, and the letters
    of proofread lines are sure."""
    # only the columns needed (not the fingerprints): a whole book's pages are listed this way
    rows = s.execute(select(Sample.id, Sample.x, Sample.y, Sample.w, Sample.h, Sample.line_number, Sample.image,
                            Sample.part, LetterGroup.label_dev)
                     .outerjoin(LetterGroup, Sample.group_id == LetterGroup.id)
                     .where(Sample.page_id == page_id, Sample.deleted.is_(False))).all()
    live = {x.id: (x, x.label_dev or "") for x in rows}
    numbers = _line_numbers(s, page_id)
    index = {n: i for i, n in enumerate(numbers)} if len(numbers) == len(stored) else {}
    known = {x["sample_id"] for line in stored for x in line}
    new: Dict[int, List] = {}
    for x, _ in live.values():
        if x.id not in known and x.line_number in index:
            new.setdefault(index[x.line_number], []).append(x)
    with_t = any("t_text_dev" in x for line in stored for x in line)
    out = []
    for i, line in enumerate(stored):
        kept = [dict(x) for x in line if x["sample_id"] in live]
        added = []
        for smp in sorted(new.get(i, []), key=lambda m: m.x):
            # a piece of a split letter (or a joined letter) keeps the word gap before the letter it replaced
            gone = [x for x in line if x["sample_id"] not in live and x["space"]
                    and x["box"][0] < smp.x + smp.w and smp.x < x["box"][0] + x["box"][2]]
            added.append({"sample_id": smp.id, "box": [smp.x, smp.y, smp.w, smp.h], "text_dev": "", "text_guj": "",
                          "conf": 0.0, "source": "none", "uncertain": True,
                          "space": bool(gone) and not any(a["space"] for a in added), "readings": [],
                          **({"t_text_dev": "", "t_text_guj": "", "t_conf": 0.0, "t_uncertain": True} if with_t else {})})
        row = sorted(kept + added, key=lambda x: x["box"][0])
        sure = proofread is not None and i < len(numbers) and str(numbers[i]) in proofread
        for x in row:
            smp, label = live[x["sample_id"]]
            x["image"] = smp.image
            if label and smp.part == "read":         # training pages keep the reading: it is measured against the labels
                if x["text_dev"] != label:
                    x["read_dev"] = x["text_dev"]
                x.update(text_dev=label, text_guj=mapping.gujarati(label), conf=1.0, source="label", uncertain=False)
                if with_t:
                    x.update(t_text_dev=label, t_text_guj=x["text_guj"], t_conf=1.0, t_uncertain=False)
            if sure and x["text_dev"]:
                x["uncertain"] = False
                if with_t and x.get("t_text_dev"):
                    x["t_uncertain"] = False
        out.append(row)
    return out


def _write_files(lib: Library, book: Book, page: Page, lines: List[List[Dict]], marker: str, mapping) -> None:
    folder = lib.book_dir(book) / "text" / page.part
    folder.mkdir(parents=True, exist_ok=True)
    marked = "\n".join(line_text(_letters(r), marker) for r in lines)
    (folder / f"{Path(page.file).stem}.txt").write_text(mapping.gujarati(marked) + "\n", encoding="utf-8")
    (folder / f"{Path(page.file).stem}.json").write_text(json.dumps({"page": page.file, "part": page.part, "lines": lines},
                                                                  ensure_ascii=False, indent=1), encoding="utf-8")


def _letter_reader(lib: Library, book: Book):
    """The book's active letter reader (C14), or None."""
    if not book.reader_id:
        return None
    from .readers import load_reader
    try:
        return load_reader(lib, book.reader_id)[1]
    except (LibraryError, OSError):
        return None                                  # its files are gone: convert without it


def _reader_readings(lib: Library, book: Book, smps: Sequence[Sample], spacing: float,
                     letter_reader) -> Dict[int, List[Tuple[str, float]]]:
    """The letter reader's three best readings of each letter: sample id -> [(label, probability)]."""
    from ..ocr.features import features
    from .samples import _sample_mask
    have = [x for x in smps if x.mask]
    if letter_reader is None or not have:
        return {}
    X = np.stack([features(_sample_mask(lib, book, x), float(spacing or 1.6 * x.h)) for x in have])
    P = letter_reader.probabilities(X)
    return {x.id: [(letter_reader.classes[int(k)], float(p[k])) for k in np.argsort(-p)[:3]] for x, p in zip(have, P)}


def _language_model(lib: Library, book: Book, cfg):
    """The book's language model (C15), or None when it is off or has learned nothing."""
    if not cfg.language_model:
        return None
    from .dictionary import book_model
    lm = book_model(lib, book.id)
    return lm if len(lm) else None


def _groups_for(s, book: Book):
    """The labelled groups (and centres) that check a book's letters: its datasets' (C23; the book's own when it
    has none; a dataset's own)."""
    srcs = Library.sources_in(s, book) or [book.id]
    if len(srcs) == 1:
        return centres(s, srcs[0], labelled_only=True)
    groups, rows = [], []
    for src in srcs:
        g, r = centres(s, src, labelled_only=True)
        if g:
            groups += g
            rows.append(r)
    return groups, (np.concatenate(rows) if rows else np.zeros((0, 0), np.float32))


def convert_page(lib: Library, page_id: int, reader: Optional[LineReader] = None,
                 targets=None, letter_reader="book", lm="book") -> Dict:
    """Convert one page and store its text. `reader` reads a line image (Tesseract by default on printed
    books; tests pass their own); `targets` are the book's labelled groups and centres, if already known;
    `letter_reader` the book's letter reader if already loaded ("book": load it here; None: none); `lm`
    the same for the language model."""
    with lib.session() as s:
        page = s.get(Page, page_id)
        if page is None:
            raise LibraryError(f"No page with id {page_id}.")
        book = s.get(Book, page.book_id)
        cfg = lib.book_config(book)
        printed = book.writing == "printed"
        lines = s.scalars(select(Line).where(Line.page_id == page_id).order_by(Line.number)).all()
        smps = s.scalars(select(Sample).where(Sample.page_id == page_id, Sample.deleted.is_(False))
                         .order_by(Sample.line_number, Sample.x, Sample.pos)).all()
        by_line: Dict[int, List[Sample]] = {}
        for x in smps:
            by_line.setdefault(x.line_id, []).append(x)
        groups, C = targets if targets is not None else _groups_for(s, book)
        tess: Dict[int, Tuple[str, float]] = {}
        readers = []
        if printed and reader is not None:
            tess = _read_lines(lib, book, cfg, lines, by_line, reader)
            readers.append("tesseract")
        if letter_reader == "book":
            letter_reader = _letter_reader(lib, book)
        mine = _reader_readings(lib, book, smps, page.line_spacing, letter_reader)
        known = set(letter_reader.classes) if mine else set()
        if mine:
            readers.append("reader")
        if len(C):
            readers.append("groups")
        if lm == "book":
            lm = _language_model(lib, book, cfg)
        if lm is not None:
            readers.append("language")
        mapping = mapping_for(cfg)
        lm_from: Dict[int, str] = {}
        out_lines: List[List[LetterText]] = []
        for line in lines:
            row: List[LetterText] = []
            seen_by: List[Tuple] = []
            for x in by_line.get(line.id, []):
                t = tess.get(x.id)
                near = _nearest(x.fingerprint, groups, C, 2)
                g = near[0] if near else None
                top = mine.get(x.id, [])
                r = top[0] if top else None
                seen_by.append((t, top, near))
                if r is not None and taught(t, g, known, cfg):
                    text, conf, source, uncertain = vote(t, r, g, cfg)
                else:
                    text, conf, source, uncertain = choose(t, g, cfg, x.kind)
                seen = ([("tesseract", t[0], round(t[1], 1))] if t else []) + \
                       ([("reader", r[0], round(r[1], 3))] if r else []) + \
                       ([("groups", g[0], round(g[1], 3))] if g else [])
                row.append(LetterText(x.id, line.number, (x.x, x.y, x.w, x.h), text, conf, source, uncertain,
                                      readings=seen))
            if lm is not None and row:                # the language model may change uncertain letters
                opts = [candidates(x.text, x.uncertain, t, top, near, cfg.group_distance)
                        for x, (t, top, near) in zip(row, seen_by)]
                _, changes = correct_line(lm, opts, cfg.lm_weight, cfg.lm_min_gain)
                for c in changes:
                    x = row[c.index]
                    lm_from[x.sample_id] = x.text
                    x.text, x.source = c.new, f"{x.source}+language"
            mark_spaces(row, cfg, printed)
            out_lines.append(row)
        text_dev = "\n".join(line_text(r) for r in out_lines)
        marked = "\n".join(line_text(r, cfg.uncertain_marker) for r in out_lines)
        uncertain = sum(x.uncertain for r in out_lines for x in r)
        def alone(x: LetterText) -> Dict:
            """Tesseract's reading alone (the Text view's "Tesseract only"), without the groups' opinion."""
            r = next(((t, v) for k, t, v in x.readings if k == "tesseract"), None)
            text, conf, _, uncertain = choose(r, None, cfg, "danda" if x.text == "।" and not r else "letter")
            return {"t_text_dev": text, "t_text_guj": mapping.gujarati(text) if text else "", "t_conf": conf,
                    "t_uncertain": uncertain}
        letters = [[{"sample_id": x.sample_id, "box": list(x.box), "text_dev": x.text,
                     "text_guj": mapping.gujarati(x.text) if x.text else "", "conf": x.conf, "source": x.source,
                     "uncertain": x.uncertain, "space": x.space_before, "readings": x.readings,
                     **({"lm_from": lm_from[x.sample_id]} if x.sample_id in lm_from else {}),
                     **(alone(x) if tess else {})} for x in r]
                   for r in out_lines]
        row = s.scalar(select(PageText).where(PageText.page_id == page_id))
        if row is None:
            row = PageText(page_id=page_id, proofread="{}")
            s.add(row)
        else:                                        # proofread lines (C17) keep their letters
            proofread = json.loads(row.proofread or "{}")
            old = json.loads(row.letters)
            numbers = [ln.number for ln in lines]
            if proofread and len(old) == len(letters) == len(numbers):
                for i, n in enumerate(numbers):
                    if str(n) in proofread:
                        letters[i] = old[i]
                text_dev = "\n".join(line_text(_letters(r)) for r in letters)
                marked = "\n".join(line_text(_letters(r), cfg.uncertain_marker) for r in letters)
                uncertain = sum(x["uncertain"] for r in letters for x in r)
        row.text_dev, row.text_guj = text_dev, mapping.gujarati(text_dev)
        row.letters, row.uncertain, row.readers = json.dumps(letters, ensure_ascii=False), uncertain, "+".join(readers)
        row.converted_at = now()
        folder = lib.book_dir(book) / "text" / page.part
        stem, file, part = Path(page.file).stem, page.file, page.part
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{stem}.txt").write_text(mapping.gujarati(marked) + "\n", encoding="utf-8")
    (folder / f"{stem}.json").write_text(json.dumps({"page": file, "part": part, "lines": letters},
                                                    ensure_ascii=False, indent=1), encoding="utf-8")
    return {"page": file, "lines": len(out_lines), "letters": sum(len(r) for r in out_lines),
            "uncertain": uncertain, "readers": readers}


def convert_book(lib: Library, book_id: int, page_ids: Optional[Sequence[int]] = None, part: str = "read",
                 progress=None, cancel: Optional[Callable[[], bool]] = None, reader: Optional[LineReader] = None,
                 tesseract_path: str = "") -> Dict:
    """Convert a book's pages of one part (or the given pages), each stored as soon as it is done."""
    t0 = time.time()
    book = lib.get_book(book_id)
    cfg = lib.book_config(book)
    with lib.session() as s:
        q = select(Page.id).where(Page.book_id == book_id, Page.excluded.is_not(True))          # excluded pages are not read (C22)
        q = q.where(Page.id.in_(list(page_ids))) if page_ids else q.where(Page.part == part)
        ids = list(s.scalars(q.order_by(Page.number, Page.id)))
        targets = _groups_for(s, book)
    if not ids:
        raise LibraryError("No pages to convert: cut the Read Book pages first.")
    if reader is None and book.writing == "printed":
        reader = book_tesseract_reader(lib, book, tesseract_path)
    letter_reader = _letter_reader(lib, book)                # loaded once for all the pages
    lm = _language_model(lib, book, cfg)
    done, uncertain, letters = 0, 0, 0
    for n, pid in enumerate(ids, 1):
        if cancel and cancel():
            raise Cancelled(f"Stopped after {done} pages; those are converted.")
        t = time.time()
        r = convert_page(lib, pid, reader, targets, letter_reader, lm)
        done += 1
        uncertain += r["uncertain"]
        letters += r["letters"]
        if progress:
            progress(n, len(ids), LineDone(r["page"], "OK", f"{r['letters']} letters, {r['uncertain']} uncertain",
                                           time.time() - t))
    return {"pages": done, "letters": letters, "uncertain": uncertain, "seconds": round(time.time() - t0, 1)}


def _page_text(lib: Library, s, row: PageText) -> Dict:
    page = s.get(Page, row.page_id)
    mapping = mapping_for(lib.book_config(s.get(Book, page.book_id)))
    proofread = json.loads(row.proofread or "{}")
    lines = live_lines(s, row.page_id, json.loads(row.letters), mapping, proofread)
    numbers = _line_numbers(s, row.page_id)
    texts = [line_text(_letters(r)) for r in lines]
    # a proofread line whose text changed since (a letter corrected, split or undone) is "changed"
    states = []
    for i, t in enumerate(texts):
        done = proofread.get(str(numbers[i])) if i < len(numbers) else None
        states.append("" if done is None else "proofread" if done == t else "changed")
    text_dev = "\n".join(texts)
    return {"page_id": row.page_id, "text_dev": text_dev, "text_guj": mapping.gujarati(text_dev),
            "lines": lines, "line_states": states,
            "proofread": states.count("proofread"),
            "corrected": sum(x["source"] == "label" for r in lines for x in r),
            "uncertain": sum(bool(x["uncertain"]) for r in lines for x in r), "readers": row.readers,
            "uncertain_tesseract": sum(bool(x.get("t_uncertain")) for r in lines for x in r),
            "converted_at": row.converted_at.isoformat() if row.converted_at else None,
            "edited_at": row.edited_at.isoformat() if row.edited_at else None}


def page_text(lib: Library, page_id: int) -> Optional[Dict]:
    """A converted page for the Text view, as it is now (`live_lines`), or None if not converted."""
    with lib.session() as s:
        row = s.scalar(select(PageText).where(PageText.page_id == page_id))
        return None if row is None else _page_text(lib, s, row)


def book_page_texts(lib: Library, book_id: int, part: str = "read", page_id: Optional[int] = None,
                    page_ids: Optional[Sequence[int]] = None) -> List[Tuple[Page, Dict]]:
    """The converted pages of a part (or one page, or the pages `page_ids` of the part) as they are now, in
    page order."""
    with lib.session() as s:
        q = select(Page, PageText).join(PageText, PageText.page_id == Page.id).where(Page.book_id == book_id)
        q = q.where(Page.id == page_id) if page_id else q.where(Page.part == part, Page.excluded.is_not(True))
        if page_ids:
            q = q.where(Page.id.in_(list(page_ids)))
        out = []
        for page, row in s.execute(q.order_by(Page.number, Page.id)).all():
            s.expunge(page)
            out.append((page, _page_text(lib, s, row)))
        return out


def set_proofread(lib: Library, page_id: int, line: int, done: bool = True) -> Dict:
    """Mark line `line` (its index on the page) proofread, keeping its text as it is now, or not."""
    with lib.session() as s:
        row = s.scalar(select(PageText).where(PageText.page_id == page_id))
        if row is None:
            raise LibraryError("This page is not converted yet.")
        now_ = _page_text(lib, s, row)
        numbers = _line_numbers(s, page_id)
        if not 0 <= line < min(len(numbers), len(now_["lines"])):
            raise LibraryError(f"The page has no line {line + 1}.")
        if done and any(not x["text_dev"] for x in now_["lines"][line]):
            raise LibraryError("The line has letters no reader could read (shown as ?): type them first.")
        proofread = json.loads(row.proofread or "{}")
        if done:
            proofread[str(numbers[line])] = line_text(_letters(now_["lines"][line]))
        else:
            proofread.pop(str(numbers[line]), None)
        row.proofread = json.dumps(proofread, ensure_ascii=False)
        row.edited_at = now()
        got = _page_text(lib, s, row)
        page = s.get(Page, page_id)
        book = s.get(Book, page.book_id)
        cfg = lib.book_config(book)
        _write_files(lib, book, page, got["lines"], cfg.uncertain_marker, mapping_for(cfg))
        return got


def _distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def proofread_stats(lib: Library, book_id: int, part: str = "read") -> Dict:
    """How right the conversion was on the proofread lines: the share of characters (Devanagari code
    points, spaces left out) wrong in the conversion's reading, with the groups and with Tesseract alone."""
    lines = chars = wrong = wrong_t = 0
    with lib.session() as s:
        q = (select(PageText).join(Page, PageText.page_id == Page.id)
             .where(Page.book_id == book_id, Page.part == part, Page.excluded.is_not(True)))
        for row in s.scalars(q):
            proofread = json.loads(row.proofread or "{}")
            if not proofread:
                continue
            stored = json.loads(row.letters)
            numbers = _line_numbers(s, row.page_id)
            for i, n in enumerate(numbers):
                truth = proofread.get(str(n))
                if truth is None or i >= len(stored):
                    continue
                truth = truth.replace(" ", "")
                lines += 1
                chars += len(truth)
                wrong += _distance(line_text(_letters(stored[i])).replace(" ", ""), truth)
                wrong_t += _distance(line_text(_letters(stored[i], "tesseract")).replace(" ", ""), truth)
    return {"lines": lines, "chars": chars,
            "cer": round(wrong / chars, 4) if chars else None,
            "cer_tesseract": round(wrong_t / chars, 4) if chars else None}


def book_texts(lib: Library, book_id: int, part: str = "read",
               page_id: Optional[int] = None) -> List[Tuple[Page, PageText]]:
    """The converted pages of a part (or one page), in page order."""
    with lib.session() as s:
        q = select(Page, PageText).join(PageText, PageText.page_id == Page.id).where(Page.book_id == book_id)
        q = q.where(Page.id == page_id) if page_id else q.where(Page.part == part, Page.excluded.is_not(True))
        return [tuple(r) for r in s.execute(q.order_by(Page.number, Page.id)).all()]


def marked_lines(lines: List[List[Dict]], marker: str, script: str, mapping, readers: str = "both") -> List[str]:
    """A page's lines (as `page_text` gives them) as written in a download: with the uncertain-letter
    marker, in Gujarati or Devanagari; `readers` "tesseract" writes Tesseract's reading alone (where the
    page has it)."""
    out = []
    for letters in lines:
        line = line_text(_letters(letters, readers), marker)
        out.append(mapping.gujarati(line) if script == "gujarati" else line)
    return out

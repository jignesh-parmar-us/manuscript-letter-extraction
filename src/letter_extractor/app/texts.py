"""Converting pages into text (C16b), and the texts' downloads.

For each page (Read Book pages, or training pages to measure against their labels):
1. its letters, line by line in reading order;
2. **printed books:** Tesseract reads each line image (several lines at once); its aksharas are put on
   the cut letters with C11's alignment;
3. every letter is compared with the book's **labelled groups** (nearest centre, C13's method);
4. `ocr.convert.choose` decides each letter's text, confidence and whether it is uncertain;
5. the page's text is joined line by line (spaces at word gaps on printed books), mapped to Gujarati,
   stored as a `PageText` row and written to `text/<part>/<page>.txt` (with the uncertain-letter
   marker) and `.json` (every letter with its sample and box: traceable to the page).
A conversion job stores each page when it is done, so a cancel keeps the pages already converted.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
from sqlalchemy import select

from .. import io_utils
from ..mapping import mapping_for
from ..ocr.align import align_line
from ..ocr.aksharas import line_aksharas
from ..ocr.convert import LetterText, choose, line_text, mark_spaces
from .centres import centres
from .db import Book, Line, Page, PageText, Sample, now
from .library import Cancelled, Library, LibraryError
from .suggest import LineDone, tesseract_reader, _workers

LineReader = Callable[[np.ndarray], object]


def _nearest(fp: Optional[bytes], groups, C: np.ndarray) -> Optional[Tuple[str, float]]:
    if fp is None or C.size == 0:
        return None
    d = np.linalg.norm(C - np.frombuffer(fp, np.float32), axis=1)
    i = int(np.argmin(d))
    return groups[i].label_dev, float(d[i])


def _read_lines(lib: Library, book: Book, cfg, lines: Sequence[Line], letters: Dict[int, List[Sample]],
                reader: LineReader) -> Dict[int, Tuple[str, float]]:
    """Tesseract's reading of each letter of these lines: sample id -> (text, confidence 0 to 100)."""
    book_dir = lib.book_dir(book)

    def read(line: Line):
        smps = letters.get(line.id, [])
        if not smps:
            return {}
        rgb, _ = io_utils.load_image(book_dir / line.image)
        reading = reader(rgb)
        al = align_line(line_aksharas(reading.words), [(x.x, x.x + x.w) for x in smps],
                        dx=max(0, line.x - cfg.line_margin_px), min_overlap=cfg.align_min_overlap,
                        sure_overlap=cfg.align_sure_overlap, min_matched=cfg.align_min_matched)
        if al.refused:
            return {}
        return {smps[m.sample].id: (m.text, m.conf) for m in al.matches}

    out: Dict[int, Tuple[str, float]] = {}
    with ThreadPoolExecutor(max_workers=_workers()) as pool:
        for got in pool.map(read, lines):
            out.update(got)
    return out


def convert_page(lib: Library, page_id: int, reader: Optional[LineReader] = None,
                 targets=None) -> Dict:
    """Convert one page and store its text. `reader` reads a line image (Tesseract by default on printed
    books; tests pass their own); `targets` are the book's labelled groups and centres, if already known."""
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
        groups, C = targets if targets is not None else centres(s, book.id, labelled_only=True)
        tess: Dict[int, Tuple[str, float]] = {}
        readers = []
        if printed and reader is not None:
            tess = _read_lines(lib, book, cfg, lines, by_line, reader)
            readers.append("tesseract")
        if len(C):
            readers.append("groups")
        mapping = mapping_for(cfg)
        out_lines: List[List[LetterText]] = []
        for line in lines:
            row: List[LetterText] = []
            for x in by_line.get(line.id, []):
                t = tess.get(x.id)
                g = _nearest(x.fingerprint, groups, C)
                text, conf, source, uncertain = choose(t, g, cfg, x.kind)
                seen = ([("tesseract", t[0], round(t[1], 1))] if t else []) + \
                       ([("groups", g[0], round(g[1], 3))] if g else [])
                row.append(LetterText(x.id, line.number, (x.x, x.y, x.w, x.h), text, conf, source, uncertain,
                                      readings=seen))
            mark_spaces(row, cfg, printed)
            out_lines.append(row)
        text_dev = "\n".join(line_text(r) for r in out_lines)
        marked = "\n".join(line_text(r, cfg.uncertain_marker) for r in out_lines)
        uncertain = sum(x.uncertain for r in out_lines for x in r)
        letters = [[{"sample_id": x.sample_id, "box": list(x.box), "text_dev": x.text,
                     "text_guj": mapping.gujarati(x.text) if x.text else "", "conf": x.conf, "source": x.source,
                     "uncertain": x.uncertain, "space": x.space_before, "readings": x.readings} for x in r]
                   for r in out_lines]
        row = s.scalar(select(PageText).where(PageText.page_id == page_id))
        if row is None:
            row = PageText(page_id=page_id)
            s.add(row)
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
        q = select(Page.id).where(Page.book_id == book_id)
        q = q.where(Page.id.in_(list(page_ids))) if page_ids else q.where(Page.part == part)
        ids = list(s.scalars(q.order_by(Page.number, Page.id)))
        targets = centres(s, book_id, labelled_only=True)
    if not ids:
        raise LibraryError("No pages to convert: cut the Read Book pages first.")
    if reader is None and book.writing == "printed":
        reader = tesseract_reader(cfg, tesseract_path)
    done, uncertain, letters = 0, 0, 0
    for n, pid in enumerate(ids, 1):
        if cancel and cancel():
            raise Cancelled(f"Stopped after {done} pages; those are converted.")
        t = time.time()
        r = convert_page(lib, pid, reader, targets)
        done += 1
        uncertain += r["uncertain"]
        letters += r["letters"]
        if progress:
            progress(n, len(ids), LineDone(r["page"], "OK", f"{r['letters']} letters, {r['uncertain']} uncertain",
                                           time.time() - t))
    return {"pages": done, "letters": letters, "uncertain": uncertain, "seconds": round(time.time() - t0, 1)}


def page_text(lib: Library, page_id: int) -> Optional[Dict]:
    """A converted page for the Text view: its lines with their letters, or None if not converted."""
    with lib.session() as s:
        row = s.scalar(select(PageText).where(PageText.page_id == page_id))
        if row is None:
            return None
        return {"page_id": page_id, "text_dev": row.text_dev, "text_guj": row.text_guj,
                "lines": json.loads(row.letters), "uncertain": row.uncertain, "readers": row.readers,
                "converted_at": row.converted_at.isoformat() if row.converted_at else None}


def book_texts(lib: Library, book_id: int, part: str = "read",
               page_id: Optional[int] = None) -> List[Tuple[Page, PageText]]:
    """The converted pages of a part (or one page), in page order."""
    with lib.session() as s:
        q = select(Page, PageText).join(PageText, PageText.page_id == Page.id).where(Page.book_id == book_id)
        q = q.where(Page.id == page_id) if page_id else q.where(Page.part == part)
        return [tuple(r) for r in s.execute(q.order_by(Page.number, Page.id)).all()]


def marked_lines(row: PageText, marker: str, script: str, mapping) -> List[str]:
    """A page's lines as written in a download: with the uncertain-letter marker, in Gujarati or Devanagari."""
    from ..ocr.convert import LetterText as L
    out = []
    for letters in json.loads(row.letters):
        line = line_text([L(x["sample_id"], 0, tuple(x["box"]), x["text_dev"], x["conf"], x["source"],
                            x["uncertain"], x["space"]) for x in letters], marker)
        out.append(mapping.gujarati(line) if script == "gujarati" else line)
    return out

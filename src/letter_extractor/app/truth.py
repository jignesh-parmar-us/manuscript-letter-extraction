"""The line truth screen: checked text of whole lines, independent of the letter cuts.

The user sees a line image with Tesseract's reading of the whole line (no cutting: what Tesseract reads
on its own) and corrects it to what the line really says, in Gujarati or Devanagari. The text is kept as
Devanagari NFC with single spaces. These lines are the test set every way of reading is compared on, so
they never depend on how the letters were cut.
"""
from __future__ import annotations

import unicodedata
from typing import Callable, Dict, List, Optional

from sqlalchemy import func, select

from .. import io_utils
from ..mapping import mapping_for
from .db import Book, Line, LineTruth, Page, now
from .library import Library, LibraryError, NotFound

_tesseract: Dict[tuple, str] = {}                       # (library, line id, line image) -> Tesseract's text


def clean(text: str, mapping) -> str:
    """Typed text as stored: Gujarati to Devanagari, NFC, single spaces."""
    return " ".join(unicodedata.normalize("NFC", mapping.devanagari(text)).split())


def _line(s, line_id: int):
    line = s.get(Line, line_id)
    if line is None:
        raise NotFound(f"No line with id {line_id}.")
    page = s.get(Page, line.page_id)
    return line, page, s.get(Book, page.book_id)


def book_progress(lib: Library, book_id: int, part: str = "read") -> Dict:
    """How many lines of each page of a part are checked."""
    with lib.session() as s:
        pages = s.execute(select(Page.id, Page.file, func.count(Line.id), func.count(LineTruth.id))
                          .join(Line, Line.page_id == Page.id)
                          .outerjoin(LineTruth, LineTruth.line_id == Line.id)
                          .where(Page.book_id == book_id, Page.part == part)
                          .group_by(Page.id).order_by(Page.number, Page.id)).all()
    out = [{"page_id": pid, "file": file, "lines": n, "checked": c} for pid, file, n, c in pages]
    return {"pages": out, "lines": sum(p["lines"] for p in out), "checked": sum(p["checked"] for p in out)}


def page_lines(lib: Library, page_id: int) -> List[Dict]:
    """The lines of a page with their checked text, if any."""
    with lib.session() as s:
        page = s.get(Page, page_id)
        if page is None:
            raise NotFound(f"No page with id {page_id}.")
        mapping = mapping_for(lib.book_config(s.get(Book, page.book_id)))
        rows = s.execute(select(Line, LineTruth).outerjoin(LineTruth, LineTruth.line_id == Line.id)
                         .where(Line.page_id == page_id).order_by(Line.number)).all()
        return [{"line_id": ln.id, "number": ln.number, "box": [ln.x, ln.y, ln.w, ln.h], "image": ln.image,
                 "truth_dev": t.text_dev if t else None, "truth_guj": mapping.gujarati(t.text_dev) if t else None}
                for ln, t in rows]


def tesseract_text(lib: Library, line_id: int, reader: Callable) -> Dict:
    """Tesseract's reading of the whole line image (no letter cutting), kept in memory."""
    with lib.session() as s:
        line, page, book = _line(s, line_id)
        key = (str(lib.root), line_id, line.image)
        mapping = mapping_for(lib.book_config(book))
        path = lib.book_dir(book) / line.image
    if key not in _tesseract:
        rgb, _ = io_utils.load_image(path)
        _tesseract[key] = unicodedata.normalize("NFC", reader(rgb).text)
    text = _tesseract[key]
    return {"line_id": line_id, "text_dev": text, "text_guj": mapping.gujarati(text)}


def save_truth(lib: Library, line_id: int, text: str, tesseract_dev: str = "") -> Optional[Dict]:
    """Store the line's checked text (empty: remove it)."""
    with lib.session() as s:
        line, page, book = _line(s, line_id)
        mapping = mapping_for(lib.book_config(book))
        dev = clean(text, mapping)
        row = s.scalar(select(LineTruth).where(LineTruth.line_id == line_id))
        if not dev:
            if row is not None:
                s.delete(row)
            return None
        if not any("ऀ" <= ch <= "ॿ" for ch in dev):
            raise LibraryError("Type the line in Gujarati or Devanagari.")
        if row is None:
            row = LineTruth(line_id=line_id)
            s.add(row)
        row.text_dev, row.updated_at = dev, now()
        row.tesseract_dev = unicodedata.normalize("NFC", tesseract_dev) or row.tesseract_dev
        return {"line_id": line_id, "truth_dev": dev, "truth_guj": mapping.gujarati(dev)}

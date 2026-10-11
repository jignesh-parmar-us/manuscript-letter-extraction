"""Reading Read Book lines whole with Tesseract: no letter cutting.

Each line image (found by the line finder, other lines' ink painted out) goes to Tesseract as one image,
with the book's settings (model, page mode). Its text is kept per line with the aksharas Tesseract read
and their confidences, words separated by spaces as Tesseract found them. Measured on 73 hand-checked
lines of the printed 1933 book (2026-10-11): 5.1% of the characters wrong, against 6.1% for the text
built from cut letters (Tesseract only) and 7.5% with the reader and language model. An akshara is
uncertain when 0.8 x its confidence / 100 is below `text_min_confidence`, as in "Tesseract only".

With the book's language model on (`language_model`, C15), each line is also corrected: an akshara may
become one of Tesseract's own alternatives for it when the line gets much more likely (`lm_weight`,
`lm_min_gain`); the corrected reading is kept beside Tesseract's. Measured on the same lines with the
user's word list: 5.06% -> 4.45%.

A line can be corrected (`edited_dev`, shown and downloaded instead of the reading) and marked reviewed;
a reviewed line is also kept as a checked line (Line truth), so every reviewed line joins the test set.
Each akshara keeps its box on the page (Tesseract's character boxes), so the Text view can show it.
"""
from __future__ import annotations

import json
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional, Sequence

from sqlalchemy import func, select

from .. import io_utils
from ..mapping import mapping_for
from ..ocr.aksharas import group_chars
from ..ocr.language import correct_line, tesseract_options
from .db import Book, Line, Page, WholeLine, now
from .library import Cancelled, Library, LibraryError, NotFound
from .suggest import LineDone, _workers, tesseract_reader


def _aksharas(reading, lm=None, cfg=None, origin=(0, 0)) -> List[list]:
    """[text, confidence, space before, language model's reading or None, box on the page or None] per
    akshara of the line; `origin` is the line image's top left corner on the page."""
    out, opts = [], []
    for wi, w in enumerate(reading.words):
        for ai, a in enumerate(group_chars(w.chars)):
            if a.text.strip():
                bx, by, bw, bh = a.box
                box = [int(origin[0] + bx), int(origin[1] + by), int(bw), int(bh)] if bw > 0 and bh > 0 else None
                out.append([a.text, round(float(a.conf), 1), bool(wi and not ai), None, box])
                opts.append(tesseract_options(a))
    if lm is not None and opts:
        pick, _ = correct_line(lm, opts, cfg.lm_weight, cfg.lm_min_gain)
        for item, o, k in zip(out, opts, pick):
            if k:
                item[3] = o[k][0]
    return out


def read_page_lines(lib: Library, page_id: int, reader: Callable) -> Dict:
    """Read every line of a page whole and store it."""
    with lib.session() as s:
        page = s.get(Page, page_id)
        if page is None:
            raise NotFound(f"No page with id {page_id}.")
        book = s.get(Book, page.book_id)
        cfg = lib.book_config(book)
        m = cfg.line_margin_px                       # the line image is the line's box with this margin
        lines = [(ln.id, ln.image, (max(0, ln.x - m), max(0, ln.y - m)))
                 for ln in s.scalars(select(Line).where(Line.page_id == page_id).order_by(Line.number))]
        folder, file, book_id = lib.book_dir(book), page.file, book.id
    lm = None
    if cfg.language_model:
        from .dictionary import book_model
        lm = book_model(lib, book_id)
        lm = lm if len(lm) else None

    def read(item):
        line_id, image, origin = item
        rgb, _ = io_utils.load_image(folder / image)
        return line_id, _aksharas(reader(rgb), lm, cfg, origin)

    with ThreadPoolExecutor(max_workers=_workers()) as pool:
        found = list(pool.map(read, lines))
    low = 0
    with lib.session() as s:
        for line_id, aks in found:
            row = s.scalar(select(WholeLine).where(WholeLine.line_id == line_id))
            if row is None:
                row = WholeLine(line_id=line_id)
                s.add(row)
            row.engine = "tesseract"
            row.text_dev = unicodedata.normalize("NFC", "".join((" " if a[2] else "") + a[0] for a in aks))
            row.aksharas, row.read_at = json.dumps(aks, ensure_ascii=False), now()
            low += sum(_uncertain(a[1], cfg) for a in aks)
    return {"page": file, "lines": len(found), "uncertain": low}


def _uncertain(conf: float, cfg) -> bool:
    return 0.8 * conf / 100 < cfg.text_min_confidence


def read_book_lines(lib: Library, book_id: int, page_ids: Optional[Sequence[int]] = None, part: str = "read",
                    progress=None, cancel: Optional[Callable[[], bool]] = None, reader: Optional[Callable] = None,
                    tesseract_path: str = "") -> Dict:
    """Read a part's pages (or the given pages) line by line, each page stored when done."""
    t0 = time.time()
    book = lib.get_book(book_id)
    with lib.session() as s:
        q = select(Page.id).where(Page.book_id == book_id)
        q = q.where(Page.id.in_(list(page_ids))) if page_ids else q.where(Page.part == part)
        ids = list(s.scalars(q.order_by(Page.number, Page.id)))
    if not ids:
        raise LibraryError("No pages to read: cut the Read Book pages first.")
    reader = reader or tesseract_reader(lib.book_config(book), tesseract_path)
    lines = uncertain = 0
    for n, pid in enumerate(ids, 1):
        if cancel and cancel():
            raise Cancelled(f"Stopped after {n - 1} pages; those are read.")
        t = time.time()
        r = read_page_lines(lib, pid, reader)
        lines += r["lines"]
        uncertain += r["uncertain"]
        if progress:
            progress(n, len(ids), LineDone(r["page"], "OK", f"{r['lines']} lines, {r['uncertain']} uncertain",
                                           time.time() - t))
    return {"pages": len(ids), "lines": lines, "uncertain": uncertain, "seconds": round(time.time() - t0, 1)}


def page_whole_lines(lib: Library, page_id: int) -> Optional[Dict]:
    """A page's lines read whole, for the Text view; None if none of them is read."""
    with lib.session() as s:
        page = s.get(Page, page_id)
        if page is None:
            raise NotFound(f"No page with id {page_id}.")
        cfg = lib.book_config(s.get(Book, page.book_id))
        mapping = mapping_for(cfg)
        rows = s.execute(select(Line, WholeLine).outerjoin(WholeLine, WholeLine.line_id == Line.id)
                         .where(Line.page_id == page_id).order_by(Line.number)).all()
        if not any(w is not None for _, w in rows):
            return None
        lines, low, read_at = [], 0, None
        for ln, w in rows:
            aks = json.loads(w.aksharas) if w is not None else []
            items = [{"text_dev": a[0], "text_guj": mapping.gujarati(a[0]), "conf": a[1], "space": a[2],
                      "uncertain": _uncertain(a[1], cfg), "box": a[4] if len(a) > 4 else None,
                      **({"lm_dev": a[3], "lm_guj": mapping.gujarati(a[3])} if len(a) > 3 and a[3] else {})}
                     for a in aks]
            low += sum(x["uncertain"] for x in items)
            if w is not None and (read_at is None or w.read_at > read_at):
                read_at = w.read_at
            edited = w.edited_dev if w is not None else ""
            lines.append({"line_id": ln.id, "number": ln.number, "box": [ln.x, ln.y, ln.w, ln.h],
                          "text_dev": w.text_dev if w is not None else "",
                          "text_guj": mapping.gujarati(w.text_dev) if w is not None else "", "aksharas": items,
                          "edited_dev": edited, "edited_guj": mapping.gujarati(edited) if edited else "",
                          "reviewed": bool(w.reviewed) if w is not None else False})
        return {"page_id": page_id, "lines": lines, "uncertain": low,
                "read_at": read_at.isoformat() if read_at else None}


def book_whole_lines(lib: Library, book_id: int, part: str = "read") -> List[Dict]:
    """The pages of a part with lines read whole: page id, lines read."""
    with lib.session() as s:
        rows = s.execute(select(Page.id, func.count(WholeLine.id)).join(Line, Line.page_id == Page.id)
                         .join(WholeLine, WholeLine.line_id == Line.id)
                         .where(Page.book_id == book_id, Page.part == part).group_by(Page.id)).all()
    return [{"page_id": pid, "lines": n} for pid, n in rows]


def whole_line_texts(lib: Library, book_id: int, part: str = "read", page_id: Optional[int] = None):
    """(page, [line texts]) per page with lines read whole, in page order, for downloads."""
    out = []
    with lib.session() as s:
        q = select(Page).where(Page.book_id == book_id)
        q = q.where(Page.id == page_id) if page_id else q.where(Page.part == part)
        pages = s.scalars(q.order_by(Page.number, Page.id)).all()
        for p in pages:
            s.expunge(p)
    for p in pages:
        got = page_whole_lines(lib, p.id)
        if got is not None:
            out.append((p, got["lines"]))
    return out


def set_whole_line(lib: Library, line_id: int, text: Optional[str] = None, reviewed: Optional[bool] = None,
                   shown: str = "") -> Dict:
    """Correct a line read whole (`text`; "" removes the correction) and / or mark it reviewed. A reviewed
    line is kept as a checked line (Line truth) with its text: the correction, or `shown` (the reading as
    the user saw it, with or without the language model)."""
    from .truth import clean, save_truth
    with lib.session() as s:
        row = s.scalar(select(WholeLine).where(WholeLine.line_id == line_id))
        if row is None:
            raise LibraryError("This line is not read yet: read the page first.")
        line = s.get(Line, line_id)
        mapping = mapping_for(lib.book_config(s.get(Book, s.get(Page, line.page_id).book_id)))
        if text is not None:
            row.edited_dev = clean(text, mapping)
            row.edited_at = now()
        if reviewed is not None:
            row.reviewed = bool(reviewed)
        edited, is_reviewed = row.edited_dev, row.reviewed
    if reviewed is not None or (text is not None and is_reviewed):
        save_truth(lib, line_id, (edited or shown or "") if is_reviewed else "")
    return {"line_id": line_id, "edited_dev": edited, "edited_guj": mapping.gujarati(edited) if edited else "",
            "reviewed": is_reviewed}

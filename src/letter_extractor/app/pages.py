"""The page manager of a book and a dataset (Phase 3, C22): the pages in their order, with what is on them;
excluding / including, moving up and down, deleting.

- **Order** is `page.number`. Pages captured or prepared keep the order of their file names until it is changed
  here; new pages then come after the last one (library._new_numbers). Reading, Measure and export follow it.
- **Excluded** pages (`page.excluded`) are kept with everything on them but skipped: in a book by Prepare, reading,
  Measure, training and export; in a dataset by capture, training and export. A file that is not prepared (or
  captured) yet is excluded with a row of its own without lines (status NOT_PREPARED); including it again removes
  that row, so the file is new again.
- **Deleting** a page removes its letters, lines, readings, checked lines and corrections. Its image file is removed
  too when it is the app's own copy (uploaded, or a PDF's page); a file in a folder of the user's own is never
  touched: the page stays there, excluded, or the next Prepare would bring it back.
- Excluding or deleting a page with checked lines, corrections or (in a dataset) letters in reviewed groups asks
  first (BookHasReviewError, then `force`).
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import delete, func, select

from .. import io_utils
from .db import BOOK, DATASET, Action, Book, LetterGroup, Line, LineTruth, Page, PageText, Sample, WholeLine, now
from .library import BookHasReviewError, Library, LibraryError, NotFound

PART = {DATASET: "training", BOOK: "read"}
NOT_PREPARED = "Not prepared"          # the status of a row that only holds an exclusion


def part_of(book: Book) -> str:
    return PART[book.kind]


def owns_files(lib: Library, book: Book, uploads: Optional[Path]) -> bool:
    """Whether the row's page images are the app's own copies (a PDF's pages, or uploaded), which deleting a page
    may remove; otherwise they are in a folder of the user's own and are never touched."""
    if book.kind == BOOK and book.read_pdf:
        return True
    folder = book.input_dir if book.kind == DATASET else book.read_dir
    return bool(folder and uploads) and Path(folder).resolve() == lib.upload_dir(book, uploads)


def _folder(lib: Library, book: Book) -> Optional[Path]:
    try:
        return lib.part_folder(book, part_of(book))
    except LibraryError:
        return None


def _counts(s, q) -> Dict[int, int]:
    return dict(s.execute(q).all())


def lost_counts(s, page_ids: List[int]) -> Dict[int, Dict[str, int]]:
    """Per page what deleting it loses (and excluding it leaves unused): checked lines (Line truth), corrections
    (whole lines corrected or reviewed, proofread lines) and letters in reviewed groups."""
    if not page_ids:
        return {}
    checked = _counts(s, select(Line.page_id, func.count(LineTruth.id)).join(LineTruth, LineTruth.line_id == Line.id)
                      .where(Line.page_id.in_(page_ids), LineTruth.text_dev != "").group_by(Line.page_id))
    corrected = _counts(s, select(Line.page_id, func.count(WholeLine.id)).join(WholeLine, WholeLine.line_id == Line.id)
                        .where(Line.page_id.in_(page_ids), (WholeLine.edited_dev != "") | WholeLine.reviewed.is_(True))
                        .group_by(Line.page_id))
    import json
    for pid, raw in s.execute(select(PageText.page_id, PageText.proofread).where(PageText.page_id.in_(page_ids))):
        n = len([v for v in json.loads(raw or "{}").values() if v])
        if n:
            corrected[pid] = corrected.get(pid, 0) + n
    reviewed = _counts(s, select(Sample.page_id, func.count(Sample.id)).join(LetterGroup, Sample.group_id == LetterGroup.id)
                       .where(Sample.page_id.in_(page_ids), Sample.deleted.is_(False), LetterGroup.status != "auto")
                       .group_by(Sample.page_id))
    return {p: {"checked": checked.get(p, 0), "corrections": corrected.get(p, 0), "reviewed": reviewed.get(p, 0)}
            for p in page_ids}


def lost_text(lost: Dict[str, int]) -> str:
    """'3 checked lines (Line truth), 2 corrections', or '' when there is nothing."""
    parts = []
    if lost.get("checked"):
        parts.append(f"{lost['checked']} checked line{'s' * (lost['checked'] != 1)} (Line truth)")
    if lost.get("corrections"):
        parts.append(f"{lost['corrections']} correction{'s' * (lost['corrections'] != 1)}")
    if lost.get("reviewed"):
        parts.append(f"{lost['reviewed']} letter{'s' * (lost['reviewed'] != 1)} in reviewed groups")
    return ", ".join(parts)


def page_list(lib: Library, book_id: int, uploads: Optional[Path] = None) -> Dict:
    """The row's pages in order (prepared or captured ones, and exclusions), then the image files not prepared
    yet (in file-name order), with what is on each."""
    book = lib.get_book(book_id)
    part = part_of(book)
    folder = _folder(lib, book)
    with lib.session() as s:
        rows = s.scalars(select(Page).where(Page.book_id == book_id, Page.part == part)
                         .order_by(Page.number, Page.id)).all()
        ids = [p.id for p in rows]
        lines = _counts(s, select(Line.page_id, func.count(Line.id)).where(Line.page_id.in_(ids)).group_by(Line.page_id))
        letters = _counts(s, select(Sample.page_id, func.count(Sample.id))
                          .where(Sample.page_id.in_(ids), Sample.deleted.is_(False)).group_by(Sample.page_id))
        lost = lost_counts(s, ids)
        out = [{"id": p.id, "file": p.file, "number": p.number, "excluded": p.excluded,
                "prepared": p.status != NOT_PREPARED, "status": p.status, "message": p.message,
                "lines": lines.get(p.id, 0), "samples": letters.get(p.id, 0), **lost[p.id],
                "missing": folder is not None and not (folder / p.file).is_file()} for p in rows]
    known = {p["file"] for p in out}
    images = io_utils.scan_folder(folder)[0] if folder is not None and folder.is_dir() else []
    out += [{"id": None, "file": f.name, "number": None, "excluded": False, "prepared": False, "status": "new",
             "message": "", "lines": 0, "samples": 0, "checked": 0, "corrections": 0, "reviewed": 0, "missing": False}
            for f in images if f.name not in known]
    return {"part": part, "folder": str(folder) if folder else "", "owned": owns_files(lib, book, uploads),
            "pages": out}


def _row(s, book_id: int, part: str, file: str) -> Optional[Page]:
    return s.scalars(select(Page).where(Page.book_id == book_id, Page.part == part, Page.file == file)).first()


def _ask(file: str, lost: Dict[str, int], what: str) -> None:
    text = lost_text(lost)
    if text:
        raise BookHasReviewError(f"Page {file} has {text}. {what}")


def set_excluded(lib: Library, book_id: int, file: str, excluded: bool, force: bool = False) -> Dict:
    """Exclude a page (kept, but skipped) or include it again. Asks first when the page has checked lines,
    corrections or letters in reviewed groups."""
    book = lib.get_book(book_id)
    part = part_of(book)
    with lib.session() as s:
        page = _row(s, book_id, part, file)
        if excluded:
            if page is not None and not page.excluded:
                if not force:
                    _ask(file, lost_counts(s, [page.id])[page.id],
                         "Excluded, they are kept but not used: not read, measured, trained on or exported.")
                page.excluded = True
            elif page is None:
                folder = _folder(lib, book)
                if folder is None or not (folder / file).is_file():
                    raise NotFound(f"No page {file} in '{book.name}'.")
                lib._exclusion_rows(s, book, part, [file])
        elif page is not None and page.excluded:
            if page.status == NOT_PREPARED:
                s.delete(page)                             # the file is new again
            else:
                page.excluded = False
        s.get(Book, book_id).updated_at = now()
    return {"file": file, "excluded": excluded}


def renumber(s, book_id: int, part: str, order: Optional[List[int]] = None) -> None:
    """Number the part's pages 1, 2, … in `order` (page ids), or in their present order."""
    if order is None:
        order = list(s.scalars(select(Page.id).where(Page.book_id == book_id, Page.part == part)
                               .order_by(Page.number, Page.id)))
    for i, pid in enumerate(order, 1):
        s.get(Page, pid).number = i


def move_page(lib: Library, book_id: int, page_id: int, by: int) -> Dict:
    """Move a page `by` places (-1 up, +1 down) among the row's pages; the pages are numbered 1, 2, … again."""
    book = lib.get_book(book_id)
    part = part_of(book)
    with lib.session() as s:
        order = list(s.scalars(select(Page.id).where(Page.book_id == book_id, Page.part == part)
                               .order_by(Page.number, Page.id)))
        if page_id not in order:
            raise NotFound(f"No page with id {page_id} in '{book.name}'.")
        i = order.index(page_id)
        j = min(max(i + by, 0), len(order) - 1)
        order.insert(j, order.pop(i))
        renumber(s, book_id, part, order)
        s.get(Book, book_id).updated_at = now()
    return {"page": page_id, "number": j + 1}


def delete_page(lib: Library, book_id: int, file: str, uploads: Optional[Path] = None, force: bool = False) -> Dict:
    """Delete a page with its letters, lines, readings, checked lines and corrections. Its image is removed when it
    is the app's own copy; in a folder of the user's own it stays, and the page stays as an exclusion. Asks first
    when something checked or reviewed is lost (`force`), which also clears the undo history if it touched the
    page's letters."""
    from .centres import recompute
    book = lib.get_book(book_id)
    part = part_of(book)
    folder = _folder(lib, book)
    owned = owns_files(lib, book, uploads)
    with lib.session() as s:
        page = _row(s, book_id, part, file)
        if page is None and (folder is None or not (folder / file).is_file()):
            raise NotFound(f"No page {file} in '{book.name}'.")
        page_id = page.id if page is not None else None
    manual = page_id is not None and lib.page_has_manual_work(page_id)
    if page_id is not None and not force:
        with lib.session() as s:
            lost = lost_counts(s, [page_id])[page_id]
        _ask(file, lost, "Deleting the page loses them for good.")
        if manual:
            raise BookHasReviewError(f"Page {file} has letters changed by hand. Deleting the page loses them.")
    with lib.session() as s:
        if page_id is not None:
            touched = set(s.scalars(select(Sample.group_id).where(Sample.page_id == page_id,
                                                                  Sample.group_id.is_not(None))))
            s.execute(delete(Sample).where(Sample.page_id == page_id))
            s.execute(delete(Page).where(Page.id == page_id))      # lines, texts, line truth go with it
            if manual:
                s.execute(delete(Action).where(Action.book_id == book_id))
            s.flush()
            recompute(s, touched)
            for gid in touched:                            # groups left empty and never reviewed go
                g = s.get(LetterGroup, gid)
                if g is not None and g.status == "auto" and not g.locked and \
                        not s.scalar(select(func.count(Sample.id)).where(Sample.group_id == gid,
                                                                       Sample.deleted.is_(False))):
                    s.delete(g)
        if not owned and folder is not None and (folder / file).is_file():
            s.flush()
            lib._exclusion_rows(s, book, part, [file])     # the user's file stays: so does its exclusion
        renumber(s, book_id, part)
        s.get(Book, book_id).updated_at = now()
    root = lib.book_dir(book) / lib.part_root(part)
    stem = Path(file).stem
    shutil.rmtree(root / "letters" / stem, ignore_errors=True)
    for f in (root / "lines").glob(f"{stem}_L[0-9][0-9].png") if (root / "lines").is_dir() else []:
        f.unlink()
    removed = bool(owned and folder is not None and (folder / file).is_file())
    if removed:
        (folder / file).unlink()
    return {"file": file, "file_removed": removed, "excluded": not owned}


def thumbnail(lib: Library, book_id: int, file: str, width: int = 200) -> Path:
    """A small copy of a page image (JPEG, kept in the row's cache/thumbs/), made when first asked for."""
    from PIL import Image
    book = lib.get_book(book_id)
    folder = _folder(lib, book)
    name = Path(file).name
    src = folder / name if folder is not None else None
    if src is None or not src.is_file():
        raise NotFound(f"No page image {name}.")
    st = src.stat()
    key = hashlib.sha1(f"{name}|{st.st_size}|{st.st_mtime_ns}|{width}".encode()).hexdigest()[:16]
    out = lib.book_dir(book) / "cache" / "thumbs" / f"{key}.jpg"
    if not out.is_file():
        out.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            im.thumbnail((width, width * 2))
            tmp = out.with_suffix(".tmp")
            im.convert("RGB").save(tmp, "JPEG", quality=80)
            tmp.rename(out)
    return out

"""The language model of a book (C15): what it learns from, imported word lists, and the model itself.

A book's model (`ocr.language.LanguageModel`) learns from:
- **its labels:** the labelled letters of its Training Data pages in reading order (a stretch ends at a
  letter without a label), which is the book's own text where it is known;
- **its proofread lines** (C17);
- **the word lists it uses:** imported text files (any running text or one word per line, in Devanagari
  or Gujarati: Gujarati is mapped to Devanagari with the C5b mapping, everything is kept as Devanagari
  NFC, and other characters break the text), stored in <library>/dictionaries/.
Models are kept in memory and rebuilt when one of these changes.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, select

from ..mapping import load_mapping
from ..ocr.language import LanguageModel, tokens
from .db import Book, LetterGroup, Page, PageText, Sample, WordList
from .library import LeftOut, Library, LibraryError, NotFound

_NOT_DEVANAGARI = re.compile(r"[^ऀ-ॿ\s]+")
_cache: Dict[Tuple[str, int], Tuple[tuple, LanguageModel]] = {}


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    return s[:40] or "words"


def to_devanagari_lines(text: str) -> List[str]:
    """A text file's lines as Devanagari NFC: Gujarati mapped to Devanagari, other characters dropped
    (they end a stretch of text), empty lines left out."""
    mapping = load_mapping()
    out = []
    for line in text.splitlines():
        dev = unicodedata.normalize("NFC", mapping.devanagari(unicodedata.normalize("NFC", line)))
        for part in _NOT_DEVANAGARI.split(dev):
            part = " ".join(part.split())
            if tokens(part):
                out.append(part)
    return out


def _json(w: WordList) -> Dict:
    return {"id": w.id, "name": w.name, "file": w.file, "lines": w.lines, "aksharas": w.aksharas,
            "books": json.loads(w.books or "[]"), "created_at": w.created_at.isoformat() if w.created_at else None}


def word_lists(lib: Library) -> List[Dict]:
    with lib.session() as s:
        return [_json(w) for w in s.scalars(select(WordList).order_by(WordList.id))]


def import_word_list(lib: Library, path: str, name: str = "", book_ids: Sequence[int] = ()) -> Dict:
    """Import a UTF-8 text file as a word list, used by `book_ids`."""
    src = Path(path).expanduser()
    if not src.is_file():
        raise LibraryError(f"No file at {src}.")
    try:
        text = src.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise LibraryError("The file is not UTF-8 text: save it as UTF-8 and import it again.")
    lines = to_devanagari_lines(text)
    if not lines:
        raise LibraryError("The file has no Devanagari or Gujarati text.")
    folder = lib.root / "dictionaries"
    folder.mkdir(parents=True, exist_ok=True)
    with lib.session() as s:
        n = (s.scalar(select(func.max(WordList.id))) or 0) + 1
        file = f"{n:04d}-{_slug(name or src.stem)}.txt"
        (folder / file).write_text("\n".join(lines) + "\n", encoding="utf-8")
        w = WordList(name=name.strip() or src.stem, file=file, lines=len(lines),
                     aksharas=sum(len(tokens(x)) for x in lines), books=json.dumps(sorted(set(book_ids))))
        s.add(w)
        s.flush()
        return _json(w)


def use_word_list(lib: Library, list_id: int, book_id: int, use: bool) -> Dict:
    with lib.session() as s:
        w = s.get(WordList, list_id)
        if w is None:
            raise NotFound(f"No word list with id {list_id}.")
        books = set(json.loads(w.books or "[]"))
        books = books | {book_id} if use else books - {book_id}
        w.books = json.dumps(sorted(books))
        return _json(w)


def delete_word_list(lib: Library, list_id: int) -> None:
    with lib.session() as s:
        w = s.get(WordList, list_id)
        if w is None:
            raise NotFound(f"No word list with id {list_id}.")
        file = w.file
        s.delete(w)
    (lib.root / "dictionaries" / file).unlink(missing_ok=True)


# ---- what a book's model learns from ----------------------------------------------------------------------
def _labels_of(s, book: Book, skip_files: Sequence = ()) -> List[str]:
    """The labelled letters the book's model learns: those of its reading model's datasets (C23; a dataset's
    own), dataset after dataset."""
    out: List[str] = []
    for src in Library.sources_in(s, book):
        out += _label_lines(s, src, skip_files)
    return out


def _label_lines(s, book_id: int, skip_files: Sequence = ()) -> List[str]:
    """The labelled letters of a row's Training Data pages in reading order, in stretches; `skip_files`: page ids
    (a LeftOut, C24) or file names of pages left out."""
    q = (select(Sample.line_id, LetterGroup.label_dev)
         .join(Page, Sample.page_id == Page.id)
         .outerjoin(LetterGroup, Sample.group_id == LetterGroup.id)
         .where(Sample.book_id == book_id, Sample.deleted.is_(False), Page.part == "training", Page.excluded.is_not(True)))
    q = _without(q, skip_files)
    rows = s.execute(q.order_by(Page.id, Sample.line_number, Sample.x, Sample.pos)).all()
    out, cur, line = [], [], None
    for line_id, label in rows:
        if line_id != line or not label:
            if cur:
                out.append("".join(cur))
            cur, line = [], line_id
        if label:
            cur.append(label)
    if cur:
        out.append("".join(cur))
    return out


def _without(q, skip):
    """`q` without the pages `skip`: page ids (a LeftOut) or file names."""
    if not skip:
        return q
    if isinstance(skip, LeftOut):
        return q.where(Page.id.not_in(list(skip)))
    return q.where(Page.file.not_in(list(skip)))


def _proofread_lines(s, book_id: int, skip_files: Sequence = ()) -> List[str]:
    out = []
    q = select(PageText.proofread).join(Page, PageText.page_id == Page.id).where(Page.book_id == book_id, Page.excluded.is_not(True))
    q = _without(q, skip_files)
    for raw in s.scalars(q):
        out.extend(v for v in json.loads(raw or "{}").values() if v)
    return out


def _lists_of(s, book_id: int) -> List[WordList]:
    return [w for w in s.scalars(select(WordList).order_by(WordList.id)) if book_id in json.loads(w.books or "[]")]


def _signature(s, book: Book) -> tuple:
    edited = s.scalar(select(func.max(PageText.edited_at)).join(Page, PageText.page_id == Page.id)
                      .where(Page.book_id == book.id))
    srcs = tuple(x for x in Library.sources_in(s, book) if x != book.id)
    labels_at = tuple(s.scalar(select(Book.updated_at).where(Book.id == x)) for x in srcs)
    return (book.updated_at, srcs, labels_at, edited, tuple((w.id, w.aksharas) for w in _lists_of(s, book.id)))


def book_model(lib: Library, book_id: int) -> LanguageModel:
    """The book's language model, rebuilt only when its labels, proofread lines or word lists changed."""
    with lib.session() as s:
        book = s.get(Book, book_id)
        if book is None:
            raise NotFound(f"No book with id {book_id}.")
        sig = _signature(s, book)
        key = (str(lib.root), book_id)
        if key in _cache and _cache[key][0] == sig:
            return _cache[key][1]
        lm = LanguageModel()
        lm.add_all(_labels_of(s, book))
        lm.add_all(_proofread_lines(s, book_id))
        files = [lib.root / "dictionaries" / w.file for w in _lists_of(s, book_id)]
    for f in files:
        if f.is_file():
            lm.add_all(f.read_text(encoding="utf-8").splitlines())
    _cache[key] = (sig, lm)
    return lm


def book_model_without(lib: Library, book_id: int, skip_files: Sequence) -> LanguageModel:
    """The book's language model without the labels and proofread lines of the pages `skip_files` (the book's
    pages, by id or file name, and the same pages of its datasets by content: Library.left_out, C24), for measuring
    on those pages; the word lists are kept. Not cached."""
    book = lib.get_book(book_id)
    skip_files = lib.left_out(book_id, skip_files)
    with lib.session() as s:
        lm = LanguageModel()
        lm.add_all(_labels_of(s, book, skip_files))
        lm.add_all(_proofread_lines(s, book_id, skip_files))
        files = [lib.root / "dictionaries" / w.file for w in _lists_of(s, book_id)]
    for f in files:
        if f.is_file():
            lm.add_all(f.read_text(encoding="utf-8").splitlines())
    return lm


def book_language(lib: Library, book_id: int) -> Dict:
    """What the book's language model learns from, for the Dictionary screen."""
    book = lib.get_book(book_id)
    cfg = lib.book_config(book)
    with lib.session() as s:
        labels = _labels_of(s, book)
        proofread = _proofread_lines(s, book_id)
    return {"enabled": cfg.language_model,
            "labels": {"stretches": len(labels), "aksharas": sum(len(tokens(x)) for x in labels)},
            "proofread": {"lines": len(proofread), "aksharas": sum(len(tokens(x)) for x in proofread)},
            "lists": [w for w in word_lists(lib) if book_id in w["books"]],
            "aksharas": len(book_model(lib, book_id))}

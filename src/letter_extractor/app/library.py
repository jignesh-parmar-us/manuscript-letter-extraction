"""The library (C5a): one folder with `library.db` and one sub-folder per book.

```
<library>/
  library.db
  books/<folder>/        letters/<page>/L01_003.png (+ _mask.png), lines/, debug/, report.csv, samples.csv
```

Input pages are only read: the database keeps the book's input folder, each page's file name and its
SHA-256 checksum, so a moved or changed page is noticed (`check_pages`).

Capturing a book runs the unchanged pipeline (C0-C4) into the book's folder and stores the result.
It replaces everything found in the book before, so it refuses when the book holds manual work,
unless `force=True` (re-cutting single pages without losing work comes with the review screens).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, delete, func, insert, select
from sqlalchemy.orm import Session, sessionmaker

from .. import io_utils
from ..config import Config, load_config
from ..grouping import UNSURE
from ..pipeline import ProgressFn, process_folder
from .db import BOOK, DATASET, Action, Book, LetterGroup, Line, Page, ReadingModel, ReadingModelDataset, Sample, now

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


class LibraryError(Exception):
    """A problem the user can fix (shown as a message, not as a crash)."""


class NotFound(LibraryError):
    """No book, page, group, sample or job with that id."""


class BookHasReviewError(LibraryError):
    """Capturing again would discard groups, labels or other manual work."""


class Cancelled(LibraryError):
    """The user cancelled a capture; nothing was stored."""


# How a book is written. It decides which readers suggest labels (Phase 2): Tesseract reads printed
# books; handwritten books learn from the books already labelled.
WRITING = ("handwritten", "printed")


# What a library row is (Phase 3, C20): a dataset (Training Data: cut, grouped, reviewed, labelled) or a book
# (Read Book: read). The word the screens and messages use for each.
KINDS = (DATASET, BOOK)
KIND_WORD = {DATASET: "dataset", BOOK: "book"}
UPLOAD_SUB = {DATASET: "datasets", BOOK: "books"}       # <uploads>/<sub>/<row folder> (C21)
PDF = ".pdf"


def _check_kind(kind: str) -> str:
    if kind not in KINDS:
        raise LibraryError(f"Kind must be one of: {', '.join(KINDS)}.")
    return kind


def _check_writing(writing: str) -> str:
    if writing not in WRITING:
        raise LibraryError(f"Writing must be one of: {', '.join(WRITING)}.")
    return writing


def default_library_dir() -> Path:
    return Path.home() / "Documents" / "Manuscript Letters"


def migrate(engine) -> None:
    """Create or update the database schema to the newest migration.

    Foreign keys are off while it runs: on SQLite, a migration that rebuilds a table (batch mode) drops
    the old one, and with foreign keys on that would delete every row pointing to it (all the lines and
    samples of the pages, for example). Every link is checked afterwards; a broken one stops with an
    error, and the migration is not kept."""
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")     # only possible outside a transaction
        connection.commit()
        try:
            with connection.begin():
                cfg.attributes["connection"] = connection
                command.upgrade(cfg, "head")
                broken = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
                if broken:
                    raise LibraryError(f"Updating the library database broke {len(broken)} links "
                                       f"(first: {broken[0]}); nothing was changed.")
        finally:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    return s[:40] or "book"


class LeftOut(frozenset):
    """Page ids a fold of Measure leaves out (Library.left_out, C24): the tested pages and the same pages in datasets."""


class Library:
    def __init__(self, root: Path):
        self.root = Path(root)
        try:
            (self.root / "books").mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise LibraryError(f"Cannot create the library folder {self.root}: {e}") from e
        self.engine = create_engine(f"sqlite:///{self.root / 'library.db'}")
        migrate(self.engine)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)
        self._folders: Dict[int, str] = {}                # book id -> its folder (never changes)

    def close(self) -> None:
        self.engine.dispose()

    @contextmanager
    def session(self) -> Iterator[Session]:
        """A unit of work: committed when the block ends, rolled back on an error."""
        with self._sessions() as s:
            with s.begin():
                yield s

    # ---- books -------------------------------------------------------------------------
    def book_dir(self, book: Book) -> Path:
        return self.root / "books" / book.folder

    def folder_of(self, book_id: int) -> Path:
        """The folder of a row by its id (cached: a row's folder never changes). A sample's files are in the
        folder of its own row, which since C20 may not be the row being read or trained (a book learns from
        its dataset's letters)."""
        if book_id not in self._folders:
            self._folders[book_id] = self.get_book(book_id).folder
        return self.root / "books" / self._folders[book_id]

    # ---- datasets and books (C20), reading models (C23) -----------------------------------------------
    def training_sources(self, book: Book) -> List[int]:
        """The rows whose reviewed Training Data letters (and labels) a row's reading learns from: the datasets of a
        book's reading model (C23; none yet: []), a dataset's own."""
        with self.session() as s:
            return self.sources_in(s, book)

    @staticmethod
    def sources_in(s: Session, book: Book) -> List[int]:
        """`training_sources` inside an open session."""
        if book.kind != BOOK:
            return [book.id]
        if book.reading_model_id is None:
            return []
        return list(s.scalars(select(ReadingModelDataset.dataset_id)
                              .where(ReadingModelDataset.model_id == book.reading_model_id)
                              .order_by(ReadingModelDataset.dataset_id)))

    def left_out(self, book_id: int, tested) -> "LeftOut":
        """What a fold of Measure leaves out (C24): the tested pages of the book (given by page id or file name) and
        every page of the book's datasets that is the same page, by its content (`sha256`), whatever its name.
        Already a LeftOut: returned as it is. Pages in no dataset need nothing more left out."""
        if isinstance(tested, LeftOut):
            return tested
        tested = list(tested or ())
        if not tested:
            return LeftOut()
        from .pages import NOT_PREPARED
        files = [t for t in tested if isinstance(t, str)]
        ids = [t for t in tested if not isinstance(t, str)]
        with self.session() as s:
            book = s.get(Book, book_id)
            if book is None:
                raise NotFound(f"No book with id {book_id}.")
            mine = s.execute(select(Page.id, Page.sha256).where(
                Page.book_id == book_id, Page.part == "read",
                Page.file.in_(files) | Page.id.in_(ids))).all()
            out = {pid for pid, _ in mine}
            shas = {h for _, h in mine if h}
            srcs = [x for x in self.sources_in(s, book) if x != book_id]
            if book.kind != BOOK:                         # a row holding both parts (before C20): its own pages
                srcs = [book_id]
            if shas and srcs:
                out |= set(s.scalars(select(Page.id).where(Page.book_id.in_(srcs), Page.part == "training",
                                                           Page.sha256.in_(shas), Page.status != NOT_PREPARED)))
        return LeftOut(out)

    def model_dir(self, book: Book) -> Path:
        """The folder of a book's reading model, <library>/models/<folder>/ (C23): its line-search reader, Measure
        results and caches. The reader of a book from before C23 is moved here from <book folder>/line-search/ the
        first time (a rename). A dataset (or a book without a model) keeps <row folder>/line-search/."""
        old = self.book_dir(book) / "line-search"
        if book.kind != BOOK or book.reading_model_id is None:
            return old
        with self.session() as s:
            m = s.get(ReadingModel, book.reading_model_id)
            folder = m.folder if m is not None else None
        if folder is None:
            return old
        out = self.root / "models" / folder
        if old.is_dir() and not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            old.rename(out)
        return out

    @staticmethod
    def _new_model(s: Session, book: Book, dataset_ids: List[int]) -> ReadingModel:
        """A reading model of the book's own, named and foldered like it, learning from `dataset_ids`."""
        m = ReadingModel(name=book.name, folder=book.folder)
        s.add(m)
        s.flush()
        for d in dict.fromkeys(dataset_ids):
            s.add(ReadingModelDataset(model_id=m.id, dataset_id=d))
        book.reading_model_id = m.id
        return m

    def set_book_datasets(self, book_id: int, dataset_ids: List[int]) -> List[int]:
        """The datasets a book's reading model learns from (C23, Reading setup); the datasets themselves are not
        changed. Any writing is allowed (the screen warns when it differs from the book's)."""
        with self.session() as s:
            book = s.get(Book, book_id)
            if book is None:
                raise NotFound(f"No book with id {book_id}.")
            self.need_kind(book, BOOK, "choosing datasets to learn from")
            for d in dataset_ids:
                row = s.get(Book, d)
                if row is None or row.kind != DATASET:
                    raise NotFound(f"No dataset with id {d}.")
            m = s.get(ReadingModel, book.reading_model_id) if book.reading_model_id else None
            if m is None:
                m = self._new_model(s, book, [])
            s.execute(delete(ReadingModelDataset).where(ReadingModelDataset.model_id == m.id))
            for d in dict.fromkeys(dataset_ids):
                s.add(ReadingModelDataset(model_id=m.id, dataset_id=d))
            book.updated_at = now()
        return self.training_sources(self.get_book(book_id))

    @staticmethod
    def need_kind(book: Book, kind: str, what: str) -> None:
        """Refuse `what` on a row of the other kind, so a row never holds both Training Data and Read Book."""
        if book.kind != kind:
            other = "a book's pages are read; Training Data is in a dataset" if book.kind == BOOK else \
                "a dataset's pages are cut, grouped and labelled; reading is done in a book"
            raise LibraryError(f"'{book.name}' is a {KIND_WORD[book.kind]}: {what} needs a {KIND_WORD[kind]} "
                               f"({other}).")

    def unsplit_books(self) -> List[Dict]:
        """Datasets that still hold Read Book pages (or a Read Book folder or PDF): libraries from before C20,
        until `split.split_library` separates them. The app does not open such a library."""
        with self.session() as s:
            rows = s.execute(select(Book.id, Book.name, func.count(Page.id))
                             .outerjoin(Page, (Page.book_id == Book.id) & (Page.part == "read"))
                             .where(Book.kind == DATASET).group_by(Book.id)).all()
            extra = {b.id for b in s.scalars(select(Book).where(Book.kind == DATASET,
                                                                (Book.read_dir != "") | (Book.read_pdf != "")))}
        return [{"id": i, "name": n, "read_pages": c} for i, n, c in rows if c or i in extra]

    # ---- the two parts of a book (C16a) ----------------------------------------------------
    def read_folder(self, book: Book) -> Optional[Path]:
        """Where the Read Book pages are: the images made from an uploaded PDF, or the chosen folder."""
        if book.read_pdf:
            return self.book_dir(book) / "read" / "pages"
        return Path(book.read_dir) if book.read_dir else None

    def part_folder(self, book: Book, part: str) -> Path:
        """The folder of a part's page files: the input folder for Training Data, the read folder."""
        if part == "training":
            if not book.input_dir:
                raise LibraryError("This book has no folder of Training Data page images yet: choose one in "
                                   "Pages & capture.")
            return Path(book.input_dir)
        folder = self.read_folder(book)
        if folder is None:
            raise LibraryError("This book has no Read Book pages yet: upload a PDF or choose a folder of images.")
        return folder

    def page_path(self, book: Book, page: Page) -> Path:
        """The image file of a page, in the folder it was captured from."""
        return self.part_folder(book, page.folder) / page.file

    @staticmethod
    def part_root(part: str) -> str:
        """Where a part's letters and lines are kept inside the book folder: the book folder itself for
        Training Data (as before the two parts), read/ for Read Book, so same-named pages never clash."""
        return "" if part == "training" else "read/"

    def _check_input_dir(self, input_dir: Path) -> str:
        input_dir = Path(input_dir).expanduser()
        if not input_dir.is_dir():
            raise LibraryError(f"Input folder does not exist or is not a folder: {input_dir}")
        if self.root.resolve() in [input_dir.resolve(), *input_dir.resolve().parents]:
            raise LibraryError("The input folder must not be inside the library folder.")
        return str(input_dir.resolve())

    def create_book(self, name: str, input_dir: Optional[Path] = None, cfg: Optional[Config] = None,
                    writing: str = "handwritten", kind: str = DATASET, dataset_id: Optional[int] = None) -> Book:
        """A new dataset (the default) or book (C20). A dataset's folder of Training Data page images may
        come later (`set_input_folder`); a book has none (its pages come with Prepare). `dataset_id`: the
        dataset a new book learns from."""
        name = name.strip()
        _check_writing(writing)
        _check_kind(kind)
        word = KIND_WORD[kind]
        if not name:
            raise LibraryError(f"A {word} needs a name.")
        if kind == BOOK and input_dir:
            raise LibraryError("A book has no Training Data folder: its pages are read. Make a dataset for that.")
        if kind == DATASET and dataset_id is not None:
            raise LibraryError("Only a book learns from datasets.")
        folder = self._check_input_dir(input_dir) if input_dir else ""
        settings = json.dumps(dataclasses.asdict(cfg or Config()))
        with self.session() as s:
            if s.scalar(select(Book.id).where(Book.name == name, Book.kind == kind)) is not None:
                raise LibraryError(f"A {word} named '{name}' already exists.")
            if dataset_id is not None:
                d = s.get(Book, dataset_id)
                if d is None or d.kind != DATASET:
                    raise NotFound(f"No dataset with id {dataset_id}.")
            book = Book(name=name, folder=uuid.uuid4().hex, input_dir=folder, settings=settings,
                        writing=writing, kind=kind)
            s.add(book)
            s.flush()
            book.folder = f"{book.id:04d}-{_slug(name)}"
            if kind == BOOK:                                # its reading model (C23)
                self._new_model(s, book, [dataset_id] if dataset_id is not None else [])
        self.book_dir(book).mkdir(parents=True, exist_ok=True)
        return book

    def set_input_folder(self, book_id: int, input_dir: Path) -> None:
        """The folder of the Training Data page images (only read, never changed). Pages captured from an
        earlier folder are looked for in the new one (Pages & capture lists the ones missing there)."""
        folder = self._check_input_dir(input_dir)
        with self.session() as s:
            b = s.get(Book, book_id)
            if b is None:
                raise NotFound(f"No book with id {book_id}.")
            self.need_kind(b, DATASET, "a folder of Training Data pages")
            b.input_dir, b.updated_at = folder, now()

    # ---- uploads (C21) -------------------------------------------------------------------------------
    # Uploaded pages are kept in the uploads folder (an app setting, main.uploads_dir): a dataset's in
    # <uploads>/datasets/<folder>/, a book's in <uploads>/books/<folder>/. That folder then is the dataset's
    # Training Data folder or the book's Read Book folder; the rule "not inside the library" does not apply to
    # it (lean plan, decision 5). A book's PDF is kept there too, its pages become images as before (import_pdf).
    def upload_dir(self, book: Book, uploads: Path) -> Path:
        return (Path(uploads).expanduser() / UPLOAD_SUB[book.kind] / book.folder).resolve()

    def _upload_into(self, book: Book, uploads: Path) -> Path:
        """Where uploaded pages of the row go: its upload folder, or for a book read from a PDF the folder of the
        PDF's page images in the book folder (C22: pages added to it)."""
        if book.kind == BOOK and book.read_pdf:
            return (self.book_dir(book) / "read" / "pages").resolve()
        return self.upload_dir(book, uploads)

    def _uses_other_folder(self, book: Book, folder: Path) -> str:
        """The row's pages' folder if they come from somewhere else than where uploads go, else ''."""
        if book.kind == DATASET:
            return book.input_dir if book.input_dir and Path(book.input_dir).resolve() != folder else ""
        if book.read_pdf:
            return ""
        return book.read_dir if book.read_dir and Path(book.read_dir).resolve() != folder else ""

    def upload_target(self, book_id: int, name: str, uploads: Path) -> Path:
        """Where an uploaded page image or PDF named `name` goes, after checking that it may: an image or a PDF,
        not uploaded already, and the row's pages not from a folder of their own (adding pages to those comes
        with the page manager, C22). A book takes images or one PDF, not both."""
        book = self.get_book(book_id)
        name = Path(name.replace("\\", "/")).name.strip()
        ext = Path(name).suffix.lower()
        if not name or name.startswith(".") or ext not in io_utils.SUPPORTED_EXTENSIONS | {PDF}:
            raise LibraryError(f"'{name}' is not a page image (jpg, png, tif, bmp) or a PDF.")
        folder = self._upload_into(book, uploads)
        other = self._uses_other_folder(book, folder)
        if other:
            raise LibraryError(f"The pages of '{book.name}' are in a folder of your own ({other}): add the page "
                               "images to that folder, and they show up as new pages.")
        if book.kind == BOOK and ext == PDF:
            with self.session() as s:
                n = s.scalar(select(func.count(Page.id)).where(Page.book_id == book_id, Page.part == "read")) or 0
            if n or book.read_dir or book.read_pdf:
                raise LibraryError(f"'{book.name}' has page images already; a PDF is uploaded into a new book.")
        target = folder / name
        if target.exists():
            raise LibraryError(f"'{name}' is uploaded already.")
        folder.mkdir(parents=True, exist_ok=True)
        return target

    def use_upload_folder(self, book_id: int, uploads: Path) -> None:
        """Make the row's upload folder its pages' folder (Training Data for a dataset, Read Book for a book)."""
        with self.session() as s:
            b = s.get(Book, book_id)
            if b is None:
                raise NotFound(f"No book with id {book_id}.")
            if b.kind == BOOK and b.read_pdf:
                return                                     # the pages were added to the PDF's page folder
            folder = str(self.upload_dir(b, uploads))
            if b.kind == DATASET:
                b.input_dir = folder
            else:
                b.read_dir, b.read_pdf = folder, ""
            b.updated_at = now()

    def upload_pdf_pages(self, book_id: int, pdf: Path, uploads: Path, progress: Optional[ProgressFn] = None,
                         cancel: Optional[Callable[[], bool]] = None) -> Dict:
        """A PDF uploaded into a dataset: its pages become images `<pdf name>-page-0001.jpg` … in the dataset's
        upload folder, beside the PDF (a book's PDF goes through import_pdf instead)."""
        from ..ocr.pdf import pdf_pages
        book = self.get_book(book_id)
        self.need_kind(book, DATASET, "PDF pages for Training Data")
        folder = self.upload_dir(book, uploads)
        tmp = folder / f".{Path(pdf).stem}.pages"
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            names = pdf_pages(pdf, tmp, dpi=self.book_config(book).pdf_dpi, progress=progress, cancel=cancel)
            if cancel and cancel():
                raise Cancelled("Cancelled; no page of the PDF was added.")
            final = [f"{Path(pdf).stem}-{n}" for n in names]
            taken = [n for n in final if (folder / n).exists()]
            if taken:
                raise LibraryError(f"{taken[0]} is in the dataset's upload folder already.")
            for n, f in zip(names, final):
                (tmp / n).rename(folder / f)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.use_upload_folder(book_id, uploads)
        return {"pages": len(final), "pdf": Path(pdf).name}

    def copy_pages(self, book_id: int, source: Path, uploads: Path, progress: Optional[ProgressFn] = None,
                   cancel: Optional[Callable[[], bool]] = None) -> Dict:
        """A dataset from a folder of page images, copied into its upload folder (the folder is only read).
        Refused before copying anything when a file of that name was uploaded already. A cancel keeps the
        copied pages."""
        from ..ocr.pdf import PageDone
        images, folder = self.copy_plan(book_id, source, uploads)
        folder.mkdir(parents=True, exist_ok=True)
        done = 0
        for i, p in enumerate(images, 1):
            if cancel and cancel():
                break
            part = folder / f".{p.name}.part"
            shutil.copy2(p, part)
            part.rename(folder / p.name)
            done = i
            if progress:
                progress(i, len(images), PageDone(p.name, "OK", "copied", 0.0))
        if done:
            self.use_upload_folder(book_id, uploads)
        return {"pages": done, "pages_left": len(images) - done}

    def copy_plan(self, book_id: int, source: Path, uploads: Path) -> Tuple[List[Path], Path]:
        """The images copy_pages would copy and where to, or LibraryError why it is refused."""
        book = self.get_book(book_id)
        self.need_kind(book, DATASET, "a folder of Training Data pages")
        source = Path(source).expanduser()
        if not source.is_dir():
            raise LibraryError(f"Folder does not exist or is not a folder: {source}")
        images, _ = io_utils.scan_folder(source)
        if not images:
            raise LibraryError(f"No page images (jpg, png, tif, bmp) in {source}.")
        folder = self.upload_dir(book, uploads)
        if source.resolve() == folder:
            raise LibraryError("That is the dataset's upload folder itself.")
        other = self._uses_other_folder(book, folder)
        if other:
            raise LibraryError(f"The pages of '{book.name}' come from {other}; copying more pages into it comes "
                               "with the page manager.")
        taken = [p.name for p in images if (folder / p.name).exists()]
        if taken:
            raise LibraryError(f"{len(taken)} of the images are uploaded already, for example {taken[0]}.")
        return images, folder

    def get_book(self, book_id: int) -> Book:
        with self.session() as s:
            book = s.get(Book, book_id)
            if book is None:
                raise NotFound(f"No book with id {book_id}.")
            return book

    def list_books(self, kind: Optional[str] = None) -> List[Dict]:
        """One summary per row (or per row of `kind`), most recently changed first. A dataset lists the books
        that learn from it (`used_by`); a book lists the datasets its reading model learns from (`datasets`, C23)."""
        with self.session() as s:
            q = select(Book).order_by(Book.updated_at.desc())
            books = s.scalars(q.where(Book.kind == _check_kind(kind)) if kind else q).all()
            names = dict(s.execute(select(Book.id, Book.name)).all())
            users: Dict[int, List[Dict]] = {}
            learns: Dict[int, List[Dict]] = {}
            for i, n, d in s.execute(select(Book.id, Book.name, ReadingModelDataset.dataset_id)
                                     .join(ReadingModelDataset, ReadingModelDataset.model_id == Book.reading_model_id)
                                     .order_by(Book.id, ReadingModelDataset.dataset_id)).all():
                users.setdefault(d, []).append({"id": i, "name": n})
                learns.setdefault(i, []).append({"id": d, "name": names.get(d, "")})
            out = []
            for b in books:
                def count(q):
                    return s.scalar(q) or 0
                out.append({
                    "id": b.id, "name": b.name, "kind": b.kind, "input_dir": b.input_dir, "writing": b.writing,
                    "datasets": learns.get(b.id, []), "used_by": users.get(b.id, []),
                    "reading_model_id": b.reading_model_id,
                    "read_dir": b.read_dir, "read_pdf": b.read_pdf, "reader_id": b.reader_id,
                    "pages": count(select(func.count(Page.id)).where(Page.book_id == b.id, Page.part == "training",
                                                                     Page.excluded.is_(False))),
                    "read_pages": count(select(func.count(Page.id)).where(Page.book_id == b.id, Page.part == "read",
                                                                          Page.excluded.is_(False))),
                    "reviewed": count(select(func.count(Sample.id)).join(LetterGroup, Sample.group_id == LetterGroup.id)
                                      .where(Sample.book_id == b.id, Sample.deleted.is_(False),
                                             LetterGroup.status != "auto")),
                    "samples": count(select(func.count(Sample.id)).where(Sample.book_id == b.id, Sample.part == "training",
                                                                         Sample.deleted.is_(False))),
                    "groups": count(select(func.count(LetterGroup.id)).where(LetterGroup.book_id == b.id)),
                    "labelled": count(select(func.count(LetterGroup.id)).where(LetterGroup.book_id == b.id,
                                                                               LetterGroup.label_dev != "")),
                    "unsure": count(select(func.count(Sample.id)).where(Sample.book_id == b.id, Sample.part == "training",
                                                                        Sample.group_id.is_(None),
                                                                        Sample.deleted.is_(False))),
                    "created_at": b.created_at, "updated_at": b.updated_at, "captured_at": b.captured_at,
                })
            return out

    def rename_book(self, book_id: int, name: str) -> None:
        name = name.strip()
        if not name:
            raise LibraryError("A name is needed.")
        with self.session() as s:
            book = s.get(Book, book_id)
            if book is None:
                raise NotFound(f"No book with id {book_id}.")
            if s.scalar(select(Book.id).where(Book.name == name, Book.kind == book.kind,
                                              Book.id != book_id)) is not None:
                raise LibraryError(f"A {KIND_WORD[book.kind]} named '{name}' already exists.")
            book.name = name
            if book.reading_model_id is not None:          # its own reading model is named like it (C23)
                m = s.get(ReadingModel, book.reading_model_id)
                if m is not None:
                    m.name = name

    def set_book_writing(self, book_id: int, writing: str) -> None:
        _check_writing(writing)
        with self.session() as s:
            book = s.get(Book, book_id)
            if book is None:
                raise NotFound(f"No book with id {book_id}.")
            book.writing = writing

    def delete_book(self, book_id: int, uploads: Optional[Path] = None) -> None:
        """Delete the book from the database and its folder in the library, and (with `uploads`) the pages
        uploaded into it (C21); never pages in a folder of their own."""
        with self.session() as s:
            book = s.get(Book, book_id)
            if book is None:
                raise NotFound(f"No book with id {book_id}.")
            folder = self.book_dir(book)
            uploaded = self.upload_dir(book, uploads) if uploads else None
            model = s.get(ReadingModel, book.reading_model_id) if book.reading_model_id else None
            model_folder = self.root / "models" / model.folder if model is not None else None
            if model is not None and not s.scalar(select(func.count(Book.id)).where(
                    Book.reading_model_id == model.id, Book.id != book_id)):
                s.delete(model)                            # its own model goes with it (C23)
            else:
                model_folder = None
            s.delete(book)
        books = (self.root / "books").resolve()
        if folder.exists() and folder.resolve().parent == books:
            shutil.rmtree(folder)
        if model_folder is not None and model_folder.is_dir():
            shutil.rmtree(model_folder)
        if uploaded and uploaded.is_dir() and uploaded.parent.parent == Path(uploads).expanduser().resolve():
            shutil.rmtree(uploaded)

    def set_book_config(self, book_id: int, cfg: Config) -> None:
        """New settings for the book's next capture or re-cut (what is in the book does not change)."""
        with self.session() as s:
            book = s.get(Book, book_id)
            if book is None:
                raise NotFound(f"No book with id {book_id}.")
            book.settings = json.dumps(dataclasses.asdict(cfg))

    def book_config(self, book: Book) -> Config:
        return load_config(None, **json.loads(book.settings))

    # ---- capture -------------------------------------------------------------------------
    def has_manual_work(self, book_id: int) -> bool:
        with self.session() as s:
            if s.scalar(select(func.count(Action.id)).where(Action.book_id == book_id)):
                return True
            # labels given at capture (C12c) stay "auto": they are not work done by hand
            if s.scalar(select(func.count(LetterGroup.id)).where(LetterGroup.book_id == book_id,
                                                                 (LetterGroup.status != "auto")
                                                                 | LetterGroup.locked)):
                return True
            return bool(s.scalar(select(func.count(Sample.id)).where(Sample.book_id == book_id,
                                                                     Sample.part == "training",
                                                                     Sample.source != "auto")))

    def _run(self, book: Book, progress, cancel, files=None, finish=True, summary=None, part="training",
             keep_done=False):
        """Run the pipeline on a part's pages into a work folder inside the book. Returns (results, work
        folder); the book's own files are untouched until `_install` moves the new ones in. A cancel
        throws the run away, unless `keep_done` (Read Book): then the pages finished so far are kept."""
        cfg = self.book_config(book)
        cfg.save_masks, cfg.write_groups = True, False
        cfg.bar_fix = book.writing == "printed"          # bars.py: not on handwriting
        work = self.book_dir(book) / (".work" if part == "training" else ".work-read")
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)
        try:
            results = process_folder(self.part_folder(book, part), work, cfg, progress, cancel,
                                     summary=summary, files=files, finish=finish)
        except io_utils.FolderError as e:
            shutil.rmtree(work, ignore_errors=True)
            raise LibraryError(str(e)) from e
        except BaseException:
            shutil.rmtree(work, ignore_errors=True)
            raise
        if cancel is not None and cancel() and not keep_done:   # stopped early: store nothing
            shutil.rmtree(work, ignore_errors=True)
            raise Cancelled("Cancelled; nothing was changed in the book.")
        return results, work

    def _install(self, book: Book, work: Path, results, replace_all: bool, part: str = "training") -> None:
        """Move the files of a finished run from the work folder into the book (its part's folder):
        everything (capture) or only the run's pages (add pages, cut a page again)."""
        out = self.book_dir(book) / self.part_root(part)
        out.mkdir(parents=True, exist_ok=True)
        if replace_all:
            for sub in ("letters", "lines"):
                if (out / sub).is_dir():
                    shutil.rmtree(out / sub)
            for name in ("letters", "lines", "report.csv", "samples.csv"):
                if (work / name).exists():
                    shutil.move(str(work / name), str(out / name))
        else:
            for r in results:
                stem = Path(r.file).stem
                old = out / "letters" / stem
                if old.is_dir():
                    shutil.rmtree(old)
                for f in (out / "lines").glob(f"{stem}_L[0-9][0-9].png") if (out / "lines").is_dir() else []:
                    f.unlink()
                (out / "letters").mkdir(exist_ok=True)
                (out / "lines").mkdir(exist_ok=True)
                if (work / "letters" / stem).is_dir():
                    shutil.move(str(work / "letters" / stem), str(old))
                for f in (work / "lines").glob(f"{stem}_L[0-9][0-9].png") if (work / "lines").is_dir() else []:
                    shutil.move(str(f), str(out / "lines" / f.name))
        shutil.rmtree(work, ignore_errors=True)

    def _store(self, s: Session, book: Book, results, group_ids: Optional[Dict[str, int]] = None,
               part: str = "training", folder_of: Optional[str] = None) -> Dict:
        """Store pages, lines and samples of pipeline results, in a part of the book. Samples join the
        groups named in their rows when `group_ids` maps those names to group ids; otherwise they are
        unsure (Training Data) or simply read (Read Book: never grouped)."""
        n_lines, n_samples = 0, 0
        where = folder_of or part                         # the folder the files are in (a moved page: the other)
        folder = self.part_folder(book, where)
        numbers = self._new_numbers(s, book.id, where, folder, [r.file for r in results])
        root = self.part_root(where)
        for r in results:
            page = Page(book_id=book.id, file=r.file, width=r.width, height=r.height, status=r.status,
                        message=r.message, line_spacing=r.line_spacing, seconds=r.seconds,
                        sha256=file_sha256(folder / r.file), part=part, folder=where,
                        number=numbers[r.file])
            s.add(page)
            s.flush()
            line_ids = {}
            for li in r.lines_info:
                line = Line(page_id=page.id, number=li["number"], x=li["x"], y=li["y"], w=li["w"],
                            h=li["h"], ink=li["ink"], image=root + li["image"])
                s.add(line)
                s.flush()
                line_ids[li["number"]] = line.id
                n_lines += 1
            if r.features is None or len(r.features) != len(r.samples):
                continue
            rows = []
            for row, fp in zip(r.samples, r.features):
                gid = (group_ids or {}).get(row.get("group_id", ""))
                dist = row.get("distance", "")
                rows.append({
                    "book_id": book.id, "page_id": page.id, "line_id": line_ids.get(row["line"]),
                    "line_number": row["line"], "pos": row["pos"], "x": row["x"], "y": row["y"],
                    "w": row["w"], "h": row["h"], "ink": row["ink"], "kind": row["kind"],
                    "pieces": row["pieces"], "rules": row["rules"], "image": root + row["image"],
                    "mask": root + row["mask"] if row.get("mask") else "", "fingerprint": fp.tobytes(),
                    "source": "auto", "deleted": False, "group_id": gid, "part": part,
                    "distance": float(dist) if (gid is not None and dist != "") else None, "created_at": now(),
                })
            if rows:
                s.execute(insert(Sample), rows)
                if part == "training":                    # Read Book is read later, by conversion (C16b)
                    Library._store_readings(s, book, page.id, r.samples)
            n_samples += len(rows)
        return {"lines": n_lines, "samples": n_samples}

    def _exclusion_rows(self, s: Session, book: Book, part: str, files: List[str]) -> None:
        """Rows for page files excluded before they are prepared or captured (C22, pages.py): no lines, no letters,
        so every step skips them, and the file is no longer new."""
        from .pages import NOT_PREPARED
        folder = self.part_folder(book, part)
        numbers = self._new_numbers(s, book.id, part, folder, files)
        for f in files:
            path = folder / f
            s.add(Page(book_id=book.id, file=f, part=part, folder=part, number=numbers[f], excluded=True,
                       status=NOT_PREPARED, sha256=file_sha256(path) if path.is_file() else ""))

    @staticmethod
    def _new_numbers(s: Session, book_id: int, where: str, folder: Path, files: List[str]) -> Dict[str, int]:
        """The places of new pages (C22): their place in the folder (by file name, as before) while the pages there
        are still in that order; once the order was changed by hand (or pages deleted), after the last page."""
        order = {p.name: i for i, p in enumerate(io_utils.scan_folder(folder)[0], 1)} if folder.is_dir() else {}
        have = dict(s.execute(select(Page.file, Page.number).where(Page.book_id == book_id,
                                                                  Page.folder == where)).all())
        if all(order.get(f) == n for f, n in have.items()):
            return {f: order.get(f, 0) for f in files}
        last = max(have.values(), default=0)
        ranked = sorted(files, key=lambda f: (order.get(f, len(order) + 1), io_utils.natural_key(Path(f))))
        return {f: last + i for i, f in enumerate(ranked, 1)}

    @staticmethod
    def _store_readings(s: Session, book: Book, page_id: int, rows: List[Dict]) -> None:
        """Letters cut by Tesseract's reading (C12c) bring their text: it is stored as their reading in
        the book's Tesseract run (made if there is none), so suggestions are there at once. Texts that
        are not labels (punctuation Tesseract read) are left out."""
        texts = {(row["line"], row["pos"]): row.get("text", "") for row in rows if row.get("text")}
        if not texts:
            return
        from ..mapping import LabelError, canonical_label, mapping_for
        from .db import OcrReading, OcrRun
        run = s.scalars(select(OcrRun).where(OcrRun.book_id == book.id, OcrRun.engine == "tesseract")
                        .order_by(OcrRun.id.desc())).first()
        cfg = load_config(None, **json.loads(book.settings))
        if run is None:
            run = OcrRun(book_id=book.id, engine="tesseract", finished_at=now(),
                         settings=json.dumps({"source": "capture", "ocr_langs": cfg.ocr_langs}))
            s.add(run)
            s.flush()
        mapping = mapping_for(cfg)
        for sid, line, pos in s.execute(select(Sample.id, Sample.line_number, Sample.pos)
                                        .where(Sample.page_id == page_id)):
            text = texts.get((line, pos))
            if not text:
                continue
            try:
                text = canonical_label(text, mapping, words=True)
            except LabelError:
                continue
            s.add(OcrReading(run_id=run.id, sample_id=sid, text_dev=text, confidence=95.0, alternatives="[]",
                             overlap=1.0))

    def capture(self, book_id: int, progress: Optional[ProgressFn] = None,
                cancel: Optional[Callable[[], bool]] = None, force: bool = False) -> Dict:
        """Cut and group all pages of the book's input folder and store the result. Replaces the
        book's earlier results; refused when the book holds manual work, unless `force`."""
        book = self.get_book(book_id)
        self.need_kind(book, DATASET, "capturing Training Data")
        if not force and self.has_manual_work(book_id):
            raise BookHasReviewError(f"'{book.name}' has groups, labels or other changes made by hand; "
                                     "capturing again would discard them.")
        summary: Dict = {}
        with self.session() as s:                               # excluded pages are not captured, but kept (C22)
            excluded = set(s.scalars(select(Page.file).where(Page.book_id == book_id, Page.part == "training",
                                                             Page.excluded.is_(True))))
        files = None
        if excluded:
            files = [p.name for p in io_utils.scan_folder(self.part_folder(book, "training"))[0]
                     if p.name not in excluded]
        results, work = self._run(book, progress, cancel, summary=summary, files=files)
        self._install(book, work, results, replace_all=True)
        with self.session() as s:
            for table in (Action, LetterGroup):                 # Read Book pages stay (C16a)
                s.execute(delete(table).where(table.book_id == book_id))
            for table in (Sample, Page):                        # lines go with their pages
                s.execute(delete(table).where(table.book_id == book_id, table.part == "training"))
            from .db import OcrRun                              # readings of the old samples are gone
            s.execute(delete(OcrRun).where(OcrRun.book_id == book_id))
            group_ids: Dict[str, int] = {}
            for r in results:
                for row in r.samples:
                    gid = row.get("group_id", "")
                    if gid and gid != UNSURE and gid not in group_ids:
                        g = LetterGroup(book_id=book_id, code=gid, kind=row["kind"])
                        s.add(g)
                        s.flush()
                        group_ids[gid] = g.id
            stored = self._store(s, book, results, group_ids)
            if excluded:
                s.flush()
                self._exclusion_rows(s, book, "training", sorted(excluded))
            labels = self._auto_label(s, book)
            b = s.get(Book, book_id)
            b.captured_at = b.updated_at = now()
        return {"pages": len(results), "pages_ok": sum(r.status == "OK" for r in results),
                "lines": stored["lines"], "samples": stored["samples"],
                "groups": len(group_ids) - labels.get("merged_groups", 0) + labels.get("groups_split", 0),
                "unsure": summary.get("unsure", 0) - labels.get("placed", 0), **labels}

    def _auto_label(self, s: Session, book: Book) -> Dict:
        """Books cut by Tesseract's reading get their labels at capture (suggest.auto_label)."""
        cfg = self.book_config(book)
        if cfg.cut_method != "tesseract":
            return {}
        s.flush()
        from .suggest import auto_label
        return auto_label(s, s.get(Book, book.id), cfg)

    def add_new_pages(self, book_id: int, progress: Optional[ProgressFn] = None,
                      cancel: Optional[Callable[[], bool]] = None) -> Dict:
        """Cut only the image files of the input folder that are not in the book yet. Their samples
        are stored as unsure; the review screens show a suggested group for each. Nothing that
        is already in the book changes."""
        book = self.get_book(book_id)
        self.need_kind(book, DATASET, "adding Training Data pages")
        with self.session() as s:
            known = set(s.scalars(select(Page.file).where(Page.book_id == book_id, Page.folder == "training")))
        images, _ = io_utils.scan_folder(self.part_folder(book, "training"))
        new = [p.name for p in images if p.name not in known]
        if not new:
            return {"pages": 0, "lines": 0, "samples": 0, "files": []}
        results, work = self._run(book, progress, cancel, files=new, finish=False)
        self._install(book, work, results, replace_all=False)
        with self.session() as s:
            stored = self._store(s, book, results)
            labels = self._auto_label(s, book)
            s.get(Book, book_id).updated_at = now()
        return {"pages": len(results), **stored, **labels, "files": [r.file for r in results]}

    def page_has_manual_work(self, page_id: int) -> bool:
        """Samples of the page that were changed by hand, are in a reviewed, labelled or locked
        group, or appear in the undo history."""
        with self.session() as s:
            page = s.get(Page, page_id)
            if page is None:
                raise NotFound(f"No page with id {page_id}.")
            samples = s.scalars(select(Sample).where(Sample.page_id == page_id)).all()
            ids = {smp.id for smp in samples}
            for smp in samples:
                if smp.source != "auto":
                    return True
                g = smp.group
                if g is not None and (g.status != "auto" or g.locked or g.label_dev):
                    return True
            for payload in s.scalars(select(Action.payload).where(Action.book_id == page.book_id)):
                data = json.loads(payload)
                touched = {int(k) for k in {**data.get("samples_before", {}), **data.get("samples_after", {})}}
                if touched & ids:
                    return True
        return False

    def recut_page(self, book_id: int, page_id: int, progress: Optional[ProgressFn] = None,
                   cancel: Optional[Callable[[], bool]] = None, force: bool = False) -> Dict:
        """Cut one page again (for example after changing settings). Only that page's samples are
        replaced; the new ones are unsure. Refused when the page holds manual work, unless `force`,
        which also clears the book's undo history (it may refer to the replaced samples)."""
        from .centres import recompute
        book = self.get_book(book_id)
        with self.session() as s:
            page = s.get(Page, page_id)
            if page is None or page.book_id != book_id:
                raise NotFound(f"No page with id {page_id} in this book.")
            file, part, where, number = page.file, page.part, page.folder, page.number
            if page.excluded:
                raise LibraryError(f"Page {file} is excluded: include it first to cut it again.")
        if self.page_has_manual_work(page_id) and not force:
            raise BookHasReviewError(f"Page {file} has samples that were reviewed or changed by hand; "
                                     "cutting it again would replace them.")
        results, work = self._run(book, progress, cancel, files=[file], finish=False, part=where)
        self._install(book, work, results, replace_all=False, part=where)
        with self.session() as s:
            touched = set(s.scalars(select(Sample.group_id).where(Sample.page_id == page_id,
                                                                  Sample.group_id.is_not(None))))
            s.execute(delete(Sample).where(Sample.page_id == page_id))
            s.execute(delete(Page).where(Page.id == page_id))
            if force:
                s.execute(delete(Action).where(Action.book_id == book_id))
            s.flush()
            stored = self._store(s, book, results, part=part, folder_of=where)
            for p in s.scalars(select(Page).where(Page.book_id == book_id, Page.folder == where, Page.file == file)):
                p.number = number                          # the page keeps its place (C22)
            recompute(s, touched)
            for gid in touched:                           # groups left empty and never reviewed go
                g = s.get(LetterGroup, gid)                # (labels given at capture are "auto" too)
                if g is not None and g.status == "auto" and not g.locked and \
                        not s.scalar(select(func.count(Sample.id)).where(Sample.group_id == gid,
                                                                       Sample.deleted.is_(False))):
                    s.delete(g)
            labels = self._auto_label(s, book) if part == "training" else {}
            s.get(Book, book_id).updated_at = now()
        return {"pages": len(results), **stored, **labels, "files": [file]}

    # ---- Read Book (C16a) -----------------------------------------------------------------
    READ_BATCH = 4                                        # pages cut and stored at a time: a cancel keeps the rest

    def capture_read(self, book_id: int, progress: Optional[ProgressFn] = None,
                     cancel: Optional[Callable[[], bool]] = None) -> Dict:
        """Cut the Read Book pages that are not cut yet, a few at a time, so a cancelled or interrupted
        capture keeps the pages already done and the next one continues. Read Book letters are never
        grouped, and Training Data is not touched."""
        book = self.get_book(book_id)
        self.need_kind(book, BOOK, "preparing pages for reading")
        folder = self.part_folder(book, "read")
        if not folder.is_dir():
            raise LibraryError(f"The Read Book folder is missing: {folder}")
        with self.session() as s:
            known = set(s.scalars(select(Page.file).where(Page.book_id == book_id, Page.folder == "read")))
        images, _ = io_utils.scan_folder(folder)
        todo = [p.name for p in images if p.name not in known]
        total, done = len(todo), 0
        stored = {"lines": 0, "samples": 0}
        for i in range(0, total, self.READ_BATCH):
            batch = todo[i:i + self.READ_BATCH]

            def step(n, _total, r, base=done):
                if progress:
                    progress(base + n, total, r)
            results, work = self._run(book, step, cancel, files=batch, finish=False, part="read", keep_done=True)
            self._install(book, work, results, replace_all=False, part="read")
            if results:
                with self.session() as s:
                    got = self._store(s, book, results, part="read")
                    s.get(Book, book_id).updated_at = now()
                stored = {k: stored[k] + got[k] for k in stored}
            done += len(results)
            if cancel and cancel():
                break
        return {"pages": done, "pages_left": total - done, **stored}

    def import_pdf(self, book_id: int, pdf: Path, progress: Optional[ProgressFn] = None,
                   cancel: Optional[Callable[[], bool]] = None, force: bool = False) -> Dict:
        """Read Book from a PDF: every page becomes an image in the book's read/pages/ folder (the PDF is
        only read). Replaces earlier Read Book pages; refused when there are some, unless `force`."""
        from ..ocr.pdf import pdf_pages
        book = self.get_book(book_id)
        self.need_kind(book, BOOK, "a PDF to read")
        pdf = Path(pdf).expanduser()
        if not pdf.is_file():
            raise LibraryError(f"No such PDF file: {pdf}")
        self._clear_read(book_id, force)
        out = self.book_dir(book) / "read" / "pages"
        tmp = out.with_name("pages.new")
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            files = pdf_pages(pdf, tmp, dpi=self.book_config(book).pdf_dpi, progress=progress, cancel=cancel)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        if cancel and cancel():
            shutil.rmtree(tmp, ignore_errors=True)
            raise Cancelled("Cancelled; the Read Book pages were not changed.")
        shutil.rmtree(out, ignore_errors=True)
        tmp.rename(out)
        with self.session() as s:
            b = s.get(Book, book_id)
            b.read_pdf, b.read_dir, b.updated_at = pdf.name, "", now()
        return {"pages": len(files), "pdf": pdf.name}

    def set_read_folder(self, book_id: int, folder: Path, force: bool = False) -> None:
        """Read Book from a folder of images (only read, never changed). Replaces earlier Read Book pages;
        refused when there are some, unless `force`."""
        folder = Path(folder).expanduser()
        if not folder.is_dir():
            raise LibraryError(f"Folder does not exist or is not a folder: {folder}")
        if self.root.resolve() in [folder.resolve(), *folder.resolve().parents]:
            raise LibraryError("The Read Book folder must not be inside the library folder.")
        book = self.get_book(book_id)
        self.need_kind(book, BOOK, "a folder of pages to read")
        if book.read_dir and Path(book.read_dir).resolve() == folder.resolve() and not book.read_pdf:
            return
        self._clear_read(book_id, force)
        shutil.rmtree(self.book_dir(book) / "read" / "pages", ignore_errors=True)
        with self.session() as s:
            b = s.get(Book, book_id)
            b.read_dir, b.read_pdf, b.updated_at = str(folder.resolve()), "", now()

    def _clear_read(self, book_id: int, force: bool) -> None:
        """Remove the Read Book pages (their letters and files), before other pages take their place."""
        book = self.get_book(book_id)
        with self.session() as s:
            n = s.scalar(select(func.count(Page.id)).where(Page.book_id == book_id, Page.folder == "read")) or 0
            if n and not force:
                raise BookHasReviewError(f"The book already has {n} Read Book pages; new pages replace them "
                                         "(their text too).")
            s.execute(delete(Sample).where(Sample.book_id == book_id,
                                           Sample.page_id.in_(select(Page.id).where(Page.book_id == book_id,
                                                                                    Page.folder == "read"))))
            s.execute(delete(Page).where(Page.book_id == book_id, Page.folder == "read"))
        root = self.book_dir(book) / "read"
        for sub in ("letters", "lines"):
            shutil.rmtree(root / sub, ignore_errors=True)

    def set_page_part(self, page_id: int, part: str, force: bool = False) -> Dict:
        """Moving a page between Training Data and Read Book (C16a) is refused since C20: the two parts are
        two rows, a dataset (it only trains) and a book (it only reads). Copying a book's page into a
        dataset is for later (docs/implementation_plan_phase3_lean.md, section 6)."""
        if part not in ("training", "read"):
            raise LibraryError("A page is used for training or for reading.")
        with self.session() as s:
            page = s.get(Page, page_id)
            if page is None:
                raise NotFound(f"No page with id {page_id}.")
            if page.part == part:
                return {"page": page_id, "part": part, "samples": 0}
        raise LibraryError("Datasets and books are separate since Phase 3: a book's page cannot be used for "
                           "training here, nor a dataset's page for reading. Copying pages between them comes "
                           "later.")

    def check_pages(self, book_id: int, part: str = "training") -> List[Dict]:
        """Pages of a part whose file is missing or changed since capture, and new image files."""
        book = self.get_book(book_id)
        folder = self.read_folder(book) if part == "read" else (Path(book.input_dir) if book.input_dir else None)
        problems = []
        if folder is None:
            return problems
        with self.session() as s:
            pages = s.scalars(select(Page).where(Page.book_id == book_id, Page.folder == part)).all()
        known = set()
        for p in pages:
            known.add(p.file)
            path = folder / p.file
            if not path.is_file():
                problems.append({"file": p.file, "problem": "missing"})
            elif p.sha256 and file_sha256(path) != p.sha256:
                problems.append({"file": p.file, "problem": "changed"})
        if folder.is_dir():
            images, _ = io_utils.scan_folder(folder)
            problems += [{"file": i.name, "problem": "new"} for i in images if i.name not in known]
        return problems

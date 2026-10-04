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
from typing import Callable, Dict, Iterator, List, Optional

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, delete, func, insert, select
from sqlalchemy.orm import Session, sessionmaker

from .. import io_utils
from ..config import Config, load_config
from ..grouping import UNSURE
from ..pipeline import ProgressFn, process_folder
from .db import Action, Book, LetterGroup, Line, Page, Sample, now

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


class LibraryError(Exception):
    """A problem the user can fix (shown as a message, not as a crash)."""


class BookHasReviewError(LibraryError):
    """Capturing again would discard groups, labels or other manual work."""


def default_library_dir() -> Path:
    return Path.home() / "Documents" / "Manuscript Letters"


def migrate(engine) -> None:
    """Create or update the database schema to the newest migration."""
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    return s[:40] or "book"


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

    def create_book(self, name: str, input_dir: Path, cfg: Optional[Config] = None) -> Book:
        name = name.strip()
        if not name:
            raise LibraryError("A book needs a name.")
        input_dir = Path(input_dir)
        if not input_dir.is_dir():
            raise LibraryError(f"Input folder does not exist or is not a folder: {input_dir}")
        if self.root.resolve() in [input_dir.resolve(), *input_dir.resolve().parents]:
            raise LibraryError("The input folder must not be inside the library folder.")
        settings = json.dumps(dataclasses.asdict(cfg or Config()))
        with self.session() as s:
            if s.scalar(select(Book.id).where(Book.name == name)) is not None:
                raise LibraryError(f"A book named '{name}' already exists.")
            book = Book(name=name, folder=uuid.uuid4().hex, input_dir=str(input_dir.resolve()), settings=settings)
            s.add(book)
            s.flush()
            book.folder = f"{book.id:04d}-{_slug(name)}"
        self.book_dir(book).mkdir(parents=True, exist_ok=True)
        return book

    def get_book(self, book_id: int) -> Book:
        with self.session() as s:
            book = s.get(Book, book_id)
            if book is None:
                raise LibraryError(f"No book with id {book_id}.")
            return book

    def list_books(self) -> List[Dict]:
        """One summary per book, most recently changed first."""
        with self.session() as s:
            books = s.scalars(select(Book).order_by(Book.updated_at.desc())).all()
            out = []
            for b in books:
                def count(q):
                    return s.scalar(q) or 0
                out.append({
                    "id": b.id, "name": b.name, "input_dir": b.input_dir,
                    "pages": count(select(func.count(Page.id)).where(Page.book_id == b.id)),
                    "samples": count(select(func.count(Sample.id)).where(Sample.book_id == b.id,
                                                                         Sample.deleted.is_(False))),
                    "groups": count(select(func.count(LetterGroup.id)).where(LetterGroup.book_id == b.id)),
                    "labelled": count(select(func.count(LetterGroup.id)).where(LetterGroup.book_id == b.id,
                                                                               LetterGroup.label_dev != "")),
                    "unsure": count(select(func.count(Sample.id)).where(Sample.book_id == b.id,
                                                                        Sample.group_id.is_(None),
                                                                        Sample.deleted.is_(False))),
                    "created_at": b.created_at, "updated_at": b.updated_at, "captured_at": b.captured_at,
                })
            return out

    def rename_book(self, book_id: int, name: str) -> None:
        name = name.strip()
        if not name:
            raise LibraryError("A book needs a name.")
        with self.session() as s:
            if s.scalar(select(Book.id).where(Book.name == name, Book.id != book_id)) is not None:
                raise LibraryError(f"A book named '{name}' already exists.")
            book = s.get(Book, book_id)
            if book is None:
                raise LibraryError(f"No book with id {book_id}.")
            book.name = name

    def delete_book(self, book_id: int) -> None:
        """Delete the book from the database and its folder in the library (never the input pages)."""
        with self.session() as s:
            book = s.get(Book, book_id)
            if book is None:
                raise LibraryError(f"No book with id {book_id}.")
            folder = self.book_dir(book)
            s.delete(book)
        books = (self.root / "books").resolve()
        if folder.exists() and folder.resolve().parent == books:
            shutil.rmtree(folder)

    def book_config(self, book: Book) -> Config:
        return load_config(None, **json.loads(book.settings))

    # ---- capture -------------------------------------------------------------------------
    def has_manual_work(self, book_id: int) -> bool:
        with self.session() as s:
            if s.scalar(select(func.count(Action.id)).where(Action.book_id == book_id)):
                return True
            if s.scalar(select(func.count(LetterGroup.id)).where(LetterGroup.book_id == book_id,
                                                                 (LetterGroup.status != "auto")
                                                                 | LetterGroup.locked
                                                                 | (LetterGroup.label_dev != ""))):
                return True
            return bool(s.scalar(select(func.count(Sample.id)).where(Sample.book_id == book_id,
                                                                     Sample.source != "auto")))

    def capture(self, book_id: int, progress: Optional[ProgressFn] = None,
                cancel: Optional[Callable[[], bool]] = None, force: bool = False) -> Dict:
        """Cut and group all pages of the book's input folder and store the result."""
        book = self.get_book(book_id)
        if not force and self.has_manual_work(book_id):
            raise BookHasReviewError(f"'{book.name}' has groups, labels or other changes made by hand; "
                                     "capturing again would discard them.")
        cfg = self.book_config(book)
        cfg.save_masks, cfg.write_groups = True, False
        out = self.book_dir(book)
        for sub in ("letters", "lines"):                  # results of an earlier capture
            if (out / sub).is_dir():
                shutil.rmtree(out / sub)
        summary: Dict = {}
        try:
            results = process_folder(Path(book.input_dir), out, cfg, progress, cancel, summary=summary)
        except io_utils.FolderError as e:
            raise LibraryError(str(e)) from e

        with self.session() as s:
            for table in (Action, Sample, LetterGroup, Page):   # lines go with their pages
                s.execute(delete(table).where(table.book_id == book_id))
            n_lines = 0
            line_ids: Dict = {}
            page_ids: Dict[str, int] = {}
            for r in results:
                page = Page(book_id=book_id, file=r.file, width=r.width, height=r.height, status=r.status,
                            message=r.message, line_spacing=r.line_spacing, seconds=r.seconds,
                            sha256=file_sha256(Path(book.input_dir) / r.file))
                s.add(page)
                s.flush()
                page_ids[r.file] = page.id
                for li in r.lines_info:
                    line = Line(page_id=page.id, number=li["number"], x=li["x"], y=li["y"], w=li["w"],
                                h=li["h"], ink=li["ink"], image=li["image"])
                    s.add(line)
                    s.flush()
                    line_ids[(r.file, li["number"])] = line.id
                    n_lines += 1
            group_ids: Dict[str, int] = {}
            for r in results:
                for row in r.samples:
                    gid = row.get("group_id", "")
                    if gid and gid != UNSURE and gid not in group_ids:
                        g = LetterGroup(book_id=book_id, code=gid, kind=row["kind"])
                        s.add(g)
                        s.flush()
                        group_ids[gid] = g.id
            rows = []
            for r in results:
                if r.features is None or len(r.features) != len(r.samples):
                    continue
                for row, fp in zip(r.samples, r.features):
                    gid = row.get("group_id", "")
                    dist = row.get("distance", "")
                    rows.append({
                        "book_id": book_id, "page_id": page_ids[r.file],
                        "line_id": line_ids.get((r.file, row["line"])), "line_number": row["line"],
                        "pos": row["pos"], "x": row["x"], "y": row["y"], "w": row["w"], "h": row["h"],
                        "ink": row["ink"], "kind": row["kind"], "pieces": row["pieces"], "rules": row["rules"],
                        "image": row["image"], "mask": row.get("mask", ""), "fingerprint": fp.tobytes(),
                        "source": "auto", "deleted": False, "group_id": group_ids.get(gid),
                        "distance": float(dist) if dist != "" else None, "created_at": now(),
                    })
            if rows:
                s.execute(insert(Sample), rows)
            b = s.get(Book, book_id)
            b.captured_at = now()
            b.updated_at = now()
        return {"pages": len(results), "pages_ok": sum(r.status == "OK" for r in results), "lines": n_lines,
                "samples": len(rows), "groups": len(group_ids), "unsure": summary.get("unsure", 0)}

    def check_pages(self, book_id: int) -> List[Dict]:
        """Pages whose input file is missing or changed since capture, and new image files."""
        book = self.get_book(book_id)
        folder = Path(book.input_dir)
        problems = []
        with self.session() as s:
            pages = s.scalars(select(Page).where(Page.book_id == book_id)).all()
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

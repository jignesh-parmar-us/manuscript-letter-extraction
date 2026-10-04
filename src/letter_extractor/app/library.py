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


class NotFound(LibraryError):
    """No book, page, group, sample or job with that id."""


class BookHasReviewError(LibraryError):
    """Capturing again would discard groups, labels or other manual work."""


class Cancelled(LibraryError):
    """The user cancelled a capture; nothing was stored."""


# How a book is written. It decides which readers suggest labels (Phase 2): Tesseract reads printed
# books; handwritten books learn from the books already labelled.
WRITING = ("handwritten", "printed")


def _check_writing(writing: str) -> str:
    if writing not in WRITING:
        raise LibraryError(f"Writing must be one of: {', '.join(WRITING)}.")
    return writing


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

    def create_book(self, name: str, input_dir: Path, cfg: Optional[Config] = None,
                    writing: str = "handwritten") -> Book:
        name = name.strip()
        _check_writing(writing)
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
            book = Book(name=name, folder=uuid.uuid4().hex, input_dir=str(input_dir.resolve()), settings=settings,
                        writing=writing)
            s.add(book)
            s.flush()
            book.folder = f"{book.id:04d}-{_slug(name)}"
        self.book_dir(book).mkdir(parents=True, exist_ok=True)
        return book

    def get_book(self, book_id: int) -> Book:
        with self.session() as s:
            book = s.get(Book, book_id)
            if book is None:
                raise NotFound(f"No book with id {book_id}.")
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
                    "id": b.id, "name": b.name, "input_dir": b.input_dir, "writing": b.writing,
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
                raise NotFound(f"No book with id {book_id}.")
            book.name = name

    def set_book_writing(self, book_id: int, writing: str) -> None:
        _check_writing(writing)
        with self.session() as s:
            book = s.get(Book, book_id)
            if book is None:
                raise NotFound(f"No book with id {book_id}.")
            book.writing = writing

    def delete_book(self, book_id: int) -> None:
        """Delete the book from the database and its folder in the library (never the input pages)."""
        with self.session() as s:
            book = s.get(Book, book_id)
            if book is None:
                raise NotFound(f"No book with id {book_id}.")
            folder = self.book_dir(book)
            s.delete(book)
        books = (self.root / "books").resolve()
        if folder.exists() and folder.resolve().parent == books:
            shutil.rmtree(folder)

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
            if s.scalar(select(func.count(LetterGroup.id)).where(LetterGroup.book_id == book_id,
                                                                 (LetterGroup.status != "auto")
                                                                 | LetterGroup.locked
                                                                 | (LetterGroup.label_dev != ""))):
                return True
            return bool(s.scalar(select(func.count(Sample.id)).where(Sample.book_id == book_id,
                                                                     Sample.source != "auto")))

    def _run(self, book: Book, progress, cancel, files=None, finish=True, summary=None):
        """Run the pipeline into a work folder inside the book. Returns (results, work folder); the
        book's own files are untouched until `_install` moves the new ones in."""
        cfg = self.book_config(book)
        cfg.save_masks, cfg.write_groups = True, False
        work = self.book_dir(book) / ".work"
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)
        try:
            results = process_folder(Path(book.input_dir), work, cfg, progress, cancel,
                                     summary=summary, files=files, finish=finish)
        except io_utils.FolderError as e:
            shutil.rmtree(work, ignore_errors=True)
            raise LibraryError(str(e)) from e
        except BaseException:
            shutil.rmtree(work, ignore_errors=True)
            raise
        if cancel is not None and cancel():               # stopped early: store nothing
            shutil.rmtree(work, ignore_errors=True)
            raise Cancelled("Cancelled; nothing was changed in the book.")
        return results, work

    def _install(self, book: Book, work: Path, results, replace_all: bool) -> None:
        """Move the files of a finished run from the work folder into the book: everything (capture)
        or only the run's pages (add pages, cut a page again)."""
        out = self.book_dir(book)
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

    @staticmethod
    def _store(s: Session, book: Book, results, group_ids: Optional[Dict[str, int]] = None) -> Dict:
        """Store pages, lines and samples of pipeline results. Samples join the groups named in their
        rows when `group_ids` maps those names to group ids; otherwise they are unsure."""
        n_lines, n_samples = 0, 0
        for r in results:
            page = Page(book_id=book.id, file=r.file, width=r.width, height=r.height, status=r.status,
                        message=r.message, line_spacing=r.line_spacing, seconds=r.seconds,
                        sha256=file_sha256(Path(book.input_dir) / r.file))
            s.add(page)
            s.flush()
            line_ids = {}
            for li in r.lines_info:
                line = Line(page_id=page.id, number=li["number"], x=li["x"], y=li["y"], w=li["w"],
                            h=li["h"], ink=li["ink"], image=li["image"])
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
                    "pieces": row["pieces"], "rules": row["rules"], "image": row["image"],
                    "mask": row.get("mask", ""), "fingerprint": fp.tobytes(), "source": "auto",
                    "deleted": False, "group_id": gid,
                    "distance": float(dist) if (gid is not None and dist != "") else None, "created_at": now(),
                })
            if rows:
                s.execute(insert(Sample), rows)
            n_samples += len(rows)
        return {"lines": n_lines, "samples": n_samples}

    def capture(self, book_id: int, progress: Optional[ProgressFn] = None,
                cancel: Optional[Callable[[], bool]] = None, force: bool = False) -> Dict:
        """Cut and group all pages of the book's input folder and store the result. Replaces the
        book's earlier results; refused when the book holds manual work, unless `force`."""
        book = self.get_book(book_id)
        if not force and self.has_manual_work(book_id):
            raise BookHasReviewError(f"'{book.name}' has groups, labels or other changes made by hand; "
                                     "capturing again would discard them.")
        summary: Dict = {}
        results, work = self._run(book, progress, cancel, summary=summary)
        self._install(book, work, results, replace_all=True)
        with self.session() as s:
            for table in (Action, Sample, LetterGroup, Page):   # lines go with their pages
                s.execute(delete(table).where(table.book_id == book_id))
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
            b = s.get(Book, book_id)
            b.captured_at = b.updated_at = now()
        return {"pages": len(results), "pages_ok": sum(r.status == "OK" for r in results),
                "lines": stored["lines"], "samples": stored["samples"], "groups": len(group_ids),
                "unsure": summary.get("unsure", 0)}

    def add_new_pages(self, book_id: int, progress: Optional[ProgressFn] = None,
                      cancel: Optional[Callable[[], bool]] = None) -> Dict:
        """Cut only the image files of the input folder that are not in the book yet. Their samples
        are stored as unsure; the review screens show a suggested group for each. Nothing that
        is already in the book changes."""
        book = self.get_book(book_id)
        with self.session() as s:
            known = set(s.scalars(select(Page.file).where(Page.book_id == book_id)))
        images, _ = io_utils.scan_folder(Path(book.input_dir))
        new = [p.name for p in images if p.name not in known]
        if not new:
            return {"pages": 0, "lines": 0, "samples": 0, "files": []}
        results, work = self._run(book, progress, cancel, files=new, finish=False)
        self._install(book, work, results, replace_all=False)
        with self.session() as s:
            stored = self._store(s, book, results)
            s.get(Book, book_id).updated_at = now()
        return {"pages": len(results), **stored, "files": [r.file for r in results]}

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
            file = page.file
        if self.page_has_manual_work(page_id) and not force:
            raise BookHasReviewError(f"Page {file} has samples that were reviewed or changed by hand; "
                                     "cutting it again would replace them.")
        results, work = self._run(book, progress, cancel, files=[file], finish=False)
        self._install(book, work, results, replace_all=False)
        with self.session() as s:
            touched = set(s.scalars(select(Sample.group_id).where(Sample.page_id == page_id,
                                                                  Sample.group_id.is_not(None))))
            s.execute(delete(Sample).where(Sample.page_id == page_id))
            s.execute(delete(Page).where(Page.id == page_id))
            if force:
                s.execute(delete(Action).where(Action.book_id == book_id))
            s.flush()
            stored = self._store(s, book, results)
            recompute(s, touched)
            for gid in touched:                           # groups left empty and never reviewed go
                g = s.get(LetterGroup, gid)
                if g is not None and not g.label_dev and g.status == "auto" and not g.locked and \
                        not s.scalar(select(func.count(Sample.id)).where(Sample.group_id == gid,
                                                                       Sample.deleted.is_(False))):
                    s.delete(g)
            s.get(Book, book_id).updated_at = now()
        return {"pages": len(results), **stored, "files": [file]}

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

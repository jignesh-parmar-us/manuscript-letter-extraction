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

    # ---- the two parts of a book (C16a) ----------------------------------------------------
    def read_folder(self, book: Book) -> Optional[Path]:
        """Where the Read Book pages are: the images made from an uploaded PDF, or the chosen folder."""
        if book.read_pdf:
            return self.book_dir(book) / "read" / "pages"
        return Path(book.read_dir) if book.read_dir else None

    def part_folder(self, book: Book, part: str) -> Path:
        """The folder of a part's page files: the input folder for Training Data, the read folder."""
        if part == "training":
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
                    "read_dir": b.read_dir, "read_pdf": b.read_pdf, "reader_id": b.reader_id,
                    "pages": count(select(func.count(Page.id)).where(Page.book_id == b.id, Page.part == "training")),
                    "read_pages": count(select(func.count(Page.id)).where(Page.book_id == b.id, Page.part == "read")),
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
        order = {p.name: i for i, p in enumerate(io_utils.scan_folder(folder)[0], 1)}
        root = self.part_root(where)
        for r in results:
            page = Page(book_id=book.id, file=r.file, width=r.width, height=r.height, status=r.status,
                        message=r.message, line_spacing=r.line_spacing, seconds=r.seconds,
                        sha256=file_sha256(folder / r.file), part=part, folder=where,
                        number=order.get(r.file, 0))
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
        if not force and self.has_manual_work(book_id):
            raise BookHasReviewError(f"'{book.name}' has groups, labels or other changes made by hand; "
                                     "capturing again would discard them.")
        summary: Dict = {}
        results, work = self._run(book, progress, cancel, summary=summary)
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
        with self.session() as s:
            known = set(s.scalars(select(Page.file).where(Page.book_id == book_id, Page.folder == "training")))
        images, _ = io_utils.scan_folder(Path(book.input_dir))
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
            file, part, where = page.file, page.part, page.folder
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
        """Move a page to the other part. To Training Data: its letters become unsure there, with a
        suggested group each (as "Add new pages"). To Read Book: its letters leave their groups; refused
        when the page holds manual work, unless `force`. The page's files stay where they are."""
        from .centres import recompute
        if part not in ("training", "read"):
            raise LibraryError("A page is used for training or for reading.")
        with self.session() as s:
            page = s.get(Page, page_id)
            if page is None:
                raise NotFound(f"No page with id {page_id}.")
            if page.part == part:
                return {"page": page_id, "part": part, "samples": 0}
        if part == "read" and self.page_has_manual_work(page_id) and not force:
            raise BookHasReviewError("This page has letters that were reviewed or changed by hand; using it "
                                     "for reading takes them out of their groups.")
        with self.session() as s:
            page = s.get(Page, page_id)
            smps = s.scalars(select(Sample).where(Sample.page_id == page_id)).all()
            touched = {x.group_id for x in smps if x.group_id is not None}
            for x in smps:
                x.part, x.group_id, x.distance = part, None, None
            page.part = part
            s.flush()
            recompute(s, touched)
            for gid in touched:                           # groups left empty and never reviewed go
                g = s.get(LetterGroup, gid)
                if g is not None and g.status == "auto" and not g.locked and \
                        not s.scalar(select(func.count(Sample.id)).where(Sample.group_id == gid,
                                                                       Sample.deleted.is_(False))):
                    s.delete(g)
            book = s.get(Book, page.book_id)
            book.updated_at = now()
            return {"page": page_id, "part": part, "samples": len(smps)}

    def check_pages(self, book_id: int, part: str = "training") -> List[Dict]:
        """Pages of a part whose file is missing or changed since capture, and new image files."""
        book = self.get_book(book_id)
        folder = self.read_folder(book) if part == "read" else Path(book.input_dir)
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

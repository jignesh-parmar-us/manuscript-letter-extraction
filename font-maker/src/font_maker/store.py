"""The library as Font Maker sees it (F0): `library.db` opened read-only, and Font Maker's own `fonts/` folder.

Font Maker never writes to the database: it is opened with SQLite's `mode=ro`, so a write is refused by
SQLite itself. It does not use the reading app's `Library()`, because that runs the database migrations.
Instead it checks the schema version and stops when it is not the one it knows (SCHEMA), rather than
reading tables whose layout may have changed. Both apps can have the library open at the same time (WAL).
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, List

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from letter_extractor.app.db import Book, LetterGroup, Sample
from letter_extractor.ocr.aksharas import split_aksharas

SCHEMA = "0015"                     # the reading app's newest migration that Font Maker was written for


class StoreError(Exception):
    """A problem the user can fix (shown as a message, not as a crash)."""


class Store:
    def __init__(self, root: Path):
        self.root = Path(root).expanduser()
        self.db_path = self.root / "library.db"
        if not self.db_path.is_file():
            raise StoreError(f"No library in {self.root}: library.db is missing. Open the folder in the "
                             "reading app first, or start Font Maker with --library.")
        uri = self.db_path.resolve().as_uri() + "?mode=ro"
        self.engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True,
                                                                                check_same_thread=False))
        self.schema = self._schema()
        if self.schema != SCHEMA:
            self.engine.dispose()
            raise StoreError(f"The library's database is version {self.schema or 'unknown'}, Font Maker knows "
                             f"version {SCHEMA}. Update Font Maker (store.SCHEMA) after checking the tables it reads.")

    def _schema(self) -> str:
        with self.engine.connect() as c:
            try:
                row = c.execute(text("SELECT version_num FROM alembic_version")).first()
            except Exception:
                return ""
        return row[0] if row else ""

    @property
    def fonts_dir(self) -> Path:
        """Font Maker's folder in the library (created when the first font project is made, F1)."""
        return self.root / "fonts"

    @contextmanager
    def session(self) -> Iterator[Session]:
        with Session(self.engine) as s:
            yield s

    def book_count(self) -> int:
        with self.session() as s:
            return s.scalar(select(func.count(Book.id))) or 0

    def sources(self) -> List[Dict]:
        """The books a font can be made from, with their groups counted per status (F1).

        `usable` counts, per status, the groups that can become a glyph: they have a label of exactly one
        akshara. A label of several aksharas (a cut error such as ખાખા) cannot, and neither can a group
        with no label (every `reviewed` group)."""
        with self.session() as s:
            books = s.execute(select(Book.id, Book.name, Book.writing).order_by(Book.id)).all()
            groups = s.execute(select(LetterGroup.book_id, LetterGroup.status, LetterGroup.label_dev)).all()
            samples = dict(s.execute(select(Sample.book_id, func.count(Sample.id))
                                     .where(Sample.deleted.is_(False), Sample.group_id.is_not(None))
                                     .group_by(Sample.book_id)).all())
        out = {b.id: {"id": b.id, "name": b.name, "writing": b.writing, "samples": samples.get(b.id, 0),
                      "groups": {"auto": 0, "reviewed": 0, "labelled": 0},
                      "usable": {"auto": 0, "labelled": 0}} for b in books}
        for book_id, status, label in groups:
            book = out.get(book_id)
            if book is None or status not in book["groups"]:
                continue
            book["groups"][status] += 1
            if status in book["usable"] and label and len(split_aksharas(label)) == 1:
                book["usable"][status] += 1
        return list(out.values())

    def close(self) -> None:
        self.engine.dispose()

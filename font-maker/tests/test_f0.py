"""F0: the library is opened read-only, the API needs the token, and the reading app never imports Font Maker.

Light on purpose (font-maker/docs/FONT_PLAN.md, section 1): a temporary library with one book, no real data.
"""
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from letter_extractor.app.db import BOOK, Base, Book
from font_maker.api import create_app
from font_maker.store import SCHEMA, Store, StoreError

REPO = Path(__file__).resolve().parents[2]


def make_library(root: Path, schema: str = SCHEMA) -> Path:
    engine = create_engine(f"sqlite:///{root / 'library.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        c.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        c.execute(text("INSERT INTO alembic_version VALUES (:v)"), {"v": schema})
    with Session(engine) as s:
        s.add(Book(name="Test book", folder="0001-test-book", input_dir="/nowhere"))
        s.commit()
    engine.dispose()
    return root


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_and_refuses_writes(self):
        store = Store(make_library(self.root))
        self.assertEqual(store.book_count(), 1)
        self.assertEqual(store.fonts_dir, self.root / "fonts")
        with store.engine.connect() as c, self.assertRaises(Exception) as caught:
            c.execute(text("DELETE FROM book"))
        self.assertIn("readonly", str(caught.exception).replace("-", "").replace(" ", ""))
        store.close()
        with sqlite3.connect(self.root / "library.db") as c:      # still there
            self.assertEqual(c.execute("SELECT COUNT(*) FROM book").fetchone()[0], 1)

    def test_sources_are_datasets_only(self):
        engine = create_engine(f"sqlite:///{make_library(self.root) / 'library.db'}")
        with Session(engine) as s:                                # a Read Book row has no groups
            s.add(Book(name="Read", kind=BOOK, folder="0002-read", input_dir=""))
            s.commit()
        engine.dispose()
        store = Store(self.root)
        self.assertEqual(([b["name"] for b in store.sources()], store.book_count()), (["Test book"], 1))
        store.close()

    def test_missing_library_and_other_schema(self):
        with self.assertRaises(StoreError):
            Store(self.root)
        make_library(self.root, schema="0099")
        with self.assertRaisesRegex(StoreError, "0099"):
            Store(self.root)


class ApiTest(unittest.TestCase):
    def test_token_and_screen(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_library(Path(tmp))
            static = root / "static"
            static.mkdir()
            (static / "index.html").write_text("<html><head></head><body></body></html>", encoding="utf-8")
            store = Store(root)
            client = TestClient(create_app(store, "secret", static_dir=static))
            self.assertEqual(client.get("/api/app").status_code, 401)
            info = client.get("/api/app", headers={"X-Token": "secret"}).json()
            self.assertEqual((info["name"], info["books"]), ("Font Maker", 1))
            self.assertIn('window.__TOKEN__ = "secret"', client.get("/").text)
            store.close()


class SeparationTest(unittest.TestCase):
    def test_reading_app_does_not_import_font_maker(self):
        pattern = re.compile(r"^\s*(from|import)\s+font_maker\b", re.M)   # fontTools is allowed: the reading app's own fonts
        for folder in ("src", "tests"):
            for path in (REPO / folder).rglob("*.py"):
                self.assertIsNone(pattern.search(path.read_text(encoding="utf-8")), str(path))


if __name__ == "__main__":
    unittest.main()

"""F1: the books with their groups per status, and creating / renaming / deleting font projects.

Light on purpose: one temporary library with one book and four groups.
"""
import hashlib
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from letter_extractor.app.db import LetterGroup, Sample
from font_maker.api import create_app
from font_maker.store import Store
from test_f0 import make_library

H = {"X-Token": "t"}


def add_groups(root: Path) -> None:
    engine = create_engine(f"sqlite:///{root / 'library.db'}")
    with Session(engine) as s:
        for code, status, label in (("g1", "labelled", "क"), ("g2", "labelled", "खाखा"),   # one akshara / two
                                    ("g3", "reviewed", ""), ("g4", "auto", "का")):
            g = LetterGroup(book_id=1, code=code, status=status, label_dev=label)
            s.add(g)
            s.flush()
            s.add(Sample(book_id=1, image=f"letters/{code}.png", group_id=g.id))
        s.commit()
    engine.dispose()


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FontProjectsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_library(Path(self.tmp.name))
        add_groups(self.root)
        self.store = Store(self.root)
        self.client = TestClient(create_app(self.store, "t", static_dir=self.root / "no-screen"))

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_sources_count_groups_per_status(self):
        (book,) = self.client.get("/api/sources", headers=H).json()
        self.assertEqual(book["groups"], {"auto": 1, "reviewed": 1, "labelled": 2})
        self.assertEqual(book["usable"], {"auto": 1, "labelled": 1})        # खाखा cannot be a glyph
        self.assertEqual(book["samples"], 4)

    def test_create_rename_delete_touch_only_fonts(self):
        db = self.root / "library.db"
        before = checksum(db)
        c = self.client
        font = c.post("/api/fonts", json={"name": " Test  book ", "book_id": 1}, headers=H).json()
        self.assertEqual((font["id"], font["name"], font["sources"], font["statuses"], font["builds"]),
                         ("f0001", "Test book", [1], ["labelled"], 0))
        self.assertTrue((self.root / "fonts" / "f0001" / "font.json").is_file())

        for body in ({"name": "test BOOK", "book_id": 1},                     # same name
                     {"name": "Other", "book_id": 9},                         # no such book
                     {"name": "Other", "book_id": 1, "statuses": ["reviewed"]},
                     {"name": "  ", "book_id": 1}):
            self.assertEqual(c.post("/api/fonts", json=body, headers=H).status_code, 400, body)

        changed = c.patch("/api/fonts/f0001", json={"name": "Vachnamrut 1944", "statuses": ["auto", "labelled"]},
                          headers=H).json()
        self.assertEqual((changed["name"], changed["statuses"]), ("Vachnamrut 1944", ["labelled", "auto"]))
        self.assertEqual([f["name"] for f in c.get("/api/fonts", headers=H).json()], ["Vachnamrut 1944"])

        self.assertEqual(c.delete("/api/fonts/f0001", headers=H).status_code, 204)
        self.assertEqual(c.get("/api/fonts/f0001", headers=H).status_code, 404)
        self.assertEqual(c.delete("/api/fonts/..", headers=H).status_code, 404)
        self.assertEqual(list((self.root / "fonts").iterdir()), [])
        self.assertEqual(checksum(db), before)


if __name__ == "__main__":
    unittest.main()

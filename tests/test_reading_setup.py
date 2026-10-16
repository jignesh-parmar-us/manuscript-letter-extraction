"""C23: a book's reading model learns from the datasets it chooses (Reading setup)."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from test_book_parts import page_image                             # noqa: E402
from alembic import command                                         # noqa: E402
from alembic.config import Config as AlembicConfig                 # noqa: E402
from fastapi.testclient import TestClient                           # noqa: E402
from letter_extractor.app import linesearch                        # noqa: E402
from letter_extractor.app.api import create_app                    # noqa: E402
from letter_extractor.app.db import LetterGroup, ReadingModel, ReadingModelDataset   # noqa: E402
from letter_extractor.app.dictionary import _labels_of, book_model  # noqa: E402
from letter_extractor.app.library import MIGRATIONS, Library, NotFound   # noqa: E402
from letter_extractor.app.main import AppContext                   # noqa: E402
from sqlalchemy import select, text                                 # noqa: E402


class ReadingSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.lib = Library(self.tmp / "lib")
        self.sets = []
        for name, label in (("A", "क"), ("B", "ख")):
            folder = self.tmp / name
            folder.mkdir()
            page_image().save(folder / "p1.png")
            d = self.lib.create_book(name, folder, writing="printed").id
            self.lib.capture(d)
            with self.lib.session() as s:
                for g in s.scalars(select(LetterGroup).where(LetterGroup.book_id == d)):
                    g.label_dev, g.status = label, "reviewed"
            self.sets.append(d)
        self.book = self.lib.create_book("Book", writing="printed", kind="book", dataset_id=self.sets[0]).id

    def tearDown(self):
        self.lib.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def book_row(self):
        return self.lib.get_book(self.book)

    def test_a_new_book_has_its_own_model_learning_from_its_dataset(self):
        with self.lib.session() as s:
            m = s.get(ReadingModel, self.book_row().reading_model_id)
            self.assertEqual((m.name, m.folder), ("Book", self.book_row().folder))
        self.assertEqual(self.lib.training_sources(self.book_row()), [self.sets[0]])
        self.assertEqual(self.lib.training_sources(self.lib.get_book(self.sets[1])), [self.sets[1]])

    def test_the_model_learns_the_labels_of_every_chosen_dataset(self):
        with self.lib.session() as s:
            one = _labels_of(s, self.book_row())
        self.assertTrue(one and all(set(x) <= {"क"} for x in one))
        self.lib.set_book_datasets(self.book, self.sets)
        with self.lib.session() as s:
            both = _labels_of(s, self.book_row())
        self.assertEqual(len(both), len(one) * 2)
        self.assertIn("ख", "".join(both))
        self.assertGreater(len(book_model(self.lib, self.book)), 0)
        self.lib.set_book_datasets(self.book, [])
        with self.lib.session() as s:
            self.assertEqual(_labels_of(s, self.book_row()), [])
        with self.assertRaises(NotFound):                                   # a book is not a dataset
            self.lib.set_book_datasets(self.book, [self.book])

    def test_the_reader_is_out_of_date_when_the_datasets_change(self):
        folder = self.lib.model_dir(self.book_row())
        folder.mkdir(parents=True)
        with self.lib.session() as s:
            sig = linesearch._signature(s, self.book_row())
        (folder / "meta.json").write_text(json.dumps({"letters": 1, "labels": 1, "trained_at": "x", "seconds": 1,
                                                      "signature": sig}), encoding="utf-8")
        self.assertFalse(linesearch.line_reader_info(self.lib, self.book)["changed"])
        self.lib.set_book_datasets(self.book, self.sets)
        self.assertTrue(linesearch.line_reader_info(self.lib, self.book)["changed"])

    def test_a_reader_from_before_moves_into_the_model_folder(self):
        old = self.lib.book_dir(self.book_row()) / "line-search"
        old.mkdir(parents=True)
        (old / "meta.json").write_text("{}", encoding="utf-8")
        new = self.lib.model_dir(self.book_row())
        self.assertEqual(new, self.lib.root / "models" / self.book_row().folder)
        self.assertTrue((new / "meta.json").is_file())
        self.assertFalse(old.exists())
        self.assertEqual(self.lib.model_dir(self.lib.get_book(self.sets[0])),        # a dataset keeps its own
                         self.lib.book_dir(self.lib.get_book(self.sets[0])) / "line-search")

    def test_deleting_the_book_deletes_its_model_deleting_a_dataset_leaves_it(self):
        self.lib.set_book_datasets(self.book, self.sets)
        self.lib.delete_book(self.sets[1])
        self.assertEqual(self.lib.training_sources(self.book_row()), [self.sets[0]])
        folder = self.lib.model_dir(self.book_row())
        folder.mkdir(parents=True)
        self.lib.delete_book(self.book)
        self.assertFalse(folder.exists())
        with self.lib.session() as s:
            self.assertEqual(s.scalars(select(ReadingModel)).all(), [])
            self.assertEqual(s.scalars(select(ReadingModelDataset)).all(), [])

    def test_the_list_says_who_learns_from_what(self):
        self.lib.set_book_datasets(self.book, self.sets)
        rows = {r["id"]: r for r in self.lib.list_books()}
        self.assertEqual([d["name"] for d in rows[self.book]["datasets"]], ["A", "B"])
        self.assertEqual(rows[self.sets[1]]["used_by"], [{"id": self.book, "name": "Book"}])

    def test_the_routes(self):
        client = TestClient(create_app(self.lib, "", AppContext(settings_file=self.tmp / "settings.json")))
        got = client.get(f"/api/books/{self.book}/reading-setup").json()
        self.assertEqual([d["id"] for d in got["datasets"]], [self.sets[0]])
        self.assertEqual([d["id"] for d in got["others"]], [self.sets[1]])
        self.assertIsNone(got["reader"])
        got = client.put(f"/api/books/{self.book}/datasets", json={"dataset_ids": self.sets}).json()
        self.assertEqual([d["id"] for d in got["datasets"]], self.sets)
        self.assertEqual(got["others"], [])
        self.assertEqual(client.put(f"/api/books/{self.book}/datasets", json={"dataset_ids": [999]}).status_code, 404)
        self.assertEqual(client.get(f"/api/books/{self.sets[0]}/reading-setup").status_code, 400)


class MigrationTests(unittest.TestCase):
    def test_a_books_dataset_becomes_its_reading_model(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            lib = Library(tmp / "lib")
            d = lib.create_book("D", writing="printed").id
            b = lib.create_book("B", writing="printed", kind="book", dataset_id=d).id
            lone = lib.create_book("Lone", writing="printed", kind="book").id
            cfg = AlembicConfig()
            cfg.set_main_option("script_location", str(MIGRATIONS))
            with lib.engine.connect() as conn:                               # back to C22: one linked dataset
                conn.exec_driver_sql("PRAGMA foreign_keys=OFF")              # as migrate() does
                conn.commit()
                cfg.attributes["connection"] = conn
                command.downgrade(cfg, "0018")
                self.assertEqual(conn.execute(text("SELECT read_dataset_id FROM book WHERE id = :b"),
                                              {"b": b}).scalar(), d)
                conn.execute(text("UPDATE book SET read_dataset_id = NULL WHERE id = :b"), {"b": lone})
                conn.commit()
            lib.close()
            lib = Library(tmp / "lib")                                       # and up again, as an old library would
            self.assertEqual(lib.training_sources(lib.get_book(b)), [d])
            self.assertEqual(lib.training_sources(lib.get_book(lone)), [])
            with lib.session() as s:
                names = sorted(s.scalars(select(ReadingModel.name)))
            self.assertEqual(names, ["B", "Lone"])
            lib.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

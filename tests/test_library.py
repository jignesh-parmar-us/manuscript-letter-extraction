"""C5a: library, database and capturing a book."""
import hashlib
import shutil
import sys
import tempfile
import unittest
from datetime import timezone
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import synthetic                                                    # noqa: E402
from letter_extractor.app.db import Action, Base, Book, LetterGroup, Line, Page, Sample   # noqa: E402
from letter_extractor.app.library import (BookHasReviewError, Library, LibraryError,       # noqa: E402
                                          file_sha256)
from letter_extractor.config import Config                          # noqa: E402
from letter_extractor.features import fingerprint_size              # noqa: E402
from sqlalchemy import func, select                                 # noqa: E402

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def _hashes(folder: Path):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}


class LibraryTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.inp = self.tmp / "pages"
        self.inp.mkdir()
        self.lib = Library(self.tmp / "My Library")

    def tearDown(self):
        self.lib.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _add_page(self, name="p1.png", seed_lines=3):
        rgb, _ = synthetic.make_letters_page(n_lines=seed_lines)
        Image.fromarray(rgb).save(self.inp / name)


class SchemaTests(LibraryTestCase):
    def test_migration_matches_the_models(self):
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        with self.lib.engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
        self.assertEqual(diff, [])

    def test_reopening_runs_no_new_migration_and_keeps_data(self):
        self.lib.create_book("A", self.inp)
        self.lib.close()
        self.lib = Library(self.tmp / "My Library")
        self.assertEqual([b["name"] for b in self.lib.list_books()], ["A"])

    def test_times_are_utc(self):
        book = self.lib.create_book("A", self.inp)
        self.assertEqual(self.lib.get_book(book.id).created_at.tzinfo, timezone.utc)


class BookTests(LibraryTestCase):
    def test_create_list_rename_delete(self):
        a = self.lib.create_book("Book A", self.inp)
        b = self.lib.create_book("ગુજરાતી પોથી", self.inp)
        self.assertTrue(self.lib.book_dir(a).is_dir())
        self.assertEqual({x["name"] for x in self.lib.list_books()}, {"Book A", "ગુજરાતી પોથી"})
        self.lib.rename_book(a.id, "Book A2")
        self.assertEqual(self.lib.get_book(a.id).name, "Book A2")
        folder = self.lib.book_dir(b)
        self.lib.delete_book(b.id)
        self.assertFalse(folder.exists())
        self.assertEqual([x["name"] for x in self.lib.list_books()], ["Book A2"])
        self.assertTrue(self.inp.is_dir(), "the input folder is never deleted")

    def test_bad_input(self):
        with self.assertRaises(LibraryError):
            self.lib.create_book("", self.inp)
        with self.assertRaises(LibraryError):
            self.lib.create_book("X", self.tmp / "missing")
        with self.assertRaises(LibraryError):
            self.lib.create_book("X", self.lib.root / "books")
        self.lib.create_book("X", self.inp)
        with self.assertRaises(LibraryError):
            self.lib.create_book("X", self.inp)
        with self.assertRaises(LibraryError):
            self.lib.get_book(999)

    def test_book_keeps_its_settings(self):
        cfg = Config()
        cfg.group_distance = 0.6
        cfg.red.min_break_px = 3
        book = self.lib.create_book("A", self.inp, cfg)
        back = self.lib.book_config(self.lib.get_book(book.id))
        self.assertEqual((back.group_distance, back.red.min_break_px), (0.6, 3))


class CaptureTests(LibraryTestCase):
    def test_capture_stores_everything(self):
        self._add_page("p1.png")
        self._add_page("p2.png")
        (self.inp / "notes.txt").write_text("not an image", encoding="utf-8")
        before = _hashes(self.inp)
        book = self.lib.create_book("Synthetic", self.inp)
        result = self.lib.capture(book.id)
        self.assertEqual((result["pages"], result["lines"]), (2, 6))
        self.assertEqual(_hashes(self.inp), before, "input pages must never change")
        with self.lib.session() as s:
            samples = s.scalars(select(Sample).where(Sample.book_id == book.id)).all()
            self.assertEqual(len(samples), result["samples"])
            self.assertEqual(s.scalar(select(func.count(Line.id))), 6)
            pages = s.scalars(select(Page)).all()
            self.assertEqual({p.file: p.sha256 for p in pages},
                             {f: file_sha256(self.inp / f) for f in ("p1.png", "p2.png")})
            folder = self.lib.book_dir(book)
            dim = fingerprint_size(self.lib.book_config(book))
            for smp in samples:
                self.assertTrue((folder / smp.image).is_file())
                mask = np.asarray(Image.open(folder / smp.mask)) > 0
                self.assertEqual(mask.shape, (smp.h, smp.w))
                self.assertEqual(np.frombuffer(smp.fingerprint, np.float32).size, dim)
                self.assertIsNotNone(smp.line_id)
            grouped = [smp for smp in samples if smp.group_id is not None]
            self.assertEqual(len(samples) - len(grouped), result["unsure"])
            self.assertEqual(s.scalar(select(func.count(LetterGroup.id))), result["groups"])
            for g in s.scalars(select(LetterGroup)).all():
                self.assertGreaterEqual(len(g.samples), 2)
                self.assertEqual(len({smp.kind for smp in g.samples}), 1)
        self.assertFalse((self.lib.book_dir(book) / "groups").exists(), "groups live in the database")

    def test_capture_again_replaces_automatic_results(self):
        self._add_page()
        book = self.lib.create_book("A", self.inp)
        first = self.lib.capture(book.id)
        second = self.lib.capture(book.id)
        self.assertEqual(first, second)
        with self.lib.session() as s:
            self.assertEqual(s.scalar(select(func.count(Sample.id))), first["samples"])
            self.assertEqual(s.scalar(select(func.count(Page.id))), 1)

    def test_capture_refuses_to_discard_manual_work(self):
        self._add_page()
        book = self.lib.create_book("A", self.inp)
        self.lib.capture(book.id)
        with self.lib.session() as s:
            g = s.scalars(select(LetterGroup)).first()
            g.label_dev = "क"
            s.add(Action(book_id=book.id, kind="label", payload="{}"))
        self.assertTrue(self.lib.has_manual_work(book.id))
        with self.assertRaises(BookHasReviewError):
            self.lib.capture(book.id)
        self.lib.capture(book.id, force=True)
        self.assertFalse(self.lib.has_manual_work(book.id))

    def test_check_pages_reports_missing_changed_and_new(self):
        self._add_page("p1.png")
        self._add_page("p2.png")
        book = self.lib.create_book("A", self.inp)
        self.lib.capture(book.id)
        self.assertEqual(self.lib.check_pages(book.id), [])
        (self.inp / "p1.png").unlink()
        self._add_page("p2.png", seed_lines=4)
        self._add_page("p3.png")
        problems = {p["file"]: p["problem"] for p in self.lib.check_pages(book.id)}
        self.assertEqual(problems, {"p1.png": "missing", "p2.png": "changed", "p3.png": "new"})

    def test_deleting_a_book_removes_its_rows(self):
        self._add_page()
        book = self.lib.create_book("A", self.inp)
        self.lib.capture(book.id)
        self.lib.delete_book(book.id)
        with self.lib.session() as s:
            for table in (Book, Page, Line, Sample, LetterGroup):
                self.assertEqual(s.scalar(select(func.count(table.id))), 0, table.__name__)


@unittest.skipUnless((SAMPLES / "page1.jpg").is_file(), "sample pages not present")
class SampleBookTests(unittest.TestCase):
    def test_sample_pages_as_a_book(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            lib = Library(tmp / "lib")
            book = lib.create_book("Samples", SAMPLES)
            result = lib.capture(book.id)
            self.assertEqual((result["pages"], result["lines"]), (2, 22))
            self.assertTrue(800 <= result["samples"] <= 900, result)
            self.assertTrue(40 <= result["groups"] <= 70, result)
            summary = lib.list_books()[0]
            self.assertEqual((summary["samples"], summary["groups"], summary["unsure"]),
                             (result["samples"], result["groups"], result["unsure"]))
            lib.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

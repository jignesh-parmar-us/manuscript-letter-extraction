"""C20: splitting a library from before Phase 3 into datasets and books (split.py), and what a book learns from its
dataset afterwards: the same letters, labels and checked lines as the one row before, so the numbers do not change."""
import json
import shutil
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import appbook                                                      # noqa: E402
from letter_extractor.app import linesearch, split                  # noqa: E402
from letter_extractor.app.db import (BOOK, DATASET, Action, Book, LetterGroup, Line, LineTruth, Page, Sample,   # noqa: E402
                                     WordList)
from letter_extractor.app.dictionary import book_model, book_model_without   # noqa: E402
from letter_extractor.app.library import LibraryError                # noqa: E402
from letter_extractor.app.main import unsplit_message                # noqa: E402
from letter_extractor.app.samples import split_sample                # noqa: E402
from sqlalchemy import func, select                                 # noqa: E402

LABELS = ("क", "ख", "ग", "घ", "च", "छ")


def legacy_read_book(lib, book_id: int, folder: Path) -> None:
    """Give a row Read Book pages as before C20, when one row held both parts (the library now refuses it)."""
    with lib.session() as s:
        s.get(Book, book_id).kind = BOOK
    lib.set_read_folder(book_id, folder)
    lib.capture_read(book_id)
    with lib.session() as s:
        s.get(Book, book_id).kind = DATASET


class SplitTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.lib, self.row, pages = appbook.fresh_copy()
        with self.lib.session() as s:                                   # reviewed, labelled groups to learn from
            rows = s.execute(select(LetterGroup.id).join(Sample, Sample.group_id == LetterGroup.id)
                             .where(LetterGroup.book_id == self.row, Sample.line_id.is_not(None))
                             .group_by(LetterGroup.id).order_by(func.count(Sample.id).desc())).all()
            for (gid,), label in zip(rows[:len(LABELS)], LABELS):
                g = s.get(LetterGroup, gid)
                g.label_dev, g.status = label, "labelled"
        self.read = self.tmp / "read-pages"                             # the same pages, as the Read Book
        shutil.copytree(pages, self.read)
        legacy_read_book(self.lib, self.row, self.read)
        with self.lib.session() as s:
            self.read_page = s.scalar(select(Page.id).where(Page.book_id == self.row, Page.part == "read")
                                      .order_by(Page.number))
            self.file = s.get(Page, self.read_page).file
            line = s.scalar(select(Line.id).where(Line.page_id == self.read_page).order_by(Line.number))
            s.add(LineTruth(line_id=line, text_dev="कखग कखग"))
            read_smp = s.scalar(select(Sample).where(Sample.page_id == self.read_page, Sample.w > 8))
            self.read_sample, x_mid = read_smp.id, read_smp.x + read_smp.w // 2
            s.add(WordList(name="w", file="w.txt", books=json.dumps([self.row])))
        split_sample(self.lib, self.row, self.read_sample, x_mid)       # an undo step of a Read Book letter
        folder = self.lib.book_dir(self.lib.get_book(self.row))
        (folder / "line-search").mkdir(exist_ok=True)
        (folder / "line-search" / "meta.json").write_text("{}", encoding="utf-8")

    def tearDown(self):
        appbook.cleanup(self.tmp, self.lib)

    def learned(self, book_id):
        """What the reader and the language model of `book_id` learn (a fold leaving out the read page)."""
        data = linesearch._training_set(self.lib, book_id, [self.file], store=None)
        with self.lib.session() as s:
            sig = linesearch._signature(s, s.get(Book, book_id))
        lm = book_model_without(self.lib, book_id, [self.file])
        return {"X": data["X"], "y": data["y"], "classes": data["classes"], "meta": data["meta"], "signature": sig,
                "checked": linesearch._checked_lines(self.lib, book_id), "lm": (dict(lm.c3), lm.lines),
                "lm_all": dict(book_model(self.lib, book_id).c3),
                "spacing": linesearch.usual_spacing(self.lib, book_id)}

    def test_the_split_keeps_every_count_and_what_the_book_learns(self):
        before = self.learned(self.row)
        self.assertTrue(before["lm"][0] and before["checked"] and len(before["y"]))   # something to compare
        steps = split.plan(self.lib)
        self.assertEqual([(p["id"], p["how"], p["problems"], p["undo steps moved"]) for p in steps],
                         [(self.row, "split", [], 1)])
        self.assertIn("split --library", unsplit_message(self.lib))     # the app does not open it yet
        old = self.lib.book_dir(self.lib.get_book(self.row))
        r = split.split_library(self.lib)
        self.assertTrue(r["same"], (r["before"], r["after"]))
        self.assertIsNone(unsplit_message(self.lib))
        (done,) = r["rows"]
        book = self.lib.get_book(done["book"])
        dataset = self.lib.get_book(self.row)
        self.assertEqual((book.kind, book.name, book.read_dataset_id, dataset.kind), (BOOK, dataset.name, self.row, DATASET))
        self.assertEqual((book.read_dir, dataset.read_dir), (str(self.read.resolve()), ""))
        self.assertEqual(done["dataset counts"]["read pages"], 0)
        self.assertEqual(done["book counts"]["training pages"], 0)
        self.assertEqual(done["book counts"]["line truth"], 1)
        new = self.lib.book_dir(book)
        self.assertFalse((old / "read").exists())                         # the book's files are in its folder
        self.assertTrue((new / "read" / "letters").is_dir())
        self.assertTrue((new / "line-search" / "meta.json").is_file())
        self.assertTrue((old / "letters").is_dir())                       # the dataset's stay
        with self.lib.session() as s:
            self.assertEqual(s.scalar(select(func.count(Action.id)).where(Action.book_id == book.id)), 1)
            self.assertEqual(s.get(Sample, self.read_sample).book_id, book.id)
            self.assertEqual(json.loads(s.scalar(select(WordList.books))), sorted([self.row, book.id]))
            images = s.scalars(select(Sample).where(Sample.book_id == book.id, Sample.deleted.is_(False))).all()
        self.assertTrue(all((new / x.image).is_file() for x in images))
        after = self.learned(book.id)                                     # the book learns from its dataset...
        np.testing.assert_array_equal(after.pop("X"), before.pop("X"))     # ...exactly what the one row learned
        np.testing.assert_array_equal(after.pop("y"), before.pop("y"))
        self.assertEqual(after, before)
        self.assertEqual(split.plan(self.lib), [])                         # nothing left to split

    def test_a_read_book_without_training_data_becomes_a_book_in_place(self):
        other = self.lib.create_book("Only read", writing="printed").id
        legacy_read_book(self.lib, other, self.read)
        how = {p["id"]: p["how"] for p in split.plan(self.lib)}
        self.assertEqual(how[other], "book")
        r = split.split_library(self.lib)
        self.assertEqual(sorted(x["dataset"] is None for x in r["rows"]), [False, True])   # only one row split in two
        self.assertTrue(r["same"])
        self.assertEqual(self.lib.get_book(other).kind, BOOK)
        self.assertIsNone(self.lib.get_book(other).read_dataset_id)

    def test_problems_stop_it_before_anything_changes(self):
        with self.lib.session() as s:
            s.get(Sample, self.read_sample).group_id = s.scalar(select(LetterGroup.id).where(LetterGroup.book_id == self.row))
        (step,) = split.plan(self.lib)
        self.assertTrue(any("in groups" in x for x in step["problems"]))
        before = split.counts(self.lib)
        with self.assertRaisesRegex(LibraryError, "Nothing was split"):
            split.split_library(self.lib)
        self.assertEqual(split.counts(self.lib), before)
        self.assertTrue((self.lib.book_dir(self.lib.get_book(self.row)) / "read").is_dir())

    def test_a_failure_moves_the_folders_back(self):
        old = self.lib.book_dir(self.lib.get_book(self.row))
        before = split.counts(self.lib)
        real = split._move

        def failing(src, dst, done):
            real(src, dst, done)
            if src.name == "line-search":
                raise OSError("disk full")
        split._move = failing
        try:
            with self.assertRaises(OSError):
                split.split_library(self.lib)
        finally:
            split._move = real
        self.assertEqual(split.counts(self.lib), before)
        self.assertTrue((old / "read").is_dir() and (old / "line-search").is_dir())
        self.assertEqual([p.name for p in (self.lib.root / "books").iterdir()], [old.name])

    def test_the_command_shows_and_runs(self):
        root = self.lib.root
        self.lib.close()
        self.assertEqual(split.main(["--library", str(root)]), 0)            # only shows
        from letter_extractor.app.library import Library
        self.lib = Library(root)
        self.assertEqual(len(self.lib.unsplit_books()), 1)
        self.lib.close()
        backup = self.tmp / "backup"
        self.assertEqual(split.main(["--library", str(root), "--run", "--backup", str(backup)]), 0)
        self.assertTrue((backup / "library.db").is_file() and (backup / "books").is_dir())
        self.lib = Library(root)
        self.assertEqual(self.lib.unsplit_books(), [])
        old = Library(backup)                                              # the backup is the library before it
        try:
            self.assertEqual(len(old.unsplit_books()), 1)
        finally:
            old.close()


if __name__ == "__main__":
    unittest.main()

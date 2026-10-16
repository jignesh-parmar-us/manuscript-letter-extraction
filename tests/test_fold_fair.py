"""C24: fold-fair Measure leaves out the datasets' pages that are the tested pages by content (sha256), not by name."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from test_book_parts import page_image                             # noqa: E402
from letter_extractor.app import linesearch                        # noqa: E402
from letter_extractor.app.db import LetterGroup, Line, Page          # noqa: E402
from letter_extractor.app.dictionary import _label_lines, book_model_without   # noqa: E402
from letter_extractor.app.library import LeftOut, Library           # noqa: E402
from letter_extractor.app.truth import save_truth                  # noqa: E402
from sqlalchemy import select                                       # noqa: E402


class FoldFairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        train, read = self.tmp / "train", self.tmp / "read"
        train.mkdir()
        read.mkdir()
        page_image(2).save(train / "scan-a.png")                       # the same page as the book's p1.png ...
        shutil.copy(train / "scan-a.png", read / "p1.png")             # ... under another name
        page_image(3).save(train / "p2.png")                           # same name as the book's p2.png ...
        page_image(1).save(read / "p2.png")                            # ... but another page
        self.lib = Library(self.tmp / "lib")
        self.dataset = self.lib.create_book("D", train, writing="printed").id
        self.lib.capture(self.dataset)
        with self.lib.session() as s:
            for i, g in enumerate(s.scalars(select(LetterGroup).where(LetterGroup.book_id == self.dataset))):
                g.label_dev, g.status = "कख"[i % 2], "reviewed"
        self.book = self.lib.create_book("B", writing="printed", kind="book", dataset_id=self.dataset).id
        self.lib.set_read_folder(self.book, read)
        self.lib.capture_read(self.book)
        with self.lib.session() as s:
            self.pages = dict(s.execute(select(Page.file, Page.id)).all())    # file names are unique here but p2
            self.book_pages = dict(s.execute(select(Page.file, Page.id).where(Page.book_id == self.book)).all())
            self.set_pages = dict(s.execute(select(Page.file, Page.id).where(Page.book_id == self.dataset)).all())

    def tearDown(self):
        self.lib.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_same_page_by_content_is_left_out_whatever_its_name(self):
        got = self.lib.left_out(self.book, ["p1.png"])
        self.assertEqual(set(got), {self.book_pages["p1.png"], self.set_pages["scan-a.png"]})
        got = self.lib.left_out(self.book, [self.book_pages["p2.png"]])     # by id; the dataset's p2 is another page
        self.assertEqual(set(got), {self.book_pages["p2.png"]})
        self.assertIs(self.lib.left_out(self.book, got), got)                # already resolved
        self.assertEqual(self.lib.left_out(self.book, []), LeftOut())

    def test_a_fold_learns_no_letter_and_no_label_of_its_page(self):
        skip = self.lib.left_out(self.book, ["p1.png"])
        with self.lib.session() as s:
            every = _label_lines(s, self.dataset)
            without = _label_lines(s, self.dataset, skip)
            only_a = _label_lines(s, self.dataset, LeftOut({self.set_pages["p2.png"]}))
        self.assertEqual(len(without) + len(only_a), len(every))             # scan-a's lines are the ones gone
        lm_all, lm_fold = book_model_without(self.lib, self.book, []), book_model_without(self.lib, self.book, ["p1.png"])
        self.assertGreater(lm_all.lines, lm_fold.lines)
        all_rows = linesearch._training_set(self.lib, self.book, ())["meta"]["letters"]
        fold_rows = linesearch._training_set(self.lib, self.book, skip)["meta"]["letters"]
        self.assertLess(fold_rows, all_rows)

    def test_its_checked_lines_are_left_out_too(self):
        with self.lib.session() as s:
            line = s.scalar(select(Line.id).where(Line.page_id == self.book_pages["p1.png"]).order_by(Line.number))
        save_truth(self.lib, line, "નારાયણ")
        self.assertEqual(len(linesearch._checked_lines(self.lib, self.book)), 1)
        self.assertEqual(linesearch._checked_lines(self.lib, self.book, self.lib.left_out(self.book, ["p1.png"])), [])
        self.assertEqual(len(linesearch._checked_lines(self.lib, self.book, ["p2.png"])), 1)


if __name__ == "__main__":
    unittest.main()

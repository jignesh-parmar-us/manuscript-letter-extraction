"""C22: the page manager of a book and a dataset: order, excluded pages, deleting, thumbnails."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from test_book_parts import page_image                             # noqa: E402
from test_wholelines import READ                                    # noqa: E402
from fastapi.testclient import TestClient                           # noqa: E402
from letter_extractor.app.api import create_app                    # noqa: E402
from letter_extractor.app.db import Line, Page, Sample              # noqa: E402
from letter_extractor.app.library import BookHasReviewError, Library, LibraryError   # noqa: E402
from letter_extractor.app.main import AppContext                   # noqa: E402
from letter_extractor.app.pages import (NOT_PREPARED, delete_page, move_page, page_list, set_excluded,   # noqa: E402
                                        thumbnail)
from letter_extractor.app.truth import save_truth                  # noqa: E402
from letter_extractor.app.wholelines import read_book_lines, whole_line_texts   # noqa: E402
from sqlalchemy import select                                       # noqa: E402


class PageManagerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.read = self.tmp / "read"
        self.read.mkdir()
        for name, lines in (("p1.png", 2), ("p2.png", 3), ("p3.png", 1)):
            page_image(lines).save(self.read / name)
        self.lib = Library(self.tmp / "lib")
        self.uploads = self.tmp / "lib" / "uploads"
        self.book = self.lib.create_book("B", writing="printed", kind="book").id
        self.lib.set_read_folder(self.book, self.read)                  # a folder of the user's own

    def tearDown(self):
        self.lib.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def listing(self):
        return page_list(self.lib, self.book, self.uploads)["pages"]

    def files(self):
        return [(p["file"], p["excluded"], p["prepared"]) for p in self.listing()]

    def numbers(self):
        with self.lib.session() as s:
            return [tuple(r) for r in s.execute(select(Page.file, Page.number).where(Page.book_id == self.book)
                                                .order_by(Page.number, Page.id))]


class BookPagesTests(PageManagerCase):
    def test_a_page_excluded_before_preparing_is_skipped_and_new_again_when_included(self):
        set_excluded(self.lib, self.book, "p2.png", True)
        self.assertEqual(self.files(), [("p2.png", True, False), ("p1.png", False, False), ("p3.png", False, False)])
        r = self.lib.capture_read(self.book)
        self.assertEqual((r["pages"], r["pages_left"]), (2, 0))
        with self.lib.session() as s:
            row = s.scalars(select(Page).where(Page.file == "p2.png")).one()
            self.assertEqual((row.status, len(row.lines)), (NOT_PREPARED, 0))
        self.assertEqual(self.lib.list_books()[0]["read_pages"], 2)
        set_excluded(self.lib, self.book, "p2.png", False)
        self.assertEqual([p["status"] for p in self.listing() if p["file"] == "p2.png"], ["new"])
        self.assertEqual(self.lib.capture_read(self.book)["pages"], 1)

    def test_an_excluded_page_is_not_read_nor_downloaded_but_kept(self):
        self.lib.capture_read(self.book)
        set_excluded(self.lib, self.book, "p2.png", True)
        got = read_book_lines(self.lib, self.book, reader=lambda rgb: READ)
        self.assertEqual(got["pages"], 2)
        with self.lib.session() as s:
            p2 = s.scalar(select(Page.id).where(Page.file == "p2.png"))
            self.assertGreater(len(s.get(Page, p2).lines), 0)                # kept
        self.assertEqual([p.file for p, _ in whole_line_texts(self.lib, self.book)], ["p1.png", "p3.png"])
        self.assertEqual([p.file for p, _ in whole_line_texts(self.lib, self.book, page_ids=[p2])], [])

    def test_excluding_a_page_with_checked_lines_asks_first(self):
        self.lib.capture_read(self.book)
        with self.lib.session() as s:
            line = s.scalar(select(Line.id).join(Page).where(Page.file == "p1.png").order_by(Line.number))
        save_truth(self.lib, line, "નારાયણ")
        self.assertEqual([p["checked"] for p in self.listing()], [1, 0, 0])
        with self.assertRaises(BookHasReviewError) as e:
            set_excluded(self.lib, self.book, "p1.png", True)
        self.assertIn("1 checked line (Line truth)", str(e.exception))
        set_excluded(self.lib, self.book, "p1.png", True, force=True)
        self.assertTrue(self.listing()[0]["excluded"])

    def test_moving_pages_and_cutting_again_keep_the_order_new_pages_come_last(self):
        self.lib.capture_read(self.book)
        self.assertEqual(self.numbers(), [("p1.png", 1), ("p2.png", 2), ("p3.png", 3)])
        with self.lib.session() as s:
            p3 = s.scalar(select(Page.id).where(Page.file == "p3.png"))
        move_page(self.lib, self.book, p3, -1)
        self.assertEqual(self.numbers(), [("p1.png", 1), ("p3.png", 2), ("p2.png", 3)])
        self.lib.recut_page(self.book, p3)
        self.assertEqual(self.numbers(), [("p1.png", 1), ("p3.png", 2), ("p2.png", 3)])
        page_image().save(self.read / "p0.png")                             # first by name, but added later
        self.lib.capture_read(self.book)
        self.assertEqual(self.numbers()[-1], ("p0.png", 4))
        with self.lib.session() as s:
            p1 = s.scalar(select(Page.id).where(Page.file == "p1.png"))
        move_page(self.lib, self.book, p1, -1)                              # already first: stays
        self.assertEqual(self.numbers()[0], ("p1.png", 1))

    def test_deleting_a_page_in_a_folder_of_ones_own_keeps_the_file_excluded(self):
        self.lib.capture_read(self.book)
        r = delete_page(self.lib, self.book, "p2.png", self.uploads)
        self.assertEqual((r["file_removed"], r["excluded"]), (False, True))
        self.assertTrue((self.read / "p2.png").is_file())
        self.assertEqual(self.files(), [("p1.png", False, True), ("p2.png", True, False), ("p3.png", False, True)])
        with self.lib.session() as s:
            self.assertEqual(s.scalar(select(Sample.id).join(Page).where(Page.file == "p2.png")), None)
        book_dir = self.lib.book_dir(self.lib.get_book(self.book))
        self.assertFalse((book_dir / "read" / "letters" / "p2").exists())
        self.assertEqual(self.lib.capture_read(self.book)["pages"], 0)      # Prepare does not bring it back

    def test_deleting_a_page_of_a_pdf_removes_its_image_and_asks_when_checked(self):
        pdf = self.tmp / "b.pdf"
        imgs = [page_image(), page_image(3)]
        imgs[0].save(pdf, save_all=True, append_images=imgs[1:], resolution=150)
        self.lib.import_pdf(self.book, pdf, force=True)
        self.lib.capture_read(self.book)
        with self.lib.session() as s:
            line = s.scalar(select(Line.id).join(Page).where(Page.file == "page-0001.jpg").order_by(Line.number))
        save_truth(self.lib, line, "નારાયણ")
        with self.assertRaises(BookHasReviewError):
            delete_page(self.lib, self.book, "page-0001.jpg", self.uploads)
        r = delete_page(self.lib, self.book, "page-0001.jpg", self.uploads, force=True)
        self.assertEqual((r["file_removed"], r["excluded"]), (True, False))
        self.assertEqual(self.files(), [("page-0002.jpg", False, True)])
        self.assertEqual(self.numbers(), [("page-0002.jpg", 1)])

    def test_a_thumbnail_is_small_and_kept(self):
        out = thumbnail(self.lib, self.book, "p1.png", width=120)
        from PIL import Image
        with Image.open(out) as im:
            self.assertLessEqual(im.width, 120)
        self.assertEqual(thumbnail(self.lib, self.book, "p1.png", width=120), out)
        with self.assertRaises(LibraryError):
            thumbnail(self.lib, self.book, "../secret.png")


class DatasetPagesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.train = self.tmp / "train"
        self.train.mkdir()
        for name in ("p1.png", "p2.png"):
            page_image().save(self.train / name)
        self.lib = Library(self.tmp / "lib")
        self.dataset = self.lib.create_book("D", self.train, writing="printed").id
        self.lib.capture(self.dataset)

    def tearDown(self):
        self.lib.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_capturing_again_skips_and_keeps_an_excluded_page(self):
        set_excluded(self.lib, self.dataset, "p2.png", True)
        self.lib.capture(self.dataset, force=True)
        with self.lib.session() as s:
            rows = {p.file: (p.excluded, p.status, len(p.lines)) for p in
                    s.scalars(select(Page).where(Page.book_id == self.dataset))}
        self.assertEqual(rows["p2.png"], (True, NOT_PREPARED, 0))
        self.assertFalse(rows["p1.png"][0])
        self.assertGreater(rows["p1.png"][2], 0)
        self.assertEqual(self.lib.list_books()[0]["pages"], 1)

    def test_an_excluded_page_is_not_trained_on(self):
        from letter_extractor.app.dictionary import _label_lines
        from letter_extractor.app.db import LetterGroup
        with self.lib.session() as s:
            for g in s.scalars(select(LetterGroup).where(LetterGroup.book_id == self.dataset)):
                g.label_dev = "क"
        with self.lib.session() as s:
            before = _label_lines(s, self.dataset)
        set_excluded(self.lib, self.dataset, "p2.png", True)
        with self.lib.session() as s:
            after = _label_lines(s, self.dataset)
        self.assertGreater(len(before), len(after))
        self.assertGreater(len(after), 0)

    def test_an_excluded_page_is_not_exported(self):
        from letter_extractor.app.export import export_book
        before = export_book(self.lib, self.dataset, self.tmp / "e1")
        set_excluded(self.lib, self.dataset, "p2.png", True)
        after = export_book(self.lib, self.dataset, self.tmp / "e2")
        self.assertLess(after["letters"], before["letters"])


class PageManagerApiTests(PageManagerCase):
    def test_the_routes(self):
        client = TestClient(create_app(self.lib, "", AppContext(settings_file=self.tmp / "settings.json")))
        got = client.get(f"/api/books/{self.book}/page-list").json()
        self.assertEqual([p["file"] for p in got["pages"]], ["p1.png", "p2.png", "p3.png"])
        self.assertFalse(got["owned"])
        self.assertEqual(client.get(got["pages"][0]["thumb"]).status_code, 200)
        r = client.post(f"/api/books/{self.book}/page-list/exclude", json={"file": "p3.png"})
        self.assertEqual(r.status_code, 200, r.text)
        self.lib.capture_read(self.book)
        self.assertEqual([p["file"] for p in client.get(f"/api/books/{self.book}/pages?part=read").json()],
                         ["p1.png", "p2.png"])
        self.assertEqual(len(client.get(f"/api/books/{self.book}/pages?part=read&excluded=true").json()), 3)
        pid = client.get(f"/api/books/{self.book}/pages?part=read").json()[1]["id"]
        self.assertEqual(client.post(f"/api/books/{self.book}/pages/{pid}/move", json={"by": -1}).json()["number"], 1)
        r = client.post(f"/api/books/{self.book}/page-list/delete", json={"file": "nope.png"})
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()

"""C16a: the two parts of a book, Training Data and Read Book; PDF pages to images."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import synthetic                                                    # noqa: E402
from fastapi.testclient import TestClient                           # noqa: E402
from letter_extractor.app.api import create_app                    # noqa: E402
from letter_extractor.app.db import LetterGroup, Page, Sample       # noqa: E402
from letter_extractor.app.library import BookHasReviewError, Library, LibraryError   # noqa: E402
from letter_extractor.ocr.pdf import PdfError, pdf_pages            # noqa: E402
from sqlalchemy import func, select                                 # noqa: E402


def page_image(lines=2):
    rgb, _ = synthetic.make_letters_page(n_lines=lines)
    return Image.fromarray(rgb)


class PdfTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_every_page_becomes_an_image_in_order(self):
        pages = [page_image(), page_image(3), page_image(1)]
        pages[0].save(self.tmp / "book.pdf", save_all=True, append_images=pages[1:], resolution=100)
        seen = []
        names = pdf_pages(self.tmp / "book.pdf", self.tmp / "out", dpi=100,
                          progress=lambda n, total, r: seen.append((n, total, r.file)))
        self.assertEqual(names, ["page-0001.jpg", "page-0002.jpg", "page-0003.jpg"])
        self.assertEqual(seen[-1], (3, 3, "page-0003.jpg"))
        with Image.open(self.tmp / "out" / names[0]) as im:
            self.assertEqual(im.size, pages[0].size)                      # 100 dpi in, 100 dpi out

    def test_not_a_pdf(self):
        (self.tmp / "broken.pdf").write_bytes(b"not a pdf at all")
        with self.assertRaises(PdfError):
            pdf_pages(self.tmp / "broken.pdf", self.tmp / "out")


class PartsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.train, self.read = self.tmp / "training", self.tmp / "read"
        self.train.mkdir()
        self.read.mkdir()
        for name in ("p1.png", "p2.png"):                                # same names in both folders
            page_image().save(self.train / name)
            page_image(3).save(self.read / name)
        page_image().save(self.read / "p3.png")
        self.lib = Library(self.tmp / "lib")
        self.book = self.lib.create_book("B", self.train, writing="printed").id
        self.lib.capture(self.book)

    def tearDown(self):
        self.lib.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def count(self, model, *where):
        with self.lib.session() as s:
            return s.scalar(select(func.count(model.id)).where(*where)) or 0


class ReadBookTests(PartsTestCase):
    def test_read_pages_are_cut_never_grouped_and_kept_apart(self):
        groups = self.count(LetterGroup, LetterGroup.book_id == self.book)
        training = self.count(Sample, Sample.part == "training")
        self.lib.set_read_folder(self.book, self.read)
        r = self.lib.capture_read(self.book)
        self.assertEqual((r["pages"], r["pages_left"]), (3, 0))
        self.assertEqual(self.count(Page, Page.part == "read"), 3)
        self.assertGreater(self.count(Sample, Sample.part == "read"), 0)
        self.assertEqual(self.count(Sample, Sample.part == "read", Sample.group_id.is_not(None)), 0)
        self.assertEqual(self.count(LetterGroup, LetterGroup.book_id == self.book), groups)
        self.assertEqual(self.count(Sample, Sample.part == "training"), training)
        with self.lib.session() as s:                                    # their files are kept apart too
            images = set(s.scalars(select(Sample.image).where(Sample.part == "read")))
        self.assertTrue(all(i.startswith("read/letters/") for i in images))
        self.assertTrue(all((self.lib.book_dir(self.lib.get_book(self.book)) / i).is_file() for i in images))
        summary = next(b for b in self.lib.list_books() if b["id"] == self.book)
        self.assertEqual((summary["pages"], summary["read_pages"]), (2, 3))
        self.assertEqual(summary["unsure"], self.count(Sample, Sample.part == "training", Sample.group_id.is_(None),
                                                         Sample.deleted.is_(False)))

    def test_capturing_training_data_again_keeps_the_read_book(self):
        self.lib.set_read_folder(self.book, self.read)
        self.lib.capture_read(self.book)
        read = self.count(Sample, Sample.part == "read")
        self.lib.capture(self.book, force=True)
        self.assertEqual(self.count(Sample, Sample.part == "read"), read)
        self.assertEqual(self.count(Page, Page.part == "training"), 2)

    def test_a_cancelled_capture_keeps_its_pages_and_the_next_one_continues(self):
        self.lib.set_read_folder(self.book, self.read)
        self.lib.READ_BATCH = 1
        done = []
        r = self.lib.capture_read(self.book, progress=lambda n, t, x: done.append(n), cancel=lambda: len(done) >= 1)
        self.assertEqual((r["pages"], r["pages_left"]), (1, 2))
        r = self.lib.capture_read(self.book)
        self.assertEqual((r["pages"], r["pages_left"]), (2, 0))
        self.assertEqual(self.count(Page, Page.part == "read"), 3)

    def test_a_pdf_becomes_the_read_book(self):
        pages = [page_image(), page_image(3)]
        pages[0].save(self.tmp / "book.pdf", save_all=True, append_images=pages[1:], resolution=150)
        cfg = self.lib.book_config(self.lib.get_book(self.book))
        cfg.pdf_dpi = 150
        self.lib.set_book_config(self.book, cfg)
        self.assertEqual(self.lib.import_pdf(self.book, self.tmp / "book.pdf")["pages"], 2)
        book = self.lib.get_book(self.book)
        self.assertEqual(book.read_pdf, "book.pdf")
        self.assertEqual(sorted(p.name for p in self.lib.read_folder(book).iterdir()), ["page-0001.jpg", "page-0002.jpg"])
        self.lib.capture_read(self.book)
        with self.lib.session() as s:
            self.assertEqual(list(s.scalars(select(Page.number).where(Page.part == "read").order_by(Page.number))), [1, 2])
        with self.assertRaises(BookHasReviewError):                      # new pages replace the old ones: ask
            self.lib.import_pdf(self.book, self.tmp / "book.pdf")
        self.lib.import_pdf(self.book, self.tmp / "book.pdf", force=True)
        self.assertEqual(self.count(Page, Page.part == "read"), 0)

    def test_a_folder_inside_the_library_is_refused(self):
        with self.assertRaises(LibraryError):
            self.lib.set_read_folder(self.book, self.lib.root / "books")


class MovingPagesTests(PartsTestCase):
    def test_a_read_page_used_for_training_and_back(self):
        self.lib.set_read_folder(self.book, self.read)
        self.lib.capture_read(self.book)
        with self.lib.session() as s:
            page = s.scalar(select(Page.id).where(Page.part == "read").order_by(Page.number))
        n = self.lib.set_page_part(page, "training")["samples"]
        self.assertEqual(self.count(Sample, Sample.page_id == page, Sample.part == "training", Sample.group_id.is_(None)), n)
        self.lib.set_page_part(page, "read")
        self.assertEqual(self.count(Sample, Sample.page_id == page, Sample.part == "read"), n)

    def test_a_training_page_with_labels_asks_first(self):
        with self.lib.session() as s:
            page = s.scalar(select(Page.id).where(Page.part == "training"))
            g = s.scalar(select(LetterGroup).join(Sample, Sample.group_id == LetterGroup.id).where(Sample.page_id == page))
            g.label_dev, g.label_guj, g.status = "क", "ક", "labelled"
            gid = g.id
        with self.assertRaises(BookHasReviewError):
            self.lib.set_page_part(page, "read")
        self.lib.set_page_part(page, "read", force=True)
        self.assertEqual(self.count(Sample, Sample.page_id == page, Sample.group_id.is_not(None)), 0)
        self.assertEqual(self.count(LetterGroup, LetterGroup.id == gid), 1)  # a labelled group stays, even empty


class ApiTests(PartsTestCase):
    def test_routes(self):
        c = TestClient(create_app(self.lib, "t"))
        h = {"X-Token": "t"}
        r = c.post(f"/api/books/{self.book}/read/folder", headers=h, json={"path": str(self.read)})
        self.assertEqual(r.json()["read_dir"], str(self.read.resolve()))
        self.assertEqual(c.get(f"/api/books/{self.book}/pages?part=read", headers=h).json(), [])
        self.assertEqual([p["problem"] for p in c.get(f"/api/books/{self.book}/page-problems?part=read",
                                                      headers=h).json()], ["new"] * 3)
        self.lib.capture_read(self.book)
        read = c.get(f"/api/books/{self.book}/pages?part=read", headers=h).json()
        self.assertEqual([p["file"] for p in read], ["p1.png", "p2.png", "p3.png"])
        self.assertEqual({p["part"] for p in read}, {"read"})
        self.assertEqual(len(c.get(f"/api/books/{self.book}/pages", headers=h).json()), 2)   # training by default
        unsure = c.get(f"/api/books/{self.book}/unsure", headers=h).json()
        self.assertTrue(all(x["page_id"] not in {p["id"] for p in read} for x in unsure["samples"]))
        r = c.post(f"/api/pages/{read[0]['id']}/part", headers=h, json={"part": "training"})
        self.assertEqual(r.json()["part"], "training")
        self.assertEqual(c.get(f"/files/pages/{read[0]['id']}?token=t").status_code, 200)   # from the read folder
        self.assertEqual(c.post(f"/api/books/{self.book}/read/pdf", headers=h,
                                json={"path": str(self.tmp / "none.pdf")}).status_code, 400)
        c.close()


if __name__ == "__main__":
    unittest.main()

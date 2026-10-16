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
    """A dataset with Training Data and a book (C20) that learns from it, with Read Book pages to prepare."""
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
        self.dataset = self.lib.create_book("B", self.train, writing="printed").id
        self.lib.capture(self.dataset)
        self.book = self.lib.create_book("B", writing="printed", kind="book", dataset_id=self.dataset).id

    def tearDown(self):
        self.lib.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def count(self, model, *where):
        with self.lib.session() as s:
            return s.scalar(select(func.count(model.id)).where(*where)) or 0


class ReadBookTests(PartsTestCase):
    def test_read_pages_are_cut_never_grouped_and_kept_apart(self):
        groups = self.count(LetterGroup, LetterGroup.book_id == self.dataset)
        training = self.count(Sample, Sample.part == "training")
        self.lib.set_read_folder(self.book, self.read)
        r = self.lib.capture_read(self.book)
        self.assertEqual((r["pages"], r["pages_left"]), (3, 0))
        self.assertEqual(self.count(Page, Page.part == "read", Page.book_id == self.book), 3)
        self.assertGreater(self.count(Sample, Sample.part == "read", Sample.book_id == self.book), 0)
        self.assertEqual(self.count(Sample, Sample.part == "read", Sample.group_id.is_not(None)), 0)
        self.assertEqual(self.count(LetterGroup, LetterGroup.book_id == self.dataset), groups)
        self.assertEqual(self.count(LetterGroup, LetterGroup.book_id == self.book), 0)
        self.assertEqual(self.count(Sample, Sample.part == "training"), training)
        with self.lib.session() as s:                                    # their files are in the book's folder
            images = set(s.scalars(select(Sample.image).where(Sample.part == "read")))
        self.assertTrue(all(i.startswith("read/letters/") for i in images))
        self.assertTrue(all((self.lib.book_dir(self.lib.get_book(self.book)) / i).is_file() for i in images))
        rows = {b["id"]: b for b in self.lib.list_books()}
        self.assertEqual((rows[self.book]["pages"], rows[self.book]["read_pages"], rows[self.book]["kind"]),
                         (0, 3, "book"))
        self.assertEqual((rows[self.dataset]["pages"], rows[self.dataset]["read_pages"]), (2, 0))
        self.assertEqual((rows[self.book]["dataset_id"], rows[self.book]["dataset_name"]), (self.dataset, "B"))
        self.assertEqual(rows[self.dataset]["used_by"], [{"id": self.book, "name": "B"}])
        self.assertEqual(rows[self.dataset]["unsure"],
                         self.count(Sample, Sample.part == "training", Sample.group_id.is_(None),
                                    Sample.deleted.is_(False)))

    def test_capturing_training_data_again_keeps_the_read_book(self):
        self.lib.set_read_folder(self.book, self.read)
        self.lib.capture_read(self.book)
        read = self.count(Sample, Sample.part == "read")
        self.lib.capture(self.dataset, force=True)
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


class KindsTests(PartsTestCase):
    """C20: a dataset only trains and a book only reads, so no row holds both parts again."""
    def test_a_dataset_gets_no_read_book_pages_and_a_book_no_training_data(self):
        for refused in (lambda: self.lib.set_read_folder(self.dataset, self.read),
                        lambda: self.lib.import_pdf(self.dataset, self.tmp / "none.pdf"),
                        lambda: self.lib.capture_read(self.dataset),
                        lambda: self.lib.set_input_folder(self.book, self.train),
                        lambda: self.lib.capture(self.book),
                        lambda: self.lib.add_new_pages(self.book)):
            with self.assertRaisesRegex(LibraryError, "is a (dataset|book)"):
                refused()
        with self.assertRaises(LibraryError):
            self.lib.create_book("C", self.train, kind="book")               # a book has no Training Data folder
        with self.assertRaises(LibraryError):
            self.lib.create_book("C", kind="dataset", dataset_id=self.dataset)
        self.assertEqual(self.lib.unsplit_books(), [])

    def test_names_are_unique_per_kind(self):
        with self.assertRaisesRegex(LibraryError, "A book named 'B'"):
            self.lib.create_book("B", kind="book")
        other = self.lib.create_book("Other", kind="book").id
        with self.assertRaisesRegex(LibraryError, "A book named 'B'"):
            self.lib.rename_book(other, "B")
        with self.assertRaisesRegex(LibraryError, "A dataset named 'B'"):
            self.lib.create_book("B")
        self.assertEqual(self.lib.training_source(self.lib.get_book(other)), None)   # learns from nothing yet
        self.assertEqual(self.lib.training_source(self.lib.get_book(self.book)), self.dataset)
        self.assertEqual(self.lib.training_source(self.lib.get_book(self.dataset)), self.dataset)

    def test_pages_are_not_moved_between_the_parts(self):
        self.lib.set_read_folder(self.book, self.read)
        self.lib.capture_read(self.book)
        with self.lib.session() as s:
            read = s.scalar(select(Page.id).where(Page.part == "read").order_by(Page.number))
            training = s.scalar(select(Page.id).where(Page.part == "training"))
        for page, part in ((read, "training"), (training, "read")):
            with self.assertRaisesRegex(LibraryError, "separate"):
                self.lib.set_page_part(page, part)
        self.assertEqual(self.lib.set_page_part(read, "read")["samples"], 0)    # already there: nothing to do
        self.assertEqual(self.count(Page, Page.part == "read", Page.book_id == self.book), 3)

    def test_deleting_a_dataset_leaves_its_books(self):
        self.lib.delete_book(self.dataset)
        self.assertIsNone(self.lib.get_book(self.book).read_dataset_id)


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
        self.assertEqual(c.get(f"/api/books/{self.book}/pages", headers=h).json(), [])     # a book: no Training Data
        self.assertEqual(len(c.get(f"/api/datasets/{self.dataset}/pages", headers=h).json()), 2)
        unsure = c.get(f"/api/datasets/{self.dataset}/unsure", headers=h).json()
        self.assertTrue(all(x["page_id"] not in {p["id"] for p in read} for x in unsure["samples"]))
        self.assertEqual(c.get(f"/api/datasets/{self.book}/unsure", headers=h).status_code, 404)   # not a dataset
        r = c.post(f"/api/pages/{read[0]['id']}/part", headers=h, json={"part": "training"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(c.get(f"/files/pages/{read[0]['id']}?token=t").status_code, 200)   # from the read folder
        self.assertEqual(c.post(f"/api/books/{self.book}/read/pdf", headers=h,
                                json={"path": str(self.tmp / "none.pdf")}).status_code, 400)
        self.assertEqual(c.post(f"/api/books/{self.dataset}/read/folder", headers=h,
                                json={"path": str(self.read)}).status_code, 400)          # a dataset reads nothing
        self.assertEqual([b["id"] for b in c.get("/api/books", headers=h).json()], [self.book])
        self.assertEqual([b["id"] for b in c.get("/api/datasets", headers=h).json()], [self.dataset])
        made = c.post("/api/books", headers=h, json={"name": "New", "dataset_id": self.dataset}).json()
        self.assertEqual((made["kind"], made["dataset_id"]), ("book", self.dataset))
        self.assertEqual(c.post("/api/books", headers=h, json={"name": "Bad", "input_dir": str(self.train)}).status_code,
                         400)
        self.assertEqual(c.get(f"/api/datasets/{self.dataset}", headers=h).json()["kind"], "dataset")   # both prefixes
        c.close()


if __name__ == "__main__":
    unittest.main()

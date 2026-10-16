"""C21: page images and PDFs uploaded into a new dataset or book, kept in the uploads folder."""
import io
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient                           # noqa: E402
from letter_extractor.app.api import create_app                    # noqa: E402
from letter_extractor.app.library import Library                   # noqa: E402
from letter_extractor.app.main import AppContext, save_settings    # noqa: E402


def png(size=(60, 40)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, "white").save(out, "PNG")
    return out.getvalue()


def pdf(pages=2) -> bytes:
    out = io.BytesIO()
    images = [Image.new("RGB", (80, 60 + 10 * i), "white") for i in range(pages)]
    images[0].save(out, "PDF", save_all=True, append_images=images[1:], resolution=72)
    return out.getvalue()


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.settings = self.tmp / "settings.json"
        self.lib = Library(self.tmp / "lib")
        self.client = TestClient(create_app(self.lib, "", AppContext(settings_file=self.settings)))
        self.uploads = (self.tmp / "lib" / "uploads").resolve()             # the default: <library>/uploads

    def tearDown(self):
        self.lib.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, kind, name="N", **extra):
        r = self.client.post(f"/api/{kind}", json={"name": name, "writing": "printed", **extra})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def upload(self, kind, row_id, name, data):
        return self.client.post(f"/api/{kind}/{row_id}/upload", params={"name": name}, content=data)

    def wait(self, job):
        for _ in range(200):
            job = self.client.get(f"/api/jobs/{job['id']}").json()
            if job["status"] != "running":
                return job
            time.sleep(0.05)
        self.fail("the job did not end")

    def test_images_go_into_the_datasets_upload_folder_which_becomes_its_folder(self):
        d = self.make("datasets")
        for n in ("p1.png", "p2.png"):
            r = self.upload("datasets", d["id"], n, png())
            self.assertEqual(r.status_code, 200, r.text)
        folder = self.uploads / "datasets" / self.lib.get_book(d["id"]).folder
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["p1.png", "p2.png"])
        self.assertEqual(r.json()["book"]["input_dir"], str(folder))
        problems = self.client.get(f"/api/datasets/{d['id']}/page-problems").json()
        self.assertEqual(sorted(p["file"] for p in problems if p["problem"] == "new"), ["p1.png", "p2.png"])

    def test_refused_names_and_twice_the_same_file(self):
        d = self.make("datasets")
        self.assertEqual(self.upload("datasets", d["id"], "notes.txt", b"x").status_code, 400)
        self.assertEqual(self.upload("datasets", d["id"], "a.png", b"").status_code, 400)
        r = self.upload("datasets", d["id"], "../../escape.png", png())     # only the file name is kept
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(Path(r.json()["book"]["input_dir"], "escape.png").is_file())
        r = self.upload("datasets", d["id"], "escape.png", png())
        self.assertEqual(r.status_code, 400)
        self.assertIn("uploaded already", r.json()["detail"])
        folder = Path(self.lib.get_book(d["id"]).input_dir)
        self.assertEqual([p.name for p in folder.iterdir()], ["escape.png"])     # no part file left

    def test_the_upload_route_of_the_other_kind_is_not_found(self):
        d, b = self.make("datasets"), self.make("books")
        self.assertEqual(self.upload("books", d["id"], "a.png", png()).status_code, 404)
        self.assertEqual(self.upload("datasets", b["id"], "a.png", png()).status_code, 404)

    def test_a_dataset_with_a_folder_of_its_own_takes_no_uploads(self):
        own = self.tmp / "own"
        own.mkdir()
        (own / "a.png").write_bytes(png())
        d = self.make("datasets")
        self.lib.set_input_folder(d["id"], own)
        r = self.upload("datasets", d["id"], "b.png", png())
        self.assertEqual(r.status_code, 400)
        self.assertIn("folder of your own", r.json()["detail"])
        self.assertEqual(self.lib.get_book(d["id"]).input_dir, str(own.resolve()))

    def test_a_books_images_become_its_read_book_folder(self):
        b = self.make("books")
        r = self.upload("books", b["id"], "page 1.jpg", png())
        self.assertEqual(r.status_code, 200, r.text)
        row = r.json()["book"]
        self.assertEqual(row["read_dir"], str(self.uploads / "books" / self.lib.get_book(b["id"]).folder))
        problems = self.client.get(f"/api/books/{b['id']}/page-problems?part=read").json()
        self.assertEqual([p["file"] for p in problems], ["page 1.jpg"])
        self.assertEqual(self.upload("books", b["id"], "all.pdf", pdf()).status_code, 400)   # images or a PDF

    def test_a_books_pdf_becomes_page_images_as_before(self):
        b = self.make("books")
        r = self.upload("books", b["id"], "Book.pdf", pdf(3))
        self.assertEqual(r.status_code, 200, r.text)
        job = self.wait(r.json()["job"])
        self.assertEqual((job["kind"], job["status"]), ("import_pdf", "done"), job)
        book = self.lib.get_book(b["id"])
        self.assertEqual((book.read_pdf, book.read_dir), ("Book.pdf", ""))
        self.assertTrue((self.uploads / "books" / book.folder / "Book.pdf").is_file())       # the PDF is kept
        pages = sorted(p.name for p in (self.lib.book_dir(book) / "read" / "pages").iterdir())
        self.assertEqual(pages, ["page-0001.jpg", "page-0002.jpg", "page-0003.jpg"])
        r = self.upload("books", b["id"], "more.png", png())                 # C22: added to the PDF's pages
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue((self.lib.book_dir(book) / "read" / "pages" / "more.png").is_file())
        self.assertEqual(self.upload("books", b["id"], "again.pdf", pdf()).status_code, 400)

    def test_a_datasets_pdf_pages_are_put_beside_it(self):
        d = self.make("datasets")
        job = self.wait(self.upload("datasets", d["id"], "Set.pdf", pdf(2)).json()["job"])
        self.assertEqual(job["status"], "done", job)
        folder = Path(self.lib.get_book(d["id"]).input_dir)
        self.assertEqual(folder, self.uploads / "datasets" / self.lib.get_book(d["id"]).folder)
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         ["Set-page-0001.jpg", "Set-page-0002.jpg", "Set.pdf"])

    def test_a_broken_pdf_fails_and_is_removed(self):
        d = self.make("datasets")
        job = self.wait(self.upload("datasets", d["id"], "bad.pdf", b"not a pdf").json()["job"])
        self.assertEqual(job["status"], "failed")
        self.assertFalse((self.uploads / "datasets" / self.lib.get_book(d["id"]).folder / "bad.pdf").exists())
        self.assertEqual(self.lib.get_book(d["id"]).input_dir, "")

    def test_a_folder_is_copied_into_the_uploads_folder(self):
        src = self.tmp / "scans"
        src.mkdir()
        for n in ("s1.png", "s2.png"):
            (src / n).write_bytes(png())
        (src / "readme.txt").write_text("not a page")
        d = self.make("datasets")
        r = self.client.post(f"/api/datasets/{d['id']}/copy-folder", json={"path": str(src)})
        self.assertEqual(r.status_code, 202, r.text)
        job = self.wait(r.json())
        self.assertEqual((job["kind"], job["status"], job["result"]["pages"]), ("copy_pages", "done", 2), job)
        folder = Path(self.lib.get_book(d["id"]).input_dir)
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["s1.png", "s2.png"])
        self.assertEqual(sorted(p.name for p in src.iterdir()), ["readme.txt", "s1.png", "s2.png"])   # untouched
        r = self.client.post(f"/api/datasets/{d['id']}/copy-folder", json={"path": str(src)})
        self.assertEqual(r.status_code, 400)                                  # the same names again
        b = self.make("books")
        self.assertEqual(self.client.post(f"/api/datasets/{b['id']}/copy-folder", json={"path": str(src)}).status_code,
                         404)

    def test_the_uploads_setting_is_used_and_deleting_a_row_deletes_its_uploads(self):
        chosen = self.tmp / "elsewhere"
        save_settings({"uploads": str(chosen)}, self.settings)
        d, other = self.make("datasets"), self.make("datasets", "Other")
        self.upload("datasets", d["id"], "a.png", png())
        self.upload("datasets", other["id"], "a.png", png())
        folder = chosen.resolve() / "datasets" / self.lib.get_book(d["id"]).folder
        self.assertTrue((folder / "a.png").is_file())
        self.assertEqual(self.client.delete(f"/api/datasets/{d['id']}").status_code, 204)
        self.assertFalse(folder.exists())
        self.assertTrue(Path(self.lib.get_book(other["id"]).input_dir, "a.png").is_file())   # the other's stay

    def test_deleting_a_row_never_touches_a_folder_of_its_own(self):
        own = self.tmp / "own"
        own.mkdir()
        (own / "a.png").write_bytes(png())
        d = self.make("datasets")
        self.lib.set_input_folder(d["id"], own)
        self.client.delete(f"/api/datasets/{d['id']}")
        self.assertTrue((own / "a.png").is_file())


if __name__ == "__main__":
    unittest.main()

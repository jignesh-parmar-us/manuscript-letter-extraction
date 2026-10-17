"""C26: the page images of older rows move into the uploads folder (copied, checked, switched; originals kept),
and move with it when the uploads setting changes."""
import io
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient                                      # noqa: E402
from letter_extractor.app import move                                         # noqa: E402
from letter_extractor.app.api import create_app                               # noqa: E402
from letter_extractor.app.db import BOOK, Book, Line, LineTruth, Page          # noqa: E402
from letter_extractor.app.jobs import APP, Job, Jobs                           # noqa: E402
from letter_extractor.app.library import Library, LibraryError, file_sha256    # noqa: E402
from letter_extractor.app.main import AppContext, load_settings, save_settings  # noqa: E402


def png(shade=255) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (60, 40), (shade, shade, shade)).save(out, "PNG")
    return out.getvalue()


class MoveExisting(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.lib = Library(self.tmp / "lib")
        self.uploads = self.tmp / "lib" / "uploads"
        self.own = self.tmp / "black and white"                # one folder of the user's own, used by three rows
        self.own.mkdir()
        for i, n in enumerate(("p1.png", "p2.png", "p3.png")):
            (self.own / n).write_bytes(png(200 + i))

    def tearDown(self):
        self.lib.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def pages(self, row_id, files, part="training", **extra):
        with self.lib.session() as s:
            for i, f in enumerate(files, 1):
                s.add(Page(book_id=row_id, file=f, part=part, folder=part, number=i,
                           sha256=file_sha256(self.own / f), **extra))

    def three_rows(self):
        a = self.lib.create_book("A", self.own).id
        b = self.lib.create_book("B", self.own).id
        book = self.lib.create_book("Read", kind=BOOK).id
        self.lib.set_read_folder(book, self.own)
        self.pages(a, ["p1.png", "p2.png"])
        self.pages(b, ["p1.png"])
        self.pages(book, ["p1.png", "p2.png", "p3.png"], part="read")
        return a, b, book

    def test_each_row_of_a_shared_folder_gets_its_own_checked_copy_and_the_originals_stay(self):
        a, b, book = self.three_rows()
        before = {f.name: f.read_bytes() for f in self.own.iterdir()}
        part = {a: "training", b: "training", book: "read"}
        problems = {rid: self.lib.check_pages(rid, part[rid]) for rid in part}     # p3.png is new for a and b
        report = move.move_existing(self.lib, self.uploads)
        self.assertEqual([m["id"] for m in report["moved"]], [a, b, book])
        self.assertEqual(report["failed"], [])
        for rid in (a, b, book):
            row = self.lib.get_book(rid)
            folder = Path(row.input_dir if rid != book else row.read_dir)
            self.assertEqual(folder, self.lib.upload_dir(row, self.uploads))
            # every image of the folder, also those that are not pages yet (the page list stays the same)
            self.assertEqual(sorted(p.name for p in folder.iterdir()), ["p1.png", "p2.png", "p3.png"])
            self.assertEqual(self.lib.check_pages(rid, part[rid]), problems[rid])
        self.assertEqual({f.name: f.read_bytes() for f in self.own.iterdir()}, before)
        self.assertEqual(report["old_folders"], [str(self.own.resolve())])
        self.assertTrue((Path(report["backup"]) / "library.db").is_file())
        self.assertIsNone(move.move_existing(self.lib, self.uploads))       # once per library

    def test_pages_lines_and_line_truth_are_unchanged_and_only_the_folder_path_changes(self):
        _, _, book = self.three_rows()
        with self.lib.session() as s:
            page = s.scalars(select(Page).where(Page.book_id == book)).first()
            line = Line(page_id=page.id, number=1, x=0, y=0, w=10, h=10, ink="black", image="lines/p1_L01.png")
            s.add(line)
            s.flush()
            s.add(LineTruth(line_id=line.id, text_dev="क"))
        def rows():
            with self.lib.session() as s:
                return ([(p.id, p.file, p.number, p.sha256) for p in s.scalars(select(Page).order_by(Page.id))],
                        [(t.line_id, t.text_dev) for t in s.scalars(select(LineTruth))])
        before = rows()
        move.move_existing(self.lib, self.uploads, backup=False)
        self.assertEqual(rows(), before)

    def test_a_copy_that_does_not_match_leaves_its_row_on_the_original_and_is_tried_again(self):
        a, b, book = self.three_rows()
        real = move._clone

        def broken(src, dst):
            real(src, dst)
            if dst.parent.name == self.lib.get_book(b).folder:
                dst.write_bytes(b"not the page")
        with mock.patch.object(move, "_clone", broken):
            report = move.move_existing(self.lib, self.uploads, backup=False)
        self.assertEqual([f["id"] for f in report["failed"]], [b])
        self.assertIn("does not match", report["failed"][0]["problem"])
        self.assertEqual(self.lib.get_book(b).input_dir, str(self.own.resolve()))
        self.assertEqual(list(self.lib.upload_dir(self.lib.get_book(b), self.uploads).iterdir()), [])
        self.assertEqual(report["old_folders"], [])                           # b still reads it
        self.assertEqual(move.load_state(self.lib)["existing"], {"done": False, "pending": [b]})
        again = move.move_existing(self.lib, self.uploads, backup=False)
        self.assertEqual([m["id"] for m in again["moved"]], [b])
        self.assertEqual(again["old_folders"], [str(self.own.resolve())])
        self.assertTrue(move.load_state(self.lib)["existing"]["done"])

    def test_a_missing_page_image_keeps_the_row_where_it_is_and_says_so_once(self):
        a = self.lib.create_book("A", self.own).id
        self.pages(a, ["p1.png"])
        with self.lib.session() as s:
            s.add(Page(book_id=a, file="gone.png", part="training", folder="training", number=2, sha256="x"))
        report = move.move_existing(self.lib, self.uploads)
        self.assertEqual(report["moved"], [])
        self.assertIn("1 page image missing", report["failed"][0]["problem"])
        self.assertEqual(report["backup"], "")                                # nothing was tried: no backup
        self.assertEqual(self.lib.get_book(a).input_dir, str(self.own.resolve()))
        self.assertIsNotNone(move.notice(self.lib))
        move.notice_seen(self.lib)
        move.move_existing(self.lib, self.uploads)                            # the same failure: no new notice
        self.assertIsNone(move.notice(self.lib))

    def test_not_moved_a_pdf_book_a_row_in_its_upload_folder_and_rows_made_after_the_first_start(self):
        pdf_book = self.lib.create_book("PDF", kind=BOOK).id
        with self.lib.session() as s:
            s.get(Book, pdf_book).read_pdf = "scan.pdf"
        self.assertIsNone(move.move_existing(self.lib, self.uploads))
        later = self.lib.create_book("Later", self.own).id                     # *Use this folder*: stays there
        self.assertIsNone(move.move_existing(self.lib, self.uploads))
        self.assertEqual(self.lib.get_book(later).input_dir, str(self.own.resolve()))

    def test_the_command_shows_and_changes_nothing_without_run(self):
        a = self.lib.create_book("A", self.own).id
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            self.assertEqual(move.main(["--library", str(self.tmp / "lib")]), 0)
        self.assertIn("Nothing was changed", out.getvalue())
        self.assertIn("3 page images", out.getvalue())
        self.assertEqual(self.lib.get_book(a).input_dir, str(self.own.resolve()))


class MoveUploads(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.settings = self.tmp / "settings.json"
        self.lib = Library(self.tmp / "lib")
        self.client = TestClient(create_app(self.lib, "", AppContext(settings_file=self.settings)))

    def tearDown(self):
        self.lib.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, kind, name):
        r = self.client.post(f"/api/{kind}", json={"name": name, "writing": "printed"})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["id"]

    def upload(self, kind, row_id, name, data):
        r = self.client.post(f"/api/{kind}/{row_id}/upload", params={"name": name}, content=data)
        self.assertEqual(r.status_code, 200, r.text)

    def wait(self, job):
        for _ in range(200):
            job = self.client.get(f"/api/jobs/{job['id']}").json()
            if job["status"] != "running":
                return job
            time.sleep(0.05)
        self.fail("the job did not end")

    def test_changing_the_uploads_folder_moves_the_uploaded_pages_and_keeps_the_old_ones(self):
        d, b = self.make("datasets", "D"), self.make("books", "B")
        self.upload("datasets", d, "a.png", png())
        self.upload("books", b, "b.png", png(100))
        old = Path(self.lib.get_book(d).input_dir)
        new = self.tmp / "elsewhere"
        r = self.client.post("/api/app/uploads", json={"path": str(new)}).json()
        job = self.wait(r["job"])
        self.assertEqual(job["status"], "done", job["error"])
        self.assertEqual(job["result"]["files"], 2)
        self.assertEqual(Path(self.lib.get_book(d).input_dir), new.resolve() / "datasets" / old.name)
        self.assertTrue(Path(self.lib.get_book(b).read_dir, "b.png").is_file())
        self.assertTrue((old / "a.png").is_file())                             # the old folder stays
        self.assertEqual(load_settings(self.settings)["uploads"], str(new))
        self.assertTrue(self.client.get(f"/api/datasets/{d}/page-list").json()["owned"])

    def test_a_problem_moves_nothing_and_keeps_the_setting(self):
        d, e = self.make("datasets", "D"), self.make("datasets", "E")
        self.upload("datasets", d, "a.png", png())
        self.upload("datasets", e, "a.png", png())
        new = self.tmp / "elsewhere"
        clash = new / "datasets" / self.lib.get_book(e).folder
        clash.mkdir(parents=True)
        (clash / "a.png").write_bytes(b"something else")
        before = self.lib.get_book(d).input_dir
        job = self.wait(self.client.post("/api/app/uploads", json={"path": str(new)}).json()["job"])
        self.assertEqual(job["status"], "failed")
        self.assertIn("exists already", job["error"])
        self.assertEqual(self.lib.get_book(d).input_dir, before)
        self.assertFalse((new / "datasets" / self.lib.get_book(d).folder / "a.png").exists())   # its copy removed
        self.assertNotIn("uploads", load_settings(self.settings))

    def test_nothing_uploaded_yet_saves_the_setting_at_once(self):
        r = self.client.post("/api/app/uploads", json={"path": str(self.tmp / "x")}).json()
        self.assertIsNone(r["job"])
        self.assertEqual(load_settings(self.settings)["uploads"], str(self.tmp / "x"))

    def test_the_new_folder_inside_the_old_one_is_refused(self):
        old = self.tmp / "lib" / "uploads"
        with self.assertRaises(LibraryError):
            move.move_uploads(self.lib, old, old / "inner")

    def test_the_notice_of_the_move_is_shown_until_seen(self):
        own = self.tmp / "own"
        own.mkdir()
        (own / "p.png").write_bytes(png())
        self.lib.create_book("A", own)
        save_settings({}, self.settings)
        move.move_existing(self.lib, self.tmp / "lib" / "uploads", backup=False)
        info = self.client.get("/api/app").json()
        self.assertEqual(info["page_move"]["moved"][0]["files"], 1)
        self.client.post("/api/app/page-move/seen")
        self.assertIsNone(self.client.get("/api/app").json()["page_move"])


class AppWideJob(unittest.TestCase):
    def test_a_job_of_the_whole_library_blocks_row_jobs_and_waits_for_them(self):
        jobs = Jobs(None)
        jobs._jobs["m"] = Job(id="m", book_id=APP, kind="move_uploads")
        with self.assertRaisesRegex(LibraryError, "being moved"):
            jobs.start(3, "capture", lambda p, c: {})
        jobs._jobs["m"].status = "done"
        jobs._jobs["c"] = Job(id="c", book_id=3, kind="capture")
        with self.assertRaisesRegex(LibraryError, "wait until it ends"):
            jobs.start(APP, "move_uploads", lambda p, c: {})


if __name__ == "__main__":
    unittest.main()

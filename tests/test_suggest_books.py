"""C13: suggestions from the labelled groups of other books."""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import appbook                                                                  # noqa: E402
from fastapi.testclient import TestClient                                      # noqa: E402
from letter_extractor.app import actions                                       # noqa: E402
from letter_extractor.app.api import create_app                                # noqa: E402
from letter_extractor.app.db import Book, LetterGroup, OcrReading, Sample      # noqa: E402
from letter_extractor.app.library import LibraryError                          # noqa: E402
from letter_extractor.app.suggest import (engines, group_suggestions, reference_books, run_books,   # noqa: E402
                                          suggestion_accuracy)
from letter_extractor.config import Config                                     # noqa: E402
from sqlalchemy import func, select                                            # noqa: E402

LETTERS = "कखगघचछजझटठडढतथदधनपफबभमयरलवशसह"


class BooksTestCase(unittest.TestCase):
    """Two books of the same (synthetic) pages: book A is labelled, book B learns from it."""

    def setUp(self):
        self.tmp, self.lib, self.a, self.pages = appbook.fresh_copy()
        self.b = self.lib.create_book("Second", self.pages).id
        self.lib.capture(self.b)
        with self.lib.session() as s:
            self.groups_a = [g.id for g in s.scalars(select(LetterGroup).where(LetterGroup.book_id == self.a)
                                                     .order_by(LetterGroup.id))]
        self.label = {}
        for i, gid in enumerate(self.groups_a):
            if self.size(gid) >= 2:
                actions.set_label(self.lib, self.a, gid, LETTERS[i % len(LETTERS)])
                self.label[gid] = LETTERS[i % len(LETTERS)]

    def tearDown(self):
        appbook.cleanup(self.tmp, self.lib)

    def size(self, gid):
        with self.lib.session() as s:
            return s.scalar(select(func.count(Sample.id)).where(Sample.group_id == gid, Sample.deleted.is_(False)))

    def ocr(self, book_id):
        with self.lib.session() as s:
            book = s.get(Book, book_id)
            return group_suggestions(s, book, self.lib.book_config(book))


class ReferenceTests(BooksTestCase):
    def test_reference_books_and_defaults(self):
        refs = reference_books(self.lib, self.b)
        self.assertEqual([(r["id"], r["comparable"], r["default"]) for r in refs], [(self.a, True, True)])
        self.assertEqual(refs[0]["labelled"], len(self.label))
        self.assertEqual(reference_books(self.lib, self.a), [])             # B has no labels

    def test_other_writing_is_not_used_by_default(self):
        self.lib.set_book_writing(self.a, "printed")
        self.assertFalse(reference_books(self.lib, self.b)[0]["default"])
        with self.assertRaises(LibraryError):
            run_books(self.lib, self.b)
        self.assertGreater(run_books(self.lib, self.b, [self.a])["samples_matched"], 0)   # chosen explicitly

    def test_other_fingerprint_settings_cannot_be_compared(self):
        self.lib.set_book_config(self.a, Config(normalize_size=32))
        ref = reference_books(self.lib, self.b)[0]
        self.assertEqual((ref["comparable"], ref["default"]), (False, False))
        with self.assertRaises(LibraryError) as e:
            run_books(self.lib, self.b, [self.a])
        self.assertIn("not comparable", str(e.exception))


class ReadingTests(BooksTestCase):
    def test_the_second_book_gets_the_labels_of_the_first(self):
        r = run_books(self.lib, self.b)
        self.assertGreater(r["samples_matched"], 0.9 * r["samples"])
        self.assertGreater(r["groups_with_suggestion"], 0)
        with self.lib.session() as s:
            labels = set(self.label.values())
            texts = set(s.scalars(select(OcrReading.text_dev)))
            self.assertTrue(texts <= labels)
        ocr = self.ocr(self.b)
        suggested = [v["suggestion"] for v in ocr.values() if v["suggestion"]]
        self.assertTrue(suggested)
        self.assertTrue(all(sg["engine"] == "books" for sg in suggested))

    def test_suggestions_are_right_when_the_pages_are_the_same(self):
        run_books(self.lib, self.b)
        # label B's groups with what A's labels say about the same pages: the check counts them right
        with self.lib.session() as s:
            pairs = {}
            for smp in s.scalars(select(Sample).where(Sample.book_id == self.b, Sample.group_id.is_not(None))):
                twin = s.scalar(select(Sample.group_id).where(Sample.book_id == self.a, Sample.page_id.is_not(None),
                                                              Sample.x == smp.x, Sample.y == smp.y))
                if twin in self.label:
                    pairs.setdefault(smp.group_id, self.label[twin])
        for gid, lab in pairs.items():
            try:
                actions.set_label(self.lib, self.b, gid, lab)
            except actions.ActionError:
                pass                                                      # one label, one group
        with self.lib.session() as s:
            book = s.get(Book, self.b)
            acc = suggestion_accuracy(s, book, self.lib.book_config(book), "books")
        self.assertEqual(acc["engine"], "books")
        self.assertGreater(acc["suggested"], 0)
        self.assertEqual(acc["right"], acc["suggested"])

    def test_a_new_run_replaces_the_old_and_the_main_reader_follows_the_writing(self):
        run_books(self.lib, self.b)
        run_books(self.lib, self.b)
        with self.lib.session() as s:
            from letter_extractor.app.db import OcrRun
            self.assertEqual(s.scalar(select(func.count(OcrRun.id)).where(OcrRun.book_id == self.b)), 1)
            self.assertEqual(engines(s, s.get(Book, self.b)), ["books"])

    def test_agreement_and_other_suggestion(self):
        run_books(self.lib, self.b)
        from test_suggest import FakeTesseract
        from letter_extractor.app.suggest import run_tesseract
        with self.lib.session() as s:
            ocr_books = self.ocr(self.b)
            gid, entry = next((g, v) for g, v in ocr_books.items() if v["suggestion"])
            agree = entry["suggestion"]["label_dev"]
        # Tesseract reads that group as the same label, every other group as ञ
        run_tesseract(self.lib, self.b, reader=FakeTesseract(self.lib, self.b,
                                                             lambda smp: agree if smp.group_id == gid else "ञ"),
                      workers=1)
        ocr = self.ocr(self.b)
        self.assertEqual(ocr[gid]["suggestion"]["agree"], ["books", "tesseract"])
        others = [v for g, v in ocr.items() if g != gid and v["suggestion"] and v["other_suggestion"]]
        self.assertTrue(others)
        self.assertEqual(others[0]["other_suggestion"]["label_dev"], "ञ")
        self.assertEqual(others[0]["other_suggestion"]["engine"], "tesseract")


class ApiTests(BooksTestCase):
    def test_routes(self):
        client = TestClient(create_app(self.lib, "t"))
        h = {"X-Token": "t"}
        refs = client.get(f"/api/books/{self.b}/reference-books", headers=h).json()
        self.assertEqual(refs[0]["id"], self.a)
        job = client.post(f"/api/books/{self.b}/suggest", headers=h, json={"engine": "books"}).json()
        t0 = time.time()
        while job["status"] == "running" and time.time() - t0 < 60:
            time.sleep(0.2)
            job = client.get(f"/api/jobs/{job['id']}", headers=h).json()
        self.assertEqual(job["status"], "done", job["error"])
        groups = client.get(f"/api/books/{self.b}/groups", headers=h).json()
        self.assertTrue(any(g["suggestion"] and g["suggestion"]["engine"] == "books" for g in groups))
        self.assertIn("other_suggestion", groups[0])
        acc = client.get(f"/api/books/{self.b}/suggestion-accuracy?engine=books", headers=h).json()
        self.assertEqual(acc["engine"], "books")
        r = client.post(f"/api/books/{self.a}/suggest", headers=h, json={"engine": "books"})
        self.assertEqual(r.status_code, 400)                              # nothing labelled elsewhere
        client.close()


if __name__ == "__main__":
    unittest.main()

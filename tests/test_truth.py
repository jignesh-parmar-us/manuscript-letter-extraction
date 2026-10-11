"""The line truth screen: checked text of whole lines, independent of the letter cuts."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import appbook                                                      # noqa: E402
from fastapi.testclient import TestClient                           # noqa: E402
from letter_extractor.app.api import create_app                    # noqa: E402
from letter_extractor.app.db import Line, LineTruth, Page           # noqa: E402
from letter_extractor.app.library import LibraryError              # noqa: E402
from letter_extractor.app.truth import book_progress, page_lines, save_truth, tesseract_text   # noqa: E402
from sqlalchemy import func, select                                 # noqa: E402


class TruthTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.lib, self.book, _ = appbook.fresh_copy()
        with self.lib.session() as s:
            self.page = s.scalar(select(Page.id).where(Page.book_id == self.book).order_by(Page.id))
            self.line = s.scalar(select(Line.id).where(Line.page_id == self.page).order_by(Line.number))

    def tearDown(self):
        appbook.cleanup(self.tmp, self.lib)

    def test_checked_text_is_stored_as_devanagari_and_counted(self):
        got = save_truth(self.lib, self.line, "  સ્વામિનારાયણ   ભગવાન ", "स्वामिनारायण भगवान")
        self.assertEqual((got["truth_dev"], got["truth_guj"]), ("स्वामिनारायण भगवान", "સ્વામિનારાયણ ભગવાન"))
        lines = page_lines(self.lib, self.page)
        self.assertEqual(lines[0]["truth_dev"], "स्वामिनारायण भगवान")
        self.assertTrue(all(x["truth_dev"] is None for x in lines[1:]))
        progress = book_progress(self.lib, self.book, part="training")
        self.assertEqual(progress["checked"], 1)
        self.assertEqual(progress["lines"], len(lines) + sum(p["lines"] for p in progress["pages"][1:]))
        self.assertIsNone(save_truth(self.lib, self.line, "   "))                    # empty: not checked any more
        with self.lib.session() as s:
            self.assertEqual(s.scalar(select(func.count(LineTruth.id))), 0)
        with self.assertRaises(LibraryError):
            save_truth(self.lib, self.line, "abc")

    def test_tesseract_reads_the_whole_line_once(self):
        calls = []
        def reader(rgb):
            calls.append(rgb.shape)
            return SimpleNamespace(text="नारायण")
        self.assertEqual(tesseract_text(self.lib, self.line, reader)["text_guj"], "નારાયણ")
        tesseract_text(self.lib, self.line, reader)
        self.assertEqual(len(calls), 1)                                                # kept in memory

    def test_api(self):
        c = TestClient(create_app(self.lib, "t"))
        h = {"X-Token": "t"}
        with mock.patch("letter_extractor.app.suggest.tesseract_reader",
                        return_value=lambda rgb: SimpleNamespace(text="भगवान")):
            self.assertEqual(c.get(f"/api/lines/{self.line}/tesseract", headers=h).json()["text_dev"], "भगवान")
        lines = c.get(f"/api/pages/{self.page}/truth", headers=h).json()
        self.assertTrue(lines[0]["image"].startswith(f"/files/books/{self.book}/"))
        r = c.put(f"/api/lines/{self.line}/truth", json={"text": "ભગવાન", "tesseract": "भगवान"}, headers=h).json()
        self.assertEqual(r["truth_dev"], "भगवान")
        self.assertEqual(c.get(f"/api/books/{self.book}/truth?part=training", headers=h).json()["checked"], 1)
        self.assertEqual(c.put(f"/api/lines/{self.line}/truth", json={"text": ""}, headers=h).json()["truth_dev"], None)
        c.close()


if __name__ == "__main__":
    unittest.main()

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


class LatestCheckTests(unittest.TestCase):
    """The latest check holds everywhere: Line truth and Whole lines (Tesseract's and our reader's views)."""

    def setUp(self):
        from letter_extractor.app.wholelines import read_book_lines
        from letter_extractor.config import Config
        from test_wholelines import READ
        self.tmp, self.lib, self.book, _ = appbook.fresh_copy()
        self.lib.set_book_config(self.book, Config(language_model=False))
        with self.lib.session() as s:
            self.page = s.scalar(select(Page.id).where(Page.book_id == self.book).order_by(Page.id))
            self.lines = list(s.scalars(select(Line.id).where(Line.page_id == self.page).order_by(Line.number)))
        self.read = lambda: read_book_lines(self.lib, self.book, [self.page], reader=lambda rgb: READ)

    def tearDown(self):
        appbook.cleanup(self.tmp, self.lib)

    def whole(self, line_id):
        from letter_extractor.app.wholelines import page_whole_lines
        x = next(x for x in page_whole_lines(self.lib, self.page)["lines"] if x["line_id"] == line_id)
        return x["edited_dev"], x["reviewed"]

    def truth(self, line_id):
        return next(x["truth_dev"] for x in page_lines(self.lib, self.page) if x["line_id"] == line_id)

    def test_a_check_in_line_truth_shows_in_whole_lines(self):
        self.read()
        save_truth(self.lib, self.lines[0], "नारायण भग")
        self.assertEqual(self.whole(self.lines[0]), ("नारायण भग", True))
        save_truth(self.lib, self.lines[0], "")                                  # removed: un-reviewed, kept
        self.assertEqual(self.whole(self.lines[0]), ("नारायण भग", False))

    def test_the_latest_check_wins_both_ways(self):
        from letter_extractor.app.wholelines import set_whole_line
        self.read()
        set_whole_line(self.lib, self.lines[0], text="नारायण", reviewed=True)
        self.assertEqual(self.truth(self.lines[0]), "नारायण")
        save_truth(self.lib, self.lines[0], "नारायण भग")                        # later, in Line truth
        self.assertEqual(self.whole(self.lines[0]), ("नारायण भग", True))
        set_whole_line(self.lib, self.lines[0], text="नारायणभग")                 # later again, in Whole lines
        self.assertEqual(self.truth(self.lines[0]), "नारायणभग")
        set_whole_line(self.lib, self.lines[0], reviewed=False)                  # un-reviewed: the correction stays
        self.assertEqual((self.whole(self.lines[0]), self.truth(self.lines[0])), (("नारायणभग", False), None))

    def test_a_line_checked_before_it_is_read_whole(self):
        save_truth(self.lib, self.lines[1], "भग")                                # not read whole yet: nothing to sync
        self.read()
        self.assertEqual(self.whole(self.lines[1]), ("भग", True))

    def test_lines_checked_earlier_are_synced_once(self):
        from letter_extractor.app.truth import sync_existing
        self.read()
        for lid, text in zip(self.lines[:2], ["नारायण", "भग"]):
            save_truth(self.lib, lid, text, sync=False)                          # as before the rule
        before = sync_existing(self.lib, self.book)
        self.assertEqual([(x["line_id"], x["truth_dev"], x["reviewed"]) for x in before],
                         [(self.lines[0], "नारायण", False), (self.lines[1], "भग", False)])
        self.assertEqual(self.whole(self.lines[0]), ("", False))                  # listing changes nothing
        sync_existing(self.lib, self.book, apply=True)
        self.assertEqual([self.whole(x) for x in self.lines[:2]], [("नारायण", True), ("भग", True)])
        self.assertEqual(sync_existing(self.lib, self.book), [])


if __name__ == "__main__":
    unittest.main()

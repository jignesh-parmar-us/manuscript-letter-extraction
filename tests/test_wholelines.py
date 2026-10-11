"""Reading Read Book lines whole with Tesseract (no letter cutting), with the language model's correction."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import appbook                                                      # noqa: E402
from fastapi.testclient import TestClient                           # noqa: E402
from letter_extractor.app.api import create_app                    # noqa: E402
from letter_extractor.app.db import Line, Page                      # noqa: E402
from letter_extractor.app.wholelines import book_whole_lines, page_whole_lines, read_book_lines   # noqa: E402
from letter_extractor.config import Config                          # noqa: E402
from letter_extractor.ocr.language import LanguageModel             # noqa: E402
from letter_extractor.ocr.tesseract import Char, LineReading, Word   # noqa: E402
from sqlalchemy import select                                       # noqa: E402


def reading(*words):
    """A Tesseract reading: words of (character, confidence, alternatives)."""
    out = []
    for w in words:
        chars = [Char(t, (0, 0, 10, 10), conf, alts) for t, conf, alts in w]
        out.append(Word((0, 0, 10, 10), min(c.conf for c in chars), chars))
    return LineReading(out, "", 1.0)


READ = reading([("न", 96.0, []), ("ा", 95.0, []), ("र", 97.0, []), ("ा", 96.0, []), ("य", 97.0, []),
                ("व", 60.0, [("ण", 40.0)])],                       # ...नारायव, with ण as Tesseract's second choice
               [("भ", 98.0, []), ("ग", 98.0, [])])


class WholeLineTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.lib, self.book, _ = appbook.fresh_copy()
        with self.lib.session() as s:
            self.page = s.scalar(select(Page.id).where(Page.book_id == self.book).order_by(Page.id))
            self.lines = s.scalar(select(Line.id).where(Line.page_id == self.page).order_by(Line.number))

    def tearDown(self):
        appbook.cleanup(self.tmp, self.lib)

    def test_lines_are_read_whole_and_kept(self):
        self.lib.set_book_config(self.book, Config(language_model=False))
        r = read_book_lines(self.lib, self.book, [self.page], reader=lambda rgb: READ)
        self.assertEqual(r["pages"], 1)
        got = page_whole_lines(self.lib, self.page)
        first = got["lines"][0]
        self.assertEqual(first["text_dev"], "नारायव भग")
        self.assertEqual([x["text_dev"] for x in first["aksharas"]], ["ना", "रा", "य", "व", "भ", "ग"])
        self.assertTrue(first["aksharas"][4]["space"])                         # a new word
        self.assertTrue(first["aksharas"][3]["uncertain"])                     # 60: below 75
        self.assertNotIn("lm_dev", first["aksharas"][3])
        self.assertEqual(book_whole_lines(self.lib, self.book, part="training"), [{"page_id": self.page,
                                                                                    "lines": len(got["lines"])}])

    def test_the_language_model_may_take_tesseracts_second_choice(self):
        lm = LanguageModel().add_all(["नारायण भगवान"] * 20)
        with mock.patch("letter_extractor.app.dictionary.book_model", return_value=lm):
            read_book_lines(self.lib, self.book, [self.page], reader=lambda rgb: READ)
        x = page_whole_lines(self.lib, self.page)["lines"][0]["aksharas"][3]
        self.assertEqual((x["text_dev"], x["lm_dev"]), ("व", "ण"))              # Tesseract's reading is kept beside it

    def test_api_and_downloads(self):
        self.lib.set_book_config(self.book, Config(language_model=False))
        c = TestClient(create_app(self.lib, "t"))
        h = {"X-Token": "t"}
        self.assertEqual(c.get(f"/api/pages/{self.page}/whole-lines", headers=h).status_code, 404)
        with mock.patch("letter_extractor.app.wholelines.tesseract_reader", return_value=lambda rgb: READ):
            job = c.post(f"/api/books/{self.book}/convert", json={"part": "training", "page_ids": [self.page],
                                                                   "mode": "lines"}, headers=h).json()
            for _ in range(200):
                job = c.get(f"/api/jobs/{job['id']}", headers=h).json()
                if job["status"] != "running":
                    break
        self.assertEqual(job["status"], "done", job.get("error"))
        self.assertEqual(c.get(f"/api/pages/{self.page}/whole-lines", headers=h).json()["page_id"], self.page)
        txt = c.get(f"/files/texts/{self.book}?readers=lines&part=training&marker=none&script=devanagari"
                    f"&page_id={self.page}&token=t").text
        self.assertIn("नारायव भग", txt)
        marked = c.get(f"/files/texts/{self.book}?readers=lines&part=training&marker=mark&page_id={self.page}&token=t").text
        self.assertIn("નારાય[?] ભગ", marked)
        c.close()


if __name__ == "__main__":
    unittest.main()

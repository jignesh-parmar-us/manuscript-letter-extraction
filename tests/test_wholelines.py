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

    def test_aksharas_keep_their_box_on_the_page(self):
        self.lib.set_book_config(self.book, Config(language_model=False))
        read_book_lines(self.lib, self.book, [self.page], reader=lambda rgb: READ)
        with self.lib.session() as s:
            ln = s.get(Line, self.lines)
            ox, oy = max(0, ln.x - 6), max(0, ln.y - 6)                       # the line image's corner on the page
        x = page_whole_lines(self.lib, self.page)["lines"][0]["aksharas"][0]
        self.assertEqual(x["box"], [ox, oy, 10, 10])

    def test_a_line_is_corrected_and_reviewed_and_becomes_a_checked_line(self):
        from letter_extractor.app.db import LineTruth
        from letter_extractor.app.wholelines import set_whole_line
        self.lib.set_book_config(self.book, Config(language_model=False))
        read_book_lines(self.lib, self.book, [self.page], reader=lambda rgb: READ)
        got = set_whole_line(self.lib, self.lines, text="નારાયણ ભગ")
        self.assertEqual((got["edited_dev"], got["reviewed"]), ("नारायण भग", False))
        with self.lib.session() as s:
            self.assertIsNone(s.scalar(select(LineTruth).where(LineTruth.line_id == self.lines)))
        set_whole_line(self.lib, self.lines, reviewed=True)
        with self.lib.session() as s:
            self.assertEqual(s.scalar(select(LineTruth.text_dev).where(LineTruth.line_id == self.lines)), "नारायण भग")
        line = page_whole_lines(self.lib, self.page)["lines"][0]
        self.assertEqual((line["edited_dev"], line["reviewed"]), ("नारायण भग", True))
        read_book_lines(self.lib, self.book, [self.page], reader=lambda rgb: READ)    # reading again keeps them
        self.assertTrue(page_whole_lines(self.lib, self.page)["lines"][0]["reviewed"])
        set_whole_line(self.lib, self.lines, reviewed=False)
        with self.lib.session() as s:
            self.assertIsNone(s.scalar(select(LineTruth).where(LineTruth.line_id == self.lines)))
        set_whole_line(self.lib, self.lines, text="", reviewed=True, shown="नारायण भगवान")   # as shown
        with self.lib.session() as s:
            self.assertEqual(s.scalar(select(LineTruth.text_dev).where(LineTruth.line_id == self.lines)), "नारायण भगवान")

    def test_the_line_search_marks_where_it_reads_differently(self):
        from letter_extractor.app import linesearch
        from letter_extractor.app.library import LibraryError
        self.lib.set_book_config(self.book, Config(language_model=False))
        with self.assertRaises(LibraryError):                                  # nothing read whole yet
            linesearch.search_book(self.lib, self.book, [self.page])
        read_book_lines(self.lib, self.book, [self.page], reader=lambda rgb: READ)
        with mock.patch.object(linesearch, "_load", return_value=(None, {"typical_width": 30.0, "widths": {}})), \
                mock.patch.object(linesearch, "read_line", return_value=("नारायण भग", [], {})) as read, \
                mock.patch.object(linesearch, "train_line_reader") as train:
            r = linesearch.search_book(self.lib, self.book, [self.page])
        train.assert_not_called()                                              # the book has its reader
        self.assertEqual(r["pages"], 1)
        self.assertGreater(read.call_count, 0)
        first = page_whole_lines(self.lib, self.page)["lines"][0]
        self.assertTrue(first["searched"])
        marks = [(x["text_dev"], x.get("search_dev")) for x in first["aksharas"] if x["uncertain"]]
        self.assertEqual(marks, [("व", "ण")])                                  # 60 for व, and the line search read ण
        self.assertEqual(first["aksharas"][3]["search_guj"], "ણ")

    def test_our_reader_shows_its_own_reading_with_places_and_shared_corrections(self):
        from letter_extractor.app import linesearch
        from letter_extractor.app.wholelines import set_whole_line
        from letter_extractor.ocr.segment import Step
        self.lib.set_book_config(self.book, Config(language_model=False))
        read_book_lines(self.lib, self.book, [self.page], reader=lambda rgb: READ)
        self.assertIsNone(page_whole_lines(self.lib, self.page, "search"))       # our reader has not read it
        self.assertEqual(book_whole_lines(self.lib, self.book, part="training", engine="search"), [])
        steps = [Step(0, 10, "ना"), Step(10, 20, "रा"), Step(20, 30, "य"), Step(30, 40, "ण"),
                 Step(60, 70, "भ", space=True), Step(70, 80, "ग")]
        with mock.patch.object(linesearch, "_load", return_value=(None, {"typical_width": 30.0, "widths": {}})), \
                mock.patch.object(linesearch, "read_line", return_value=("नारायण भग", steps, {})):
            linesearch.search_book(self.lib, self.book, [self.page])
        got = page_whole_lines(self.lib, self.page, "search")
        first = got["lines"][0]
        self.assertEqual(first["text_dev"], "नारायण भग")
        self.assertEqual([x["text_dev"] for x in first["aksharas"]], ["ना", "रा", "य", "ण", "भ", "ग"])
        self.assertEqual([x["space"] for x in first["aksharas"]], [False] * 4 + [True, False])
        self.assertEqual([(x["text_dev"], x.get("other_dev")) for x in first["aksharas"] if x["uncertain"]],
                         [("ण", "व")])                                         # Tesseract read व there
        self.assertIsNotNone(first["aksharas"][0]["box"])                      # its place on the page
        self.assertEqual(first["aksharas"][4]["box"][0] - first["aksharas"][0]["box"][0], 60)
        self.assertTrue(book_whole_lines(self.lib, self.book, part="training", engine="search"))
        set_whole_line(self.lib, self.lines, text="नारायण भगवान", reviewed=True)    # one correction per line
        for engine in ("tesseract", "search"):
            line = page_whole_lines(self.lib, self.page, engine)["lines"][0]
            self.assertEqual((line["edited_dev"], line["reviewed"]), ("नारायण भगवान", True))

    def test_the_reader_says_when_the_reviewed_letters_changed(self):
        from letter_extractor.app import linesearch
        from letter_extractor.app.db import LetterGroup, Sample
        reader = mock.MagicMock()
        meta = {"letters": 30, "labels": 3, "typical_width": 30.0, "widths": {}}
        self.assertIsNone(linesearch.line_reader_info(self.lib, self.book))
        with mock.patch.object(linesearch, "_train", return_value=(reader, meta)):
            linesearch.train_line_reader(self.lib, self.book)
        self.assertFalse(linesearch.line_reader_info(self.lib, self.book)["changed"])
        with self.lib.session() as s:
            g = s.scalar(select(LetterGroup).join(Sample, Sample.group_id == LetterGroup.id)
                         .where(LetterGroup.book_id == self.book, Sample.line_id.is_not(None)))
            g.label_dev, g.status = "क", "reviewed"
        self.assertTrue(linesearch.line_reader_info(self.lib, self.book)["changed"])

    def test_the_measure_leaves_out_the_tested_pages(self):
        from letter_extractor.app import linesearch
        from letter_extractor.app.wholelines import set_whole_line
        self.lib.set_book_config(self.book, Config(language_model=True))
        with mock.patch("letter_extractor.app.dictionary.book_model", return_value=LanguageModel()):
            read_book_lines(self.lib, self.book, [self.page], reader=lambda rgb: READ)
        with self.lib.session() as s:
            page = s.get(Page, self.page)
            page.part, file = "read", page.file                                # the checked lines are Read Book lines
        set_whole_line(self.lib, self.lines, text="नारायण भग", reviewed=True)
        meta = {"letters": 30, "labels": 3, "typical_width": 30.0, "widths": {}}
        with mock.patch.object(linesearch, "_train", return_value=(None, meta)) as train, \
                mock.patch("letter_extractor.app.dictionary.book_model_without", return_value=LanguageModel()) as lm, \
                mock.patch.object(linesearch, "read_line", return_value=("नारायण भग", [], {})):
            r = linesearch.measure(self.lib, self.book)
        self.assertEqual(train.call_args.args[2], [file])                      # trained without the tested page
        self.assertEqual(lm.call_args.args[2], [file])
        self.assertEqual((r["folds"], r["lines"]), (1, 1))
        self.assertEqual(r["cer"]["ours"], 0.0)
        self.assertGreater(r["cer"]["tesseract"], 0.0)                         # व for ण
        self.assertEqual((r["mistakes"], r["caught"]), (1, 1))                 # the mark falls on the mistake
        self.assertEqual(linesearch.last_measure(self.lib, self.book)["line_results"][0]["truth"], "नारायण भग")

    def test_border_marks_at_the_line_edges_are_left_out(self):
        from letter_extractor.app.wholelines import trim_edges
        aks = [["|", 40.0, False], ["!", 30.0, True], ["ना", 96.0, True], ["।", 90.0, False], ["]", 20.0, True]]
        self.assertEqual([a[0] for a in trim_edges(aks)], ["ना", "।"])
        self.assertFalse(trim_edges(aks)[0][2])                                  # no gap before the first akshara
        self.assertEqual(trim_edges([["|", 40.0, False]]), [])

    def test_disagreements(self):
        from letter_extractor.app.linesearch import disagreements
        self.assertEqual(disagreements(["ना", "रा", "य"], "नारा य"), [None, None, None])
        self.assertEqual(disagreements(["ना", "रा", "व"], "नाराण"), [None, None, "ण"])
        self.assertEqual(disagreements(["ना", "रा", "य"], "ना"), [None, "", ""])          # read nothing there
        self.assertEqual(disagreements(["ना", "व"], "नाकख"), [None, ""])                  # 1 against 2: no single reading

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
        r = c.put(f"/api/lines/{self.lines}/whole", json={"text": "नारायण भग", "reviewed": True}, headers=h).json()
        self.assertTrue(r["reviewed"])
        txt = c.get(f"/files/texts/{self.book}?readers=lines&part=training&marker=mark&script=devanagari"
                    f"&page_id={self.page}&token=t").text
        self.assertIn("नारायण भग", txt)                                             # the correction is downloaded
        self.assertEqual(c.get(f"/api/books/{self.book}/line-search", headers=h).json(), {"reader": None, "measure": None})
        self.assertEqual(c.get(f"/api/pages/{self.page}/whole-lines?engine=search", headers=h).status_code, 404)
        self.assertEqual(c.get(f"/api/books/{self.book}/whole-lines?part=training&engine=search", headers=h).json(), [])
        c.close()


if __name__ == "__main__":
    unittest.main()

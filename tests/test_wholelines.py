"""Reading Read Book lines whole with Tesseract (no letter cutting), with the language model's correction."""
import io
import sys
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import appbook                                                      # noqa: E402
from fastapi.testclient import TestClient                           # noqa: E402
from letter_extractor.app.api import create_app                    # noqa: E402
from letter_extractor.app.db import Book, Line, Page                # noqa: E402
from letter_extractor.app.wholelines import book_whole_lines, page_whole_lines, read_book_lines   # noqa: E402
from letter_extractor.config import Config                          # noqa: E402
from letter_extractor.ocr.language import LanguageModel             # noqa: E402
from letter_extractor.ocr.tesseract import Char, LineReading, Word   # noqa: E402
from sqlalchemy import func, select                                 # noqa: E402


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
        line = page_whole_lines(self.lib, self.page)["lines"][0]
        self.assertEqual(line["aksharas"][0]["box"], [ox, oy, 10, 10])
        self.assertEqual(line["image_box"][:2], [ox, oy])                     # the line image starts there
        with self.lib.session() as s:
            ln = s.get(Line, self.lines)
            self.assertEqual(line["image"], ln.image)
            self.assertLessEqual(line["image_box"][2], ln.w + 12)

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
        import io, zipfile
        c = TestClient(create_app(self.lib, "t"))
        for fmt in ("txt", "docx"):                                           # downloads: our reader's text
            r = c.get(f"/files/texts/{self.book}?format={fmt}&readers=search&part=training&marker=none"
                      f"&script=devanagari&page_id={self.page}&token=t")
            got = r.text if fmt == "txt" else zipfile.ZipFile(io.BytesIO(r.content)).read("word/document.xml").decode()
            self.assertIn("नारायण", got)
            self.assertNotIn("नारायव", got)                                    # not Tesseract's
        c.close()
        set_whole_line(self.lib, self.lines, text="नारायण भगवान", reviewed=True)    # one correction per line
        for engine in ("tesseract", "search"):
            line = page_whole_lines(self.lib, self.page, engine)["lines"][0]
            self.assertEqual((line["edited_dev"], line["reviewed"]), ("नारायण भगवान", True))

    def test_our_reader_reads_a_page_tesseract_never_read(self):
        from letter_extractor.app import linesearch
        from letter_extractor.ocr.segment import Step
        steps = [Step(0, 10, "ना"), Step(10, 20, "रा")]
        with mock.patch.object(linesearch, "_load", return_value=(None, {"typical_width": 30.0, "widths": {}})), \
                mock.patch.object(linesearch, "read_line", return_value=("नारा", steps, {})):
            linesearch.search_book(self.lib, self.book, [self.page])
        got = page_whole_lines(self.lib, self.page, "search")
        self.assertEqual(got["lines"][0]["text_dev"], "नारा")
        self.assertEqual([x["uncertain"] for x in got["lines"][0]["aksharas"]], [False, False])   # nothing to compare
        self.assertIsNone(page_whole_lines(self.lib, self.page))                 # still not read by Tesseract
        self.assertEqual(book_whole_lines(self.lib, self.book, part="training"), [])
        self.assertTrue(book_whole_lines(self.lib, self.book, part="training", engine="search"))
        self.lib.set_book_config(self.book, Config(language_model=False))
        read_book_lines(self.lib, self.book, [self.page], reader=lambda rgb: READ)   # Tesseract may read later
        self.assertEqual(page_whole_lines(self.lib, self.page)["lines"][0]["text_dev"], "नारायव भग")
        self.assertEqual(page_whole_lines(self.lib, self.page, "search")["lines"][0]["text_dev"], "नारा")

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

    def test_a_page_at_another_scale_is_read_at_the_readers_scale(self):
        import numpy as np
        from letter_extractor.app import linesearch
        self.assertEqual(linesearch.page_scale(105.0, 106.0), 1.0)           # a normal page is read as it is
        self.assertEqual(linesearch.page_scale(0, 106.0), 1.0)               # no spacing known
        self.assertEqual(linesearch.page_scale(42.0, 0), 1.0)                # no training pages
        self.assertAlmostEqual(linesearch.page_scale(42.5, 106.0), 106.0 / 42.5)    # a photo of a card
        self.assertAlmostEqual(linesearch.page_scale(212.0, 106.0), 0.5)             # a larger scan
        m = np.zeros((10, 20), bool)
        m[3:7, 5:15] = True
        self.assertIs(linesearch._scaled(m, 1.0), m)
        big = linesearch._scaled(m, 2.5)
        self.assertEqual(big.shape, (25, 50))
        self.assertTrue(big[12, 25] and not big[0, 0])

    def test_lines_are_read_scaled_and_boxed_in_page_pixels(self):
        import numpy as np
        from letter_extractor.app import linesearch
        from letter_extractor.ocr.segment import Step
        with self.lib.session() as s:
            lid = s.scalar(select(Line.id).where(Line.page_id == self.page))
        c = np.ones((40, 100), bool)
        with mock.patch.object(linesearch, "_line_ink", return_value=(c, 10, 20)) as ink, \
                mock.patch.object(linesearch, "read_line", return_value=("क", [Step(0, 50, "क")], {})) as read:
            got = linesearch._read_lines(self.lib, self.lib.get_book(self.book), [lid], 40.0,
                                         (None, {"typical_width": 54.0, "widths": {}, "spacing": 100.0}), None)
        self.assertEqual(ink.call_args[0][4], 2.5)                           # the ink is scaled by 100 / 40
        self.assertEqual(read.call_args[0][1], 100.0)                        # the spacing with it
        self.assertEqual(got[lid][1][0][2], [10, 20, 20, 16])                    # back in page pixels

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
        data = {"meta": meta}
        with mock.patch.object(linesearch, "_training_set", return_value=data) as train, \
                mock.patch.object(linesearch, "_fit", return_value=None) as fit, \
                mock.patch.object(linesearch, "_learn_folds", return_value={0: {"lines": 0}}) as learn, \
                mock.patch("letter_extractor.app.dictionary.book_model_without", return_value=LanguageModel()) as lm, \
                mock.patch.object(linesearch, "read_line", return_value=("नारायण भग", [], {})):
            r = linesearch.measure(self.lib, self.book)
        fold = self.lib.left_out(self.book, [file])                          # C24: the tested page, resolved
        self.assertIn(self.page, fold)
        self.assertEqual([c.args[2] for c in train.call_args_list], [fold, fold])   # trained without the tested page
        self.assertEqual(learn.call_args.args[2][0][2], fold)                  # learns from no checked line of it
        self.assertEqual(fit.call_args_list[0].kwargs["epochs"], linesearch.BASE_EPOCHS)
        self.assertEqual(lm.call_args.args[2], fold)
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

    def test_letters_on_no_line_are_learned_from_their_picture(self):
        from letter_extractor.app import linesearch
        from letter_extractor.app.db import LetterGroup, Sample
        with self.lib.session() as s:
            rows = s.execute(select(LetterGroup.id).join(Sample, Sample.group_id == LetterGroup.id)
                             .where(LetterGroup.book_id == self.book, Sample.line_id.is_not(None))
                             .group_by(LetterGroup.id).order_by(func.count(Sample.id).desc())).all()
            for (gid,), label in zip(rows[:3], ("क", "ख", "ग")):
                g = s.get(LetterGroup, gid)
                g.label_dev, g.status = label, "labelled"
            like = s.scalars(select(Sample).where(Sample.group_id == rows[0][0])).first()
            made = LetterGroup(book_id=self.book, code="g9999", label_dev="घ", status="labelled")
            s.add(made)
            s.flush()
            s.add(Sample(book_id=self.book, page_id=None, line_id=None, x=0, y=0, w=like.w, h=like.h, source="generated",
                         image=like.image, mask=like.mask, group_id=made.id))
        without = linesearch._training_set(self.lib, self.book, unlined=False)
        got = linesearch._training_set(self.lib, self.book)
        self.assertNotIn("घ", without["classes"])
        self.assertIn("घ", got["classes"])                                       # System generated: learned too
        self.assertEqual(got["meta"]["letters"], without["meta"]["letters"] + 1)
        ci = got["classes"].index("घ")
        self.assertGreaterEqual(int((got["y"] == ci).sum()), 4)                  # its picture and varied copies
        with self.lib.session() as s:
            sig = linesearch._signature(s, s.get(Book, self.book))
            s.scalar(select(Sample).where(Sample.source == "generated")).deleted = True
        with self.lib.session() as s:
            self.assertNotEqual(linesearch._signature(s, s.get(Book, self.book)), sig)        # the notice sees it change

    def test_corrections_add_examples_and_new_labels(self):
        import numpy as np
        from letter_extractor.app.linesearch import NOT_A_LETTER, _with_corrections
        data = {"X": np.zeros((3, 2), np.float32), "y": np.array([0, 1, 2]), "weights": np.ones(3, np.float32),
                "classes": ["क", "ख", NOT_A_LETTER], "meta": {"widths": {"क": 20.0}, "labels": 2}}
        learned = {"X": [np.ones(2, np.float32)] * 2, "labels": ["क", "हे"], "widths": {"हे": [30, 34], "क": [99]}}
        got = _with_corrections(data, learned)
        self.assertEqual(got["classes"], ["क", "ख", "हे", NOT_A_LETTER])        # हे: a label no group has
        self.assertEqual(got["y"].tolist(), [0, 1, 3, 0, 2])                     # the old classes renumbered
        self.assertEqual(got["meta"]["widths"], {"क": 20.0, "हे": 32.0})          # the letters' width kept
        w = got["weights"]
        self.assertAlmostEqual(float(w[0] + w[3]), float(w[1]), places=5)        # every label weighs the same

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
        ticked = c.get(f"/files/texts/{self.book}?readers=lines&part=training&marker=mark&script=devanagari"
                       f"&page_ids={self.page}&token=t")                             # the ticked pages (C19)
        self.assertEqual(ticked.text, txt)
        two = c.get(f"/files/texts/{self.book}?readers=lines&part=training&marker=mark&script=devanagari"
                    f"&page_ids={self.page},999999&token=t").text                  # 999999: not this book's
        self.assertIn("नारायण भग", two)
        self.assertTrue(two.startswith("=== "))                                      # several pages: with headings
        self.assertEqual(c.get(f"/files/texts/{self.book}?readers=lines&part=training&page_ids=999999&token=t")
                         .status_code, 404)                                          # no ticked page of the book
        self.assertEqual(c.get(f"/files/texts/{self.book}?readers=lines&page_ids=1;2&token=t").status_code, 422)
        self.assertEqual(c.get(f"/api/books/{self.book}/line-search", headers=h).json(), {"reader": None, "measure": None,
                                                                                         "quick_measure": None})
        self.assertEqual(c.get(f"/api/pages/{self.page}/whole-lines?engine=search", headers=h).status_code, 404)
        self.assertEqual(c.get(f"/api/books/{self.book}/whole-lines?part=training&engine=search", headers=h).json(), [])
        # a Word file in one of the library's fonts, embedded (custom fonts, T3)
        from test_fonts import GUJARATI, make_font
        font = c.post("/api/fonts/upload", params={"name": "s.ttf"}, content=make_font(GUJARATI, "Saral"), headers=h).json()
        url = f"/files/texts/{self.book}?format=docx&readers=lines&part=training&page_id={self.page}&token=t"
        z = zipfile.ZipFile(io.BytesIO(c.get(f"{url}&font={font['id']}").content))
        self.assertIn('w:cs="Saral"', z.read("word/document.xml").decode())
        self.assertIn("word/fonts/font1.odttf", z.namelist())
        self.assertEqual(c.get(f"{url}&font=000000000000").status_code, 404)
        c.close()


if __name__ == "__main__":
    unittest.main()

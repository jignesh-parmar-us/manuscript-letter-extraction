"""C15: the akshara language model, correcting a line, word lists and the model in conversion."""
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import appbook                                                      # noqa: E402
from fastapi.testclient import TestClient                           # noqa: E402
from letter_extractor.app.api import create_app                    # noqa: E402
from letter_extractor.app.db import LetterGroup, Page, Sample       # noqa: E402
from letter_extractor.app.dictionary import (book_language, book_model, delete_word_list, import_word_list,   # noqa: E402
                                             to_devanagari_lines, use_word_list, word_lists)
from letter_extractor.app.library import LibraryError              # noqa: E402
from letter_extractor.app.texts import convert_page, page_text     # noqa: E402
from letter_extractor.ocr.language import LanguageModel, candidates, correct_line, tokens   # noqa: E402
from sqlalchemy import select                                       # noqa: E402

TEXT = ["स्वामिनारायण भगवान", "स्वामिनारायण", "नारायण", "भगवान नारायण"] * 5


class ModelTests(unittest.TestCase):
    def test_tokens_are_aksharas_without_spaces(self):
        self.assertEqual(tokens("स्वामि ना"), ["स्वा", "मि", "ना"])

    def test_probabilities_add_up_and_known_text_is_likelier(self):
        lm = LanguageModel().add_all(TEXT)
        seen = list(lm.c1) + ["क"]
        self.assertAlmostEqual(sum(lm.prob("ना", "रा", a) for a in seen), 1.0, delta=0.05)
        self.assertGreater(lm.logprob(tokens("नारायण"))[0], lm.logprob(tokens("नारायव"))[0])

    def test_an_uncertain_letter_is_corrected_and_a_sure_one_never(self):
        lm = LanguageModel().add_all(TEXT)
        line = [[("ना", 1.0)], [("रा", 1.0)], [("य", 1.0)], [("व", 0.55), ("ण", 0.45)]]
        pick, changes = correct_line(lm, line, min_gain=1.0)
        self.assertEqual(pick, [0, 0, 0, 1])
        self.assertEqual((changes[0].old, changes[0].new), ("व", "ण"))
        sure = [[("ना", 1.0)], [("रा", 1.0)], [("य", 1.0)], [("व", 1.0)]]              # one candidate: kept
        self.assertEqual(correct_line(lm, sure)[1], [])
        self.assertEqual(correct_line(lm, line, min_gain=1000)[1], [])                 # not worth enough

    def test_candidates(self):
        self.assertEqual(candidates("क", False, ("ख", 99), [("ख", 0.9)], [], 0.6), [("क", 1.0)])
        got = candidates("क", True, ("ख", 90), [("क", 0.6), ("फ", 0.3)], [("ख", 0.2), ("ग", 0.9)], 0.6)
        self.assertEqual(got[0][0], "क")
        self.assertEqual({c for c, _ in got}, {"क", "ख", "फ"})                         # ग is too far
        self.assertAlmostEqual(sum(w for _, w in got), 1.0, places=3)


class WordListTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.lib, self.book, _ = appbook.fresh_copy()

    def tearDown(self):
        appbook.cleanup(self.tmp, self.lib)

    def test_gujarati_and_devanagari_become_devanagari_lines(self):
        self.assertEqual(to_devanagari_lines("સ્વામિનારાયણ ભગવાન\n\nनारायण, (1) abc भगवान"),
                         ["स्वामिनारायण भगवान", "नारायण", "१", "भगवान"])            # digits are text (verse numbers)

    def test_import_use_and_delete(self):
        f = Path(self.tmp) / "words.txt"
        f.write_text("સ્વામિનારાયણ\nनारायण\n", encoding="utf-8")
        before = len(book_model(self.lib, self.book))
        w = import_word_list(self.lib, str(f), "Words", [self.book])
        self.assertEqual((w["lines"], w["books"]), (2, [self.book]))
        self.assertTrue((self.lib.root / "dictionaries" / w["file"]).is_file())
        self.assertEqual(len(book_model(self.lib, self.book)), before + w["aksharas"])  # rebuilt with it
        self.assertEqual(book_language(self.lib, self.book)["lists"][0]["name"], "Words")
        use_word_list(self.lib, w["id"], self.book, False)
        self.assertEqual(len(book_model(self.lib, self.book)), before)
        delete_word_list(self.lib, w["id"])
        self.assertEqual(word_lists(self.lib), [])
        with self.assertRaises(LibraryError):
            import_word_list(self.lib, str(Path(self.tmp) / "missing.txt"))
        (Path(self.tmp) / "latin.txt").write_text("only latin\n", encoding="utf-8")
        with self.assertRaises(LibraryError):
            import_word_list(self.lib, str(Path(self.tmp) / "latin.txt"))

    def test_the_model_learns_the_books_labels(self):
        with self.lib.session() as s:
            page = s.scalar(select(Page.id).where(Page.book_id == self.book).order_by(Page.id))
            g = s.scalars(select(LetterGroup).join(Sample, Sample.group_id == LetterGroup.id)
                          .where(Sample.page_id == page)).first()
            g.label_dev, g.status = "क", "labelled"
        got = book_language(self.lib, self.book)
        self.assertGreater(got["labels"]["aksharas"], 0)
        self.assertTrue(got["enabled"])

    def test_conversion_uses_the_model_and_marks_what_it_changed(self):
        self.lib.set_book_writing(self.book, "printed")
        with self.lib.session() as s:
            page = s.scalar(select(Page.id).where(Page.book_id == self.book).order_by(Page.id))
            ids = list(s.scalars(select(Sample.id).where(Sample.page_id == page, Sample.deleted.is_(False))
                                 .order_by(Sample.line_number, Sample.x)))
            for g in s.scalars(select(LetterGroup).where(LetterGroup.book_id == self.book)):
                g.label_dev, g.status = "क", "labelled"                         # every group says क
        lm = LanguageModel().add_all(["क" * 30])                               # and the text is all क
        readings = {i: ("क", 97.0) for i in ids}
        readings[ids[3]] = ("ख", 92.0)                                           # Tesseract: ख, sure enough to win
        with mock.patch("letter_extractor.app.texts._read_lines", return_value=readings):
            got = convert_page(self.lib, page, reader=lambda rgb: None, lm=lm)
        self.assertIn("language", got["readers"])
        letters = {x["sample_id"]: x for line in page_text(self.lib, page)["lines"] for x in line}
        x = letters[ids[3]]
        self.assertEqual((x["lm_from"], x["text_dev"], x["uncertain"]), ("ख", "क", True))
        self.assertTrue(x["source"].endswith("+language"))

    def test_api(self):
        f = Path(self.tmp) / "words.txt"
        f.write_text("नारायण\n", encoding="utf-8")
        c = TestClient(create_app(self.lib, "t"))
        h = {"X-Token": "t"}
        w = c.post("/api/wordlists", json={"path": str(f), "name": "N", "book_id": self.book}, headers=h).json()
        self.assertEqual(w["books"], [self.book])
        self.assertEqual(c.get(f"/api/books/{self.book}/language", headers=h).json()["lists"][0]["id"], w["id"])
        self.assertEqual(c.patch(f"/api/wordlists/{w['id']}", json={"book_id": self.book, "use": False},
                                 headers=h).json()["books"], [])
        self.assertEqual(c.delete(f"/api/wordlists/{w['id']}", headers=h).status_code, 204)
        self.assertEqual(c.post("/api/wordlists", json={"path": "/nope.txt"}, headers=h).status_code, 400)
        c.close()


if __name__ == "__main__":
    unittest.main()

"""C17: proofreading a Read Book page: corrections are labels, split letters, proofread lines, the measurement."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import appbook                                                      # noqa: E402
from fastapi.testclient import TestClient                           # noqa: E402
from letter_extractor.app import actions                            # noqa: E402
from letter_extractor.app.api import create_app                    # noqa: E402
from letter_extractor.app.db import Page, Sample                    # noqa: E402
from letter_extractor.app.library import LibraryError              # noqa: E402
from letter_extractor.app.samples import split_sample               # noqa: E402
from letter_extractor.app.texts import convert_page, page_text, proofread_stats, set_proofread   # noqa: E402
from sqlalchemy import select                                       # noqa: E402


class ProofreadTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.lib, self.book, _ = appbook.fresh_copy()
        self.lib.set_book_writing(self.book, "printed")
        with self.lib.session() as s:
            self.page = s.scalar(select(Page.id).where(Page.book_id == self.book).order_by(Page.id))
        self.lib.set_page_part(self.page, "read", force=True)                       # a Read Book page, never grouped
        with self.lib.session() as s:
            self.all = list(s.scalars(select(Sample.id).where(Sample.page_id == self.page, Sample.deleted.is_(False))))
        self.convert({i: ("क", 97.0) for i in self.all})

    def tearDown(self):
        appbook.cleanup(self.tmp, self.lib)

    def convert(self, readings):
        with mock.patch("letter_extractor.app.texts._read_lines", return_value=readings):
            convert_page(self.lib, self.page, reader=lambda rgb: None)

    def letters(self):
        return {x["sample_id"]: x for line in page_text(self.lib, self.page)["lines"] for x in line}

    def first_line(self):
        return [x["sample_id"] for x in page_text(self.lib, self.page)["lines"][0]]

    def test_a_correction_labels_the_letter_and_undo_takes_it_back(self):
        sid = self.all[0]
        actions.label_samples(self.lib, self.book, [sid], "ख")
        x = self.letters()[sid]
        self.assertEqual((x["text_dev"], x["source"], x["uncertain"], x["read_dev"]), ("ख", "label", False, "क"))
        self.assertEqual(x["t_text_dev"], "ख")                                   # "Tesseract only" shows it too
        self.assertEqual(page_text(self.lib, self.page)["corrected"], 1)
        with self.lib.session() as s:                                            # in a group: Review and the reader see it
            self.assertIsNotNone(s.get(Sample, sid).group_id)
        self.convert({i: ("ग", 97.0) for i in self.all})                         # converting again keeps it
        self.assertEqual(self.letters()[sid]["text_dev"], "ख")
        actions.undo(self.lib, self.book)
        self.assertEqual(self.letters()[sid]["text_dev"], "ग")

    def test_a_split_letter_gives_way_to_its_pieces(self):
        with self.lib.session() as s:
            wide = max((s.get(Sample, i) for i in self.all), key=lambda m: m.w)
            sid, cut = wide.id, wide.x + wide.w // 2
        try:
            r = split_sample(self.lib, self.book, sid, cut)
        except LibraryError:
            self.skipTest("no ink on one side of the widest letter")
        got = self.letters()
        self.assertNotIn(sid, got)
        pieces = [x["id"] for x in r["samples"]]
        self.assertTrue(all(got[p]["text_dev"] == "" and got[p]["uncertain"] for p in pieces))   # to be typed
        actions.label_samples(self.lib, self.book, pieces, "ख")
        self.assertTrue(all(self.letters()[p]["text_dev"] == "ख" for p in pieces))

    def test_proofread_lines_are_kept_and_measured(self):
        line = self.first_line()
        actions.label_samples(self.lib, self.book, [line[0]], "ख")
        got = set_proofread(self.lib, self.page, 0)
        self.assertEqual(got["line_states"][0], "proofread")
        self.assertEqual(got["proofread"], 1)
        stats = proofread_stats(self.lib, self.book)
        self.assertEqual(stats["lines"], 1)
        self.assertAlmostEqual(stats["cer"], 1 / stats["chars"], places=3)                # one letter of the line was wrong
        # converting again keeps the proofread line's letters, not the new reading
        self.convert({i: ("ग", 97.0) for i in self.all})
        lines = page_text(self.lib, self.page)["lines"]
        self.assertTrue(all(x["text_dev"] != "ग" for x in lines[0]))
        if len(lines) > 1 and lines[1]:
            self.assertEqual(lines[1][0]["text_dev"], "ग")
        # a change after proofreading shows
        actions.label_samples(self.lib, self.book, [line[1]], "घ")
        self.assertEqual(page_text(self.lib, self.page)["line_states"][0], "changed")
        self.assertEqual(set_proofread(self.lib, self.page, 0, False)["line_states"][0], "")

    def test_a_line_with_unread_letters_cannot_be_proofread(self):
        self.convert({})                                                         # nothing read: the letters are "?"
        if all(x["text_dev"] for x in page_text(self.lib, self.page)["lines"][0]):
            self.skipTest("the groups read every letter")
        with self.assertRaises(LibraryError):
            set_proofread(self.lib, self.page, 0)

    def test_moving_the_page_to_training_keeps_the_corrections(self):
        sid = self.all[0]
        actions.label_samples(self.lib, self.book, [sid], "ख")
        self.lib.set_page_part(self.page, "training")
        with self.lib.session() as s:
            smp = s.get(Sample, sid)
            self.assertIsNotNone(smp.group_id)
            self.assertEqual(smp.part, "training")

    def test_api(self):
        c = TestClient(create_app(self.lib, "t"))
        h = {"X-Token": "t"}
        got = c.post(f"/api/pages/{self.page}/proofread", json={"line": 0}, headers=h).json()
        self.assertEqual(got["line_states"][0], "proofread")
        self.assertTrue(got["lines"][0][0]["image"].startswith(f"/files/books/{self.book}/"))
        self.assertEqual(c.get(f"/api/books/{self.book}/proofread-stats", headers=h).json()["cer"], 0)
        listed = c.get(f"/api/books/{self.book}/texts", headers=h).json()
        self.assertEqual([t["proofread"] for t in listed], [1])
        self.assertEqual(c.post(f"/api/pages/{self.page}/proofread", json={"line": 999}, headers=h).status_code, 400)
        c.close()


if __name__ == "__main__":
    unittest.main()

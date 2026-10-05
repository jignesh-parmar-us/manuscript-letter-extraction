"""C12b: fixing cuts with Tesseract's readings (split samples that hold several letters, join pieces)."""
import json
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import appbook                                                                   # noqa: E402
from letter_extractor.app import actions, samples as manual                     # noqa: E402
from letter_extractor.app.db import LetterGroup, Line, OcrReading, OcrRun, Sample, now   # noqa: E402
from letter_extractor.app.library import LibraryError                           # noqa: E402
from letter_extractor.app.recut import best_cut, fix_cuts                        # noqa: E402
from sqlalchemy import func, select                                             # noqa: E402

BORDER = 10        # read_line adds this border; hOCR boxes are in the bordered image


def hocr(chars):
    """hOCR of one word: chars = [(text, x0, x1)] in line-image pixels."""
    spans = "".join(f"<span class='ocrx_cinfo' title='x_bboxes {x0 + BORDER} {BORDER} {x1 + BORDER} {BORDER + 40}; "
                    f"x_conf 95'>{t}</span>" for t, x0, x1 in chars)
    return (f"<html><body><div class='ocr_page'><span class='ocr_line'><span class='ocrx_word' "
            f"title='bbox 0 0 10 10; x_wconf 95'>{spans}</span></span></div></body></html>")


class RecutTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp, self.lib, self.book, _ = appbook.fresh_copy()
        self.lib.set_book_writing(self.book, "printed")
        self.cfg = self.lib.book_config(self.lib.get_book(self.book))
        with self.lib.session() as s:
            run = OcrRun(book_id=self.book, engine="tesseract", finished_at=now())
            s.add(run)
            s.flush()
            self.run_id = run.id

    def tearDown(self):
        appbook.cleanup(self.tmp, self.lib)

    def letter_of(self, smp):
        return "कखगघचछजझटठडढतथदधनप"[(smp.group_id or 0) % 18]

    def write_readings(self, read_as):
        """One hOCR file per line: `read_as(line, samples)` gives [(text, page x0, page x1)]."""
        ocr = self.lib.book_dir(self.lib.get_book(self.book)) / "ocr"
        ocr.mkdir(exist_ok=True)
        with self.lib.session() as s:
            for line in s.scalars(select(Line)):
                smps = s.scalars(select(Sample).where(Sample.line_id == line.id, Sample.deleted.is_(False))
                                 .order_by(Sample.x)).all()
                dx = max(0, line.x - self.cfg.line_margin_px)
                chars = [(t, x0 - dx, x1 - dx) for t, x0, x1 in read_as(line, smps)]
                (ocr / (Path(line.image).stem + ".hocr")).write_text(hocr(chars), encoding="utf-8")

    def big_neighbours(self):
        """Two neighbouring samples of one line, both in groups with at least 5 samples."""
        with self.lib.session() as s:
            size = dict(s.execute(select(Sample.group_id, func.count(Sample.id)).group_by(Sample.group_id)).all())
            for line in s.scalars(select(Line).order_by(Line.id)):
                smps = s.scalars(select(Sample).where(Sample.line_id == line.id, Sample.deleted.is_(False))
                                 .order_by(Sample.x)).all()
                for a, b in zip(smps, smps[1:]):
                    if a.kind == b.kind == "letter" and size.get(a.group_id, 0) >= 5 and size.get(b.group_id, 0) >= 5:
                        return a.id, b.id, (a.x, a.x + a.w), (b.x, b.x + b.w)
        self.skipTest("no two neighbouring letters in big groups")


class SplitJoinTests(RecutTestCase):
    def test_a_sample_holding_two_letters_is_split_again(self):
        a, b, span_a, span_b = self.big_neighbours()
        joined = manual.join_samples(self.lib, self.book, [a, b])["sample"]["id"]

        def read_as(line, smps):
            out = []
            for x in smps:
                if x.id == joined:
                    out += [("क", *span_a), ("ख", *span_b)]
                else:
                    out.append((self.letter_of(x), x.x, x.x + x.w))
            return out
        self.write_readings(read_as)
        r = fix_cuts(self.lib, self.book)
        self.assertGreaterEqual(r["splits"], 1)
        with self.lib.session() as s:
            self.assertTrue(s.get(Sample, joined).deleted)
            new = s.scalars(select(Sample).where(Sample.source == "ocr-split", Sample.deleted.is_(False))
                            .order_by(Sample.x)).all()
            self.assertEqual(len(new), 2)
            self.assertLess(abs(new[0].x - span_a[0]), 6)
            self.assertLess(abs(new[1].x + new[1].w - span_b[1]), 6)
            reads = {x.id: s.scalar(select(OcrReading.text_dev).where(OcrReading.sample_id == x.id)) for x in new}
            self.assertEqual(sorted(reads.values()), ["क", "ख"])
            self.assertTrue(all(x.group_id is None for x in new))                     # to Unsure

    def test_a_letter_cut_off_a_fragment_is_joined_again(self):
        a, _, span_a, _ = self.big_neighbours()
        for frac in (0.8, 0.75, 0.7, 0.85):
            try:
                pieces = manual.split_sample(self.lib, self.book, a, span_a[0] + int(frac * (span_a[1] - span_a[0])))
                break
            except actions.ActionError:
                continue
        else:
            self.skipTest("the letter cannot be cut near its right edge")
        ids = {p["id"] for p in pieces["samples"]}

        def read_as(line, smps):
            out = [(self.letter_of(x), x.x, x.x + x.w) for x in smps if x.id not in ids]
            if any(x.id in ids for x in smps):
                out.append(("क", *span_a))
            return sorted(out, key=lambda t: t[1])
        self.write_readings(read_as)
        r = fix_cuts(self.lib, self.book)
        self.assertGreaterEqual(r["joins"], 1)
        with self.lib.session() as s:
            self.assertTrue(all(s.get(Sample, i).deleted for i in ids))
            new = s.scalars(select(Sample).where(Sample.source == "ocr-joined", Sample.deleted.is_(False))).all()
            self.assertEqual(len(new), 1)
            self.assertLess(abs(new[0].x - span_a[0]), 6)

    def test_two_letters_are_never_joined(self):
        a, b, span_a, span_b = self.big_neighbours()

        def read_as(line, smps):
            out = [(self.letter_of(x), x.x, x.x + x.w) for x in smps if x.id not in (a, b)]
            if any(x.id == a for x in smps):
                out.append(("क", span_a[0], span_b[1]))                                  # one akshara over both
            return sorted(out, key=lambda t: t[1])
        self.write_readings(read_as)
        r = fix_cuts(self.lib, self.book)
        self.assertEqual(r["joins"], 0)

    def test_one_undo_takes_it_all_back(self):
        a, b, span_a, span_b = self.big_neighbours()
        joined = manual.join_samples(self.lib, self.book, [a, b])["sample"]["id"]
        before = appbook.state(self.lib, self.book)
        self.write_readings(lambda line, smps: [t for x in smps for t in (
            [("क", *span_a), ("ख", *span_b)] if x.id == joined else [(self.letter_of(x), x.x, x.x + x.w)])])
        self.assertGreaterEqual(fix_cuts(self.lib, self.book)["splits"], 1)
        actions.undo(self.lib, self.book)
        samples, groups = appbook.state(self.lib, self.book)
        known = {row[0] for row in before[0]}
        self.assertEqual(([r for r in samples if r[0] in known], groups), before)
        self.assertTrue(all(r[2] for r in samples if r[0] not in known))     # the new samples are deleted again

    def test_locked_groups_are_left_alone(self):
        a, b, span_a, span_b = self.big_neighbours()
        joined = manual.join_samples(self.lib, self.book, [a, b])["sample"]["id"]
        made = actions.new_group(self.lib, self.book, [joined])["group_id"]
        actions.set_status(self.lib, self.book, made, locked=True)
        self.write_readings(lambda line, smps: [t for x in smps for t in (
            [("क", *span_a), ("ख", *span_b)] if x.id == joined else [(self.letter_of(x), x.x, x.x + x.w)])])
        fix_cuts(self.lib, self.book)
        with self.lib.session() as s:
            self.assertFalse(s.get(Sample, joined).deleted)

    def test_nothing_to_fix_changes_nothing(self):
        before = appbook.state(self.lib, self.book)
        self.write_readings(lambda line, smps: [(self.letter_of(x), x.x, x.x + x.w) for x in smps])
        r = fix_cuts(self.lib, self.book)
        self.assertEqual((r["splits"], r["joins"], r["samples_new"]), (0, 0, 0))
        self.assertEqual(appbook.state(self.lib, self.book), before)


class RefusalTests(RecutTestCase):
    def test_handwritten_books_are_refused(self):
        self.lib.set_book_writing(self.book, "handwritten")
        with self.assertRaises(LibraryError):
            fix_cuts(self.lib, self.book)

    def test_a_tesseract_run_is_needed(self):
        with self.lib.session() as s:
            s.query(OcrRun).delete()
        with self.assertRaises(LibraryError):
            fix_cuts(self.lib, self.book)


class BestCutTests(unittest.TestCase):
    def test_cut_goes_to_the_gap_below_the_headline(self):
        m = np.zeros((40, 60), bool)
        m[5:7, :] = True                     # headline over both letters
        m[5:35, 5:25] = True                 # letter 1
        m[5:35, 32:55] = True                # letter 2; the gap is 25..31
        self.assertIn(best_cut(m, 22, 8), range(25, 32))
        self.assertIn(best_cut(m, 34, 8), range(25, 32))

    def test_no_room(self):
        self.assertIsNone(best_cut(np.ones((10, 1), bool), 0, 0))


if __name__ == "__main__":
    unittest.main()

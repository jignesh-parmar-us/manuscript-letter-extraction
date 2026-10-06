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
from letter_extractor.app.recut import best_cut, fix_cuts, left_bar, plan_line   # noqa: E402
from letter_extractor.config import Config                                       # noqa: E402
from letter_extractor.mapping import load_mapping                               # noqa: E402
from letter_extractor.ocr.aksharas import Akshara                               # noqa: E402
from letter_extractor.ocr.tesseract import Char                                 # noqa: E402
from types import SimpleNamespace                                               # noqa: E402
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



def letter(width=40, height=50, stem=True):
    """A letter-like mask: headline, a body, and a stem on the right."""
    m = np.zeros((height, width), bool)
    m[4:7, :] = True
    m[16:30, 4:width - 8] = True                         # a body in the middle rows, not a full-height stroke
    if stem:
        m[4:46, width - 8:width - 3] = True
    return m


def bar(height=50, width=7):
    m = np.zeros((height, width), bool)
    m[4:7, :] = True
    m[4:46, 1:6] = True
    return m


class LeftBarTests(unittest.TestCase):
    def test_bar_then_letter(self):
        m = np.concatenate([bar(), np.zeros((50, 4), bool), letter()], axis=1)
        m[4:7, :] = True                                     # one headline over both
        cut = left_bar(m, 40)
        self.assertIsNotNone(cut)
        self.assertTrue(6 <= cut <= 12, cut)

    def test_a_lone_bar(self):
        self.assertEqual(left_bar(bar(), 40), 7)

    def test_a_letter_does_not_start_with_a_bar(self):
        self.assertIsNone(left_bar(letter(), 40))


class AnyShape:
    def distance(self, mask, spacing):
        return 0.0


class BarMoveTests(unittest.TestCase):
    """अ | ावे: Phase 1 joined the bar of आ to the next letter; Tesseract reads आ, then वे."""

    def plan(self, next_mask, readings):
        cur = SimpleNamespace(id=1, x=100, y=10, w=40, h=50, kind="letter", page_id=1)
        nxt = SimpleNamespace(id=2, x=140, y=10, w=next_mask.shape[1], h=50, kind="letter", page_id=1)
        others = [SimpleNamespace(id=3 + k, x=140 + next_mask.shape[1] + 40 * k, y=10, w=40, h=50, kind="letter",
                                  page_id=1) for k in range(3)]
        smps = [cur, nxt] + others
        masks = {1: letter(), 2: next_mask, **{o.id: letter() for o in others}}
        aks = [Akshara(t, (x0, 0, x1 - x0, 40), 95.0, chars=[Char(t, (x0, 0, x1 - x0, 40), 95.0)])
               for t, x0, x1 in readings(cur, nxt, others)]
        return plan_line(aks, smps, lambda smp: masks[smp.id], 0, Config(), AnyShape(), 70.0, load_mapping())

    def test_the_bar_moves_to_the_letter_before_it(self):
        nm = np.concatenate([bar(), np.zeros((50, 4), bool), letter()], axis=1)
        nm[4:7, :] = True
        changes, _ = self.plan(nm, lambda c, n, o: [("आ", 98, 138), ("वे", 150, 192)] +
                               [("क", x.x, x.x + 40) for x in o])
        self.assertEqual([c.kind for c in changes], ["bar"])
        first, rest = changes[0].pieces
        self.assertEqual((first.text, rest.text), ("आ", "वे"))
        self.assertGreaterEqual(first.box[2], 46)                           # the letter and its bar
        self.assertGreaterEqual(rest.box[0], 146)                           # the next letter without its bar

    def test_a_lone_bar_is_joined(self):
        changes, _ = self.plan(bar(), lambda c, n, o: [("ता", 100, 140)] + [("क", x.x, x.x + 40) for x in o])
        self.assertEqual([c.kind for c in changes], ["bar"])
        self.assertEqual(len(changes[0].pieces), 1)
        self.assertEqual(changes[0].pieces[0].text, "ता")

    def test_no_move_when_the_next_letter_has_an_i_sign(self):
        nm = np.concatenate([bar(), np.zeros((50, 4), bool), letter()], axis=1)
        changes, _ = self.plan(nm, lambda c, n, o: [("ता", 100, 140), ("कि", 140, 192)] +
                               [("क", x.x, x.x + 40) for x in o])
        self.assertEqual(changes, [])

    def test_no_move_when_the_reading_has_no_bar(self):
        nm = np.concatenate([bar(), np.zeros((50, 4), bool), letter()], axis=1)
        changes, _ = self.plan(nm, lambda c, n, o: [("त", 100, 140), ("वे", 150, 192)] +
                               [("क", x.x, x.x + 40) for x in o])
        self.assertEqual(changes, [])


class PlacementTests(RecutTestCase):
    def test_pieces_go_into_the_labelled_group_of_their_reading(self):
        a, b, span_a, span_b = self.big_neighbours()
        with self.lib.session() as s:
            ga, gb = s.get(Sample, a).group_id, s.get(Sample, b).group_id
        actions.set_label(self.lib, self.book, ga, "क")
        actions.set_label(self.lib, self.book, gb, "ख")
        joined = manual.join_samples(self.lib, self.book, [a, b])["sample"]["id"]
        self.write_readings(lambda line, smps: [t for x in smps for t in (
            [("क", *span_a), ("ख", *span_b)] if x.id == joined else [(self.letter_of(x), x.x, x.x + x.w)])])
        r = fix_cuts(self.lib, self.book)
        self.assertGreaterEqual(r["placed"], 2)
        with self.lib.session() as s:
            new = s.scalars(select(Sample).where(Sample.source == "ocr-split", Sample.deleted.is_(False))
                            .order_by(Sample.x)).all()
            self.assertEqual([x.group_id for x in new], [ga, gb])


if __name__ == "__main__":
    unittest.main()

"""aa bars cut onto the next letter (bars.py, app/barfix.py), on drawn letters and the synthetic book."""
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import appbook                                                      # noqa: E402
from fastapi.testclient import TestClient                           # noqa: E402
from letter_extractor.app.api import create_app                    # noqa: E402
from letter_extractor.app.barfix import fix_bars                    # noqa: E402
from letter_extractor.app.library import LibraryError              # noqa: E402
from letter_extractor.bars import ends_with_bar, lone_bar, move_bars, plan_pair, split_bar, stray_bar   # noqa: E402
from letter_extractor.config import Config                          # noqa: E402
from letter_extractor.letters import Letter                         # noqa: E402

W = 40          # the letter width of the drawings
H = 60


def body(m, x0, x1):
    """A letter body under the headline: a loop joined to a stem on its right."""
    m[22:26, x0:x1] = True
    m[14:50, x0:x0 + 4] = True
    m[14:58, x1 - 5:x1] = True
    return m


def headline(m, x0, x1):
    m[10:14, x0:x1] = True
    return m


def e_sign(m):
    """The e sign of the letter after the bar (रे): high at its left end, over the bar, coming down to
    the headline at its right."""
    img = m.astype(np.uint8)
    cv2.line(img, (4, 2), (30, 8), 1, 3)
    return img.astype(bool)


def bar_then_letter(hook=False, dot=False, joined=False):
    """ार: a bar (columns 2-6), a gap, a letter; optionally the i hook (रवि), an anusvara over the bar,
    or the bar joined to the letter below the headline (a letter of its own, no gap)."""
    m = headline(np.zeros((H, 46), bool), 0, 46)
    m[10:58, 2:7] = True
    body(m, 11, 44)
    if hook:                       # starts over the bar and arches over the letter, not touching it
        m[2:8, 4:36] = True
        m[0:3, 10:30] = True
    if dot:                        # a narrow mark over the bar
        m[2:7, 3:7] = True
    if joined:
        m[30:34, 6:12] = True
    return m


class RuleTests(unittest.TestCase):
    cfg = Config()

    def test_a_bar_at_the_start_is_found(self):
        gap = stray_bar(bar_then_letter(), W, self.cfg)
        self.assertIsNotNone(gap)
        self.assertTrue(7 <= gap <= 11)

    def test_the_i_sign_stays(self):
        self.assertIsNone(stray_bar(bar_then_letter(hook=True), W, self.cfg))       # रवि is never cut

    def test_under_an_e_sign_only_with_tesseracts_reading(self):
        m = e_sign(bar_then_letter())
        self.assertIsNone(stray_bar(m, W, self.cfg))                                # shape alone: left alone
        self.assertIsNotNone(stray_bar(m, W, self.cfg, "रे"))                        # read with an e sign: moves
        self.assertIsNone(stray_bar(m, W, self.cfg, "रि"))                           # read with an i sign: stays
        hook = bar_then_letter(hook=True)
        self.assertIsNone(stray_bar(hook, W, self.cfg, "रे"))                        # an i hook's shape: stays anyway
        bar, rest = split_bar(m, stray_bar(m, W, self.cfg, "रे"), W)
        self.assertFalse(bar[:9, 12:].any())                                         # the e sign stays with its letter
        self.assertTrue(rest[:9].any())

    def test_a_stem_with_a_foot_curling_left(self):
        m = bar_then_letter()
        m[52:58, 0:3] = True                                                         # the foot of ण's stem
        self.assertIsNotNone(stray_bar(m, W, self.cfg))

    def test_a_soft_bar_edge(self):
        m = bar_then_letter()
        m[18:58, 1] = np.arange(40) % 3 == 0                                         # a faint column before the bar
        self.assertIsNotNone(stray_bar(m, W, self.cfg))                              # (માટે cut as મ + ાટે)
        ma = headline(np.zeros((H, 40), bool), 0, 40)                                # म: a loop, then its stem
        ma[16:20, 0:10] = ma[30:34, 0:10] = True
        ma[16:34, 0:3] = True
        ma[10:58, 9:13] = True
        ma[14:50, 30:34] = True
        self.assertIsNone(stray_bar(ma, W, self.cfg))                                # a loop is not a soft edge

    def test_a_lone_bar_before_a_letter_with_the_i_hook_is_that_i(self):
        body = headline(np.zeros((H, 34), bool), 0, 34)
        body[14:50, 2:6] = body[14:50, 20:24] = body[46:50, 2:24] = True
        bar = headline(np.zeros((H, 14), bool), 0, 14)
        bar[10:58, 4:9] = True
        hooked = headline(np.zeros((H, 34), bool), 0, 34)                            # नि without its bar
        hooked[14:58, 26:31] = True
        hooked[2:8, 0:30] = True
        plain = headline(np.zeros((H, 34), bool), 0, 34)
        plain[14:58, 26:31] = True
        args = ((100, 50, 34, H), body, (136, 50, 14, H), bar, W, self.cfg, "")
        self.assertIsNone(plan_pair(*args, nxt=(hooked, "")))                        # the bar is the ि of the next
        self.assertIsNone(plan_pair(*args, nxt=(plain, "नि")))                       # Tesseract read ि there
        self.assertIsNotNone(plan_pair(*args, nxt=(plain, "न")))
        own = hooked.copy()
        own[10:58, 0:5] = True                                                       # the next letter has its own bar
        self.assertIsNotNone(plan_pair(*args, nxt=(own, "नि")))

    def test_a_whole_na_read_with_aa_gets_its_bar(self):
        na = headline(np.zeros((H, 40), bool), 0, 40)                                # ण with its stem apart
        na[14:50, 2:6] = na[14:50, 20:24] = na[46:50, 2:24] = True
        na[10:58, 32:37] = True
        self.assertTrue(ends_with_bar(na, W, self.cfg))                              # the stem looks like a bar
        args = ((100, 50, 40, H), na, (141, 50, 46, H), bar_then_letter(), W, self.cfg)
        self.assertIsNone(plan_pair(*args))                                          # no reading: left alone
        self.assertIsNone(plan_pair(*args, prev_reading="ण"))                        # read without aa: left alone
        self.assertIsNotNone(plan_pair(*args, prev_reading="णा"))                    # read णा: the bar is its aa
        self.assertIsNone(plan_pair(*args, prev_reading="ना"))                       # न has no stem apart

    def test_a_bar_on_its_own(self):
        stem = headline(np.zeros((H, 14), bool), 0, 14)                              # ण's stem with its headline
        stem[10:58, 4:9] = True
        self.assertTrue(lone_bar(stem, W, self.cfg))
        danda = np.zeros((H, 9), bool)                                               # no headline: a danda
        danda[10:58, 2:7] = True
        self.assertFalse(lone_bar(danda, W, self.cfg))
        i_sign = headline(np.zeros((H, 24), bool), 0, 24)
        i_sign[10:58, 4:9] = True
        i_sign[2:8, 6:24] = True                                                     # a hook leaning right: ि
        self.assertFalse(lone_bar(i_sign, W, self.cfg))
        o_sign = stem.copy()
        o_sign[2:8, 0:7] = True                                                      # a mark leaning left: ो
        self.assertTrue(lone_bar(o_sign, W, self.cfg))
        self.assertFalse(lone_bar(bar_then_letter(), W, self.cfg))                   # a letter follows the bar
        body = headline(body_only := np.zeros((H, 34), bool), 0, 34)                 # ण without its stem
        body[14:50, 2:6] = body[14:50, 20:24] = body[46:50, 2:24] = True
        (whole, none) = plan_pair((100, 50, 34, H), body, (136, 50, 14, H), stem, W, self.cfg)
        self.assertIsNone(none)
        self.assertEqual((whole[0][0], whole[0][0] + whole[0][2]), (100, 150))       # one letter again

    def test_capture_joins_a_lone_bar_and_numbers_the_line_again(self):
        body = headline(np.zeros((H, 34), bool), 0, 34)
        body[14:50, 2:6] = body[14:50, 20:24] = body[46:50, 2:24] = True
        stem = headline(np.zeros((H, 14), bool), 0, 14)
        stem[10:58, 4:9] = True
        nxt = headline(body_only := np.zeros((H, 34), bool), 0, 34)
        nxt[14:58, 26:31] = True
        letters = [Letter(1, 1, (100, 50, 34, H), body, "black", "letter", 1, text="ण"),
                   Letter(1, 2, (136, 50, 14, H), stem, "black", "letter", 1, text=""),
                   Letter(1, 3, (200, 50, 34, H), nxt, "black", "letter", 1, text="त")]
        out = move_bars(letters, Config())
        self.assertEqual([(x.pos, x.text) for x in out], [(1, "ण"), (2, "त")])
        self.assertIn("lone-bar-back", out[0].rules)

    def test_a_dot_over_the_bar_does_not_stop_it(self):
        self.assertIsNotNone(stray_bar(bar_then_letter(dot=True), W, self.cfg))

    def test_a_stem_joined_to_its_letter_is_not_a_bar(self):
        self.assertIsNone(stray_bar(bar_then_letter(joined=True), W, self.cfg))
        self.assertIsNone(stray_bar(headline(body(np.zeros((H, 40), bool), 2, 38), 0, 40), W, self.cfg))

    def test_a_letter_ending_with_its_own_bar(self):
        na = headline(body(np.zeros((H, 46), bool), 0, 33), 0, 46)
        self.assertFalse(ends_with_bar(na, W, self.cfg))                            # न: its stem is its own
        na[10:58, 38:43] = True                                                     # ना: a bar apart from it
        self.assertTrue(ends_with_bar(na, W, self.cfg))

    def test_marks_are_not_cut(self):
        m = bar_then_letter(dot=True)
        m[2:7, 20:26] = True                                                        # a mark over the letter
        bar, rest = split_bar(m, stray_bar(m, W, self.cfg), W)
        self.assertTrue(bar[2:7, 3:7].all() and not rest[2:7, 3:7].any())           # the bar's mark goes with it
        self.assertTrue(rest[2:7, 20:26].all() and not bar[2:7, 20:26].any())
        self.assertEqual(int(bar.sum() + rest.sum()), int(m.sum()))                  # nothing lost

    def test_the_bar_goes_to_the_letter_before(self):
        prev = headline(body(np.zeros((H, 34), bool), 0, 33), 0, 34)                # न at x 100
        cur = bar_then_letter()                                                     # ार right after it
        (lbox, lmask), (rbox, rmask) = plan_pair((100, 50, 34, H), prev, (135, 50, 46, H), cur, W, self.cfg)
        self.assertEqual(lbox[0], 100)
        self.assertGreaterEqual(lbox[0] + lbox[2], 135 + 7)                         # now ends after the bar
        self.assertGreaterEqual(rbox[0], 135 + 7)                                   # the rest starts after it
        self.assertEqual(int(lmask.sum() + rmask.sum()), int(prev.sum() + cur.sum()))
        far = plan_pair((100, 50, 34, H), prev, (135 + W, 50, 46, H), cur, W, self.cfg)
        self.assertIsNone(far)                                                      # another word: a bar never starts one
        ending = headline(body(np.zeros((H, 34), bool), 0, 24), 0, 34)
        ending[10:58, 29:33] = True                                                 # the letter before has its own bar
        self.assertIsNone(plan_pair((100, 50, 34, H), ending, (135, 50, 46, H), cur, W, self.cfg))

    def test_capture_moves_the_bar_and_tesseracts_aa(self):
        prev = headline(body(np.zeros((H, 34), bool), 0, 33), 0, 34)
        cur = bar_then_letter()
        hook = bar_then_letter(hook=True)
        letters = [Letter(1, 1, (100, 50, 34, H), prev, "black", "letter", 1, text="न"),
                   Letter(1, 2, (135, 50, 46, H), cur, "black", "letter", 1, text="ार"),
                   Letter(1, 3, (182, 50, 46, H), hook, "black", "letter", 1, text="वि")]
        out = move_bars(letters, Config())
        self.assertEqual([x.text for x in out], ["ना", "र", "वि"])
        self.assertIn("aa-bar-back", out[0].rules)
        self.assertIs(out[2], letters[2])                                           # the i sign: untouched


class BookTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.lib, self.book, _ = appbook.fresh_copy()

    def tearDown(self):
        appbook.cleanup(self.tmp, self.lib)

    def test_the_new_letters_keep_tesseracts_readings(self):
        from unittest import mock
        from sqlalchemy import select
        from letter_extractor.app import actions as A
        from letter_extractor.app.barfix import carry_readings
        from letter_extractor.app.db import OcrReading, OcrRun, Page, Sample
        from letter_extractor.app.samples import _sample_mask
        self.lib.set_book_writing(self.book, "printed")
        with self.lib.session() as s:
            page = s.scalar(select(Page.id).where(Page.book_id == self.book))
            a, b = s.scalars(select(Sample).where(Sample.page_id == page, Sample.line_number == 1)
                             .order_by(Sample.x)).all()[:2]
            book = self.lib.get_book(self.book)
            ma, mb = _sample_mask(self.lib, book, a), _sample_mask(self.lib, book, b)
            plan = (a.id, b.id, ((a.x, a.y, a.w, a.h), ma), ((b.x, b.y, b.w, b.h), mb))
            run = OcrRun(book_id=self.book, engine="tesseract", finished_at=a.created_at)
            s.add(run)
            s.flush()
            s.add(OcrReading(run_id=run.id, sample_id=a.id, text_dev="न", confidence=90, overlap=1))
            s.add(OcrReading(run_id=run.id, sample_id=b.id, text_dev="ार", confidence=80, overlap=1))
            run_id = run.id
        with mock.patch("letter_extractor.app.barfix.plan_book", return_value=[plan]):
            r = fix_bars(self.lib, self.book)
        self.assertEqual(r["readings"], 2)

        def readings():
            with self.lib.session() as s:
                return dict(s.execute(select(Sample.x, OcrReading.text_dev).join(OcrReading, OcrReading.sample_id == Sample.id)
                                      .where(OcrReading.run_id == run_id, Sample.deleted.is_(False),
                                             Sample.source == "bar")).all())
        got = readings()
        self.assertEqual(sorted(got.values()), ["न", "र"])                     # the rest without its aa
        with self.lib.session() as s:
            right = s.scalar(select(Sample.id).where(Sample.source == "bar", Sample.deleted.is_(False),
                                                     Sample.x == max(got)))
        A.remove_readings(self.lib, self.book, [right], "tesseract")
        self.assertEqual(carry_readings(self.lib, self.book), 0)                # a removed reading stays removed
        self.assertEqual(sorted(readings().values()), ["न"])

    def test_handwritten_books_are_refused(self):
        self.lib.set_book_writing(self.book, "handwritten")
        with self.assertRaises(LibraryError):
            fix_bars(self.lib, self.book)
        c = TestClient(create_app(self.lib, "t"))
        self.assertEqual(c.post(f"/api/books/{self.book}/fix-bars", headers={"X-Token": "t"}).status_code, 400)
        c.close()

    def test_a_book_without_stray_bars_is_left_alone(self):
        self.lib.set_book_writing(self.book, "printed")
        r = fix_bars(self.lib, self.book)
        self.assertEqual(r["bars"], 0)
        self.assertEqual(appbook.state(self.lib, self.book), appbook.state(self.lib, self.book))


if __name__ == "__main__":
    unittest.main()

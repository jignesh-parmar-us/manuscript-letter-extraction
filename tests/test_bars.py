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
from letter_extractor.bars import ends_with_bar, move_bars, plan_pair, split_bar, stray_bar   # noqa: E402
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

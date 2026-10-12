"""Letters made from parts of others (compose.py), on drawn masks."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from letter_extractor import compose as C                          # noqa: E402


def letter(w=40, h=50, top=10):
    """A block letter: headline at `top` (5 rows), a stem on the right, a short bowl on the left."""
    m = np.zeros((top + h, w), bool)
    m[top:top + 5, :] = True
    m[top + 5:, w - 8:w - 2] = True
    m[top + 15:top + 30, 2:14] = True
    return m


def with_mark(w=40):
    """The letter with an e stroke above its headline, near the right edge."""
    m = letter(w)
    for k in range(8):
        m[1 + k, w - 14 + k:w - 10 + k] = True
    return m


def with_bar(w=40, gap=6, bar=6):
    """The letter, a gap, and an aa bar joined by the headline."""
    m = letter(w)
    out = np.zeros((m.shape[0], w + gap + bar), bool)
    out[:, :w] = m
    out[10:15, w:] = True
    out[15:, w + gap:w + gap + bar] = True
    return out


class HeadlineTests(unittest.TestCase):
    def test_the_top_long_run_not_a_busier_middle_bar(self):
        m = letter()
        m[30:36, 0:38] = True                         # the middle bar of भ: as long and thicker
        self.assertEqual(C.headline(m), (10, 14))

    def test_two_short_strokes_above_are_not_the_headline(self):
        m = letter()
        m[2:9, 20:26] = m[2:9, 28:34] = True          # the two strokes of ै
        self.assertEqual(C.headline(m)[0], 10)


class ComposeTests(unittest.TestCase):
    def test_a_sign_above_goes_over_the_new_letter_at_the_same_place(self):
        part = C.cut(with_mark(), "े")
        self.assertIsNotNone(part)
        base = letter(w=52)                           # a wider letter
        out = C.compose(base, part)
        ys, xs = np.nonzero(out[:9])                  # the stroke, above the headline
        self.assertTrue(ys.size)
        donor_hy1 = C.headline(with_mark())[1]
        self.assertEqual(int(xs.max()) - C.body_right(base, 14),                # same distance from the right edge
                         int(np.nonzero(with_mark()[:9])[1].max()) - C.body_right(with_mark(), donor_hy1))
        self.assertTrue(out[-50:, :52][base[-50:]].all(), "the base is kept whole")

    def test_a_bar_goes_after_the_new_letter_with_the_same_gap_and_a_headline_over_it(self):
        part = C.cut(with_bar(gap=6), "ा")
        self.assertEqual(part.gap, 9)                 # from the stem's last column (37) to the bar (46)
        out = C.compose(letter(w=30), part)
        self.assertEqual(out.shape[1], 30 + 6 + 6)
        self.assertTrue(out[10:15].all(), "the headline runs on over the gap")

    def test_a_bar_that_does_not_end_with_its_letter_is_refused(self):
        part = C.cut(with_bar(), "ा")
        short = letter(h=90)                          # a far taller base: the bar would end high
        self.assertIsNone(C.compose(short, part))

    def test_a_sign_below_hangs_under_the_foot(self):
        donor = letter()
        donor = np.vstack([donor, np.zeros((12, 40), bool)])
        donor[60:70, 30:40] = True                    # a tail under the stem
        part = C.cut(donor, "ु", letter_height=50)
        out = C.compose(letter(w=46), part)
        self.assertEqual(out.shape[0], 60 + 10)
        self.assertTrue(out[60:].any())

    def test_only_typical_parts_are_kept(self):
        good = [C.cut(with_mark(), "े") for _ in range(4)]
        dotted = with_mark()
        dotted[2:5, 2:5] = True                       # a dot too (ं): two pieces
        big = letter()
        big[0:9, 15:35] = True                        # far too much ink above
        parts = good + [C.cut(dotted, "े"), C.cut(big, "े")]
        self.assertEqual(len(C.typical(parts)), 4)

    def test_odd_bases_are_left_out(self):
        masks = [letter() for _ in range(4)] + [letter(w=12, h=20)]
        self.assertEqual(C.typical_bases(masks), [0, 1, 2, 3])


if __name__ == "__main__":
    unittest.main()

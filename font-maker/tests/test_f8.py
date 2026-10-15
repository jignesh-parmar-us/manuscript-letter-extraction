"""F8: one even headline. Light on purpose: made-up glyph images a few dozen pixels wide.
"""
import unittest

import numpy as np

from font_maker.headline import even, find, font_headline


def glyph(bar_row: int, bar_h: int = 4, w: int = 40, h: int = 60) -> np.ndarray:
    """A made-up akshara: a headline at `bar_row` and a stem hanging from it on the right."""
    a = np.zeros((h, w), bool)
    a[bar_row:bar_row + bar_h, 2:w - 2] = True
    a[bar_row:h, w - 10:w - 6] = True
    return a


class HeadlineTest(unittest.TestCase):
    def test_find_and_the_fonts_median(self):
        self.assertEqual(find(glyph(8)), (8, 12, 2, 38))
        no_bar = np.zeros((60, 40), bool)
        no_bar[10:50, 18:22] = True                      # a stroke, no headline (as ध has only part of one)
        self.assertIsNone(find(no_bar))
        self.assertEqual(font_headline([(-10, 1), (-11, 1.5), (-12, 1)]), {"top": -11, "thickness": 1, "glyphs": 3})

    def test_a_bar_2_px_off_moves_to_the_fonts_line_and_the_stem_stays_joined(self):
        img = glyph(8)                                   # glyph top 0 px against the baseline -> bar at row 8 (x4 = 2 px)
        out, pad = even(img, 0.0, {"top": 4.0, "thickness": 1.0}, 4)    # the font's bar 2 px lower: row 16
        self.assertEqual(pad, 0)
        self.assertEqual(find(out)[:2], (16, 20))
        self.assertTrue(out[16:, 32].all())              # the stem still meets the bar
        self.assertEqual(out[0:8, 0].sum(), 0)
        self.assertTrue(out[16, 0] and out[16, 39])      # drawn to the edges, so neighbours touch
        up, pad = even(img, 0.0, {"top": -1.0, "thickness": 1.0}, 4)    # above the image: rows added on top
        self.assertEqual(pad, 4)
        self.assertEqual(find(up)[:2], (0, 4))
        self.assertTrue(up[4:, 32].all())

    def test_a_gap_in_the_headline_stays(self):
        img = glyph(8)
        img[8:12, 12:20] = False                         # a gap, as in भ थ ध (else they read म प घ)
        out, _ = even(img, 0.0, {"top": 4.0, "thickness": 1.0}, 4)
        self.assertFalse(out[16:20, 12:20].any())
        self.assertTrue(out[16:20, 2:12].all() and out[16:20, 20:38].all())

    def test_a_glyph_without_a_headline_is_left_alone(self):
        no_bar = np.zeros((60, 40), bool)
        no_bar[10:50, 18:22] = True
        out, pad = even(no_bar, 0.0, {"top": 4.0, "thickness": 1.0}, 4)
        self.assertTrue((out == no_bar).all() and pad == 0)


if __name__ == "__main__":
    unittest.main()

"""Reading a line by searching along it (ocr/segment.py): boundaries, the search, not-a-letter windows, spaces."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from letter_extractor.features import hog, hog_batch                     # noqa: E402
from letter_extractor.ocr.features import features, features_batch       # noqa: E402
from letter_extractor.ocr.language import LanguageModel                  # noqa: E402
from letter_extractor.ocr.segment import SearchSettings, candidates, clear_borders, read_line   # noqa: E402

SPACING = 100.0


class WidthReader:
    """A stand-in letter reader: a window about 20 x 24 px is क, about 40 x 30 px is ख, anything else is not a
    letter (the last class). It reads the size from the features' size part (size / line spacing)."""
    classes = ["क", "ख", "<not a letter>"]

    def probabilities(self, X):
        out = []
        for w, h in zip(X[:, -2] * SPACING, X[:, -1] * SPACING):
            if abs(w - 20) <= 3 and abs(h - 24) <= 2:
                out.append([0.9, 0.05, 0.05])
            elif abs(w - 40) <= 3 and abs(h - 30) <= 2:
                out.append([0.05, 0.9, 0.05])
            else:
                out.append([0.0005, 0.0005, 0.999])
        return np.array(out, np.float32)


def line(*blocks):
    """A line mask with solid letters of the given widths, `gap` px apart; a negative width is a wide gap."""
    m = np.zeros((40, 400), bool)
    x = 10
    for w in blocks:
        if w < 0:
            x += -w
            continue
        m[8:32 if w <= 25 else 38, x:x + w] = True             # ख is taller than क
        x += w + 4
    return m


class SegmentTests(unittest.TestCase):
    def test_batched_features_are_the_same(self):
        rng = np.random.default_rng(0)
        masks = [rng.random((60, int(w))) > 0.5 for w in (12, 40, 77)]
        np.testing.assert_allclose(features_batch(masks, SPACING), np.stack([features(m, SPACING) for m in masks]),
                                   atol=1e-5)
        imgs = np.stack([(rng.random((48, 48)) * 255).astype(np.uint8) for _ in range(3)])
        np.testing.assert_allclose(hog_batch(imgs), np.stack([hog(i) for i in imgs]), atol=1e-5)

    def test_candidates_include_the_gaps_and_a_grid(self):
        m = line(20, 40)
        c = candidates(m, 6)
        self.assertIn(10, c)                                   # where the ink starts
        self.assertIn(30, c)                                   # the gap after the first letter
        self.assertTrue(all(b - a >= 2 for a, b in zip(c, c[1:])))

    def test_the_search_reads_letters_and_skips_wrong_windows(self):
        widths = {"क": 20.0, "ख": 40.0}
        text, steps, stats = read_line(line(20, 40, 20), SPACING, WidthReader(), 30.0, widths, None,
                                       SearchSettings(step=2, bonus=2.0))
        self.assertEqual(text, "कखक")
        self.assertEqual([(s.x0, s.x1) for s in steps][0][0], 10)
        self.assertGreater(stats["windows"], 3)

    def test_a_wide_gap_is_a_space_and_the_language_model_breaks_ties(self):
        widths = {"क": 20.0, "ख": 40.0}
        text, _, _ = read_line(line(20, -60, 20), SPACING, WidthReader(), 30.0, widths, None, SearchSettings(step=2))
        self.assertEqual(text, "क क")
        _, steps, _ = read_line(line(20, -60, 20), SPACING, WidthReader(), 30.0, widths, None, SearchSettings(step=2))
        self.assertEqual([s.space for s in steps], [False, True])               # the gap before the second letter
        lm = LanguageModel().add_all(["कख"] * 10)
        self.assertEqual(read_line(line(20, 40), SPACING, WidthReader(), 30.0, widths, lm, SearchSettings(step=2))[0], "कख")

    def test_a_page_border_at_the_edge_is_cleared_but_a_danda_is_kept(self):
        m = np.zeros((120, 400), bool)
        m[40:100, 60:110] = True                                # letters in the band 40-100
        m[40:100, 130:180] = True
        m[5:30, 20:24] = m[45:70, 20:24] = m[85:115, 20:24] = True   # a broken border, taller than the letters
        m[40:100, 200:212] = True                               # a danda: solid, within the band
        out, n = clear_borders(m, 50.0, 60.0, (40.0, 100.0))
        self.assertEqual(n, 1)
        self.assertFalse(out[:, 20:24].any())
        self.assertTrue(out[40:100, 200:212].all())            # the danda stays
        self.assertTrue(m[:, 20:24].any())                     # the mask given is not changed
        m[50:53, 380:383] = True                                # a speck after the danda
        out, n = clear_borders(m, 50.0, 60.0, (40.0, 100.0))
        self.assertEqual(n, 2)
        self.assertTrue(out[:, 200:212].any())

    def test_pruning_drops_unlikely_windows(self):
        widths = {"क": 20.0, "ख": 40.0}
        _, _, all_ = read_line(line(20, 40), SPACING, WidthReader(), 30.0, widths, None, SearchSettings(step=2, min_prob=0.0))
        _, _, pruned = read_line(line(20, 40), SPACING, WidthReader(), 30.0, widths, None,
                                 SearchSettings(step=2, min_prob=0.5))
        self.assertLess(pruned["kept"], all_["kept"])


if __name__ == "__main__":
    unittest.main()

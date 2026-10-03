"""C3a: stroke pieces from headline breaks."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import synthetic                                                    # noqa: E402
from letter_extractor import io_utils                               # noqa: E402
from letter_extractor.config import Config                          # noqa: E402
from letter_extractor.pipeline import process_page                  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


class KnownJoinsTests(unittest.TestCase):
    def _check(self, colour):
        rgb, expected = synthetic.make_break_page(colour=colour)
        _, layout, pieces, _ = process_page(rgb, Config())
        self.assertEqual(len(layout.lines), len(expected))
        for line, (breaks, joined) in zip(layout.lines, expected):
            mine = [p for p in pieces if p.line == line.index]
            cuts = [p.x0 for p in mine[1:]]
            for a, b in breaks:
                self.assertTrue(any(a <= c <= b for c in cuts), f"line {line.index}: no cut in {a}-{b}: {cuts}")
            for j in joined:
                self.assertFalse(any(abs(c - j) <= 6 for c in cuts), f"line {line.index}: cut near {j}: {cuts}")
            self.assertEqual(len(mine), len(breaks) + 1, cuts)
            danda = mine[-1]                                  # its own piece, no wider than its stroke
            self.assertLessEqual(danda.box[2], 12)
            self.assertLessEqual(danda.head_width, danda.stem_width + 2)
            self.assertGreater(mine[0].head_width, 2 * mine[0].stem_width)
            kind = "red" if colour == synthetic.RED_INK else "black"
            self.assertEqual({p.ink for p in mine}, {kind})

    def test_black_ink(self):
        self._check(synthetic.BLACK_INK)

    def test_red_ink(self):
        self._check(synthetic.RED_INK)

    def test_pieces_cover_the_main_zone_ink_once(self):
        rgb, _ = synthetic.make_break_page()
        page, layout, pieces, _ = process_page(rgb, Config())
        seen = np.zeros(page.ink.shape, np.int32)
        for p in pieces:
            x, y, w, h = p.box
            self.assertTrue(p.x0 <= x and x + w <= p.x1, "piece ink outside its columns")
            seen[y:y + h, x:x + w] += p.mask
        self.assertEqual(seen.max(), 1)
        self.assertTrue((seen.astype(bool) <= page.ink).all())


@unittest.skipUnless((SAMPLES / "page1.jpg").is_file(), "sample pages not present")
class SamplePagePiecesTests(unittest.TestCase):
    """Baseline on the real pages, measured when C3a was tuned: about 36-46 pieces per line
    (a line holds roughly 40-50 letters; vowel bars give extra pieces, touching headlines fewer)."""

    def test_pieces_per_line(self):
        cfg = Config()
        for name in ("page1.jpg", "page2.jpg"):
            rgb, _ = io_utils.load_image(SAMPLES / name)
            _, layout, pieces, _ = process_page(rgb, cfg)
            per_line = len(pieces) / len(layout.lines)
            self.assertTrue(33 <= per_line <= 48, (name, per_line))


if __name__ == "__main__":
    unittest.main()

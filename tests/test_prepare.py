"""C1: page preparation on a synthetic page and on the two sample pages."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import synthetic                                                    # noqa: E402
from letter_extractor import io_utils                               # noqa: E402
from letter_extractor.config import Config                          # noqa: E402
from letter_extractor.prepare import prepare_page                   # noqa: E402

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


class SyntheticPrepareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rgb, cls.truth = synthetic.make_page()
        cls.page = prepare_page(cls.rgb, Config())

    def test_scanner_background_is_not_paper(self):
        self.assertFalse(self.page.paper[5, 5])
        self.assertFalse(self.page.paper[-5, 700])
        self.assertTrue(self.page.paper[350, 700])

    def test_text_block_holds_the_text_and_not_the_margin(self):
        x, y, w, h = self.page.block
        bx0, by0, bx1, by1 = synthetic.BLOCK
        self.assertLessEqual(x, bx0)
        self.assertGreaterEqual(x + w, bx1 - 40)
        self.assertLessEqual(y, by0 + 20)
        self.assertGreaterEqual(y + h, by1 - 30)
        self.assertGreater(x, synthetic.FOLIO[2], "folio number must be outside the text block")

    def test_ink_colours_are_found_and_kept_apart(self):
        for key, mask, other in (("red", self.page.red, self.page.black),
                                 ("black", self.page.black, self.page.red)):
            truth = self.truth[key]
            recall = (mask & truth).sum() / truth.sum()
            self.assertGreater(recall, 0.90, f"{key} ink found: {recall:.1%}")
            wrong = (other & truth).sum() / truth.sum()
            self.assertLess(wrong, 0.02, f"{key} ink given the other colour: {wrong:.1%}")
        self.assertLess((self.page.ink & ~(self.truth["red"] | self.truth["black"])).sum(),
                        0.05 * self.page.ink.sum(), "too much ink where nothing was drawn")

    def test_border_is_not_ink(self):
        for x0 in (150, synthetic.W - 150 - 44):
            self.assertEqual(self.page.ink[:, x0:x0 + 44].sum(), 0)


@unittest.skipUnless((SAMPLES / "page1.jpg").is_file(), "sample pages not present")
class SamplePageTests(unittest.TestCase):
    """Regression checks on the real pages: values were measured when C1 was tuned."""

    def _prepare(self, name):
        rgb, _ = io_utils.load_image(SAMPLES / name)
        return prepare_page(rgb, Config())

    def _check_block(self, page):
        x, y, w, h = page.block
        # text spans about x 400-3260, y 250-1520; folio numbers lie left of x 390 and right of x 3290
        self.assertTrue(370 <= x <= 420 and 3240 <= x + w <= 3290, page.block)
        self.assertTrue(220 <= y <= 270 and 1500 <= y + h <= 1560, page.block)

    def test_page1_red_and_black(self):
        for name in ("page1.jpg", "cleaned/page1.jpg"):
            page = self._prepare(name)
            self._check_block(page)
            # 8 red lines and 3 black lines
            self.assertGreater(page.red.sum(), 2 * page.black.sum(), name)
            self.assertGreater(page.black.sum(), 200_000, name)

    def test_page2_is_black(self):
        for name in ("page2.jpg", "cleaned/page2.jpg"):
            page = self._prepare(name)
            self._check_block(page)
            self.assertLess(page.red.sum(), 0.01 * page.black.sum(), name)


if __name__ == "__main__":
    unittest.main()

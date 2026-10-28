"""C1: page preparation on a synthetic page and on the two sample pages."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import samplepages                                                  # noqa: E402
import synthetic                                                    # noqa: E402
from letter_extractor import io_utils                               # noqa: E402
from letter_extractor.config import Config                          # noqa: E402
from letter_extractor.pipeline import process_page                  # noqa: E402
from letter_extractor.prepare import prepare_page, ruled_lines      # noqa: E402

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


class BorderTests(unittest.TestCase):
    """Faint, broken side borders close to the text (docs/plans/BORDER_PLAN.md): the cut stays between them."""

    @classmethod
    def setUpClass(cls):
        cls.rgb, cls.truth = synthetic.make_page(broken_borders=True)
        off = Config()
        off.border_clip = False
        cls.old = prepare_page(cls.rgb, off)
        cls.page = prepare_page(cls.rgb, Config())

    def _border_ink(self, page):
        return sum(int(page.ink[:, x0:x1].sum()) for x0, x1 in synthetic.BROKEN_BORDERS)

    def test_without_the_clip_the_border_is_cut(self):
        self.assertGreater(self._border_ink(self.old), 1000, "the test page must show the problem")

    def test_border_is_not_ink(self):
        self.assertEqual(self._border_ink(self.page), 0)
        left, right = self.page.borders
        self.assertTrue(205 <= left < 230, self.page.borders)
        self.assertTrue(1160 < right <= 1182, self.page.borders)

    def test_text_is_kept_and_the_folio_dropped(self):
        truth = self.truth["red"] | self.truth["black"]
        self.assertGreater((self.page.ink & truth).sum() / truth.sum(), 0.90)
        self.assertGreater(self.page.block[0], synthetic.FOLIO[2])

    def test_no_letter_is_cut_from_the_border(self):
        d = process_page(self.rgb, Config())
        for L in d.letters:
            x, _, w, _ = L.box
            for x0, x1 in synthetic.BROKEN_BORDERS:
                self.assertFalse(x < x1 and x + w > x0 and L.mask[:, max(0, x0 - x):x1 - x].any(), (L.box, L.rules))

    def test_pages_without_such_borders_do_not_change(self):
        off = Config()
        off.border_clip = False
        rgb, _ = synthetic.make_page()
        ruled = rgb.copy()
        ruled[100:600, 700:704] = synthetic.BLACK_INK      # a rule between two text columns: never a border
        lines, _, _ = synthetic.make_lines_page()
        for img in (rgb, ruled, lines, synthetic.make_letters_page()[0]):
            self.assertEqual(prepare_page(img, Config()).block, prepare_page(img, off).block)


class RuledLineTests(unittest.TestCase):
    def test_a_long_headline_is_not_a_rule(self):
        ink = np.zeros((400, 1000), bool)
        ink[100:108, 100:700] = True                 # a word's headline, 60 % of the width...
        for x in range(100, 700, 40):                # ...with its letters hanging from it (body and stem)
            ink[115:150, x + 4:x + 34] = True
            ink[108:150, x + 28:x + 34] = True
        ink[300:306, 100:900] = True                 # a rule with nothing hanging from it
        rules = ruled_lines(ink, Config())
        self.assertEqual(rules[100:150].sum(), 0, "headline taken for a rule")
        self.assertTrue(rules[300:306, 100:900].all(), "rule kept as ink")

    def test_a_vertical_rule_is_still_a_rule(self):
        ink = np.zeros((400, 1000), bool)
        ink[20:380, 900:906] = True
        ink[50:60, 902:960] = True                   # text touching it does not save it
        self.assertTrue(ruled_lines(ink, Config())[20:380, 900:906].all())


@unittest.skipUnless((SAMPLES / "page1.jpg").is_file(), "sample pages not present")
class SamplePageTests(unittest.TestCase):
    """Regression checks on the real pages: values were measured when C1 was tuned."""
    LEVEL = samplepages.LEVEL

    def _prepare(self, name):
        if name in ("page1.jpg", "page2.jpg"):
            return samplepages.processed(name).page                     # cut once, shared
        rgb, _ = io_utils.load_image(SAMPLES / name)
        return prepare_page(rgb, Config())

    def _check_block(self, page):
        x, y, w, h = page.block
        # text spans about x 430-3215, y 250-1520, between the inner red rules (about x 428 and 3225 on
        # the raw scans: the block stops there, docs/plans/BORDER_PLAN.md); folio numbers lie left of x 390 and right of x 3290
        self.assertTrue(370 <= x <= 435 and 3215 <= x + w <= 3290, page.block)
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

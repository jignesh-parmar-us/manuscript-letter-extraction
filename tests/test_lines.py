"""C2: line detection on synthetic pages and on the two sample pages."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import synthetic                                                    # noqa: E402
from letter_extractor import io_utils                               # noqa: E402
from letter_extractor.config import Config                          # noqa: E402
from letter_extractor.lines import detect_lines, line_image         # noqa: E402
from letter_extractor.prepare import prepare_page                   # noqa: E402

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


class SlantedPageTests(unittest.TestCase):
    """A page scanned at a slant: each line drifts by more than half a line pitch across the page,
    far beyond the search around its average row. Its headline is followed from window to window,
    and the two profile peaks such a line can give end as one line."""

    def test_every_line_is_followed_to_both_ends(self):
        cfg = Config()
        rgb, heads, marks = synthetic.make_lines_page(slope=0.05, wave=2.0)       # 60 px over the page
        layout = detect_lines(prepare_page(rgb, cfg), cfg)
        self.assertEqual(len(layout.lines), len(heads))
        for line, truth in zip(layout.lines, heads):
            x, _, w, _ = line.box
            cols = np.arange(x + 10, x + w - 10)
            err = np.abs(line.headline_y[cols] - truth[cols])
            self.assertLessEqual(np.percentile(err, 95), 2.0, f"line {line.index}: max error {err.max():.1f}")
        wrong = [(n, x, y) for n, x, y in marks
                 if not any(ln.index == n and ln.box[0] <= x < ln.box[0] + ln.box[2]
                            and ln.box[1] <= y < ln.box[1] + ln.box[3] and ln.mask[y - ln.box[1], x - ln.box[0]]
                            for ln in layout.lines)]
        self.assertEqual(wrong, [], "marks given to the wrong line")


class SlopedWavyLinesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = Config()
        cls.rgb, cls.heads, cls.marks = synthetic.make_lines_page()
        cls.page = prepare_page(cls.rgb, cls.cfg)
        cls.layout = detect_lines(cls.page, cls.cfg)

    def test_every_line_is_found(self):
        self.assertIsNotNone(self.layout)
        self.assertEqual(len(self.layout.lines), len(self.heads))

    def test_headline_is_traced_within_2_px(self):
        for line, truth in zip(self.layout.lines, self.heads):
            x, _, w, _ = line.box
            cols = np.arange(x + 10, x + w - 10)
            err = np.abs(line.headline_y[cols] - truth[cols])
            self.assertLessEqual(np.percentile(err, 95), 2.0, f"line {line.index}: max error {err.max():.1f}")

    def test_detached_marks_go_to_their_own_line(self):
        wrong = []
        for number, x, y in self.marks:
            owner = [ln.index for ln in self.layout.lines
                     if ln.box[0] <= x < ln.box[0] + ln.box[2] and ln.box[1] <= y < ln.box[1] + ln.box[3]
                     and ln.mask[y - ln.box[1], x - ln.box[0]]]
            if owner != [number]:
                wrong.append((number, x, y, owner))
        self.assertEqual(wrong, [], "marks given to the wrong line")

    def test_lines_share_no_ink_and_cover_all_of_it(self):
        total = np.zeros(self.page.ink.shape, np.int32)
        for ln in self.layout.lines:
            x, y, w, h = ln.box
            total[y:y + h, x:x + w] += ln.mask
        self.assertEqual(total.max(), 1)
        self.assertEqual(int(total.sum()), int(self.page.ink.sum()))

    def test_line_image_keeps_only_its_own_ink(self):
        line = self.layout.lines[2]
        img = line_image(self.page, line, self.cfg)
        m = self.cfg.line_margin_px
        self.assertEqual(img.shape[:2], (line.box[3] + 2 * m, line.box[2] + 2 * m))
        # outside the line's own ink, nothing as dark as ink is left
        x, y, w, h = line.box
        own = np.zeros(img.shape[:2], bool)
        own[m:m + h, m:m + w] = line.mask
        grow = np.zeros_like(own)
        grow[1:-1, 1:-1] = own[1:-1, 1:-1] | own[:-2, 1:-1] | own[2:, 1:-1] | own[1:-1, :-2] | own[1:-1, 2:]
        self.assertGreater(np.percentile(img[~grow].mean(axis=1), 0.5), 100)


class FlatLinesTests(unittest.TestCase):
    def test_straight_lines_and_ink_colour(self):
        rgb, _ = synthetic.make_page()
        cfg = Config()
        layout = detect_lines(prepare_page(rgb, cfg), cfg)
        n = len(range(synthetic.BLOCK[1] + 20, synthetic.BLOCK[3], synthetic.LINE_PITCH))
        self.assertEqual(len(layout.lines), n)
        self.assertEqual([ln.ink for ln in layout.lines],
                         ["red"] * synthetic.RED_LINES + ["black"] * (n - synthetic.RED_LINES))


@unittest.skipUnless((SAMPLES / "page1.jpg").is_file(), "sample pages not present")
class SamplePageLinesTests(unittest.TestCase):
    def test_eleven_lines_on_every_sample_page(self):
        cfg = Config()
        for name in ("page1.jpg", "page2.jpg", "cleaned/page1.jpg", "cleaned/page2.jpg"):
            rgb, _ = io_utils.load_image(SAMPLES / name)
            layout = detect_lines(prepare_page(rgb, cfg), cfg)
            self.assertEqual(len(layout.lines), 11, name)
            self.assertTrue(105 <= layout.spacing <= 120, (name, layout.spacing))
            if "page1" in name:          # 8 red lines, then black (the 8th ends in black)
                self.assertEqual([ln.ink for ln in layout.lines[:7]], ["red"] * 7, name)
                self.assertEqual([ln.ink for ln in layout.lines[8:]], ["black"] * 3, name)
            else:
                self.assertEqual({ln.ink for ln in layout.lines}, {"black"}, name)


if __name__ == "__main__":
    unittest.main()

"""C3b: join and split rules, letter samples."""
import csv
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import synthetic                                                    # noqa: E402
from letter_extractor import io_utils                               # noqa: E402
from letter_extractor.config import Config                          # noqa: E402
from letter_extractor.pipeline import process_folder, process_page  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


class RulesTests(unittest.TestCase):
    def _check(self, colour):
        rgb, expected = synthetic.make_letters_page(colour=colour)
        d = process_page(rgb, Config())
        self.assertEqual(len(d.layout.lines), len(expected))
        for line, exp in zip(d.layout.lines, expected):
            got = [L for L in d.letters if L.line == line.index]
            self.assertEqual(len(got), len(exp), [(L.box, L.kind, L.rules) for L in got])
            for L, (kind, x_from, x_to, points) in zip(got, exp):
                x, y, w, h = L.box
                self.assertEqual(L.kind, kind, (L.box, L.rules))
                self.assertTrue(x <= x_from + 3 and x + w >= x_to - 3, (L.box, x_from, x_to, L.rules))
                for px, py in points:
                    lx, ly = px - x, py - y
                    self.assertTrue(0 <= lx < w and 0 <= ly < h and L.mask[ly, lx], (L.box, (px, py), L.rules))
            self.assertEqual([L.pos for L in got], list(range(1, len(got) + 1)))

    def test_black(self):
        self._check(synthetic.BLACK_INK)

    def test_red(self):
        self._check(synthetic.RED_INK)

    def test_letters_share_no_ink(self):
        rgb, _ = synthetic.make_letters_page()
        d = process_page(rgb, Config())
        seen = np.zeros(d.page.ink.shape, np.int32)
        for L in d.letters:
            x, y, w, h = L.box
            seen[y:y + h, x:x + w] += L.mask
        self.assertEqual(seen.max(), 1)
        # every ink pixel of every line ends up in a letter
        lines = np.zeros_like(seen)
        for ln in d.layout.lines:
            x, y, w, h = ln.box
            lines[y:y + h, x:x + w] += ln.mask
        self.assertEqual(int(seen.sum()), int(lines.sum()))


class OutputTests(unittest.TestCase):
    def test_letter_images_and_samples_csv(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "in").mkdir()
            rgb, expected = synthetic.make_letters_page()
            Image.fromarray(rgb).save(tmp / "in" / "p1.png")
            process_folder(tmp / "in", tmp / "out", Config(workers=1))
            with open(tmp / "out" / "samples.csv", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), sum(len(e) for e in expected))
            self.assertEqual(rows[0]["image"], "letters/p1/L01_001.png")
            n = len(expected[0])
            self.assertEqual([r["kind"] for r in rows[:n]], [e[0] for e in expected[0]])
            for r in rows:
                with Image.open(tmp / "out" / r["image"]) as img:
                    size = img.size
                m = Config().letter_margin_px
                self.assertEqual(size, (int(r["w"]) + 2 * m, int(r["h"]) + 2 * m))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless((SAMPLES / "page1.jpg").is_file(), "sample pages not present")
class SamplePageLettersTests(unittest.TestCase):
    """Baseline measured when C3b was tuned (docs/TUNING.md): 36-44 letters per line, dandas found
    on page 1 (red verses) and only a few on page 2 (prose)."""

    def test_letters_per_line(self):
        cfg = Config()
        for name, dandas in (("page1.jpg", (15, 40)), ("page2.jpg", (0, 6))):
            rgb, _ = io_utils.load_image(SAMPLES / name)
            d = process_page(rgb, cfg)
            per_line = len(d.letters) / len(d.layout.lines)
            self.assertTrue(36 <= per_line <= 44, (name, per_line))
            n_danda = sum(L.kind == "danda" for L in d.letters)
            self.assertTrue(dandas[0] <= n_danda <= dandas[1], (name, n_danda))


if __name__ == "__main__":
    unittest.main()

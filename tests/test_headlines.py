"""Headlines given back to samples cut while the rule finder still erased them (app/headlines.py)."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import synthetic                                                    # noqa: E402
from letter_extractor.app import headlines as HL                   # noqa: E402
from letter_extractor.app.db import Sample                          # noqa: E402
from letter_extractor.app.library import Library                    # noqa: E402
from letter_extractor.config import Config                          # noqa: E402
from sqlalchemy import select                                       # noqa: E402

QUIET = dict(progress=lambda _m: None)


def long_words_page():
    """Three lines, each a word of eight letters joined by one headline 368 px long (more than 15 % of the
    1600 px page, so the old rule finder took it for a ruled line), then three short words that kept theirs."""
    rng = np.random.default_rng(7)
    img = np.empty((800, 1600, 3), np.float32)
    img[:] = synthetic.PAPER
    img += rng.normal(0, 3.0, (800, 1600, 1))
    for i in range(3):
        hy = 120 + i * 110
        for start, n in ((100, 8), (508, 2), (640, 2), (772, 2)):
            for k in range(n):
                synthetic._block_letter(img, start + 46 * k, hy, synthetic.BLACK_INK)
    return np.clip(img, 0, 255).astype(np.uint8)


class HeadlineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="headlines-"))
        pages = cls.tmp / "pages"
        pages.mkdir()
        Image.fromarray(long_words_page()).save(pages / "p1.png")
        cls.lib = Library(cls.tmp / "lib")
        cls.book = cls.lib.create_book("Long words", pages, cfg=Config(rule_headline_frac=2.0)).id   # cut as before
        cls.lib.capture(cls.book)
        cls.lib.set_book_config(cls.book, Config())                                                   # the fix

    @classmethod
    def tearDownClass(cls):
        cls.lib.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def samples(self):
        folder = self.lib.book_dir(self.lib.get_book(self.book))
        out = {}
        with self.lib.session() as s:
            for x in s.scalars(select(Sample).where(Sample.book_id == self.book, Sample.deleted.is_(False))):
                with Image.open(folder / x.mask) as im:
                    ink = int((np.asarray(im) > 127).sum())
                out[x.id] = ((x.x, x.y, x.w, x.h), x.group_id, ink, x.fingerprint)
        return out

    def test_list_fix_undo(self):
        before = self.samples()
        rows = HL.affected(self.lib, self.book, **QUIET)
        hit = {sid for r in rows for sid in r["sample_ids"]}
        in_long = {sid for sid, ((x, _, w, _), *_) in before.items() if x + w <= 100 + 8 * 46}
        self.assertGreaterEqual(len(in_long), 24)
        self.assertEqual(hit, in_long, "the long words' samples lost their headline, the short words' did not")

        r = HL.restore(self.lib, self.book, [r["group"] for r in rows], **QUIET)
        self.assertEqual(r["samples"], len(hit))
        after = self.samples()
        self.assertEqual(set(after), set(before), "every sample keeps its id")
        for sid in hit:
            (x0, y0, w0, h0), g0, ink0, fp0 = before[sid]
            (x1, y1, w1, h1), g1, ink1, fp1 = after[sid]
            self.assertEqual(g1, g0, "and its group")
            self.assertLess(y1, y0, "the box grows up to the headline")
            self.assertGreater(ink1, ink0 + 4 * w0, "the headline (10 px high) is back in the mask")
            self.assertNotEqual(fp1, fp0)
        self.assertEqual(HL.affected(self.lib, self.book, **QUIET), [], "nothing is left to give back")
        self.assertEqual(HL.restore(self.lib, self.book, [r["group"] for r in rows], **QUIET)["samples"], 0)

        backup = Path(r["backup"])
        self.assertEqual(len(json.loads((backup / "backup.json").read_text())["samples"]), len(hit))
        HL.undo(self.lib, self.book, backup)
        self.assertEqual(self.samples(), before, "undo puts masks, boxes and fingerprints back")


class GivenBackTests(unittest.TestCase):
    """`_given_back` on its own: what comes back is the lost ink in the sample's columns, above and in its box."""

    class Smp:
        x, y, w, h = 10, 20, 30, 40

    def test_lost_ink_above_and_in_the_box(self):
        lost = np.zeros((100, 100), bool)
        lost[12:22, 0:60] = True                      # a headline from 8 px above the box into it
        mask = np.ones((40, 30), bool)
        box, m = HL._given_back(lost, self.Smp, mask)
        self.assertEqual(box, (10, 12, 30, 48))       # same columns; from the headline's top
        self.assertTrue(m.all())

    def test_nothing_lost_nothing_given(self):
        lost = np.zeros((100, 100), bool)
        lost[12:22, 50:90] = True                     # another letter's columns
        self.assertIsNone(HL._given_back(lost, self.Smp, np.ones((40, 30), bool)))
        lost = np.zeros((100, 100), bool)
        lost[30:35, 10:40] = True                     # already in the mask
        self.assertIsNone(HL._given_back(lost, self.Smp, np.ones((40, 30), bool)))


if __name__ == "__main__":
    unittest.main()

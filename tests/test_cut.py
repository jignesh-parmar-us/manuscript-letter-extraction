"""C12c: cutting lines into letters by Tesseract's reading (with a stand-in for Tesseract)."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import appbook                                                                  # noqa: E402
from letter_extractor.app.db import OcrReading, Sample                         # noqa: E402
from letter_extractor.app.library import Library                               # noqa: E402
from letter_extractor.config import Config                                     # noqa: E402
from letter_extractor.lines import Line                                        # noqa: E402
from letter_extractor.ocr import cut                                           # noqa: E402
from letter_extractor.ocr.aksharas import Akshara                              # noqa: E402
from letter_extractor.ocr.tesseract import Char, LineReading, TesseractError, Word, ink_mask   # noqa: E402
from letter_extractor.prepare import PreparedPage                              # noqa: E402
from sqlalchemy import select                                                  # noqa: E402

CFG = Config()
LX = 100                                   # the line's x on the page
X0 = LX - CFG.line_margin_px               # the line image's x on the page


def page_with_line(widths, gap=8, height=50):
    """A page with one line of letter-like shapes under one headline; the line and the letters'
    page x spans."""
    total = sum(widths) + gap * (len(widths) - 1)
    mask = np.zeros((height, total), bool)
    mask[4:7, :] = True
    spans, x = [], 0
    for w in widths:
        mask[16:30, x + 2:x + w - 6] = True
        mask[4:46, x + w - 6:x + w - 1] = True
        spans.append((LX + x, LX + x + w))
        x += w + gap
    H, W = 120, LX + total + 50
    ink = np.zeros((H, W), bool)
    ink[30:30 + height, LX:LX + total] = mask
    page = PreparedPage(rgb=np.where(ink[..., None], 0, 255).astype(np.uint8).repeat(3, 2), paper=~ink,
                        black=ink, red=np.zeros_like(ink), rules=np.zeros_like(ink), block=(0, 0, W, H))
    line = Line(index=1, box=(LX, 30, total, height), mask=mask, headline_y=np.full(W, 35), ink="black")
    return page, line, spans


def aks(texts, spans, shift=0):
    """Aksharas with boxes in the line image (page x minus X0), optionally shifted like Tesseract's."""
    return [Akshara(t, (a - X0 + shift, 0, b - a, 40), 95.0, chars=[Char(t, (a - X0 + shift, 0, b - a, 40), 95.0)])
            for t, (a, b) in zip(texts, spans)]


class CutLineTests(unittest.TestCase):
    def test_one_letter_per_akshara_at_the_gaps(self):
        page, line, spans = page_with_line([40, 40, 40, 40])
        letters = cut.cut_line(page, line, aks(["क", "ता", "र्क", "॥"], spans, shift=-10), X0, CFG)
        self.assertEqual([L.text for L in letters], ["क", "ता", "र्क", "॥"])
        self.assertEqual([L.kind for L in letters], ["letter", "letter", "letter", "danda"])
        for L, (a, b) in zip(letters, spans):            # each cut lies in the gap before the letter
            self.assertTrue(a - 9 <= L.box[0] <= a + 1, (L.box, a))
            self.assertTrue(b - 1 <= L.box[0] + L.box[2] <= b + 9, (L.box, b))
        self.assertEqual([L.pos for L in letters], [1, 2, 3, 4])
        self.assertTrue(all(L.rules == ["tesseract"] for L in letters))

    def test_cuts_too_close_together_keep_aksharas_in_one_sample(self):
        page, line, spans = page_with_line([40, 40, 40])
        # Tesseract reads 4 aksharas; two of them squeezed into the second letter
        mid = spans[1]
        squeezed = [spans[0], (mid[0], mid[0] + 6), (mid[0] + 6, mid[1]), spans[2]]
        letters = cut.cut_line(page, line, aks(["क", "ख", "ग", "घ"], squeezed), X0, CFG)
        self.assertEqual([L.text for L in letters], ["क", "खग", "घ"])

    def test_an_akshara_without_a_box_stays_with_its_neighbour(self):
        page, line, spans = page_with_line([40, 40, 40])
        a = aks(["क", "ख", "ग"], spans)
        a[1] = Akshara("ख", (0, 0, 0, 0), 95.0, chars=[Char("ख", (0, 0, 0, 0), 95.0)])
        a.insert(2, Akshara("ं", (0, 0, 0, 0), 95.0, chars=[Char("ं", (0, 0, 0, 0), 95.0)]))
        letters = cut.cut_line(page, line, a, X0, CFG)
        self.assertEqual(len(letters), 2)                        # ख and ं have no boxes: one sample with ग
        self.assertEqual(letters[0].text, "क")


class FallbackTests(unittest.TestCase):
    def test_a_line_tesseract_cannot_read_keeps_the_shape_cut(self):
        page, line, spans = page_with_line([40, 40, 40])
        class L:
            def __init__(self):
                self.line = 1

        shape = [L(), L(), L()]

        def broken(img):
            raise TesseractError("not installed")
        self.assertEqual(cut.tesseract_letters(page, [line], shape, CFG, reader=broken), shape)
        empty = lambda img: LineReading(words=[], hocr="", scale=1.0)                 # noqa: E731
        self.assertEqual(cut.tesseract_letters(page, [line], shape, CFG, reader=empty), shape)

    def test_a_readable_line_is_cut_by_the_reading(self):
        page, line, spans = page_with_line([40, 40, 40])

        def reader(img):
            chars = [Char(t, (a - X0 + 10, 10, b - a, 40), 95.0) for t, (a, b) in zip("कखग", spans)]
            return LineReading(words=[Word((0, 0, 1, 1), 95.0, chars)], hocr="", scale=1.0)
        letters = cut.tesseract_letters(page, [line], [], CFG, reader=reader)
        self.assertEqual([L.text for L in letters], ["क", "ख", "ग"])


def fake_read_line(img, engine, **kw):
    """Stand-in for Tesseract on the synthetic pages: one "क" per 30 px of the line's ink."""
    ink = ink_mask(img)
    cols = np.flatnonzero(ink.any(axis=0))
    if cols.size == 0:
        return LineReading(words=[], hocr="", scale=1.0)
    chars = [Char("क", (int(x) + 10, 10, 30, 40), 95.0) for x in range(int(cols[0]), int(cols[-1]) - 15, 30)]
    return LineReading(words=[Word((0, 0, 1, 1), 95.0, chars)], hocr="", scale=1.0)


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        pages = self.tmp / "pages"
        pages.mkdir()
        appbook.add_page(pages, "p1.png")
        self.lib = Library(self.tmp / "lib")
        self.book = self.lib.create_book("T", pages, Config(cut_method="tesseract", workers=1, save_masks=True),
                                         writing="printed").id

    def tearDown(self):
        self.lib.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_capture_cuts_by_the_reading_and_keeps_it(self):
        with mock.patch.object(cut, "engine", lambda cfg: None), mock.patch.object(cut, "read_line", fake_read_line):
            self.lib.capture(self.book)
        with self.lib.session() as s:
            smps = s.scalars(select(Sample).where(Sample.book_id == self.book)).all()
            self.assertTrue(smps)
            cut_by_reading = [x for x in smps if x.rules == "tesseract"]
            self.assertGreater(len(cut_by_reading), 0.5 * len(smps))
            reads = s.scalars(select(OcrReading)).all()
            self.assertEqual(len(reads), len(cut_by_reading))
            self.assertEqual({r.text_dev for r in reads}, {"क"})

    def test_capture_labels_the_groups_from_the_reading(self):
        from letter_extractor.app.db import LetterGroup
        with mock.patch.object(cut, "engine", lambda cfg: None), mock.patch.object(cut, "read_line", fake_read_line):
            r = self.lib.capture(self.book)
        self.assertEqual(r["labelled_groups"], 1)                    # everything was read as क: one group
        with self.lib.session() as s:
            groups = s.scalars(select(LetterGroup).where(LetterGroup.book_id == self.book,
                                                         LetterGroup.label_dev != "")).all()
            self.assertEqual([(g.label_dev, g.label_guj, g.status) for g in groups], [("क", "ક", "auto")])
            read = s.scalars(select(Sample.group_id).join(OcrReading, OcrReading.sample_id == Sample.id)).all()
            self.assertGreater(sum(gid == groups[0].id for gid in read), 0.8 * len(read))
        self.assertFalse(self.lib.has_manual_work(self.book))       # capturing again needs no confirmation

    def test_shape_cut_books_get_no_labels_at_capture(self):
        from letter_extractor.app.db import LetterGroup
        self.lib.set_book_config(self.book, Config(cut_method="shapes", workers=1, save_masks=True))
        r = self.lib.capture(self.book)
        self.assertNotIn("labelled_groups", r)
        with self.lib.session() as s:
            self.assertEqual(s.scalars(select(LetterGroup).where(LetterGroup.label_dev != "")).all(), [])

    def test_unknown_cut_method_fails_the_page(self):
        from letter_extractor.pipeline import process_page
        with self.assertRaises(ValueError):
            process_page(np.full((50, 50, 3), 255, np.uint8), Config(cut_method="magic"))


if __name__ == "__main__":
    unittest.main()

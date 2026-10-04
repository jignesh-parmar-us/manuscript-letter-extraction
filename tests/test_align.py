"""C11: matching OCR aksharas to cut samples within a line."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from letter_extractor.ocr.aksharas import Akshara                                   # noqa: E402
from letter_extractor.ocr.align import akshara_spans, align_line, inside, overlap   # noqa: E402
from letter_extractor.ocr.tesseract import Char                                     # noqa: E402


def ak(text, x0, x1, conf=95.0):
    """An akshara whose characters share one box (x0..x1); x0 = x1 = None: no box."""
    box = (x0, 0, x1 - x0, 40) if x0 is not None else (0, 0, 0, 0)
    return Akshara(text=text, box=box, conf=conf, chars=[Char(text, box, conf, [(text, conf)])])


def texts(al):
    return [(m.sample, m.text) for m in al.matches]


SAMPLES = [(0, 40), (40, 80), (80, 120), (120, 160)]


class OverlapTests(unittest.TestCase):
    def test_overlap_and_inside(self):
        self.assertEqual(overlap((0, 40), (20, 60)), 0.5)
        self.assertEqual(overlap((0, 40), (10, 20)), 1.0)          # share of the narrower span
        self.assertEqual(overlap(None, (0, 10)), 0.0)
        self.assertEqual(inside((10, 20), (0, 40)), 1.0)
        self.assertEqual(inside((30, 50), (0, 40)), 0.5)


class AlignTests(unittest.TestCase):
    def test_equal_counts(self):
        al = align_line([ak("क", 2, 38), ak("ख", 41, 79), ak("ग", 82, 118), ak("घ", 121, 159)], SAMPLES)
        self.assertEqual(texts(al), [(0, "क"), (1, "ख"), (2, "ग"), (3, "घ")])
        self.assertFalse(al.refused)

    def test_offset_of_the_line_image(self):
        al = align_line([ak("क", 2, 38), ak("ख", 41, 79), ak("ग", 82, 118), ak("घ", 121, 159)],
                        [(x0 + 500, x1 + 500) for x0, x1 in SAMPLES], dx=500)
        self.assertEqual(len(al.matches), 4)

    def test_ocr_splits_one_sample_in_two(self):
        # sample 1 holds a word that was not cut: both aksharas lie inside it, so its reading is the word
        al = align_line([ak("क", 2, 38), ak("ख", 42, 58), ak("ग", 61, 78), ak("घ", 82, 118), ak("च", 121, 159)],
                        SAMPLES)
        self.assertEqual(texts(al), [(0, "क"), (1, "खग"), (2, "घ"), (3, "च")])

    def test_ocr_merges_two_samples(self):
        # one akshara over samples 1 and 2 (a conjunct cut in two): neither gets a reading
        al = align_line([ak("क", 2, 38), ak("क्ष", 41, 119), ak("घ", 121, 159)], SAMPLES)
        self.assertEqual(texts(al), [(0, "क"), (3, "घ")])

    def test_missing_akshara(self):
        al = align_line([ak("क", 2, 38), ak("ग", 82, 118), ak("घ", 121, 159)], SAMPLES)
        self.assertEqual(texts(al), [(0, "क"), (2, "ग"), (3, "घ")])

    def test_akshara_without_a_box_gets_the_gap(self):
        aks = [ak("क", 2, 38), ak("ख", None, None), ak("ग", 82, 118), ak("घ", 121, 159)]
        self.assertEqual(akshara_spans(aks)[1], (38, 82))
        al = align_line(aks, SAMPLES)
        self.assertIn((1, "ख"), texts(al))

    def test_implausibly_wide_character_box_is_ignored(self):
        # the vowel sign's box spans the whole line; the akshara is placed by its consonant
        box_k, wide = (41, 0, 30, 40), (0, 0, 160, 40)
        a = Akshara(text="खा", box=(0, 0, 160, 40), conf=90, chars=[Char("ख", box_k, 90), Char("ा", wide, 90)])
        aks = [ak("क", 2, 38), a, ak("ग", 82, 118), ak("घ", 121, 159)]
        self.assertEqual(akshara_spans(aks)[1], (41, 71))
        self.assertIn((1, "खा"), texts(align_line(aks, SAMPLES)))

    def test_unclear_overlap_is_left_unmatched(self):
        # half on sample 1, half on sample 2: better no reading than a wrong one
        al = align_line([ak("क", 2, 38), ak("ख", 60, 100), ak("ग", 121, 159)], SAMPLES, min_matched=0)
        self.assertNotIn(1, [m.sample for m in al.matches])
        self.assertNotIn(2, [m.sample for m in al.matches])

    def test_line_refused_when_too_few_samples_match(self):
        al = align_line([ak("क", 2, 38)], SAMPLES)
        self.assertTrue(al.refused)
        self.assertEqual(al.matches, [])

    def test_empty(self):
        self.assertEqual(align_line([], []).matches, [])
        self.assertTrue(align_line([], SAMPLES).refused)

    def test_confidence_and_alternatives(self):
        al = align_line([ak("क", 2, 38, 70), ak("ख", 42, 58, 90), ak("ग", 61, 78, 80), ak("घ", 82, 118),
                         ak("च", 121, 159)], SAMPLES)
        m = al.matches[1]
        self.assertEqual((m.text, m.conf), ("खग", 80))
        self.assertEqual(m.alternatives, [[("ख", 90)], [("ग", 80)]])


if __name__ == "__main__":
    unittest.main()

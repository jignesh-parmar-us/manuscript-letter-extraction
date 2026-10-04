"""C10: splitting Devanagari text into aksharas, and OCR characters into aksharas with boxes."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from letter_extractor.ocr.aksharas import group_chars, split_aksharas, split_spans   # noqa: E402
from letter_extractor.ocr.tesseract import Char                                      # noqa: E402


class SplitTests(unittest.TestCase):
    def test_single_units(self):
        for word in ["क", "कि", "क्ष", "श्री", "र्क", "द्ध्य", "कं", "कः", "कँ", "ॐ", "।", "॥", "अ", "अं", "ऋ",
                     "क़ि", "क्‍ष"]:
            self.assertEqual(split_aksharas(word), [word], word)

    def test_words(self):
        self.assertEqual(split_aksharas("स्वामियेपुछ्युं"), ["स्वा", "मि", "ये", "पु", "छ्युं"])
        self.assertEqual(split_aksharas("श्रीजिमहाराज"), ["श्री", "जि", "म", "हा", "रा", "ज"])
        self.assertEqual(split_aksharas("नमो॥१॥"), ["न", "मो", "॥", "१", "॥"])

    def test_digits_are_separate(self):
        self.assertEqual(split_aksharas("१२३"), ["१", "२", "३"])

    def test_spaces_are_skipped(self):
        self.assertEqual(split_aksharas("क ख"), ["क", "ख"])

    def test_final_halant_stays_with_its_consonant(self):
        self.assertEqual(split_aksharas("वाक्"), ["वा", "क्"])

    def test_orphan_vowel_sign(self):
        spans = split_spans("िक")
        self.assertEqual(spans, [(0, 1, True), (1, 2, False)])
        self.assertEqual(split_spans("ं")[0][2], True)

    def test_nfc(self):
        # क + nukta (two code points) and the composed क़ give the same akshara
        self.assertEqual(split_aksharas("क़"), split_aksharas("क़"))


class GroupCharsTests(unittest.TestCase):
    def test_boxes_and_confidence(self):
        chars = [Char("क", (10, 5, 20, 30), 99.0), Char("ि", (5, 0, 30, 35), 80.0),
                 Char("त", (32, 5, 20, 30), 95.0)]
        out = group_chars(chars)
        self.assertEqual([a.text for a in out], ["कि", "त"])
        self.assertEqual(out[0].box, (5, 0, 30, 35))
        self.assertEqual(out[0].conf, 80.0)
        self.assertEqual(out[1].box, (32, 5, 20, 30))

    def test_empty_boxes_are_ignored(self):
        out = group_chars([Char("क", (10, 5, 20, 30), 99.0), Char("ं", (0, 0, 0, 0), 90.0)])
        self.assertEqual(out[0].text, "कं")
        self.assertEqual(out[0].box, (10, 5, 20, 30))

    def test_character_with_several_code_points(self):
        out = group_chars([Char("क्ष", (0, 0, 10, 10), 90.0), Char("ा", (8, 0, 4, 10), 95.0)])
        self.assertEqual([a.text for a in out], ["क्षा"])
        self.assertEqual(out[0].box, (0, 0, 12, 10))

    def test_orphan(self):
        out = group_chars([Char("ि", (0, 0, 5, 10), 70.0), Char("क", (5, 0, 10, 10), 99.0)])
        self.assertEqual([(a.text, a.orphan) for a in out], [("ि", True), ("क", False)])


if __name__ == "__main__":
    unittest.main()

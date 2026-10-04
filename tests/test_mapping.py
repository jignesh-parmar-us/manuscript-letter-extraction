"""C5b: Devanagari <-> Gujarati mapping, labels, categories, order and safe names."""
import re
import shutil
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from letter_extractor import mapping as mp                          # noqa: E402
from letter_extractor.config import Config                          # noqa: E402
from letter_extractor.mapping import (DATA, LabelError, canonical_label, category,   # noqa: E402
                                      code_points, describe, load_mapping, mapping_for, safe_name,
                                      sort_key, to_devanagari, to_gujarati, transliterate)


class MappingTests(unittest.TestCase):
    def test_examples_of_the_requirements(self):
        # Section 4: one to one at a fixed offset; conjuncts, reph and halant the same way
        for dev, guj in (("क", "ક"), ("कि", "કિ"), ("क्ष", "ક્ષ"), ("श्री", "શ્રી"), ("र्म", "ર્મ"),
                         ("ज्ञा", "જ્ઞા"), ("कं", "કં"), ("कः", "કઃ"), ("अ", "અ"), ("ॐ", "ૐ")):
            self.assertEqual(to_gujarati(dev), guj, dev)
            self.assertEqual(to_devanagari(guj), dev, guj)

    def test_danda_stays_devanagari(self):
        self.assertEqual(to_gujarati("।"), "।")
        self.assertEqual(to_gujarati("॥"), "॥")
        self.assertEqual(to_devanagari("॥"), "॥")

    def test_digits_gujarati_or_western(self):
        self.assertEqual(to_gujarati("१२"), "૧૨")
        self.assertEqual(to_gujarati("१२", load_mapping(digits="western")), "12")
        self.assertEqual(to_devanagari("૧૨"), "१२")
        self.assertEqual(to_devanagari("12"), "१२")
        with self.assertRaises(ValueError):
            load_mapping(digits="roman")

    def test_letters_without_gujarati_letter_use_nukta(self):
        for dev, guj in (("ऩ", "ન઼"), ("ऱ", "ર઼"), ("ऴ", "ળ઼"), ("क़", "ક઼"), ("फ़", "ફ઼")):
            self.assertEqual(to_gujarati(dev), guj, dev)
            self.assertEqual(to_gujarati(to_devanagari(guj)), guj)

    def test_offset_positions_that_are_other_characters_are_not_used(self):
        # U+0971 + 0x180 is the Gujarati rupee sign, U+097A-F + 0x180 are Gujarati nukta signs
        for cp in (0x0971, *range(0x097A, 0x0980)):
            ch = chr(cp)
            self.assertEqual(to_gujarati(ch), ch, f"U+{cp:04X} must stay Devanagari")

    def test_name_rule_holds_without_the_table(self):
        # a user's table may drop rows: the default rule alone must never map to another character
        tmp = Path(tempfile.mkdtemp())
        try:
            own = tmp / "empty.csv"
            own.write_text("devanagari,gujarati,note\n", encoding="utf-8")
            m = load_mapping(str(own))
            for cp in (0x0971, *range(0x097A, 0x0980), 0x0904, 0x0929):
                self.assertEqual(to_gujarati(chr(cp), m), chr(cp), f"U+{cp:04X}")
            self.assertEqual(to_gujarati("कि", m), "કિ")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_whole_devanagari_block_is_covered(self):
        m = load_mapping()
        for cp in range(0x0900, 0x0980):
            ch = chr(cp)
            try:
                unicodedata.name(ch)
            except ValueError:
                continue                                  # not assigned in Unicode
            out = m.to_guj.get(ch)
            if out is None:
                self.assertIn(ch, m.kept, f"U+{cp:04X} {unicodedata.name(ch)} is neither mapped nor listed")
            elif out not in ("।", "॥"):
                self.assertTrue(all(0x0A80 <= ord(c) < 0x0B00 for c in out), f"U+{cp:04X} -> {out!r}")

    def test_every_mapped_gujarati_character_round_trips(self):
        m = load_mapping()
        for dev, guj in m.to_guj.items():
            if len(guj) == 1 and 0x0A80 <= ord(guj) < 0x0B00:
                self.assertEqual(m.devanagari(guj), unicodedata.normalize("NFC", dev))

    def test_editing_the_table_changes_the_mapping(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            own = tmp / "mine.csv"
            text = DATA.read_text(encoding="utf-8").replace("।,।,", "।,|,")
            own.write_text(text, encoding="utf-8")
            self.assertEqual(to_gujarati("।", load_mapping(str(own))), "|")
            cfg = Config()
            cfg.mapping_file, cfg.digits = str(own), "western"
            self.assertEqual(to_gujarati("।१", mapping_for(cfg)), "|1")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class LabelTests(unittest.TestCase):
    def test_both_scripts_give_the_same_label(self):
        for dev, guj in (("कि", "કિ"), ("क्ष", "ક્ષ"), ("श्री", "શ્રી"), ("र्म", "ર્મ"), ("ऩ", "ન઼"), ("५", "૫")):
            self.assertEqual(canonical_label(dev), dev)
            self.assertEqual(canonical_label(guj), dev, guj)

    def test_normalization_and_invisible_characters(self):
        self.assertEqual(canonical_label("  कि \n"), "कि")
        self.assertEqual(canonical_label("क्‍ष"), "क्ष")        # zero-width joiner removed
        self.assertEqual(canonical_label("क़"), "क़")         # stored in NFC (letter + nukta)
        self.assertEqual(canonical_label("5"), "५")

    def test_valid_letters(self):
        for label in ("अ", "आं", "ऋ", "क", "कि", "कु", "कें", "कों", "क्", "क्ष", "क्षे", "श्री", "र्म", "स्त्री",
                      "ह्म", "च्चि", "कँ", "कः", "।", "॥", "ऽ", "ॐ", "०"):
            self.assertTrue(mp.is_label(label), label)

    def test_refused_with_a_reason(self):
        cases = {"": "empty", "कम": "क + म", "ि": "needs a letter", "ं": "needs a letter",
                 "्क": "needs a letter", "abc": "neither", "क़ab": "neither", "कિમ": "कि + म", "१२": "१ + २",
                 "कि।": "कि + ।"}
        for text, reason in cases.items():
            with self.assertRaises(LabelError, msg=text) as e:
                canonical_label(text)
            self.assertIn(reason, str(e.exception), text)

    def test_words_only_when_asked(self):
        self.assertEqual(canonical_label("નમઃ", words=True), "नमः")
        self.assertEqual(canonical_label("१२", words=True), "१२")
        self.assertEqual(mp.letters("श्रीकृष्ण"), ["श्री", "कृ", "ष्ण"])
        for text, reason in {"काि": "'ि' needs a letter before it (after 'का')", "ि": "needs a letter",
                             "क" * 13: "at most 12"}.items():
            with self.assertRaises(LabelError, msg=text) as e:
                canonical_label(text, words=True)
            self.assertIn(reason, str(e.exception))
        self.assertEqual(category("श्रीकृष्ण"), "words")
        long = safe_name("श्रीकृष्णाय")
        self.assertRegex(long, r"^shriikrissnnaaya__h[0-9a-f]{10}$")
        self.assertNotEqual(long, safe_name("श्रीकृष्णः"))

    def test_gujarati_character_without_devanagari(self):
        with self.assertRaises(LabelError):
            canonical_label("૱")                     # Gujarati rupee sign

    def test_describe_for_the_screen(self):
        d = describe("કિ")
        self.assertEqual((d["ok"], d["devanagari"], d["gujarati"]), (True, "कि", "કિ"))
        self.assertEqual(d["code_points_gujarati"], "U+0A95 U+0ABF")
        self.assertEqual(d["safe_name"], "ki__U0A95-U0ABF")
        self.assertEqual(describe("ॲ")["kept_in_devanagari"], ["ॲ"])
        self.assertFalse(describe("कम")["ok"])

    def test_code_points(self):
        self.assertEqual(code_points("कि"), "U+0915 U+093F")


class CategoryOrderNameTests(unittest.TestCase):
    def test_categories(self):
        expected = {"अ": "vowels", "आं": "vowels", "क": "consonants", "कि": "consonants", "कं": "consonants",
                    "क्": "consonants", "क्ष": "conjuncts", "श्री": "conjuncts", "र्म": "conjuncts",
                    "५": "digits", "।": "punctuation", "॥": "punctuation", "ॐ": "punctuation"}
        for label, cat in expected.items():
            self.assertEqual(category(label), cat, label)

    def test_alphabet_order(self):
        shuffled = ["॥", "५", "श्री", "ह", "कि", "क", "आ", "अ", "क्ष", "ख", "का", "औ", "ऋ"]
        expected = ["अ", "आ", "ऋ", "औ", "क", "का", "कि", "ख", "ह", "क्ष", "श्री", "५", "॥"]
        self.assertEqual(sorted(shuffled, key=sort_key), expected)

    def test_transliteration(self):
        for label, tr in (("कि", "ki"), ("क्ष", "kssa"), ("श्री", "shrii"), ("र्म", "rma"), ("क़", "kxa"),
                          ("कं", "kam"), ("।", "danda"), ("५", "5"), ("अ", "a")):
            self.assertEqual(transliterate(label), tr, label)

    def test_safe_names_are_unique_and_portable(self):
        labels = set()
        for cp in list(range(0x0905, 0x0915)) + list(range(0x0915, 0x093A)):
            c = chr(cp)
            if mp.is_label(c):
                labels.add(canonical_label(c))
                for matra in "ािीुूेैोौ":
                    if mp.is_label(c + matra):
                        labels.add(c + matra)
        labels |= {"क्ष", "त्र", "ज्ञ", "श्री", "र्म", "।", "॥", "५", "ॐ", "ऩ", "क़"}
        names = [safe_name(x) for x in labels]
        self.assertEqual(len(set(n.lower() for n in names)), len(names), "names collide (also case-insensitively)")
        for n in names:
            self.assertRegex(n, r"^[A-Za-z0-9_-]+$")
            self.assertLess(len(n), 100)
        self.assertEqual(safe_name("कि"), "ki__U0A95-U0ABF")


if __name__ == "__main__":
    unittest.main()

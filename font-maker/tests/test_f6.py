"""F6: Try it, akshara by akshara. Light on purpose: a made-up build report, no font file.
"""
import unittest

from font_maker.tryit import classify

REPORT = {"build": 3, "labels": ["क", "कि", "र", "म", "ु", "त", "्", "ग"], "filled": ["ं"], "missing": ["ळ"]}


class TryItTest(unittest.TestCase):
    def test_each_akshara_is_book_pieced_filled_missing_or_other(self):
        out = classify("कि क्त किं ळ ક", REPORT)
        kinds = [(a["text"], a["kind"]) for a in out["aksharas"] if a["kind"] != "space"]
        self.assertEqual(kinds, [("कि", "book"), ("क्त", "pieced"), ("किं", "filled"), ("ळ", "missing"), ("ક", "other")])
        self.assertEqual(out["counts"], {"book": 1, "pieced": 1, "generated": 0, "drawn": 0, "filled": 1, "missing": 1, "other": 1})
        self.assertEqual("".join(a["text"] for a in out["aksharas"]), "कि क्त किं ळ ક")   # spaces kept
        self.assertEqual([a["text"] for a in classify("abc क", REPORT)["aksharas"]], ["abc", " ", "क"])


if __name__ == "__main__":
    unittest.main()

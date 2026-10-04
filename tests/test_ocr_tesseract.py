"""C10: Tesseract's hOCR, image preparation, finding the program, and (if installed) reading a line."""
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from letter_extractor.ocr import tesseract as T                      # noqa: E402
from letter_extractor.ocr.aksharas import line_aksharas              # noqa: E402

DATA = Path(__file__).resolve().parent / "data" / "ocr"


def _hocr(name: str) -> str:
    return (DATA / name).read_text(encoding="utf-8")


def _installed():
    try:
        engine = T.find_tesseract()
    except T.TesseractError:
        return None
    return engine if "script/Devanagari" in engine.langs else None


class HocrTests(unittest.TestCase):
    def test_printed_line(self):
        r = T.reading_from_hocr(_hocr("printed_line.hocr"))
        self.assertTrue(r.text.startswith("स्वामियेपु"), r.text)
        self.assertIn("महाराज", r.text)
        chars = r.chars
        self.assertGreater(len(chars), 20)
        for c in chars:
            self.assertTrue(c.text)
            self.assertTrue(0 <= c.conf <= 100)
            self.assertTrue(c.alternatives, c.text)                    # lstm_choice_mode=2 gives choices
            confs = [a[1] for a in c.alternatives]
            self.assertEqual(confs, sorted(confs, reverse=True))
        # boxes are mapped back by the 10 px border: the first letter starts near the left edge
        self.assertLess(chars[0].box[0], 20)

    def test_aksharas_of_a_line(self):
        r = T.reading_from_hocr(_hocr("printed_line.hocr"))
        aks = line_aksharas(r.words)
        self.assertEqual([a.text for a in aks[:4]], ["स्वा", "मि", "ये", "पु"])
        xs = [a.box[0] for a in aks if a.box[2]]
        self.assertGreater(xs[-1], xs[0])

    def test_handwritten_line_parses(self):
        r = T.reading_from_hocr(_hocr("handwritten_line.hocr"))
        self.assertIn("॥१॥", r.text)
        self.assertGreater(len(r.words), 1)

    def test_scale_is_undone(self):
        words = T.parse_hocr(_hocr("printed_line.hocr"))
        x, y, w, h = words[0].chars[0].box
        r = T.reading_from_hocr(_hocr("printed_line.hocr"), scale=0.5, border=10)
        self.assertEqual(r.chars[0].box, (round((x - 10) / 0.5), round((y - 10) / 0.5), round(w / 0.5), round(h / 0.5)))

    def test_empty_output(self):
        self.assertEqual(T.parse_hocr("<html><body><div class='ocr_page'></div></body></html>"), [])


class PrepareTests(unittest.TestCase):
    def test_black_on_white_with_border(self):
        rgb = np.full((60, 200, 3), 230, np.uint8)
        rgb[20:40, 10:190] = (180, 40, 40)                                   # red ink
        img, scale = T.prepare_line(rgb, target_height=0, border=10)
        self.assertEqual(scale, 1.0)
        self.assertEqual(img.shape, (80, 220))
        self.assertEqual(img[0, 0], 255)
        self.assertEqual(img[30, 50], 0)

    def test_scaled_to_letter_height(self):
        ink = np.zeros((120, 400), bool)
        ink[30:31, 10:390] = True                                            # headline
        for x in range(20, 380, 40):
            ink[30:90, x:x + 9] = ink[30:90, x + 18:x + 27] = True            # 60 px tall letter bodies
            ink[60:64, x:x + 27] = True
        self.assertAlmostEqual(T.letter_height(ink), 60, delta=2)
        img, scale = T.prepare_line(np.zeros((120, 400, 3), np.uint8), target_height=40, ink=ink)
        self.assertAlmostEqual(scale, 40 / 60, delta=0.03)
        self.assertEqual(img.shape[0], round(120 * scale) + 20)


class FindTests(unittest.TestCase):
    def test_missing_program_is_explained(self):
        old = os.environ.get("PATH", "")
        places = T._USUAL_PLACES
        try:
            os.environ["PATH"] = ""
            T._USUAL_PLACES = []
            with self.assertRaises(T.TesseractError) as e:
                T.find_tesseract("/no/such/tesseract")
            self.assertIn("INSTALL_TESSERACT.md", str(e.exception))
        finally:
            os.environ["PATH"] = old
            T._USUAL_PLACES = places

    @unittest.skipIf(sys.platform == "win32", "uses a shell script as a fake program")
    def test_set_path_with_version_and_languages(self):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "tesseract"
            fake.write_text('#!/bin/sh\nif [ "$1" = "--version" ]; then echo "tesseract 5.3.0"; exit 0; fi\n'
                            'echo \'List of available languages in "/x/" (2):\'\necho hin\necho san\n')
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            engine = T.find_tesseract(str(fake))
            self.assertEqual((engine.path, engine.version, engine.langs), (str(fake), "5.3.0", ["hin", "san"]))
            engine.check_langs("hin+san")
            with self.assertRaises(T.TesseractError) as e:
                engine.check_langs("san+mar")
            self.assertIn("mar", str(e.exception))


@unittest.skipUnless(_installed(), "Tesseract with script/Devanagari is not installed")
class ReadLineTests(unittest.TestCase):
    def test_printed_line(self):
        engine = _installed()
        r = T.read_line(T.load_rgb(DATA / "printed_line.png"), engine)
        self.assertTrue(r.text.startswith("स्वामि"), r.text)
        self.assertIn("महाराज", r.text)
        aks = line_aksharas(r.words)
        self.assertEqual(aks[0].text, "स्वा")


if __name__ == "__main__":
    unittest.main()

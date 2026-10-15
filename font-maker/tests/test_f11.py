"""F11: missing letters made from the book's parts, drawn or uploaded. Light on purpose: blocks of a few
dozen pixels, one copy per group.
"""
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from fontTools.ttLib import TTFont
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from letter_extractor.app.db import LetterGroup, Sample
from font_maker import gen
from font_maker.glyphs import GlyphMaker
from font_maker.projects import Projects
from font_maker.store import Store
from font_maker.tryit import classify
from test_f0 import make_library


def block(w=26, h=26):
    a = np.zeros((h, w), np.uint8)
    a[8:24, 2:12] = 255
    return a


def masks():
    ka, kau, a_, dd = block(), block(), block(), np.zeros((26, 20), np.uint8)
    kau[8:24, 14:16] = 255                           # कौ: a bar right of क (as the ौ's stem)
    dd[8:24, 3:6] = 255                              # ॥: two strokes
    dd[8:24, 12:15] = 255
    return {"क": ka, "कौ": kau, "अ": a_, "॥": dd}


def make_groups(root: Path) -> None:
    folder = root / "books" / "0001-test-book" / "letters"
    folder.mkdir(parents=True)
    engine = create_engine(f"sqlite:///{root / 'library.db'}")
    with Session(engine) as s:
        for n, (label, ink) in enumerate(masks().items(), 1):
            g = LetterGroup(book_id=1, code=f"g{n:04d}", status="labelled", label_dev=label, label_guj="",
                            kind="danda" if label == "॥" else "letter")
            s.add(g)
            s.flush()
            cv2.imwrite(str(folder / f"{g.code}_mask.png"), ink)
            s.add(Sample(book_id=1, image=f"letters/{g.code}.png", mask=f"letters/{g.code}_mask.png", group_id=g.id))
        s.commit()
    engine.dispose()


def png_of(ink: np.ndarray) -> bytes:
    return cv2.imencode(".png", np.where(ink, 0, 255).astype(np.uint8))[1].tobytes()


class MissingLettersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = make_library(Path(self.tmp.name))
        make_groups(root)
        self.store = Store(root)
        self.projects = Projects(self.store.fonts_dir)
        self.font = self.projects.create("Test", [1])["id"]
        self.maker = GlyphMaker(self.store, self.projects)
        self.maker.refresh(self.font)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_letters_from_the_books_parts(self):
        state = self.maker.set_generated(self.font, ["।", "ौ", "औ", "ऊ"], True)
        self.assertEqual([f["char"] for f in state["not_generated"]], ["ऊ"])     # no rule for ऊ
        folder = self.store.fonts_dir / self.font / "glyphs" / "generated"
        danda = cv2.imread(str(folder / self.maker._gen_entry(self.font, "।")["image"]), cv2.IMREAD_GRAYSCALE)
        self.assertAlmostEqual(danda.shape[1] / 4, 3, delta=0.5)               # one of the two strokes
        au = self.maker._gen_entry(self.font, "औ")
        self.assertEqual(au["parts"], ["अ", "ौ"])
        self.assertGreater(au["size"][0] / 4, 12)                              # अ (10 px) and the ौ beside it

    def test_drawn_and_uploaded_letters(self):
        square = np.zeros((60, 30), bool)
        square[:, :] = True
        self.maker.set_drawn(self.font, "ळ", png_of(np.pad(square, 10)))       # uploaded: the font's height
        e = self.maker._drawn_entry(self.font, "ळ")
        self.assertEqual((e["source"], e["top"]), ("uploaded", -16.0))         # a consonant here is 16 px tall
        self.assertAlmostEqual(e["size"][1] / 4, 16, delta=0.5)
        pad = np.zeros((100, 100), bool)
        pad[40:80, 30:50] = True                                                # drawn on the pad: baseline row 80
        self.maker.set_drawn(self.font, "ऊ", png_of(pad), baseline=80, px_per_page_px=2)
        e = self.maker._drawn_entry(self.font, "ऊ")
        self.assertEqual((e["source"], e["top"]), ("drawn", -20.0))
        self.assertAlmostEqual(e["size"][1] / 4, 20, delta=0.5)

    def test_in_the_font_drawn_wins_over_generated(self):
        self.maker.set_generated(self.font, ["।"], True)
        bar = np.zeros((60, 12), bool)
        bar[:, 3:9] = True
        self.maker.set_drawn(self.font, "।", png_of(np.pad(bar, 6)))
        report = self.maker.build(self.font)
        self.assertEqual((report["drawn_chars"], report["generated_chars"]), (["।"], []))
        path = self.store.fonts_dir / self.font / "builds" / report["file"]
        self.assertGreaterEqual(TTFont(path)["glyf"]["uni0964"].numberOfContours, 1)
        self.assertEqual([a["kind"] for a in classify("।", report)["aksharas"]], ["drawn"])
        self.maker.remove_drawn(self.font, "।")
        self.assertEqual(self.maker.build(self.font)["generated_chars"], ["।"])


if __name__ == "__main__":
    unittest.main()

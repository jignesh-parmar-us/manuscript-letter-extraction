"""F9: signs cut from the book's aksharas. Light on purpose: blocks of a few dozen pixels, one copy per group.
"""
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
import uharfbuzz as hb
from fontTools.ttLib import TTFont
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from letter_extractor.app.db import LetterGroup, Sample
from font_maker import gen
from font_maker.glyphs import GlyphMaker
from font_maker.projects import Projects
from font_maker.store import Store
from test_f0 import make_library


def block(w=24, h=26):
    a = np.zeros((h, w), np.uint8)
    a[8:24, 2:12] = 255                              # the "consonant": a block, its top at row 8
    return a


def masks():
    ka = block()
    kaa = block()
    kaa[8:24, 14:16] = 255                           # + a bar 2 px to its right: ा
    kam = block()
    kam[3:6, 6:9] = 255                              # + a dot above: ं
    kha = block()
    kha[8:24, 2:16] = 255                            # a wider "consonant" with no ं of its own
    return {"क": ka, "का": kaa, "कं": kam, "ख": kha}


def make_groups(root: Path) -> None:
    folder = root / "books" / "0001-test-book" / "letters"
    folder.mkdir(parents=True)
    engine = create_engine(f"sqlite:///{root / 'library.db'}")
    with Session(engine) as s:
        for n, (label, ink) in enumerate(masks().items(), 1):
            g = LetterGroup(book_id=1, code=f"g{n:04d}", status="labelled", label_dev=label, label_guj="")
            s.add(g)
            s.flush()
            cv2.imwrite(str(folder / f"{g.code}_mask.png"), ink)
            s.add(Sample(book_id=1, image=f"letters/{g.code}.png", mask=f"letters/{g.code}_mask.png", group_id=g.id))
        s.commit()
    engine.dispose()


def shape(path: Path, text: str):
    font = hb.Font(hb.Face(hb.Blob.from_file_path(str(path))))
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf, {})
    return [(font.glyph_to_string(i.codepoint), p.x_advance) for i, p in zip(buf.glyph_infos, buf.glyph_positions)]


class SignTest(unittest.TestCase):
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

    def test_the_sign_is_the_akshara_without_the_consonant(self):
        glyphs = self.maker.state(self.font)["glyphs"]
        folder = self.store.fonts_dir / self.font / "glyphs"
        aa, img = gen.make_sign("ा", glyphs, folder)
        self.assertEqual((aa["kind"], aa["n"], aa["few"]), ("right", 1, True))
        self.assertAlmostEqual(aa["left"], 2.0, delta=0.5)                 # 2 px right of the consonant
        self.assertAlmostEqual(img.shape[1] / 4, 2.0, delta=0.5)           # the bar, 2 px wide
        am, img = gen.make_sign("ं", glyphs, folder)
        self.assertEqual(am["kind"], "above")
        self.assertLess(am["top"], -16)                                     # above the consonant's top
        self.assertIsNone(gen.make_sign("ु", glyphs, folder))              # no pair: not generated

    def test_generated_signs_in_the_font(self):
        state = self.maker.set_generated(self.font, ["ा", "ं", "ु"], True)
        self.assertEqual([f["char"] for f in state["not_generated"]], ["ु"])
        self.assertEqual(sorted(state["coverage"]["generated_chars"]), ["ं", "ा"])
        report = self.maker.build(self.font)
        path = self.store.fonts_dir / self.font / "builds" / report["file"]
        self.assertEqual([n for n, _ in shape(path, "खं")], ["uni0916", "uni0902"])
        self.assertEqual(shape(path, "खं")[1][1], 0)                       # a mark: no width
        kha_aa = shape(path, "खा")
        self.assertEqual(kha_aa[1][0], "uni093E")
        self.assertGreater(kha_aa[1][1], 0)                                 # ा has its own width
        self.assertEqual([n for n, _ in shape(path, "कं")], ["a1_g0003"])  # the book's own akshara wins
        self.assertEqual(TTFont(path)["GDEF"].table.GlyphClassDef.classDefs["uni0902"], 3)
        self.assertEqual(sorted(report["generated_chars"]), ["ं", "ा"])


if __name__ == "__main__":
    unittest.main()

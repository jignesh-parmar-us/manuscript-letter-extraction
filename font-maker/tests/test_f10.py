"""F10: half forms, reph and rakar cut from the book's conjuncts; HarfBuzz joins conjuncts without a glyph
of their own with them. Light on purpose: blocks of a few dozen pixels, one copy per group.
"""
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
import uharfbuzz as hb
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from letter_extractor.app.db import LetterGroup, Sample
from font_maker import gen
from font_maker.glyphs import GlyphMaker
from font_maker.projects import Projects
from font_maker.store import Store
from font_maker.tryit import classify
from test_f0 import make_library


def letter(w=30, h=26, x0=14):
    a = np.zeros((h, w), np.uint8)
    a[8:24, x0:x0 + 10] = 255                       # a "full letter": a block, its top at row 8
    return a


def masks():
    ta, kta = letter(), letter()
    kta[8:24, 2:8] = 255                             # क्त: a half form left of त
    ya, rya = letter(), letter()
    rya[3:6, 20:26] = 255                            # र्य: a reph above the end of य
    pa, pra = letter(h=28), letter(h=28)
    pra[24:26, 6:14] = 255                           # प्र: a rakar under प, reaching left of its stem
    kya, rta, yra = kta.copy(), rya.copy(), pra.copy()   # a second conjunct for each form (they need two)
    return {"त": ta, "क्त": kta, "य": ya, "र्य": rya, "प": pa, "प्र": pra, "क्य": kya, "र्त": rta, "य्र": yra}


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
    return [font.glyph_to_string(i.codepoint) for i in buf.glyph_infos]


class JoinedFormsTest(unittest.TestCase):
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

    def test_one_conjunct_or_a_special_one_is_not_enough(self):
        entry = {"char": "half:ह", "n": 1, "agree": 1.0, "pairs": [{"akshara": "ह्म"}]}
        self.assertIn("one conjunct only", gen.why_not(entry))
        glyphs = [{"label_dev": l, "left_out": False} for l in ("ष", "क्ष", "त", "क्त")]
        self.assertEqual([w["label_dev"] for _, w in gen.pairs_for("half:क", glyphs)], ["क्त"])   # not क्ष

    def test_forms_are_cut_from_the_conjuncts(self):
        glyphs = self.maker.state(self.font)["glyphs"]
        self.assertEqual(gen.available(glyphs), ["half:क", "reph", "rakar"])
        folder = self.store.fonts_dir / self.font / "glyphs"
        half, img = gen.make_sign("half:क", glyphs, folder)
        self.assertEqual(half["kind"], "half")
        self.assertAlmostEqual(img.shape[1] / 4, 6, delta=0.5)            # the 6 px block left of त
        reph, _ = gen.make_sign("reph", glyphs, folder)
        self.assertLess(reph["top"], -16)                                   # above य's top

    def test_conjuncts_without_a_glyph_join_with_the_forms(self):
        state = self.maker.set_generated(self.font, ["half:क", "reph", "rakar"], True)
        self.assertEqual(state["not_generated"], [])
        report = self.maker.build(self.font)
        path = self.store.fonts_dir / self.font / "builds" / report["file"]
        self.assertEqual(shape(path, "क्प"), ["half_0915", "uni092A"])
        self.assertEqual(shape(path, "र्प"), ["uni092A", "reph"])          # the reph moves to the end
        self.assertEqual(shape(path, "त्र"), ["uni0924", "rakar"])
        self.assertEqual(shape(path, "क्त"), ["a1_g0002"])                 # the book's own akshara wins
        self.assertEqual(shape(path, "र्य"), ["a1_g0004"])
        kinds = [a["kind"] for a in classify("क्प र्प त्र क्त", report)["aksharas"] if a["kind"] != "space"]
        self.assertEqual(kinds, ["generated", "generated", "generated", "book"])


if __name__ == "__main__":
    unittest.main()

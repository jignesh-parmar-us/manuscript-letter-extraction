"""F5: the built font, shaped with HarfBuzz (as in Chrome). Light on purpose: one copy per group, small squares.
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
from font_maker.build import rule_orders
from font_maker.glyphs import GlyphMaker
from font_maker.projects import Projects
from font_maker.store import Store
from test_f0 import make_library

LABELS = ["क", "का", "कि", "क्ति", "क्ष", "र्य", "१", "२"]


def make_font_groups(root: Path) -> None:
    folder = root / "books" / "0001-test-book" / "letters"
    folder.mkdir(parents=True)
    engine = create_engine(f"sqlite:///{root / 'library.db'}")
    with Session(engine) as s:
        for n, label in enumerate(LABELS, 1):
            g = LetterGroup(book_id=1, code=f"g{n:04d}", status="labelled", label_dev=label, label_guj="")
            s.add(g)
            s.flush()
            ink = np.zeros((20, 20), np.uint8)
            ink[2:18, 2:4 + n] = 255                         # a different width for each group
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


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_library(Path(self.tmp.name))
        make_font_groups(self.root)
        self.store = Store(self.root)
        self.projects = Projects(self.store.fonts_dir)
        self.font = self.projects.create("Test Font", [1])["id"]
        self.maker = GlyphMaker(self.store, self.projects)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def built(self) -> Path:
        report = self.maker.build(self.font)
        return self.store.fonts_dir / self.font / "builds" / report["file"]

    def test_rules_shape_like_a_browser_and_the_version_goes_up(self):
        self.assertEqual(rule_orders("क्ति"), [["क", "्", "ि", "त"], ["ि", "क", "्", "त"]])
        self.assertEqual(rule_orders("कि"), [["ि", "क"]])
        path = self.built()
        lig = {label: f"a1_g{n:04d}" for n, label in enumerate(LABELS, 1)}
        for text in ("का", "कि", "क्ति", "क्ष", "र्य"):
            self.assertEqual(shape(path, text), [lig[text]], text)
        self.assertEqual(shape(path, "क का"), ["uni0915", "space", lig["का"]])
        self.assertEqual(shape(path, "१२"), ["uni0967", "uni0968"])
        self.assertEqual(shape(path, "ક"), [".notdef"])                       # Gujarati is not in this font
        self.assertEqual(TTFont(path)["name"].getDebugName(5), "Version 1.001")
        self.assertEqual(TTFont(self.built())["name"].getDebugName(5), "Version 1.002")

    def test_missing_is_a_box_filled_comes_from_noto_with_its_mark(self):
        path = self.built()
        self.assertEqual(shape(path, "ग"), ["uni0917"])
        self.assertEqual(TTFont(path)["glyf"]["uni0917"].numberOfContours, 2)  # the box and its hole
        self.assertIn("ग", self.maker.build_state(self.font)["report"]["missing"])

        self.projects.set_filled(self.font, ["ग"], True)
        marked = TTFont(self.built())["glyf"]["uni0917"].numberOfContours
        self.projects.update(self.font, mark_filled=False)
        plain = TTFont(self.built())["glyf"]["uni0917"].numberOfContours
        self.assertEqual(marked, plain + 1)                                     # the line under it
        state = self.maker.build_state(self.font)
        self.assertEqual((state["report"]["filled"], "ग" in state["coverage"]["missing"]), (["ग"], False))
        self.projects.set_filled(self.font, ["ई"], True)                  # made of other letters in Noto
        self.assertFalse(TTFont(self.built())["glyf"]["uni0908"].isComposite())


if __name__ == "__main__":
    unittest.main()

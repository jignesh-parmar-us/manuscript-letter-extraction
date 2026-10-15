"""F4: tracing. Light on purpose: a made-up square and ring, and one outline through the glyph flow.
"""
import tempfile
import unittest
from pathlib import Path

import numpy as np
from fontTools.pens.areaPen import AreaPen

from font_maker.glyphs import GlyphMaker
from font_maker.projects import Projects
from font_maker.store import Store
from font_maker.trace import draw, reverse, trace
from test_f0 import make_library
from test_f2 import make_groups


def area(contours) -> float:
    """fontTools' signed area: counter-clockwise > 0, so a TrueType outer curve (clockwise) is < 0."""
    pen = AreaPen()
    draw(contours, pen, 10.0, 0, 0)                         # 10 units a page pixel: little rounding
    return pen.value / 100


def image(outer: int, inner: int = 0) -> np.ndarray:
    """A filled square of `outer` pixels (enlarged x4 like a glyph image), with a square hole of `inner`."""
    a = np.zeros((outer + 16, outer + 16), bool)
    a[8:8 + outer, 8:8 + outer] = True
    if inner:
        o = 8 + (outer - inner) // 2
        a[o:o + inner, o:o + inner] = False
    return a


class TraceTest(unittest.TestCase):
    def test_square_area_in_page_pixels(self):
        contours = trace(image(80), 4)                      # 80 px at x4 = a 20 x 20 page-pixel square
        self.assertEqual(len(contours), 1)
        self.assertAlmostEqual(area(contours), -400, delta=20)

    def test_ring_has_an_outer_curve_and_a_hole_running_the_other_way(self):
        contours = trace(image(80, 40), 4)
        self.assertEqual(len(contours), 2)
        self.assertEqual(sorted(area([c]) < 0 for c in contours), [False, True])    # one each way
        self.assertAlmostEqual(area(contours), -(400 - 100), delta=20)
        self.assertAlmostEqual(area([reverse(contours[0])]), -area([contours[0]]), delta=0.5)


class OutlineFlowTest(unittest.TestCase):
    def test_an_outline_is_traced_once_and_goes_with_its_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_library(Path(tmp))
            make_groups(root)
            store = Store(root)
            projects = Projects(store.fonts_dir)
            font = projects.create("Test", [1])["id"]
            maker = GlyphMaker(store, projects)
            maker.refresh(font)
            glyph = next(g for g in maker.state(font)["glyphs"] if g["label_dev"] == "ख")
            svg = maker.svg(font, glyph["group"])
            self.assertTrue(svg["d"].startswith("M") and svg["contours"] >= 1)
            maker.svg(font, glyph["group"])
            self.assertEqual(maker.traced, 1)                                      # the second time: from its file
            (outline,) = (store.fonts_dir / font / "glyphs").glob(glyph["image"] + "*.outline.json")
            maker.choose(font, glyph["group"], "copy", maker.copies(font, glyph["group"])[1]["id"])
            self.assertFalse(outline.exists())                                     # a new image: the old outline goes
            store.close()


if __name__ == "__main__":
    unittest.main()

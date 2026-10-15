"""F3: baselines (also on a tilted line), letter gap and word space, and where a glyph sits.

Light on purpose: made-up boxes, and one small library line for the whole flow.
"""
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session

from letter_extractor.app.db import Line, Page, Sample
from font_maker.glyphs import GlyphMaker, Group
from font_maker.metrics import Box, baselines, estimate, gaps, place
from font_maker.projects import Projects
from font_maker.store import Store
from test_f0 import make_library
from test_f2 import make_groups


class MetricsTest(unittest.TestCase):
    def test_tilted_baseline_ignores_letters_below_the_line(self):
        # bottoms fall 0.015 px per px to the right (a tilted scan); कु reaches 20 px below the line
        boxes = [Box(i, 1, x, int(300 - 0.015 * x) - 50, 40, 50, "क") for i, x in enumerate(range(0, 3000, 300))]
        boxes.append(Box(99, 1, 1500, 300 - 22 - 50 + 20, 40, 50, "कु"))
        base = baselines(boxes, {1: 120})[1]
        self.assertAlmostEqual(base.b, -0.015, places=3)
        self.assertAlmostEqual(base.at(1500), 300 - 22.5, delta=1)

    def test_letter_gap_and_word_space(self):
        xs = [0, 42, 85, 127, 200]                          # gaps 2, 3, 2 between letters, 33 for a space
        boxes = [Box(i, 1, x, 0, 40, 50, "क") for i, x in enumerate(xs)]
        self.assertEqual(gaps(boxes, 120), (2, 33))

    def test_place_is_the_median_over_copies(self):
        boxes = {1: Box(1, 7, 0, 100, 10, 10, "क"), 2: Box(2, 7, 20, 100, 10, 10, "क")}
        lines = baselines(boxes.values(), {7: 40})
        self.assertEqual(place({"1": [2, 6, 2, 6], "2": [3, 9, 1, 6]}, boxes, lines),
                         {"bottom": -2.5, "top": -7.5, "width": 4.5})

    def test_system_made_letters_only_when_nothing_else_and_their_place_is_estimated(self):
        g = Group(1, 1, Path("."), "g1", "letter", "labelled", "कु", "કુ",
                  copies=[(1, "", ""), (2, "", ""), (3, "", "")], generated={1, 3})
        self.assertEqual(g.best(8), ([(2, "", "")], False))
        g.generated = {1, 2, 3}
        self.assertEqual(g.best(2), ([(1, "", ""), (2, "", "")], True))
        glyphs = [{"label_dev": "पु", "bottom": 21.0}, {"label_dev": "मु", "bottom": 20.0},
                  {"label_dev": "खु", "bottom": None, "size": [200, 320]}, {"label_dev": "ख", "bottom": None, "size": [200, 240]}]
        estimate(glyphs, 4)
        self.assertEqual([(g["bottom"], g["placed"]) for g in glyphs[2:]], [(20.5, "estimated"), (0.0, "estimated")])
        self.assertEqual((glyphs[2]["top"], glyphs[2]["width"]), (-59.5, 50))


class FlowTest(unittest.TestCase):
    def test_glyphs_get_their_place_on_the_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_library(Path(tmp))
            make_groups(root)
            engine = create_engine(f"sqlite:///{root / 'library.db'}")
            with Session(engine) as s:                      # all copies on one line, y = 100, 10x10 boxes
                page = Page(book_id=1, file="p.png")
                s.add(page)
                s.flush()
                line = Line(page_id=page.id, number=1, x=0, y=90, w=200, h=40, ink="black", image="l.png")
                s.add(line)
                s.flush()
                for i, sid in enumerate(sorted(s.scalars(Sample.__table__.select().with_only_columns(Sample.id)))):
                    s.execute(update(Sample).where(Sample.id == sid)
                              .values(line_id=line.id, x=12 * i + (20 if i >= 4 else 0), y=100, w=10, h=10))
                s.commit()
            engine.dispose()
            store = Store(root)
            projects = Projects(store.fonts_dir)
            font = projects.create("Test", [1])["id"]
            maker = GlyphMaker(store, projects)
            maker.refresh(font)
            st = maker.state(font)
            self.assertEqual(st["metrics"], {"lines": 1, "line_height": 40.0, "letter_gap": 2, "word_space": 22})
            ka = next(g for g in st["glyphs"] if g["label_dev"] == "क")   # squares: ink rows 2-6 of a 10 px box
            self.assertEqual((ka["bottom"], ka["top"], ka["width"]), (-4, -8, 4))
            self.assertEqual(maker.refresh(font), 0)                    # measuring again remakes no image
            store.close()


if __name__ == "__main__":
    unittest.main()

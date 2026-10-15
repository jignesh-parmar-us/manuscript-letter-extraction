"""F2: glyph images. Light on purpose: two groups of three made-up 10x10 masks; work is counted, not timed.
"""
import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session

from letter_extractor.app.db import LetterGroup, Sample
from font_maker.api import create_app
from font_maker.glyphs import GlyphMaker, make_image
from font_maker.projects import Projects
from font_maker.store import Store
from test_f0 import make_library

H = {"X-Token": "t"}


def square(dy=0, dx=0) -> np.ndarray:
    a = np.zeros((10, 10), bool)
    a[2 + dy:6 + dy, 2 + dx:6 + dx] = True
    return a


def bar(horizontal: bool) -> np.ndarray:
    a = np.zeros((10, 10), bool)
    a[4:6, 1:9] = True
    return a if horizontal else a.T


def make_groups(root: Path) -> None:
    """क: three shifted squares (agree); ख: a square and two bars (disagree); खाखा: a cut error."""
    letters = root / "books" / "0001-test-book" / "letters"
    letters.mkdir(parents=True)
    engine = create_engine(f"sqlite:///{root / 'library.db'}")
    with Session(engine) as s:
        for code, label, inks in (("g1", "क", [square(), square(1, 0), square(0, 2)]),
                                  ("g2", "ख", [square(), bar(True), bar(False)]),
                                  ("g3", "खाखा", [square()])):
            g = LetterGroup(book_id=1, code=code, status="labelled", label_dev=label, label_guj=label)
            s.add(g)
            s.flush()
            for k, ink in enumerate(inks):
                name = f"letters/{code}_{k}"
                cv2.imwrite(str(root / "books" / "0001-test-book" / f"{name}_mask.png"), ink.astype(np.uint8) * 255)
                s.add(Sample(book_id=1, image=f"{name}.png", mask=f"{name}_mask.png", group_id=g.id, distance=k / 10))
        s.commit()
    engine.dispose()


class ImageTest(unittest.TestCase):
    def test_average_when_copies_agree_else_best_copy(self):
        img, method, agree = make_image([square(), square(1, 0), square(0, 2)], 0.6)
        self.assertEqual((method, agree), ("average", 1.0))
        self.assertEqual(img.shape, (16, 16))                       # 4x4 ink, enlarged x4
        _, method, agree = make_image([square(), bar(True), bar(False)], 0.6)
        self.assertEqual(method, "copy")
        self.assertLess(agree, 0.6)


class GlyphsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_library(Path(self.tmp.name))
        make_groups(self.root)
        self.store = Store(self.root)
        self.projects = Projects(self.store.fonts_dir)
        self.font = self.projects.create("Test", [1])["id"]

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_only_changed_glyphs_are_made_and_lost_picks_are_shown(self):
        db = self.root / "library.db"
        before = hashlib.sha256(db.read_bytes()).hexdigest()
        maker = GlyphMaker(self.store, self.projects)
        self.assertEqual(maker.refresh(self.font), 2)
        st = maker.state(self.font)
        self.assertEqual({g["label_dev"]: g["method"] for g in st["glyphs"]}, {"क": "average", "ख": "copy"})
        self.assertEqual([e["label_dev"] for e in st["cut_errors"]], ["खाखा"])
        self.assertEqual(GlyphMaker(self.store, self.projects).refresh(self.font), 0)   # read back from glyphs.json

        g2 = next(g for g in st["glyphs"] if g["label_dev"] == "ख")
        picked = maker.copies(self.font, g2["group"])[2]["id"]
        made = maker.made
        glyph = maker.choose(self.font, g2["group"], "copy", picked)["glyph"]
        self.assertEqual((maker.made - made, glyph["method"]), (1, "pick"))
        saved = json.loads((self.store.fonts_dir / self.font / "font.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["picks"][str(g2["group"])], {"group": g2["group"], "label": "ख", "sample": picked})
        self.assertEqual(maker.refresh(self.font), 0)
        self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), before)

        engine = create_engine(f"sqlite:///{db}")                  # the reading app deletes the picked copy
        with engine.begin() as c:
            c.execute(update(Sample).where(Sample.id == picked).values(deleted=True))
        engine.dispose()
        maker.refresh(self.font)
        st = maker.state(self.font)
        glyph = next(g for g in st["glyphs"] if g["group"] == g2["group"])
        self.assertEqual((glyph["lost"], glyph["method"]), (True, "copy"))
        self.assertEqual([(p["label"], p["sample"]) for p in st["lost"]], [("ख", picked)])
        maker.choose(self.font, g2["group"], "system")                # choosing again forgets the lost pick
        self.assertEqual(maker.state(self.font)["lost"], [])

    def test_api_check_choice_and_files(self):
        client = TestClient(create_app(self.store, "t", static_dir=self.root / "no-screen"))
        client.post(f"/api/fonts/{self.font}/glyphs/check", headers=H)
        for _ in range(100):                                           # the background job
            st = client.get(f"/api/fonts/{self.font}/glyphs", headers=H).json()
            if not st["job"]["running"]:
                break
            time.sleep(0.05)
        self.assertEqual((len(st["glyphs"]), st["job"]["error"]), (2, None))
        g = st["glyphs"][0]
        self.assertEqual(client.get(f"/files/fonts/{self.font}/glyphs/{g['image']}", headers=H).status_code, 200)
        self.assertEqual(client.get(f"/files/fonts/{self.font}/glyphs/..%2Ffont.json", headers=H).status_code, 404)
        out = client.put(f"/api/fonts/{self.font}/glyphs/{g['group']}/choice", json={"choice": "left_out"},
                         headers=H).json()
        self.assertTrue(out["glyph"]["left_out"])


if __name__ == "__main__":
    unittest.main()

"""C4: fingerprints and grouping of letter samples."""
import csv
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import synthetic                                                    # noqa: E402
from letter_extractor import io_utils                               # noqa: E402
from letter_extractor.config import Config                          # noqa: E402
from letter_extractor.features import fingerprint, fingerprint_size  # noqa: E402
from letter_extractor.grouping import UNSURE, group_samples         # noqa: E402
from letter_extractor.pipeline import process_folder, process_page  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
SHAPES = "ABCZEHKX"     # clearly different shapes; look-alikes such as B / D may share a group


def glyph(ch: str, rng) -> np.ndarray:
    """Ink mask of one hand-drawn-like glyph: random size, stroke width, shift and slant."""
    img = np.zeros((90, 90), np.uint8)
    scale = rng.uniform(1.6, 1.9)
    cv2.putText(img, ch, (int(15 + rng.integers(-4, 5)), int(70 + rng.integers(-4, 5))),
                cv2.FONT_HERSHEY_SIMPLEX, scale, 255, int(rng.integers(5, 8)))
    shear = np.float32([[1, rng.uniform(-0.08, 0.08), 0], [0, 1, 0]])
    img = cv2.warpAffine(img, shear, (90, 90))
    return img > 127


class FingerprintTests(unittest.TestCase):
    def test_unit_length_and_size(self):
        cfg = Config()
        rng = np.random.default_rng(0)
        v = fingerprint(glyph("A", rng), 110.0, cfg)
        self.assertEqual(v.shape, (fingerprint_size(cfg),))
        self.assertAlmostEqual(float(np.linalg.norm(v)), 1.0, places=4)

    def test_same_shape_is_closer_than_other_shape(self):
        cfg = Config()
        rng = np.random.default_rng(1)
        a1, a2 = (fingerprint(glyph("A", rng), 110.0, cfg) for _ in range(2))
        b = fingerprint(glyph("B", rng), 110.0, cfg)
        self.assertLess(np.linalg.norm(a1 - a2), np.linalg.norm(a1 - b))

    def test_ink_colour_and_position_do_not_matter(self):
        cfg = Config()
        m = glyph("K", np.random.default_rng(2))
        moved = np.zeros((140, 140), bool)
        moved[30:120, 25:115] = m
        self.assertLess(np.linalg.norm(fingerprint(m, 110.0, cfg) - fingerprint(moved, 110.0, cfg)), 1e-5)


class GroupingTests(unittest.TestCase):
    def test_known_shapes_form_pure_groups(self):
        cfg = Config()
        rng = np.random.default_rng(3)
        labels = [c for c in SHAPES for _ in range(12)]
        rng.shuffle(labels)
        X = np.stack([fingerprint(glyph(c, rng), 110.0, cfg) for c in labels])
        g = group_samples(X, ["letter"] * len(labels), cfg)
        for gid, members in g.groups.items():
            self.assertEqual(len({labels[m] for m in members}), 1, f"{gid} mixes {[labels[m] for m in members]}")
        self.assertEqual(len(g.groups), len(SHAPES), {k: len(v) for k, v in g.groups.items()})
        self.assertLessEqual(len(g.unsure), 4)
        self.assertEqual(list(g.groups), [f"g{i:04d}" for i in range(1, len(g.groups) + 1)])
        sizes = [len(m) for m in g.groups.values()]
        self.assertEqual(sizes, sorted(sizes, reverse=True))

    def test_kinds_never_share_a_group(self):
        cfg = Config()
        rng = np.random.default_rng(4)
        X = np.stack([fingerprint(glyph("H", rng), 110.0, cfg) for _ in range(10)])
        kinds = ["letter"] * 5 + ["danda"] * 5
        g = group_samples(X, kinds, cfg)
        for members in g.groups.values():
            self.assertEqual(len({kinds[m] for m in members}), 1)

    def test_singletons_are_unsure(self):
        cfg = Config()
        rng = np.random.default_rng(5)
        X = np.stack([fingerprint(glyph(c, rng), 110.0, cfg) for c in "AAAAB"])
        g = group_samples(X, ["letter"] * 5, cfg)
        self.assertEqual(g.unsure, [4])
        self.assertEqual(g.group_id[4], UNSURE)
        self.assertTrue(np.isnan(g.distance[4]))


class OutputTests(unittest.TestCase):
    def test_group_folders_html_and_samples_columns(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "in").mkdir()
            rgb, _ = synthetic.make_letters_page()
            Image.fromarray(rgb).save(tmp / "in" / "p1.png")
            summary = {}
            process_folder(tmp / "in", tmp / "out", Config(workers=1), summary=summary)
            out = tmp / "out"
            with open(out / "samples.csv", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(summary["samples"], len(rows))
            grouped = [r for r in rows if r["group_id"] != UNSURE]
            self.assertEqual(len(grouped) + summary["unsure"], len(rows))
            self.assertGreater(summary["groups"], 0)
            for r in rows:
                name = f"p1_{Path(r['image']).name}"
                folder = out / "unsure" if r["group_id"] == UNSURE else out / "groups" / r["group_id"]
                self.assertTrue((folder / name).is_file(), (folder, name))
                self.assertEqual(r["distance"] == "", r["group_id"] == UNSURE)
            self.assertEqual(len(list((out / "groups").iterdir())), summary["groups"])
            html = (out / "groups.html").read_text(encoding="utf-8")
            self.assertIn("g0001", html)
            self.assertIn('src="letters/p1/', html)
            # a second run replaces the groups of the first
            (out / "groups" / "g0999").mkdir()
            process_folder(tmp / "in", out, Config(workers=1))
            self.assertFalse((out / "groups" / "g0999").exists())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless((SAMPLES / "page1.jpg").is_file(), "sample pages not present")
class SamplePagesGroupingTests(unittest.TestCase):
    """Baseline measured when C4 was tuned (docs/TUNING.md): about 54 groups and 28% unsure."""

    def test_both_pages(self):
        cfg = Config()
        feats, kinds = [], []
        for name in ("page1.jpg", "page2.jpg"):
            rgb, _ = io_utils.load_image(SAMPLES / name)
            d = process_page(rgb, cfg)
            feats += [fingerprint(L.mask, d.layout.spacing, cfg) for L in d.letters]
            kinds += [L.kind for L in d.letters]
        g = group_samples(np.stack(feats), kinds, cfg)
        self.assertTrue(40 <= len(g.groups) <= 70, len(g.groups))
        self.assertLess(len(g.unsure) / len(kinds), 0.35)
        largest = max(len(m) for m in g.groups.values())
        self.assertLess(largest, 0.15 * len(kinds), "one group swallowed many letters")


if __name__ == "__main__":
    unittest.main()

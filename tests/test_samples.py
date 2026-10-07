"""C5f: new samples from a box, join, split, upload; with undo / redo."""
import base64
import io
import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import appbook                                                      # noqa: E402
from fastapi.testclient import TestClient                           # noqa: E402
from letter_extractor.app import actions as A                      # noqa: E402
from letter_extractor.app import samples as S                      # noqa: E402
from letter_extractor.app.api import create_app                    # noqa: E402
from letter_extractor.app.centres import suggestions               # noqa: E402
from letter_extractor.app.db import Page, Sample                    # noqa: E402
from sqlalchemy import select                                       # noqa: E402

# letters of the synthetic page (tests/synthetic.make_letters_page): line 1 headline at y = 80,
# letter 1 spans x 80-125 and y 75-132, letter 2 starts at x 134
LETTER1_BOX = (72, 60, 60, 85)


class SampleTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp, self.lib, self.book, self.pages = appbook.fresh_copy()
        with self.lib.session() as s:
            self.page = s.scalar(select(Page.id).where(Page.book_id == self.book, Page.file == "p1.png"))
            line1 = s.scalars(select(Sample).where(Sample.page_id == self.page, Sample.line_number == 1)
                              .order_by(Sample.x)).all()
            self.l1 = [x.id for x in line1]

    def tearDown(self):
        appbook.cleanup(self.tmp, self.lib)

    def mask_sum(self, sid):
        with self.lib.session() as s:
            smp = s.get(Sample, sid)
            folder = self.lib.book_dir(self.lib.get_book(self.book))
            with Image.open(folder / smp.mask) as im:
                return int((np.asarray(im) > 127).sum()), (smp.x, smp.y, smp.w, smp.h), smp

    def assert_undo_redo(self, before, after):
        A.undo(self.lib, self.book)
        self.assertEqual(appbook.state(self.lib, self.book)[1], before[1])
        self.assertEqual([x for x in appbook.state(self.lib, self.book)[0] if not x[2]],
                         [x for x in before[0] if not x[2]], "undo shows exactly the samples shown before")
        A.redo(self.lib, self.book)
        self.assertEqual(appbook.state(self.lib, self.book), after)


class CropTests(SampleTestCase):
    def test_box_around_a_letter_gives_its_ink(self):
        before = appbook.state(self.lib, self.book)
        r = S.crop_sample(self.lib, self.book, self.page, LETTER1_BOX)
        after = appbook.state(self.lib, self.book)
        new, box, smp = self.mask_sum(r["sample"]["id"])
        old, old_box, _ = self.mask_sum(self.l1[0])
        self.assertEqual(box, old_box)
        self.assertLess(abs(new - old), 0.03 * old)
        self.assertEqual((smp.source, smp.group_id, smp.line_number), ("cropped", None, 1))
        self.assertIn(self.l1[0], r["overlapping"])
        self.assertTrue((self.lib.book_dir(self.lib.get_book(self.book)) / smp.image).is_file())
        self.assert_undo_redo(before, after)

    def test_cropped_sample_is_suggested_its_letter_group(self):
        r = S.crop_sample(self.lib, self.book, self.page, LETTER1_BOX)
        with self.lib.session() as s:
            group_of_letter1 = s.get(Sample, self.l1[0]).group_id
            sug = suggestions(s, self.book, [s.get(Sample, r["sample"]["id"])], 0.55)
        self.assertEqual(sug[r["sample"]["id"]]["group_id"], group_of_letter1)

    def test_ink_cache(self):
        S.crop_sample(self.lib, self.book, self.page, LETTER1_BOX)
        cache = self.lib.book_dir(self.lib.get_book(self.book)) / "cache" / "p1_ink.npz"
        self.assertTrue(cache.is_file())
        S.crop_sample(self.lib, self.book, self.page, LETTER1_BOX)   # from the cache: same result
        with self.lib.session() as s:
            cropped = s.scalars(select(Sample).where(Sample.source == "cropped")).all()
            self.assertEqual(len(cropped), 2)
            self.assertEqual(len({(x.x, x.y, x.w, x.h) for x in cropped}), 1, "the cached ink gives the same sample")

    def test_refused_boxes(self):
        for box in ((1500, 5, 40, 30), (80, 80, 2, 2)):
            with self.assertRaises(A.ActionError):
                S.crop_sample(self.lib, self.book, self.page, box)


class JoinSplitTests(SampleTestCase):
    def test_join_two_letters(self):
        before = appbook.state(self.lib, self.book)
        a, _, _ = self.mask_sum(self.l1[0])
        b, _, _ = self.mask_sum(self.l1[1])
        r = S.join_samples(self.lib, self.book, self.l1[:2])
        after = appbook.state(self.lib, self.book)
        joined, box, smp = self.mask_sum(r["sample"]["id"])
        self.assertEqual(joined, a + b)
        self.assertEqual(smp.source, "joined")
        with self.lib.session() as s:
            self.assertTrue(all(s.get(Sample, i).deleted for i in self.l1[:2]))
        self.assert_undo_redo(before, after)

    def test_split_a_letter(self):
        before = appbook.state(self.lib, self.book)
        whole, (x, y, w, h), _ = self.mask_sum(self.l1[0])
        r = S.split_sample(self.lib, self.book, self.l1[0], x + w // 2)
        after = appbook.state(self.lib, self.book)
        parts = [self.mask_sum(p["id"]) for p in r["samples"]]
        self.assertEqual(sum(p[0] for p in parts), whole)
        self.assertLessEqual(parts[0][1][0] + parts[0][1][2], x + w // 2)
        self.assertGreaterEqual(parts[1][1][0], x + w // 2)
        self.assert_undo_redo(before, after)

    def test_refused(self):
        with self.lib.session() as s:
            other_page = s.scalar(select(Sample.id).join(Page).where(Page.file == "p2.png"))
        with self.assertRaises(A.ActionError):
            S.join_samples(self.lib, self.book, [self.l1[0], other_page])
        with self.assertRaises(A.ActionError):
            S.join_samples(self.lib, self.book, [self.l1[0]])
        _, (x, y, w, h), _ = self.mask_sum(self.l1[0])
        for cut in (x, x + w, x - 10):
            with self.assertRaises(A.ActionError):
                S.split_sample(self.lib, self.book, self.l1[0], cut)


def _png(rgb) -> str:
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


class UploadTests(SampleTestCase):
    def test_upload_a_letter_image(self):
        img = np.full((80, 70, 3), (205, 170, 150), np.uint8)
        img[20:60, 15:22] = (35, 30, 35)
        img[20:26, 10:55] = (35, 30, 35)
        r = S.upload_sample(self.lib, self.book, "my letter.png", _png(img))
        _, box, smp = self.mask_sum(r["sample"]["id"])
        self.assertEqual((smp.page_id, smp.source, smp.group_id), (None, "uploaded", None))
        self.assertEqual(box[2:], (45, 40))
        self.assertIsNotNone(smp.fingerprint)
        self.assertIn("my letter.png", smp.rules)
        A.undo(self.lib, self.book)
        with self.lib.session() as s:
            self.assertTrue(s.get(Sample, smp.id).deleted)

    def test_refused_uploads(self):
        with self.assertRaises(A.ActionError):
            S.upload_sample(self.lib, self.book, "x.png", base64.b64encode(b"not an image").decode())
        with self.assertRaises(A.ActionError):
            S.upload_sample(self.lib, self.book, "blank.png", _png(np.full((40, 40, 3), 230, np.uint8)))


class LineContextTests(SampleTestCase):
    def test_a_sample_with_its_neighbours(self):
        mid = self.l1[len(self.l1) // 2]
        with Image.open(io.BytesIO(S.line_context(self.lib, mid, around=1, height=1000))) as im:
            rgb = np.asarray(im.convert("RGB"))
        with self.lib.session() as s:
            near = [s.get(Sample, i) for i in self.l1]
            k = self.l1.index(mid)
            three = near[k - 1:k + 2]
            width = max(m.x + m.w for m in three) - min(m.x for m in three)
        self.assertGreaterEqual(rgb.shape[1], width)                       # the letter and one on each side
        self.assertLess(rgb.shape[1], width + 3 * near[k].h)               # but not the whole line
        self.assertTrue((np.abs(rgb.astype(int) - S.CONTEXT_COLOUR).sum(axis=2) < 10).any())   # outlined
        with Image.open(io.BytesIO(S.line_context(self.lib, mid))) as im:
            self.assertLessEqual(im.height, 96)                            # scaled down, never up

    def test_uploaded_samples_have_none(self):
        img = np.full((50, 50, 3), 220, np.uint8)
        img[10:40, 20:28] = 20
        sid = S.upload_sample(self.lib, self.book, "a.png", _png(img))["sample"]["id"]
        with self.assertRaises(S.NotFound):
            S.line_context(self.lib, sid)
        c = TestClient(create_app(self.lib, "t"))
        self.assertEqual(c.get(f"/files/samples/{sid}/context?token=t").status_code, 404)
        r = c.get(f"/files/samples/{self.l1[0]}/context?token=t")
        self.assertEqual((r.status_code, r.headers["content-type"]), (200, "image/png"))
        c.close()


class ApiTests(SampleTestCase):
    def test_routes(self):
        c = TestClient(create_app(self.lib, "t"))
        h = {"X-Token": "t"}
        r = c.post(f"/api/books/{self.book}/samples/crop", headers=h, json={"page_id": self.page, "box": list(LETTER1_BOX)})
        self.assertEqual(r.status_code, 200)
        self.assertIn(self.l1[0], r.json()["overlapping"])
        self.assertEqual(r.json()["undo"], 1)
        r = c.post(f"/api/books/{self.book}/samples/join", headers=h, json={"sample_ids": self.l1[1:3]})
        self.assertEqual(r.json()["sample"]["source"], "joined")
        r = c.post(f"/api/books/{self.book}/samples/split", headers=h, json={"sample_id": self.l1[3], "x": 0})
        self.assertEqual(r.status_code, 400)
        r = c.post(f"/api/books/{self.book}/samples/crop", headers=h, json={"page_id": 9999, "box": [0, 0, 9, 9]})
        self.assertEqual(r.status_code, 404)
        img = np.full((50, 50, 3), 220, np.uint8)
        img[10:40, 20:28] = 20
        r = c.post(f"/api/books/{self.book}/samples/upload", headers=h, json={"filename": "a.png", "data": _png(img)})
        self.assertEqual(r.json()["sample"]["page_id"], None)
        c.close()


if __name__ == "__main__":
    unittest.main()

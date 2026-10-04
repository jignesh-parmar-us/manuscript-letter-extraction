"""C5g: export of a book (FR-9, FR-10)."""
import base64
import csv
import io
import sys
import time
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
from letter_extractor.app.db import LetterGroup, Page, Sample       # noqa: E402
from letter_extractor.app.export import export_book                 # noqa: E402
from letter_extractor.app.library import LibraryError               # noqa: E402
from letter_extractor.app.main import AppContext                    # noqa: E402
from sqlalchemy import select                                       # noqa: E402


def _rows(path: Path):
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "CSV must be utf-8-sig (Excel)"
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.lib, self.book, self.pages = appbook.fresh_copy()
        groups = appbook.groups_with_members(self.lib, self.book)
        self.big, self.second = sorted(groups, key=lambda g: -len(groups[g]))[:2]
        A.set_label(self.lib, self.book, self.big, "ક")                 # typed in Gujarati
        A.set_label(self.lib, self.book, self.second, "श्री")
        self.deleted = groups[self.big][0]
        A.delete_samples(self.lib, self.book, [self.deleted])
        img = np.full((60, 60, 3), 215, np.uint8)
        img[10:50, 25:32] = 25
        buf = io.BytesIO()
        Image.fromarray(img).save(buf, "PNG")
        self.uploaded = S.upload_sample(self.lib, self.book, "u.png", base64.b64encode(buf.getvalue()).decode())
        with self.lib.session() as s:
            self.n_big = len(appbook.groups_with_members(self.lib, self.book)[self.big])
            self.n_second = len(appbook.groups_with_members(self.lib, self.book)[self.second])
            self.alive = s.query(Sample).filter(Sample.book_id == self.book, Sample.deleted.is_(False)).count()

    def tearDown(self):
        appbook.cleanup(self.tmp, self.lib)

    def test_dataset_csvs_overview_summary(self):
        out = self.tmp / "export"
        r = export_book(self.lib, self.book, out)
        # dataset: one folder per class, every sample, label.txt in Gujarati
        ka = out / "dataset" / "consonants" / "ka__U0A95"
        shri = out / "dataset" / "conjuncts" / "shrii__U0AB6-U0ACD-U0AB0-U0AC0"
        self.assertEqual((ka / "label.txt").read_text(encoding="utf-8"), "ક\n")
        self.assertEqual((shri / "label.txt").read_text(encoding="utf-8"), "શ્રી\n")
        self.assertEqual(len(list(ka.glob("*.png"))), self.n_big)
        self.assertEqual(len(list(shri.glob("*.png"))), self.n_second)
        # letters.csv in alphabet order (consonants before conjuncts)
        letters = _rows(out / "letters.csv")
        self.assertEqual([x["gujarati"] for x in letters], ["ક", "શ્રી"])
        self.assertEqual(letters[0]["code_points"], "U+0A95")
        self.assertEqual(int(letters[0]["samples"]), self.n_big)
        self.assertTrue((out / letters[0]["example_image"]).is_file())
        # samples.csv: every sample that is not deleted, traceable, uploaded marked
        samples = _rows(out / "samples.csv")
        self.assertEqual(len(samples), self.alive)
        self.assertNotIn(self.deleted, [int(Path(x["image"]).stem.split("_")[-1]) for x in samples])
        up = [x for x in samples if x["source"] == "uploaded"]
        self.assertEqual(len(up), 1)
        self.assertEqual(up[0]["page"], "")
        self.assertTrue(all((out / x["image"]).is_file() for x in samples))
        # unsure: everything without a label
        self.assertEqual(len(list((out / "unsure").glob("*.png"))), r["unsure"])
        self.assertEqual(r["unsure"] + self.n_big + self.n_second, self.alive)
        # lines: Gujarati text in reading order, [?] for unlabelled letters
        texts = sorted((out / "lines").glob("*.txt"))
        self.assertEqual(len(texts), 6)
        self.assertEqual(len(list((out / "lines").glob("*.png"))), 6)
        joined = "".join(t.read_text(encoding="utf-8") for t in texts)
        self.assertIn("ક", joined)
        self.assertIn("[?]", joined)
        # overview: classes in alphabet order, few-sample classes outlined
        html = (out / "overview.html").read_text(encoding="utf-8")
        self.assertLess(html.index(">ક<"), html.index(">શ્રી<"))
        self.assertIn("class='cls few'", html)
        summary = (out / "summary.txt").read_text(encoding="utf-8")
        self.assertIn("Classes (labelled letters): 2", summary)
        self.assertIn(f"Unsure (no label): {r['unsure']}", summary)
        self.assertIn("Uploaded samples: 1", summary)
        self.assertEqual((r["classes"], r["uploaded"], r["image"]), (2, 1, "original"))

    def test_groups_with_the_same_label_are_one_class(self):
        groups = appbook.groups_with_members(self.lib, self.book)
        third = sorted(groups, key=lambda g: -len(groups[g]))[2]
        A.set_label(self.lib, self.book, third, "क")
        r = export_book(self.lib, self.book, self.tmp / "e")
        self.assertEqual(r["classes"], 2)
        self.assertEqual(len(list((self.tmp / "e" / "dataset" / "consonants" / "ka__U0A95").glob("*.png"))),
                         self.n_big + len(groups[third]))

    def test_image_modes(self):
        export_book(self.lib, self.book, self.tmp / "f", image="fixed64")
        img = next((self.tmp / "f" / "dataset" / "consonants" / "ka__U0A95").glob("*.png"))
        with Image.open(img) as im:
            a = np.asarray(im)
        self.assertEqual(a.shape, (64, 64))
        self.assertEqual((a.min(), a.max()), (0, 255), "black ink on white")
        export_book(self.lib, self.book, self.tmp / "n", image="normalized")
        with Image.open(next((self.tmp / "n" / "dataset" / "consonants" / "ka__U0A95").glob("*.png"))) as im:
            self.assertEqual(im.mode, "L")
        with self.assertRaises(LibraryError):
            export_book(self.lib, self.book, self.tmp / "x", image="sepia")

    def test_never_into_a_folder_with_files(self):
        busy = self.tmp / "busy"
        busy.mkdir()
        (busy / "keep.txt").write_text("mine")
        with self.assertRaises(LibraryError):
            export_book(self.lib, self.book, busy)
        self.assertEqual([p.name for p in busy.iterdir()], ["keep.txt"])

    def test_default_folder_and_digits_setting(self):
        cfg = self.lib.book_config(self.lib.get_book(self.book))
        cfg.digits = "western"
        self.lib.set_book_config(self.book, cfg)
        groups = appbook.groups_with_members(self.lib, self.book)
        third = sorted(groups, key=lambda g: -len(groups[g]))[2]
        A.set_label(self.lib, self.book, third, "૫")                     # a digit, typed in Gujarati
        r = export_book(self.lib, self.book)
        out = Path(r["folder"])
        self.assertEqual(out.parent, self.lib.book_dir(self.lib.get_book(self.book)) / "exports")
        digit = next((out / "dataset" / "digits").iterdir())
        self.assertEqual((digit / "label.txt").read_text(encoding="utf-8"), "5\n", "Western digits by setting")


class ExportApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.lib, self.book, self.pages = appbook.fresh_copy()
        self.opened = []
        ctx = AppContext(open_folder=self.opened.append)
        self.c = TestClient(create_app(self.lib, "t", context=ctx))
        self.h = {"X-Token": "t"}

    def tearDown(self):
        self.c.close()
        appbook.cleanup(self.tmp, self.lib)

    def test_export_job_and_open_folder(self):
        job = self.c.post(f"/api/books/{self.book}/export", headers=self.h, json={"image": "fixed64"}).json()
        t0 = time.time()
        while job["status"] == "running":
            self.assertLess(time.time() - t0, 120)
            time.sleep(0.2)
            job = self.c.get(f"/api/jobs/{job['id']}", headers=self.h).json()
        self.assertEqual(job["status"], "done", job["error"])
        folder = job["result"]["folder"]
        self.assertTrue((Path(folder) / "overview.html").is_file())
        self.assertEqual(self.c.post("/api/app/open-folder", headers=self.h, json={"path": folder}).status_code, 200)
        self.assertEqual(self.opened, [Path(folder)])
        self.assertEqual(self.c.post("/api/app/open-folder", headers=self.h, json={"path": "/no/such"}).status_code, 404)

    def test_refused_requests(self):
        bad = self.c.post(f"/api/books/{self.book}/export", headers=self.h, json={"image": "sepia"})
        self.assertEqual(bad.status_code, 400)
        busy = self.tmp / "busy"
        busy.mkdir()
        (busy / "f").write_text("x")
        r = self.c.post(f"/api/books/{self.book}/export", headers=self.h, json={"folder": str(busy)})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()

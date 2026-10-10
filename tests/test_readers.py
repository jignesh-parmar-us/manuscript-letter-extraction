"""C14: the letter reader: features, the network, training on a book, reading with it, "Check these"."""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import appbook                                                      # noqa: E402
from fastapi.testclient import TestClient                           # noqa: E402
from letter_extractor.app.api import create_app                    # noqa: E402
from letter_extractor.app.db import Book, LetterGroup, OcrReading, OcrRun, Reader, Sample   # noqa: E402
from letter_extractor.app.library import LibraryError              # noqa: E402
from letter_extractor.app.readers import check_list, delete_reader, read_with_reader, train_reader   # noqa: E402
from letter_extractor.app.suggest import engines                   # noqa: E402
from letter_extractor.ocr.features import dimension, features, varied   # noqa: E402
from letter_extractor.ocr.reader import LetterReader                # noqa: E402
from sqlalchemy import func, select                                 # noqa: E402


class NetworkTests(unittest.TestCase):
    def test_features_keep_size_and_vary_a_little(self):
        bar = np.zeros((40, 8), bool)
        bar[:, 2:6] = True
        dot = np.zeros((8, 8), bool)
        dot[2:6, 2:6] = True
        self.assertEqual(len(features(bar, 100)), dimension())
        self.assertGreater(np.abs(features(bar, 100) - features(dot, 100)).sum(), 1.0)   # a dot is not a bar
        rng = np.random.default_rng(1)
        v = varied(bar, rng)
        self.assertGreater(v.sum(), 10)

    def test_it_learns_three_easy_shapes_and_saves(self):
        rng = np.random.default_rng(0)
        def shape(k):
            m = np.zeros((30, 30), bool)
            if k == 0:
                m[:, 12:18] = True                                      # a bar
            elif k == 1:
                m[12:18, :] = True                                      # a dash
            else:
                m[5:25, 5:25] = True                                    # a block
                m[10:20, 10:20] = False
            return m
        X = np.stack([features(varied(shape(k), rng), 60) for k in (0, 1, 2) for _ in range(30)])
        y = np.repeat([0, 1, 2], 30)
        for hidden in (0, 32):
            r = LetterReader(["a", "b", "c"], X.shape[1], hidden=hidden)
            r.train(X, y, epochs=15)
            self.assertEqual((r.probabilities(X).argmax(axis=1) == y).mean(), 1.0)
        with tempfile.TemporaryDirectory() as d:
            r.save(Path(d) / "r.npz")
            back = LetterReader.load(Path(d) / "r.npz")
            np.testing.assert_allclose(back.probabilities(X), r.probabilities(X), rtol=1e-5)


class BookTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.lib, self.book, _ = appbook.fresh_copy()
        with self.lib.session() as s:
            rows = s.execute(select(LetterGroup.id, func.count(Sample.id)).join(Sample, Sample.group_id == LetterGroup.id)
                             .where(LetterGroup.book_id == self.book, Sample.deleted.is_(False))
                             .group_by(LetterGroup.id).order_by(func.count(Sample.id).desc())).all()
            self.groups = [gid for gid, _ in rows[:3]]
            for gid, label in zip(self.groups, ("क", "ख", "ग")):
                g = s.get(LetterGroup, gid)
                g.label_dev, g.label_guj, g.status = label, "", "labelled"
            # one letter of क's group put into ख's: "Check these" should find it
            self.planted = s.scalars(select(Sample.id).where(Sample.group_id == self.groups[0]).order_by(Sample.id)).first()
            s.get(Sample, self.planted).group_id = self.groups[1]

    def tearDown(self):
        appbook.cleanup(self.tmp, self.lib)

    def test_train_read_check_delete(self):
        steps = []
        r = train_reader(self.lib, [self.book], min_samples=2, progress=lambda n, t, x: steps.append(x.file))
        self.assertEqual(steps[-1], "done")
        self.assertEqual(r["labels"], 3)
        with self.lib.session() as s:
            rec = s.get(Reader, r["reader"])
            self.assertEqual(s.get(Book, self.book).reader_id, rec.id)          # the book's active reader
            folder = self.lib.root / "readers" / rec.folder
        self.assertTrue((folder / "reader.npz").is_file())
        got = read_with_reader(self.lib, self.book)
        with self.lib.session() as s:
            n = s.scalar(select(func.count(Sample.id)).where(Sample.book_id == self.book, Sample.deleted.is_(False),
                                                             Sample.part == "training", Sample.mask != ""))
            self.assertEqual(got["samples"], n)
            run = s.scalar(select(OcrRun.id).where(OcrRun.engine == "reader"))
            self.assertEqual(s.scalar(select(func.count(OcrReading.id)).where(OcrReading.run_id == run)), n)
            self.assertEqual(engines(s, s.get(Book, self.book))[0], "reader")   # the main reader now
        found = {c["sample_id"]: c for c in check_list(self.lib, self.book)}
        self.assertIn(self.planted, found)
        self.assertEqual((found[self.planted]["label"], found[self.planted]["read"]), ("ख", "क"))
        with self.lib.session() as s:                                          # moved since: no longer listed
            s.get(Sample, self.planted).group_id = self.groups[0]
        self.assertNotIn(self.planted, {c["sample_id"] for c in check_list(self.lib, self.book)})
        delete_reader(self.lib, r["reader"])
        self.assertFalse(folder.exists())
        self.assertIsNone(self.lib.get_book(self.book).reader_id)

    def test_rare_labels_can_be_learned_from_one_letter(self):
        with self.lib.session() as s:
            one = s.scalars(select(Sample).where(Sample.group_id == self.groups[2])).first()
            g = LetterGroup(book_id=self.book, code="g9999", label_dev="घ", label_guj="", status="labelled")
            s.add(g)
            s.flush()
            one.group_id = g.id
        self.assertEqual(train_reader(self.lib, [self.book], min_samples=5)["left_out"] >= 1, True)
        self.assertEqual(train_reader(self.lib, [self.book], min_samples=1)["labels"], 4)

    def test_too_few_labels(self):
        with self.assertRaises(LibraryError):
            train_reader(self.lib, [self.book], min_samples=10_000)

    def test_api(self):
        r = train_reader(self.lib, [self.book], min_samples=2)
        c = TestClient(create_app(self.lib, "t"))
        h = {"X-Token": "t"}
        listed = c.get("/api/readers", headers=h).json()
        self.assertEqual([x["id"] for x in listed], [r["reader"]])
        full = c.get(f"/api/readers/{r['reader']}", headers=h).json()
        self.assertEqual({x["label"] for x in full["per_label"]}, {"क", "ख", "ग"})
        self.assertEqual(c.get(f"/api/books/{self.book}", headers=h).json()["reader_id"], r["reader"])
        check = c.get(f"/api/books/{self.book}/check", headers=h).json()
        self.assertIn(self.planted, [x["sample_id"] for x in check])
        self.assertTrue(all("image" in x["sample"] for x in check))
        self.assertEqual(c.delete(f"/api/readers/{r['reader']}", headers=h).status_code, 204)
        c.close()


if __name__ == "__main__":
    unittest.main()

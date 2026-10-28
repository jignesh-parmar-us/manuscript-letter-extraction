"""S3 (docs/plans/done/SPEED_PLAN.md): the Measure cache. Each letter's rows computed once and kept, the same in every fold;
the checked lines cut into windows once for all folds; letter masks from one file. Logic and equality tests
on the synthetic test book, no heavy runs."""
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import appbook                                                      # noqa: E402
from letter_extractor.app import linesearch                         # noqa: E402
from letter_extractor.app.db import LetterGroup, Line, LineTruth, Page, Sample   # noqa: E402
from letter_extractor.app.linestore import FeatureStore, MaskPack, store_folder   # noqa: E402
from letter_extractor.ocr import features as feat                   # noqa: E402
from letter_extractor.ocr.segment import SearchSettings, line_windows, line_windows_range, narrow   # noqa: E402
from sqlalchemy import func, select                                 # noqa: E402

LABELS = ("क", "ख", "ग", "घ", "च", "छ")


class Counting:
    """Counts the feature computations of the line search (ocr.features.features)."""

    def __init__(self):
        self.calls = 0

    def __call__(self, mask, spacing):
        self.calls += 1
        return feat.features(mask, spacing)


class FakeReader:
    """Probabilities from the window's features alone (fixed weights): enough to cut checked lines the same way."""

    def __init__(self, classes):
        self.classes = list(classes)
        self.W = np.random.default_rng(1).standard_normal((feat.dimension(), len(self.classes))).astype(np.float32)

    def probabilities(self, X):
        z = X @ self.W
        z -= z.max(axis=1, keepdims=True)
        e = np.exp(z)
        return e / e.sum(axis=1, keepdims=True)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.lib, self.book, _ = appbook.fresh_copy()
        self.book_dir = self.lib.book_dir(self.lib.get_book(self.book))
        with self.lib.session() as s:
            rows = s.execute(select(LetterGroup.id).join(Sample, Sample.group_id == LetterGroup.id)
                             .where(LetterGroup.book_id == self.book, Sample.line_id.is_not(None))
                             .group_by(LetterGroup.id).order_by(func.count(Sample.id).desc())).all()
            self.groups = [gid for (gid,) in rows[:len(LABELS)]]
            for gid, label in zip(self.groups, LABELS):
                g = s.get(LetterGroup, gid)
                g.label_dev, g.status = label, "labelled"
            self.files = sorted(s.scalars(select(Page.file).where(Page.book_id == self.book)))

    def tearDown(self):
        appbook.cleanup(self.tmp, self.lib)

    def _train(self, skip=(), **kw):
        count = Counting()
        with mock.patch.object(linesearch, "features", count):
            data = linesearch._training_set(self.lib, self.book, skip, **kw)
        return data, count.calls

    def test_a_letters_rows_are_the_same_in_every_fold(self):
        a, b = FeatureStore(self.tmp / "a"), FeatureStore(self.tmp / "b")
        linesearch._training_set(self.lib, self.book, (), store=a)
        linesearch._training_set(self.lib, self.book, [self.files[1]], store=b)    # another fold
        self.assertTrue(b.entries)
        for sid, e in b.entries.items():
            same = a.entries[sid]
            for part in ("base", "negs"):
                self.assertTrue(all(np.array_equal(x, y) for x, y in zip(getattr(e, part), getattr(same, part))))
            n = min(len(e.varied), len(same.varied))
            self.assertTrue(all(np.array_equal(x, y) for x, y in zip(e.varied[:n], same.varied[:n])))

    def test_a_second_training_on_an_unchanged_book_computes_no_features(self):
        first, made = self._train()
        self.assertGreater(made, 0)
        self.assertTrue((store_folder(self.book_dir) / "rows.npz").is_file())
        again, made = self._train()
        self.assertEqual(made, 0)
        for k in ("X", "y", "weights"):                                       # kept exactly
            self.assertTrue(np.array_equal(first[k], again[k]), k)
        self.assertEqual(first["classes"], again["classes"])

    def test_reviewing_or_relabelling_a_group_computes_nothing(self):
        self._train()
        with self.lib.session() as s:
            s.get(LetterGroup, self.groups[0]).status = "reviewed"
            s.get(LetterGroup, self.groups[1]).label_dev = "ज"
        data, made = self._train()
        self.assertEqual(made, 0)
        self.assertIn("ज", data["classes"])                                  # the label comes from the database
        self.assertNotIn("ख", data["classes"])

    def test_recutting_one_line_computes_only_that_lines_letters(self):
        self._train()
        with self.lib.session() as s:
            smp = s.scalar(select(Sample).where(Sample.group_id == self.groups[0]).order_by(Sample.id))
            line_id = smp.line_id
            on_line = s.scalar(select(func.count(Sample.id)).where(Sample.line_id == line_id,
                                                                   Sample.group_id.in_(self.groups)))
            smp.x += 1                                                       # its box changed
        store = FeatureStore(self.book_dir)
        linesearch._training_set(self.lib, self.book, store=store)
        self.assertEqual(store.computed, on_line)

    def test_a_changed_mask_file_is_read_again(self):
        self._train()
        with self.lib.session() as s:
            smp = s.scalar(select(Sample).where(Sample.group_id == self.groups[0]).order_by(Sample.id))
            sid, path = smp.id, self.book_dir / smp.mask
        from PIL import Image
        m = np.asarray(Image.open(path).convert("L")) > 127
        h, w = m.shape
        m[h // 2, w // 2] = not m[h // 2, w // 2]                            # the mask's content changed
        Image.fromarray(m.astype(np.uint8) * 255).save(path)
        store = FeatureStore(self.book_dir)
        masks = MaskPack(self.book_dir)
        linesearch._training_set(self.lib, self.book, store=store, masks=masks)
        self.assertEqual(masks.read, 1)                                      # only that PNG opened
        self.assertGreaterEqual(store.computed, 1)
        self.assertTrue(np.array_equal(masks.masks[sid], m))

    def test_masks_from_the_pack_are_the_pngs(self):
        from letter_extractor.app.samples import _sample_mask
        self._train()
        pack = MaskPack(self.book_dir)
        self.assertGreater(len(pack.masks), 20)
        book = self.lib.get_book(self.book)
        with self.lib.session() as s:
            for smp in s.scalars(select(Sample).where(Sample.id.in_(list(pack.masks)[:40]))):
                self.assertTrue(np.array_equal(pack.get(smp), _sample_mask(self.lib, book, smp)))
        self.assertEqual(pack.read, 0)                                       # nothing opened again

    def test_varied_copies_are_topped_up_as_needed_and_kept(self):
        store = FeatureStore(self.tmp / "s")
        linesearch._training_set(self.lib, self.book, store=store)
        with self.lib.session() as s:                                        # a label loses most of its letters
            for smp in s.scalars(select(Sample).where(Sample.group_id == self.groups[0]).order_by(Sample.id)).all()[2:]:
                smp.group_id = None
        before = {s_: len(e.varied) for s_, e in store.entries.items()}
        linesearch._training_set(self.lib, self.book, store=store)
        grew = [s_ for s_, e in store.entries.items() if len(e.varied) > before.get(s_, 0)]
        self.assertEqual(len(grew), 2)                                       # its two letters got more copies

class WindowTests(unittest.TestCase):
    def _line(self):
        rng = np.random.default_rng(3)
        m = np.zeros((60, 400), bool)
        for x in range(10, 380, 37):
            m[10:14, x:x + 30] = True                                       # headline piece
            m[14:50, x + rng.integers(5, 25):x + 30] |= rng.random((36, 1)) < 0.9
        m[:, 200:215] = False                                                # a word gap
        return m

    def test_windows_of_a_range_narrowed_are_those_of_one_width(self):
        m = self._line()
        every = line_windows_range(m, 100.0, 28.0, 41.0)
        for T in (28.0, 33.5, 41.0):
            one, got = line_windows(m, 100.0, T), narrow(every, T)
            self.assertEqual(got.cand, one.cand)
            self.assertEqual(got.empty_edges, one.empty_edges)
            self.assertEqual(got.meta, one.meta)
            self.assertTrue(np.array_equal(got.X, one.X))                   # bit for bit
        self.assertIsNone(narrow(None, 30.0))

    def test_a_letters_features_are_the_same_every_time_and_as_a_windows(self):
        m = self._line()[:, 40:75]
        rows = [feat.features(m, 100.0) for _ in range(20)]
        self.assertTrue(all(np.array_equal(rows[0], r) for r in rows))
        self.assertTrue(np.array_equal(rows[0], feat.features_batch([m, m[:, 3:]], 100.0)[0]))
        self.assertEqual(len(rows[0]), feat.dimension())


class CorrectionTests(unittest.TestCase):
    """Learning from corrections for several folds at once gives each fold the windows and rows of one fold at a
    time (the code before S3: `_line_ink` and `line_windows` per fold)."""

    def setUp(self):
        self.tmp, self.lib, self.book, _ = appbook.fresh_copy()
        with self.lib.session() as s:
            pages = s.scalars(select(Page).where(Page.book_id == self.book).order_by(Page.id)).all()
            self.files = [p.file for p in pages]
            for p in pages:
                p.part = "read"
                for ln in s.scalars(select(Line).where(Line.page_id == p.id)):
                    s.add(LineTruth(line_id=ln.id, text_dev="कखग कखग कखग कखग"))

    def tearDown(self):
        appbook.cleanup(self.tmp, self.lib)

    def _old(self, base, meta, skip):
        from letter_extractor.ocr.aksharas import split_aksharas
        from letter_extractor.ocr.segment import align
        book = self.lib.get_book(self.book)
        T, X, labels = meta["typical_width"], [], []
        for lid, _, spacing, text in linesearch._checked_lines(self.lib, self.book, skip):
            f = linesearch.page_scale(spacing, meta.get("spacing"))
            ink = linesearch._line_ink(self.lib, book, lid, T, f)
            if ink is None:
                continue
            win = line_windows(ink[0], (spacing or 100.0) * f, T)
            if win is None or not len(win.X):
                continue
            aks = [a for a in split_aksharas(linesearch._chars(text)) if a.strip() and a != "?"]
            path, score = align(win, base.probabilities(win.X), base.classes, T, aks)
            if path is None or score < linesearch.MIN_ALIGN:
                continue
            for q, a in path:
                X.append(win.X[q])
                labels.append(a)
        return X, labels

    def test_several_folds_at_once_learn_what_each_fold_learned_alone(self):
        base = FakeReader(list(LABELS) + [linesearch.NOT_A_LETTER])
        folds = {0: (base, {"typical_width": 30.0, "spacing": 0.0}, {self.files[0]}),
                 1: (base, {"typical_width": 36.0, "spacing": 0.0}, {self.files[1]}),
                 2: (base, {"typical_width": 33.0, "spacing": 0.0}, set())}
        with mock.patch.object(linesearch, "MIN_ALIGN", -1e9):                # learn from every line
            got = linesearch._learn_folds(self.lib, self.book, folds,
                                          masks=MaskPack(self.lib.book_dir(self.lib.get_book(self.book))))
            for k, (b, meta, skip) in folds.items():
                X, labels = self._old(b, meta, sorted(skip))
                self.assertGreater(len(X), 0)
                self.assertEqual(got[k]["labels"], labels, k)
                self.assertTrue(np.array_equal(np.array(got[k]["X"]), np.array(X)), k)

    def test_a_quick_measure_reads_half_the_folds_and_keeps_the_last_full_measure(self):
        from letter_extractor.app.db import WholeLine
        with self.lib.session() as s:
            for lid in s.scalars(select(LineTruth.line_id)):
                s.add(WholeLine(line_id=lid, engine="tesseract", aksharas="[]"))
        full = linesearch._measure_file(self.lib, self.lib.get_book(self.book))
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text('{"cer": {"ours": 7.3}}', encoding="utf-8")
        meta = {"letters": 30, "labels": 3, "typical_width": 30.0, "widths": {}}
        with mock.patch.object(linesearch, "_training_set", return_value={"meta": meta}) as train, \
                mock.patch.object(linesearch, "_fit", return_value=None), \
                mock.patch.object(linesearch, "_learn_folds", return_value={0: {"lines": 0}}) as learn, \
                mock.patch.object(linesearch, "read_line", return_value=("कखग", [], {})), \
                mock.patch.object(linesearch, "_read_many", wraps=linesearch._read_many) as many:
            r = linesearch.measure(self.lib, self.book, quick=True)
        with self.lib.session() as s:
            checked = sorted(s.scalars(select(LineTruth.line_id).join(Line, Line.id == LineTruth.line_id)
                                       .join(Page, Page.id == Line.page_id).where(Page.file == self.files[0])))
        self.assertEqual(many.call_count, 1)                                 # the fold's lines in one batch
        self.assertEqual(sorted(lid for lid, _ in many.call_args.args[2]), checked)
        self.assertEqual((r["quick"], r["folds"], r["tested_folds"], r["pages"]), (True, 2, 1, 2))
        fold = self.lib.left_out(self.book, [self.files[0]])                 # C24: the fold's pages, resolved
        self.assertEqual([c.args[2] for c in train.call_args_list], [fold] * 2)               # one fold, base and final
        self.assertEqual(list(learn.call_args.args[2]), [0])
        self.assertEqual({x["page"] for x in linesearch.last_measure(self.lib, self.book, quick=True)["line_results"]},
                         {self.files[0]})
        self.assertEqual(linesearch.last_measure(self.lib, self.book)["cer"]["ours"], 7.3)   # not replaced


if __name__ == "__main__":
    unittest.main()

"""S4 (docs/SPEED_PLAN.md): faster reading and retraining, the same numbers. Window features without searching a
window's ink three times and HOG without Python loops (a); lines in parallel, results in line order (b); Adam in
place (c); the batch and the base reader's epochs as settings (d, e)."""
import os
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC)

import appbook                                                      # noqa: E402
from letter_extractor import features as F                          # noqa: E402
from letter_extractor.app import linesearch                         # noqa: E402
from letter_extractor.app.db import Line, LineTruth, Page           # noqa: E402
from letter_extractor.config import Config                          # noqa: E402
from letter_extractor.ocr import segment                            # noqa: E402
from letter_extractor.ocr.features import features_batch            # noqa: E402
from letter_extractor.ocr.reader import adam_step                   # noqa: E402
from sqlalchemy import select                                       # noqa: E402
from test_linestore import FakeReader, LABELS                       # noqa: E402


def old_hog_batch(imgs):
    """hog_batch before S4a: cv2.Sobel image by image, the blocks one by one."""
    g = imgs.astype(np.float32)
    n, size, _ = g.shape
    gx = np.stack([cv2.Sobel(im, cv2.CV_32F, 1, 0, ksize=3) for im in g])
    gy = np.stack([cv2.Sobel(im, cv2.CV_32F, 0, 1, ksize=3) for im in g])
    mag = np.sqrt(gx * gx + gy * gy)
    ang = (np.degrees(np.arctan2(gy, gx)) + 180.0) % 180.0
    b = np.minimum((ang / (180.0 / F.HOG_BINS)).astype(np.int64), F.HOG_BINS - 1)
    cell = size // F.HOG_CELLS
    rows = np.minimum(np.arange(size) // cell, F.HOG_CELLS - 1)
    cy, cx = np.meshgrid(rows, rows, indexing="ij")
    idx = (cy[None] * F.HOG_CELLS + cx[None]) * F.HOG_BINS + b
    idx = idx + (np.arange(n) * F.HOG_CELLS * F.HOG_CELLS * F.HOG_BINS)[:, None, None]
    hist = np.bincount(idx.ravel(), weights=mag.ravel().astype(np.float64),
                       minlength=n * F.HOG_CELLS * F.HOG_CELLS * F.HOG_BINS).astype(np.float32)
    hist = hist.reshape(n, F.HOG_CELLS, F.HOG_CELLS, F.HOG_BINS)
    blocks = []
    for i in range(F.HOG_CELLS - 1):
        for j in range(F.HOG_CELLS - 1):
            v = hist[:, i:i + 2, j:j + 2].reshape(n, -1)
            v = v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-6)
            v = np.minimum(v, 0.2)
            blocks.append(v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-6))
    return np.concatenate(blocks, axis=1)


def line_mask(seed=3, width=900):
    rng = np.random.default_rng(seed)
    m = np.zeros((70, width), bool)
    for x in range(10, width - 40, 41):
        m[10:15, x:x + 33] = True
        m[15:58, x + rng.integers(4, 26):x + 33] |= rng.random((43, 1)) < 0.85
        m[15:58, x:x + 33] &= rng.random((43, 33)) < 0.97
    m[:, 300:318] = False
    return m


class WindowFeatureTests(unittest.TestCase):
    def test_hog_of_many_images_is_the_same_as_with_opencvs_sobel(self):
        rng = np.random.default_rng(0)
        imgs = np.stack([cv2.GaussianBlur((rng.random((40, 40)) < 0.3).astype(np.uint8) * 255, (0, 0), 0.8)
                         for _ in range(60)])
        imgs[0] = 0                                                          # an empty image
        self.assertTrue(np.array_equal(F.hog_batch(imgs), old_hog_batch(imgs)))

    def test_a_windows_ink_box_from_its_columns_is_the_searched_one(self):
        m = line_mask()
        ink = segment._Ink(m)
        for a, b in [(0, 40), (5, 77), (290, 330), (300, 318), (-5, 20), (880, 950), (40, 40), (100, 90)]:
            want, got = segment._crop(m, a, b), ink.crop(a, b)
            if want is None:
                self.assertIsNone(got, (a, b))
            else:
                self.assertTrue(np.array_equal(want, got), (a, b))

    def test_tight_windows_give_the_same_features(self):
        m = line_mask()
        crops = [c for c in (segment._crop(m, a, a + w) for a in range(0, 800, 37) for w in (20, 45, 80)) if c is not None]
        self.assertTrue(np.array_equal(features_batch(crops, 110.0, tight=True), features_batch(crops, 110.0)))

    def test_a_lines_windows_are_those_found_by_searching_each(self):
        m = line_mask(width=600)
        win = segment.line_windows(m, 110.0, 40.0)
        s = segment.SearchSettings()
        crops = []
        for i, j, _ in win.meta:                                            # each window searched as before S4a
            crops.append(segment._crop(m, win.cand[i], win.cand[j]))
        self.assertGreater(len(crops), 100)
        self.assertTrue(np.array_equal(win.X, features_batch(crops, 110.0)))
        self.assertTrue(all(s.min_width * 40 <= w <= s.max_width * 40 for _, _, w in win.meta))


class AdamTests(unittest.TestCase):
    def test_adam_in_place_is_the_written_out_formula(self):
        rng = np.random.default_rng(1)
        p = rng.standard_normal((50, 30)).astype(np.float32)
        m, v = np.zeros_like(p), np.zeros_like(p)
        p2, m2, v2 = p.copy(), m.copy(), v.copy()
        buf = (np.empty_like(p), np.empty_like(p))
        for step in range(1, 8):
            g = rng.standard_normal(p.shape).astype(np.float32)
            adam_step(p, g, m, v, buf, step, 2e-3)
            m2 = 0.9 * m2 + 0.1 * g                                          # before S4c
            v2 = 0.999 * v2 + 0.001 * g * g
            mh, vh = m2 / (1 - 0.9 ** step), v2 / (1 - 0.999 ** step)
            p2 -= 2e-3 * mh / (np.sqrt(vh) + 1e-8)
        self.assertTrue(np.array_equal(p, p2) and np.array_equal(m, m2) and np.array_equal(v, v2))


class SettingsTests(unittest.TestCase):
    def test_batch_and_base_epochs_are_book_settings(self):
        tmp, lib, book, _ = appbook.fresh_copy()
        try:
            lib.set_book_config(book, Config(line_batch=512, line_base_epochs=8))
            data = {"X": np.zeros((1, 2)), "meta": {"typical_width": 30.0}}
            with mock.patch.object(linesearch, "_training_set", return_value=data), \
                    mock.patch.object(linesearch, "_fit") as fit, \
                    mock.patch.object(linesearch, "_learn_corrections", return_value={"lines": 0}):
                linesearch._train(lib, book)
            self.assertEqual(fit.call_args_list[0].kwargs, {"epochs": 8, "batch": 512})
            self.assertEqual(fit.call_args_list[1].kwargs, {"batch": 512})
            self.assertEqual((Config().line_batch, Config().line_base_epochs), (128, linesearch.BASE_EPOCHS))
        finally:
            appbook.cleanup(tmp, lib)


class ParallelTests(unittest.TestCase):
    """Lines in worker processes give the same text and rows, in the same order, as one after the other."""
    LEVEL = "full"                    # starts worker processes: tools/test_parallel.py runs it in `full` only

    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"LETTER_EXTRACTOR_WORKERS": ""})   # the test runner's cap off
        self.env.start()
        self.tmp, self.lib, self.book, _ = appbook.fresh_copy()
        with self.lib.session() as s:
            pages = s.scalars(select(Page).where(Page.book_id == self.book).order_by(Page.id)).all()
            self.pages = [(p.id, p.line_spacing or 100.0) for p in pages]
            for p in pages:
                p.part = "read"
                for ln in s.scalars(select(Line).where(Line.page_id == p.id)):
                    s.add(LineTruth(line_id=ln.id, text_dev="कखग कखग कखग कखग"))

    def tearDown(self):
        appbook.cleanup(self.tmp, self.lib)
        self.env.stop()

    def test_reading_lines_in_workers_gives_the_same_text(self):
        book = self.lib.get_book(self.book)
        reader = FakeReader(list(LABELS) + [linesearch.NOT_A_LETTER])
        meta = {"typical_width": 32.0, "widths": {a: 32.0 for a in LABELS}, "spacing": 0.0}
        with self.lib.session() as s:
            lines = list(s.scalars(select(Line.id).where(Line.page_id == self.pages[0][0]).order_by(Line.number)))
        alone = linesearch._read_lines(self.lib, book, lines, self.pages[0][1], (reader, meta), None)
        with segment.LinePool(2, reader, None, min_lines=1) as pool:
            together = linesearch._read_lines(self.lib, book, lines, self.pages[0][1], (reader, meta), None, pool=pool)
            self.assertIsNotNone(pool.ex)                                    # it did use the workers
        self.assertEqual(together, alone)
        self.assertTrue(any(text for text, _ in alone.values()))

    def test_learning_from_lines_in_workers_gives_the_same_rows(self):
        base = FakeReader(list(LABELS) + [linesearch.NOT_A_LETTER])
        folds = {0: (base, {"typical_width": 30.0, "spacing": 0.0}, set()),
                 1: (base, {"typical_width": 36.0, "spacing": 0.0}, set())}
        with mock.patch.object(linesearch, "MIN_ALIGN", -1e9):
            alone = linesearch._learn_folds(self.lib, self.book, folds)
            self.lib.set_book_config(self.book, Config(line_workers=2))
            with mock.patch.object(segment, "MIN_PARALLEL_LINES", 1):
                together = linesearch._learn_folds(self.lib, self.book, folds)
        for k in folds:
            self.assertGreater(len(alone[k]["X"]), 0)
            self.assertEqual(together[k]["labels"], alone[k]["labels"])
            self.assertTrue(np.array_equal(np.array(together[k]["X"]), np.array(alone[k]["X"])))

    def test_killing_a_parallel_read_leaves_no_worker(self):
        run = (f"import sys,os,time; sys.path.insert(0,{SRC!r})\n"
               "import numpy as np\n"
               "from letter_extractor.ocr.segment import LinePool, SearchSettings\n"
               "if __name__ == '__main__':\n"
               "    pool = LinePool(2, min_lines=1)\n"
               "    list(pool.windows([(np.ones((20, 40), bool), 100.0, 30.0, 30.0, SearchSettings())] * 2))\n"
               "    print(' '.join(str(p.pid) for p in pool.ex._processes.values()), flush=True)\n"
               "    time.sleep(60)\n")
        p = subprocess.Popen([sys.executable, "-c", run], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        pids = [int(x) for x in p.stdout.readline().split()]
        self.assertEqual(len(pids), 2)
        os.kill(p.pid, signal.SIGKILL)
        p.wait()
        p.stdout.close()

        def alive(pid):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return False
            return True
        deadline = time.time() + 10
        while time.time() < deadline and any(alive(x) for x in pids):
            time.sleep(0.2)
        self.assertFalse([x for x in pids if alive(x)])


if __name__ == "__main__":
    unittest.main()

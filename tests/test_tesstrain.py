"""C30a: Tesseract taught from a book's checked lines (export in Measure's folds, training steps, fold-fair scoring)."""
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import appbook                                                      # noqa: E402
from test_wholelines import READ, reading                           # noqa: E402
from letter_extractor import io_utils                               # noqa: E402
from letter_extractor.app import linesearch, suggest, tesstrain     # noqa: E402
from letter_extractor.app.db import BOOK, Book, Line, Page          # noqa: E402
from letter_extractor.app.library import Cancelled                  # noqa: E402
from letter_extractor.app.wholelines import read_book_lines, set_whole_line   # noqa: E402
from letter_extractor.config import Config                          # noqa: E402
from letter_extractor.ocr import tesseract as T                     # noqa: E402
from letter_extractor.ocr.language import LanguageModel             # noqa: E402
from sqlalchemy import select                                       # noqa: E402

RIGHT = reading([("न", 96.0, []), ("ा", 95.0, []), ("र", 97.0, []), ("ा", 96.0, []), ("य", 97.0, []),
                 ("ण", 90.0, [])], [("भ", 98.0, []), ("ग", 98.0, [])])        # नारायण भग


class TesstrainTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.lib, self.book, _ = appbook.fresh_copy()
        self.lib.set_book_config(self.book, Config(language_model=False))
        with self.lib.session() as s:
            self.pages = list(s.scalars(select(Page.id).where(Page.book_id == self.book).order_by(Page.id)))
            for pid in self.pages:
                s.get(Page, pid).part = "read"                         # the checked lines are Read Book lines
        read_book_lines(self.lib, self.book, self.pages, reader=lambda rgb: READ)
        with self.lib.session() as s:
            first, second = (list(s.scalars(select(Line.id).where(Line.page_id == pid).order_by(Line.number)))
                             for pid in self.pages)
            self.lines = [first[0], first[1], second[0]]               # two lines of page 1, one of page 2
        for i, lid in enumerate(self.lines):                          # ZWJ and the border "|" are not training text
            set_whole_line(self.lib, lid, text=["नारायण भग", "क्‍ष |", "भग"][i], reviewed=True)
        self.out = self.tmp / "tess"

    def tearDown(self):
        appbook.cleanup(self.tmp, self.lib)

    def test_the_folds_are_measures(self):
        rows = linesearch.checked_rows(self.lib, self.book)
        pages, n = linesearch.fold_pages(rows, 2)
        meta = tesstrain.export_lines(self.lib, self.book, self.out, folds=2)
        self.assertEqual((meta["folds"], meta["lines"]), (n, 3))
        for k in range(n):
            self.assertEqual(meta["fold_info"][k]["pages"], [p[2] for p in pages[k::n]])
            tested = {f"p{p[1]}_" for p in pages[k::n]}
            test = (self.out / f"fold{k}" / "test.txt").read_text().split()
            train = [p.name for p in (self.out / f"fold{k}" / "train").glob("*.gt.txt")]
            self.assertTrue(test and all(t[:len(next(iter(tested)))] in tested for t in test))
            self.assertFalse([t for t in train if any(t.startswith(x) for x in tested)])   # no tested line to learn from
            self.assertEqual(len(test) + len(train), 3)

    def test_ground_truth_is_cleaned_as_scored(self):
        tesstrain.export_lines(self.lib, self.book, self.out)
        texts = sorted(p.read_text(encoding="utf-8") for p in (self.out / "all").glob("*.gt.txt"))
        self.assertEqual(texts, sorted(["नारायण भग\n", "क्ष\n", "भग\n"]))

    def test_the_exported_image_is_the_one_tesseract_gets(self):
        tesstrain.export_lines(self.lib, self.book, self.out)
        with self.lib.session() as s:
            ln = s.get(Line, self.lines[0])
            image, stem = ln.image, f"p{ln.page_id}_L{ln.number:02d}"
        rgb, _ = io_utils.load_image(self.lib.book_dir(self.lib.get_book(self.book)) / image)
        seen = []
        engine = T.Engine("tesseract", "5", ["script/Devanagari"])
        with mock.patch.object(T, "run_hocr", side_effect=lambda e, img, *a, **k: seen.append(img) or ""):
            T.read_line(rgb, engine, target_height=0)
        exported = np.array(Image.open(self.out / "all" / f"{stem}.png"))
        np.testing.assert_array_equal(exported, seen[0])

    def test_boxes_keep_a_virama_with_its_letter(self):
        self.assertEqual(tesstrain.box_lines("क्षा", 10, 5),
                         ["क् 0 0 10 5 0", "ष 0 0 10 5 0", "ा 0 0 10 5 0", "\t 0 0 10 5 0"])

    def test_training_runs_the_steps_from_the_start_model(self):
        tesstrain.export_lines(self.lib, self.book, self.out, folds=2)
        calls = []

        def run(cmd, env, log):
            calls.append([str(c) for c in cmd])
            if cmd[0] == "tesseract":
                Path(f"{cmd[2]}.lstmf").write_bytes(b"")                   # what lstm.train writes
        start = self.tmp / "tools" / "tessdata" / "Devanagari.traineddata"
        model = tesstrain.train_model(self.out / "fold0" / "train", self.out / "work", "fold0", self.tmp / "tools",
                                      start, epochs=12, run=run)
        self.assertEqual(model, self.out / "work" / "fold0.traineddata")
        progs = [c[0] for c in calls]
        n = len(list((self.out / "fold0" / "train").glob("*.gt.txt")))
        self.assertEqual(progs, ["tesseract"] * n + ["combine_tessdata", "unicharset_extractor", "merge_unicharsets",
                                                      "combine_lang_model", "lstmtraining", "lstmtraining"])
        self.assertIn("lstm.train", calls[0])
        self.assertEqual(calls[0][calls[0].index("--psm") + 1], "13")             # a raw line: 7 makes no .lstmf
        self.assertEqual(calls[0][calls[0].index("-l") + 1], "Devanagari")        # no eng model needed
        train = calls[-2]
        self.assertEqual(train[train.index("--max_iterations") + 1], "-12")         # 12 epochs
        self.assertEqual(train[train.index("--old_traineddata") + 1], str(start))
        self.assertIn("--stop_training", calls[-1])
        self.assertTrue((self.out / "work" / "fold0" / "proto" / "fold0").is_dir())     # combine_lang_model writes there
        box = next((self.out / "work" / "fold0" / "lines").glob("*.box")).read_text(encoding="utf-8")
        self.assertTrue(box.endswith("\t 0 0 " + box.splitlines()[0].split(" ", 3)[3] + "\n"))

    def test_training_stops_when_no_line_gives_a_training_file(self):
        tesstrain.export_lines(self.lib, self.book, self.out, folds=2)
        with self.assertRaises(tesstrain.LibraryError):
            tesstrain.train_model(self.out / "fold0" / "train", self.out / "work", "fold0", self.tmp / "tools",
                                  self.tmp / "Devanagari.traineddata", run=lambda cmd, env, log: None)

    def test_a_model_folder_is_passed_to_tesseract(self):
        engine = T.Engine("tesseract", "5", ["fold0"], tessdata_dir="/m")
        with mock.patch.object(T, "_run") as run:
            run.return_value.returncode, run.return_value.stdout = 0, b""
            T.run_hocr(engine, np.full((20, 20), 255, np.uint8), "fold0", 7)
        args = run.call_args.args[0]
        self.assertEqual(args[args.index("--tessdata-dir") + 1], "/m")
        self.assertEqual(T.Engine("tesseract", "5", []).model_args(), [])          # default: the installed models

    def test_a_reader_reads_in_the_given_mode_or_the_books(self):
        engine = T.Engine("tesseract", "5", ["fold0"], tessdata_dir="/m")
        cfg = Config(ocr_psm=7)
        with mock.patch.object(tesstrain, "find_tesseract", return_value=engine), \
                mock.patch.object(tesstrain, "read_line") as read:
            tesstrain.model_reader(cfg, "/m", "fold0")(None)
            tesstrain.model_reader(cfg, "/m", "fold0", psm=13)(None)
        self.assertEqual([c.kwargs["psm"] for c in read.call_args_list], [7, 13])

    def test_a_line_read_empty_is_read_again_in_the_fallback_mode(self):
        engine = T.Engine("tesseract", "5", ["fold0"], tessdata_dir="/m")
        empty = T.LineReading(words=[], hocr="", scale=1.0)
        by_mode = {7: empty, 13: RIGHT}
        with mock.patch.object(tesstrain, "find_tesseract", return_value=engine), \
                mock.patch.object(tesstrain, "read_line", side_effect=lambda *a, **kw: by_mode[kw["psm"]]) as read:
            self.assertIs(tesstrain.model_reader(Config(ocr_psm=7), "/m", "fold0", fallback_psm=13)(None), RIGHT)
            self.assertIs(tesstrain.model_reader(Config(ocr_psm=7), "/m", "fold0")(None), empty)   # default: not
            by_mode[7] = READ
            self.assertIs(tesstrain.model_reader(Config(ocr_psm=7), "/m", "fold0", fallback_psm=13)(None), READ)
        self.assertEqual([c.kwargs["psm"] for c in read.call_args_list], [7, 13, 7, 7])   # read again only if empty

    def test_scoring_is_fold_fair_and_per_reader(self):
        self.lib.set_book_config(self.book, Config(language_model=True))
        lm = LanguageModel().add_all(["नारायण भगवान"] * 20)
        with mock.patch("letter_extractor.app.dictionary.book_model_without", return_value=lm) as without:
            r = tesstrain.score(self.lib, self.book, lambda k: {"stock": lambda rgb: READ, "tuned": lambda rgb: RIGHT},
                                folds=4)
        tested = {c.args[2] for c in without.call_args_list}
        self.assertEqual(len(tested), 2)                                            # one language model per fold (2 pages)
        self.assertEqual(set(r["cer"]), {"stock", "stock_lm", "tuned", "tuned_lm"})
        first = next(x for x in r["line_results"] if x["truth"] == "नारायण भग")
        self.assertEqual((first["wrong"]["stock"], first["wrong"]["tuned"]), (1, 0))   # व for ण
        self.assertEqual(first["read"]["stock_lm"], "नारायण भग")                    # the language model's fix
        self.assertIn("<mark>", tesstrain.score_page(r, "t"))

    def test_suspects_are_where_the_model_disagrees_most_sure_first(self):
        r = tesstrain.score(self.lib, self.book, lambda k: {"stock": lambda rgb: READ, "tuned": lambda rgb: RIGHT},
                            folds=4)
        found = tesstrain.suspects(r, "stock")
        first = [s for s in found if s["truth"] == "नारायण भग"]
        self.assertEqual(len(first), 1)                                             # व for ण, nothing else
        s = first[0]
        self.assertEqual((s["truth"][slice(*s["at"][0])], s["read"][slice(*s["at"][1])]), ("ण", "व"))
        conf = next(a[1] for x in r["line_results"] if x["truth"] == "नारायण भग" for a in x["aks"]["stock"]
                    if a[0] == "व")
        self.assertEqual(s["conf"], conf)                                           # the akshara read there
        self.assertEqual([x["conf"] for x in found], sorted((x["conf"] for x in found), reverse=True))
        self.assertTrue(s["stem"].startswith(f"p{self.pages[0]}_L"))                # the export's picture
        self.assertNotIn("नारायण भग", [x["truth"] for x in tesstrain.suspects(r, "tuned")])   # reads it right
        self.assertIn(f"all/{s['stem']}.png", tesstrain.suspects_page(found, "t"))



class BookModelTests(unittest.TestCase):
    """C30c: a book's Tesseract model trained in the app, and any book reading with any trained model."""

    def setUp(self):
        TesstrainTests.setUp(self)
        with self.lib.session() as s:
            s.get(Book, self.book).kind = BOOK                       # a model is trained on a book's checked lines
        self.tools = self.tmp / "tools"
        (self.tools / "tessdata" / "configs").mkdir(parents=True)
        (self.tools / "tessdata" / "Devanagari.traineddata").write_bytes(b"start")
        (self.tools / "tessdata" / "configs" / "hocr").write_text("hocr", encoding="utf-8")
        self.calls = []

    def tearDown(self):
        appbook.cleanup(self.tmp, self.lib)

    def run_programs(self, cmd, env, log):
        cmd = [str(c) for c in cmd]
        self.calls.append(cmd)
        if cmd[0] == "tesseract":
            Path(f"{cmd[2]}.lstmf").write_bytes(b"")
        if cmd[0] == "lstmtraining" and "--stop_training" not in cmd:
            log.write("At iteration 40/40/40, mean rms=0.1%, delta=0.2%, BCER train=1.300%, BWER train=4%\n")
        if "--stop_training" in cmd:
            Path(cmd[cmd.index("--model_output") + 1]).write_bytes(b"trained")

    def train(self, start_book=0):
        return tesstrain.train_book_model(self.lib, self.book, start_book, str(self.tools), run=self.run_programs)

    def test_a_book_model_is_trained_on_every_checked_line_and_kept(self):
        self.lib.set_book_config(self.book, Config(language_model=False, tesstrain_epochs=7))
        r = self.train()
        folder = tesstrain.model_folder(self.lib, self.lib.get_book(self.book))
        self.assertEqual((folder / "book.traineddata").read_bytes(), b"trained")
        self.assertTrue((folder / "configs" / "hocr").is_file())                 # reading with hocr needs it
        self.assertFalse((folder / "work").exists())                              # work files are not kept
        self.assertEqual((r["lines"], r["epochs"], r["start_name"], r["psm"], r["training_error"]),
                         (3, 7, "Standard", 13, 1.3))
        self.assertEqual(sum(c[0] == "tesseract" for c in self.calls), 3)          # every checked line, no folds
        train = next(c for c in self.calls if c[0] == "lstmtraining")
        self.assertEqual(train[train.index("--old_traineddata") + 1],
                         str(self.tools / "tessdata" / "Devanagari.traineddata"))
        info = tesstrain.model_info(self.lib, self.lib.get_book(self.book))
        self.assertFalse(info["changed"])
        self.assertNotIn("signature", info)
        self.assertEqual([m["book_id"] for m in tesstrain.trained_models(self.lib)], [self.book])
        set_whole_line(self.lib, self.lines[2], text="नर", reviewed=True)            # a checked line changes
        self.assertTrue(tesstrain.model_info(self.lib, self.lib.get_book(self.book))["changed"])

    def test_training_can_start_from_another_books_model_but_not_its_own(self):
        self.train()
        other = self.lib.create_book("Other printing", writing="printed", kind=BOOK).id
        own = tesstrain.model_folder(self.lib, self.lib.get_book(self.book)) / "book.traineddata"
        self.assertEqual(tesstrain.start_model(self.lib, self.lib.get_book(other), self.tools, self.book), own)
        with self.assertRaises(tesstrain.LibraryError):
            tesstrain.start_model(self.lib, self.lib.get_book(self.book), self.tools, self.book)

    def test_the_book_reads_with_the_chosen_model(self):
        book = self.lib.get_book(self.book)
        self.assertIsNone(tesstrain.book_model(self.lib, book))                     # Standard
        self.lib.set_book_config(self.book, Config(ocr_model_book=self.book))
        with self.assertRaises(tesstrain.LibraryError):                             # chosen, but not trained
            tesstrain.book_model(self.lib, self.lib.get_book(self.book))
        self.train()
        folder = str(tesstrain.model_folder(self.lib, book))
        self.assertEqual(tesstrain.book_model(self.lib, self.lib.get_book(self.book)), (folder, "book", 13))
        engine = T.Engine("tesseract", "5", ["book"], tessdata_dir=folder)
        empty = T.LineReading(words=[], hocr="", scale=1.0)
        with mock.patch.object(suggest, "find_tesseract", return_value=engine) as find, \
                mock.patch.object(suggest, "read_line", side_effect=lambda *a, **kw: empty if kw["psm"] == 7 else RIGHT) as read:
            self.assertIs(suggest.book_tesseract_reader(self.lib, self.lib.get_book(self.book))(None), RIGHT)
        self.assertEqual(find.call_args.args, ("", folder))
        self.assertEqual([(c.kwargs["langs"], c.kwargs["psm"]) for c in read.call_args_list], [("book", 7), ("book", 13)])

    def test_standard_tesseract_reads_an_empty_line_once(self):
        engine = T.Engine("tesseract", "5", ["script/Devanagari"])
        empty = T.LineReading(words=[], hocr="", scale=1.0)
        with mock.patch.object(suggest, "find_tesseract", return_value=engine), \
                mock.patch.object(suggest, "read_line", return_value=empty) as read:
            suggest.book_tesseract_reader(self.lib, self.lib.get_book(self.book))(None)
        self.assertEqual([c.kwargs["psm"] for c in read.call_args_list], [7])       # as before C30c

    def test_cancelling_stops_a_training_program(self):
        log = open(self.tmp / "log.txt", "w", encoding="utf-8")
        try:
            with self.assertRaises(Cancelled):
                tesstrain.runner(lambda: True)(["sleep", "30"], {}, log)
        finally:
            log.close()

    def test_choosing_a_model_in_reading_setup(self):
        from fastapi.testclient import TestClient
        from letter_extractor.app.api import create_app
        c = TestClient(create_app(self.lib, "t"))
        h = {"X-Token": "t"}
        url = f"/api/books/{self.book}/tesseract-model"
        self.assertEqual(c.put(url, json={"book_id": self.book}, headers=h).status_code, 400)   # not trained yet
        self.train()
        setup = c.put(url, json={"book_id": self.book}, headers=h).json()["tesseract"]
        self.assertEqual((setup["using"], setup["own"]["lines"], len(setup["models"])), (self.book, 3, 1))
        self.assertEqual(self.lib.book_config(self.lib.get_book(self.book)).ocr_model_book, self.book)
        self.assertEqual(c.put(url, json={"book_id": 0}, headers=h).json()["tesseract"]["using"], 0)
        c.close()


if __name__ == "__main__":
    unittest.main()

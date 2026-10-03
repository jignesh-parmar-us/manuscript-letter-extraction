"""C0: folder input, bad files, report, config file."""
import csv
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from synthetic import make_page                                    # noqa: E402
from letter_extractor import cli, io_utils                         # noqa: E402
from letter_extractor.config import Config, load_config            # noqa: E402
from letter_extractor.pipeline import process_folder               # noqa: E402

CFG = Config(workers=1)


def _read_report(out: Path):
    with open(out / "report.csv", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _hashes(folder: Path):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}


class FolderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.inp, self.out = self.tmp / "in", self.tmp / "out"
        self.inp.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _page(self, name):
        Image.fromarray(make_page()[0]).save(self.inp / name)

    def test_mixed_folder_runs_to_the_end(self):
        self._page("page2.png")
        self._page("page10.jpg")
        (self.inp / "broken.jpg").write_bytes(b"\xff\xd8\xff not really a jpeg")
        (self.inp / "notes.txt").write_text("hello", encoding="utf-8")
        before = _hashes(self.inp)

        results = process_folder(self.inp, self.out, CFG)

        self.assertEqual([r.file for r in results], ["broken.jpg", "page2.png", "page10.jpg"])
        status = {row["file"]: row["status"] for row in _read_report(self.out)}
        self.assertEqual(status, {"broken.jpg": "FAILED", "page2.png": "OK",
                                  "page10.jpg": "OK", "notes.txt": "IGNORED"})
        self.assertEqual(_hashes(self.inp), before, "input folder must never change")

    def test_report_has_page_size_and_block(self):
        self._page("p.png")
        process_folder(self.inp, self.out, CFG)
        row = _read_report(self.out)[0]
        self.assertEqual((row["width"], row["height"]), ("1400", "700"))
        self.assertNotEqual(row["block_w"], "")

    def test_natural_sort_order(self):
        names = [Path(n) for n in ("p10.png", "p2.png", "P1.png")]
        self.assertEqual([p.name for p in sorted(names, key=io_utils.natural_key)],
                         ["P1.png", "p2.png", "p10.png"])

    def test_missing_input_folder(self):
        with self.assertRaises(io_utils.FolderError):
            process_folder(self.tmp / "nope", self.out, CFG)

    def test_same_input_and_output_folder(self):
        self._page("p.png")
        with self.assertRaises(io_utils.FolderError):
            process_folder(self.inp, self.inp, CFG)

    def test_empty_folder(self):
        with self.assertRaises(io_utils.FolderError):
            process_folder(self.inp, self.out, CFG)

    def test_debug_writes_ink_overlay(self):
        self._page("p.png")
        process_folder(self.inp, self.out, Config(workers=1, debug=True))
        self.assertTrue((self.out / "debug" / "p_ink.png").is_file())

    def test_cli_exit_codes(self):
        self.assertEqual(cli.main(["-i", str(self.tmp / "nope"), "-o", str(self.out)]), 2)
        self._page("p.png")
        self.assertEqual(cli.main(["-i", str(self.inp), "-o", str(self.out), "-w", "1"]), 0)
        (self.inp / "broken.png").write_bytes(b"x")
        self.assertEqual(cli.main(["-i", str(self.inp), "-o", str(self.out), "-w", "1"]), 1)


class ConfigTests(unittest.TestCase):
    def test_json_overrides_nested_values(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cfg.json"
            p.write_text(json.dumps({"black_max_rel_l": 0.5, "red": {"min_speck_px": 3}}), encoding="utf-8")
            cfg = load_config(p, workers=2)
        self.assertEqual(cfg.black_max_rel_l, 0.5)
        self.assertEqual(cfg.red.min_speck_px, 3)
        self.assertEqual(cfg.black.min_speck_px, Config().black.min_speck_px)
        self.assertEqual(cfg.workers, 2)

    def test_unknown_setting_is_an_error(self):
        with self.assertRaises(ValueError):
            load_config(None, no_such_setting=1)
        with self.assertRaises(ValueError):
            load_config(None, red={"nope": 1})


if __name__ == "__main__":
    unittest.main()

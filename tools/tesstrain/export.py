"""C30a: a book's checked lines as Tesseract training pairs, in Measure's folds.

Usage: PYTHONPATH=src .venv/bin/python tools/tesstrain/export.py --library <copy> --book 8 --out <dir>

Writes <dir>/all/<stem>.png + .gt.txt, <dir>/fold<k>/train/ (the other folds' lines), <dir>/fold<k>/test.txt
and <dir>/meta.json (app/tesstrain.py, export_lines). Reads the library, changes nothing; use a copy anyway
(tools/harness/copy_library.sh).
"""
import argparse
import json

from letter_extractor.app.library import Library
from letter_extractor.app.tesstrain import export_lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", required=True)
    ap.add_argument("--book", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--folds", type=int, default=4)
    a = ap.parse_args()
    lib = Library(a.library)
    try:
        meta = export_lines(lib, a.book, a.out, a.folds)
    finally:
        lib.close()
    print(json.dumps(meta, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

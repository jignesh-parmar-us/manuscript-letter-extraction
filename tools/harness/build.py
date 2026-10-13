"""Build one fold's cache: the training windows without the fold's pages, and the windows of its checked lines.

Usage: PYTHONPATH=src .venv/bin/python tools/harness/build.py --library <copy> --cache <dir> --fold K [--book 6]

The pages with checked lines (Line truth, Read Book) are sorted by their number and dealt into 4 folds
(K::4), as `linesearch.measure` does. Writes <cache>/train{K}.npz + .json and <cache>/lines{K}.pkl.
Letters on no line are left out here (`unlined=False`); a variant adds them (run.py --unlined).
"""
import argparse
import json
import pickle

import numpy as np
from sqlalchemy import select

from letter_extractor.app import linesearch
from letter_extractor.app.db import Line, LineTruth, Page, WholeLine
from letter_extractor.app.library import Library
from letter_extractor.app.wholelines import trim_edges
from letter_extractor.ocr.segment import SearchSettings, line_windows

FOLDS = 4


def checked_rows(lib, book_id):
    with lib.session() as s:
        return s.execute(select(Page.id, Page.file, Page.number, Page.line_spacing, Line.id, Line.number,
                                LineTruth.text_dev, WholeLine.aksharas)
                         .join(Line, Line.page_id == Page.id).join(LineTruth, LineTruth.line_id == Line.id)
                         .join(WholeLine, WholeLine.line_id == Line.id)
                         .where(Page.book_id == book_id, Page.part == "read", LineTruth.text_dev != "")
                         .order_by(Page.number, Page.id, Line.number)).all()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", required=True)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--fold", type=int, required=True)
    ap.add_argument("--book", type=int, default=6)
    a = ap.parse_args()
    lib = Library(a.library)
    book = lib.get_book(a.book)
    rows = checked_rows(lib, a.book)
    pages = sorted({(r[2], r[0], r[1], r[3]) for r in rows})
    fold = pages[a.fold::FOLDS]
    files = [p[2] for p in fold]
    print("fold", a.fold, files, flush=True)
    data = linesearch._training_set(lib, a.book, files, progress=lambda m: print(m, flush=True), unlined=False)
    np.savez_compressed(f"{a.cache}/train{a.fold}.npz", X=data["X"], y=data["y"], weights=data["weights"])
    json.dump({"classes": data["classes"], "meta": data["meta"], "files": files},
              open(f"{a.cache}/train{a.fold}.json", "w"), ensure_ascii=False)
    T = data["meta"]["typical_width"]
    lines = []
    for _, pid, file, spacing in fold:
        for r in [r for r in rows if r[0] == pid]:
            ink = linesearch._line_ink(lib, book, r[4], T)
            if ink is None:
                continue
            win = line_windows(ink[0], spacing or 100.0, T, SearchSettings())
            aks = trim_edges(json.loads(r[7]))
            lines.append({"page": file, "line": r[5], "line_id": r[4], "truth": r[6], "win": win,
                          "spacing": spacing or 100.0, "tess_aks": [x[0] for x in aks],
                          "tess_lm_aks": [x[3] if len(x) > 3 and x[3] else x[0] for x in aks], "ink": ink[0]})
            print("line", file, r[5], len(win.meta) if win else 0, flush=True)
    pickle.dump(lines, open(f"{a.cache}/lines{a.fold}.pkl", "wb"))
    print("done", a.fold, flush=True)


if __name__ == "__main__":
    main()

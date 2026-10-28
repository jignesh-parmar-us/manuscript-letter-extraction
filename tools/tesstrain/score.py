"""C30a: stock Tesseract against the fold-trained models on the book's checked lines, fold-fair.

Usage: PYTHONPATH=src .venv/bin/python tools/tesstrain/score.py --library <copy> --book 8 --data <dir>
       [--folds 0 1] [--name tuned] [--psm 13] [--fallback-psm 13]
       PYTHONPATH=src .venv/bin/python tools/tesstrain/score.py --library <copy> --book 7 --data <dir> \
       --model <a book's model folder> --fallback-psm 13

Each fold's lines are read through the app's Whole-lines route by the installed model (the book's ocr_langs,
"stock") and by <dir>/models/fold<k>.traineddata ("tuned"), each also with the book's language model without
the fold's pages ("_lm"). `--model`: "tuned" is that trained model (a book's `<model folder>/tesseract`, C30c) for every
fold instead, to see whether another book's model reads this one (it never saw these lines; <dir> only gets the
results, no meta.json needed). `--psm`: read in this page segmentation mode (default the book's `ocr_psm`); `--fallback-psm`: read a line read empty again in this mode. Prints the characters wrong; writes <dir>/<name>.json and <dir>/<name>.html (every
line, to check by eye). A heavy job: takes the heavy-job lock.
"""
import argparse
import json
from pathlib import Path

from letter_extractor.app.library import Library
from letter_extractor.app.tesstrain import MODEL, model_reader, score, score_page
from letter_extractor.heavy import heavy_lock, lower_priority


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", required=True)
    ap.add_argument("--book", type=int, required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--folds", type=int, nargs="*", default=None, help="only these folds (default all)")
    ap.add_argument("--name", default="score")
    ap.add_argument("--psm", type=int, default=None, help="page segmentation mode (default the book's ocr_psm)")
    ap.add_argument("--fallback-psm", type=int, default=None, help="read a line read empty again in this mode")
    ap.add_argument("--model", default="", help="a trained model's folder (book.traineddata) for every fold")
    a = ap.parse_args()
    data = Path(a.data)
    data.mkdir(parents=True, exist_ok=True)
    meta = data / "meta.json"
    n = json.loads(meta.read_text(encoding="utf-8"))["folds"] if meta.is_file() else 4
    lib = Library(a.library)
    cfg = lib.book_config(lib.get_book(a.book))
    stock = model_reader(cfg, "", "", psm=a.psm, fallback_psm=a.fallback_psm)

    other = model_reader(cfg, a.model, MODEL, psm=a.psm, fallback_psm=a.fallback_psm) if a.model else None

    def readers(k):
        out = {"stock": stock}
        if other:
            out["tuned"] = other
        elif (data / "models" / f"fold{k}.traineddata").is_file():
            out["tuned"] = model_reader(cfg, str(data / "models"), f"fold{k}", psm=a.psm,
                                        fallback_psm=a.fallback_psm)
        return out
    lower_priority()
    try:
        with heavy_lock(f"tesseract scoring ({data})"):
            result = score(lib, a.book, readers, n, a.folds, progress=print)
    finally:
        lib.close()
    (data / f"{a.name}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    (data / f"{a.name}.html").write_text(score_page(result, f"Tesseract trained on checked lines: book {a.book}"),
                                         encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "line_results"}, ensure_ascii=False, indent=1))
    print(data / f"{a.name}.html")


if __name__ == "__main__":
    main()

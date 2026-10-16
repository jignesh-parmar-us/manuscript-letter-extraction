"""Try a variant of our reader on the cached folds, fold-fair, and score it on the checked lines.

Usage (after build.py for folds 0-3):
  PYTHONPATH=src .venv/bin/python tools/harness/run.py --library <copy> --cache <dir> --name base [options]

Options: --batch 512, --base-epochs 8 (S4d, S4e: tried in S5), --quick (only folds 0 and 1 trained and read: about half the time, to throw out bad ideas early;
never quote its numbers), --lm 0.35 0.5 (language model weights to try; the readers are trained once), --hidden 0 (384: a
network), --epochs 40, --seed 0, --no-corrections (do not learn from the other folds' checked lines),
--unlined (also the reviewed letters on no line, System generated), --unreviewed-generated (with
--unlined: also generated letters not reviewed).

For each fold: the reader is trained on the cached training windows (without the fold's pages); unless
--no-corrections, a first reader cuts the other folds' checked lines into the aksharas of their text
(`segment.align`) and those windows are added (`linesearch._with_corrections`), as Retrain does. Then the
fold's lines are read with the search. Prints characters wrong (all lines, and Untitled-52/53), the most
common confusions, and writes <cache>/<name>_lm<w>.html: every line, its checked text, our reader and
Tesseract, the differences marked.
"""
import argparse
import collections
import difflib
import html
import json
import pickle
import time
import unicodedata

import numpy as np

from letter_extractor.app import linesearch
from letter_extractor.heavy import heavy_lock, lower_priority
from letter_extractor.app.dictionary import book_model_without
from letter_extractor.app.library import Library
from letter_extractor.ocr.aksharas import split_aksharas
from letter_extractor.ocr.reader import LetterReader
from letter_extractor.ocr.segment import SearchSettings, align, search

FOLDS = 4
NEW_PAGES = ("Untitled-52.jpg", "Untitled-53.jpg")
ch, dist = linesearch._chars, linesearch._distance


def fold_data(cache, k):
    z = np.load(f"{cache}/train{k}.npz")
    j = json.load(open(f"{cache}/train{k}.json"))
    return {"X": z["X"], "y": z["y"], "weights": z["weights"], "classes": j["classes"], "meta": j["meta"],
            "files": j["files"]}


def fit(data, hidden, epochs, seed, batch=128):
    r = LetterReader(data["classes"], data["X"].shape[1], hidden=hidden, seed=seed)
    r.train(data["X"], data["y"], weights=data["weights"], epochs=epochs, seed=seed, batch=batch)
    return r


def unlined_rows(lib, book_id, classes, y, unreviewed_generated, seed=0):
    """The letters on no line as training rows: picture and varied copies (as `_training_set` does)."""
    from sqlalchemy import select
    from letter_extractor.app.db import LetterGroup, Page, Sample
    from letter_extractor.app.samples import _sample_mask
    from letter_extractor.ocr.features import features, varied
    rng = np.random.default_rng(seed)
    book = lib.get_book(book_id)
    with lib.session() as s:
        sp = [v for v in s.scalars(select(Page.line_spacing).where(Page.book_id == book_id, Page.part == "training")) if v]
        usual = float(np.median(sp)) if sp else 0.0
        ok = (LetterGroup.status != "auto") | (Sample.source == "generated") if unreviewed_generated \
            else LetterGroup.status != "auto"
        rows = s.execute(select(Sample, LetterGroup.label_dev).join(LetterGroup, Sample.group_id == LetterGroup.id)
                         .where(Sample.book_id == book_id, Sample.deleted.is_(False), Sample.line_id.is_(None),
                                Sample.mask != "", LetterGroup.label_dev != "", ok)).all()
        items = [(smp, lab, _sample_mask(lib, book, smp)) for smp, lab in rows if len(split_aksharas(lab)) == 1]
    freq = collections.Counter(classes[i] for i in y)
    for _, lab, _ in items:
        freq[lab] += 1
    X, labels, widths = [], [], collections.defaultdict(list)
    for smp, lab, m in items:
        spc = usual or 1.6 * smp.h
        for mm in [m] + [varied(m, rng) for _ in range(max(3, min(30, -(-20 // freq[lab]))))]:
            X.append(features(mm, spc))
            labels.append(lab)
        widths[lab].append(smp.w)
    return {"X": X, "labels": labels, "widths": widths}


def confusions(out, n=30):
    c = collections.Counter()
    for x in out:
        T = [a for a in split_aksharas(ch(x["truth"])) if a.strip()]
        O = [a for a in split_aksharas(ch(x["ours"])) if a.strip()]
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, T, O, autojunk=False).get_opcodes():
            if op != "equal":
                c[("".join(T[i1:i2]), "".join(O[j1:j2]))] += 1
    return c.most_common(n)


def marked(text, truth):
    """The text with what differs from the checked text marked."""
    sm = difflib.SequenceMatcher(None, truth, text, autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        part = html.escape(text[j1:j2])
        out.append(part if op == "equal" else f"<mark>{part or '·'}</mark>")
    return "".join(out)


def page(name, out, scores):
    rows = "".join(
        f"<tr><td>{html.escape(x['page'])} · {x['line']}</td><td class=t><div>{html.escape(x['truth'])}</div>"
        f"<div>{marked(x['ours'], x['truth'])}</div><div class=m>{marked(x['tess'], x['truth'])}</div></td>"
        f"<td class=n>{x['w_ours']}</td><td class=n>{x['w_tess']}</td></tr>" for x in out)
    return f"""<!doctype html><meta charset=utf-8><title>{html.escape(name)}</title>
<style>body{{font:15px system-ui;margin:16px}}td{{border-bottom:1px solid #ddd;padding:4px 8px;vertical-align:top}}
.t{{font:19px/1.5 "Noto Sans Devanagari",sans-serif}}.t div:first-child{{font-weight:600}}.m{{color:#555}}
mark{{background:#ffd27a}}.n{{text-align:right}}</style>
<h1>{html.escape(name)}</h1><p>{html.escape(scores)}</p>
<p>Each line: the checked text, our reader, Tesseract (grey); what differs from the checked text is marked.</p>
<table><tr><th>Page · line</th><th>Text</th><th>Ours wrong</th><th>Tesseract wrong</th></tr>{rows}</table>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", required=True)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--book", type=int, default=6)
    ap.add_argument("--lm", type=float, nargs="+", default=[0.5])
    ap.add_argument("--hidden", type=int, default=0)
    ap.add_argument("--epochs", type=int, default=linesearch.EPOCHS)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-corrections", action="store_true")
    ap.add_argument("--unlined", action="store_true")
    ap.add_argument("--unreviewed-generated", action="store_true")
    ap.add_argument("--batch", type=int, default=128, help="training batch (S4d: 512 tried in S5)")
    ap.add_argument("--base-epochs", type=int, default=linesearch.BASE_EPOCHS, help="the reader that cuts the checked lines (S4e)")
    ap.add_argument("--quick", action="store_true", help="2 of the 4 folds: for screening only, never quote it")
    a = ap.parse_args()
    lower_priority()
    with heavy_lock(f"harness run ({a.library})"):
        _main(a)


def _main(a):
    lib = Library(a.library)

    datas = {k: fold_data(a.cache, k) for k in range(FOLDS // 2 if a.quick else FOLDS)}
    if a.unlined:
        for k, d in datas.items():
            extra = unlined_rows(lib, a.book, d["classes"], d["y"], a.unreviewed_generated)
            datas[k] = {**linesearch._with_corrections(d, extra), "files": d["files"]}
            print(f"fold {k}: {len(extra['labels'])} rows of letters on no line", flush=True)
    if not a.no_corrections:
        bases = {k: fit(d, 0, a.base_epochs, a.seed, a.batch) for k, d in datas.items()}
        learned = {k: {"X": [], "labels": [], "widths": collections.defaultdict(list), "lines": 0} for k in datas}
        for j in range(FOLDS):                              # one fold's lines in memory at a time
            lines = pickle.load(open(f"{a.cache}/lines{j}.pkl", "rb"))
            for k in datas:
                if k == j:
                    continue
                T = datas[k]["meta"]["typical_width"]
                for L in lines:
                    if L["win"] is None or not len(L["win"].X):
                        continue
                    A = [x for x in split_aksharas(ch(L["truth"])) if x.strip() and x != "?"]
                    path, score = align(L["win"], bases[k].probabilities(L["win"].X), bases[k].classes, T, A)
                    if path is None or score < linesearch.MIN_ALIGN:
                        continue
                    learned[k]["lines"] += 1
                    for q, x in path:
                        learned[k]["X"].append(L["win"].X[q].copy())
                        learned[k]["labels"].append(x)
                        learned[k]["widths"][x].append(L["win"].meta[q][2])
            del lines
        for k in datas:
            datas[k] = {**linesearch._with_corrections(datas[k], learned[k]), "files": datas[k]["files"]}
            print(f"fold {k}: learned {learned[k]['lines']} checked lines", flush=True)
    readers = {k: fit(d, a.hidden, a.epochs, a.seed, a.batch) for k, d in datas.items()}

    for w in a.lm:
        t0, out = time.time(), []
        for k, d in datas.items():
            lm = book_model_without(lib, a.book, d["files"])
            lm = lm if len(lm) else None
            r, meta = readers[k], d["meta"]
            for L in pickle.load(open(f"{a.cache}/lines{k}.pkl", "rb")):
                text = ""
                if L["win"] is not None and len(L["win"].X):
                    text, _, _ = search(L["win"], r.probabilities(L["win"].X), r.classes, meta["typical_width"],
                                        meta["widths"], lm, SearchSettings(lm_weight=w))
                text = unicodedata.normalize("NFC", text)
                t = ch(L["truth"])
                out.append({"page": L["page"], "line": L["line"], "truth": L["truth"], "ours": text,
                            "tess": "".join(L["tess_aks"]), "chars": len(t), "w_ours": dist(ch(text), t),
                            "w_tess": dist(ch("".join(L["tess_aks"])), t)})
        C = sum(x["chars"] for x in out)
        new = [x for x in out if x["page"] in NEW_PAGES]
        Cn = sum(x["chars"] for x in new) or 1
        scores = (f"{'QUICK (2 of 4 folds, screening only) ' if a.quick else ''}{a.name} lm{w}: ours {100 * sum(x['w_ours'] for x in out) / C:.2f}%, tesseract "
                  f"{100 * sum(x['w_tess'] for x in out) / C:.2f}% | new pages ours "
                  f"{100 * sum(x['w_ours'] for x in new) / Cn:.2f}%, tesseract {100 * sum(x['w_tess'] for x in new) / Cn:.2f}%"
                  f" | {len(out)} lines, {C} characters")
        print(scores, f"({time.time() - t0:.0f} s)", flush=True)
        with open(f"{a.cache}/{a.name}_lm{w}.html", "w", encoding="utf-8") as f:
            f.write(page(f"{a.name}, language model {w}", out, scores))
        for (x, y), n in confusions(out):
            print(f"  {n} {x!r} -> {y!r}")


if __name__ == "__main__":
    main()

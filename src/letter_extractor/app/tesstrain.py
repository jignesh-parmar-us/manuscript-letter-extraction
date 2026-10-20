"""Teaching Tesseract a book from its checked lines (C30a, docs/implementation_plan_phase3_later.md).

Tesseract is a line reader (CNN-LSTM-CTC): it can be fine-tuned on pairs of a line image and its text, with no
letter boxes. Here:

- `export_lines`: every checked line (Line truth) of the book's Read Book pages as `<stem>.png` (the image exactly
  as the Whole-lines route gives it to Tesseract: `prepare_line` with the book's `ocr_letter_height`) and
  `<stem>.gt.txt` (the checked text, cleaned as scored). Folders `all/` and, per fold, `fold<k>/train/` (the other
  folds' lines) and `fold<k>/test.txt`. The folds are Measure's (`linesearch.fold_pages`).
- `train_model`: the steps of tesstrain's Makefile (github.com/tesseract-ocr/tesstrain), run from Python with the
  training programs of `tools/tesstrain/setup.sh`: boxes, `.lstmf`, unicharset, `combine_lang_model`,
  `lstmtraining` from a float start model (`tessdata_best`), then the model as `<name>.traineddata`.
- `score`: each fold's lines read through the app's own route (`wholelines._aksharas`, `trim_edges`), with the
  language model without the fold's pages (fold-fair), by several readers (stock and trained Tesseract), scored
  with Measure's `_chars` / `_distance`; `score_page` is the line-by-line page.

Nothing here changes the library: it reads lines and writes files in the given folders.
"""
from __future__ import annotations

import difflib
import html
import json
import os
import shutil
import subprocess
import time
import unicodedata
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np
from PIL import Image
from sqlalchemy import select

from .. import io_utils
from ..ocr.tesseract import find_tesseract, prepare_line, read_line
from .db import Line
from .library import Library, LibraryError
from .linesearch import _chars, _distance, checked_rows, fold_pages

BORDER = 10                                  # white border around a line image, as `read_line` adds


def gt_text(text: str) -> str:
    """A checked text as training text: NFC, without the invisible joiners (ZWNJ, ZWJ) and the border "|"
    (left out when scoring too), spaces as single spaces."""
    t = unicodedata.normalize("NFC", text)
    t = "".join(ch for ch in t if ch not in "|‌‍")
    return " ".join(t.split())


def line_png(rgb: np.ndarray, cfg) -> np.ndarray:
    """The image Tesseract gets for a line in the Whole-lines route."""
    return prepare_line(rgb, cfg.ocr_letter_height, BORDER)[0]


def _stem(page_id: int, line_number: int) -> str:
    return f"p{page_id}_L{line_number:02d}"


def export_lines(lib: Library, book_id: int, out: Path, folds: int = 4) -> Dict:
    """Write the book's checked lines for training (see the module notes). Returns what was written."""
    out = Path(out)
    book = lib.get_book(book_id)
    cfg = lib.book_config(book)
    rows = checked_rows(lib, book_id)
    if not rows:
        raise LibraryError("No checked lines yet.")
    pages, n = fold_pages(rows, folds)
    with lib.session() as s:
        images = dict(s.execute(select(Line.id, Line.image).where(Line.id.in_([r[4] for r in rows]))).all())
    folder = lib.book_dir(book)
    every = out / "all"
    every.mkdir(parents=True, exist_ok=True)
    stems, empty = {}, 0
    for r in rows:
        text = gt_text(r[6])
        if not text:
            empty += 1
            continue
        stem = _stem(r[0], r[5])
        rgb, _ = io_utils.load_image(folder / images[r[4]])
        Image.fromarray(line_png(rgb, cfg)).save(every / f"{stem}.png", dpi=(300, 300))
        (every / f"{stem}.gt.txt").write_text(text + "\n", encoding="utf-8")
        stems.setdefault(r[0], []).append(stem)
    fold_info = []
    for k in range(n):
        tested = {p[1] for p in pages[k::n]}
        train = out / f"fold{k}" / "train"
        if train.exists():
            shutil.rmtree(train)
        train.mkdir(parents=True)
        for pid, mine in stems.items():
            if pid in tested:
                continue
            for stem in mine:
                for ext in (".png", ".gt.txt"):
                    shutil.copyfile(every / f"{stem}{ext}", train / f"{stem}{ext}")
        test = [stem for pid in sorted(tested) for stem in stems.get(pid, [])]
        (out / f"fold{k}" / "test.txt").write_text("".join(f"{x}\n" for x in test), encoding="utf-8")
        fold_info.append({"fold": k, "pages": [p[2] for p in pages[k::n]], "test": len(test),
                          "train": sum(len(v) for pid, v in stems.items() if pid not in tested)})
    meta = {"book": book_id, "book_name": book.name, "folds": n, "lines": sum(len(v) for v in stems.values()),
            "empty": empty, "ocr_letter_height": cfg.ocr_letter_height, "ocr_psm": cfg.ocr_psm,
            "ocr_langs": cfg.ocr_langs, "fold_info": fold_info}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


# ---- training -------------------------------------------------------------------------------------

def box_lines(text: str, width: int, height: int) -> List[str]:
    """A line's box file for line training (tesstrain's generate_line_box.py): one box per character, each the
    whole image, a combining mark (virama, nukta) kept with the character before it, then the end of line."""
    line = unicodedata.normalize("NFC", text.strip())
    out = []
    for i in range(1, len(line)):
        ch, prev = line[i], line[i - 1]
        if unicodedata.combining(ch):
            out.append(f"{prev + ch} 0 0 {width} {height} 0")
        elif not unicodedata.combining(prev):
            out.append(f"{prev} 0 0 {width} {height} 0")
    if line and not unicodedata.combining(line[-1]):
        out.append(f"{line[-1]} 0 0 {width} {height} 0")
    if line:
        out.append(f"\t 0 0 {width} {height} 0")
    return out


def _run(cmd: Sequence[str], env: Dict[str, str], log) -> None:
    log.write("$ " + " ".join(str(c) for c in cmd) + "\n")
    log.flush()
    r = subprocess.run([str(c) for c in cmd], env=env, stdout=log, stderr=subprocess.STDOUT)
    if r.returncode != 0:
        raise LibraryError(f"{Path(str(cmd[0])).name} failed (exit code {r.returncode}); see {log.name}.")


def train_model(gt_dir: Path, work: Path, name: str, tools: Path, start: Path, epochs: int = 20,
                psm: int = 13, learning_rate: float = 0.0001, ratio_train: float = 0.9, indic: bool = True,
                run: Callable = _run) -> Path:
    """Fine-tune the float model `start` (a .traineddata of tessdata_best, in a folder with `configs/lstm.train`)
    on the pairs in `gt_dir`, with the training programs in `tools` (`<tools>/bin`, langdata in
    `<tools>/langdata`: tools/tesstrain/setup.sh). Work files go to
    `work/<name>/`; returns `work/<name>.traineddata`. `run(cmd, env, log)` runs one program (tests).
    `psm` 13 (a raw line, tesstrain's default): with 7, `lstm.train` writes no `.lstmf` and says nothing
    (seen on 2026-10-20). Reading stays at the book's `ocr_psm`. A line without a `.lstmf` is listed in the log."""
    gt_dir, work, tools, start = Path(gt_dir), Path(work), Path(tools), Path(start)
    out = work / name
    out.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PATH": f"{tools / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
           "OMP_THREAD_LIMIT": "1"}
    pairs = sorted(p for p in gt_dir.glob("*.gt.txt"))
    if not pairs:
        raise LibraryError(f"No *.gt.txt in {gt_dir}.")
    with open(out / "training.log", "a", encoding="utf-8") as log:
        log.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')}: {name}, {len(pairs)} lines, {epochs} epochs\n")
        lstmf, gt_all = [], []
        for gt in pairs:
            stem = gt.name[:-len(".gt.txt")]
            png = gt_dir / f"{stem}.png"
            text = gt.read_text(encoding="utf-8").strip()
            gt_all.append(text)
            dest = out / "lines" / stem
            dest.parent.mkdir(exist_ok=True)
            shutil.copyfile(png, dest.with_suffix(".png"))
            with Image.open(png) as im:
                w, h = im.size
            dest.with_suffix(".box").write_text("\n".join(box_lines(text, w, h)) + "\n", encoding="utf-8")
            # the start model's folder holds configs/lstm.train (setup.sh); `-l` so no `eng` model is needed
            run(["tesseract", dest.with_suffix(".png"), dest, "--tessdata-dir", start.parent, "-l", start.stem,
                 "--psm", str(psm), "lstm.train"], env, log)
            if dest.with_suffix(".lstmf").is_file():
                lstmf.append(dest.with_suffix(".lstmf"))
            else:
                log.write(f"no .lstmf for {stem}: left out\n")
        if not lstmf:
            raise LibraryError(f"Tesseract made no training file (.lstmf) from the lines; see {log.name}.")
        # the same split as tesstrain (generate_eval_train.py): the first `ratio_train` to learn, the rest to evaluate
        cut = max(1, min(len(lstmf) - 1, int(ratio_train * len(lstmf)))) if len(lstmf) > 1 else 1
        (out / "list.train").write_text("\n".join(str(p) for p in lstmf[:cut]) + "\n", encoding="utf-8")
        (out / "list.eval").write_text("\n".join(str(p) for p in (lstmf[cut:] or lstmf[:1])) + "\n", encoding="utf-8")
        (out / "all-gt").write_text("\n".join(gt_all) + "\n", encoding="utf-8")
        unpacked = out / "start" / "start"
        unpacked.parent.mkdir(exist_ok=True)
        run(["combine_tessdata", "-u", start, f"{unpacked}."], env, log)
        run(["unicharset_extractor", "--output_unicharset", out / "my.unicharset", "--norm_mode", "2",
             out / "all-gt"], env, log)
        run(["merge_unicharsets", f"{unpacked}.lstm-unicharset", out / "my.unicharset", out / "unicharset"], env, log)
        (out / "proto" / name).mkdir(parents=True, exist_ok=True)       # it writes there but does not make it
        run(["combine_lang_model", "--input_unicharset", out / "unicharset", "--script_dir", tools / "langdata",
             "--output_dir", out / "proto", *(["--pass_through_recoder"] if indic else []), "--lang", name], env, log)
        proto = out / "proto" / name / f"{name}.traineddata"
        (out / "checkpoints").mkdir(exist_ok=True)
        run(["lstmtraining", "--traineddata", proto, "--old_traineddata", start, "--continue_from",
             f"{unpacked}.lstm", "--learning_rate", str(learning_rate), "--model_output", out / "checkpoints" / name,
             "--train_listfile", out / "list.train", "--eval_listfile", out / "list.eval",
             "--max_iterations", str(-abs(epochs)), "--target_error_rate", "0.01"], env, log)
        model = work / f"{name}.traineddata"
        run(["lstmtraining", "--stop_training", "--continue_from", out / "checkpoints" / f"{name}_checkpoint",
             "--traineddata", proto, "--model_output", model], env, log)
    return model


# ---- scoring ----------------------------------------------------------------------------------------

def model_reader(cfg, tessdata_dir: str, lang: str, tesseract_path: str = "") -> Callable:
    """A line reader like the Whole-lines route's (`suggest.tesseract_reader`), with the model `lang` of the
    folder `tessdata_dir` ("" = the installed models and the book's `ocr_langs`)."""
    engine = find_tesseract(tesseract_path, tessdata_dir)
    langs = lang or cfg.ocr_langs
    engine.check_langs(langs)
    return lambda rgb: read_line(rgb, engine, langs=langs, psm=cfg.ocr_psm, target_height=cfg.ocr_letter_height,
                                 border=BORDER, env={"OMP_THREAD_LIMIT": "1"})


def score(lib: Library, book_id: int, readers: Callable[[int], Dict[str, Callable]], folds: int = 4,
          only: Optional[Sequence[int]] = None, progress: Optional[Callable[[str], None]] = None) -> Dict:
    """Read each fold's checked lines with `readers(k)` ({name: reader}), fold-fair (see the module notes).
    Each name is scored as read and, with the book's language model on, as corrected by it (`<name>_lm`).
    `only`: the folds to read (default all)."""
    from .dictionary import book_model_without
    from .wholelines import _aksharas, trim_edges
    t0 = time.time()
    book = lib.get_book(book_id)
    cfg = lib.book_config(book)
    rows = checked_rows(lib, book_id)
    if not rows:
        raise LibraryError("No checked lines yet.")
    pages, n = fold_pages(rows, folds)
    with lib.session() as s:
        images = dict(s.execute(select(Line.id, Line.image).where(Line.id.in_([r[4] for r in rows]))).all())
    folder = lib.book_dir(book)
    lines: List[Dict] = []
    for k in (only if only is not None else range(n)):
        tested = [p[1] for p in pages[k::n]]
        lm = None
        if cfg.language_model:
            lm = book_model_without(lib, book_id, lib.left_out(book_id, tested))
            lm = lm if len(lm) else None
        by_name = readers(k)
        for r in (r for r in rows if r[0] in tested):
            rgb, _ = io_utils.load_image(folder / images[r[4]])
            line = {"fold": k, "page": r[1], "line": r[5], "truth": r[6], "chars": len(_chars(r[6])),
                    "read": {}, "wrong": {}}
            for name, reader in by_name.items():
                aks = trim_edges(_aksharas(reader(rgb), lm, cfg))
                line["read"][name] = "".join((" " if a[2] else "") + a[0] for a in aks)
                if lm is not None:
                    line["read"][f"{name}_lm"] = "".join((" " if a[2] else "") + (a[3] or a[0]) for a in aks)
            for name, text in line["read"].items():
                line["wrong"][name] = _distance(_chars(text), _chars(r[6]))
            lines.append(line)
        if progress:
            progress(f"fold {k + 1} of {n}: {len([x for x in lines if x['fold'] == k])} lines")
    names = list(lines[0]["read"]) if lines else []

    def cer(xs):
        chars = sum(x["chars"] for x in xs) or 1
        return {e: round(100 * sum(x["wrong"][e] for x in xs) / chars, 2) for e in names}
    return {"book": book_id, "folds": n, "lines": len(lines), "chars": sum(x["chars"] for x in lines),
            "seconds": round(time.time() - t0, 1), "cer": cer(lines),
            "per_fold": {k: cer([x for x in lines if x["fold"] == k]) for k in sorted({x["fold"] for x in lines})},
            "line_results": lines}


def _marked(text: str, truth: str) -> str:
    sm = difflib.SequenceMatcher(None, truth, text, autojunk=False)
    return "".join(html.escape(text[j1:j2]) if op == "equal" else f"<mark>{html.escape(text[j1:j2]) or '·'}</mark>"
                   for op, i1, i2, j1, j2 in sm.get_opcodes())


def score_page(result: Dict, title: str) -> str:
    """Every scored line: the checked text, then each reading with what differs from it marked."""
    names = list(result["cer"])
    head = "".join(f"<th>{html.escape(e)}</th>" for e in names)
    rows = []
    for x in result["line_results"]:
        reads = "".join(f"<div><span class=e>{html.escape(e)}</span> {_marked(x['read'][e], x['truth'])}</div>"
                        for e in names)
        wrong = "".join(f"<td class=n>{x['wrong'][e]}</td>" for e in names)
        rows.append(f"<tr><td>{html.escape(x['page'])} · {x['line']}<br><small>fold {x['fold'] + 1}</small></td>"
                    f"<td class=t><div class=g>{html.escape(x['truth'])}</div>{reads}</td>{wrong}</tr>")
    total = " · ".join(f"{e} {v}%" for e, v in result["cer"].items())
    folds = "".join(f"<li>fold {int(k) + 1}: " + " · ".join(f"{e} {v}%" for e, v in c.items()) + "</li>"
                    for k, c in result["per_fold"].items())
    return f"""<!doctype html><meta charset=utf-8><title>{html.escape(title)}</title>
<style>body{{font:15px system-ui;margin:16px}}td{{border-bottom:1px solid #ddd;padding:4px 8px;vertical-align:top}}
.t{{font:19px/1.5 "Noto Sans Devanagari",sans-serif}}.g{{font-weight:600}}.e{{font:12px system-ui;color:#777}}
mark{{background:#ffd27a}}.n{{text-align:right}}</style>
<h1>{html.escape(title)}</h1><p>Characters wrong ({result['lines']} lines, {result['chars']} characters): {html.escape(total)}</p>
<ul>{folds}</ul><p>Each line: the checked text (bold), then each reading; what differs from the checked text is marked.</p>
<table><tr><th>Page · line</th><th>Text</th>{head}</tr>{"".join(rows)}</table>"""

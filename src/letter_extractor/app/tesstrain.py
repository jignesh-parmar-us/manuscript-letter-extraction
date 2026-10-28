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

Nothing here changes the library's database: it reads lines and writes files in the given folders.

In the app (C30c): `train_book_model` trains a book's model on all its checked lines and keeps it in its reading
model folder (`model_folder`); any book can read with any trained model (`Config.ocr_model_book`, `book_model`).
"""
from __future__ import annotations

import difflib
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import time
import unicodedata
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image
from sqlalchemy import select

from .. import io_utils
from ..ocr.tesseract import find_tesseract, prepare_line, read_line
from .db import BOOK, Book, Line, now
from .library import Cancelled, Library, LibraryError, NotFound
from .linesearch import _chars, _distance, checked_rows, fold_pages

BORDER = 10                                  # white border around a line image, as `read_line` adds
MODEL = "book"                               # a book's trained model: <model folder>/book.traineddata (C30c)
TRAIN_PSM = 13                               # training reads a raw line; a trained model reads a line it read empty again so


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


def runner(cancel: Optional[Callable[[], bool]] = None) -> Callable:
    """A `run(cmd, env, log)` for `train_model` that stops the program when `cancel()` turns true (Cancelled)."""
    def run(cmd: Sequence[str], env: Dict[str, str], log) -> None:
        log.write("$ " + " ".join(str(c) for c in cmd) + "\n")
        log.flush()
        p = subprocess.Popen([str(c) for c in cmd], env=env, stdout=log, stderr=subprocess.STDOUT)
        while True:
            try:
                code = p.wait(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                if cancel and cancel():
                    p.kill()
                    p.wait()
                    raise Cancelled("Cancelled; the Tesseract model is as it was.")
        if code != 0:
            raise LibraryError(f"{Path(str(cmd[0])).name} failed (exit code {code}); see {log.name}.")
    return run


_run = runner()


def train_model(gt_dir: Path, work: Path, name: str, tools: Path, start: Path, epochs: int = 20,
                psm: int = TRAIN_PSM, learning_rate: float = 0.0001, ratio_train: float = 0.9, indic: bool = True,
                run: Callable = _run, progress: Optional[Callable[[str], None]] = None) -> Path:
    """Fine-tune the float model `start` (a .traineddata of tessdata_best, in a folder with `configs/lstm.train`)
    on the pairs in `gt_dir`, with the training programs in `tools` (`<tools>/bin`, langdata in
    `<tools>/langdata`: tools/tesstrain/setup.sh). Work files go to
    `work/<name>/`; returns `work/<name>.traineddata`. `run(cmd, env, log)` runs one program (tests, `runner`);
    `progress(message)` hears each step.
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
        say = progress or (lambda m: None)
        for i, gt in enumerate(pairs):
            if i % 20 == 0:
                say(f"training files: line {i + 1} of {len(pairs)}")
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
        say(f"training on {len(lstmf)} lines, {epochs} epochs")
        run(["lstmtraining", "--traineddata", proto, "--old_traineddata", start, "--continue_from",
             f"{unpacked}.lstm", "--learning_rate", str(learning_rate), "--model_output", out / "checkpoints" / name,
             "--train_listfile", out / "list.train", "--eval_listfile", out / "list.eval",
             "--max_iterations", str(-abs(epochs)), "--target_error_rate", "0.01"], env, log)
        model = work / f"{name}.traineddata"
        run(["lstmtraining", "--stop_training", "--continue_from", out / "checkpoints" / f"{name}_checkpoint",
             "--traineddata", proto, "--model_output", model], env, log)
    return model


# ---- in the app (C30c) --------------------------------------------------------------------------------

def default_tools() -> Path:
    """Where tools/tesstrain/setup.sh puts the training programs (the app setting `tesstrain_tools` when empty)."""
    return Path.home() / "tesstrain"


def model_folder(lib: Library, book: Book) -> Path:
    """Where a book's trained Tesseract model is kept: its reading model folder's `tesseract/` (C23)."""
    return lib.model_dir(book) / "tesseract"


def lines_signature(lib: Library, book_id: int) -> str:
    """The book's checked lines (line and text, as trained) as a hash: the model is out of date when it changes."""
    rows = sorted((r[4], gt_text(r[6])) for r in checked_rows(lib, book_id))
    return hashlib.sha1(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()


def model_info(lib: Library, book: Book) -> Optional[Dict]:
    """What the book's trained model learnt (meta.json), or None; `changed`: its checked lines changed since."""
    meta = model_folder(lib, book) / "meta.json"
    if not meta.is_file() or not (meta.parent / f"{MODEL}.traineddata").is_file():
        return None
    info = json.loads(meta.read_text(encoding="utf-8"))
    return {**{k: v for k, v in info.items() if k != "signature"}, "book_id": book.id, "book_name": book.name,
            "changed": info.get("signature") != lines_signature(lib, book.id)}


def trained_models(lib: Library) -> List[Dict]:
    """Every book's trained model (`model_info`), for choosing one in Reading setup."""
    out = []
    for row in lib.list_books(BOOK):
        info = model_info(lib, lib.get_book(row["id"]))
        if info:
            out.append(info)
    return out


def book_model(lib: Library, book: Book) -> Optional[Tuple[str, str, int]]:
    """The Tesseract model the book reads with (`ocr_model_book`): (folder for --tessdata-dir, language, PSM for
    a line read empty), or None for Standard."""
    src_id = lib.book_config(book).ocr_model_book
    if not src_id:
        return None
    try:
        src = lib.get_book(src_id)
    except NotFound:
        raise LibraryError("The book whose Tesseract model this book reads with is gone: choose another in "
                           "Reading setup.") from None
    folder = model_folder(lib, src)
    if not (folder / f"{MODEL}.traineddata").is_file():
        raise LibraryError(f"'{src.name}' has no trained Tesseract model (any more): train it, or choose another in "
                           "Reading setup.")
    meta = folder / "meta.json"
    psm = json.loads(meta.read_text(encoding="utf-8")).get("psm", TRAIN_PSM) if meta.is_file() else TRAIN_PSM
    return str(folder), MODEL, int(psm)


def start_model(lib: Library, book: Book, tools: Path, start_book: int = 0) -> Path:
    """The float model training starts from: another book's trained model, or the setup's `tessdata_best`
    model of the book's script (`ocr_langs` script/Devanagari: tessdata/Devanagari.traineddata)."""
    if start_book:
        if start_book == book.id:
            raise LibraryError("Start from Standard or from another book's model, not from this book's own.")
        src = lib.get_book(start_book)
        path = model_folder(lib, src) / f"{MODEL}.traineddata"
        if not path.is_file():
            raise LibraryError(f"'{src.name}' has no trained Tesseract model to start from.")
        return path
    script = lib.book_config(book).ocr_langs.split("+")[0].split("/")[-1]
    path = tools / "tessdata" / f"{script}.traineddata"
    if not path.is_file():
        raise LibraryError(f"No start model {path}: run tools/tesstrain/setup.sh (docs/INSTALL_TESSERACT.md).")
    return path


def _training_error(log: Path) -> Optional[float]:
    """The last training error (lstmtraining's "BCER train=1.300%") in the log, %."""
    found = re.findall(r"BCER train=([\d.]+)%", log.read_text(encoding="utf-8", errors="replace")) if log.is_file() else []
    return float(found[-1]) if found else None


def train_book_model(lib: Library, book_id: int, start_book: int = 0, tools: str = "",
                     progress: Optional[Callable[[str], None]] = None, cancel: Optional[Callable[[], bool]] = None,
                     run: Optional[Callable] = None) -> Dict:
    """Train the book's Tesseract model on all its checked lines (from Standard or `start_book`'s model) and keep it
    in `model_folder` (the old one stays until the new one is done). `run` replaces the programs (tests)."""
    t0 = time.time()
    book = lib.get_book(book_id)
    lib.need_kind(book, BOOK, "a Tesseract model")
    cfg = lib.book_config(book)
    tools_dir = Path(tools).expanduser() if tools else default_tools()
    if run is None and not (tools_dir / "bin" / "lstmtraining").is_file():
        raise LibraryError(f"The Tesseract training programs are not in {tools_dir}: run tools/tesstrain/setup.sh "
                           "(docs/INSTALL_TESSERACT.md), or set their folder in the app settings.")
    start = start_model(lib, book, tools_dir, start_book)
    say = progress or (lambda m: None)
    signature = lines_signature(lib, book_id)
    folder = model_folder(lib, book)
    work = folder / "work"
    if work.exists():
        shutil.rmtree(work)
    say("exporting the checked lines")
    exported = export_lines(lib, book_id, work / "lines", folds=1)
    model = train_model(work / "lines" / "all", work, MODEL, tools_dir, start, epochs=cfg.tesstrain_epochs,
                        run=run or runner(cancel), progress=say)
    if cancel and cancel():
        raise Cancelled("Cancelled; the Tesseract model is as it was.")
    say("keeping the model")
    shutil.copyfile(model, folder / f"{MODEL}.traineddata.new")
    os.replace(folder / f"{MODEL}.traineddata.new", folder / f"{MODEL}.traineddata")
    if (start.parent / "configs").is_dir():              # reading with hocr looks for configs/ in the model's folder
        shutil.copytree(start.parent / "configs", folder / "configs", dirs_exist_ok=True)
    log = work / MODEL / "training.log"
    if log.is_file():
        shutil.copyfile(log, folder / "training.log")
    start_name = lib.get_book(start_book).name if start_book else "Standard"
    info = {"trained_at": now().isoformat(), "lines": exported["lines"], "epochs": cfg.tesstrain_epochs,
            "start_book": start_book, "start_name": start_name, "psm": TRAIN_PSM,
            "training_error": _training_error(log), "seconds": round(time.time() - t0, 1), "signature": signature}
    (folder / "meta.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    return {k: v for k, v in info.items() if k != "signature"}


# ---- scoring ----------------------------------------------------------------------------------------

def model_reader(cfg, tessdata_dir: str, lang: str, tesseract_path: str = "", psm: Optional[int] = None,
                 fallback_psm: Optional[int] = None) -> Callable:
    """A line reader like the Whole-lines route's (`suggest.tesseract_reader`), with the model `lang` of the
    folder `tessdata_dir` ("" = the installed models and the book's `ocr_langs`), at page segmentation mode `psm`
    (None = the book's `ocr_psm`). A line read empty is read again at `fallback_psm` (None = not): a trained model
    reads some lines empty at 7 but not at 13, the mode it learnt in (book 8: 4 of 119 lines)."""
    engine = find_tesseract(tesseract_path, tessdata_dir)
    langs = lang or cfg.ocr_langs
    engine.check_langs(langs)
    psm = cfg.ocr_psm if psm is None else psm

    def read(rgb, mode):
        return read_line(rgb, engine, langs=langs, psm=mode, target_height=cfg.ocr_letter_height, border=BORDER,
                         env={"OMP_THREAD_LIMIT": "1"})

    def reader(rgb):
        reading = read(rgb, psm)
        if fallback_psm is not None and fallback_psm != psm and not reading.text.strip():
            reading = read(rgb, fallback_psm)
        return reading
    return reader


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
            line = {"fold": k, "page": r[1], "line": r[5], "stem": _stem(r[0], r[5]), "truth": r[6],
                    "chars": len(_chars(r[6])), "read": {}, "wrong": {}, "aks": {}}
            for name, reader in by_name.items():
                aks = trim_edges(_aksharas(reader(rgb), lm, cfg))
                line["aks"][name] = [[a[0], a[1], a[2]] for a in aks]         # text, confidence, space before
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


# ---- likely wrong checked texts ----------------------------------------------------------------------

def suspects(result: Dict, name: str = "tuned") -> List[Dict]:
    """The places where the reader `name` reads a line differently from its checked text, the most confident
    first. A fold's model never saw its fold's lines, so where it is sure and disagrees, the checked text may be
    wrong. Confidence: the lowest of the aksharas read in the place, or, where the reading leaves something out,
    of the two beside it. Each: fold, page, line, stem, the checked text and the reading with the place in each
    (`at` = [start, end] in `truth` and in `read`), and the confidence."""
    out = []
    for x in result["line_results"]:
        aks = x.get("aks", {}).get(name)
        if aks is None:
            continue
        read, owner = "", []                                      # owner: the akshara of each character read
        for i, (text, _, space) in enumerate(aks):
            if space:
                read, owner = read + " ", owner + [None]
            read, owner = read + text, owner + [i] * len(text)
        truth = gt_text(x["truth"])
        sm = difflib.SequenceMatcher(None, truth, read, autojunk=False)
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "equal":
                continue
            near = owner[j1:j2] if j2 > j1 else owner[max(0, j1 - 1):j1 + 1]
            confs = [aks[o][1] for o in near if o is not None]
            out.append({"fold": x["fold"], "page": x["page"], "line": x["line"], "stem": x.get("stem", ""),
                        "truth": truth, "read": read, "at": [[i1, i2], [j1, j2]],
                        "conf": min(confs) if confs else 0.0})
    return sorted(out, key=lambda s: (-s["conf"], s["page"], s["line"]))


def _span(text: str, i: int, j: int) -> str:
    return f"{html.escape(text[:i])}<mark>{html.escape(text[i:j]) or '·'}</mark>{html.escape(text[j:])}"


def suspects_page(found: List[Dict], title: str, images: str = "all") -> str:
    """The places of `suspects`, each with the line's picture (`<images>/<stem>.png`, the export's) to fix the
    checked text by eye in the app (Read Book → Line truth)."""
    rows = "".join(
        f"<tr><td class=n>{s['conf']:.0f}</td><td>{html.escape(s['page'])} · {s['line']}<br>"
        f"<small>fold {s['fold'] + 1}</small></td><td><img src=\"{html.escape(images)}/{html.escape(s['stem'])}.png\">"
        f"<div class=t><span class=e>checked</span> {_span(s['truth'], *s['at'][0])}</div>"
        f"<div class=t><span class=e>model</span> {_span(s['read'], *s['at'][1])}</div></td></tr>" for s in found)
    return f"""<!doctype html><meta charset=utf-8><title>{html.escape(title)}</title>
<style>body{{font:15px system-ui;margin:16px}}td{{border-bottom:1px solid #ddd;padding:6px 8px;vertical-align:top}}
.t{{font:19px/1.5 "Noto Sans Devanagari",sans-serif}}.e{{font:12px system-ui;color:#777}}img{{max-width:100%}}
mark{{background:#ffd27a}}.n{{text-align:right}}</style>
<h1>{html.escape(title)}</h1><p>{len(found)} places where the fold's model, which never saw the line, reads differently
from the checked text. The model's confidence first: high means it was sure, so the checked text is worth a look.
Fix real mistakes in the app (Read Book → Line truth).</p>
<table><tr><th>Sure</th><th>Page · line</th><th>Picture, checked text, model's reading</th></tr>{rows}</table>"""

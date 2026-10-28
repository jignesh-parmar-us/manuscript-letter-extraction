"""C30a: fine-tune Tesseract on one fold's training lines (or on every line: --fold all).

Usage: PYTHONPATH=src .venv/bin/python tools/tesstrain/train.py --data <dir> --fold 0 [--epochs 20]

<dir> is export.py's output. Uses the training programs and the start model of tools/tesstrain/setup.sh
(--tools, default ~/tesstrain). Writes <dir>/models/fold<k>.traineddata (work files and training.log in
<dir>/work/fold<k>/). A heavy job: takes the heavy-job lock, lower priority (docs/plans/done/SPEED_PLAN.md, S1).
"""
import argparse
import shutil
import time
from pathlib import Path

from letter_extractor.app.tesstrain import train_model
from letter_extractor.heavy import heavy_lock, lower_priority


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--fold", required=True, help="a fold number, or 'all'")
    ap.add_argument("--tools", default=str(Path.home() / "tesstrain"))
    ap.add_argument("--start", default="", help="start model (default <tools>/tessdata/Devanagari.traineddata)")
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--learning-rate", type=float, default=0.0001)
    ap.add_argument("--psm", type=int, default=13, help="13: a raw line (7 makes no .lstmf)")
    a = ap.parse_args()
    data, tools = Path(a.data), Path(a.tools)
    name = "all" if a.fold == "all" else f"fold{int(a.fold)}"
    gt = data / "all" if a.fold == "all" else data / name / "train"
    start = Path(a.start) if a.start else tools / "tessdata" / "Devanagari.traineddata"
    lower_priority()
    with heavy_lock(f"tesseract training {name} ({data})"):
        t = time.time()
        model = train_model(gt, data / "work", name, tools, start, epochs=a.epochs, psm=a.psm,
                            learning_rate=a.learning_rate)
        (data / "models").mkdir(exist_ok=True)
        shutil.copyfile(model, data / "models" / f"{name}.traineddata")
        # reading with --tessdata-dir models/ looks there for the configs too (hocr)
        shutil.copytree(start.parent / "configs", data / "models" / "configs", dirs_exist_ok=True)
    print(f"{name}: {data / 'models' / (name + '.traineddata')} in {time.time() - t:.0f} s")


if __name__ == "__main__":
    main()

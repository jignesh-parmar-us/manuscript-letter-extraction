# Harness: trying changes to our reader quickly and fairly

Our reader (Text → Whole lines (our reader), `docs/SEGMENTATION_PLAN.md`) is measured fold-fair on the
checked lines: for each of 4 groups of pages, a reader trained without those pages reads them. Done
from scratch that takes about two hours per idea. Most of the time goes into the features of the
training letters and of every window of every checked line, which are the same for every idea about
the reader or the search. The harness computes them once per fold (the *cache*) and then tries a
variant in minutes.

Always on a **copy** of the library, never the real one (`CLAUDE.md`, data safety).

## Steps

```zsh
# 1. a copy of the library (database by SQLite backup, the book's folder, the word lists)
tools/harness/copy_library.sh ~/harness/libcopy

# 2. the cache, one process per fold (about 20 minutes; about 5 GB on disk)
mkdir -p ~/harness/cache
for k in 0 1 2 3; do
  PYTHONPATH=src .venv/bin/python tools/harness/build.py --library ~/harness/libcopy --cache ~/harness/cache --fold $k > ~/harness/cache/build$k.log 2>&1 &
done; wait

# 3. variants (each about 20-40 minutes; run at most two at a time on 8 GB of memory)
PYTHONPATH=src .venv/bin/python tools/harness/run.py --library ~/harness/libcopy --cache ~/harness/cache --name base --lm 0.35 0.5
PYTHONPATH=src .venv/bin/python tools/harness/run.py --library ~/harness/libcopy --cache ~/harness/cache --name generated --unlined
```

`run.py` prints the characters wrong (all checked lines, and the newest pages), the most common
confusions, and writes `<cache>/<name>_lm<weight>.html`: every checked line with its checked text, our
reader's and Tesseract's reading, the differences marked, to check by eye.

Options: `--lm` (weights to try; the readers are trained once), `--hidden 384` (a network instead of the
linear reader), `--epochs`, `--seed` (to see how much a result moves by chance), `--no-corrections`
(without learning from the other folds' checked lines), `--unlined` (also the reviewed letters on no
line, System generated), `--unreviewed-generated` (with `--unlined`: also unreviewed generated letters).

## Rebuild the cache when

- the groups, labels or checked lines changed (a new copy first), or
- a change touches the features (`ocr/features.py`), the line's ink (`linesearch._line_ink`, borders) or
  the windows (`segment.line_windows`, `SearchSettings.step` / widths).

A change to the reader, the training or the search needs no rebuild.

## What it reproduces

The app's Retrain and Measure: the same training set (`linesearch._training_set`), learning from
corrections (`segment.align`, `linesearch._with_corrections`), reader (`ocr.reader.LetterReader`), search
(`segment.search`) and scoring (`linesearch._chars`, `_distance`). Results go in `docs/TUNING_PHASE2.md`.

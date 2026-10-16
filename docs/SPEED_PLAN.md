# Speed plan: tests, Measure and the reader in minutes, not hours

Comes **before Phase 3** (built from `docs/implementation_plan_phase3_lean.md`): every Phase 3 chunk is checked with the
tests and with Measure, so they must be fast first.

**Status:** S1–S4 are built (2026-10-16); S2 missed its `fast` target (see S2). Next: S5, the heavy session,
when the user chooses (questions 7–9 still open; the defaults chosen are in S4). Written 2026-10-15; the questions were answered the same day (section 5) and
the plan cut down to a lean scope the same day (section 6). S4 (faster reading and retraining) added the
same day; its questions are open (section 5).

## 1. Where the time goes today (checked 2026-10-15)

| What | Today | Why |
|---|---|---|
| Backend tests, all 375 | about **6 minutes** (CLAUDE.md says 12) | they run one after the other on **one** of the 8 cores. No single test is slow: the slowest are 10–17 s (the sample-page tests), the slowest modules 10–35 s. |
| Measure in the app (Text → Whole lines (our reader)) | **42 minutes** (`TUNING_PHASE2.md`) | the same work done 4 times, once per fold (S3) |
| Harness: build the cache | about **20 minutes per fold**, about 5 GB on disk | the same as Measure |
| Harness: try one idea | **20–40 minutes**, at most two at a time on 8 GB | reads every checked line again, at about 6.6 s per line |
| A library copy for experiments | 3.2 GB per copy | it also copies `exports/` (726 MB) and `read/` (1.3 GB) with rsync |

And what makes the computer slow on top of that:

- **Jobs run on top of each other.** Tests, harness folds and the app run at the same time. Each Python
  process lets NumPy (Accelerate) and OpenCV use all 8 cores, so 4 jobs make 32 threads fighting for 8
  cores, and with 8 GB of memory the computer starts swapping.
- **Left-over workers.** The pipeline cuts pages in a pool of worker processes (`pipeline.py`, "spawn").
  When the run that started them is stopped or dies, the workers can keep running on their own and keep
  using the CPU. Seen on 2026-10-15: 4 such workers were still running after their test run was stopped.

## 2. Working rule while implementing

- **No heavy runs while implementing:** no Measure, no harness, no full test suite. Only the tests of the
  module changed (seconds), and `fast` once S2 exists.
- **Equality tests instead of measuring:** a change that must give the same numbers is proven by a small
  test on the synthetic test book (old and new code give the same rows, windows and masks, bit for bit).
- **Heavy runs only when the user asks**, one at a time (S1's lock), at a time the user chooses (S5).

## 3. The chunks

Each chunk is one commit, with a test.

### S1. Stop the CPU fights (about 1 h)

What makes the computer slow today, fixed first, because it is cheap and helps at once:

- **One thread per process** for NumPy and OpenCV in tests, Measure, the harness and the pipeline's
  workers (`VECLIB_MAXIMUM_THREADS=1`, `OMP_NUM_THREADS=1`, `cv2.setNumThreads(1)`).
- **One heavy job at a time:** tests (`full`), the harness and the app's Measure take a lock file
  (`~/.manuscript-letters-heavy.lock`, with the process id and what it is). A second one says what is
  running and waits; a lock whose process is gone is taken over.
- **No left-over workers:** the pipeline's workers stop themselves when their parent process ends; a
  heavy job first stops workers left by a run that is gone. `tools/cleanup.sh` lists left-over runs
  (tests, harness, Measure) and old scratchpad copies and caches, and stops / deletes them after showing
  what it will do.
- Heavy jobs run at lower priority (`nice`), so the app and the editor stay responsive.
- **Library copies in seconds:** `tools/harness/copy_library.sh` makes APFS clones (`cp -c`: seconds, and
  no extra disk space until a file changes) instead of rsync copies, and leaves out `exports/` and
  `headline-backup/`. The database is still copied with SQLite's backup (safe while the app runs).

**Done when:** two heavy jobs started together run one after the other; killing a test run leaves no
Python process behind; a copy of the library takes seconds.

**Built (2026-10-16)** in `src/letter_extractor/heavy.py`, tests `tests/test_heavy.py`. What differs from the plan:

- **One thread** is set when the package is imported (`letter_extractor/__init__.py`, before NumPy): the
  thread variables of Accelerate, OpenMP, OpenBLAS and `OPENCV_FOR_THREADS_NUM`, each only if not already set.
  So it covers the app as well: Measure and Retrain run in the app's process, and NumPy cannot change its
  thread count after it is loaded. Processes started from it (page workers, Tesseract) inherit it.
- **The lock** is taken by the app's Measure **and Retrain** (Retrain is as heavy: 28 min), `tools/harness/build.py`
  and `run.py`, and (S2) the full test suite. In the app a waiting job shows "waiting: ... is running" and
  can be cancelled. A process started by the lock holder (`MANUSCRIPT_HEAVY_HELD`: the test workers of S2)
  runs inside its lock.
- **Left-over workers:** on macOS a venv's python runs as the framework's `Python.app`, so workers are found
  by the base installation's path and `from multiprocessing.` with parent process 1. Every page worker
  watches its parent (every 2 s) and stops itself when it is gone.
- **Lower priority:** the page workers and the harness run with `nice 10`; the app's own Measure runs in a
  thread of the app, which macOS cannot give a lower priority (S4b's workers will be niced).
- **Copies:** APFS clones, but one clone per file: book 6 has about 150,000 letter pictures, so a copy takes
  **about 40 s** (6 folders at once; 71 s one by one), not seconds, and no disk space. `exports/` and
  `headline-backup/` are left out. The database copy is 5 s.

### S2. Backend tests in about 1.5–2 minutes (1.5–2 h)

- `tools/test_parallel.py` (no new package): runs the test modules in 4 processes at once, the slowest
  modules first, and prints one summary (passed, failed, the slowest tests). Each process has one thread
  (S1), so 4 processes use 4 cores and leave the rest for the app.
- The sample pages (`samples/page1.jpg`, `page2.jpg`) are prepared once per test run and shared by the
  sample-page tests (lines, letters, pieces, grouping), instead of once per test.
- Two levels:
  - `fast`: everything except the sample-page and end-to-end tests: while implementing and before a
    commit, under 1 minute.
  - `full`: all of them: at the end of a plan or before a merge, when the user asks (heavy, takes S1's lock).
- CLAUDE.md gets the new commands and times.

**Done when:** `full` passes in at most 2 minutes, `fast` in at most 1, the same 375 tests as before.

**Built (2026-10-16)**, test `tests/test_parallel_runner.py`. What differs from the plan, and the numbers:

- **One task per test class**, not per module: `test_book_parts` alone (77 s) was the longest path. The
  classes are read from the files without importing them; their times are kept in `tests/.durations.json`
  (not in git) and the slowest start first.
- **Not `multiprocessing.Pool`**: its workers are daemons and may not start the page workers that capture uses;
  a `ProcessPoolExecutor` (spawn) with `heavy.worker_init` (one thread, nice, stops with the run).
- **Pages cut in the test process** (`LETTER_EXTRACTOR_WORKERS=1` in the runner's processes): starting a pool of
  page workers costs about 3 s per worker on this Mac (importing NumPy, OpenCV, FastAPI), more than cutting a
  synthetic page. A test cutting pages in 2 real worker processes (`test_folder`,
  `test_pages_are_cut_the_same_in_worker_processes`) keeps that path tested.
- **Shared sample pages:** `tests/samplepages.py` cuts page1 and page2 once per process; the sample-page
  classes (lines, pieces, letters, grouping, prepare: `LEVEL = "samples"`) run in one task. The end-to-end
  class `test_library.SampleBookTests` has `LEVEL = "full"`.
- **Tests:** 382 after S1 (375 + 7), 386 with this chunk's 4; `fast` leaves out 7.
- **Times (measured on a busy computer: Spotlight indexing, load 6-15):** `full` 122 s (382 tests, one run);
  `fast` 112 s. **`fast` is not under 1 minute.** The plan assumed the sample-page tests were the slow part;
  they are about 40 s of CPU out of about 320 s. The rest is spread over the app tests, most of which capture
  a synthetic book or copy one (`appbook`), 5-15 s per class. Getting `fast` under a minute needs those
  tests to share their captured books (e.g. `test_book_parts.ReadBookTests`, 44 s, captures in every
  `setUp`): a later chunk, if wanted, not done here. `full` and `fast` to be timed again in S5 on a quiet computer.

### S3. The Measure cache: each letter, line and mask computed once (3–4 h)

One chunk for three things that touch the same code (`linesearch._training_set`, `_learn_corrections`,
`measure`, and the harness's `build.py` / `run.py`).

#### a. Each letter's features once, kept (changes the numbers once)

**What happens today.** To train the reader, `linesearch._training_set` turns each reviewed letter on the
Training Data pages into rows of numbers (features: `ocr/features.py`, 1,303 numbers per row: the
letter's picture at 20 x 20, its stroke directions, its size). Per letter it makes:

| Rows | What | How many |
|---|---|---|
| "is this letter" | the cut letter itself; the window at its exact place on the line (with the neighbours' ink); the window shifted a little left and a little right (3–10% of its width, random) | 4 |
| "is this letter" | **varied copies**: the letter slightly rotated, slanted, thicker or thinner (random) | 3 to 30: more for a label with few letters (fairness rule: small groups topped up) |
| "not a letter" | the left half, the right half, the letter with the next one, the window shifted by a quarter to a half (random) | 4–5 |

Measure does this for **every fold**, with only the pages under test left out. With 4 folds, it opens each
letter's picture and computes its rows 4 times, and about three quarters of that work is the same each time.
A fold differs from another only in **which letters it may use**, not in what a letter's rows are.

**What changes.**

1. **A letter's rows depend only on the letter, not on the fold.** Today the random numbers (the shift,
   the rotation of a varied copy) come from one random stream for the whole training set, so a letter's
   rows depend on which letters came before it, which differs per fold. Instead, every random choice gets
   its own seed from (seed, the letter's sample id, which copy). Then the letter's rows are the same in
   every fold and in every run, so they can be kept.
2. **The rows are kept on disk:** the feature store, in `<book folder>/line-search/features/` (in the
   copy's folder when the harness runs). For each letter: its rows and a key that says when they are out of
   date: the mask file's content, the letter's box, the other letters on its line (their ink is in its
   windows), its page's line spacing, and a version number of the feature code.
3. **A fold only picks rows.** Measure reads the store, leaves out the rows of the letters on the tested
   pages, and attaches the **labels and review status read fresh from the database**. A label is not in
   the store, so relabelling or reviewing a group needs no recomputing; nothing about labels can go stale.
4. **Varied copies are made as needed.** Copy number k of a letter always has the same seed, so the store
   holds as many copies as were needed so far; a fold that needs more (its label lost letters to the
   tested pages, so it needs more copies to top it up) adds them and they are kept.
5. **Only what changed is computed.** After a review session, a new page or a recut line, only those
   letters' keys change; the rest come from the store. Retrain (not only Measure) uses the same store.

**What it costs.** About 9,000 letters x about 14 rows x 1,303 numbers: about 650 MB in 32-bit numbers,
**about 330 MB in 16-bit**, the format the store uses (an equality test checks the reader's numbers are
unchanged by it). It is a cache: deleting the folder is always safe; it is built again. It is not reviewed
data (CLAUDE.md data safety).

**The one-time change in the numbers.** Because the random choices change (point 1), the reader learns
from slightly different varied copies and shifts, so CER moves a little (the readers' random training
moved it by about 0.6 points in stage 5). This is measured in S5, before/after, fold-fair on the checked
lines, with the line-by-line page. After S3 the numbers no longer move between runs of the same library.

**Fairness rule:** unchanged. No row is weighted by group size; the number of varied copies per label is
the same top-up as today, decided per fold from that fold's letters.

**Phase 3 (C24, datasets):** the store is keyed by sample and mask content, not by book folder or page
name, so moving Training Data into datasets does not make it stale.

#### b. The checked lines cut into windows once (same numbers)

Today a checked line is cut into windows (candidate letter-sized pieces, each with its features) when it
is read in its own fold, and again in each of the other three folds when the reader learns from the
corrections (`_learn_corrections`): 4 times. The windows depend on the typical letter width, which differs
a little per fold. Now: each line is cut once with the widest range of window widths of the 4 folds, kept
(keyed like a. by the line's letters and the feature version), and each fold drops the windows outside its
own range. The same windows as today.

**What is kept (changed 2026-10-15):** the windows' places (candidate boundaries and each window's
(i, j, width)) and the features computed **within one Measure run** (in memory, shared by its folds), not
the features on disk. Kept on disk, the features would be about 7,600 windows x 1,303 numbers per line:
about 2 GB for 119 checked lines even in 16-bit. With S4a/b the features of a line are cheap to compute
again.

#### c. Letter pictures from one file (same numbers)

Today every letter's mask is a PNG opened one by one (`samples._sample_mask`), about 9,000 per fold plus all
letters of every training line. Now they are packed into one file per book (rebuilt for the letters that
changed), read once.

#### d. Quick Measure (screening only)

`Measure --quick` (and `run.py --quick`): 2 of the 4 folds, about half the time, to throw out bad ideas
early. **Its numbers are never quoted as results**; a change is judged only on the full 4-fold Measure
(CLAUDE.md, measuring reading quality).

**Printed and handwritten:** the same code path for both. The checked lines exist only for book 6
(printed), so S5's numbers are printed only; it says so.

**Done when** (equality and logic tests on the synthetic test book, no heavy runs): a letter's rows are the
same in every fold; a second training on an unchanged book computes no features; reviewing or relabelling a
group computes none either; recutting one line computes only that line's letters; b and c give exactly the
rows and windows of today's code.

#### Built (2026-10-16)

Code: `app/linestore.py` (the mask pack and the feature store), `linesearch._training_set` / `_learn_folds` /
`measure`, `segment.line_windows_range` / `narrow`; tests `tests/test_linestore.py` (11, on the synthetic book).
What differs from the plan:

- **Rows kept exactly, not in 16-bit.** A row's picture part is a whole number / 255, so it is kept as 8 bits
  (exact); the stroke directions and the size as 32-bit. About 460 MB for book 6 instead of 330, and rows from
  the store are bit for bit the rows computed (tested), so the one-time change of the numbers is only the seeds.
- **`features()` of one letter now uses `features_batch`.** The single-letter HOG normalised its blocks with
  `np.linalg.norm`, which goes through Accelerate and can round the last bit differently depending on where
  the array lies in memory: the same letter gave rows up to 6e-8 apart from one call to the next. Now one
  letter's features are reproducible and equal to a window's. This moves every letter's row by at most 1 ulp
  (part of the one-time change; also the C14 letter readers' features, by the same 1 ulp). The grouping
  fingerprints (`letter_extractor.features`) are unchanged.
- **One seed for all folds.** Measure trained fold k with seed k; with per-letter seeds the rows of all folds
  come from seed 0, or they could not be shared. The reader's own random start is unchanged (seed 0).
- **The store key** (`_letter_key`): the feature version, the seed, the letter's line spacing, its id and box,
  and the line's letters (ids, boxes, mask contents). Labels and review status are never in it. Retrain also
  forgets the letters no longer trained on; a fold of a Measure does not.
- **Varied copies** are made per letter up to the number its label needs in that fold and kept.
- **Checked lines' windows: twice per Measure, not once.** Keeping every line's window features for all folds
  would take about 4.7 GB of memory (119 lines x 7,600 windows x 1,303 numbers), too much for 8 GB. Measure is
  reorganised instead: (1) the base reader of every fold, (2) one pass over the checked lines: each cut into
  windows once, with the widest window range of the folds that learn from it, each fold taking its own
  (`narrow`: the same windows bit for bit, tested), (3) each fold's final reader reads its own lines (cut again).
  So 2 cuts per line instead of 4. Nothing is kept on disk for the windows (their places are cheap to compute).
- **A memory leak fixed on the way:** each row learned from a checked line was a view into the line's whole
  window array, so all lines' window features (up to about 4.7 GB) stayed in memory until the fit. They are
  copied now (same values).
- **Mask pack** (`masks.npz`): every mask the training opens (training lines, checked lines), read again when
  its PNG changed (path, size, time); a hash of its content goes into the letter keys. Reading a page with
  Read Book still opens the PNGs (S4b looks at reading).
- **Quick Measure** reads the first half of the folds (2 of 4) and trains only those; kept in
  `measure-quick.json`, so it never replaces the last full Measure. In the app: **Quick measure**, its result
  marked "screening only". `run.py --quick` trains and reads folds 0 and 1.
- **Phase 3 (C24):** the store is keyed by sample id inside the book folder; moving Training Data into
  datasets will make it cold once (built again), never wrong.
- **Not measured yet** (S5): the times of a cold and a warm Measure and Retrain, and the one-time CER change.

### S4. Faster reading and retraining (added 2026-10-15, about 3–4 h)

Measure got faster in S3; this chunk makes the reader itself faster: **Retrain** (Text → Whole lines (our
reader)) and **reading** pages with it.

**Where the time goes (checked 2026-10-15, timings on synthetic data of the book's size, one thread):**

| What | Today | Why |
|---|---|---|
| Retrain, book 6 | **1,709 s (28 min)**: 9,050 letters, 497 labels, 119 checked lines (`line-search/meta.json`) | estimated split: fitting the reader twice (15 + 40 epochs, about 115,000 rows, about 900 batches of 128 per epoch at 20–29 ms) **17–20 min**; the checked lines' windows (`_learn_corrections`) 7–8 min; the letters' rows (about 110,000 `features()` calls at 1.4 ms) and opening the PNGs about 3 min |
| One training batch | 20–29 ms | the matrix products about 11 ms, the Adam update of all 650,000 weights about 14 ms (new arrays at every step) |
| Reading | **6.6 s per line** (`TUNING_PHASE2.md`, stage 5) | about 95% is the window features (about 7,600 windows a line); the reader (one matrix product) and the beam search are under 0.5 s together. Each window's ink is searched three times (`_crop`, `normalize`, the size), HOG counts in float64 |

Only 2% of a line's windows are the same crop, so skipping repeated windows is not worth it.

#### a. Faster window features (same numbers)

`features_batch` and `line_windows`: a window's ink box is found once (in `_crop`) and passed on, so
`normalize` and the size part do not search it again; HOG with fewer passes over the pixels. About 1.3–1.5x
on reading and on learning from the checked lines. An equality test checks the rows are identical to
today's, bit for bit, on the synthetic test book's lines.

#### b. Lines in parallel (same numbers)

Reading a page (`_read_lines`, `search_book`) and learning from the checked lines (`_learn_corrections`:
each line's windows and features; the base reader's probabilities and `align` stay in the main process)
use a pool of 3 worker processes, one thread each (S1), stopped with their parent (S1). The reader is
small (about 2.6 MB), so each worker keeps its own copy. Results are put back in line order, so the text,
the training rows and their order are the same as one after the other. About 2.5–3x in wall-clock time on
the 4-core i5.

#### c. Adam with fewer passes (same numbers, checked)

`LetterReader.train`: the moments and the step updated in place with buffers made once, the same formula
in the same order. About 1.2–1.3x on training. An equality test compares the weights after a few epochs
with today's code; if they are not identical bit for bit, the commit says how far apart they are and S5
measures it with c, d, e.

#### d. Bigger batches (changes the numbers: measured in S5)

Training batches of 512 instead of 128 (fewer Adam steps per epoch; the learning rate checked in S5). About
1.7x on the fit, the biggest part of a retrain. A setting (`batch`), not hardcoded.

#### e. Fewer epochs for the base reader (changes the numbers: measured in S5)

The base reader (`BASE_EPOCHS = 15`) only cuts the checked lines into their aksharas. Tried with 5 and 8 in
S5; kept only if CER does not get worse. Saves about 2–4 minutes.

**Not done:** reusing the last training's cuts of unchanged checked lines to skip the base reader. It
would save more, but Retrain would no longer match what Measure tests, and in a fold the cuts would come
from a reader that saw the tested pages' letters (not fold-fair).

**Printed and handwritten:** the same code path for both.

**Fairness rule:** unchanged; the rows, their weights and the top-up are as in S3.

**Done when** (no heavy runs): a's rows and b's readings and training rows equal today's on the synthetic
test book; c's check written; d and e are settings ready for S5; killing a parallel read leaves no worker.

**Expected** (estimates, confirmed in S5):

| | Today | a–c + S3 | a–e + S3 |
|---|---|---|---|
| Retrain | 28 min | about 15 min | about 8–10 min |
| Reading | 6.6 s per line | about 1.5–2 s per line | about 1.5–2 s per line |

#### Built (2026-10-16)

Tests `tests/test_fast_reader.py` (9; the 3 that start worker processes run in `full` only). What was done and
how it differs from the plan:

- **a. Window features (same numbers, tested bit for bit against the code before):** a window's ink box comes
  from the line's per-column ink counts and top / bottom rows (`segment._Ink`), not from searching its pixels;
  the crop is passed on as tight, so `normalize` and the size part do not search it again; `hog_batch` computes
  the 3 x 3 Sobel gradients for all windows at once in NumPy (on 8-bit images every gradient is a small whole
  number, exact in any order, so equal to `cv2.Sobel`'s) and normalises the 25 blocks in one step. On two lines
  of `samples/page1.jpg` (5,600–9,000 windows): **1.8–2.05x**. The blur and the two resizes per window are still
  one OpenCV call each (about a third of what is left).
- **b. Lines in parallel (same results, tested):** `segment.LinePool`, 3 worker processes by default (book
  setting `line_workers`; question 7 open: 3 or 4), one thread each, lower priority, stopped with their parent
  (tested by killing the parent). Reading (`search_book`: one pool for the book; Measure: one per fold, holding
  that fold's reader and language model) and learning from the checked lines (`_learn_folds`: the windows in
  the workers, the base readers' probabilities and `align` in the main process). Results in line order.
  Workers start only for **8 lines or more at once** (`MIN_PARALLEL_LINES`): starting one costs about 3 s here,
  about one line's work, so Read this page on a short page and the tests stay in one process. 9 sample lines
  with 3 workers, the start included: **1.99x**. `LETTER_EXTRACTOR_WORKERS` (the test runner: 1) caps it too.
- **c. Adam in place (same numbers, tested bit for bit):** `reader.adam_step`, buffers made once. With the
  linear reader (the one used) on 6,000 rows: **1.5–1.6x** on training; with a hidden layer no gain (there the
  matrix products dominate).
- **d, e. Settings, defaults unchanged:** `line_batch` (128) and `line_base_epochs` (15) in the book's settings,
  used by Retrain and Measure; `run.py --batch` / `--base-epochs` for the harness. Not tried yet (S5).
- **Measured on a busy computer** (load 6–18: VS Code, the animated wallpaper, Spotlight), so the seconds
  above are only ratios; S5 times Retrain and reading on a quiet one.

### S5. One heavy session, when the user chooses (about 2.5 h on the computer, mostly unattended)

On a copy of the library in the scratchpad (S1's clone), one job after the other:

1. **Before:** Measure with the code before the speed plan (commit `89e16b3`), once: about 45 minutes.
2. **After:** Measure with the new code, twice: cold (builds the store) and warm (nothing changed), about
   15 minutes together. The warm run is profiled (cProfile) to see where the rest of the time goes.
3. **S4d and S4e:** Measure warm with batches of 512, then with the base reader at 5 and 8 epochs (about
   10 minutes each). Kept only if CER does not get worse; the batch's learning rate is checked here.
4. **Retrain and reading timed:** one Retrain of book 6 and one Read Book page read, before (`89e16b3`) and
   after, seconds per step.
5. The full test suite once: about 2 minutes.

Reported: before/after CER (ours, Tesseract, Tesseract + language model), the line-by-line page, the
seconds per step, in `docs/TUNING_PHASE2.md`. If the numbers look wrong, each commit of the speed plan is
measured in turn to find which one.

## 4. Targets

| | Today | After S1–S4 |
|---|---|---|
| Backend tests | about 6 min, 1 core | about 2 min (S2: `full` 122 s; `fast` 112 s, not under 1 min) |
| App Measure | 42 min | about 10 min the first time, about 5 min when nothing changed |
| A library copy | 3.2 GB, minutes | about 40 s, almost no disk (S1) |
| Running two heavy jobs by mistake | both slow, swapping | the second waits |
| Retrain (book 6) | 28 min | about 15 min; about 8–10 min if S4d/e are kept |
| Reading | 6.6 s per line | about 1.5–2 s per line |

## 5. Questions answered (2026-10-15)

1. The one-time change of the numbers from per-letter seeds (S3a), measured before/after: **yes**.
2. A quick 2-fold Measure for screening, never quoted as a result: **yes**.
3. Where the plan lives: **this file**, done before Phase 3.
4. No Measure and no full test suite while implementing; heavy runs only when asked: **yes**.
5. The lean scope (section 6): **yes**.
6. A chunk for faster reading and retraining (S4), before the heavy session; S4d/e measured in S5: **yes**.

**Open (S4):**

7. Workers for reading in parallel: 3 (one core left for the app and the editor), or 4?
8. Batch size to try in S5: 512 only, or 256 and 512?
9. Base reader epochs to try in S5: 5 and 8?

## 6. Lean scope (2026-10-15) and later

To cut the building time from 11–13 h to **about 5–7 h**, the first plan was cut down:

- Its S5 (one heavy job, no left-over workers, one thread) and S6 (copies) became **S1, done first**: they
  are cheap and fix the slow computer at once.
- Its S2, S3 and S4 (features, windows, masks) became **one chunk, S3**: the same code.
- Its S0 (profiling) moved into **S5**, at the end, as part of the one heavy session.

**Later, only if S5 shows Measure is still too slow:**

- Folds in parallel (2–4 worker processes, the feature store memory-mapped so they share it).
- Faster search (its Python loops; under 0.5 s a line today, so only if S5 shows it matters).
  (Window features, lines in parallel and training batches moved into S4.)

## 7. Time to build

| Chunk | My work | Heavy runs |
|---|---|---|
| S1 CPU fights, copies (built) | about 1 h | — |
| S2 parallel tests (built) | 1.5–2 h | — |
| S3 Measure cache (built) | 3–4 h | — |
| S4 faster reading and retraining | 3–4 h | — |
| S5 heavy session | 30 min to set up and report | about 2.5 h, unattended, when the user says |

**About 8–11 hours** of building. Suggested model: Opus (S3 and S4 change the reader's training). A new session
per chunk keeps replies fast; this file carries what the next session needs.

# Manuscript Letter Extraction: Implementation Plan

Desktop tool (Python) that reads scanned manuscript pages, cuts out every letter (akshara) with its matras, groups identical letters and writes a labeled dataset with CSV and HTML reports.

This plan implements **Phase 1** of `requirements-fetch-text.md` (FR-1 to FR-10). Phases 2 and 3 (OCR training and conversion) are out of scope, but the output is designed for them (`dataset/`, `lines/`, reading order in `samples.csv`).

The work is split into **small chunks (C0 to C9)**. Each chunk ends with a CLI you can run on the sample pages, and output you can check by eye, before the next chunk starts.

**Status:** C0, C1, C2, C3a and C3b are done (letter cutting: 92% of letters correct on the counted sample lines, see `docs/TUNING.md`). C4 (grouping) is next. Where the implementation differs from the original plan, the chunk has a **Changes from the original plan** note that says what changed and why.

---

## 1. Technology Choices

Same stack as `manuscript-border-remover-app`, so code, packaging and CI can be reused.

| Area | Choice | Why |
|---|---|---|
| Language | **Python 3.10+** (build with 3.13) | Same code on Windows and macOS. |
| Image processing | **OpenCV** (`opencv-python-headless`) + **NumPy** | Thresholding, morphology, connected components and projections are built in and fast. |
| Image I/O | **Pillow** | Unicode-safe paths on Windows. Never use `cv2.imread` / `cv2.imwrite`. |
| Grouping | **scikit-learn** (added in C4 only) | Agglomerative clustering and HOG-like features without writing them by hand. |
| GUI | **Tkinter** | Ships with Python, small installer, same as the border remover. |
| Batch speed | `ProcessPoolExecutor` | Pages are independent up to the grouping step. |
| Packaging | **PyInstaller** | `.exe` on Windows, `.app` on macOS (each built on its own OS). |
| Tests | `unittest` | The border remover's CI already runs `python -m unittest discover -s tests`. |

### Cross-platform rules

- `pathlib` everywhere; no hand-built paths.
- All image files are read and written through Pillow.
- Worker processes start only under `if __name__ == "__main__":` with `multiprocessing.freeze_support()`.
- Output folder names are ASCII-safe (`ki__U0A95-U0ABF`); the real Gujarati label lives in a file inside the folder (FR-9).
- CSV files are written as `utf-8-sig` so Gujarati text opens correctly in Excel.
- Never write into the input folder; refuse to run if input and output folders are the same.

---

## 2. Project Layout

```
manuscript-letter-extraction/
├── README.md
├── pyproject.toml
├── requirements.txt
├── src/letter_extractor/
│   ├── __init__.py
│   ├── __main__.py        # python -m letter_extractor
│   ├── cli.py             # command line entry point (built first)
│   ├── gui.py             # Tkinter front end (C6)
│   ├── config.py          # all thresholds, with separate red / black ink values
│   ├── io_utils.py        # folder scan, Unicode-safe image load/save (from border remover)
│   ├── prepare.py         # text block, red and black ink masks           (C1)
│   ├── lines.py           # line bands and headline tracking              (C2)
│   ├── pieces.py          # headline breaks -> stroke pieces              (C3a)
│   ├── letters.py         # join / split rules -> letters, ink masks      (C3b)
│   ├── features.py        # shape fingerprints                            (C4)
│   ├── grouping.py        # clustering, unsure                            (C4)
│   ├── mapping.py         # Devanagari -> Gujarati, safe folder names     (C5)
│   ├── data/mapping_dev_guj.csv   # user-editable exception table         (C5)
│   ├── dataset.py         # dataset/, lines/, unsure/ writers             (C5)
│   ├── overview.py        # overview.html                                 (C5)
│   ├── report.py          # report.csv, samples.csv, letters.csv, summary (C0 -> C5)
│   └── pipeline.py        # process_page(), process_folder()
├── tests/
│   ├── synthetic.py       # draws fake pages with known lines and breaks
│   └── test_*.py
├── samples/               # page1.jpg, page2.jpg, cleaned/ (copied from border remover)
├── packaging/             # gui_entry.py, build_macos.sh, build_windows.bat  (C7)
└── .github/workflows/build.yml                                              (C8)
```

The core (`pipeline.py` and everything it calls) has no GUI or CLI code, so the CLI and the GUI call the same functions.

*Change:* there is no separate `debug.py`. Each step's module has its own overlay function next to the code it shows (`ink_overlay` in `prepare.py`, `lines_overlay` in `lines.py`, `pieces_overlay` in `pieces.py`, `letters_overlay` in `letters.py`), which keeps a step and its picture together.

### Files reused from `manuscript-border-remover-app`

| From | Use |
|---|---|
| `src/border_remover/io_utils.py` | Copy as is (`scan_folder`, `natural_key`, `validate_folders`, `load_image`, `FolderError`). |
| `src/border_remover/config.py` | Same pattern: one `@dataclass Config`. |
| `src/border_remover/cli.py`, `__main__.py` | Same argparse, progress callback and exit codes. |
| `src/border_remover/report.py` | Same CSV writer (`utf-8-sig`) and overlay helper. |
| `src/border_remover/gui.py` | Starting point for the GUI in C6. |
| `packaging/*`, `.github/workflows/build.yml` | Rename `BorderRemover` to `LetterExtractor` (C7, C8). |
| `samples/page1.jpg`, `page2.jpg`, `samples/cleaned/` | Test pages. |

---

## 3. Pipeline and Data Model

```
input pages
  → C1 prepare page     text block, red / black ink masks
  → C2 find lines       line bands, headline y per column
  → C3a first cut       headline breaks → stroke pieces
  → C3b letters         join / split rules, attach marks, ink mask per letter
  → C4 group            shape fingerprints, clustering across all pages
  → C5 write output     labels, Gujarati mapping, dataset/, lines/, CSV, HTML
```

Steps C1 to C3b run per page in parallel. C4 and C5 run once over all pages.

Data passed between steps (plain dataclasses, each in the module that makes it; `pipeline.PageData` holds them all for one page):

```python
@dataclass
class PreparedPage:            # prepare.py (C1)
    rgb: np.ndarray            # the page as loaded, never modified
    paper, black, red, rules: np.ndarray   # bool masks: paper, black ink, red ink, removed ruled lines
    block: tuple | None        # text block x, y, w, h

@dataclass
class Line:                    # lines.py (C2)
    index: int                 # 1-based, top to bottom
    box: tuple                 # x, y, w, h of the line's ink, incl. upper and lower matras
    mask: np.ndarray           # this line's ink only, inside box
    headline_y: np.ndarray     # headline row for every page column (follows slope and waves)
    ink: str                   # "black" | "red" | "mixed"

@dataclass
class Piece:                   # pieces.py (C3a)
    line: int; index: int
    x0: int; x1: int           # columns between two cuts
    box: tuple; mask: np.ndarray
    ink: str
    head_width: int            # widest run of ink in the headline band
    stem_width: float          # median width of the ink rows below the headline

@dataclass
class Letter:                  # letters.py (C3b)
    line: int; pos: int        # reading order (FR-6); the page is known from the file
    box: tuple                 # x, y, w, h in page coordinates
    mask: np.ndarray           # ink pixels that belong to this letter only
    ink: str                   # "black" | "red"
    kind: str                  # "letter" | "danda" | "digit"
    pieces: int                # stroke pieces joined into it
    rules: list[str]           # join / split rules applied (for tuning)
```

Group, label and confidence are not stored on the letter: they are added in C4 and C5 as columns of `samples.csv`.

Every stage can save a **debug overlay** to `<output>/debug/` (`--debug`). These overlays are how each chunk is checked and tuned.

---

## 4. Implementation Chunks

Each chunk is one branch and one PR. A chunk is closed when its "done when" is met on `samples/page1.jpg` and `samples/page2.jpg`.

### C0. Project skeleton: read the input folder

**Goal:** a CLI that reads every image in the input folder and writes a report. No image processing yet.

- `pyproject.toml`, `requirements.txt` (`numpy`, `opencv-python-headless`, `pillow`), `.gitignore`, README usage.
- `io_utils.py` copied from the border remover.
- `config.py` with the `Config` dataclass and `load_config(path)` (JSON file overrides defaults).
- `cli.py`:
  ```
  letter-extractor --input <folder> --output <folder> [--config cfg.json] [--debug] [--workers N]
  ```
- `pipeline.process_folder()` loads each image in natural name order. Unreadable files are caught, recorded and skipped (FR-1).
- `report.csv`: file, status (`OK` / `FAILED` / `IGNORED`), width, height, message, seconds.

**Done when:** a folder with good images, a broken JPEG and a `.txt` file runs to the end; the bad files are in the report; the input folder is unchanged.
**Tests:** missing input folder, same input and output folder, empty folder, broken file, natural sort order.

**Changes from the original plan:**
- `report.csv` has a fourth status, `NO_TEXT` (the page loaded but no text block or no lines were found), and gains columns as later chunks add results (text block, ink pixels, lines, pieces, letters, dandas, digits).
- The CLI exits with 0 (all pages OK), 1 (some pages failed) or 2 (folder or config error), and a misspelled setting in the `--config` file is an error rather than being ignored.

### C1. Page preparation (FR-2)

**Goal:** a clean ink mask for each page, with red and black ink separated.

- Accept pages already cleaned by the border remover (`samples/cleaned/`) or raw pages.
- **Paper mask:** exclude the black scanner background (dark pixels connected to the image edge).
- **Paper tone:** the local paper value of each Lab channel is a **151 px median** computed on a quarter-size copy.
- **Ink masks:**
  - red ink: Lab `a*` at least 14 above the local paper and at least 8 darker (L) than it;
  - black ink: lightness below 0.62 x the local paper lightness, and not red.
- **Ruled lines:** straight ink runs longer than 15% of the page height or width are border rules and are removed from the ink masks.
- **Text block:** the main run of ink-dense columns, then of rows; folio numbers cover only a few lines, so they fall outside it.
- Remove specks smaller than `min_speck_px` (separately for red and black).

**Output:** `debug/<page>_ink.png` (black ink in black, red ink in red, removed rules in blue, outside the block greyed out, block outlined in green).
**Done when:** on both sample pages the text block is found, the border and folio numbers are outside it, and red verses are fully in the red mask. *Met.*

**Changes from the original plan:**
- **Fixed thresholds against the local paper instead of an adaptive (Sauvola) threshold.** The ink is clearly separated from the paper once the paper tone is known locally, so a simple, explainable rule per ink was enough.
- **The median window is 151 px, not 51.** With 51 px the window is about one letter wide; inside dense red text the "paper" estimate was pulled towards red (`a*` 150 instead of 134), so the red headlines and light strokes were lost. With 151 px paper and red ink separate cleanly (paper at 0, red ink at about +40 in `a*` difference).
- **Ruled lines are removed by shape**, which the plan did not mention. On raw scans the red rules are red ink too; removing them is what lets the text block exclude them. Letters that cross a rule lose the crossing pixels, so pages cleaned by the border remover are still preferred.

### C2. Line detection (FR-3)

**Goal:** find all text lines and trace each headline.

1. Keep only **horizontal ink runs of at least 25 px** (stems, dandas and matras drop out). Their row profile has one peak per line: the headline. Line spacing comes from the profile's autocorrelation (about 112 px on the samples) unless `line_spacing_px` is set.
2. **Follow the headline:** in 150 px windows near the line's peak, take the strongest row of horizontal runs. Fit a smooth curve (degree 2) through all windows and replace windows more than 0.08 x spacing away from it. This follows slope and gentle waves but not jumps.
3. **Main zone and boundaries:** the main zone ends where the ink below the aligned headlines drops off (about 57 px). The boundary between two lines follows the emptiest rows between the main zone of the upper line and the headline of the lower one.
4. **Assign ink to lines:** every connected ink blob is assigned whole. A blob touching one headline belongs to that line, even if it crosses the boundary. A blob touching two headlines is split at the boundary. A detached blob goes to the nearer of "just above the headline below" (upper mark) and "just below the main zone above" (lower mark).
5. Mark each line `black`, `red` or `mixed` from its ink share (80%).
6. Each line image is cut from the original page; ink of the neighbouring lines inside the crop is **inpainted** from the paper around it.

**Output:**
- `lines/<page>_L01.png`, ... one cropped image per line (paper background, only that line's ink kept);
- `debug/<page>_lines.png` with the traced headlines and band edges drawn.

**Done when:** 11 of 11 lines found on both sample pages, headlines follow the ink, and a visual check finds no matras on the wrong line. *Met (raw and cleaned pages).*
**Tests:** synthetic page with N slanted, wavy fake headlines → N lines, headline error ≤ 2 px (measured: 1.5 px on lines that drop 15 px and wave). Detached marks go to their own line; every ink pixel belongs to exactly one line.

**Changes from the original plan:**
- **Headlines are found on horizontal runs only, not on all ink.** On all ink the peak was right, but tracing failed over dandas and headless stretches: the vertical strokes beat the real headline and the trace dropped into the letter bodies.
- **A smooth-curve fit replaces the 3-window median.** Runs of big upper matras and the dandas at line ends pulled single windows 20 px off; a median of 3 cannot remove a run of bad windows, a robust fit can.
- **Boundaries follow the emptiest rows, not the midpoint between headlines.** The midpoint is about 55 px below a headline, which cuts through the letters' lower parts. The blob rules (step 4) decide matras anyway; the boundary only matters for blobs touching two lines.
- **Line images use inpainting instead of a flat paper colour.** The flat median colour left visible lighter patches.

### C3a. Stroke pieces: headline breaks (FR-4)

**Goal:** the first cut, exactly as the trial in the requirements (Section 2).

- Measure the **headline thickness** in every column, in a band from 8 px above to 4 px below the traced headline (letter bodies start lower).
- A **break** is a run of columns where the headline is thinner than half its typical thickness on that line (`break_soft_frac`), and somewhere thinner than 30% of it (`break_max_frac`). Runs narrower than `min_break_px` (2 px) are ignored. Limits are set separately for red and black ink.
- Inside a break the cut goes through each empty column run of the main zone, otherwise through the column with the least ink. A danda or digit standing in a gap becomes its own piece.
- Each piece takes the line's ink in its columns from just above the headline to the bottom of the main zone. Pieces with less ink than `min_piece_ink_px` are specks and are dropped.
- Each piece records its ink colour, `head_width` (widest run of headline ink) and `stem_width` (median width of its rows below the headline) for C3b.

**Output:** `debug/<page>_pieces.png` with a thin red line at every cut and numbered pieces; `report.csv` counts pieces and specks.
**Done when:** results match the trial: black lines show most letter boundaries (with extra cuts at vowel bars and missing cuts at touching headlines); this is the baseline the next chunk corrects. *Met: 36-46 pieces per line.*

**Changes from the original plan:**
- **A break is where the headline thins, not only where it has no ink.** The trial in the requirements expected red lines to have too many breaks. On these pages it is the opposite: the red headlines are almost continuous and only thin to 1-3 px (of about 10) at each join, so "no ink in the band" kept whole runs of red letters together (for example तापोनरको as one piece).
- **Hysteresis (two limits).** A join is often only 1 px wide at its thinnest point, which `min_break_px` would throw away. The run is measured where the headline is below half its thickness, and must reach below 30% somewhere.
- **No `has_headline` flag; `head_width` and `stem_width` instead.** Every danda reaches into the headline band, so "ink in the band" called every danda a letter with a headline. On the real pages dandas and vowel bars are about equally wide in the band, so C3a cannot tell them apart; the measurements go to C3b, which decides with more context.

### C3b. Letters: join and split rules (FR-5, FR-6)

**Goal:** turn stroke pieces into letters and save each one as an image.

Each line is handled as a label image (every ink pixel carries its letter number). Rules in order:

1. **Narrow pieces** (narrower than `min_letter_width_ratio` x the line's typical piece width):
   - a **tall stroke** (ink in at least 85% of its rows, at least 0.6 x the piece zone tall, and no narrow waist) with an **upper mark touching it** is an i-matra bar. If the mark leans right it is the **ि hook and joins RIGHT**; otherwise it is **ी and joins LEFT**;
   - a tall stroke whose headline runs **through the cut into its left neighbour** (ink on both sides of the cut), or whose headline is clearly wider than its stem, is a **vowel bar (ा ो ौ) and joins LEFT**;
   - any other tall stroke is a **danda**; two dandas close together are one **double danda**;
   - anything else (broken strokes, visarga) joins the neighbour it touches most across the cut, or the left one.
2. **ि stems hidden in the previous letter:** when the ि stem's headline touches the letter before it there is no break. Its curl rises from a stem near that letter's right edge and arches over the next letter; the stem is moved across.
3. **Split wide letters:** a letter wider than `split_width_ratio` (1.4) x the **page's** typical letter width is cut into round(width / typical) parts, each cut at the column with the least body ink near its expected place, **only where that column is nearly empty** (bodies apart, only the headline joins). Letters wider than `split_force_ratio` (2.2) are cut anyway. Joined bars, ि hooks and moved ि stems are protected, and every part must keep a letter body.
4. **Attach marks:** ink above the headline band, above or below the piece zone, and specks go to the letter they **touch most**, otherwise the one they overlap most horizontally, otherwise the nearest.
5. **Digits:** one or two short letters between two dandas are a verse number (`kind = "digit"`).
6. **Ink mask per letter:** only the pixels labelled with that letter; the letter image inpaints any other ink inside its crop (FR-6).

**Output:**
- `letters/<page>/L01_003.png`: crop with a 4 px margin, original paper background, other letters' ink inpainted away (images of an earlier run are replaced);
- `samples.csv`: page, line, pos, x, y, w, h, ink, kind, pieces, rules, image (one row per letter, all pages);
- `debug/<page>_letters.png`: each letter in its own colour with a box; dandas grey, digits magenta, split letters with a dashed red box;
- `report.csv` counts letters, dandas and digits per page.

**Done when:** for both sample pages, count missed breaks, extra breaks and wrongly attached matras, and record them in a tuning table in `docs/TUNING.md` (as Section 8.4 of the requirements asks). Tune until most letters on black lines are cut right; record the red-line numbers separately. *Met: 142 of 154 counted letters correct (92%); black 80 of 83, red 62 of 71. Remaining error types and possible fixes are listed in `docs/TUNING.md`.*
**Tests:** a synthetic line with every rule (plain letter, letter + ा bar, ि hook + letter, two touching letters, anusvara and a leaning e-mark, double danda, lower mark, visarga) in red and black; every letter must be found with the right extent, kind and marks. Each rule was checked by disabling it: the tests then fail.
**Performance:** 6-7 s per page on one worker, without `--debug` (the process pool from C0 runs pages in parallel).

**Changes from the original plan:**
- **ि vs ी vs danda vs vowel bar by evidence, not by shape alone.** The plan described the ि hook as "curl above the headline on its left side". In C3a's pieces the curl is outside the piece zone, so a ि stem looks like any bar. The direction of the upper mark that touches the stem decides (right: ि, left: ी), and bars and dandas are told apart by whether the headline continues through the cut (bar) or the stroke stands in empty columns (danda).
- **Waist test for strokes.** The two dots of a visarga often almost touch and passed as a tall stroke (a danda). A real stroke has about the same width all the way down.
- **New rule: ि stems hidden in the previous letter** (rule 2). Very common in this hand (मि, नि, ति); without it the stem stayed with the letter before and the curl followed it.
- **Splitting uses the page's typical width and needs a body gap; threshold 1.4 / 2.2 instead of 1.6.** With 1.6 x a per-line median, real wide letters (प्यो 124 px, श्री 127 px) were split and merged pairs were not: lines with many merges have an inflated median. Width alone cannot separate them (single letters up to about 130 px, pairs from about 130 px), but a merged pair has an empty column between the two bodies and a single letter does not. Repeated halving was replaced by cutting into round(width / typical) parts in one go, so long runs of touching letters are cut evenly.
- **Marks attach by contact first, then by overlap.** By overlap alone a ि curl or a leaning e-mark goes to the letter it covers instead of the letter it belongs to. Counting contact pixels per letter (not taking the highest label number nearby) fixed the स्वामि case.
- **Ink above the headline band is always treated as mark ink**, because the column cut of C3a could hand the bottom of a leaning matra to the neighbouring piece.
- **Digits** are recognised only by position (between dandas); "small isolated shapes in red verse numbers" was not needed.
- **`samples.csv` also records `pieces`, `rules` and the image path**, so each sample can be traced and each rule's effect counted.

### C4. Grouping identical letters (FR-7, Section 8.2)

**Goal:** put samples that look alike into groups across all pages, so the user labels groups instead of single letters.

1. **Normalize** each letter: ink mask → black on white, crop to ink, pad to a square, resize to 48 × 48.
2. **Fingerprint:** downsampled pixels plus HOG (`skimage`-free, written with OpenCV `HOGDescriptor` or NumPy gradients), L2-normalized.
3. **Cluster:** agglomerative clustering (`sklearn`) with a distance threshold from `Config` (`group_distance`). Red and black samples share groups.
4. **Unsure:** groups smaller than `min_group_size` and samples far from their group centre go to `unsure`.
5. Order groups by size (biggest first) and give them stable IDs `g0001`, `g0002`, ...

**Output:**
- `groups/g0001/<page>_L01_003.png`, ... (temporary review folders);
- `unsure/`;
- `samples.csv` gets `group_id` and `distance` columns;
- `groups.html`: a simple page with one row per group showing up to 20 samples, to check the grouping.

**Done when:** on the two pages most groups contain a single letter. Look-alikes that merge (व/ब, घ/ध, म/भ) are noted for the review step.
**Tests:** synthetic glyphs (rendered shapes plus noise) cluster into the right number of groups.

### C5. Labels, Gujarati mapping, CSV and HTML reports (FR-7, FR-9, FR-10)

**Goal:** the full output folder of FR-9 and the run summary of FR-10.

**Labeling (file-based until the review screen exists):**
- The first run writes `labels.csv` (group_id, example image, sample count, label). The user fills in the **Devanagari** label (or Gujarati; both are accepted) while looking at `groups.html`.
- Re-running reads `labels.csv` and keeps the labels. Groups are matched to the previous run by their samples (page, line, pos), so labels survive a re-run.

**Mapping (Section 4 of the requirements), `mapping.py`:**
- Default rule: Devanagari U+0900–U+097F → Gujarati at a fixed offset (+0x180).
- Exceptions from the editable `mapping_dev_guj.csv`: danda । ॥ kept as Devanagari, digits १२३ → ૧૨૩ (or 123, a setting), rare letters (ऴ ऩ ऱ ...) with a rule each.
- Safe folder names: transliteration + code points, for example `ki__U0A95-U0ABF`.

**Writers:**
- `dataset/<category>/<class>/`: every sample of the class as a PNG; `label.txt` with the Gujarati label. Categories: `vowels`, `consonants`, `conjuncts`, `digits`, `punctuation`. Options: `original` crop (default), `normalized` black on white, fixed size (64 × 64).
- `lines/<page>_L01.png` + `.txt`: Gujarati text of the line, built from labeled letters in reading order (unlabeled letters written as `[?]`).
- `letters.csv`: Gujarati label, Devanagari form, code points, transliteration, sample count, example image.
- `samples.csv`: page, line, pos, bbox, ink, kind, group_id, class, confidence.
- `overview.html`: one example per class in a grid, sorted in alphabet order (vowels, consonants ક to હ, conjuncts, digits, punctuation), with label and count; classes under `min_samples_warn` highlighted. Self-contained (images linked relatively, no internet needed).
- `unsure/`: samples not yet labeled.
- `summary.txt` (and the same numbers at the end of the CLI output): pages, lines, letters, classes, classes with few samples, unsure count, skipped files.

**Done when:** after labeling a few groups and re-running, `dataset/`, `lines/*.txt`, both CSVs and `overview.html` are correct; Gujarati shows correctly in Excel and in the browser on Windows and macOS.
**Tests:** mapping round-trips (क → ક, कि → કિ, क्ष → ક્ષ, । → ।, १२ → ૧૨), safe folder names are unique, labels survive a re-run.

### C6. Desktop GUI

**Goal:** the same run from a window, for users who do not use the command line.

- Tkinter window: input folder, output folder, optional config file, "debug images" checkbox.
- Run button, progress bar, log pane; processing in a worker thread so the window stays responsive.
- After the run: buttons to open the output folder, `overview.html` and `labels.csv`.

**Done when:** a GUI run gives the same output as the CLI run.

### C7. Packaging for Windows and macOS

**Goal:** a downloadable app for both platforms.

- `packaging/gui_entry.py` (with `freeze_support()`), `build_macos.sh`, `build_windows.bat`, copied from the border remover and renamed to `LetterExtractor`.
- Bundle `data/mapping_dev_guj.csv` with `--add-data`; load it through a helper that works both from source and from the frozen app (`sys._MEIPASS`).
- Check the size added by scikit-learn; if it is too large, replace the clustering with a small NumPy implementation.

**Output:** `dist/LetterExtractor.app` (macOS), `dist/LetterExtractor/LetterExtractor.exe` (Windows).
**Done when:** each build runs the two sample pages on a clean machine of its OS.
**Note:** unsigned apps trigger SmartScreen (Windows) and Gatekeeper (macOS). Fine for internal use; signing is a separate task.

### C8. GitHub Actions

**Goal:** tests on every push and pull request, builds for both platforms, releases from tags.

- Copy `.github/workflows/build.yml` from the border remover:
  - `test` job on `ubuntu-latest`, Python 3.10 and 3.13, `python -m unittest discover -s tests`;
  - `build` job on `macos-latest` and `windows-latest` (needs `test`), zip and upload the app;
  - `release` job on `v*` tags, attaches both zips to a GitHub release.
- Add a smoke step: run the CLI on `samples/` and check that `summary.txt` reports 22 lines (11 per page).

**Done when:** a PR shows green tests and both build artifacts; tagging `v0.1.0` creates a release.

### C9. Review screen (FR-8), after first delivery

**Goal:** fix grouping and cutting errors quickly without editing CSV files.

- View groups as image grids; label, rename, merge, split groups; move a sample to another group; delete specks.
- Fix wrong cuts: join two neighbouring samples or split one, shown on the line image.
- Every decision is saved to `review.json` in the output folder and re-applied on re-run.
- Optional label suggestions (AI or a Phase 2 recognizer), opt-in only, offline by default.

**Done when:** corrections survive a re-run and appear in `dataset/` and the CSV files.

### Chunk summary

| # | Chunk | Main output | Requirements |
|---|---|---|---|
| C0 | Read input folder, skeleton | `report.csv` | FR-1 |
| C1 | Page preparation | `debug/*_ink.png` | FR-2 |
| C2 | Line detection | `lines/*.png`, `debug/*_lines.png` | FR-3 |
| C3a | Stroke pieces | `debug/*_pieces.png` | FR-4 |
| C3b | Letters | `letters/`, `samples.csv` | FR-5, FR-6 |
| C4 | Grouping | `groups/`, `unsure/`, `groups.html` | FR-7 |
| C5 | Labels, mapping, CSV and HTML | `dataset/`, `lines/*.txt`, `letters.csv`, `overview.html`, `summary.txt` | FR-7, FR-9, FR-10 |
| C6 | GUI | Desktop window | Section 7 |
| C7 | Packaging | `.app`, `.exe` | Section 7 |
| C8 | GitHub Actions | CI builds, releases | Section 7 |
| C9 | Review screen | `review.json` | FR-8 |

---

## 5. Configuration

One `Config` dataclass in `config.py`. A JSON file passed with `--config` overrides any value. Ink-specific values sit in an `InkParams` dataclass that exists twice, `cfg.black` and `cfg.red`.

The main settings as implemented (see `src/letter_extractor/config.py` for all of them, each with a comment):

| Setting | Chunk | Default (black / red) |
|---|---|---|
| `paper_blur_px` | C1 | 151 (was 51 in the plan, see C1) |
| `black_max_rel_l`, `red_min_da`, `red_min_dl` | C1 | 0.62, 14, 8 |
| `rule_min_frac` | C1 | 0.15 of the page |
| `min_speck_px` | C1 | 8 / 5 |
| `line_spacing_px` | C2 | 0 = auto (≈ 112) |
| `headline_min_run_px` | C2 | 25 |
| `headline_window_px` | C2 | 150 |
| `headline_max_wave_frac` | C2 | 0.08 of the spacing |
| `headline_above_px`, `headline_below_px` | C3a | 8, 4 (replace `headline_half_height`) |
| `break_max_frac`, `break_soft_frac` | C3a | 0.3, 0.5 / 0.3, 0.5 of the headline thickness |
| `min_break_px` | C3a | 2 / 2 |
| `min_piece_ink_px` | C3a | 15 / 10 |
| `min_letter_width_ratio` | C3b | 0.45 |
| `stroke_min_fill`, `stroke_min_waist` | C3b | 0.85, 0.4 |
| `split_width_ratio`, `split_force_ratio` | C3b | 1.4, 2.2 (was 1.6, see C3b) |
| `split_gap_frac` | C3b | 0.15 |
| `letter_margin_px` | C3b | 4 |
| `normalize_size` | C4 | 48 |
| `group_distance` | C4 | to tune |
| `min_group_size` | C4 | 2 |
| `digits` | C5 | `gujarati` (or `western`) |
| `dataset_image` | C5 | `original` (or `normalized`, `fixed64`) |
| `min_samples_warn` | C5 | 10 |

---

## 6. Testing

- **Synthetic tests (`tests/synthetic.py`):** draw fake pages with OpenCV: N slanted, wavy headlines; blocks with known gaps; vowel-bar-like pieces; red and black strokes. They check line count, headline position, break positions and letter counts with exact expected values.
- **Sample pages:** regression checks on `samples/page1.jpg` and `page2.jpg`: 11 lines per page; letter count within a range that is fixed once C3b is tuned.
- **Output checks:** CSV columns, `utf-8-sig`, safe folder names, labels surviving a re-run, input folder unchanged.
- Run locally and in CI with `python -m unittest discover -s tests -v` (`PYTHONPATH=src`).
- **Synthetic pages must be realistic in size.** Several thresholds are fractions of the page (a ruled line is longer than 15% of the page height or width). On small test pages, stems and joined headlines counted as ruled lines and were erased. The test pages are therefore at least 800 x 1600 px.
- **Rule tests are checked by breaking the rule.** For C2 and C3b each rule was disabled once to confirm a test fails; two test pages had to be corrected because a rule was not actually exercised.

---

## 7. Requirement Traceability

| Requirement | Chunk | Module |
|---|---|---|
| FR-1 Folder input, skip bad files | C0 | `io_utils.py`, `pipeline.py`, `report.py` |
| FR-2 Page preparation, red / black ink | C1 | `prepare.py` |
| FR-3 Line detection, headline tracking, matras to lines | C2 | `lines.py` |
| FR-4 Headline-break splitting | C3a | `pieces.py` |
| FR-5 Join and split rules | C3b | `letters.py` |
| FR-6 Letter samples, ink mask, reading order | C3b | `letters.py`, `report.py` |
| FR-7 Grouping and labeling | C4, C5 | `features.py`, `grouping.py`, `labels.csv` |
| FR-8 Review screen | C9 | `review.py`, `gui.py` |
| FR-9 Output folder | C5 | `dataset.py`, `overview.py`, `report.py`, `mapping.py` |
| FR-10 Report | C0, C5 | `report.py` |
| Desktop app, Windows and macOS | C6, C7, C8 | `gui.py`, `packaging/`, `.github/workflows/` |
| Offline, non-destructive, traceable, adjustable | all | `io_utils.py`, `samples.csv`, `config.py` |

---

## 8. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Red ink headlines are thin and broken, giving too many cuts | Separate red settings; larger `min_break_px` for red; join rules in C3b; red error counts tracked separately. |
| Touching headlines give missed cuts | Width-based split at the thinnest point (C3b); join/split in the review screen (C9). |
| Upper and lower matras touch the next line | Matras assigned by position relative to both headlines (C2), checked in debug overlays. |
| Look-alike letters land in one group | Expected; split in review. A Phase 2 recognizer later suggests labels. |
| Old letterforms (अ like ल्ल, ख like रव) cut in two | Conjuncts and broken letters joined by the "touches most" rule; the user can join cuts in C9. |
| Too slow on hundreds of pages | Process pool for C1 to C3b; grouping on 48 × 48 fingerprints only. |
| scikit-learn makes the installer large | Measure in C7; replace with a small NumPy clustering if needed. |

---

## 9. Decisions to Confirm

From Section 9 of the requirements, with a proposed default:

1. **Digits:** Gujarati (૧૨૩) by default, Western as a setting.
2. **Rare letters** with no Gujarati equivalent: keep the Devanagari character and list it in the summary until a rule is chosen.
3. **Anusvara and visarga:** proposed as part of the letter class (કં), open for confirmation; the mapping and grouping work either way.
4. **Red and black ink:** share classes; the ink colour is kept in `samples.csv`.
5. **Cloud use:** offline only for Phase 1; AI suggestions are a C9 opt-in.
6. **Other manuscripts:** all cutting rules use settings, not fixed values, so another hand needs a new config file, not new code.
7. **GUI toolkit:** Tkinter, as in the border remover.

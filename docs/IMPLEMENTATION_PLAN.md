# Manuscript Letter Extraction: Implementation Plan

Desktop app that reads scanned manuscript pages, cuts out every letter (akshara) with its matras, groups identical letters, lets a person review the groups and map each one to its Unicode letter, and writes a labeled dataset with CSV and HTML reports. The image processing is Python; the review app has a Python backend, a React screen and a SQLite database, with one library of **books**.

This plan implements **Phase 1** of `requirements-fetch-text.md` (FR-1 to FR-10). Phases 2 and 3 (OCR training and conversion) are out of scope, but the output is designed for them (`dataset/`, `lines/`, reading order in `samples.csv`).

The work is split into **small chunks (C0 to C9, with C5 in seven parts)**. Each chunk ends with something you can run on the sample pages and check by eye (the CLI for C0-C4; tests, the API or the app screens for C5), before the next chunk starts.

**Status:** C0 to C4 are done (letter cutting: 92% of letters correct on the counted sample lines; grouping: 854 samples of the two sample pages in 54 groups and 28% unsure; see `docs/TUNING.md`). C5 was redesigned before it started (2026-10-04): instead of labeling through a `labels.csv` file, it is now a **review app** (React screen, Python backend, SQLite database, books), which also takes over C6 (GUI) and most of C9 (review screen). C5a (library and database), C5b (Unicode mapping) and C5c (backend API) are done; C5d (app shell, Books and Capture screens) is next. Where the implementation differs from the original plan, the chunk has a **Changes from the original plan** note that says what changed and why.

---

## 1. Technology Choices

Same stack as `manuscript-border-remover-app`, so code, packaging and CI can be reused.

| Area | Choice | Why |
|---|---|---|
| Language | **Python 3.10+** (build with 3.13) | Same code on Windows and macOS. |
| Image processing | **OpenCV** (`opencv-python-headless`) + **NumPy** | Thresholding, morphology, connected components and projections are built in and fast. |
| Image I/O | **Pillow** | Unicode-safe paths on Windows. Never use `cv2.imread` / `cv2.imwrite`. |
| Grouping | **NumPy** (was: scikit-learn) | Threshold clustering written for this project; see C4 for why scikit-learn was not used. |
| App backend | **FastAPI** + **Uvicorn** (C5) | Small, typed Python web API; calls the existing pipeline directly. |
| Database | **SQLite** through **SQLAlchemy 2**, migrations with **Alembic** (C5) | One file, no server, works offline, every change saved whole. SQLAlchemy and Alembic keep a later move to MySQL or PostgreSQL to a configuration change plus a data copy. |
| App screen | **React** + **TypeScript**, built with **Vite** (C5); `@dnd-kit` for drag and drop, `react-image-crop` for drawing a box | The best ready-made parts for image grids, drag and drop and cropping; Gujarati and Devanagari typing works natively in a browser engine. The team is new to React, so the screen uses few libraries, plain CSS and one pattern for talking to the backend. |
| App window | **pywebview** (own window) or the default **browser** (C5) | Both, as decided: the app opens in its own window; `--browser` (or a menu item) opens the same screen in the browser. |
| GUI | ~~Tkinter~~ replaced by the review app (C5) | Tkinter is weak at grids of thousands of thumbnails, drag and drop and Unicode text entry. |
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
- The app listens on `127.0.0.1` only (never on the network) and works without internet.

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
│   ├── config.py          # all thresholds, with separate red / black ink values
│   ├── io_utils.py        # folder scan, Unicode-safe image load/save (from border remover)
│   ├── prepare.py         # text block, red and black ink masks           (C1)
│   ├── lines.py           # line bands and headline tracking              (C2)
│   ├── pieces.py          # headline breaks -> stroke pieces              (C3a)
│   ├── letters.py         # join / split rules -> letters, ink masks      (C3b)
│   ├── features.py        # shape fingerprints                            (C4)
│   ├── grouping.py        # clustering, unsure                            (C4)
│   ├── mapping.py         # Devanagari <-> Gujarati, akshara check, names (C5b)
│   ├── data/mapping_dev_guj.csv   # user-editable exception table         (C5b)
│   ├── report.py          # report.csv, samples.csv, letters.csv, summary (C0 -> C5g)
│   ├── pipeline.py        # process_page(), process_folder()
│   └── app/               # the review app backend                        (C5)
│       ├── db.py          # SQLAlchemy models: books, pages, samples, groups, actions (C5a)
│       ├── library.py     # library folder, create / open books, capture            (C5a)
│       ├── api.py         # FastAPI routes                                          (C5c)
│       ├── actions.py     # review actions and undo                                 (C5c)
│       ├── jobs.py        # extraction in the background, progress                  (C5c)
│       ├── samples.py     # new samples from a box, join, split, upload             (C5f)
│       ├── export.py      # dataset/, lines/, CSV files, overview.html             (C5g)
│       ├── main.py        # start the server, open the window or the browser       (C5d)
│       └── static/        # the built React screen (not in git)
├── frontend/              # the React + TypeScript source (C5d-C5f)
│   ├── package.json
│   └── src/               # screens: Books, Capture, Groups, Page viewer
├── tests/
│   ├── synthetic.py       # draws fake pages with known lines and breaks
│   └── test_*.py
├── samples/               # page1.jpg, page2.jpg, cleaned/ (copied from border remover)
├── packaging/             # gui_entry.py, build_macos.sh, build_windows.bat  (C7)
└── .github/workflows/build.yml                                              (C8)
```

The core (`pipeline.py` and everything it calls) has no GUI or CLI code, so the CLI and the app call the same functions. The CLI stays for batch runs; the app adds books, the database and review.

*Change:* there is no separate `debug.py`. Each step's module has its own overlay function next to the code it shows (`ink_overlay` in `prepare.py`, `lines_overlay` in `lines.py`, `pieces_overlay` in `pieces.py`, `letters_overlay` in `letters.py`), which keeps a step and its picture together.

### Files reused from `manuscript-border-remover-app`

| From | Use |
|---|---|
| `src/border_remover/io_utils.py` | Copy as is (`scan_folder`, `natural_key`, `validate_folders`, `load_image`, `FolderError`). |
| `src/border_remover/config.py` | Same pattern: one `@dataclass Config`. |
| `src/border_remover/cli.py`, `__main__.py` | Same argparse, progress callback and exit codes. |
| `src/border_remover/report.py` | Same CSV writer (`utf-8-sig`) and overlay helper. |
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
  → C5 review app       store in the book's database (C5a), review and label groups (C5c-C5f),
                        Gujarati mapping (C5b), export dataset/, lines/, CSV, HTML (C5g)
```

Steps C1 to C3b run per page in parallel. C4 runs once over all pages. C5 keeps the result per book in the library and adds the manual work.

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

Group, label and confidence are not stored on the letter: C4 adds the group as a column of `samples.csv`, and in the app (C5) groups and labels live in the book's database (`sample.group_id`, `letter_group.label_dev` / `label_guj`).

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

1. **Fingerprint** (`features.py`, computed in the page workers from each letter's ink mask, so paper tone and ink colour do not matter): crop to the ink, pad to a square, resize to 48 x 48, blur 1 px; then a 24 x 24 image part, a HOG part (stroke directions in 6 x 6 cells, 2 x 2 block normalization) and the letter's width and height relative to the line spacing. Each part is scaled to unit length, the whole vector too, so distances run from 0 (same) to 2.
2. **Cluster** (`grouping.py`, plain NumPy), separately per kind (letters, dandas, digits); red and black share groups:
   - first pass in reading order: a sample joins the nearest group centre within `group_distance` (0.55), otherwise starts a new group;
   - merge: closest groups first while their centres are within `group_distance`, and only if 90% of the merged members stay within `group_outlier_distance` (0.5) of the new centre;
   - reassign every sample to its nearest centre; merge and reassign repeat 3 times;
   - centres are kept at unit length.
3. **Unsure:** samples further than `group_outlier_distance` from their group's centre, and groups smaller than `min_group_size` (2).
4. Groups are numbered by size, largest first (`g0001`, `g0002`, ...), ties by the first sample in reading order.

**Output:**
- `groups/g0001/<page>_L01_003.png`, ...: copies of the letter images, one folder per group (replaced on every run);
- `unsure/<page>_L01_003.png`;
- `samples.csv` gets `group_id` (or `unsure`) and `distance` (to the group's centre);
- `groups.html`: one row per group with up to 20 samples (nearest to the centre first), sample counts and red / black split, then the unsure samples; hover a sample to see its page, line and position. Works offline;
- the CLI prints the number of groups and unsure samples.

**Done when:** on the two pages most groups contain a single letter. Look-alikes that merge (व/ब, घ/ध, म/भ) are noted for the review step. *Met: 54 groups and 236 unsure of 854 samples; about two thirds of the 30 largest groups hold one letter, the others join look-alikes (ता / ना / मा, नि / ति, नो / तो, त / न ...). Details in `docs/TUNING.md`.*
**Tests:** synthetic glyphs (8 shapes with random size, stroke width, shift and slant) form exactly 8 pure groups; kinds never share a group; singletons are unsure; fingerprints ignore position; folders, `groups.html` and the `samples.csv` columns agree; on the sample pages there are 40-70 groups, under 35% unsure and no group with more than 15% of the samples. Disabling the compactness check or the unit-length centres makes the tests fail.
**Performance:** 40,000 samples (about 100 pages) group in 41-77 s; per page 5-6 s on one worker.

**Changes from the original plan:**
- **No scikit-learn; NumPy clustering instead of agglomerative clustering.** Agglomerative clustering needs the distance between every pair of samples: 40,000 samples (about 100 pages) is 1.6 billion distances, far too much memory for a laptop, and the plan had already flagged scikit-learn's size for the installer (C7). The NumPy version needs memory for the groups only.
- **Centres are kept at unit length.** With plain means, the centre of a large, varied group is a short vector close to every sample, and one group swallowed most of the letters.
- **Merges must keep a group compact** (90% of members within `group_outlier_distance`). Without it, groups crept from letter to look-alike letter one merge at a time, and the result jumped between nearby settings.
- **Outliers are removed once, at the end,** not during the rounds; doing it in every round made the result unstable.
- **The fingerprint is sharper than first planned** (24 x 24 image part, 1 px blur, 6 x 6 HOG cells instead of 16 x 16, 1.5 px and 4 x 4): this separated वा / ना / ता, छे / के and म / न / स.
- **HOG is computed with NumPy**, because OpenCV 5 no longer ships `cv2.HOGDescriptor` in the main package.
- **Group folders hold copies** of the letter images (named `<page>_L01_003.png`), so a group can be looked through in any image viewer. In C5 the labelled `dataset/` folders replace them as the main output.

### C5. Review app: books, database, review and labeling, export (FR-7, FR-8, FR-9, FR-10)

**Goal:** one app for the whole job, per book: choose the input pages, capture the letters (C0-C4), review the groups by hand, map each group to its Unicode letter, fix wrong cuts, and export the dataset. All of it is stored, so a book can be reopened later.

**Changes from the original plan:** the original C5 had the user type labels into a `labels.csv` file while looking at `groups.html`, with a small Tkinter window in C6 and a review screen only after first delivery (C9). Decided on 2026-10-04, before C5 started:
- **A review app instead of a CSV file.** Reviewing is mostly moving images between groups (drag to unsure, new group from a selection, merge) and fixing cuts, which a file cannot do well.
- **A database, per book.** Every decision is stored as it is made (FR-8: decisions must not be lost), and earlier books can be reopened. **SQLite** because one person uses the app per computer; through SQLAlchemy and Alembic so that MySQL or PostgreSQL can replace it later.
- **React (TypeScript) screen with a Python backend,** in its own window and in the browser. React rather than Angular: the team knows neither, and React has the best ready-made parts for this screen.
- **Labels in both scripts:** typed or picked in Devanagari or in Gujarati; stored once in Devanagari (the canonical form), shown in Gujarati.
- C6 (GUI) and most of C9 (review screen) are now part of C5.

**The library.** On first start the user picks a library folder (default: `Documents/Manuscript Letters`). It holds:

```
<library>/
  library.db                 the SQLite database
  books/<id>-<name>/            for example books/0001-sample-book/
    letters/<page>/L01_003.png   letter images (+ L01_003_mask.png, the ink mask)
    lines/<page>_L01.png         line images
    report.csv, samples.csv      the pipeline's reports of the last capture
    debug/                       overlays, when switched on
    exports/<date>/              exported datasets (C5g)
```

Input pages are **referenced, never copied or changed**: the database keeps each page's path and a SHA-256 checksum, so a moved or changed page is noticed. The whole library folder can be copied to another computer.

**Database (SQLite, SQLAlchemy models in `app/db.py`):**

| Table | Holds |
|---|---|
| `book` | name, input folder, settings (a copy of `Config`, so a book keeps the settings it was cut with), created / changed |
| `page` | book, file name, checksum, size, status and message (as in `report.csv`), line spacing |
| `line` | page, number, box, ink colour, line image |
| `sample` | page, line (and line number), position, box, ink, kind, pieces, rules, image and mask files, fingerprint (BLOB), **source** (`auto`, `cropped`, `joined`, `split`, `uploaded`), deleted flag, distance to the group's centre |
| `letter_group` | book, code (`g0001`), kind (letter, danda, digit), label in Devanagari, label in Gujarati, status (`auto`, `reviewed`, `labelled`), locked |
| `sample.group_id` | the sample's group; empty means **unsure** |
| `action` | every change by the user (what, which samples / groups, before and after) for **undo** and history |

All times are stored in UTC and shown in local time.

**Labels.** Stored in Devanagari (one canonical form, so the same letter typed in either script is the same class); the Gujarati label is derived through `mapping.py` and shown everywhere. Input:
- type in either script (the keyboard's own layout), or use the **on-screen picker** (consonant, then halant for a conjunct, then matra, anusvara / visarga), with a Devanagari / Gujarati switch;
- the app checks that the label is **one akshara** (for example क, कि, क्ष, श्री, र्म) or a danda / digit, and shows its Unicode code points.

**Sub-chunks and status:**

| Sub-chunk | Status | Depends on |
|---|---|---|
| C5a Library and database | **done** | C0-C4 |
| C5b Unicode mapping | **done** | - |
| C5c Backend API | **done** | C5a, C5b |
| C5d App shell, Books and Capture screens | **next** | C5c |
| C5e Group review and labeling | planned | C5c, C5d |
| C5f Fixing cuts and adding samples | planned | C5c, C5e |
| C5g Export | planned | C5a, C5b (can run before the screens) |

Every sub-chunk below has the same parts: status, goal, files, what it does, done when, tests, and (once built) the changes from this plan.

**Re-running extraction must not lose manual work:**
- adding pages to a book only adds samples; new samples are **suggested** for existing labelled groups (nearest group centre within `group_distance`) but stay unsure until confirmed;
- re-cutting a page that has reviewed samples asks first, and replaces only that page's samples;
- labelled groups are never renumbered or merged automatically.

#### C5a. Library and database

**Status: done** (commit "Add the library of books with a SQLite database (C5a)").
**Goal:** keep everything found in a book in a database, so a book can be captured once and reopened later.
**Files:** `app/db.py`, `app/library.py`, `app/migrations/`, `tests/test_library.py`.

- SQLAlchemy models (`app/db.py`) and the first Alembic migration (`app/migrations/versions/0001_initial.py`); `Library(path)` creates or opens the library and brings the database to the newest migration; create, list, rename and delete books (deleting removes the book's rows and its folder in the library, never the input pages).
- **Capture:** `Library.capture(book)` runs the existing pipeline into the book's folder and stores pages (with SHA-256), lines, samples (with ink masks and fingerprints) and the automatic groups. It replaces the book's earlier results and **refuses** when the book holds manual work (labels, reviewed or locked groups, user actions, cropped / uploaded samples) unless `force=True`.
- `Library.check_pages(book)` lists input pages that are missing, changed (checksum) or new.
- **Done when:** a book made from `samples/` holds 2 pages, 22 lines, 854 samples and the same groups as `groups.html`; closing and reopening gives the same data. *Met: 2 pages, 22 lines, 854 samples, 54 groups, 236 unsure; capture takes about 12 s.*
- **Tests (12):** the migration creates exactly the schema of the models; reopening keeps the data; times are UTC; books are created, listed, renamed, deleted, with bad names and folders refused; a book keeps its settings; capture stores every page, line, sample, mask, fingerprint and group and leaves the input folder unchanged; capturing again is repeatable; manual work blocks a new capture; missing, changed and new pages are reported; the sample pages give 2 pages, 22 lines and 40-70 groups. Switching off foreign keys or dropping an index from the migration makes a test fail.

**Changes from the original plan (C5a):**
- **The pipeline gained three switches for the app**, all off by default so the CLI's output is unchanged: `save_masks` (each letter's ink mask as `L01_003_mask.png`; later steps re-fingerprint and crop from it), `write_groups` (the app keeps groups in the database, so no `groups/` copies or `groups.html`), and each page result now carries its lines (`lines_info`).
- **Capture replaces the whole book's results for now.** Re-cutting single pages while keeping reviewed work (as described above) needs the review actions and comes with C5c / C5f; until then a capture over manual work is refused.
- **Small schema additions:** `letter_group.kind` (letters, dandas and digits never share a group) and `sample.line_number` (kept for uploaded and cropped samples too); timestamps are stored as UTC (`UTCDateTime`), because SQLite keeps no time zone.
- **Development uses a virtual environment** (`.venv`); `sqlalchemy` and `alembic` are now in `requirements.txt` and `pyproject.toml`, and the migrations ship as package data.

#### C5b. Unicode mapping (Section 4 of the requirements)

**Status: done** (commit "Add the Devanagari <-> Gujarati mapping and label check (C5b)").
**Goal:** one module that turns a label typed in Devanagari **or** Gujarati into one canonical Devanagari label, checks that it is a single letter, and gives everything the screens and the export need: the Gujarati form, code points, category, alphabet order, a transliteration and a safe folder name.
**Files:** `src/letter_extractor/mapping.py`, `src/letter_extractor/data/mapping_dev_guj.csv`, `tests/test_mapping.py`. No dependency on the database or the app: the CLI, the API and the export use the same functions.

**The mapping (Section 4 of the requirements):**
- **Default rule:** a Devanagari character U+0900-U+097F maps to the Gujarati character at +0x180 (क U+0915 -> ક U+0A95, ि U+093F -> િ U+0ABF), **if Unicode gives that Gujarati character the same name** (GUJARATI instead of DEVANAGARI); conjuncts, halant and reph follow automatically (क्ष -> ક્ષ).
- **Exceptions** in the editable `data/mapping_dev_guj.csv` (columns `devanagari`, `gujarati`, `note`), read once at start; a user's own copy can be given in the settings:
  - danda । and double danda ॥ stay Devanagari (Gujarati has none);
  - letters with no Gujarati letter but a nukta form - ऩ ऱ ऴ and क़ ख़ ग़ ज़ ड़ ढ़ फ़ य़ - are written as **letter + nukta**, which Gujarati has (ऩ -> ન઼, क़ -> ક઼) (decision 2);
  - the remaining 32 characters with no Gujarati equivalent (short a / e / o and their signs, the inverted chandrabindu, stress and Vedic signs, ॲ, ॸ and the other late additions) are listed with an empty `gujarati` value, meaning "keep the Devanagari character"; `unmapped()` lists them in a label and the export summary counts them;
  - candra e / o (ऍ ऑ) are listed explicitly, because Unicode names them LETTER in Devanagari and VOWEL in Gujarati.
- **Digits:** १२३ -> ૧૨૩ by default, or 123 with the setting `digits = "western"` (decision 1).
- **Back to Devanagari:** the reverse of the same table (Gujarati -> Devanagari), so a label typed in Gujarati is stored like one typed in Devanagari.

**Labels (`canonical_label(text)`):**
1. Unicode normalization (NFC); all spaces and the zero-width joiner / non-joiner removed (they only change how a conjunct is drawn, not which letter it is).
2. Every Gujarati character converted to Devanagari, and Western digits to Devanagari digits; any other script (Latin, Arabic ...) and Gujarati characters with no Devanagari equivalent (for example the rupee sign) are refused with a message.
3. The result must be **one akshara** (Section 3 of the requirements):
   - an independent vowel (अ ... औ, ऋ, ऍ, ऑ ...) with optional chandrabindu / anusvara / visarga;
   - or a consonant cluster: consonant (+ nukta), then any number of halant + consonant (this covers conjuncts and reph, for example क्ष, श्री, र्म), then either a vowel sign (matra) or a final halant, then optional chandrabindu / anusvara / visarga;
   - or one digit, a danda, a double danda, avagraha ऽ or Om ॐ.
   Anything else (two letters, a matra on its own, a mark without a letter) is refused with a reason that the screen shows (for example "two letters: क + म").
4. Returned: the canonical Devanagari label; the Gujarati form, code points and category are computed from it.

**Other functions:**
- `to_gujarati(dev, digits)`, `to_devanagari(guj)`, `code_points(text)` ("U+0915 U+093F");
- `category(label)`: `vowels`, `consonants` (one consonant, with or without matra and marks), `conjuncts` (two or more consonants), `digits`, `punctuation` - the dataset folders of FR-9;
- `sort_key(label)`: alphabet order for the overview: vowels, consonants ક to હ (by the first consonant, then the matra in the usual order), conjuncts, digits, punctuation;
- `transliterate(label)`: lower-case ASCII for folder names, readable only (कि `ki`, क्ष `kssa`, श्री `shrii`, क़ `kxa`; retroflex letters doubled: ट `tt`, ष `ss`);
- `safe_name(label)`: transliteration + Gujarati code points, for example `ki__U0A95-U0ABF` (FR-9). The code points make every name unique even where transliterations coincide (also on case-insensitive disks), and the name uses only `A-Z a-z 0-9 _ -`;
- `describe(text)`: everything the label field of the screen shows while typing (canonical form, both scripts, code points, category, safe name, characters kept in Devanagari, or the reason it is not a letter);
- `mapping_for(cfg)`: the mapping a book's settings ask for (`digits`, `mapping_file`).

**Done when:** every character of U+0900-U+097F either maps to a defined Gujarati character or is listed in the CSV; labels typed in either script give the same canonical label; all the examples of Section 4 of the requirements convert correctly; invalid labels are refused with a readable reason. *Met.*
**Tests (20):** round trips (क <-> ક, कि <-> કિ, क्ष <-> ક્ષ, श्री <-> શ્રી, र्म <-> ર્મ, ज्ञा <-> જ્ઞા, । stays ।, १२ <-> ૧૨ or 12); nukta forms; the offset positions that are other characters (U+0971, U+097A-F) are never used, even with an empty table; the whole Devanagari block is covered; every mapped character round-trips; an edited table and the `digits` / `mapping_file` settings take effect; Gujarati and Devanagari input give the same label; NFC, spaces and zero-width characters handled; refused labels with their reasons (`कम` "क + म", `ि`, `ं`, `्क`, `abc`, mixed scripts, `१२`, `कि।`); categories; alphabet order; transliteration; safe names unique (also case-insensitively), portable and short. Removing the name rule, the cleaning or the one-digit limit makes a test fail.

**Changes from the original plan (C5b):**
- **Same-name rule instead of "the Gujarati code point exists".** For 9 characters the +0x180 position holds a different character (U+0971 + 0x180 is the Gujarati rupee sign, U+097A-F + 0x180 are Gujarati nukta signs), so a plain offset would silently produce wrong letters.
- **Rare letters get a Gujarati nukta form** instead of staying Devanagari: ऩ ऱ ऴ and the eight nukta letters are written as letter + nukta, which Gujarati supports; only characters with no Gujarati form at all stay Devanagari. Decision 2 is updated accordingly.
- **Lenient input:** spaces inside a label and Western digits are accepted (removed / converted), because they are easy to type by mistake and cannot change which letter is meant.
- **A label holds one digit** (verse numbers are cut into one sample per digit by C3b).
- **Transliteration examples** are `kssa` and `shrii` rather than `ksha` and `shri`: a fixed letter-by-letter table (retroflex letters doubled) instead of a hand-made spelling, so it never needs exceptions. Safe names contain upper-case code points (`U0A95`), as in the example of FR-9.
- **Two helpers added for later chunks:** `describe()` (the label field of C5c / C5e) and `mapping_for()` (a book's settings).

#### C5c. Backend API

**Status: done** (commit "Add the backend API with review actions, undo and capture jobs (C5c)").
**Goal:** everything the screens do, available and tested as a local web API, before any screen exists.
**Files:** `app/actions.py` (review actions, undo / redo, history; usable without HTTP), `app/centres.py` (group centres, distances, suggestions), `app/jobs.py` (capture in the background), `app/api.py` (FastAPI routes), `app/schemas.py` (request bodies), additions to `app/library.py` (add pages, re-cut a page, work folder) and `pipeline.py` (`files`, `finish`); `tests/appbook.py` (a small captured book, copied per test), `tests/test_actions.py`, `tests/test_api.py`. New dependencies: `fastapi`, `uvicorn`; `httpx` for the tests.

**What it does:**
- **Books:** list, create (with optional settings overrides), get (with settings, undo / redo counts and a running job), rename, delete; page problems (`check_pages`).
- **Jobs** (`jobs.py`): capture, add new pages, re-cut one page. A job runs in a background thread; the page work runs in worker processes as in the CLI. Progress (pages done of total, the total known from the start, per-page status) is polled; a job can be cancelled. One job per book at a time. Capture or re-cut over manual work answers **409 "needs_confirmation"** until repeated with `force`.
- **Work folder:** every run writes into `<book>/.work/` and its files are moved into the book only when the run succeeded, just before the database is updated. A cancelled or failed run leaves the book exactly as it was.
- **Keeping manual work when pages change:** **add new pages** cuts only files not in the book; their samples start unsure. **Re-cut one page** replaces only that page's samples (new ones unsure); groups it leaves empty are removed if never reviewed; with `force` it also clears the undo history, which could refer to the replaced samples.
- **Reading:** pages (with line images and the page's samples), groups (code, kind, label in both scripts, status, locked, samples, red / black, spread = mean distance to the centre, example sample), a group's samples nearest to the centre first, unsure samples (or deleted ones) with a **suggested group**, single samples. Lists are paged (`offset`, `limit` up to 500).
- **Review actions** (`actions.py`): move samples (to a group or unsure), new group from samples (this is also "split a group"), merge groups, dissolve a group, label (Devanagari or Gujarati, through C5b's `canonical_label`), reviewed / locked status, delete and restore samples. Each runs in one transaction and stores the before / after state of everything it touched; **undo** and **redo** restore those states exactly; a new action clears the redo stack; **history** lists the actions. Locked groups refuse every change except unlocking. Group centres and member distances are recomputed after every change.
- **Suggestions** (`centres.py`): for an unsure sample, the nearest group whose centre is within `group_distance`; a labelled group is preferred when it is at most 10% further away than the nearest one.
- **Images:** letter, mask and line images (only `.png` files inside the book's folder) and input pages (only files recorded as pages of the book).
- **Label check:** `GET /api/label?text=...&book_id=...` returns `mapping.describe()` with the book's mapping.
- **Local only:** a session token is required on every request (header `X-Token`, or `?token=` for images, since an `<img>` tag cannot send headers); `main.py` (C5d) binds to `127.0.0.1`. Errors: 401 no token, 404 not found, 400 refused action (with the reason), 409 needs confirmation, 422 malformed request.

**Done when:** every action needed by C5e works through the API on the sample book, undo restores the exact state, a capture shows progress and can be cancelled. *Met. On a real server with the sample pages: capture through the API in about 10 s (2 pages, 22 lines, 854 samples, 54 groups, 236 unsure); labelling with Gujarati input stores ने / ને; unsure samples come with suggestions; undo, images and the token check work.* The sample actions of C5f (box, join, split, upload) come with C5f.
**Tests (36):** actions (22): undo and redo give back the exact state for every action; six actions undone in a row return to the start; a new action clears redo; labels in both scripts and refused labels change nothing; locked groups refuse changes; new group codes; distances follow the groups; deleted samples leave their group; another book's samples and groups are refused; suggestions; history; adding pages changes nothing else and the new samples get suggestions; re-cut keeps other pages, needs confirmation over manual work, keeps labelled groups; a cancelled capture changes neither database nor files. API (14): token required; images served, nothing outside the book; book create / rename / delete with settings and errors; page problems; capture job with progress and the 409 confirmation; one job per book and cancel; add pages and re-cut through jobs; a full review round trip with undo of everything; deleted listing and restore; bad requests; label check; group fields. Disabling undo, the recomputation, clearing redo, the lock, the member snapshot, the token check or the path check makes tests fail.

**Changes from the original plan (C5c):**
- **Jobs run in a background thread, not a worker process per job:** the pages are already cut in worker processes by `process_folder`; a thread keeps the progress and the database work in the app process, which is simpler and safe with SQLite in WAL mode.
- **Runs write into a work folder first** (new). Without it a cancelled or failed capture would have deleted the book's letter images while the database still pointed at them.
- **`centres.py` added** for centres, distances and suggestions, shared by the actions and the library (re-cut).
- **Extra actions and reads:** dissolve a group, history, undo / redo counts, the deleted-samples list; "split a group" is "new group from selection" rather than a separate action.
- **Re-cut with confirmation clears the undo history**, because recorded states may refer to samples that no longer exist.
- **Errors have their own types** (`NotFound` -> 404, `BookHasReviewError` -> 409 with `code: needs_confirmation`), so the screens can react without reading messages.
- **The page total is known when a job starts**, so the screen can show "0 of 12" instead of "0 of 0".

#### C5d. App shell, Books and Capture screens

**Status: planned.**
**Goal:** the app starts like a desktop app, in its own window or in the browser, and handles books and capture.
**Files:** `app/main.py`; `frontend/` (Vite + React + TypeScript): `src/api.ts` (the one way to call the backend), `src/screens/Books.tsx`, `src/screens/Capture.tsx`; `tests/test_main.py`; frontend tests in `frontend/src/**/*.test.tsx`. New dependencies: `pywebview` (Python); React, TypeScript, Vite, Vitest, Testing Library (Node, development only).

**What it does:**
- `app/main.py`: on first start, ask for the library folder (default `Documents/Manuscript Letters`) and remember it in the user's settings; create a random session token; start `create_app(library, token)` (C5c) with uvicorn on `127.0.0.1` with a free port; serve the built screen at `/` with the token written into the page, so `src/api.ts` sends it as `X-Token` and adds `?token=` to image URLs (C5c returns image URLs with it already); open **its own window** (pywebview) or, with `--browser` or from the menu, the **default browser**. If the window engine is missing (old Windows without WebView2), open the browser instead.
- **Books** screen: the books (name, pages, samples, groups, labelled share, unsure, last change in local time); create (name, input folder: a folder dialog in the window, a path field in the browser); open, rename, delete (with confirmation); page problems (missing, changed, new) shown on the book.
- **Capture** screen: settings (defaults; load a config file), Start, progress (polling `GET /api/jobs/{id}`: pages done of total, per-page status as in `report.csv`), Cancel, summary; a 409 `needs_confirmation` answer shows the "has manual work" confirmation and repeats the call with `force`; add new pages / re-cut a page (C5c jobs).

**Done when:** a book can be created from `samples/`, captured with visible progress, closed and reopened, in window and in browser mode on macOS, and in the Windows build (C7).
**Tests:** the backend serves the built screen and refuses requests without the token (Python); Books list, create form and capture progress with a mocked API (Vitest); type check.

#### C5e. Group review and labeling

**Status: planned.**
**Goal:** clean and label all groups of a book without leaving the app (FR-7, FR-8).
**Files:** `frontend/src/screens/Groups.tsx`, `GroupView.tsx`, `Unsure.tsx`, `components/SampleGrid.tsx`, `components/LabelPicker.tsx`; tests next to them. New dependencies (Node): `@dnd-kit/core` (drag and drop), `@tanstack/react-virtual` (large grids).

**What it does:**
- **Groups** list (`GET /api/books/{id}/groups`): code, label (Gujarati, with Devanagari on hover), sample count, red / black share, status, locked; filter (unlabelled, reviewed, large spread = possibly mixed; empty groups shown last with "dissolve"), sort.
- **Group** view: samples as a grid, nearest to the centre first, only the visible part loaded; select by click, shift-click, box; **drag** to `Unsure` or to a group in the side list; **New group from selection**; **Merge** with another group; **Delete** (specks).
- **Unsure** view: the same grid; select and **create a group**, or drop on a group; each sample shows its **suggested group**, accepted with one key.
- **Label** a group: type in Devanagari or Gujarati, or the **on-screen picker** (consonant, halant for a conjunct, matra, anusvara / visarga; Devanagari / Gujarati switch); live check through the API; shown in both scripts with code points; mark **reviewed** / **lock**.
- **Undo / redo** (Ctrl+Z / Cmd+Z, Shift for redo; `POST /undo`, `/redo`, counts returned with every action) and keyboard keys for the main actions; a history panel (`GET /history`).
- All of these call the C5c actions (`move`, `new-group`, `merge`, `dissolve`, `label`, `status`, `delete`, `restore`); refused actions show the reason the API returns.

**Done when:** on the sample book, the mixed groups listed in `docs/TUNING.md` (ता / ना, नि / ति, नो / तो ...) can be cleaned and labelled in the app, and everything is still there after a restart.
**Tests:** selection, drag and the label picker with a mocked API (Vitest); the picker builds क्षि and શ્રી correctly; a large group (2000 samples) stays responsive (render count check).

#### C5f. Fixing cuts and adding samples

**Status: planned.**
**Goal:** fix the cutting errors of C3b by hand (FR-8: "fix a wrong cut ... must be quick") and add letters the cutting missed.
**Files:** `app/samples.py` (new samples from a box, join, split, upload), routes in `app/api.py`, `frontend/src/screens/PageViewer.tsx`; `tests/test_samples.py`. New dependency (Node): `react-image-crop`. The new actions record their before / after states with the same mechanism as C5c (`actions._Change`), so undo, redo and history cover them too; new samples get a fingerprint, so C5c's suggestions work for them.

**What it does:**
- **Page / line viewer:** the page or one line with every sample's box, coloured by group; click a box to open its group.
- **Draw a box** on a line or page: a new sample from the ink inside the box (the page's C1 ink masks, computed on demand and cached in the book folder), source `cropped`; samples it overlaps are offered for deletion.
- **Join** two neighbouring samples (union of their masks); **split** a sample at a column (drag a line); source `joined` / `split`; the old samples are kept as deleted, so undo works.
- **Upload** a letter image: ink found with the C1 colour rules (no text block needed), source `uploaded`, no page position (shown as such; the export marks it).
- Every new sample gets its image, mask, fingerprint and a suggested group.

**Done when:** on the sample book, the cutting errors listed in `docs/TUNING.md` (ज्ञा + नं, the split श्री, a split ॥ ...) can be fixed in the viewer, and the fixed samples group with their letters.
**Tests:** a box around a known synthetic letter gives exactly its ink; join and split give the expected masks; uploaded images get a mask and fingerprint; undo of each.

#### C5g. Export (FR-9, FR-10)

**Status: planned.**
**Goal:** the output folder of FR-9 and the summary of FR-10, built from a book's database, for Phase 2 training.
**Files:** `app/export.py`, an Export button in the screens (after C5d), `tests/test_export.py`. Can be built and tested before the screens, from the library API.

**What it does** (to `exports/<date>/` in the book folder, or a chosen folder):
- uses C5b's `category()`, `sort_key()`, `safe_name()`, `transliterate()` and `unmapped()` with the book's mapping (`mapping_for`);
- `dataset/<category>/<safe name>/`: every sample of each **labelled** group (`original` crop by default; `normalized` black on white and `fixed64` 64 x 64 as options), `label.txt` with the Gujarati label; categories from C5b;
- `lines/<page>_L01.png` + `.txt`: Gujarati text of each line from the labelled letters in reading order (`[?]` for unlabelled ones);
- `letters.csv` (Gujarati label, Devanagari form, code points, transliteration, category, sample count, example image), `samples.csv` (as now, plus label, source and group status), `overview.html` (one example per class in alphabet order, classes under `min_samples_warn` highlighted, works offline), `unsure/` (unlabelled samples), `summary.txt` (pages, lines, letters, classes, classes with few samples, unsure, skipped files, letters with no Gujarati equivalent).

**Done when:** after labelling a few groups of the sample book, the export is complete and Gujarati shows correctly in Excel and in the browser on Windows and macOS.
**Tests:** export of a small labelled synthetic book: folder names, `label.txt`, CSV columns and `utf-8-sig`, alphabet order in `overview.html`, `[?]` in line text, uploaded samples marked, nothing written outside the export folder.

### C6. Desktop GUI: merged into C5

The planned Tkinter window (folders, Run, progress, open the output) is the C5d app shell.

### C7. Packaging for Windows and macOS

**Goal:** a downloadable app for both platforms.

- Build the React screen first (`npm ci && npm run build` into `app/static/`), then PyInstaller with an `app_entry.py` (with `freeze_support()`) that starts the app; `build_macos.sh` and `build_windows.bat` from the border remover, renamed to `LetterExtractor`.
- Bundle `data/mapping_dev_guj.csv`, the built screen and the Alembic migrations with `--add-data`; load them through a helper that works from source and from the frozen app (`sys._MEIPASS`).
- The CLI stays available (`LetterExtractor --cli ...` or a separate console executable).
- **Windows:** pywebview uses Microsoft Edge WebView2, preinstalled on current Windows 10 and 11; if missing, the app opens in the browser instead. **macOS** uses the built-in WebKit.

**Output:** `dist/LetterExtractor.app` (macOS), `dist/LetterExtractor/LetterExtractor.exe` (Windows).
**Done when:** each build creates a library, captures the two sample pages and reopens the book on a clean machine of its OS, in window and in browser mode.
**Note:** unsigned apps trigger SmartScreen (Windows) and Gatekeeper (macOS). Fine for internal use; signing is a separate task. Node.js is needed only to build, not to run the app.

### C8. GitHub Actions

**Goal:** tests on every push and pull request, builds for both platforms, releases from tags.

- Copy `.github/workflows/build.yml` from the border remover and extend it:
  - `test` job on `ubuntu-latest`, Python 3.10 and 3.13: `python -m unittest discover -s tests` (core and API);
  - `frontend` job: `npm ci`, type check, unit tests (Vitest), `npm run build`; the build is passed to the platform builds;
  - `build` job on `macos-latest` and `windows-latest` (needs both), zip and upload the app;
  - `release` job on `v*` tags, attaches both zips to a GitHub release.
- Smoke step: run the CLI on `samples/` and check 22 lines; create a library and import `samples/` through the API.

**Done when:** a PR shows green tests and both build artifacts; tagging `v0.1.0` creates a release.

### C9. Label suggestions (after first delivery)

Most of the original C9 (review screen, fixing cuts, decisions kept across runs) is now C5e and C5f. What remains:
- **Label suggestions** for unlabelled groups from a Phase 2 recognizer, or from an AI service as an **opt-in** only (manuscripts may be private; offline by default).
- Better fingerprints learned from the labelled groups, measured with the labels instead of by eye.

### Chunk summary

| # | Chunk | Status | Main output | Requirements |
|---|---|---|---|---|
| C0 | Read input folder, skeleton | done | `report.csv` | FR-1 |
| C1 | Page preparation | done | `debug/*_ink.png` | FR-2 |
| C2 | Line detection | done | `lines/*.png`, `debug/*_lines.png` | FR-3 |
| C3a | Stroke pieces | done | `debug/*_pieces.png` | FR-4 |
| C3b | Letters | done | `letters/`, `samples.csv` | FR-5, FR-6 |
| C4 | Grouping | done | `groups/`, `unsure/`, `groups.html` | FR-7 |
| C5a | Library and database | done | `library.db`, books | FR-7, FR-8 |
| C5b | Unicode mapping | done | `mapping.py`, `mapping_dev_guj.csv` | Section 4 |
| C5c | Backend API | done | review actions, capture jobs, undo | FR-7, FR-8 |
| C5d | App shell, Books, Capture | **next** | own window and browser | FR-1, Section 7 |
| C5e | Group review and labeling | planned | clean, labelled groups | FR-7, FR-8 |
| C5f | Fixing cuts, adding samples | planned | cropped / joined / split / uploaded samples | FR-8 |
| C5g | Export | planned | `dataset/`, `lines/*.txt`, `letters.csv`, `samples.csv`, `overview.html`, `summary.txt` | FR-9, FR-10 |
| C6 | GUI | merged into C5d | - | Section 7 |
| C7 | Packaging | planned | `.app`, `.exe` with the React screen | Section 7 |
| C8 | GitHub Actions | planned | CI (Python, API, React), builds, releases | Section 7 |
| C9 | Label suggestions | planned | suggested labels (opt-in) | FR-7 |

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
| `fp_pixels`, `fp_blur` | C4 | 24, 1.0 |
| `group_distance` | C4 | 0.55 |
| `group_outlier_distance` | C4 | 0.5 |
| `min_group_size` | C4 | 2 |
| `save_masks`, `write_groups` | C5a | `False`, `True` (the app sets `True`, `False`) |
| `digits` | C5b | `gujarati` (or `western`) |
| `mapping_file` | C5b | empty = the built-in `data/mapping_dev_guj.csv` |
| `dataset_image` | C5g | `original` (or `normalized`, `fixed64`) |
| `min_samples_warn` | C5g | 10 |

---

## 6. Testing

- **Synthetic tests (`tests/synthetic.py`):** draw fake pages with OpenCV: N slanted, wavy headlines; blocks with known gaps; vowel-bar-like pieces; red and black strokes. They check line count, headline position, break positions and letter counts with exact expected values.
- **Sample pages:** regression checks on `samples/page1.jpg` and `page2.jpg`: 11 lines per page; letter count within a range that is fixed once C3b is tuned.
- **Output checks:** CSV columns, `utf-8-sig`, safe folder names, labels surviving a re-run, input folder unchanged.
- Run locally and in CI with `python -m unittest discover -s tests -v` (`PYTHONPATH=src`).
- **App (C5):** backend routes and review actions are tested with FastAPI's test client on small synthetic books (an in-memory or temporary SQLite database); the React screen has component tests (Vitest + Testing Library) and a type check; the database migrations are tested by creating a library from scratch.
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
| FR-7 Grouping and labeling | C4, C5e | `features.py`, `grouping.py`, `app/api.py`, Groups screen |
| FR-8 Review screen | C5c, C5e, C5f | `app/actions.py` (actions, undo / redo), `app/api.py`, Groups and Page viewer screens |
| FR-9 Output folder | C5g | `app/export.py`, `mapping.py`, `report.py` |
| FR-10 Report | C0, C5g | `report.py`, `app/export.py` |
| Desktop app, Windows and macOS | C5d, C7, C8 | `app/main.py`, `frontend/`, `packaging/`, `.github/workflows/` |
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
| scikit-learn makes the installer large | Avoided: grouping is plain NumPy (C4). |
| Team is new to React | TypeScript (errors found while typing), few libraries, plain CSS, one way of calling the backend, small screens built one chunk at a time, component tests (Vitest). |
| WebView2 missing on an older Windows | The app falls back to the default browser. |
| Database changes in later versions | Alembic migrations from the first version; a book's settings are stored with it. |
| A capture writes while the user reviews | SQLite in WAL mode, short transactions, one job per book; capture over manual work needs confirmation; runs install their files only when finished (work folder). |
| Re-running extraction undoes manual work | Samples have a stable identity (page checksum + box); re-cutting a reviewed page asks first; labelled groups are never changed automatically. |
| Large books feel slow in the screen | Thumbnails load lazily, grids show one screen at a time (virtual scrolling), images are served from disk, not from the database. |
| Many groups on very large batches | The merge step runs for up to `group_max_merge` (5000) groups after the first pass; beyond that only the first pass and reassignment run. Raise it, or group book by book. |

---

## 9. Decisions to Confirm

From Section 9 of the requirements, with a proposed default:

1. **Digits:** Gujarati (૧૨૩) by default, Western as a setting.
2. **Rare letters** with no Gujarati letter: **decided in C5b:** written as Gujarati letter + nukta where Gujarati has the base letter (ऩ -> ન઼, ऱ -> ર઼, ऴ -> ળ઼, क़ -> ક઼ ...); characters with no Gujarati form at all are kept in Devanagari and listed in the summary. The rule can be changed in `data/mapping_dev_guj.csv`.
3. **Anusvara and visarga:** proposed as part of the letter class (કં), open for confirmation; the mapping and grouping work either way.
4. **Red and black ink:** share classes; the ink colour is kept in `samples.csv`.
5. **Cloud use:** offline only for Phase 1; AI suggestions are a C9 opt-in.
6. **Other manuscripts:** all cutting rules use settings, not fixed values, so another hand needs a new config file, not new code.
7. **GUI:** ~~Tkinter~~ **decided (2026-10-04): a review app with a React (TypeScript) screen and a Python (FastAPI) backend**, opening in its own window and in the browser (C5).
8. **Storage: decided: SQLite**, one person per computer; through SQLAlchemy / Alembic so MySQL or PostgreSQL can follow.
9. **Labels: decided: entered in Devanagari or Gujarati** (typed or with the on-screen picker), stored in Devanagari, shown in Gujarati.
10. **Books: decided:** every run belongs to a book; earlier books can be reopened from the Books screen.

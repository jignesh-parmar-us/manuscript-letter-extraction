# Manuscript Letter Extraction: Implementation Plan

Desktop tool (Python) that reads scanned manuscript pages, cuts out every letter (akshara) with its matras, groups identical letters and writes a labeled dataset with CSV and HTML reports.

This plan implements **Phase 1** of `requirements-fetch-text.md` (FR-1 to FR-10). Phases 2 and 3 (OCR training and conversion) are out of scope, but the output is designed for them (`dataset/`, `lines/`, reading order in `samples.csv`).

The work is split into **small chunks (C0 to C9)**. Each chunk ends with a CLI you can run on the sample pages, and output you can check by eye, before the next chunk starts.

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
│   ├── debug.py           # overlays drawn on the page for every stage
│   └── pipeline.py        # process_page(), process_folder()
├── tests/
│   ├── synthetic.py       # draws fake pages with known lines and breaks
│   └── test_*.py
├── samples/               # page1.jpg, page2.jpg, cleaned/ (copied from border remover)
├── packaging/             # gui_entry.py, build_macos.sh, build_windows.bat  (C7)
└── .github/workflows/build.yml                                              (C8)
```

The core (`pipeline.py` and everything it calls) has no GUI or CLI code, so the CLI and the GUI call the same functions.

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

Data passed between steps (plain dataclasses in `pipeline.py`):

```python
@dataclass
class Line:
    index: int                 # 1-based, top to bottom
    top: int; bottom: int      # band incl. upper and lower matras
    headline_y: np.ndarray     # headline row for every column (follows slope and waves)
    ink: str                   # "black" | "red" | "mixed"

@dataclass
class Letter:
    page: str; line: int; pos: int          # reading order (FR-6)
    bbox: tuple[int, int, int, int]         # x, y, w, h in page coordinates
    mask: np.ndarray                        # ink pixels that belong to this letter only
    ink: str                                # "black" | "red"
    kind: str                               # "letter" | "danda" | "digit" | "mark"
    group_id: str = ""; label: str = ""; confidence: float = 0.0
```

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

### C1. Page preparation (FR-2)

**Goal:** a clean ink mask for each page, with red and black ink separated.

- Accept pages already cleaned by the border remover (`samples/cleaned/`) or raw pages.
- **Paper mask:** exclude the black scanner background (dark pixels connected to the image edge).
- **Paper tone:** estimate the background with a large median blur, then divide by it to flatten uneven paper tone.
- **Ink masks:**
  - black ink: dark after flattening (adaptive or Sauvola-style threshold);
  - red ink: high `a*` channel in Lab with its own, lower thresholds (it is lighter and thinner).
- **Text block:** largest region of dense ink rows and columns; drop the ruled border, margin folio numbers and tape marks outside it.
- Remove specks smaller than `min_speck_px`.

**Output:** `debug/<page>_ink.png` (black ink in black, red ink in red, discarded areas greyed out).
**Done when:** on both sample pages the text block is found, the border and folio numbers are outside it, and red verses are fully in the red mask.

### C2. Line detection (FR-3)

**Goal:** find all text lines and trace each headline.

1. Horizontal projection of the ink mask inside the text block. The **headline rows are the strongest peaks**, about 110 px apart (expected spacing is a setting, auto-estimated per page from the peak distances).
2. **Follow the headline:** split the line into column windows (for example 150 px), find the peak row in each window near the global peak, and smooth / interpolate it into `headline_y[x]`. This handles slope and waviness.
3. **Line band:** from the midpoint to the previous headline down to the midpoint to the next one, measured along the traced headline (not a straight row).
4. **Assign matras:** each connected component that crosses a band boundary goes to the headline it is closest to, judged by its position relative to each headline (upper matras sit just above a headline, lower matras just below the main zone).
5. Mark each line `black`, `red` or `mixed` from its ink share.

**Output:**
- `lines/<page>_L01.png`, ... one cropped image per line (paper background, only that line's ink kept);
- `debug/<page>_lines.png` with the traced headlines and band edges drawn.

**Done when:** 11 of 11 lines found on both sample pages, headlines follow the ink, and a visual check finds no matras on the wrong line.
**Tests:** synthetic page with N slanted, wavy fake headlines → N lines, headline error ≤ 2 px.

### C3a. Stroke pieces: headline breaks (FR-4)

**Goal:** the first cut, exactly as the trial in the requirements (Section 2).

- Take a thin **headline band** (± `headline_half_height` px around `headline_y[x]`).
- Column has a **break** if the band has no ink in it. Ignore breaks narrower than `min_break_px` (≈ 2 px).
- Cut the line at each break into **stroke pieces**. Each piece takes all ink below its part of the headline down to the bottom of the main zone.
- Pieces with less ink than `min_piece_ink_px` are specks and are dropped.

**Output:** `debug/<page>_pieces.png` with a thin vertical line at every cut, numbered pieces.
**Done when:** results match the trial: black lines show most letter boundaries (with extra cuts at vowel bars and missing cuts at touching headlines); this is the baseline the next chunk corrects.

### C3b. Letters: join and split rules (FR-5, FR-6)

**Goal:** turn stroke pieces into letters and save each one as an image.

Rules applied in order, all thresholds in `Config` with separate red and black values:

1. **Typical letter width** per line = median piece width (robust to errors).
2. **Join vowel bars** (ा ी ो ौ): a narrow piece that is mostly one vertical stroke with a short headline joins the piece on its **left**.
3. **Join ि**: the hook piece (curl above the headline on its left side) joins the piece on its **right**.
4. **Join broken letters:** a piece narrower than `min_letter_width_ratio` × typical width, with no bar shape, joins the neighbour it touches most.
5. **Split wide pieces:** wider than `split_width_ratio` (1.6) × typical width → split at the column with the lowest ink count in the main zone below the headline, repeat if still too wide.
6. **Attach marks:** components above the headline (ि ी े ै ो ौ, ं, र्, ँ) and below the main zone (ु ू ृ ्) go to the letter they overlap most horizontally.
7. **Dandas, digits and punctuation:** tall thin strokes without a headline (।, ॥), and small isolated shapes in red verse numbers, get `kind = "danda"` / `"digit"`.
8. **Ink mask per letter:** only the pixels of components (or component parts) assigned to that letter, so ink from neighbours is left out (FR-6).

**Output:**
- `letters/<page>/L01_003.png`: crop with a small margin, paper background, foreign ink painted out;
- `samples.csv`: page, line, pos, x, y, w, h, ink, kind (one row per letter);
- `debug/<page>_letters.png`: one coloured box per letter.

**Done when:** for both sample pages, count missed breaks, extra breaks and wrongly attached matras, and record them in a tuning table in `docs/TUNING.md` (as Section 8.4 of the requirements asks). Tune until most letters on black lines are cut right; record the red-line numbers separately.
**Tests:** synthetic line with a known number of blocks and vowel-bar-like pieces → expected letter count.
**Performance:** add the process pool here; check ≤ 10 s per page.

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

| Setting | Chunk | Default (black / red) |
|---|---|---|
| `paper_blur_px` | C1 | 51 |
| `black_threshold`, `red_min_a` | C1 | to tune |
| `min_speck_px` | C1 | 8 / 5 |
| `line_spacing_px` | C2 | 0 = auto (≈ 110) |
| `headline_window_px` | C2 | 150 |
| `headline_half_height` | C3a | 3 / 2 |
| `min_break_px` | C3a | 2 / 3 |
| `min_piece_ink_px` | C3a | 15 / 10 |
| `bar_max_width_ratio` | C3b | 0.35 |
| `min_letter_width_ratio` | C3b | 0.45 |
| `split_width_ratio` | C3b | 1.6 |
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

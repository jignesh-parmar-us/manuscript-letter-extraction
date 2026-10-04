# manuscript-letter-extraction

Letter extraction. Read every page in an input folder, cut out every letter with its matras, group identical letters, and write an image of each one to an output folder. A person maps each unique letter to its Gujarati Unicode text (for example the image of कि is mapped to કિ).

Requirements: [docs/requirements-fetch-text.md](docs/requirements-fetch-text.md). Plan and chunks: [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).

**Status:** C0 (read the input folder), C1 (page preparation), C2 (line detection), C3a (first cut into stroke pieces) C3b (letters) and C4 (grouping identical letters) are done: about 92% of letters are cut correctly on the sample pages, and their 854 letters form 54 groups ([docs/TUNING.md](docs/TUNING.md)). The review app (C5) is under way: C5a (library of books in a SQLite database), C5b (Devanagari / Gujarati labels) C5c (backend API with review actions and undo), C5d (the app window with the Books and Capture screens), C5e (the group review and labeling screen), C5f (fixing cuts in a page viewer) and C5g (the export of the dataset) are done. Packaging for Windows and macOS (C7) and the GitHub build (C8) come next.

## Install

Python 3.10 or newer on Windows or macOS. Use a virtual environment:

```
python3 -m venv .venv                      (Windows: py -3 -m venv .venv)
.venv/bin/pip install -r requirements.txt  (Windows: .venv\Scripts\pip install -r requirements.txt)
```

The commands below use `python`; run them with `.venv/bin/python` (Windows: `.venv\Scripts\python`) or after activating the environment.

## Use

```
export PYTHONPATH=src          (macOS / Linux)          set PYTHONPATH=src          (Windows)
python -m letter_extractor --input samples --output out --debug
```

Options:

| Option | Meaning |
|---|---|
| `--input`, `-i` | Folder with the page images (`.jpg .jpeg .png .tif .tiff .bmp`), read in name order (page2 before page10). Only read, never changed. |
| `--output`, `-o` | Folder for the results; created if missing. Must differ from the input folder. |
| `--config`, `-c` | JSON file that overrides settings in [config.py](src/letter_extractor/config.py), for example `{"black_max_rel_l": 0.6, "red": {"min_speck_px": 4}}`. |
| `--workers`, `-w` | Parallel processes (default: automatic). |
| `--debug` | Save an overlay of each step to `<output>/debug/`. |

The exit code is 0 if every page is OK, 1 if some pages failed, and 2 for a folder or config error.

## Output so far

- `report.csv`: one row per file with status (`OK`, `NO_TEXT`, `FAILED`, `IGNORED`), message, page size, text block (`block_x/y/w/h`), black and red ink pixel counts, number of lines, line spacing, number of stroke pieces, specks dropped, letters, dandas, digits, and seconds. Files that cannot be read are `FAILED` and do not stop the run; files that are not images are `IGNORED`.
- `letters/<page>/L01_003.png`: one image per letter (line 1, third letter), cut from the original page with a 4 px margin; ink of neighbouring letters is filled in from the paper around it.
- `samples.csv`: one row per letter of all pages, in reading order: page, line, position, box (x, y, w, h), ink colour, kind (`letter`, `danda`, `digit`), number of stroke pieces joined, the join / split rules applied, the image path, the letter group (`group_id`, or `unsure`) and the distance to the group's centre.
- `groups.html`: every group as a row of its samples (nearest to the group's centre first) with sample counts, then the unsure samples. Hover a sample to see its page, line and position. Opens offline in any browser.
- `groups/g0001/`, ...: the letter images of each group, largest group first; `unsure/`: samples that fit no group (often letters that occur only once). Both are replaced on every run.
- `lines/<page>_L01.png`, ...: one image per text line, cut from the original page with a small margin. Matras that reach into the neighbouring lines are kept; ink of the neighbouring lines is filled in from the paper around it.
- `debug/<page>_ink.png` (with `--debug`): black ink in black, red ink in red, removed ruled lines in blue, everything outside the text block greyed out, text block outlined in green.
- `debug/<page>_lines.png` (with `--debug`): each line's ink in its own colour (a matra in the wrong colour is on the wrong line), traced headlines as thin dark lines, boundaries between lines dashed.
- `debug/<page>_pieces.png` (with `--debug`): stroke pieces in alternating colours with their numbers, a thin red line at every cut, and ink outside the pieces (upper and lower matras, left for C3b) in light purple.
- `debug/<page>_letters.png` (with `--debug`): each letter in its own colour with a box around it; dandas grey, digits magenta, letters made by a split with a dashed red box.

## How page preparation works (C1)

1. **Paper:** dark areas touching the image edge are the scanner background.
2. **Paper tone:** the local paper colour is a wide median (151 px) on a quarter-size copy, so uneven tone and stains are followed. A narrower window is pulled towards the ink colour inside dense red text.
3. **Ink:** red ink is clearly redder (Lab a*) and somewhat darker than the local paper; black ink is much darker than the local paper. The yellow border band is not red, so it is not ink.
4. **Ruled lines:** straight ink runs longer than 15% of the page are border rules and are removed from the ink.
5. **Text block:** the main run of ink-dense columns and rows. Folio numbers in the margin cover only a few lines, so they fall outside it.
6. **Specks:** blobs smaller than `min_speck_px` (set separately for red and black ink) are removed.

Raw scans and pages cleaned by the border remover both work. Letters that touch a border rule may lose the pixels where they cross it, so cleaned pages are preferred.

## How line detection works (C2)

1. **Headlines:** only horizontal ink runs (25 px or longer) are used, so stems, dandas and matras drop out. Their row profile has one peak per line; the line spacing comes from its autocorrelation (about 112 px on the samples) unless `line_spacing_px` is set.
2. **Tracing:** each headline is followed in 150 px windows near its peak. Windows far from a smooth curve through all windows (dandas, runs of big matras) are replaced by the curve, so slope and gentle waves are followed but not jumps.
3. **Main zone and boundaries:** the main zone ends where the ink below the headlines drops off (about 57 px). Between two lines the boundary follows the emptiest rows below that.
4. **Matras to lines:** every ink blob is assigned whole. A blob touching one headline belongs to that line, even if it reaches past the boundary. A blob touching two headlines (two lines' matras touching) is split at the boundary. A detached blob (anusvara, a dot, a loose matra) goes to the line it is closer to: just above the headline below, or just below the main zone above.
5. **Ink colour per line:** `red` or `black` if at least 80% of the line's ink has that colour, otherwise `mixed`.

On both sample pages all 11 lines are found, and a page takes about 2 s (without `--debug`).

## How the first cut works (C3a)

The headline is drawn letter by letter. Between two letters it either has a gap or, where the strokes overlap, thins out sharply. On the sample pages the red headlines are almost continuous but thin to 1-3 px at every join, so looking only for empty columns misses most red letter boundaries.

1. **Headline thickness** is measured in every column, in a band from 8 px above to 4 px below the traced headline (letter bodies start lower).
2. **Breaks:** a run of columns where the headline is thinner than half its typical thickness, and somewhere thinner than 30% of it. Runs narrower than `min_break_px` are ignored. Limits are set separately for red and black ink.
3. **Cuts:** inside a break the cut goes through each empty column run of the main zone, otherwise through the column with the least ink. A danda or digit standing in a gap becomes its own piece.
4. **Pieces** take the line's ink in their columns, from just above the headline to the bottom of the main zone. Pieces with less ink than `min_piece_ink_px` are dropped as specks. Each piece records its ink colour, the width of its headline ink and the width of its stems, for C3b.

Result on the sample pages: about 36-46 pieces per line. As in the trial in the requirements, black lines show most letter boundaries, with extra pieces where vowel bars (ा ी) have their own short headline and missed cuts where headlines run into each other. Red lines have more of both: about a quarter of their pieces are narrow (bars, ि hooks) and a fifth are wider than 1.6 x the typical piece. C3b corrects these.

## How letters are made (C3b)

Stroke pieces are joined and split by rules, in this order (details and the reasons behind them: [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md), C3b):

1. **Narrow pieces:** a tall stroke with a mark touching it from above is an i-matra bar; if the mark leans right it is the short-i hook (ि) and joins the letter on its right, otherwise long-i (ी) and joins left. A stroke whose headline runs into its left neighbour, or is wider than its stem, is a vowel bar (ा ो ौ) and joins left. Other tall strokes are dandas (two close together are one ॥). Anything else (broken strokes, visarga) joins the neighbour it touches most.
2. **Short-i stems in the previous letter:** a curl that rises near a letter's right edge and arches over the next letter marks a ि stem; the stem moves to the next letter.
3. **Wide letters** (over 1.4 x the page's typical letter width) are split where there is an empty column between two letter bodies, or anyway when over 2.2 x. Joined bars and ि stems are never cut off.
4. **Marks** above and below the letters go to the letter they touch most, otherwise the one they overlap most.
5. **Digits:** one or two short letters between dandas.

Black ink is cut almost perfectly; red ink, whose headlines run into each other, has most of the remaining errors. They are listed with their causes in [docs/TUNING.md](docs/TUNING.md).

## How letters are grouped (C4)

1. **Fingerprint:** each letter's ink is cropped, padded to a square and scaled to 48 x 48 px. Its fingerprint combines a 24 x 24 picture of the ink, the directions of its strokes (HOG) and its size relative to the line spacing. Paper tone and ink colour play no part, so red and black samples of a letter group together.
2. **Clustering** (plain NumPy, no extra dependency): a sample joins the nearest group within `group_distance`, otherwise it starts a new one. Then close groups merge, but only if the merged group stays compact (`group_outlier_distance`); without that check, groups creep from letter to look-alike letter.
3. **Unsure:** samples far from their group's centre, and groups of a single sample.

Letters that look nearly the same in this hand (ता / ना, नि / ति, त / न) may share a group; they are split when labelling or in the review screen (C9). Raise `group_distance` for fewer groups and fewer unsure samples but more mixed groups; lower it for the opposite.

## Labels and the Gujarati mapping (C5b)

Every letter group gets a label: one letter (akshara) such as क, कि, क्ष, श्री, र्म, a digit or a danda. It can be typed in **Devanagari or Gujarati** (कि and કિ are the same label); it is stored in Devanagari and shown in Gujarati.

```python
from letter_extractor.mapping import describe, to_gujarati
describe("કિ")      # {'ok': True, 'devanagari': 'कि', 'gujarati': 'કિ', 'category': 'consonants', 'safe_name': 'ki__U0A95-U0ABF', ...}
describe("कम")      # {'ok': False, 'error': 'more than one letter: क + म'}
to_gujarati("श्री॥१")  # 'શ્રી॥૧'
```

The mapping follows Section 4 of the requirements: each Devanagari character becomes the Gujarati character with the same Unicode name; dandas stay Devanagari; letters without a Gujarati letter (ऩ ऱ ऴ, क़ ...) are written as letter + nukta; characters with no Gujarati form at all are kept in Devanagari. The exceptions are in the editable file [data/mapping_dev_guj.csv](src/letter_extractor/data/mapping_dev_guj.csv); a book can use its own copy (`mapping_file` setting), and digits can be Gujarati (૧૨૩, default) or Western (`digits: "western"`).

## The library of books (C5a, used by the app)

The review app keeps its work in a **library folder** (default `Documents/Manuscript Letters`) with a SQLite database (`library.db`) and one folder per book. Until the app screens exist (C5d), it can be used from Python:

```python
from pathlib import Path
from letter_extractor.app.library import Library

lib = Library(Path("~/Documents/Manuscript Letters").expanduser())
book = lib.create_book("My manuscript", Path("pages"))     # input pages are only read, never changed
print(lib.capture(book.id))                                # cut, group and store: pages, lines, samples, groups
print(lib.list_books())
print(lib.check_pages(book.id))                            # missing / changed / new input pages
```

Capturing a book again replaces its automatic results; it is refused once the book holds manual work (labels, reviewed groups), unless `force=True`.

## The app (C5d)

Build the screen once (and after every change in `frontend/`), then start the app:

```
cd frontend && npm install && npm run build && cd ..
python -m letter_extractor.app               # its own window
python -m letter_extractor.app --browser     # or in the web browser
python -m letter_extractor.app --library "/path/to/My Library"   # another library folder (remembered)
```

The **Books** screen lists the books of the library and creates new ones (a name, the folder with the page images, and whether the book is **handwritten or printed**; this can be changed later in Pages & capture). A book's **Pages & capture** tab cuts the pages into letters with a progress bar, adds new pages later, cuts single pages again, and holds the book's settings.

The **Review groups** tab is where the letters are sorted and labelled: the groups on the left (with filters such as *without label* or *possibly mixed*), the chosen group's samples on the right. Select samples (click, Ctrl/Cmd+click, Shift+click) and send them to **Unsure** (U), a **new group** (N), another group, or delete them; or drag them onto a group in the list. Label a group by typing in Gujarati or Devanagari, or with the on-screen letters; it is checked as you type. Unsure samples show a suggested group to accept with one click. Ctrl/Cmd+Z undoes, Shift+Ctrl/Cmd+Z redoes.

The **Pages** tab shows a page with a box around every sample, to fix wrong cuts: **Draw a box** around ink that should be one letter (it becomes a new sample, and the samples it covers can be deleted), **Join** selected samples, **Split** a sample where you click, or **Upload letter image…** for a letter the cutting missed. New samples start in Unsure with a suggested group. Everything can be undone.

The **Export** tab writes the book's dataset for OCR training: every sample of each labelled letter in `dataset/<category>/<letter>/` (as cut, black on white, or 64 × 64), the lines with their Gujarati text in `lines/`, the unlabelled samples in `unsure/`, `letters.csv`, `samples.csv`, `overview.html` (every letter at a glance, in alphabet order) and `summary.txt`. It goes into a new dated folder in the library (or a new, empty folder of your choice) and never overwrites anything; **Open the folder** shows it in Finder or Explorer.

If `npm install` fails with `EACCES` on `~/.npm`, an earlier `sudo npm` left root-owned files in npm's cache: run `sudo chown -R $(id -u):$(id -g) ~/.npm` once (or add `--cache /some/other/folder`).

For screen development: `npm run dev` in `frontend/` serves the screen with live reload and passes API calls to a backend on port 8765 (`python -m letter_extractor.app --browser --port 8765`). `npm test` runs the screen tests, `npm run typecheck` the type check.

## Reading lines with Tesseract (Phase 2, C10)

Printed books can be read by [Tesseract](https://github.com/tesseract-ocr/tesseract) to suggest labels (the suggestions come in C11 and C12). Tesseract is a separate install: see [docs/INSTALL_TESSERACT.md](docs/INSTALL_TESSERACT.md). To read one line image and see its aksharas with their boxes:

```
python -m letter_extractor.ocr out/lines/page1_L01.png            # script/Devanagari, one line
python -m letter_extractor.ocr LINE.png --langs hin --hocr line.hocr
```

Tesseract reads print well (about 5% wrong characters on the sample book) but handwriting poorly (about a third wrong), and its confidence stays high either way; see [docs/TUNING_PHASE2.md](docs/TUNING_PHASE2.md).

## The backend API (C5c)

The review app's screens (C5d-C5f) talk to a local web API (FastAPI) that can already be used on its own. It covers books, capture in the background with progress and cancel, adding new pages and cutting one page again without losing review work, the review actions (move samples to a group or to unsure, new group, merge, dissolve, label in Devanagari or Gujarati, reviewed / locked, delete / restore) with **undo and redo**, suggested groups for unsure samples, and the letter, line and page images. It listens on `127.0.0.1` only and every request needs the session token. The route list is at the top of [app/api.py](src/letter_extractor/app/api.py); while it runs, FastAPI also shows interactive documentation at `/docs` (a developer aid; that page loads its scripts from the internet, the app itself does not).

## Tests

```
PYTHONPATH=src python -m unittest discover -s tests -v
```

Synthetic pages ([tests/synthetic.py](tests/synthetic.py)) check folder handling, ink masks line detection (sloped and wavy headlines within 2 px, detached marks on the right line) the first cut (gaps and thin joins cut, tiny gaps and continuous headlines not, a danda as its own piece, in red and black ink) every letter rule (vowel bar, short-i hook, touching letters, upper and lower marks, double danda, visarga) and grouping (synthetic shapes form pure groups, kinds never mix, output folders and `groups.html` agree) against known values. The sample pages in `samples/` check the text block, ink colours, 11 lines per page and the number of letters and dandas on real scans.

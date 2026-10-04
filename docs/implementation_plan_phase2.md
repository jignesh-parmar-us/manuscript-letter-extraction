# Manuscript Letter Extraction: Implementation Plan, Phase 2

Phase 1 (`docs/IMPLEMENTATION_PLAN.md`) cuts every letter out of the pages, groups identical letters, and lets a person label each group and export a dataset. **Phase 2 takes the app from labelled letters to text.** It suggests labels automatically, so that review becomes mostly confirming. It learns this scribe's hand from the labelled books, uses a dictionary to correct unlikely letters, and converts whole pages into Gujarati Unicode text.

The work is split into **small chunks (C10 to C18)**, numbered after Phase 1's chunks. As in Phase 1, each chunk ends with something to run and check by eye, and is a separate commit. Where the implementation turns out different from this plan, the chunk gets a **Changes from the original plan** note, and later chunks are updated in the same commit.

**Status:** C10 is done (2026-10-04): Tesseract reads a line into aksharas, and every book says whether it is **handwritten or printed**. **C11 is next.** Tesseract is a separate install: see `docs/INSTALL_TESSERACT.md`. Measured numbers are in `docs/TUNING_PHASE2.md`.

---

## 0. Scope and how it relates to the requirements

`requirements-fetch-text.md` has three phases: 1 letter extraction, 2 OCR training (FR-11), 3 conversion (FR-12). This plan **merges the requirements' Phases 2 and 3**, as decided on 2026-10-04:

| Part of this plan | Chunks | Requirement |
|---|---|---|
| **A. Label suggestions with Tesseract** (first step, for printed books) | C10, C11, C12 | FR-7 "suggested label", Phase 1's C9 |
| **B. Suggestions for handwriting** from the labelled books | C13, C14 | FR-7, FR-11 |
| **C. Dictionary and language model** | C15 | new (not in the requirements) |
| **D. Whole page to Unicode text** | C16a (training pages and pages to convert), C16b, C17 | FR-12 |
| **E. Line recognizer** (optional, later) | C18 | Section 8.3 of the requirements |

**Why this order:**
- **Tesseract comes first.** It needs no training, it reads printed Devanagari well, and it pays off at once: the printed book (`samples/blackandwhite/`, 4,604 samples in 253 groups) can be labelled mostly by confirming. Each confirmed label also becomes training data for parts B to D.
- **Tesseract cannot read handwriting reliably.** Handwritten books need part B, which learns from the books already labelled, whether printed or handwritten. The handwritten and printed forms of a letter differ, so handwritten books need some labelled handwritten pages of their own. C10 measured about 30 to 35% wrong code points on a line of the sample hand (5% on print), so Tesseract on handwriting is something to **try and measure** (C12), not the default.
- **Each book says how it is written** (handwritten or printed, chosen when the book is created; added in C10). This decides which reader suggests labels by default: Tesseract for printed books, other books (C13) and the classifier (C14) for handwritten books. Tesseract can still be run on a handwritten book on request.
- **Conversion (D) comes last.** It needs a reader for every sample, so it uses group labels, Tesseract and the classifier together, plus the dictionary for correction.
- **Training pages and pages to convert are kept apart** (decided 2026-10-05). A book has two page sets, each with its own folder: the few **training pages** that are cut, grouped and labelled (Phase 1), and the many **pages to convert** into text, which are cut but not reviewed. They stay in one book because they are usually the same manuscript and hand, and share its settings, writing, labelled groups and model. Built in C16a, just before conversion; C11 to C15 only use training pages.

**Phase 1 chunks still open:** C7 (packaging) and C8 (GitHub Actions) are not done yet. Phase 2 can start before them, but each Phase 2 chunk lists what it adds to C7 and C8 (new files to bundle, new CI steps), so that packaging stays a known amount of work. C9 of Phase 1 (label suggestions) **is replaced by C10 to C14 here**; `IMPLEMENTATION_PLAN.md` will point to this file.

---

## 1. Technology choices

| Area | Choice | Why |
|---|---|---|
| Printed OCR | **Tesseract 5** (installed separately), called as a program through `subprocess` | Free, offline, good Devanagari models (`hin`, `san`, `mar`, `script/Devanagari`). Calling the program directly needs no Python package and no compiler. `pytesseract` would only wrap the same call. The default model is `script/Devanagari` (measured in C10). |
| Tesseract output | **hOCR with character boxes** (`-c hocr_char_boxes=1`), and with `-c lstm_choice_mode=2` for alternative readings | Gives a box and a confidence for every character, which is what aligns OCR text to our cut samples (C11). The alternatives feed the dictionary step (C15). |
| hOCR parsing | Python's own `html.parser` | hOCR is HTML. No new dependency. |
| Akshara splitting | Our own rules (`ocr/aksharas.py`) | A Devanagari "letter" in our sense (consonant cluster + matras + marks) is a sequence of code points. The rules are short and must match how Phase 1 cuts. A general Unicode grapheme library splits conjuncts differently. This splits Tesseract's **text**; the cutting of the page images is still Phase 1's, for printed and handwritten books alike. |
| Cross-book suggestions (C13) | **NumPy**, the existing fingerprints (C4) | No new dependency; works on day one with the labelled groups. |
| Letter classifier (C14) | Train with **PyTorch** (CPU); run with **ONNX Runtime** | PyTorch is the standard for small CNNs, but it is large (200+ MB). Running a trained model needs only ONNX Runtime (about 15 to 20 MB), which the app bundles. Training runs in a separate "training" install (see decision 3 in Section 9). |
| Language model (C15) | Akshara n-grams + word list in a trie, **pure Python / NumPy** | Small, explainable, offline. The text has no spaces, so word lookup is a word-break search, not a spell checker. |
| Line recognizer (C18) | **Kraken** or Tesseract fine-tuning (`tesstrain`): to be decided after C17 | Both train from `lines/*.png` + `.txt`, which Phase 1 already exports. |
| Database | Same SQLite / SQLAlchemy / Alembic; **migration `0002`** onwards | New tables and columns only. Existing books open unchanged. |
| Screen | Same React / TypeScript / Vitest | New parts in the Review tab, two page sets in the Pages & capture tab (C16a), and a new **Text** tab (C16b, C17). |

**Offline:** everything above runs on the computer. Cloud AI suggestions are still possible only as an opt-in (requirement Section 7); they are not part of this plan.

---

## 2. Project layout (additions)

```
src/letter_extractor/
├── ocr/
│   ├── __init__.py
│   ├── __main__.py       # python -m letter_extractor.ocr LINE.png: print a line's aksharas  (C10)
│   ├── tesseract.py      # find the program, list languages, run on an image, parse hOCR      (C10)
│   ├── aksharas.py       # split Devanagari text into aksharas (our letter units)             (C10)
│   ├── align.py          # match OCR aksharas to cut samples in a line                        (C11)
│   ├── classifier.py     # load an ONNX model, classify sample images                         (C14)
│   ├── train.py          # build the training set, train, evaluate, export to ONNX            (C14)
│   ├── language.py       # word lists, akshara n-grams, correction search                     (C15)
│   └── convert.py        # page → Devanagari text → Gujarati text, confidences                (C16b)
├── app/
│   ├── suggest.py        # label-suggestion jobs: Tesseract, other books, classifier          (C11, C13, C14)
│   ├── texts.py          # converted text, proofreading edits                                  (C16b, C17)
│   └── migrations/versions/0002_book_writing.py (C10), 0003_ocr_suggestions.py, 0004_models_dictionary.py,
│                           0005_page_sets.py (C16a), 0006_texts.py

frontend/src/components/
└── WritingChoice.tsx     # handwritten / printed, in the new-book form and the Capture tab       (C10)

frontend/src/screens/
├── Suggestions.tsx       # suggestion chips, accept / reject, "accept all above x%"             (C12)
├── Models.tsx            # trained models and their per-class accuracy                          (C14)
├── Dictionary.tsx        # word lists: import, enable per book, statistics                     (C15)
├── Capture.tsx           # + a second section, "Pages to convert", with its own folder         (C16a)
└── TextView.tsx          # page image next to its text, proofreading                           (C16b, C17)

docs/
├── INSTALL_TESSERACT.md
├── implementation_plan_phase2.md   (this file)
└── TUNING_PHASE2.md      # measured suggestion accuracy and text error rates, per chunk

tests/data/ocr/           # a printed line image and saved hOCR (printed and handwritten), for tests without Tesseract (C10)
```

**Library folder additions:**
```
<library>/
  models/<id>-<date>/model.onnx, classes.json, report.html   (C14)
  dictionaries/<name>.txt                                    (C15, imported word lists, a copy)
  books/<id>-<name>/
    ocr/<page>_L01.hocr     raw Tesseract output, kept for checking and re-alignment  (C10, C11)
    text/<page>.txt         converted Gujarati text, one file per page                (C16b)
```

---

## 3. Data model (additions)

```
Book            + writing (handwritten | printed), migration 0002 (C10); existing books become handwritten
Book            + convert_dir (the folder of the pages to convert; empty = none), migration 0005 (C16a)
Page            + folder (training | convert): which of the book's folders the file is in
                + role (training | convert): how the page is used; it changes when a page is moved across
                unique (book_id, folder, file) instead of (book_id, file); existing pages are training / training
OcrRun          id, book_id, engine (tesseract | classifier | books), settings JSON, model_id?, started_at, finished_at, status
OcrReading      id, run_id, sample_id, text_dev, confidence, alternatives JSON, box_overlap, matched (bool)
                one row per sample the run read; samples it could not match get no row
LetterGroup     + suggested_dev, suggested_share, suggested_count, suggested_run_id, suggestion_state
                  (none | open | accepted | rejected): the current suggestion of the group
Model           id, kind (letter-cnn), path, classes JSON, trained_on JSON (books, sample counts), accuracy, created_at
WordList        id, name, source, words (count), enabled_books JSON
PageText        id, page_id, version, text_dev, text_guj, letters JSON (sample id, text, confidence, source per letter),
                proofread (bool), edited_at
```

Rules that carry over from Phase 1:
- **A suggestion never sets a label by itself.** Only an accept by the user does, and then as a normal `set_label` action with undo.
- **Labels stay canonical in Devanagari NFC.** OCR text is normalised to NFC before it is compared or stored.
- **Raw results are kept** (`OcrReading`, the hOCR files), so a better alignment or voting rule can be re-run without running OCR again.

---

## 4. Implementation chunks

### Part A: label suggestions with Tesseract (printed books)

### C10. Tesseract engine, akshara splitting, and how a book is written

**Status:** done (2026-10-04).

**Goal:** read one line image with Tesseract and get its text as a list of aksharas, each with a box and a confidence. Every book records whether it is handwritten or printed.

**Files:** `ocr/__init__.py`, `ocr/__main__.py`, `ocr/tesseract.py`, `ocr/aksharas.py`, `app/migrations/versions/0002_book_writing.py`, additions to `app/db.py`, `app/library.py`, `app/schemas.py`, `app/api.py`; `frontend/src/components/WritingChoice.tsx`, additions to `api.ts`, `Books.tsx`, `BookView.tsx`, `Capture.tsx` (+ tests); `tests/test_ocr_tesseract.py`, `tests/test_aksharas.py`, additions to `tests/test_library.py`, `tests/test_api.py`; `tests/data/ocr/` (a printed line and saved hOCR); `docs/TUNING_PHASE2.md`.

**What it does:**
- **Finding Tesseract:** the path in the app settings, then the PATH, then the usual install folders (`/usr/local/bin`, `/opt/homebrew/bin`, `/opt/local/bin`, `C:\Program Files\Tesseract-OCR`). It returns the version and the installed languages (`--list-langs`). If the program or a language is missing, the error message names it and points to `INSTALL_TESSERACT.md`.
- **Reading a line:** `read_line(image, engine, langs="script/Devanagari", psm=7, target_height=0)`:
  - write the prepared image to a temporary PNG (Pillow; Unicode-safe paths, as in Phase 1);
  - run `tesseract <png> - -l <langs> --psm 7 -c hocr_char_boxes=1 -c lstm_choice_mode=2 hocr` with a timeout;
  - parse the hOCR into words → characters (`ocrx_cinfo` with `x_bboxes`, `x_conf`), each followed by its alternatives (`lstm_choices`, sorted best first);
  - map every box back to the coordinates of the image that was passed in (undo the border and the scaling), so callers never see Tesseract's image. The raw hOCR is returned too, to be kept.
- **Image preparation:** black ink on white (Otsu threshold on the lightness, which also works for red ink, or an ink mask passed in), with a 10 px white border. Optional scaling to a letter-body height (`target_height`). The body height is estimated from the rows where at least 35% as many columns have ink as on the headline row. The default is **no scaling**: in C10 it changed single letters both ways, and the printed bodies (50 to 65 px) are already in Tesseract's good range.
- **Akshara splitting:** `split_aksharas(text)` groups code points into units that match Phase 1 cuts:
  - consonant (+ nukta) (+ virama + consonant …): a conjunct is one akshara;
  - + vowel sign(s) + anusvara / candrabindu / visarga;
  - independent vowels, digits, danda and double danda are their own units;
  - a stray vowel sign with no consonant is kept as its own unit and marked `orphan`. Tesseract makes these errors.

  Each akshara's box is the union of its characters' boxes. Its confidence is the lowest of its characters' confidences. Each keeps its characters, and with them Tesseract's alternatives (for C15). An akshara never spans a space.
- **Language comparison:** `san`, `hin`, `san+hin`, `mar` and `script/Devanagari` were run on 3 lines of each printed page and on the handwritten lines, and the character error rate was counted on 4 transcribed lines (`TUNING_PHASE2.md`). **`script/Devanagari` is the default:** about 5% wrong code points on print (as good as `mar`, better than `hin` and `san`), and the best on the handwritten line (about 35%). Tesseract's confidence was 95% on average even on handwriting, so it does not show which readings are wrong.
- **How a book is written:** `Book.writing` is `handwritten` (the default; existing books get it in migration `0002`) or `printed`. It is chosen in the **New book** form and can be changed in **Pages & capture**; the book's header shows it. The API takes it in `POST /api/books` and `PATCH /api/books/{id}` (which now also renames). In C10 it changes nothing else; C11 to C16b use it to choose the default reader (see "Changes from the original plan").

**Tests:**
- Unit tests run on saved hOCR files (a printed and a handwritten line), so the CI does not need Tesseract for them: parsing, alternatives, boxes mapped back, empty output.
- Finding the program: a missing program names `INSTALL_TESSERACT.md`; a fake `tesseract` script gives the version and languages; a missing language is named.
- One integration test reads a printed sample line (`tests/data/ocr/printed_line.png`); it is skipped when Tesseract with `script/Devanagari` is not installed.
- Akshara tests cover क, कि, क्ष, श्री, र्क (reph), द्ध्य, कं, कः, कँ, ॐ, ।, ॥, digits, ZWJ, nukta (and NFC), a final halant, an orphan matra, and characters that carry several code points.
- Writing: library and API (create, change, invalid value), upgrading a library from schema `0001`, and the screen (choosing it for a new book, changing it in Capture).

**Output:** `python -m letter_extractor.ocr <line.png> [--langs …] [--height …] [--hocr out.hocr]` prints the line's text, then the aksharas with their boxes and confidences.
**Done when:** the printed sample lines come out as readable Devanagari, the akshara splits match the cutting rules on the test words, and the CI passes without Tesseract installed.
**C7/C8 additions:** none bundled (Tesseract stays a separate install, see decision 1). In C8, the Ubuntu test job installs `tesseract-ocr tesseract-ocr-script-deva` with `apt` (the package with `script/Devanagari`), so the integration test runs there too.

**Changes from the original plan:**
- **Handwritten or printed, per book** (asked for on 2026-10-04): the original plan had no such setting and would have offered Tesseract on every book. Tesseract's output is only useful on print, and its confidence does not warn when it is wrong, so the book now says which it is. Printed books use Tesseract by default; handwritten books use other books (C13) and the classifier (C14), and Tesseract only when the user asks for it. It is stored as a column (`Book.writing`, migration `0002`), not in the capture settings: it is not a cutting setting, and "Back to the defaults" must not reset it. Migrations after it are renumbered (`0003` onwards).
- **Default language** `script/Devanagari`, not `san+hin` (measured, see above; decision 2 is settled).
- **No scaling by default** (`ocr_letter_height = 0` instead of 40 px). The binarization is Otsu on the line image instead of Phase 1's ink mask: line images are what C11 reads, and an ink mask can still be passed in.
- **Boxes come back in the input image's coordinates** from `read_line`, so C11 only adds the line's offset on the page.
- **No `data/devanagari_aksharas.txt`:** the akshara rules need a few Unicode ranges, which are clearer as constants in `aksharas.py`.

### C11. Matching OCR letters to our samples, and group suggestions

**Goal:** a job that reads every line of a book with Tesseract, gives each cut sample its OCR akshara where the match is clear, and gives each group a suggested label by vote.

**Files:** `ocr/align.py`, `app/suggest.py`, `app/migrations/versions/0003_ocr_suggestions.py`, additions to `app/db.py`, `app/jobs.py`, `app/api.py`, `app/schemas.py`, `tests/test_align.py`, `tests/test_suggest.py`.

**What it does:**
- **Per line:** run C10 on the line image (`Line.image`). Keep the hOCR in `books/<book>/ocr/`. The job runs on any book; the screen offers it as the main action only on printed books (C12).
- **Alignment** (`align.py`): match the line's OCR aksharas to its samples (not deleted, in reading order by x):
  1. **By overlap:** an OCR akshara and a sample match when their x ranges overlap by at least 60% of the smaller one. C10 returns boxes in the line image's coordinates (border and scaling already undone); they are converted to page coordinates with the line's offset.
  2. **By order, where boxes are unclear:** Tesseract's boxes for vowel signs and conjuncts are sometimes too narrow or empty. A dynamic-programming alignment (like a text diff) matches the two sequences by position. Its costs come from overlap, and it allows "skip OCR akshara" and "skip sample". This handles a sample that Tesseract read as two aksharas, or the other way round.
  3. A match is kept only if **both** methods agree, or the overlap is at least 80%. Everything else is left unmatched, which is better than a wrong match.
  4. **Whole lines are refused** when fewer than 50% of the samples match. That usually means Tesseract misread the line, or the line is not text.
- **Readings:** one `OcrReading` per matched sample (text, confidence, alternatives, overlap).
- **Group vote:** for each group, the readings of its samples are counted, weighted by confidence. The group gets a suggestion when:
  - at least `suggest_min_votes` samples (3) were read;
  - the winner has at least `suggest_min_share` (0.6) of the weighted votes.

  The suggestion is stored on the group (`suggested_dev`, share, count). A sample can also match several OCR aksharas in a row (a whole word that was not cut); its reading is then the word, so a word label can be suggested too. If another group already has the suggested label, the suggestion is shown as **"merge into gXXXX"**, because one label belongs to one group. **Labelled groups and groups with a rejected suggestion are skipped.** A new run replaces open suggestions only.
- **Unsure samples:** each gets its own reading as a suggestion if its confidence is at least `suggest_min_confidence` (80). C10 found Tesseract's confidence about 95% even on misread handwriting, so this filter alone is weak: on handwritten books, unsure samples get no Tesseract suggestion unless C12's measurement shows they are right often enough.
- **Job:** `POST /api/books/{id}/suggest {"engine": "tesseract"}`. It is cancellable, with progress per line, and one job per book as in Phase 1. Its result gives lines read, lines refused, samples matched, groups with a suggestion, and seconds.

**Settings (per book, in `Config`):** `ocr_langs` ("script/Devanagari"), `ocr_psm` (7), `ocr_letter_height` (0 = as is), `suggest_min_votes` (3), `suggest_min_share` (0.6), `suggest_min_confidence` (80), `align_min_overlap` (0.6). The `tesseract_path` setting is per app, not per book.

**Tests:**
- Alignment on hand-made sequences: equal counts; OCR splitting one sample in two; OCR merging two samples; a missing akshara; empty boxes.
- The vote, with a tie, too few votes, and a labelled group left untouched.
- The job runs on the synthetic book with a fake Tesseract (a function that returns saved hOCR).
- The migration upgrades a library at schema `0002`.

**Output:** in the API, every group carries `suggestion: {label_dev, label_guj, share, count}`.
**Done when:** on the printed book, at least 70% of the groups with 5 or more samples get a suggestion; the screen check is in C12.

### C12. Reviewing suggestions in the app, and measuring them

**Goal:** the user sees each suggestion on its group and accepts, corrects or rejects it, one at a time or all above a threshold. The accuracy is measured, not guessed.

**Files:** `frontend/src/screens/Suggestions.tsx` (+ test), additions to `GroupView.tsx`, `Review.tsx`, `SamplesView.tsx`, `api.ts`; additions to `app/actions.py` (`accept_suggestions`, `reject_suggestion`); `docs/TUNING_PHASE2.md`.

**What it does:**
- **Review tab:**
  - a **"Suggest labels"** button. Its default reader follows the book's writing: **printed** → Tesseract (the C11 job; disabled, with the reason, when Tesseract is missing); **handwritten** → other books (C13) or the classifier (C14) once they exist. Handwritten books also get **"Try Tesseract"** in the same place, with a note that it is measured to be less reliable on handwriting. Until C13 is built, that is the only reader a handwritten book has;
  - a filter "Suggested" shows groups with an open suggestion, sorted by share, highest first.
- **On a group:** a chip `क? 18 of 20 (90%)`, shown in Gujarati and Devanagari like labels:
  - **Accept** sets the label (the normal `set_label` action, undoable);
  - **Change** opens the label picker with the suggestion filled in;
  - **Reject** keeps the group unlabelled and stops suggesting it.
- **Bulk:** **"Accept all with ≥ 90%"** (the threshold can be changed) accepts many suggestions as **one** undoable action, after a confirmation that shows how many groups it will label.
- **Disagreeing samples:** in a group, samples whose own reading differs from the suggestion get a small badge with their reading (for example `ब` in a `व` group). Selecting them and pressing "New group" or "Move to unsure" splits the look-alikes that Phase 1 grouping merged. This uses the existing actions.
- **Unsure tab:** samples with a confident reading show it, and "Accept" moves them into the group with that label, or creates one if none exists.
- **Measuring** (written to `TUNING_PHASE2.md`): on the printed book, after the user's full review, compare suggestions with the final labels:
  - the share of correct suggestions, by share band (≥ 90%, 75 to 90%, 60 to 75%);
  - how many groups had no suggestion;
  - the most common wrong pairs.

  This sets the default bulk-accept threshold. The same is measured on the **handwritten** sample book with "Try Tesseract", to see whether group votes make Tesseract useful there. C10 measured about 30 to 35% wrong code points per handwritten line, so some common letters may still get right suggestions. If the share of correct handwritten suggestions at the threshold is 90% or more, "Try Tesseract" stays offered for handwritten books; otherwise it is hidden behind the settings.

**Done when:** the printed book can be labelled mostly through suggestions, and the measured accuracy at the default threshold is at least 95%. If it is lower, the threshold is raised until it is, and the figure is recorded.
**C7 addition:** none. **C8:** screen tests run as before.

### Part B: suggestions for handwriting

### C13. Suggestions from other labelled books

**Goal:** use the labelled groups of earlier books (printed or handwritten) to suggest labels in a new book, with no training and no new dependency.

**Files:** additions to `app/suggest.py`, `app/centres.py`, `app/api.py`; `tests/test_suggest_books.py`.

**What it does:**
- **Reference set:** the centres of all labelled groups in the chosen books (the user picks them; by default, all books with the **same writing**, handwritten or printed, as the new book; added in C10). Fingerprints come from the C4 fingerprint, so all books must use the same fingerprint settings. Groups from books with other `normalize_size` / `fp_*` settings are skipped, with a message.
- **For each group of the new book:** the nearest reference centres (k = 5). Their labels are voted, weighted by 1 / distance. A suggestion is made when the nearest is within `group_distance` and the vote share is at least `suggest_min_share`.
- Stored as an `OcrRun` with `engine = books`. It is shown in the same chip as Tesseract suggestions, with the source named ("from Book 2"). When both engines suggest, the screen shows both, and agreement raises the share shown.
- **Measured** on the two handwritten sample pages: label page1 in one book and page2 in another, suggest page2 from page1, and record the accuracy in `TUNING_PHASE2.md`.

**Done when:** a second book of the same hand gets suggestions for most of its common letters, with the measured accuracy recorded.

### C14. Letter classifier: training and suggestions (FR-11)

**Goal:** a small neural network that learns the letters of the labelled books. It gives better suggestions than C13, a confidence per sample, and it is the reader for C16b.

**Files:** `ocr/train.py`, `ocr/classifier.py`, `app/migrations/versions/0004_models_dictionary.py` (`Model`), `app/suggest.py` (engine `classifier`), `frontend/src/screens/Models.tsx`, a `train` command in `cli.py`, `requirements-train.txt`, `tests/test_classifier.py`.

**What it does:**
- **Word labels** (category `words`, a sample that is a whole word) are left out of the letter classifier; conversion (C16b) still uses them through their group's label.
- **Training set:** every labelled, non-deleted sample of the chosen books (by default the books with the same writing as the book it is for), as 64 × 64 normalised ink images. This is the same image as the C5g export's `fixed64` mode. Classes with fewer than `min_class_samples` (5) samples are left out and listed.
- **Held-out test set** (FR-11): 15% of each class, chosen by page, so test letters come from pages the network has not seen. It is never used for training.
- **Network:** a small CNN (3 convolution blocks + 1 dense layer, about 300k weights). Small random shifts, rotations (±5°), thickness changes and noise are added during training, because one hand varies and the dataset is small. Training stops early when the test loss stops improving. On a laptop CPU it takes minutes, not hours, for a few thousand samples.
- **Report** (`models/<id>/report.html`): overall accuracy, **accuracy per class** sorted worst first with the sample count, and the most confused pairs (व/ब, घ/ध). This shows which letters need more samples (FR-11).
- **Export:** `model.onnx` + `classes.json` (labels in Devanagari NFC). The app loads models with **ONNX Runtime** only.
- **In the app:**
  - **Models tab:**
    - list the trained models with their date, books and accuracy;
    - open a model's report;
    - set the active model.
  - **Train** button: available when the training extras are installed. Otherwise it shows the command to run (`python -m letter_extractor train --books 1,2`).
- **Suggestions:** engine `classifier`. It classifies every sample of the book; the group vote uses the class probabilities, the same as C11. It is also used for **unsure** samples one by one.
- **Retraining:** each new reviewed book is added and the model is trained again (FR-11: "training can be repeated"). Models are kept, not overwritten, so an older model can be chosen again.

**Done when:**
- a model trained on the reviewed sample books reaches at least 90% accuracy on its held-out pages for classes with 20 or more samples;
- per-class accuracy is reported;
- its suggestions on a new book are measured as in C12.

**C7 addition:** bundle `onnxruntime` (about 20 MB). PyTorch is **not** bundled (decision 3).
**C8 addition:** a small training run on the synthetic book in CI (in a separate job with `requirements-train.txt`).

### Part C: dictionary

### C15. Dictionary and language model

**Goal:** use known words and known letter sequences to correct unlikely letters in a line, and to decide between close readings (व or ब), without ever silently changing confident letters.

**Files:** `ocr/language.py`, additions to migration `0004` (`WordList`), `app/api.py` (import, list, enable), `frontend/src/screens/Dictionary.tsx`, `tests/test_language.py`.

**What it does:**
- **Word lists:**
  - **import** plain UTF-8 text files, one word per line or running text. They can be in **Devanagari or Gujarati**: Gujarati is mapped back to Devanagari with the C5b mapping, and everything is stored as Devanagari NFC, like labels;
  - **build** a word list from the proofread text of the library's own books (C17), which grows with every book;
  - each book chooses which lists it uses (for example a Sanskrit list for a Sanskrit text). Lists are copied into `<library>/dictionaries/`.
- **Language model:**
  - an **akshara n-gram model** (trigrams, with backing off to bigrams and single aksharas), counted from the enabled word lists and proofread texts;
  - a **trie of words**.

  Both are rebuilt when a list changes and kept in memory per book.
- **Correction search** (`correct_line(candidates)`): each letter position has its candidate readings with probabilities, from the classifier's top 5 or Tesseract's alternatives. A beam search (width 20) finds the line text with the best combined score: letter probability × n-gram probability, plus a bonus when a stretch of the line splits into known words (a word-break search over the trie, since the manuscript has no spaces).
- **Safe by design:**
  - a letter is changed only when the change gains at least `lm_min_gain` in score;
  - a letter whose reader confidence is at least `lm_protect_confidence` (0.95) is never changed;
  - every changed letter is marked, so the user can see what the dictionary did.
- **Uses:** in C16b (conversion), and in the C11 / C14 group votes as a tie-breaker between close readings.
- **Measured:** character error rate (CER) on proofread lines, with and without the language model, in `TUNING_PHASE2.md`. If it does not help, it stays off by default.

**Done when:**
- importing a word list works in both scripts;
- on proofread lines, the language model lowers the CER, or the measurement shows it does not and it stays off;
- tests show confident letters are never changed.

### Part D: whole page to Unicode text

### C16a. Training pages and pages to convert

**Status:** planned (asked for and decided on 2026-10-05).

**Goal:** a book holds two page sets with separate folders: **training pages**, which are cut, grouped, reviewed and labelled as in Phase 1, and **pages to convert**, which are cut and later read into text (C16b) without being reviewed. The database records which set each page belongs to.

**Files:** `app/migrations/versions/0005_page_sets.py`, additions to `app/db.py`, `app/library.py`, `app/jobs.py`, `app/samples.py`, `app/export.py`, `app/api.py`, `app/schemas.py`; additions to `frontend/src/api.ts`, `Books.tsx`, `BookView.tsx`, `Capture.tsx`, `PageViewer.tsx`, `Review.tsx` (+ tests); `tests/test_page_sets.py`, additions to `tests/test_library.py`, `tests/test_api.py`.

**What it does:**
- **One book, two page sets** (decision of 2026-10-05). A manuscript's training pages and pages to convert are usually the same hand, so they share the book's cutting settings, writing (C10), labelled groups and model. Two separate books would have to be linked by hand.
- **Folders:** the training pages stay in the book's input folder (`Book.input_dir`). The pages to convert have their own folder (`Book.convert_dir`), chosen in the New book form (optional) or later in the Pages & capture tab. Both folders are only read, never changed, as in Phase 1. The two folders may hold files with the same name.
- **Database** (migration `0005`): `Book.convert_dir`; `Page.folder` (which folder the file is in) and `Page.role` (how the page is used). The two differ only for a page that was moved across. Page files are unique per book and folder. Existing books keep all their pages as training pages.
- **Capturing pages to convert:** the same cutting as Phase 1 (C0 to C3b): lines, samples with their images, masks and fingerprints. **No grouping:** their samples get no group and do not appear in Unsure. "Capture", "Add new pages" and "Cut a page again" work per set. Capturing the pages to convert never touches the training pages, their groups or labels, so it needs no confirmation. The same applies the other way round.
- **Kept apart everywhere else:**
  - Review groups, Unsure, group counts, suggestions (C11 to C14) and Export use **training pages only**;
  - the **Pages** tab shows both sets (a switch above the page list). Fixing cuts there (draw a box, join, split; C5f) works on pages to convert too, because a better cut gives better text;
  - the Books list and the book header show both counts ("12 training pages · 340 to convert").
- **Moving a page across:**
  - **"Use for training"** on a page to convert: the page becomes a training page. Its samples go to Unsure, each with a suggested group, as "Add new pages" does, and are then reviewed as usual. This is for pages with letters the readers keep getting wrong. One undoable action.
  - **"Use for conversion"** on a training page: its samples leave their groups. As with capturing again, this is refused when the page has manual work (labelled or hand-moved samples, fixed cuts) unless confirmed.
- **API:** `POST /api/books` and `PATCH /api/books/{id}` take `convert_dir`; capture, add-pages and page-problems take `"pages": "training" | "convert"` (default `training`, so the current screens keep working); `GET /api/books/{id}/pages?set=…`; `POST /api/pages/{id}/role`.
- **Screens:**
  - **New book:** an optional second folder, "Pages to convert".
  - **Pages & capture:** two sections, **Training pages** (as now) and **Pages to convert**, each with its folder, Capture / Add new pages buttons and page list. The settings card stays shared.
  - **Pages tab:** the set switch and "Use for training" / "Use for conversion".

**Tests:**
- The migration upgrades a library at schema `0004`: all pages become training pages, and nothing else changes.
- Capturing pages to convert creates samples without groups; Review, Unsure, counts and Export do not see them; same-named files in both folders.
- Capturing one set leaves the other set's pages, samples and labels unchanged.
- Moving a page both ways, with undo; moving a training page with labelled samples needs confirmation.
- API: the `pages` parameter, `convert_dir`, and its default of `training`.
- Screens: the second folder in the New book form, both sections in Pages & capture, the set switch in Pages.

**Output:** a book with, for example, the 2 handwritten sample pages as training pages and further pages of the same manuscript as pages to convert, both cut and visible in the Pages tab.
**Done when:** both sets can be captured, viewed and fixed independently; review and export are unchanged for training pages; a page can be moved across and back.
**C7 addition:** none. **C8:** the new tests run as before.

### C16b. Page conversion (FR-12)

**Goal:** convert the pages of a book into **one UTF-8 Gujarati text file per page**, keeping the manuscript's line breaks, with uncertain letters marked. The pages to convert (C16a) are the main target; training pages can be converted too, which is how the CER is measured against their labels.

**Files:** `ocr/convert.py`, `app/texts.py`, `app/migrations/versions/0006_texts.py` (`PageText`), a `convert` job in `app/jobs.py`, a `convert` command in `cli.py`, the first version of `frontend/src/screens/TextView.tsx`, `tests/test_convert.py`.

**What it does:**
- **Reading each letter**, in reading order per line, using the first source that applies:
  1. the label of its **reviewed group** (the user's decision is always used first). Samples on pages to convert have no group; they get the label of the **nearest labelled group** of the book instead, if it is within `group_distance` (the C13 method, with the book's own centres);
  2. the **classifier** (C14), if a model is active;
  3. **Tesseract's** reading (C11), for printed books, and for handwritten books only if C12 showed it helps there;
  4. otherwise **unknown**.

  Where 2 and 3 disagree, the higher confidence wins, and the letter is marked uncertain.
- **Correction:** each line is corrected with the language model (C15), if it is enabled for the book.
- **Text:**
  - letters are joined in Devanagari, then mapped to Gujarati with C5b's `mapping.py` (Gujarati or Western digits per book setting);
  - dandas and verse numbers are kept as written;
  - no spaces are added (FR-12);
  - letters below `text_min_confidence` are written as the marker setting: `[?]`, `[?क]` (the best guess inside the marker), or the plain guess.
- **Output:**
  - `books/<book>/text/<page>.txt`;
  - `text/<page>.json`: per letter, sample id, text, confidence, source, and whether it was corrected. This makes every converted letter traceable to the page (requirement Section 7);
  - a `PageText` row per page.

  It is also included in the C5g export as `text/`.
- **In the app:** a "Convert" button in the Text tab converts the pages to convert (or a chosen page) as a cancellable job with progress per page.
- **Without the app** (Phase 3 use): the CLI `python -m letter_extractor convert --input pages/ --output text/ --model <id>` cuts the pages (C0 to C3b) and converts them in one step, without a book or database. In the app, the same work is done through a book's pages to convert (C16a).

**Done when:**
- every page to convert of the printed book and of the handwritten sample book has a text file;
- the CER of each is measured against proofread lines and recorded;
- the `[?]` markers match the low-confidence letters.

**C8 addition:** a smoke test converts the synthetic book.

### C17. Proofreading view and feedback

**Goal:** a person checks the converted text side by side with the page. Every correction improves the data: it labels samples, adds to the dictionary and becomes training data.

**Files:** `frontend/src/screens/TextView.tsx` (+ test), `app/texts.py`, additions to `app/actions.py`, `app/api.py`.

**What it does:**
- **Text tab:**
  - the page image on the left, with the line boxes from Phase 1;
  - its text on the right, one row per manuscript line, in Gujarati (switch to Devanagari);
  - uncertain and dictionary-corrected letters are highlighted.
- **Linked selection:** clicking a letter in the text highlights its sample on the page, and the other way round.
- **Editing:** a letter can be changed by typing (Devanagari or Gujarati, with the label picker), or "this is two letters" / "these are one letter", which opens the existing join and split from C5f.
  - A changed letter **labels its sample**: the sample moves to a group with that label, or to a new group if none exists. This is an undoable action. On a page to convert (C16a), this puts that one sample into the book's training data without moving the whole page.
  - A line can be marked **proofread**. Proofread lines are:
    - the ground truth for the CER measurements;
    - the source of the library's own word list (C15);
    - the line training data for C18 (`lines/*.png` + `.txt` in the export).
- **Re-run:** converting again keeps proofread lines unchanged and only re-reads the others.

**Done when:**
- a page can be fully proofread in the Text tab;
- the corrections appear as labels in Review;
- converting again does not undo them.

### Part E: line recognizer (optional, later)

### C18. Line recognizer (Section 8.3 of the requirements)

**Goal:** a recognizer that reads whole lines, so cutting errors stop mattering. Start it only after **a few hundred proofread lines** exist (C17), and only if the measured CER of the letter route (C16b) is not good enough.

**What it does (to be detailed when it starts):**
- **Compare two routes** on the same proofread lines:
  - **(a) Kraken:** train a model from `lines/*.png` + `.txt` (the standard tool for handwritten manuscripts);
  - **(b) Tesseract fine-tuning:** fine-tune `san` / `hin` from the same lines with `tesstrain`. This needs Tesseract's training tools, which are easier to install on Linux and macOS than on Windows.
- **The best route by CER** becomes another reader in C16b, used before or instead of the letter classifier.

**Done when:** a decision has been recorded with the measured CER of each route.

---

### Chunk summary

| # | Chunk | Status | Main output | Requirements |
|---|---|---|---|---|
| C10 | Tesseract engine, akshara splitting, book writing | done | OCR of a line as aksharas with boxes; handwritten / printed per book | FR-7 |
| C11 | Matching OCR to samples, group suggestions | **next** | suggestions on groups and unsure samples | FR-7 |
| C12 | Reviewing suggestions, measuring | planned | accept / reject / bulk accept; measured accuracy | FR-7, FR-8 |
| C13 | Suggestions from other labelled books | planned | handwriting suggestions, no training | FR-7 |
| C14 | Letter classifier | planned | `model.onnx`, per-class accuracy report | FR-11 |
| C15 | Dictionary and language model | planned | word lists, correction, measured CER | new |
| C16a | Training pages and pages to convert | planned | two page sets per book, separate folders, `Page.role` | FR-12 (pages to convert) |
| C16b | Page conversion | planned | `text/<page>.txt` in Gujarati, `[?]` marks | FR-12 |
| C17 | Proofreading view | planned | proofread lines, feedback into labels | FR-12 (side-by-side view) |
| C18 | Line recognizer | optional | Kraken or Tesseract model; decision by CER | Section 8.3 |

---

## 5. Configuration (new settings)

All in the same `Config` dataclass, per book, except where noted.

| Setting | Chunk | Default |
|---|---|---|
| `writing` (a column of the book, not in `Config`) | C10 | `handwritten` (or `printed`) |
| `tesseract_path` (app setting, not per book) | C10 (used from C11; the CLI takes `--tesseract`) | empty = search |
| `ocr_langs` | C10 (used from C11) | `script/Devanagari` (measured in C10) |
| `ocr_psm` | C10 (used from C11) | 7 (one text line) |
| `ocr_letter_height` | C10 (used from C11) | 0 = as is (measured in C10) |
| `align_min_overlap` | C11 | 0.6 |
| `suggest_min_votes` | C11 | 3 |
| `suggest_min_share` | C11 | 0.6 |
| `suggest_min_confidence` | C11 | 80 (Tesseract scale 0 to 100) |
| `bulk_accept_share` | C12 | 0.9 (set from the C12 measurement) |
| `reference_books` | C13 | all books with the same writing |
| `min_class_samples` | C14 | 5 |
| `active_model` (app setting) | C14 | none |
| `word_lists` | C15 | none |
| `lm_min_gain`, `lm_protect_confidence` | C15 | set in C15, 0.95 |
| `convert_dir` (a column of the book, not in `Config`) | C16a | empty = no pages to convert |
| `text_min_confidence` | C16b | 0.6 |
| `uncertain_marker` | C16b | `[?]` (or `[?x]`, or none) |

---

## 6. Testing

- **No Tesseract needed for the unit tests:** saved hOCR files and a fake Tesseract function cover parsing, alignment and voting. Integration tests with the real program are skipped when it is missing, and run in CI on Ubuntu, where `apt` installs it.
- **Akshara rules** have their own test table: one row per tricky word, from Phase 1's known cutting cases.
- **Alignment tests use made-up sequences** with known answers: equal, split, merged, missing.
- **Measurements, not only tests:** every chunk that suggests or converts records its measured accuracy or CER on the sample books in `TUNING_PHASE2.md`, like `TUNING.md` in Phase 1. Defaults are set from these numbers.
- **The classifier** is tested on the synthetic book for the code path, a short run that checks it learns 3 easy classes. Its real accuracy is a measurement, not a unit test.
- **Migrations:** each new migration is tested by upgrading a library made with the previous version.
- **Screen tests** (Vitest) for the suggestion chips, bulk accept, the Models and Dictionary screens, and the Text view's linked selection.

---

## 7. Requirement traceability

| Requirement | Chunk | Module |
|---|---|---|
| FR-7 Suggested label for each group, confirmed by the user | C10 to C14 | `ocr/tesseract.py`, `ocr/align.py`, `app/suggest.py`, `Suggestions.tsx` |
| FR-11 Train a recognizer, held-out test set, per-class accuracy, repeatable | C14 (C18) | `ocr/train.py`, `ocr/classifier.py`, `Models.tsx` |
| FR-12 Pages to convert kept apart from training pages (decided 2026-10-05) | C16a | `app/library.py`, `Page.role`, `Capture.tsx` |
| FR-12 One UTF-8 Gujarati text file per page, line breaks, `[?]`, dandas, no spaces | C16b | `ocr/convert.py`, `mapping.py` |
| FR-12 Side-by-side proofreading view (optional) | C17 | `TextView.tsx`, `app/texts.py` |
| Section 7 Offline | all | Tesseract and ONNX Runtime run locally |
| Section 7 Traceable | C11, C16b | `OcrReading`, `text/<page>.json` |
| Section 8.3 Letter classifier first, line recognizer later | C14, C18 | |

---

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Tesseract's character boxes are wrong for vowel signs and conjuncts | Alignment uses boxes **and** order, keeps only matches where they agree, and refuses unclear lines (C11). Raw hOCR is kept, so the rules can be improved without re-running OCR. |
| Tesseract splits text into aksharas differently from our cutting | Our own akshara rules match Phase 1 cutting; mismatches are handled by the alignment's split / merge steps. |
| Old typefaces (old अ, ण, श forms) are misread | Suggestions are voted per group, so single misreads are outvoted. Nothing is labelled without the user. Languages were compared in C10 (`script/Devanagari`). |
| Tesseract is run on handwriting and its suggestions look sure but are wrong (its confidence is about 95% even there, C10) | Books say whether they are handwritten; Tesseract is the default only for printed books. On handwritten books it is a "Try" that C12 measures, and its share threshold comes from that measurement. |
| Bulk accept labels many groups wrongly | The threshold comes from measured accuracy (C12); bulk accept is one undoable action; disagreeing samples are shown. |
| Tesseract is not installed on a user's computer | Only the suggestion button needs it; the app explains what to install. Bundling it is decision 1. |
| Too little handwritten data for a good classifier | Suggestions from other books (C13) work with no training; augmentation; per-class report shows where to add samples; models improve with every reviewed book. |
| PyTorch makes the installer very large | Only ONNX Runtime is bundled; training is a separate install (decision 3). |
| The dictionary "corrects" right letters into wrong words | Confident letters are protected; every change is marked; it stays off unless measurement shows it helps (C15). |
| Users change suggestions after accepting, and the measurements drift | Measurements are taken from the final labels after review, and repeated per book. |
| Converted text loses track of its source | Every letter keeps its sample id and source in `text/<page>.json`. |
| Hundreds of pages to convert flood the review screens | Pages to convert are never grouped and never shown in Review or Unsure (C16a); only single corrected samples or pages moved on purpose join the training data. |

---

## 9. Decisions to confirm

1. **Tesseract: separate install or bundled?** Proposed: **separate install** for now (`INSTALL_TESSERACT.md`). The app finds it automatically, and nothing else depends on it. Bundling adds about 30 to 60 MB per platform and needs its own build steps on macOS. It can be added to C7 later if the team finds the install too hard.
2. **Default OCR languages:** settled in C10: `script/Devanagari`, which read the printed and handwritten sample lines best (`TUNING_PHASE2.md`). It can be changed per book (`ocr_langs`).
3. **Training in the app or as a separate tool?** Proposed: **separate** at first. Training is `python -m letter_extractor train` in an install with `requirements-train.txt` (PyTorch, CPU). The app only runs the trained model (ONNX Runtime). Bundling PyTorch would make the app about 4 times larger. A "Train" button inside the app can follow if the people who review books also need to train.
4. **Word lists:** which sources may be used? Proposed: the library's own proofread text, plus lists the team imports. No list is downloaded automatically (offline, and licences differ).
5. **Uncertain-letter marker in the text:** `[?]` (the requirement's example), `[?क]` with the best guess, or the plain guess with a side file only. Proposed: `[?]` by default, as a setting.
6. **Phase 1 C7 / C8 timing:** proposed to do C7 and C8 **after C12**, so the first packaged version already contains Tesseract suggestions. The alternative is before C10, to get an installable app to the team sooner.

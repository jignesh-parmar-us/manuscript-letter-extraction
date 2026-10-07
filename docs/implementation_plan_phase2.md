# Manuscript Letter Extraction: Implementation Plan, Phase 2

Phase 1 (`docs/IMPLEMENTATION_PLAN.md`) cuts every letter out of the pages, groups identical letters, and lets a person label each group and export a dataset. **Phase 2 takes the app from labelled letters to text.** It suggests labels automatically, so that review becomes mostly confirming. It learns this scribe's hand from the labelled books, uses a dictionary to correct unlikely letters, and converts whole pages into Gujarati Unicode text.

The work is split into **small chunks (C10 to C18)**, numbered after Phase 1's chunks. As in Phase 1, each chunk ends with something to run and check by eye, and is a separate commit. Where the implementation turns out different from this plan, the chunk gets a **Changes from the original plan** note, and later chunks are updated in the same commit.

**Status:** C10 is done (2026-10-04): Tesseract reads a line into aksharas, and every book says whether it is **handwritten or printed**. C11 is done (2026-10-05): a job reads a whole book, matches the readings to the samples, and groups carry suggestions in the API. C12 is built (2026-10-05): suggestions, mixed groups and bulk accept in the Review tab; its final measurement waits for a full review of a printed book. C12b is built (2026-10-05): on printed books, Tesseract's readings split samples that hold several letters and join cut pieces. C12c is built (2026-10-06): a printed book can be cut by Tesseract's reading instead of by ink shapes, chosen per book. C13 is built (2026-10-06): suggestions from the labelled groups of other books, the first reader for handwriting; its measurement on handwriting waits for labels. C12d is built (2026-10-06): groups that mix two letters are split by their readings where the shapes agree. **C14 is next.** Tesseract is a separate install: see `docs/INSTALL_TESSERACT.md`. Measured numbers are in `docs/TUNING_PHASE2.md`.

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
│   ├── cut.py            # cut a line into the aksharas Tesseract reads (printed books)       (C12c)
│   ├── align.py          # match OCR aksharas to cut samples in a line                        (C11)
│   ├── classifier.py     # load an ONNX model, classify sample images                         (C14)
│   ├── train.py          # build the training set, train, evaluate, export to ONNX            (C14)
│   ├── language.py       # word lists, akshara n-grams, correction search                     (C15)
│   └── convert.py        # page → Devanagari text → Gujarati text, confidences                (C16b)
├── app/
│   ├── suggest.py        # label-suggestion jobs: Tesseract, other books, classifier          (C11, C13, C14)
│   ├── recut.py          # split and join samples where Tesseract's readings show a wrong cut  (C12b)
│   ├── texts.py          # converted text, proofreading edits                                  (C16b, C17)
│   └── migrations/versions/0002_book_writing.py (C10), 0003_ocr_readings.py (C11), 0004_models_dictionary.py,
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
├── NEW_BOOK_GUIDE.md     # step by step through a new book (added 2026-10-06)
├── help/new-book.html    # the same guide as the app's help page: `npm run build` copies docs/help/ into the
│                           app, which serves it at /help/ (no token); the header's "Help" link opens it
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
OcrRun          id, book_id, engine (tesseract | books | classifier), settings JSON, result JSON (counts),
                started_at, finished_at; only the newest run per book and engine is kept (C11).
                C14 adds model_id.
OcrReading      id, run_id, sample_id, text_dev (a valid label, NFC), confidence, alternatives JSON, overlap
                one row per sample the run read; samples it could not match get no row
LetterGroup     + rejected_dev: the suggested label the user rejected (C11). Suggestions themselves are
                  not stored: they are voted from the readings of the group's current samples when asked for
Model           id, kind (letter-cnn), path, classes JSON, trained_on JSON (books, sample counts), accuracy, created_at
WordList        id, name, source, words (count), enabled_books JSON
PageText        id, page_id, version, text_dev, text_guj, letters JSON (sample id, text, confidence, source per letter),
                proofread (bool), edited_at
```

Rules that carry over from Phase 1:
- **A suggestion never sets a label by itself.** Only an accept by the user does, and then as a normal `set_label` action with undo.
- **Labels stay canonical in Devanagari NFC.** OCR text is normalised to NFC before it is compared or stored.
- **Raw results are kept** (`OcrReading`, the hOCR files), so a better alignment or voting rule can be re-run without running OCR again.
- **Suggestions follow the groups:** they are voted live from the readings, so moving, merging or splitting samples changes them at once (C11).

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

**Status:** done (2026-10-05).

**Goal:** a job that reads every line of a book with Tesseract, gives each cut sample its OCR akshara where the match is clear, and gives each group a suggested label by vote.

**Files:** `ocr/align.py`, `app/suggest.py`, `app/migrations/versions/0003_ocr_readings.py`, additions to `app/db.py`, `app/jobs.py`, `app/api.py`, `app/schemas.py`, `config.py`, `ocr/tesseract.py` (environment for parallel runs), `frontend/src/api.ts` (types only; the screen is C12); `tests/test_align.py`, `tests/test_suggest.py`, additions to `tests/test_api.py`, `tests/test_library.py`; `docs/TUNING_PHASE2.md`.

**What it does:**
- **Per line:** run C10 on the line image (`Line.image`), several lines at once (one Tesseract process per core, each limited to one thread). The hOCR is kept in `books/<book>/ocr/<line image>.hocr`. The job runs on any book; the screen offers it as the main action only on printed books (C12).
- **Alignment** (`ocr/align.py`), on x positions only, with the line's samples (not deleted, in reading order by x):
  1. **Akshara spans:** the union of its characters' boxes, leaving out boxes wider than 2.5 × the line's median character width (Tesseract gives some vowel signs a box over a whole word). If the base letter's box was left out, the span starts where the previous akshara ends. An akshara with no usable box gets the gap between its neighbours. Spans are moved to page coordinates by the line image's x (`Line.x` − `line_margin_px`, at least 0).
  2. **Dynamic programming** (like a text diff) aligns the two sequences with these steps: one akshara to one sample (cost 1 − overlap); 2 or 3 aksharas on one sample (a word that was not cut: its reading is the word); one akshara over 2 or 3 samples (a conjunct cut in two: no reading); skip an akshara or a sample (cost 0.5). For several items on one, each must lie inside the one.
  3. **A match is kept** when its overlap is at least `align_sure_overlap` (0.8), or at least `align_min_overlap` (0.6) and the pair are also each other's best overlap. Everything else is left unmatched.
  4. **Whole lines are refused** when fewer than `align_min_matched` (0.5) of the samples match.
- **Readings:** one `OcrReading` per matched sample (text, confidence, alternatives per character, overlap). Only readings that are valid labels (`mapping.canonical_label`, words allowed) are stored; stray signs and other characters are counted and dropped. A new run replaces the book's previous Tesseract run. Nothing is stored when the job is cancelled.
- **Group vote** (`suggest.group_readings`), live from the readings of the group's current samples, weighted by confidence. A group gets a suggestion when:
  - it is unlabelled;
  - at least `suggest_min_votes` (3) of its samples were read;
  - the winner has at least `suggest_min_share` (0.6) of the weighted votes, with no tie;
  - the winner is not the label the user rejected for this group (`rejected_dev`).

  If another group already has the suggested label, the suggestion carries `merge_into` (that group), because one label belongs to one group. Every group with readings also carries its **3 most common readings with counts**: a mixed group shows up as two strong readings.
- **Unsure samples:** on **printed** books, each gets its own reading if its confidence is at least `suggest_min_confidence` (80). Handwritten books get none (C10: Tesseract's confidence stays high when it is wrong).
- **API:**
  - `POST /api/books/{id}/suggest {"engine": "tesseract"}`: a job (kind `suggest`), cancellable, progress per line, one job per book. It fails at once with the reason when Tesseract or the book's language is missing. Its result gives lines, lines read, refused and failed, samples, samples matched, readings that were not labels, groups with a suggestion, and seconds.
  - `GET /api/tesseract[?book_id=]`: whether Tesseract runs with the book's languages, its version and languages, or the error (for the C12 button).
  - every group carries `suggestion: {label_dev, label_guj, share, count, read, engine, merge_into}` or null, `readings: [{label_dev, label_guj, count}]` and `read`; unsure samples carry `reading`; the book carries `ocr_runs` (engine, time, result).
  - The Tesseract path is the app setting `tesseract_path` in the user's settings file (empty: search).

**Settings (per book, in `Config`):** `ocr_langs` ("script/Devanagari"), `ocr_psm` (7), `ocr_letter_height` (0 = as is), `align_min_overlap` (0.6), `align_sure_overlap` (0.8), `align_min_matched` (0.5), `suggest_min_votes` (3), `suggest_min_share` (0.6), `suggest_min_confidence` (80). The `tesseract_path` setting is per app, not per book.

**Tests:**
- Alignment on hand-made sequences: equal counts, the line image's offset, OCR splitting one sample in two, OCR merging two samples, a missing akshara, an akshara without a box, an implausibly wide character box, an unclear overlap left unmatched, a refused line, confidence and alternatives.
- The vote: a winner, too few votes, a tie, a share below the minimum, weighting by confidence.
- The job on the synthetic book with a fake Tesseract (it "reads" each sample as a text the test chooses): every group gets its reading; hOCR kept per line; a new run replaces the old; cancelling stores nothing; readings that are not labels are dropped; progress per line.
- Groups: a labelled group gets no suggestion but keeps its readings; `merge_into`; a rejected label is not suggested again; a mixed group shows both readings; votes follow moved samples; unsure readings on printed books only.
- API: suggestions in the group list, one group, the book's `ocr_runs` and unsure samples; `/api/tesseract`; the real job when Tesseract is installed (skipped otherwise).
- The migration upgrades a library at schema `0002`.

**Output:** in the API, every group carries `suggestion` and `readings`.

**Measured** (`TUNING_PHASE2.md`, on a copy of the user's library): on the printed book with 27 labelled groups, 75% of the read samples match their label. 13 of the 27 groups would get a suggestion, **all 13 right**; the others get none. 74 to 75% of all samples get a reading; a 23-page book takes 2 minutes. **27 to 32% of the groups with 5 or more samples get a suggestion**, short of the planned 70%: most groups of this print are mixed (Phase 1 grouping puts ता and ना, नि and ने together), and the vote rightly refuses to suggest one label for them. The ा bar, which Phase 1 cuts off on its own or joins to the next letter, makes त / ता split the vote in the same way.

**Done when:** the job runs on the printed books and the suggestions are measured against the user's labels. *Met, with the coverage target moved to C12 (see below).*

**Changes from the original plan:**
- **Suggestions are voted live, not stored on the group.** The plan stored `suggested_dev`, share, count, run and state on each group. Then every move, merge or split would have left stale suggestions. Now only the readings are stored, the vote runs when groups are listed (one query per book), and the group stores only the label the user rejected (`rejected_dev`). "Accepted" needs no state: the group then has a label. Migration `0003_ocr_readings`.
- **Readings must be valid labels.** Tesseract's stray signs, Latin letters and punctuation are dropped before they are stored, so a suggestion can always be accepted as a label.
- **Groups also return their most common readings**, so C12 can show mixed groups. The original plan had only the winner.
- **Akshara spans leave out implausible character boxes** and start where the previous akshara ends when the base letter's box is unusable (measured: Tesseract gives vowel signs boxes over whole words).
- **The match rule** is "overlap ≥ 0.8, or ≥ 0.6 and each other's best overlap" (the plan: "both methods agree, or overlap ≥ 80%"). Both new thresholds are settings (`align_sure_overlap`, `align_min_matched`).
- **A vowel-bar rule was tried and removed:** dropping ा from a reading when the next sample is a narrow bar raised sample accuracy only from 75.4% to 75.8% (`TUNING_PHASE2.md`).
- **Unsure samples get readings on printed books only** (the plan already said so for handwritten books; now it is in the code).
- **Parallel reading:** several Tesseract processes, one thread each. The plan read lines one by one.
- **The coverage target (70% of groups with ≥ 5 samples) moves to C12.** It depends on splitting mixed groups, which C12's screen does with the readings.
- **The job is offered for any book** through the API; the screen decides what to show (C12).

### C12. Reviewing suggestions in the app, and measuring them

**Status:** built (2026-10-05). Open: the measurement after a full review of a printed book (see "Done when").

**Goal:** the user sees each suggestion on its group and accepts, corrects or rejects it, one at a time or all above a threshold. The accuracy is measured, not guessed.

**Files:** `frontend/src/screens/Suggestions.tsx` (+ `Suggestions.test.tsx`), additions to `Review.tsx`, `GroupView.tsx`, `SamplesView.tsx`, `components/SampleGrid.tsx`, `components/LabelPicker.tsx` (`initialText`), `api.ts`, `styles.css`, `Review.test.tsx`, `reviewTestUtils.tsx`; additions to `app/actions.py` (`accept_suggestions`, `reject_suggestion`, `label_samples`), `app/suggest.py` (`samples_read_as`, `suggestion_accuracy`, readings for group samples), `app/api.py`, `app/schemas.py`, `config.py` (`bulk_accept_share`); tests in `tests/test_suggest.py`, `tests/test_api.py`; `docs/TUNING_PHASE2.md`.

**What it does:**
- **Review tab, side bar: "Label suggestions" panel:**
  - the button follows the book's writing: **printed** → "Suggest labels (Tesseract)" (then "Read again with Tesseract"); **handwritten** → "Try Tesseract", with a note that about a third of its letters are wrong on handwriting. Disabled, with the reason from `GET /api/tesseract`, when Tesseract or the book's language model is missing. It starts the C11 job and shows "Reading lines: n of m" with Cancel; the groups reload when it ends;
  - after a run: when it ran, how many letters were read, how many groups got a suggestion;
  - **"Accept N with ≥ [90] %"**: labels every group whose suggestion has at least that share, is not locked and needs no merge, as **one** undoable action (`accept_suggestions`), after a confirmation that says how many groups it will label. The start value is the book setting `bulk_accept_share` (0.9);
  - **"Checked against your labels: x of y right"** (once the book has labels): each labelled group voted as if unlabelled, by share band, with the groups that would get none and the most common wrong pairs (`GET /api/books/{id}/suggestion-accuracy`). This is the C12 measurement, built into the app so it can be repeated on every book.
- **Filters:** "Suggested" (unlabelled groups with a suggestion; sorts by share, highest first) and **"Mixed readings"** (the second most common reading is at least 2 samples and a quarter of those read). New sort: "by suggestion share". Unlabelled groups in the list show their suggestion after the code (`g0019 ર?`).
- **On a group:** a chip "Suggested: ક क · 18 of 20 read (90%)":
  - **Accept** labels the group (`accept_suggestions` with one group; undoable);
  - **Change…** fills the label picker with the suggestion, to correct it before saving;
  - **Reject** keeps the group unlabelled and stops suggesting that label (`reject_suggestion` sets `rejected_dev`; undoable). Another reading can still be suggested later;
  - when another group already has the label, **"Merge into gXXXX"** replaces Accept (one label, one group).
- **Readings line:** "Read as: તા 29 · ના 25 · મા 6 of 68 read". Clicking a reading **selects all samples of the group read that way** (every page of samples, `GET /api/groups/{id}/read-as`); then "New group" or "To Unsure" splits the group with the existing actions, and the parts get their own suggestions at once (C11 votes live). For mixed groups the line says so.
- **Badges:** in a group, a sample whose reading differs from the group's (its suggestion, else its label, else its most common reading) shows that reading in its corner. In g0009 of the sample book they mark exactly the ના, મા and સા samples in a તા group.
- **Unsure:** on printed books, samples with a confident reading show it as a green chip next to the suggested group. Clicking it, or **"Accept readings"** for a selection, puts the samples in the group with that label, or in a new group that gets it, as one undoable action (`label_samples`).
- **Undo:** the group's `rejected_dev` is part of the recorded group state; actions recorded before C12 (without it) still undo.

**Tests:** accept many groups as one undoable action (undo and redo restore everything); accept skips a label another group has and refuses when nothing can be labelled; reject is undoable; undo of an action recorded before `rejected_dev`; label samples into the labelled group or a new one, and undo; samples read as X; accuracy against labels; the API routes. Screen: the panel (start and follow the job, "Try" on handwritten books, disabled with the reason, bulk accept with confirmation, the accuracy line), the chip (accept, reject, merge, change), badges only on samples read otherwise, selecting one reading of a mixed group, accepting an unsure sample's reading, the new filters and sort.

**Measured** (`TUNING_PHASE2.md`): on the 27 labelled groups of the sample book, 13 of 13 suggestions are right in every share band (5 at ≥ 90%, 5 at 75 to 90%, 3 below). Too few groups to set the threshold, so `bulk_accept_share` stays 0.9. Splitting the mixed groups by reading, simulated on a copy, raised the groups (≥ 5 samples) with a suggestion from 32% to 57% in one round and 59% in two.

**Done when:**
- the printed book can be labelled mostly through suggestions, and the measured accuracy at the default threshold is at least 95%. If it is lower, the threshold is raised until it is, and the figure is recorded. *Open: needs the user's full review of a printed book; the app's "Checked against your labels" gives the figures.*
- after the mixed groups of the printed book are split with the help of the readings, at least 70% of the groups with 5 or more samples get a suggestion. *Simulated: 59% by splitting alone; the rest (readings spread over many texts, the ा bar) is left to the person reviewing. To be measured again after that review.*

**C7 addition:** none. **C8:** screen tests run as before.

**Later changes (2026-10-06, asked for by the user):**
- **Layout:** the Label suggestions panel grew too tall in the side bar and pushed the groups down. It is now a bar across the top of the Review tab, next to Undo and Redo: the reader buttons, Fix cuts, Split mixed groups and "Accept N with ≥" in one row, one status line under it, and the reference books and the accuracy check folded under "Details". The side bar holds only Unsure, Deleted samples, Missing letters, the filter and sort, and the group list, which fills the rest of its height. Below 860 px wide the two columns stack. Check boxes and radio buttons no longer take the 260 px minimum width of text inputs.
- **Joined letters** (2026-10-06): the label palette has a row "Joined letters (જોડાક્ષર)" with reph र् (put before a letter: र्क) and rakar ्र (put after it: क्र, क्रा; on ट and ड it is drawn as the bottom churn, ट्र). The letter overview can add rows for every consonant with rakar and with reph (each across all vowel signs), shown in sections, alongside the four conjuncts.
- **"Move to…" picker** (`frontend/src/screens/GroupPicker.tsx`, 2026-10-06): the long "Move to group" drop-downs of the group view, Unsure and the Pages tab are replaced by a dialog with the letter table: a letter with a group moves the selected letters into it; any other letter puts them under that label, in a new group (`label_samples`). Below the table: the other labelled groups, and the groups without a label, newest first, 30 at a time ("Show more"). The current group and locked groups cannot be chosen. "Merge another group into this one…" uses the same picker in a merge mode: only letters with a group can be chosen (green, or amber for an unlabelled group suggested as the letter), and the chosen group's letters join the current group.
- **Actions stay in view:** the group view's label box (Save label, Clear label, Letters…) and its toolbar, with the group's label and the selection count, stick together to the top of the window while the letters scroll; an open Letters palette scrolls on its own. Unsure's toolbar sticks the same way.
- **Side bars fit the window** (Review groups; Pages until 2026-10-07): the side bar always ends at the window's bottom, wherever it starts (`components/useFitHeight.ts`), and its list does not pass its scrolling on to the window, so the group or page list scrolls by itself.
- **Reviewing an automatic label:** ticking "Reviewed" on a group labelled at capture or by Fix cuts (label set, status `auto`) marks it `labelled`; unticking marks it `auto` again with its label kept. Before, the check box did nothing on such groups.
- **One top bar** (`frontend/src/components/AppBar.tsx`, 2026-10-07): in a book, the app's name, the book's title and stats, and the tabs are one line: a **section menu** (Review groups, Pages, Pages & capture, Export) on the left, the book's name, writing and counts in the middle, and **Books** and **Help** on the right. The library path is no longer shown in the header (the Books screen still shows each book's folder).
- **Pages tab without a page list** (2026-10-07): the left page list is gone, so the page takes the full width. A row above the tools has ◀ / ▶ and a button with the page's file name and "i of n" that opens a **page chooser** (`frontend/src/screens/PagePicker.tsx`): every page in a scrolling list with its letter count, a search box (Enter opens the first match), Esc to close. The page and the selection panel fill the window's height together; the page scrolls inside its own box with some empty room below the last line, so a letter opened from the Review tab (double click) is centred even at the bottom of the page. Before, the page box was not fitted to the window when the page arrived after the first draw, so a letter near the bottom could not be scrolled into view.
- **Pages tab keeps its place:** the selection panel (and the "new box overlaps" offer) is below the page (since 2026-10-07 it shares the window's height with the page instead of sticking), so the page no longer moves when it opens or closes; after a delete, join, split, move, label or new box, a dashed marker stays on that spot until the next click.
- **Removing a wrong reading** (`actions.remove_readings`): a letter's badge (its reading, where it differs from the group's) is a button: one click removes that letter's reading of the book's main reader, so it no longer shows or counts in the group's vote; the letter stays in its group. "Remove readings" in the toolbar does it for the selected letters. One undoable action; the removed readings are kept in the action and come back on undo (unless the book was read again since).
- **Sorted by label:** the side bar's group list is sorted by label by default, and so are the group menus in the group view, Unsure and the Pages tab (labelled groups in letter order, then the others by code).
- **Letter overview** (`frontend/src/screens/LetterOverview.tsx`; first called "Missing letters"): every consonant with every vowel sign (ा ि ी ु ू ृ े ै ो ौ), and the vowels अ to औ in the same columns: 385 letters, 429 with the conjuncts क्ष त्र ज्ञ श्र. Each cell is green when a labelled group has that exact label (with its sample count; a click opens it), amber when no group has it but a group is suggested as it (a click opens that group to review), grey otherwise. "Hide rows with no group yet" drops the rows where no letter has a group or a suggestion. Below the table, **Other labelled groups** lists every labelled group whose label is not in the table (words, other conjuncts, letters with ं or ः, dandas, digits), so the page shows every label of the book. The side bar shows how many letters of the table are not labelled yet ("Letter overview (336 missing)").

**Changes from the original plan:**
- **The measurement is built into the app** ("Checked against your labels", `suggestion-accuracy`) instead of a one-off script, so it can be repeated for every book and after every review session.
- **"Mixed readings" filter, "select samples read as X" and badges against the group's most common reading** (not only against a suggestion), because C11 showed that most groups without a suggestion are mixed.
- **Unsure samples' readings are accepted with a new action, `label_samples`,** which moves them to the group with that label or creates one, as **one** undo step. The plan said "moves them into the group with that label, or creates one"; doing it in the backend makes it one action.
- **Bulk accept leaves out groups that need a merge** (their label is on another group) and locked groups; the backend also skips any group that got a label meanwhile, and names the skipped ones.
- **`bulk_accept_share`** is a book setting (0.9), as the plan's settings table said; the screen starts from it and the user can change it per use.
- **No `Suggestions.tsx` screen of its own:** the plan named the file; it holds the panel, the chip and the readings line, used inside the Review tab rather than as a separate screen.

### C12b. Fixing cuts with Tesseract's readings (printed books)

**Status:** built (2026-10-05). Asked for by the user after C12: the suggestions showed Tesseract reads print well, while Phase 1 leaves several letters in one sample on print.

**Goal:** split samples that hold several letters, and join letters that were cut in pieces, where Tesseract's reading shows it, without ever cutting a conjunct, and without cutting worse than before.

**Decisions (user, 2026-10-05):** applied automatically as **one undoable action** (not a list to approve); samples in labelled and reviewed groups are fixed too (their new pieces go to Unsure with their readings). **Locked groups stay untouched**, as everywhere else in the app.

**Files:** `app/recut.py`, `ocr/align.py` (the alignment path, `steps`), additions to `app/jobs.py`, `app/api.py`, `config.py`, `frontend/src/screens/Suggestions.tsx`, `api.ts`, `Capture.tsx` (job name); `tests/test_recut.py`, additions to `tests/test_api.py`, `Suggestions.test.tsx`; `docs/TUNING_PHASE2.md`.

**What it does:**
- **Not a new cutter.** Phase 1 still finds the lines and makes the first cut. Tesseract's character boxes are too rough to cut with (about 15 px off, some over a whole word, C11); they only say how many aksharas a stretch of line holds and roughly where they meet.
- **Per line** read by the newest Tesseract run, its kept hOCR is aligned with the line's current samples again (C11's alignment, now also returning its path):
  - **split:** a sample holding 2 or 3 aksharas is cut between them. Each cut goes to the column with the least ink, the headline rows left out, within `recut_window` (0.3) x the line's median sample width of the boundary Tesseract gives;
  - **join:** 2 or 3 samples inside one akshara become one sample, only when one of them is letter-sized and the others are fragments (a vowel bar, an i-hook, a mark). Two letter-sized samples are never joined;
  - **vowel bar** (added 2026-10-06): a letter read with a bar on its right (ा ो ौ ी, or आ ओ औ, which are अ with a bar but characters of their own in Unicode) whose bar Phase 1 cut off or joined to the next letter (अ | ावे): when the next sample starts with a tall stroke and a gap, the stroke moves to the letter; a lone bar is joined to it. The next letter must keep no i-sign (its stroke is not a bar), the letter must not itself start with a bar (that one belongs to the letter before), and the letter with its bar may be at most 0.6 letter widths wider than before. The rest of the next sample must still look like a letter of the book.
- **Splits only happen between aksharas** (C10's rules), so a conjunct (क्ष, त्र, द्ध), a reph (र्क) or a letter with its vowel signs and marks is never cut.
- **A change is kept only when every new sample looks like a letter of this book:** its fingerprint is within `group_distance` of the centre of a group with at least `recut_min_group` (5) samples, it is at least `recut_min_width` (0.45) x the line's median sample width wide, and its reading is one letter. Dandas, digits and samples of locked groups are left alone.
- **Applying:** all changes as **one action** (`fix_cuts`); one undo takes them all back. As with the Pages tab's split and join (C5f), the old samples are marked deleted; the new ones (source `ocr-split`, `ocr-joined`, `ocr-bar`) get their akshara as their reading in the newest run.
- **Placing the new samples** (asked for by the user, 2026-10-06: "if it reads as આ, fix the cut and put it in the આ group"): a new sample goes into the labelled group with its reading's label when its shape is within `group_distance` of that group's centre. When no group has that label, the new samples with that reading that look alike (within `group_distance` of their own centre), at least `suggest_min_votes` (3) of them, get a **new group with that label, marked not reviewed** (the "Not reviewed" filter shows these). Everything else goes to Unsure, with its reading.
- **In the app:** the Label suggestions panel of printed books gets **"Fix cuts with Tesseract"** once the book has been read. It asks first, runs as a job ("Checking cuts: n of m", cancellable: nothing changes), and reports the samples split and joined. `POST /api/books/{id}/fix-cuts` (400 on handwritten books; the job fails with the reason when the book has not been read).

**Tests:** a sample holding two letters (made with the Pages tab's join) is split again at the right places, with the right readings; the pieces go into the labelled groups of their readings; a letter cut with a narrow fragment is joined again; two letters under one akshara are not joined; one undo restores everything; locked groups are untouched; nothing to fix changes nothing; handwritten books and books without a run are refused; the least-ink column below the headline; the bar detection (a bar then a letter, a lone bar, a letter without one); the bar move (अ | ावे becomes आ | वे, a lone bar is joined, no move when the next letter has an i-sign or the reading has no bar); the API route; the button (printed only, asks, follows the job).

**Measured** (`TUNING_PHASE2.md`, a copy of the user's 23-page book): 12% of the read samples held several letters. One run (78 s) split **725** samples into 1,460 and joined **126**, refusing 706 candidates. By eye about three quarters of the splits and most joins are right. The new pieces' readings agree with the label of the nearest labelled group as often as ordinary samples do (75%). With the vowel-bar rule, a second run moved **586 bars**, and placed 705 of 1,258 new samples by reading and shape into 40 new labelled groups; the new आ, ता and ना groups hold only that letter. In the user's example group g0004, samples read as आ went from 28 to 9.

**Done when:** on a printed book, the fix splits most samples that hold several letters, a look at the new samples shows mostly single letters, and one undo restores the book. *Met on the copy of the user's book; to be checked by the user in the app.*

**Changes from the original plan:** a new chunk. Added after the user's first use (2026-10-06): the vowel-bar rule, and placing new samples by their reading (the original C12b put all of them in Unsure). This labels groups without the user, which C11's rule "a suggestion never sets a label by itself" did not allow: the user asked for it, the reading must agree with the shape, and the groups it makes are marked not reviewed. Two approaches were tried and dropped on the way: re-reading each new piece with Tesseract as the check (it cannot read a lone letter: 16 of 120 passed), and joining any samples under one akshara (half of the joins merged two letters).

### C12c. Cutting by Tesseract's reading (printed books, an option at capture)

**Status:** built (2026-10-06). Asked for by the user: "give an option at the initial stage for cutting with Tesseract instead of Phase 1 cuts, so the user decides; try it and see how accurate the results are".

**Goal:** a printed book can be cut into letters by Tesseract's reading instead of by the shapes of the ink, chosen per book, and the two are compared on the same pages.

**Files:** `ocr/cut.py`, additions to `pipeline.py` (`process_page`), `letters.py` (`Letter.text`), `report.py` (`text` column of samples.csv), `config.py`, `app/library.py` (`_store_readings`), `app/jobs.py` (Tesseract checked before a capture), `app/recut.py` (shares `best_cut`), `frontend/src/screens/Capture.tsx` (+ test); `tests/test_cut.py`; `docs/TUNING_PHASE2.md`.

**What it does:**
- **Setting `cut_method`** per book: `shapes` (C3a, C3b, the default) or `tesseract`. In the app: **Pages & capture → "Cutting into letters"**, shown for printed books; it is used at the next capture, add-pages or cut-a-page-again. In the CLI: a config file with `{"cut_method": "tesseract"}`.
- **Cutting a line:** Phase 1 still finds the lines and each line's own ink (C2). Tesseract reads the line image (C10); between two aksharas the cut goes to the column with the least ink, the headline rows left out, within `recut_window` (0.3) x the median akshara width of Tesseract's boundary. Cuts closer than `tesseract_cut_min_gap` (0.3) x that width are not made, and an akshara without a usable box stays with its neighbour: those aksharas are one sample with their text together. Splits only fall between aksharas, so conjuncts, reph and vowel signs stay with their letter. A text of dandas is kind `danda`, of digits `digit`.
- **Fallback:** a line Tesseract cannot read, or reads as fewer than half as many aksharas as the shape cut finds letters, is cut by shapes.
- **Readings come with the cut:** each letter keeps its akshara(s) (`Letter.text`, the `text` column of samples.csv). The app stores them as readings of the book's Tesseract run (`_store_readings`; texts that are not labels are left out), so suggestions, mixed groups and "Fix cuts" work right after capture, without "Suggest labels". Capturing again removes the old runs.
- **Labels at capture** (asked for by the user, 2026-10-06: "those cuts should be labelled by what Tesseract reads at that time, so I don't need an extra step"): after grouping, every group whose vote gives a suggestion (C11) gets that label; groups whose suggestion is the same label are merged into the largest (one label, one group). Then an unsure sample whose reading is the label of a group, and whose shape is within `group_distance` of that group's centre, joins it. The same runs after "Add new pages" and "Cut a page again". These labels are **"auto" (not reviewed)**: the "Not reviewed" filter lists them, and they do not count as work done by hand, so capturing again does not ask. Mixed groups (no reading with 60% of the votes) stay unlabelled. Locked groups are not touched (`suggest.auto_label`).
- **Tesseract missing:** a capture (or add pages, cut a page again) of a book cut by Tesseract stops at once with the reason, instead of failing page by page. Tesseract runs one thread per process, since the pages are cut in worker processes.

**Tests:** a line is cut at the gaps into one letter per akshara, with its text, kind and position; cuts too close together keep two aksharas in one sample; an akshara without a box stays with its neighbour; a line Tesseract cannot read (an error or nothing read) keeps the shape cut; a readable line is cut by the reading; a capture with a stand-in for Tesseract cuts by the reading and stores the readings; the capture labels the groups from the readings (merged into one group per label, "auto", not counted as work by hand); a shape-cut capture gives no labels; an unknown cut method is refused; the Cutting choice in Pages & capture (printed books only).

**Measured** (`TUNING_PHASE2.md`): on 3 transcribed lines the Tesseract cut gives 52 / 50 / 47 samples for 51 / 52 / 46 aksharas (shapes: 57 / 46 / 51). On the user's 23-page printed book: samples read as several letters fall from 1,325 to 583, groups from 531 to 399, groups (≥ 5 samples) with a suggestion rise from 27% to 34%, unsure samples from 2,145 to 1,995; time 234 s against 255 s for shapes plus a Tesseract run. By eye about 30 of 40 random samples are clean single letters (shapes: about 26). The number of mixed groups does not change (52 / 53).

**Done when:** a printed book can be captured either way, and the two are compared on the same pages. *Met; the user compares on their own books.*

**Changes from the original plan:** a new chunk. The default stays the shape cut: it is the only one for handwriting, and on print the gain is real but modest. Labelling at capture goes further than C11's rule that a suggestion never sets a label by itself: the user asked for it for books cut by Tesseract, the labels need a 60% majority of the group's readings, and they stay marked not reviewed.

### C12d. Splitting groups that mix two letters

**Status:** built (2026-10-06). Reported by the user: in book 3, ने groups held ते, न groups held म, प groups held व; asked to tell these apart at grouping, for handwriting too, without splitting one letter into several groups by its strokes.

**Goal:** groups hold one letter each, without more groups of the same letter.

**Files:** additions to `app/suggest.py` (`mixed_splits`, `_after_reading`, `auto_label`), `app/actions.py` (`split_mixed`), `app/api.py`, `app/library.py` (capture summary), `config.py`; `frontend/src/screens/Suggestions.tsx`, `api.ts` (+ test); `tests/test_split_mixed.py`; `docs/TUNING_PHASE2.md`.

**What it does:**
- **Shape alone is not enough** (measured in `TUNING_PHASE2.md`): the fingerprint tells the letters apart about as well as any variant tried; a tighter grouping distance multiplies the groups; splitting groups by shape splits one letter by stroke weight; even strokes do not help. So the C4 grouping is unchanged.
- **Split by reading, checked by shape** (`mixed_splits`): in each group, the samples read as another letter than the group's main reading leave it, to a new group of their own, when there are at least `split_min_samples` (5) of them and `split_min_share` (10%) of the group, the centre of their shapes is at least `split_distance` (0.25) from the centre of the main reading's samples, and each of them is closer to its own reading's centre. Misreadings of the same shape (न read as ना) are close and stay; real other letters (ते in a ने group) are far and leave. A group with one reading is never split, however varied its strokes, so one letter does not end in several groups. Locked groups are left alone.
- **When it runs:** after every reading run (Tesseract, C11, or other books, C13) as one undoable action (`split_mixed`); at capture for books cut by Tesseract, before their labels are given (C12c); and from **"Split mixed groups"** in the Label suggestions panel (`POST /api/books/{id}/actions/split-mixed`). The new groups are unlabelled and get their own suggestions; a labelled group keeps its label.
- **Handwriting:** the rule works with any reader. With the labelled-books reader (C13) it splits handwritten groups the same way; with Tesseract on handwriting, the shape check keeps its many wrong readings from splitting groups (measured: one split in 854 letters, a right one).

**Tests:** two letters merged into one group come apart after reading, as one undoable action; a misreading of the same shape stays; one reading never splits a group of varied shapes; too few letters do not split; locked groups are left alone; running it again on clean groups does nothing; the panel button.

**Measured** (`TUNING_PHASE2.md`): on all letters of book 3, mixed groups (≥ 5 samples) fall from 46 to 28 and purity rises from 52.9% to 63.8%, with 333 groups instead of 252; the 9 confusable letters from 72.6% to 92.3% purity with 10 more groups. The user's examples: g0001 lost its 152 ते, g0002 its 57 म and 34 मा (its 70 ना are misread न and stay), g0003 its 36 व and 26 वा.

**Done when:** the user's mixed groups come apart without the common letters splitting into more groups. *Met on a copy of book 3; to be checked by the user.*

**Changes from the original plan:** a new chunk. Three shape-only approaches were tried and dropped (smaller grouping distance, splitting by shape, even strokes); see `TUNING_PHASE2.md`.

### Part B: suggestions for handwriting

### C13. Suggestions from other labelled books

**Status:** built (2026-10-06). Open: the measurement on handwriting, once a handwritten book is labelled (see "Done when").

**Goal:** use the labelled groups of earlier books (printed or handwritten) to suggest labels in a new book, with no training and no new dependency. It is the first reader for handwriting, where Tesseract reads too many letters wrong (C10).

**Files:** additions to `app/suggest.py` (`reference_books`, `run_books`, `engines`, `group_suggestions`; the reader is a parameter of `group_readings`, `sample_readings`, `samples_read_as`, `suggestion_accuracy`), `app/jobs.py`, `app/api.py`, `app/schemas.py`, `config.py`; `frontend/src/screens/Suggestions.tsx`, `api.ts`, `styles.css` (+ tests); `tests/test_suggest_books.py`, a change in `tests/test_api.py`; `docs/TUNING_PHASE2.md`.

**What it does:**
- **Reference books** (`GET /api/books/{id}/reference-books`): every other book with labelled groups, with its number of labelled groups, whether its fingerprints can be compared (the same C4 settings `normalize_size`, `fp_*`), and whether it is used by default (comparable and the same writing). The user can tick others, for example printed books for a handwritten one. Books that cannot be compared are not offered.
- **Reading each sample** (`run_books`, engine `books`): the labelled group centres of the chosen books; a sample's reading is the vote of the `books_k` (5) nearest centres within `books_distance` (0.5), weighted by 1 / distance; its confidence is the winner's share of that vote. Samples with no centre that close get no reading. One reading per sample is stored as the book's run of engine `books` (replacing the previous one), with the 3 best labels as alternatives and the nearest distance.
- **Groups vote live from these readings**, as from Tesseract's (C11): so moves, merges and splits are followed, and C12's readings line, badges, "Mixed readings", bulk accept and the accuracy check work unchanged.
- **Two readers on one book:** the book's main reader is Tesseract on printed books and the other books on handwritten ones (`engines`). A group carries the main reader's suggestion; when the other reader suggests the same label, the suggestion lists both (`agree`); when only the other one suggests, its suggestion is shown; when they differ, the other one is `other_suggestion`.
- **In the app:** the Label suggestions panel gets **"From your labelled books"**: the reference books with check boxes (defaults ticked), "Suggest from labelled books" (the main button on handwritten books, first in the panel), and when it last ran. The chip says where a suggestion comes from ("from your labelled books", "your labelled books and Tesseract agree") and shows the other reader's different suggestion with "Accept this instead". "Checked against your labels" is shown per reader.
- **API:** `POST /api/books/{id}/suggest {"engine": "books", "books": [ids]}` (a job; 400 with the reason when no other book can teach this one); groups carry `other_suggestion`; `GET /api/books/{id}/suggestion-accuracy?engine=books`.

**Tests:** reference books and defaults; another writing is not used by default but can be chosen; other fingerprint settings cannot be compared; a second book of the same pages gets the labels of the first, with suggestions from engine `books`; the accuracy check against labels; a new run replaces the old one, and the main reader follows the writing; agreement and `other_suggestion` with Tesseract; the API routes. Screen: the reference books (defaults ticked, not comparable ones hidden), starting the job, no other labelled book, the chip's source, agreement and the other suggestion.

**Measured** (`TUNING_PHASE2.md`): no handwritten book is labelled yet, so it was measured on print. Book 3 (cut by shapes) suggesting for book 4 (the same pages cut by Tesseract, grouped on its own), with the pages split in halves so no page is on both sides: 89% of the read samples right, group suggestions 31 right / 1 wrong and 30 / 1 (about half the groups get none: their letter is not labelled in the reference half). The distance limit matters (0.55: 5 and 4 wrong), the number of voting groups does not. The job takes about 3 s for 14,000 samples.

**Done when:** a second book of the same hand gets suggestions for most of its common letters, with the measured accuracy recorded. *Measured on print (above). On handwriting: open until a handwritten book is labelled; then the page-split measurement is repeated on it.*

**Changes from the original plan:**
- **Readings per sample, not suggestions per group.** The plan voted the nearest reference centres for each group's centre. Reading each sample and letting groups vote (as C11 does for Tesseract) keeps suggestions right after moves and merges, and gives C12's readings, badges and mixed-group tools for free.
- **`books_distance` (0.5) instead of `group_distance` (0.55)**, measured: the grouping distance lets look-alikes in (4 to 5 wrong group suggestions instead of 1).
- **Agreement is shown, not added to the share:** "agreement raises the share shown" would mix two different votes; the chip says both readers agree instead.
- **Measured on print** for now: there are no handwritten labels yet.

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
| C11 | Matching OCR to samples, group suggestions | done | suggestions on groups and unsure samples | FR-7 |
| C12 | Reviewing suggestions, measuring | built (measurement after a full review) |
| C12b | Fixing cuts with Tesseract's readings (printed books) | built | split samples holding several letters, join cut pieces; one undo | FR-8 |
| C12c | Cutting by Tesseract's reading (printed books) | built | per-book choice of cutting; readings stored at capture | FR-5, FR-7 |
| C12d | Splitting groups that mix two letters | built | mixed groups split by reading where shapes agree; never by stroke | FR-7 | accept / reject / bulk accept; measured accuracy | FR-7, FR-8 |
| C13 | Suggestions from other labelled books | built (handwriting measurement open) | handwriting suggestions, no training | FR-7 |
| C14 | Letter classifier | **next** | `model.onnx`, per-class accuracy report | FR-11 |
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
| `align_sure_overlap` | C11 | 0.8 |
| `align_min_matched` | C11 | 0.5 (share of a line's samples) |
| `suggest_min_votes` | C11 | 3 |
| `suggest_min_share` | C11 | 0.6 |
| `suggest_min_confidence` | C11 | 80 (Tesseract scale 0 to 100) |
| `bulk_accept_share` | C12 | 0.9 (to be set from the C12 measurement after a full review) |
| `cut_method` | C12c | `shapes` (or `tesseract`) |
| `tesseract_cut_min_gap` | C12c | 0.3 (x the median akshara width) |
| `recut_window` | C12b, C12c | 0.3 (x the line's median sample width) |
| `recut_min_width` | C12b | 0.45 (x the line's median sample width) |
| `recut_min_group` | C12b | 5 |
| `reference_books` | C13 | all comparable books with the same writing (chosen per run in the panel, not a stored setting) |
| `split_distance`, `split_min_samples`, `split_min_share` | C12d | 0.25, 5, 0.1 (measured in C12d) |
| `books_k` | C13 | 5 |
| `books_distance` | C13 | 0.5 (measured in C13) |
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
| Tesseract's character boxes are wrong for vowel signs and conjuncts | Alignment uses boxes **and** order, leaves out implausible boxes, keeps only clear matches, and refuses unclear lines (C11). Raw hOCR is kept, so the rules can be improved without re-running OCR. |
| Fixing cuts with Tesseract cuts letters wrongly | Splits only between aksharas; every new piece must look like a letter of the book (group centre, width); never two letters joined; locked groups untouched; one undo takes the whole fix back (C12b). |
| Phase 1 groups mix different letters on print, so few groups get a suggestion (C11: 27 to 32%) | Groups show their most common readings; C12 adds a "Mixed readings" filter and "select samples read as X" to split them, after which the parts get suggestions at once. |
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

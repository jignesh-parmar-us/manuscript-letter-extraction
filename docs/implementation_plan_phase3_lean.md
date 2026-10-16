# Manuscript Letter Extraction: Implementation Plan, Phase 3 (lean scope)

The plan to **build**. It is the full Phase 3 plan (`docs/implementation_plan_phase3.md`, kept unchanged as
the reference) cut down to what is needed to separate datasets from books. Everything left out is listed in
section 6 (later), so nothing is lost. Same chunk names (C19–C24), so the two plans can be read side by side.

**Status:** C19 built (2026-10-16), waiting for Stop 1 (your check of the screens). Written 2026-10-15 from the
full plan of 2026-10-14 and its answered decisions. Comes **after the speed plan** (`docs/SPEED_PLAN.md`, S1–S4).
Next: C20.

**Building time:** about **16–20 hours** (the full plan: about 25–32).

## 0. The idea in one picture

| Today | After Phase 3 (lean) |
|---|---|
| A **book** has Training Data pages and Read Book pages | A **dataset** is a set of pages whose letters are cut, grouped, reviewed and labelled. A **book** is something to read. They are separate things. |
| Read Book points at a folder or a PDF | A new book is created with a **type** (printed / handwritten), a **name**, and **uploaded** images or a PDF. Its pages are managed in the app. Existing books keep their files where they are. |
| A book's reader learns from its own Training Data | A book picks **one or more datasets** (and word lists) to learn from |
| Training Data → "Readers" (letter reader) vs. Whole lines (our reader) | Two clearly named things: the **Letter checker** (inside a dataset) and the **Reading model** (for books) |
| Read Book → "Cut pages" / "Cut again" | **Prepare for reading** / **Prepare again** |
| Text → Tesseract / our reader / Cut letters | Text → Tesseract / our reader. Cut letters is hidden. Pages to export can be chosen. |

Words used from here on:

- **Dataset:** what "Training Data of a book" is now. Same screens (Pages & capture, Review groups, Pages,
  Export dataset), same rules (fairness rule: no weighting by group size; min samples per group is a setting).
- **Book:** only what is read. Pages, preparing, text, reading setup, line truth.
- **Letter checker:** today's Training Data → Readers (see C19).
- **Reading model:** the thing a book reads with: the line-search reader and the language model, trained from
  the book's chosen datasets and word lists.

## 1. How the app is built today

As in section 1 of the full plan (checked in the code on 2026-10-14). The points that matter here:

- **One `book` table row holds both parts** (`page.part`, `sample.part`: `training` or `read`; Read Book data
  in `<book folder>/read/`).
- **Our reader (line search)** is kept per book (`<book folder>/line-search/`), trained on the book's own
  reviewed letters and checked lines (`linesearch.py`).
- **The language model** is built per book from its labels, proofread lines and word lists (`dictionary.py`).
- **Fold-fair measuring relies on** every Read Book page also being a Training Data page of the same book
  (`linesearch.measure`).
- `linesearch._line_ink` pastes the line's **cut letters' masks**, so Prepare for reading must still cut the
  letters (ungrouped). Hiding Cut letters in Text is safe; removing the cutting is not, yet.

## 2. Decisions

Kept from the full plan:

1. **One table, a `kind` column** (`dataset` | `book`), not two tables.
2. **Datasets are chosen in a new book tab "Reading setup"**, with the word lists (today's Dictionary) as its
   second part. Datasets can be added, removed, created and opened there; deleting a dataset is on the
   Datasets screen only and says which books use it.
3. **Existing books are split, not deleted:** each current book with Read Book pages becomes a dataset and a
   book of the same name, linked (the book uses that dataset by default). Backup first; a dry run on a copy
   first; I ask before running it on your library (data safety rule).
4. **Datasets take uploads too.**

Changed for the lean scope (the full decision is in section 6, later):

5. **Uploads folder for new uploads only.** New datasets and books upload into `<uploads>/datasets/<folder>/`
   and `<uploads>/books/<folder>/`; `uploads` is an app setting (per-user `settings.json`, default
   `<library>/uploads`), but changing it does not move files yet. **Existing books keep their files where
   they are**: no file is moved, so no file move can go wrong. The rule "the input folder must not be inside
   the library" (`library._check_input_dir`) does not apply to the uploads folder.
6. **One reading model per book.** The table is built so a model can be shared later (a model has its own
   datasets, word lists and folder; a book points at one), but each book trains its own.
7. **No redirects for the old API routes:** only the app calls them, and its screens change in the same commit.

## 3. Reading setup (one screen)

**Read Book → Reading setup**, three parts:

1. **Datasets used** (tick one or several; each shows pages, reviewed letters, writing type; a warning when
   the writing type differs from the book's). *Add dataset* (pick one, or *New dataset*), *Remove from this
   book* (the dataset itself is untouched), *Open*.
2. **Word lists** (today's Dictionary, unchanged inside).
3. **Reading model:** what it was trained on, *out of date* when the datasets or word lists changed,
   **Train** / **Retrain**, **Measure**.

The tab "Dictionary" disappears; its help page points to Reading setup.

## 4. Working rule

- **No heavy runs while implementing:** no Measure, no harness, no full test suite (CLAUDE.md). The tests of
  the changed modules, `fast` (`docs/SPEED_PLAN.md` S2), and `npm test` when `frontend/` changed. Heavy runs
  only when you ask: the C20 dry run and migration, one training in C23, the C24 gate, `full` before merging.
- **Three stops for your check:** after C19, after C20 (it moves your reviewed data between rows), and at the
  end (C21–C24 together).
- Each chunk is one commit, ends with something to run and check by eye, and updates this plan,
  `docs/help/` and the README in the same commit.
- A new session per chunk (this file carries what it needs). Suggested model: Sonnet for the screen-only
  chunks C19, C21, C22; Opus for C20, C23, C24.
- C19 was planned to touch only `frontend/`; as built it also needed two small backend additions (section 8).

## 5. Chunks

### C19. Names and small screens (no data change), 2–3 h — built 2026-10-16

As built (what differs from the points below is in section 8):

- **Text:** *Cut letters* (the tab, its Convert buttons and its downloads) is hidden unless the **book setting
  `show_cut_letters`** (default off; `config.py`) is on. It is switched with a tick box *Show Cut letters* in
  Pages & capture → Settings, which keeps the book's other settings. A remembered choice of Cut letters falls back to
  Whole lines (Tesseract) while the setting is off. No data is changed.
- **Export pages** (both Whole lines views): the button before the downloads says *All N pages* or *K ticked pages*
  and opens a tick box per page (*(not read)* beside pages without a reading), **Select all**, **Select none**,
  **Only this page**. .txt, Word, PDF, the picture (one .png per page) and the page images (PDF) take the ticked
  pages in page order, or every page when none is ticked. The ticks are kept per book in the browser
  (`export-pages-<book id>`), the same in both views. The old *Page …* / *Whole book …* buttons are gone.
- **Letter checker:** the section, its heading, its table and job names, and every "letter reader" on the screens
  (Review groups, Check these, suggestions, mix-up tips) say *letter checker*. Its first line: finds letters
  probably in the wrong group (Check these) and suggests labels; it does not read books.
- **Prepare:** Read Book tab *Upload & capture* → **Prepare**; *Cut the pages* → **Prepare for reading** (*Prepare
  the remaining pages* when some are prepared); *Cut again* → **Prepare again**; status *OK* → **Prepared**; "N of M
  pages prepared"; the job panel says *Preparing the book pages for reading* / *Preparing a page again*. Datasets
  (Training Data) keep *Capture* and *Cut again*. The section addresses (`#/books/<id>/read`, `/readers`) are kept.
- **Files:** `frontend/src/screens/{BookView,ReadBook,TextView,WholeLinesView,Readers,Capture,CheckView,Review,
  GroupView,Suggestions,TruthView}.tsx`, `components/SampleGrid.tsx`, `api.ts`, `styles.css`; backend
  `app/api.py` (`page_ids` on `/files/texts` and `/files/page-images`), `app/texts.py`, `app/wholelines.py`
  (`page_ids` filters), `config.py` (`show_cut_letters`); tests (screen tests of those screens, a new ticked-pages
  test, `tests/test_wholelines.py`, `tests/test_convert.py`); `docs/help/{new-book,workflow,parts,our-reader}.html`,
  README.

The plan as written:


- **Text:** hide *Cut letters* (the tab and its Convert button). Data is kept; a setting "Show Cut letters"
  (off) brings it back for experiments.
- **Export pages:** a tick box per page in Text, **Select all / none**; Download uses the ticked pages (all,
  if none ticked). For .txt, Word, PDF and picture.
- **Readers → Letter checker.** Its first line says what it does: finds letters probably in the wrong group
  (Check these) and suggests labels; it does not read books.
- **Cut pages / Cut again → Prepare for reading / Prepare again** (Read Book tab *Upload & capture* →
  *Prepare*). Statuses say "Prepared". "Cut" and "Capture" stay for datasets.
- **Files:** `frontend/src/screens/{BookView,ReadBook,TextView,Readers,Capture}.tsx`, `api.ts`, tests,
  `docs/help/*`, README.

**Stop 1:** you check the screens.

### C20. Datasets and books become separate things (data change), 4–5 h

- Migration `0017` (`0016` is taken by speed S5's index on `sample.line_id`): `book.kind` (default `dataset`). For every existing book with Read Book pages: a
  `book`-kind row with the same name (suffix if taken); its `part = read` pages, their lines, `whole_line`,
  `line_truth`, `page_text`, readings and ungrouped samples move to the new row; the `read/` and
  `line-search/` folders move to the new book's folder; `book.read_dataset_id` links it to its dataset. Books
  without Read Book pages stay datasets only. **Page image files are not moved** (decision 5): the rows keep
  pointing at where they are.
- **Before running:** a backup of the library folder (location told to you); a dry run on a copy in the
  scratchpad with counts before and after (pages, lines, line truth, reviewed groups, labels) that must match.
  Then I ask before running it on your library.
- The setting `uploads` is added (used by C21).
- API: `/api/datasets/...` and `/api/books/...`; the screens move to them in the same commit.
- **Files:** `app/db.py`, `app/migrations/versions/0017_*.py`, `app/library.py`, `app/api.py`,
  `app/schemas.py`, `frontend/src/api.ts`, tests.

**Stop 2:** you check the counts and the app on your library.

### C21. Two lists, two creators, 2–3 h

- **Datasets** screen: list, create (name, writing type, **upload images or a PDF** with a file picker, or
  **pick a folder** whose images are copied into the uploads folder).
- **Books** screen: list, **New book**: type, name, then **upload a PDF or images** (file picker, several
  files). A PDF becomes page images as now (`import_pdf`).
- **Files:** `frontend/src/screens/Books.tsx` (split into `Datasets.tsx`, `Books.tsx`), `route.ts`,
  `App.tsx`, `app/api.py` (upload endpoints), `app/library.py`, tests.

### C22. Page manager for a book and a dataset, 3 h

- One page manager for both. Pages tab: thumbnails and a table; **Add pages** (upload more), **Delete**,
  **Exclude / Include** (an excluded page is skipped by Prepare, Read and export in a book, and by capture,
  training and export in a dataset, but kept), **▲ / ▼** to change the order. Order is stored
  (`page.number`); `page.excluded` is new.
- Reading and export follow this order (the C19 export already takes pages in `page.number` order; an excluded
  page must also leave the C19 tick list and the "every page" download). Deleting or excluding a page asks first and says what is lost when it
  has checked lines (Line truth), corrections, or (in a dataset) reviewed groups.
- **Files:** `app/db.py` (`page.excluded`), `app/library.py`, `app/api.py`, `frontend/src/screens/ReadBook.tsx`
  → `BookPages.tsx`, tests.

### C23. Reading setup and a reading model per book, 4–5 h

- New table `reading_model` (name, dataset ids, word list ids, folder, trained-on hash, trained at) and
  `book.reading_model_id`; each book gets its own row. Files in `<library>/models/<folder>/` (the line-search
  reader moves here from the book folder).
- The line search learns the reviewed letters of the **chosen datasets**; the language model learns their
  labels and proofread lines and the chosen word lists, not "the book's own" Training Data.
- **Fairness rule kept:** balanced copies per group, min samples a setting, no weighting by group size or
  frequency; frequency only in the language model.
- The Reading setup screen (section 3). **Train** is offered when the choice changed.
- **Files:** `app/db.py`, `app/migrations`, `app/linesearch.py` (paths, training sources), `app/dictionary.py`
  (sources), `app/api.py`, `frontend/src/screens/ReadingSetup.tsx` (replaces `Dictionary.tsx` as the tab),
  tests. `app/readers.py` (letter checker) unchanged.

### C24. Fold-fair measuring without "same book", 2–3 h

- A book's page and a dataset's page are the *same page* when their `sha256` is equal. For each fold, Measure
  leaves out the letters, labels and corrections of the datasets' pages that match the tested pages. Pages in
  no dataset need nothing left out.
- The speed plan's feature store is keyed by sample and mask content, so the split does not make it stale.
- **Gate (must pass before C24 is done):** on a copy of your library, Measure after the split gives the same
  numbers as before it on the same checked lines (the "after" numbers of `docs/SPEED_PLAN.md` S4), with a
  line-by-line page to check by eye. Both printed and handwritten are tried; I say if a number exists for
  only one (today the checked lines are all printed, book 6).
- **Files:** `app/linesearch.py` (`measure`), `app/dictionary.py` (`book_model_without`), tests.

**Stop 3:** you check C21–C24 together.

## 6. Later (left out of the lean scope)

From the full plan, to build when wanted:

- **Existing files move into the uploads folder** automatically (copy, verify by hash, switch paths, keep the
  originals), and move again when the uploads folder is changed in settings (full plan, decisions 2 and 6).
- **Reading models shared between books:** two books with the same datasets and word lists use one trained
  model (full plan, decision 4). The C23 table is ready for it.
- **Drag and drop** of uploads (C21) and **drag to reorder** pages (C22).
- Old API routes kept as redirects (dropped, not needed while only the app calls them).
- The line search on the stored line image instead of the cut letters' masks, so Prepare stops cutting
  letters. Needs its own measurement first.
- Copy pages of a book into a dataset ("use these pages for training too").

## 7. Time to build

| Chunk | My work | Heavy runs (only when you ask) |
|---|---|---|
| C19 names, hide Cut letters, export page choice | 2–3 h | — |
| C20 datasets and books separate | 4–5 h | dry run on a copy, backup, migration |
| C21 two lists, two creators | 2–3 h | — |
| C22 page manager | 3 h | — |
| C23 reading setup, one model per book | 4–5 h | one training |
| C24 fold-fair Measure without "same book" | 2–3 h | the gate Measure |

About **16–20 hours** of building, after the speed plan's 5–7.

## 8. Changes from this plan

**C19 (2026-10-16):**

1. **Not frontend-only.** Downloading the ticked pages needed the backend to take several pages: `page_ids`
   (comma-separated) on `/files/texts/{book}` and `/files/page-images/{book}`, filtered in `texts.book_page_texts`
   and `wholelines.whole_line_texts`. One ticked page is downloaded as that page (its file name, no heading);
   ids of another book are ignored. The old `page_id` still works (the hidden Cut letters view uses it).
2. **"Show Cut letters" is a book setting** (`show_cut_letters` in `config.py`), not an app setting: the app has no
   app-wide settings screen yet (the per-user `settings.json` comes with C20's `uploads`). Its tick box is in
   Pages & capture → Settings (the card's title is now just *Settings*). If C20 adds app settings, it may move there.
3. **Export page choice only in the Whole lines views**, the views that are shown. The hidden Cut letters view keeps
   its old page / whole-book downloads.
4. **Picture of several pages:** one .png per ticked page (the browser may ask once to allow several downloads),
   not one tall picture (a canvas has a height limit). The **page images (PDF)** follow the ticks too.
5. **"Letter checker" is used everywhere on the screens**, not only in its section (Review groups, Check these,
   suggestions, mix-up tips, the reader names in Cut letters), so the two words never mix. Code names
   (`readers.py`, `Readers.tsx`, `reader_id`, the `/readers` address) are unchanged.
6. **Later chunks:** C20's migration is `0017` (speed S5 used `0016`). C21/C22: the *Prepare* tab is the one that
   becomes the book's page manager; keep its *Prepare for reading* / *Prepare again* names. C22: an excluded page
   leaves the C19 tick list and downloads.

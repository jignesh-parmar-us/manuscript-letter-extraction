# Manuscript Letter Extraction: Implementation Plan, Phase 3 (lean scope)

The plan to **build**. It is the full Phase 3 plan (`docs/implementation_plan_phase3.md`, kept unchanged as
the reference) cut down to what is needed to separate datasets from books. Everything left out is listed in
section 6 (later), so nothing is lost. Same chunk names (C19–C24), so the two plans can be read side by side.

**Status:** C19 built and committed (2026-10-16). C20 built (2026-10-16); dry run on a copy and the split of your
library done the same day (all counts equal; book 6 → dataset 6 + book 8, book 7 a book; backup
`~/Documents/Manuscript Letters backup 2026-10-16 225329`). Stop 2 passed (2026-10-16). Written 2026-10-15
from the full plan of 2026-10-14 and its answered decisions. Comes **after the speed plan**
(`docs/SPEED_PLAN.md`, S1–S4). Next: C21.

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

### C20. Datasets and books become separate things (data change), 4–5 h — built 2026-10-16

As built (what differs from the points below, and why, is in section 8):

- **Migration `0017`** (schema only): `book.kind` (`dataset` | `book`, every existing row a dataset),
  `book.read_dataset_id` (foreign key to `book.id`, set null when the dataset is deleted), and a name unique per
  kind (`uq_book_kind_name`) instead of in the whole library. On your library (snapshot of 2026-10-16) it takes
  about 9 s and changes no count.
- **The split is a command, not the migration** (your answer, 2026-10-16): `python -m letter_extractor.app.split
  --library DIR` shows per row what it would do (and problems that stop it); `--run` backs the library up beside it
  (`<library> backup <date time>`: the database through SQLite's backup, the rest as APFS clones on a Mac), splits
  in one transaction and compares the counts (pages and letters per part, lines, groups, reviewed and labelled
  groups, letters in reviewed groups, line truth, checked lines, whole lines, reviewed whole lines, page texts,
  readings, undo steps, word lists). A failure rolls the database back and moves the folders back. Until it has
  run, **the app does not open the library** and prints the two commands (`main.unsplit_message`).
- **What the split does** (`split.py`): a row with Read Book pages and Training Data keeps its id, name, Training
  Data, groups, labels, letter checker, exports and their undo steps as the **dataset**; a new **book** row with the
  same name gets the `read` pages (their lines, whole lines, line truth, page texts go with the pages), the Read
  Book letters, the **undo steps that touch only Read Book letters** (your library: 12, cut fixes in Book pages), the
  Read Book folder / PDF, the settings, the letter checker (for the hidden Cut letters), `read_dataset_id`, and
  the word lists the dataset had (the book is added to them). Folders moved to the book's folder (a rename, same
  disk): `read/`, `line-search/`, `text/read/`, `cache/read-*`. A row with Read Book pages and **no** Training Data
  becomes a book in place (your answer: no empty dataset; your book 7). It refuses, before changing anything, pages
  moved between the parts (their files are in the other part's folders), Read Book letters in a group, and undo
  steps that touch letters of both parts. Your library has none of these (checked on the snapshot).
- **A book learns from its dataset** (until C23 chooses several): `Library.training_source(book)` is the book's
  `read_dataset_id` (a dataset's own id). The line search (`_training_set`, `_signature`, `usual_spacing`, Measure),
  the language model's labels (`dictionary._labels_of`) and the hidden Cut letters' groups (`texts._groups_for`)
  use it; checked lines, proofread lines, word lists, readings and the reader's files stay the book's. A sample's
  files are found in its own row's folder (`Library.folder_of`, `MaskPack(folder_of=…)`, `samples._sample_mask`).
  Measure still leaves out the dataset's pages with the tested pages' file names, so its numbers do not change
  (`tests/test_split.py`: the book's training rows, labels, signature, checked lines, language model and spacing
  are equal to the unsplit row's).
- **Kept apart:** a dataset gets no Read Book pages (Read Book folder, PDF, Prepare refused) and a book no
  Training Data (folder, capture, add pages refused); moving a page between the parts (*Use for training /
  reading*, `set_page_part`) is refused and its button removed. A book has no Training Data folder; only a book
  names a dataset.
- **API:** `GET/POST /api/datasets` and `GET/POST /api/books` (a book: `dataset_id`); 29 routes of what only a
  dataset has moved to `/api/datasets/{id}/…` (404 for a book); reading routes stay `/api/books/{id}/…`; 16 routes of
  what both have answer under both prefixes. Rows carry `kind`, `dataset_id`, `dataset_name`, `used_by`.
  `reference-books` lists datasets only. No redirects (decision 7).
- **Setting `uploads`** in the per-user `settings.json` (`main.uploads_dir`, default `<library>/uploads`), shown in
  `GET /api/app`, set with `POST /api/app/uploads`; nothing uses it before C21.
- **Screens:** the Books screen lists **Books** (pages, learns from) and **Datasets** (numbers, used by) and
  creates either (**New** → Dataset / Book, a book's *Learns from*: datasets of the same writing). A row shows only
  its kind's sections (another section's address opens its first: *Pages & capture* or *Prepare*); the header says
  Dataset / Book and links the dataset. The *Show Cut letters* tick box moved from Pages & capture to the book's
  Prepare → Settings. The letter checker learns from datasets. Help pages and README updated.
- **Files:** `app/db.py`, `app/migrations/versions/0017_datasets_and_books.py`, `app/split.py` (new),
  `app/library.py`, `app/linesearch.py`, `app/linestore.py`, `app/samples.py`, `app/dictionary.py`, `app/texts.py`,
  `app/suggest.py`, `app/api.py`, `app/schemas.py`, `app/main.py`; `frontend/src/api.ts`,
  `screens/{Books,BookView,ReadBook,PageViewer,Capture,Readers,CheckView,TextView,WholeLinesView,Dictionary}.tsx`,
  `styles.css`; tests (`tests/test_split.py` new, `test_book_parts.py` rewritten for a dataset and a book,
  `test_proofread.py`, `test_wholelines.py`, route paths in eight test files; screen tests); help, README.

The plan as written:

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

*After C20:* the Books screen already lists both kinds and creates either (without uploads); C21 splits it into the
two screens and adds the uploads. `GET/POST /api/datasets` and `/api/books` exist; the setting `uploads` too.

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

*After C20:* replace `Library.training_source` (one linked dataset, `book.read_dataset_id`) by the chosen datasets
in every place that calls it (`linesearch`, `dictionary._labels_of`, `texts._groups_for`); the reader's files are in
the book's folder (`line-search/`, moved there by the split) and its mask pack already reads other rows' letters
(`MaskPack(folder_of=…)`).

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

*After C20:* Measure of a split book already leaves out its dataset's pages with the tested pages' **file names**
(the same pages, as before the split), so its numbers should not change; C24 changes the match to `sha256` (robust to
renamed files) and to several datasets. The gate measurement is still needed.

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

**C20 (2026-10-16):**

1. **The split is a separate command, not part of migration `0017`** (your choice): the migration only adds the
   columns, so starting the app with the new code cannot split your library by accident; the app refuses to open an
   unsplit library and prints the commands. The plan's "backup, dry run on a copy, then I ask" is the command's
   `--run` (with its backup) on a copy first.
2. **Names are unique per kind** (your choice), so the book keeps the dataset's name (no suffix).
3. **A Read Book without Training Data becomes a book in place** (your choice): no empty dataset (book 7).
4. **Undo steps move with their letters:** the plan did not say; those touching only Read Book letters go to the
   book (12 on your library), the rest stay. Steps touching both parts stop the split (none on your library).
5. **The word lists** of a split row are kept by the dataset and given to the book too (the Dictionary is a book
   tab).
6. **Not frontend/API only: a book must learn from its dataset now,** or our reader, Measure and the language model
   would have nothing to learn from between C20 and C23. `Library.training_source` is that bridge (one dataset); C23
   replaces it. The plan's C20 file list did not have `linesearch.py`, `dictionary.py`, `texts.py`, `samples.py`,
   `linestore.py`.
7. **Moving pages between the parts is gone** (*Use for training / reading*): it would put both parts in one row
   again. Copying a book's pages into a dataset is in section 6 (later). Its tests were replaced by refusal tests.
8. **Routes:** only what is a dataset's alone moved to `/api/datasets/{id}`; reading routes stay at
   `/api/books/{id}` without a kind check (a dataset has no Read Book pages, and the library refuses to give it
   any), and what both have answers under both prefixes. The screens call those with `/api/books/{id}`.
9. **Show Cut letters moved** from Pages & capture (now a dataset's) to the book's Prepare → Settings, where the
   setting acts.
10. **Later chunks:** C21, C23 and C24 have a note "After C20" with what is already there.

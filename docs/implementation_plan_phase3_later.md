# Manuscript Letter Extraction: Implementation Plan, Phase 3 "later" (C25+)

The plan for section 6 of `docs/implementation_plan_phase3_lean.md`: the things left out of the lean scope.
It starts after C19–C24. Chunk names go on from there (C25–C29).

**Status:** written 2026-10-17. Questions 1 and 2 answered the same day (section 3). **C25 and C26 built
2026-10-17**; C26's move ran on your library the same day (21:34, checked: section "C26 as built"). C27–C29 not
started; questions 3–6 still open.

## 0. What is where today (checked in the code and, read-only, in your library on 2026-10-17)

- **Your library is already at migration `0019`**: it has `reading_model` rows (book 7 → model 1, no dataset;
  book 8 → model 2, dataset 6), and book 8's reader is in `models/0008-…/`. So step 1 of the lean plan's
  "Start here" (back up before the migrations) is already behind us. The newest backup is
  `~/Documents/Manuscript Letters backup 2026-10-16 225329`, from before the migrations. **A new backup before
  C26 is part of the plan** (section 4).
- **Where the page images are:**

  | Row | Kind | Pages | Folder |
  |---|---|---|---|
  | 1, 3, 4, 6 | dataset | 7, 23, 23, 23 | `~/Downloads/black and white` (one folder for all four, 102 MB, 91 images) |
  | 8 | book | 91 | `~/Downloads/black and white` (the same folder) |
  | 5 | dataset | 35 | `~/Documents/GujTypingApp/inputs/handwritten_samples` (66 MB) |
  | 7 | book | 6 | from a PDF: the pages are in `<library>/books/0007-…/read/pages/` (the app's own already) |

  No row uses the uploads folder yet. Five rows depend on a folder in **Downloads**, which is easy to clear by
  accident. That is the main reason to do C26.
- **Uploads** (`library.upload_dir`, `main.uploads_dir`): `<uploads>/datasets/<row folder>/` and
  `<uploads>/books/<row folder>/`. The setting is in `settings.json`, and changing it moves nothing.
  `pages.owns_files` says a row's images are the app's own when its folder **is** its upload folder under the
  **current** setting. So after the setting changes, older uploads count as "a folder of your own": the app
  stops deleting their files and refuses to upload more into them. C26 fixes that.
- **Order of pages:** `pages.move_page(…, by)` already moves a page any number of places (`by` = −1, +1, or
  any number, with a clamp). Drag to reorder needs **no backend change**.
- **Uploads on the screen** (`components/UploadPages.tsx`, `PageFilePicker`): an `<input type="file" multiple>`.
  One file per request, the file as the body (C21, decision 1).
- **The reader learns from more than the datasets.** `linesearch._train` learns the reviewed letters of the
  model's datasets **and the checked lines of the book** (`_learn_corrections`). `_signature` hashes both.
  The language model (`dictionary.book_model`) uses the datasets' labels, **the book's** proofread lines and
  **the book's** word lists. It is cheap and rebuilt automatically. One training of book 8's reader took
  **33 minutes** (`meta.json`: 1984 s, 9,578 letters, 587 labels, 119 checked lines).
- **Our reader reads cut letters, not the line.** `linesearch._line_ink` pastes the masks of a line's cut letters
  (`_paste`). Prepare stores each line's image as an **RGB crop** with other lines painted out (`lines.line_image`,
  `lines/<stem>_L01.png`), **not** its ink mask. The ink mask exists while Prepare runs (`Line.mask` in `lines.py`)
  and is then thrown away. A book's cut letters are also used by: the hidden *Cut letters* view
  (`texts.convert_book`), *Book pages* (fixing cuts, `recut.py`), and which pages our reader reads
  (`linesearch.search_book`: "lines with cut letters").

## 1. The chunks at a glance

| Chunk | What | My work | Heavy runs (only when you ask) | Data change |
|---|---|---|---|---|
| C25 | Drag and drop: uploads and page order | 1.5–2 h | — | none |
| C26 | Page images move into the uploads folder (existing rows, and when the setting changes) | 4–5 h | dry run on a copy, then your library (after a backup) | paths only |
| C27 | Copy a book's pages into a dataset | 2–3 h | — | new dataset pages (no reviewed data touched) |
| C28a | Line ink from the line, not the cut letters: build it and **measure** | 3–4 h | line masks for book 8 on a copy, two Measures | none (a copy) |
| C28b | Prepare stops cutting letters (**only if C28a passes**) | 3–4 h | Prepare of one book, timed | new pages only |
| C29 | Reading models shared between books (**optional**, see question 5) | 4–5 h | one training | model rows |
| — | Old API routes as redirects | **not built** (question 6) | | |

About **14–19 hours** with C29, 10–14 without. Order: C25 is small and on its own. **C26 comes before C27**,
because C27 copies into a dataset's upload folder, and today every dataset uses a folder of your own. C28 is the
largest and needs measurement. C29 is last because it is worth little with two books.

## 2. Chunks

### C25. Drag and drop: uploads and page order, 1.5–2 h — built 2026-10-17

As built (what differs from the points below, and why):

- **Drop zone:** `PageFilePicker` (`components/UploadPages.tsx`) is a dashed box ("Drop them here, or choose files");
  every place that uses it (New book, New dataset, Upload more in Prepare and Pages & capture) takes drops. A drag
  that carries no files (a page row) is ignored; a folder (`webkitGetAsEntry().isDirectory`) is refused with
  "Drop the page images, not their folder.". `droppedFiles` is the check.
- **Drag to reorder** (`components/PageManager.tsx`): a handle ⠿ before ▲ ▼ in the actions cell (not a new column:
  the place column stays first). Only the handle is draggable, so text in the rows can still be selected. A line
  above or below the row under the pointer shows where it lands; `dropMove(from, onto, after)` turns that into the
  `by` of the existing move route. **Excluded pages can be dragged**, as ▲ ▼ already allowed (the plan said they
  could not; that was wrong about ▲ ▼): only files not prepared yet (no row) have no handle.
- **Tests:** `components/PageManager.test.tsx` (a drop after p3 moves p1 by 2; a drop onto a file not prepared yet
  or onto its own place does nothing; `dropMove`), `components/UploadPages.test.tsx` (new: dropped files, checked
  like chosen ones, a folder refused, a disabled box and a drag without files ignored);
  `tests/test_page_manager.py` (a page moved 2 places, and beyond the first: no capture needed).
- **No backend change.**

The plan as written:

Screen only (`frontend/`). The same for printed and handwritten.

- **Drop files to upload:** `PageFilePicker` becomes a drop zone too: a dashed box that says "Drop page images or a
  PDF here, or choose files". It is used in New book, New dataset, Prepare and Pages & capture. Dropped files go
  through the same checks as chosen ones (images or one PDF, not both). A dropped **folder** is refused with a
  message ("drop the images, not the folder"). Reading a folder from a drop works differently in each browser, and
  *Copy a folder of page images* already exists for datasets. The upload itself is unchanged ("Uploading 3 of 12").
- **Drag to reorder pages** (`components/PageManager.tsx`): each row gets a handle (⠿), and a row can be dragged to a
  new place. A line shows where it will land. On drop, the screen calls the existing
  `POST {B}/pages/{id}/move {"by": target − current}`. ▲ ▼ stay, for small moves and for the keyboard. It uses
  HTML5 drag events, with no new library. Pages not prepared yet (no number) and excluded pages can't be dragged,
  as with ▲ ▼ today. It is locked while a job runs.
- **Tests:** `PageManager.test.tsx` (a drop moves by the right `by`; an unprepared row can't be dragged),
  `UploadPages` (dropped files are checked like chosen ones; a folder is refused). Backend: none (a test in
  `test_page_manager.py` that `by = 5` moves 5 places, if one is missing).
- **Docs:** `docs/help/new-book.html`, `workflow.html` (pages), README.

### C26. Page images move into the uploads folder, 4–5 h — built and run on your library 2026-10-17

As built (what differs from the points below, and why):

- **`app/move.py`** (new): `row_plan` / `move_plan` (what a row would move and why it cannot), `move_row` (copy,
  check, switch one row), `move_existing` (all rows from before C26, once per library), `move_uploads` (the setting
  changes), `backup_db`, `notice` / `notice_seen`, and the command (`python -m letter_extractor.app.move --library DIR
  [--run] [--no-backup]`).
- **Automatic at the start, before the screen opens** (your answer 1): `main.main` calls `move_existing` after the
  split check and before serving, not as a job. Then nothing else can run against a row while its folder changes,
  and the console says what it does. If it stops halfway, the rows already moved stay moved (each row is complete
  on its own), and the next start goes on.
- **Once per library, existing rows only** (your answer 1, "automatic for the existing"): `<library>/page-moves.json`
  keeps `existing: {done, pending}`. The first start puts every row that needs a move in it; later starts only try
  the rows still pending (those that failed). Rows made later with *Use this folder* are never moved.
- **Each row gets its own copy** (your answer 2), as clones (`cp -c`; a normal copy across disks), through a hidden
  `.part` file. A file of the same name and content already in the upload folder is used as it is; one with other
  content stops that row.
- **Checked against the original as it is now** (its SHA-256 computed at the move), not against `Page.sha256`: the
  copy must be the same bytes as what the row reads today. A page changed since capture is reported by *page
  problems* as before, in the new folder too. The plan said "against the page's stored hash"; that would have kept a
  row whose original was edited after capture from ever moving.
- **Problems found before copying** (folder not there, a page image missing) keep the row on its folder without
  copying anything. If no row can be tried, **no backup is made**. A failure that repeats at every start becomes a
  notice only once.
- **The backup is `library.db` only**, made with SQLite's backup into `<library> backups/<date time> before moving
  pages/` (beside your existing `2026-10-14-before-recut-failed-pages`). It is not the whole library: no file in the
  library is changed, and cloning about 150,000 letter pictures would take minutes at every first start.
- **`updated_at` is not changed** by the move, so the lists keep their order (the move is meant to be invisible).
- **The notice:** `GET /api/app` carries `page_move` (moved rows with their file counts and old folders, rows not
  moved and why, the backup, the folders no row uses any more) until **OK** (`POST /api/app/page-move/seen`).
  `components/RowList.tsx` → `PageMoveNote`, at the top of Books and Datasets.
- **Uploads setting:** `POST /api/app/uploads` answers `{uploads, job}`: `job` is `null` (saved at once) when the old
  uploads folder has nothing in it, else a job `move_uploads` of the whole library (`Jobs`, `book_id` = `APP` = 0).
  While it runs no row's job can start, and it does not start while any job runs. It copies **every file** of each
  row's upload folder (also a book's PDF), switches the rows that read from there, then saves the setting. All or
  nothing. A new folder inside the old one is refused. The folders card shows its progress and the result.
- **Not built:** moving a book's PDF pages (in the book folder already, as planned) and a separate
  `POST /api/app/move-pages` (the start does it; the command does it on a copy).
- **Tests:** `tests/test_move_pages.py` (new, 12 tests, no capture: three rows sharing a folder get three checked
  copies, the originals stay, the folder is listed as unused, a backup is made, a second run does nothing; pages,
  lines and line truth unchanged; a copy that does not match keeps its row and is moved at the next try; a missing
  page image keeps the row, no backup, the notice once; a PDF book, a row in its upload folder and a row made later
  are not moved; the command without `--run`; the setting change through the API moves and switches, a clash moves
  nothing and keeps the setting, nothing uploaded saves at once, a folder inside the old one is refused, the notice
  until seen; a job of the whole library blocks row jobs and waits for them). `screens/Books.test.tsx` (the setting
  change follows the job; the notice and OK).
- **Files:** `app/move.py` (new), `app/main.py`, `app/jobs.py`, `app/api.py`; `frontend/src/api.ts`,
  `components/RowList.tsx`, `screens/{Books,Datasets,Capture}.tsx`, `styles.css`; help (`new-book`, `workflow`),
  README.
- **Dry run on a copy** (2026-10-17, the database copied into the scratchpad, about 5 s): the listing showed rows
  1, 3, 4, 5, 6 and 8, not book 7 (a PDF); `--run` on the copy took 19 s (backup included). All 202 pages were found
  in their new folders with their stored SHA-256; page problems 0 missing, 0 changed (the "new" files, 84 / 68 / 68 /
  68, are the shared folder's other images, as before); the counts of pages, lines, letters, groups, labels, line
  truth, whole lines and model datasets were the same as in the real database (208 / 2,649 / 129,755 / 2,400 /
  1,030 / 119 / 1,270 / 1); the originals unchanged (names, sizes, dates, hashes compared before and after); a second
  run said "moved already". Datasets 1, 3, 4 and 6 get all 91 images of the shared folder, not only their own 7–23
  pages, so their page lists stay the same.
- **On your library** (2026-10-17 21:34, at the first start of the app with this code): the same six rows moved into
  `~/Documents/Manuscript Letters/uploads/`; checked read-only afterwards: all 202 pages there with their stored
  hashes, the same counts as above. Backup: `~/Documents/Manuscript Letters backups/2026-10-17 213448 before moving
  pages/library.db`. No row uses `~/Downloads/black and white` or `~/Documents/GujTypingApp/inputs/handwritten_samples`
  any more (nothing was deleted).

The plan as written:

This builds full-plan decisions 2 and 6 (*copy, verify by hash, switch paths, keep the originals*). How it starts
(automatic or a button) is question 1.

**What "moving" a row means** (`app/move.py`, new; `Library.move_plan`, `move_row`):

1. **Which rows:** a dataset whose `input_dir`, or a book whose `read_dir`, is not its upload folder. Not moved:
   a book from a PDF (its pages are already the app's own, in `books/<folder>/read/pages/`; its PDF stays where
   it is). The same goes for a row with no pages folder.
2. **Which files:** every page image in the row's folder that the row uses: its pages (also excluded and *Not
   prepared* ones), **and** the images in that folder that are not pages yet. That way the page list
   (`pages.page_list`) shows the same files after the move as before. Other files (not images) are not copied.
3. **Copy** into `<uploads>/<datasets|books>/<row folder>/`, with the **same file names**. Letters, lines,
   thumbnails and checked lines are stored by page and file name, not by folder, so nothing else changes. On this
   Mac the copy is an APFS **clone** (`cp -c`, as `tools/harness/copy_library.sh` does since speed S1). A clone
   takes no extra disk space until one side changes, so the five rows that share `~/Downloads/black and white` cost
   no extra space on the same disk. Across disks it is a normal copy.
4. **Verify:** each copy's `sha256` must equal the page's stored `sha256` (`Page.sha256`). For images that are
   not pages yet, it must equal the original's hash. **If any file doesn't match, the row is not switched**: it
   keeps working from the original folder, its copies are removed, and the result says which file failed.
5. **Switch:** `input_dir` / `read_dir` change to the upload folder, in one transaction per row.
6. **Originals are never deleted.** The result lists the old folders, for you to remove when you like.
   `~/Downloads/black and white` is then used by no row.

**When the uploads setting changes** (`POST /api/app/uploads`): every row whose folder is under the **old** uploads
folder gets the same copy, verify and switch into the new one. The old folder is left in place and its path is
shown once. If anything fails, the setting is **not** changed, and the screen says why. Today's text "new uploads go
to the new folder; old ones stay" changes to say that the pages move.

**Where it shows:** a job `move_pages` (`jobs.py`; one at a time, like every heavy job since S1) with progress
("Copying 40 of 91: …"). The Books and Datasets screens show the result once, with the backup and the old folders.

**Safety** (data safety rule): the backup is the library database (`library.db`) only, because no file is changed
or deleted in place. Its path goes in the log and the notice. Before your library: a **dry run on a copy**
(`--dry-run` lists what would be copied and switched), then the run on the copy, then I ask before your library.
Reviewed groups, labels and line truth are not touched. The only database change is the two path columns.

- **Command too:** `python -m letter_extractor.app.move --library … [--dry-run]`, like the C20 split command, so it
  can be run on a copy without the app.
- **Afterwards:** `owns_files` is true for every moved row, so Delete removes the app's **copy** (never the
  original), and *Upload page images* works in Prepare and Pages & capture for those rows too.
  *Use this folder* (a folder of your own, used where it is) still exists for new datasets; such a row is moved
  the next time (or never, depending on question 1).
- **Files:** `app/move.py` (new), `app/library.py`, `app/jobs.py`, `app/api.py` (`POST /api/app/move-pages`,
  the uploads change), `app/main.py`; `frontend/src/components/RowList.tsx` (folders card), `api.ts`; tests
  `tests/test_move_pages.py` (new: a folder shared by two rows gives two copies; a copy with a wrong hash leaves
  its row on the original; letters and line truth unchanged; a changed setting moves the uploads and refuses on
  failure; a PDF book is not moved); help (`new-book`, `workflow`), README.
- **Printed and handwritten alike:** only files move.

### C27. Copy a book's pages into a dataset, 2–3 h

"Use these pages for training too": the pages of a book you read can also be cut, grouped and labelled. This
replaces the old *Use for training*, which C20 removed.

- **Where:** Prepare → the page manager: tick pages, then **Copy into a dataset…**. Pick a dataset of the
  library (another writing is marked, as in Reading setup), or **New dataset** (name, the book's writing).
- **What happens:** the page images are **copied** (cloned) into the dataset's upload folder under their own
  names. If a name is taken by a **different** image, it becomes `<name>-2.jpg`. If the **same** image is already
  there (same `sha256`), the page is skipped and listed as "already in the dataset". The dataset gets them as new
  pages, *not captured yet*: its own **Capture** cuts and groups them with the dataset's settings, like any other
  page. The book's lines, readings, checked lines and corrections stay with the book. The book's page itself is
  unchanged (not excluded, not moved).
- **Refused** for a dataset whose pages are in a folder of your own (the message points to C26's move), and while
  a job runs for either row.
- **Fold-fair Measure stays fair by itself:** a copied page has the same `sha256` as the book's page, so C24's
  `Library.left_out` already leaves its dataset letters out when that page is tested. The test proves it.
- **Fairness rule:** nothing new. The new letters go through Review groups like any others, and no weighting is
  added.
- **API:** `POST /api/books/{id}/copy-to-dataset {"page_ids", "dataset_id"}` (or `"new_dataset": {name, writing}`),
  a job `copy_pages` (C21's, reused) with the answer listing copied / skipped.
- **Files:** `app/library.py` (`copy_book_pages`), `app/jobs.py`, `app/api.py`; `frontend/src/components/PageManager.tsx`,
  `api.ts`; tests `tests/test_uploads.py` (copy, the same image skipped, a taken name renamed, refused into a
  folder of your own), `tests/test_fold_fair.py` (a copied page's dataset letters are left out), `PageManager.test.tsx`;
  help (`parts`, `workflow`), README.
- **Printed and handwritten alike.**

### C28a. Line ink from the line, not the cut letters: build and measure, 3–4 h + the measurement

Our reader would read a line from its own ink, not from the masks of its cut letters pasted together. This chunk
only **builds the option and measures it**. Nothing changes for you unless C28a passes and C28b is built.

**In simple terms** (written 2026-10-17):

- **Today:** *Prepare* finds the lines on each page, then cuts each line into letters, the same way a dataset is
  cut. A book's letters are never grouped or labelled, but our reader needs them: to read a line, it pastes the
  letter pictures back side by side to rebuild the line, then slides along it looking for aksharas it knows. It is
  like photocopying a page by cutting out every letter and gluing them onto a blank sheet before reading it.
- **The change:** when Prepare finds a line it already knows exactly which ink belongs to it; today that is thrown
  away. C28a keeps it (a small file per line), adds a setting so the reader takes its line from that file instead of
  the glued letters (the old way stays the default), and measures both ways on book 8's 119 checked lines,
  fold-fair, with the line-by-line page.
- **Why it might read better:** nothing is lost or broken by cutting; a badly cut letter (a matra split off, two
  letters merged) does not matter when the reader never uses the cuts.
- **Why it might read worse:** cutting also drops specks, dust and stray marks; reading the whole line brings them
  back, and they might confuse the reader. Only the measurement tells which is bigger.
- **What it leads to (C28b):** if the new way reads at least as well, Prepare stops cutting a book's letters:
  faster, and no thousands of unused letter pictures per book. If it reads worse, nothing changes.
- **The catch:** all checked lines are printed (book 8), so it can only be measured on printed pages (question 4).

- **Keep the line's ink mask at Prepare:** `pipeline.process_file` writes `lines/<stem>_L01_mask.png` (the
  `Line.mask` it has already) beside the line image, and records the line's headline row and main zone, which
  `_line_ink` needs for its band. That is a few KB per line.
- **For pages prepared before:** `tools/line_masks.py <library copy> --book 8` runs the line finder again on
  each page (same code, same settings, so the same lines) and writes only the mask files. A line is matched by its
  stored box; a line whose box differs is listed and left on cut letters. **No database row is changed**, and it
  runs on a copy only.
- **`_line_ink(…)` gets a setting `line_ink`: `letters` (today's, the default) | `line`.** With `line` and a mask
  file there: the line's mask, scaled and border-cleared as now. Without a mask file, it falls back to the cut
  letters, so the old behaviour stays possible.
- **Training is unchanged:** the datasets' letters and their neighbours' ink stay as they are. Only the ink of the
  lines being read (and of the checked lines the reader learns from) changes. **Risk:** the line's ink also has
  the specks and stray marks that cutting dropped. That is what the measurement shows.
- **The measurement** (heavy, only when you ask, on a copy, one at a time): book 8, 4 folds, fold-fair, the same
  119 checked lines. `line_ink = letters` must give the S5 numbers (8.03% ours). Then `line_ink = line`.
  **Pass:** ours no worse than letters beyond the usual ±1 point between trainings, and no worse with the language
  model. Both rows, the difference per page, and the line-by-line page go into `docs/TUNING_PHASE2.md` and here.
- **Printed only, so far:** there are no handwritten checked lines. A handwritten result needs some checked lines
  of a handwritten book first (question 4).
- **Files:** `pipeline.py`, `lines.py`, `app/linesearch.py`, `config.py` (`line_ink`), `tools/line_masks.py` (new);
  tests `tests/test_linesearch*.py` (a mask file is used; without it, cut letters; `letters` gives the same ink as
  before: an equality test), `tests/test_pipeline*.py` (mask file written).

### C28b. Prepare stops cutting letters, 3–4 h (only if C28a passes)

- **Prepare for reading** finds lines and keeps their masks, with no letter cutting (`Library.capture_read` with a
  `cut_letters=False` path in the pipeline). It is faster: Prepare is timed on one book before and after, and the
  times are recorded.
- **What used the cut letters of a book, and what happens to it:**
  - our reader's pages (`search_book`: "lines with cut letters") now take lines with a mask;
  - the hidden *Cut letters* view: pages prepared without letters show "no cut letters (prepared without
    cutting)", and the book setting *Show Cut letters* also brings back cutting at Prepare;
  - *Book pages* (fixing cuts, `recut.py`) is hidden for a book whose pages have no cut letters;
  - Tesseract's whole lines read the line image, as now (unchanged).
- **Existing books keep their cut letters.** Nothing is deleted. *Prepare again* on a page uses the new way.
- **Datasets are unchanged:** Capture still cuts, since cutting is how training letters are made.
- **Files:** `pipeline.py`, `app/library.py`, `app/linesearch.py`, `app/texts.py`, `app/api.py`,
  `frontend/src/screens/{ReadBook,BookView}.tsx`; tests; help (`our-reader`, `tech-reading`, `workflow`), README.

### C29. Reading models shared between books (optional), 4–5 h

Full-plan decision 4: two books that read with the same choice use one trained model. That saves one training
(about 33 minutes for book 8's size) per extra book. **Today it saves nothing:** book 7 learns from no dataset, and
book 8 from dataset 6.

**The catch:** a reader learns the **book's own checked lines** too, not only its datasets. Proposed (question 5):

- **Share the reader, not the language model.** The language model stays per book, with the book's proofread lines
  and word lists. It is cheap, rebuilt automatically, and never out of date, so the word lists stay on the book
  (lean C23, change 2) and nothing moves.
- **A shared reader learns the checked lines of every book that uses it.** That is better for each of them
  (more corrections), and it follows the fairness rule (a line is a line, with no weighting by book).
- **Two books share a model when** they have the same set of datasets **and** the same reader settings
  (`line_base_epochs`, `line_batch`, the window settings). That is checked when the datasets change in Reading
  setup: if another book's model matches, *"Book X reads with the same datasets: use its reading model (trained
  …), or train one of its own?"*. Leaving a shared model (changing the datasets) gives the book a model of its
  own, untrained.
- **Fold-fair Measure** of a book with a shared model leaves out, for each fold, the tested pages, the same pages
  in the datasets (C24), **and the same pages in the other books of the model** (by `sha256`). Their checked lines
  stay in, because they are other pages.
- **Signature:** `_signature` hashes the checked lines of every book of the model. Checking a line in one book
  marks the shared model *out of date* for both.
- **Screen:** Reading setup → Reading model shows "Shared with: …", with a model name that can be changed. The
  folder stays as it is: `models/<first book's folder>/`.
- **Migration `0020`:** none needed for sharing itself (`book.reading_model_id` can already point at one row).
  Possibly a model name column for the screen.
- **Files:** `app/library.py` (`set_book_datasets`, `model_books`, `left_out`), `app/linesearch.py`
  (`_signature`, `_checked_rows` over the model's books), `app/api.py`, `frontend/src/screens/ReadingSetup.tsx`;
  tests `tests/test_reading_setup.py`, `tests/test_fold_fair.py`; help (`our-reader`, `new-book`), README.
- **Not run while building:** the one training (Retrain when two books share), only when you ask.

### Not built: old API routes as redirects

C20–C24 changed the routes and the screens in the same commits. Only the app calls them, and nothing outside uses
them (Font Maker reads the library database, not the API). Redirects would only add code to keep. **Recommended:
drop this item for good.**

## 3. Questions for you (before C25)

**Answered 2026-10-17:** 1. Automatic, for the existing rows. 2. Each row gets its own copy. 3–6 still open.


1. **C26: how does the move start?** (a) **Automatic** at the first start with the new code, as you decided on
   2026-10-14 (full plan, decision 6): a database backup, then the move job with its notice. (b) **A button** on the
   Books / Datasets folders card, *Move page images into the uploads folder*, which shows the list first.
   *Recommended: (a)*, run first by me on a copy and then on your library only after you say so. After that, new
   rows made with *Use this folder* would also be moved at the next start. Say if those should stay where they are.
2. **C26: the five rows that share `~/Downloads/black and white`** each get their own copy in their own upload
   folder (clones, so no extra disk space on this Mac). OK? (The other choice, one shared folder, breaks the
   "one row, one upload folder" rule that deleting a row relies on.)
3. **C27: copied pages are captured again in the dataset** (cut and grouped with the dataset's settings). The book's
   cut letters are not carried over. OK?
4. **C28: handwritten.** The measurement can only be printed (book 8). Do you want to check some lines of a
   handwritten book first (Line truth), so C28a can be measured on both? Without that, C28b would change printed
   and handwritten Prepare on a printed measurement only. I'd then keep `line_ink = letters` for handwritten books
   until there is a number.
5. **C29: build it now, later, or not at all?** With two books and different datasets it saves nothing today.
   If you build it: "share the reader, not the language model; a shared reader learns every sharing book's checked
   lines". OK?
6. **Old API redirects: drop for good?** (Recommended.)

## 4. Working rule (as in the lean plan)

- One commit per chunk. Each updates this plan ("as built" and what changed), `docs/help/` and the README.
- **No heavy runs while building:** only the changed modules' tests, `fast`, and `npm test` when `frontend/` changed.
  Heavy runs only when you ask, one at a time: C26's dry run and run, C28a's line masks and two Measures, C28b's
  timed Prepare, C29's training.
- **Before C26 touches your library:** a backup of `library.db` (C26 changes no file in place). I tell you where.
- **Stops for your check:** after C26 (the move on your library: page counts, every page opens, Measure inputs the
  same), after C28a (the numbers and line-by-line page decide C28b), and at the end.
- Still open from the lean plan, and best done before C25: the C24 gate Measure on a copy, the backend `full`
  suite, and Stop 3 (lean plan, "Start here next session", steps 2–5).

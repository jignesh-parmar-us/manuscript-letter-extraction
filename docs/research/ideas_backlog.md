# Ideas backlog: the full Phase 3 plan (reference only)

Written as the full Phase 3 plan (`implementation_plan_phase3.md` until 2026-10-28). What was built from it is
`docs/phases/phase3_C19-C24.md` (C19–C24), what came next `docs/phases/phase4_C25-on.md`. Not a to-do list: the
ideas here are picked up only when a phase plan takes them.

Phase 1 (`docs/phases/phase1_C0-C9.md`) cuts, groups and labels letters. Phase 2 (`docs/phases/phase2_C10-C18.md`) reads books. Since C16a one **book** holds two parts, **Training Data** and **Read Book**, and the app mixes the two: "Cut", "Reader", "Dictionary" and "Text" each mean something different depending on the part. **Phase 3 separates them.**

**Status:** a plan, not built. Written 2026-10-14; the questions were answered the same day (section 5) and the plan updated. Next: C19 (needs only your go-ahead).

## 0. The idea in one picture

| Today | After Phase 3 |
|---|---|
| A **book** has Training Data pages and Read Book pages | A **dataset** is a set of pages whose letters are cut, grouped, reviewed and labelled. A **book** is something to read. They are separate things. |
| Read Book points at a folder or a PDF | A book is created with a **type** (printed / handwritten), a **name**, and **uploaded** images or a PDF. Its pages are managed in the app. |
| A book's reader learns from its own Training Data | A book picks **one or more datasets** (and word lists) to learn from |
| Training Data → "Readers" (letter reader) vs. Whole lines (our reader) | Two clearly named things: the **Letter checker** (inside a dataset) and the **Reading model** (for books) |
| Read Book → "Cut pages" / "Cut again" | **Prepare for reading** / **Prepare again** |
| Text → Tesseract / our reader / Cut letters | Text → Tesseract / our reader. Cut letters is hidden. Pages to export can be chosen. |

Words used from here on:

- **Dataset:** what "Training Data of a book" is now. Same screens (Pages & capture, Review groups, Pages, Export dataset), same rules (fairness rule: no weighting by group size; min samples per group is a setting).
- **Book:** only what is read. Pages, preparing, text, dictionary/reading setup, line truth.
- **Letter checker:** today's Training Data → Readers (see C19).
- **Reading model:** the thing a book reads with: the line-search reader and the language model, trained from the chosen datasets and word lists.

## 1. How the app is built today (what this plan must work with)

Checked in the code on 2026-10-14:

- **One `book` table row holds both parts.** `page.part` and `sample.part` say `training` or `read`; the folder of Read Book files is `book.read_dir` / `book.read_pdf`; Read Book data lives in `<book folder>/read/`.
- **The letter reader** (`Reader` table, `app/readers.py`) belongs to the library, is trained on chosen books' reviewed letters, and `book.reader_id` is the active one. It reads *cut letters*: used by Check these, suggestions and Cut letters. It does not read a book's lines.
- **Our reader (line search)** is kept per book (`<book folder>/line-search/`), trained on the book's own reviewed letters and checked lines (`linesearch.py`).
- **The language model** is built per book from its labels, its proofread lines and the word lists whose `books` list contains it (`dictionary.py`; `WordList.books` is a JSON list of book ids).
- **Fold-fair measuring relies on one fact:** every Read Book page is also a Training Data page of the same book, so tested pages' letters are left out by page (`linesearch.measure`).
- **Correction to what I told you earlier (2026-10-14):** I said our reader works on the stored line images and not on the cut letters. That was incomplete. `linesearch._line_ink` builds the line's ink by pasting the line's *cut letters' masks* together. So **Prepare for reading must still cut the letters** (ungrouped) until the line search is changed to use the line image. Hiding Cut letters in Text is safe; removing the cutting is not, yet.

## 2. Decisions this plan makes (change any of them)

1. **One table, a `kind` column** (`dataset` | `book`), not two tables. Samples, groups, pages, lines all key on `book_id` and keep working. The screens show the word the `kind` says. *(Why: the least code to change; a rename of the table can come later.)*
2. **Pages of datasets and books are uploaded** into one **uploads folder**, in a stored order, and managed in the app (add, delete, exclude, reorder). A dataset can still be made from a folder: the folder's images are copied into the uploads folder, so nothing depends on where the originals are.
   - **The uploads folder is an app setting** (in the per-user `settings.json`, key `uploads`; default `<library>/uploads`), changed in the app's settings. Changing it **moves the existing files automatically** (copy, verify by hash, switch the paths); the old folder is left in place and its path is shown once.
   - Layout: `<uploads>/datasets/<dataset folder>/` and `<uploads>/books/<book folder>/`.
   - The rule "the input folder must not be inside the library" ([library.py](src/letter_extractor/app/library.py), `_check_input_dir`) no longer applies to the uploads folder.
3. **The choice of datasets is on a new book tab "Reading setup"**, and the Dictionary (word lists) moves into it as its second section. See section 3. Datasets are **managed there**: add a dataset to the book, remove it, create a new dataset, open one. Deleting a dataset itself is on the Datasets screen only, and says which books use it.
4. **Trained reading models belong to the library and can be reused:** a model = a set of datasets + word lists + settings; two books that choose the same set share one trained model. Not per book.
5. **Existing books are split, not deleted:** each current book becomes a dataset and a book of the same name, linked to each other (the book uses that dataset by default). Back up first, ask before running (data safety rule).
6. **Existing files move into the uploads folder automatically, without asking** (the first start after the update, as part of the migration): the page images of every existing book (Training Data folder, Read Book folder, or the PDF's page images) are **copied** there, each copy checked by its hash against the original, and the database paths updated. This is invisible to you: nothing to click. Three safeguards stay, because they cost you nothing: the library is **backed up first** (the location is written in the app's log and shown once in a notice), a file whose copy does not match is **not switched** (the book keeps working from the original and the notice says so), and **originals are never deleted** by the migration (they are only listed, for you to remove when you like). Your reviewed groups, labels and line truth are not changed by the file move.

## 3. My thoughts on "select the datasets in Dictionary"

Close, but I would not put datasets *in the Dictionary*. The Dictionary is a list of word lists. The datasets decide three things: the letters the line search learns, the labelled text the language model learns, and the checked lines it is measured against. A person looking for "what is this book read with?" would not look under "Dictionary".

So: **Read Book → Reading setup** with three parts on one screen:

1. **Datasets used** (tick one or several; each shows pages, reviewed letters, writing type; a warning when the writing type differs from the book's).
2. **Word lists** (today's Dictionary, unchanged inside; the tab "Dictionary" becomes this part).
3. **Reading model:** what it was trained on, *out of date* when the datasets changed, **Train** / **Retrain**, **Measure**.

The old tab name disappears; the Dictionary help page points to Reading setup.

**Managing datasets there:** *Add dataset* (pick from the library, or *New dataset*), *Remove from this book* (the dataset itself is untouched), *Open* (go to its screens). Adding or removing marks the Reading model *out of date* until Train.

## 4. Chunks

Each chunk is one commit, ends with something to run and check by eye, and updates this plan, `docs/help/` and the README in the same commit. Backend tests for changed code with each; `npm test` when `frontend/` changed.

### C19. Names and small screens (no data change)

The quick wins that need no migration, and ship first:

- **Text:** hide *Cut letters* (the tab and its Convert button). Data is kept; a setting "Show Cut letters" (off) brings it back for experiments.
- **Export pages:** a tick box per page in Text, **Select all / none**, and Download uses the ticked pages (all, if none ticked). Applies to .txt, Word, PDF and picture.
- **Readers → Letter checker.** It trains on reviewed letters to find wrongly grouped letters (Check these) and suggest labels. It does not read books, which is why "Readers" is confusing next to the reader that does. The page text says this in its first line.
- **Cut pages / Cut again → Prepare for reading / Prepare again** (Read Book tab *Upload & capture* → *Prepare*). Statuses say "Prepared", not "Cut". "Cut" and "Capture" stay for datasets only.
- **Files:** `frontend/src/screens/{BookView,ReadBook,TextView,Readers,Capture}.tsx`, `api.ts`, tests, `docs/help/*`, README.

### C20. Datasets and books become separate things (data change)

- Migration `0016`: `book.kind` (default `dataset`). For every existing book that has Read Book pages: create a `book`-kind row with the same name (suffix if taken); move its `part = read` pages, their lines, `whole_line`, `line_truth`, `page_text`, readings and ungrouped samples to the new row; move `read/` and `line-search/` folders; set `book.read_dataset_id` (the linked dataset). Books without Read Book pages stay datasets only.
- **Before running:** backup of the library folder, location told to you. Dry run on a copy in the scratchpad first, with counts before and after (pages, lines, line truth, reviewed groups) that must match.
- **Files move** to the uploads folder as decision 6 says (copy, verify by hash, update paths, keep originals), with the setting `uploads` added to the app settings.
- API: `/api/datasets/...` and `/api/books/...` (old routes kept as redirects for one version).
- **Files:** `app/db.py`, `app/migrations/versions/0016_*.py`, `app/library.py`, `app/api.py`, `app/schemas.py`, tests.

### C21. Two lists, two creators

- **Datasets** screen: list, create (name, writing type, **upload images or a PDF, or pick a folder to copy in**), same as Books today.
- **Books** screen: list, **New book**: type, name, then **upload a PDF or images** (drag and drop, several files). A PDF is turned into page images as now (`import_pdf`).
- **Files:** `frontend/src/screens/Books.tsx` (split into `Datasets.tsx`, `Books.tsx`), `route.ts`, `App.tsx`, `app/api.py` (upload endpoints), `app/library.py`.

### C22. Page manager for a book and a dataset

- The same page manager serves both. Pages tab: thumbnails and a table; **Add pages** (upload more), **Delete**, **Exclude / Include** (an excluded page is skipped by Prepare, Read and export, but kept), **drag to reorder** (or move up / down). Order is stored (`page.number`); `page.excluded` is new.
- Reading and export follow this order. Deleting a page with checked lines (Line truth) or corrections asks first and says what is lost.
- **Files:** `app/db.py` (`page.excluded`), `app/library.py`, `app/api.py`, `frontend/src/screens/ReadBook.tsx` → `BookPages.tsx`, tests. In a dataset, deleting or excluding a page asks first when it has reviewed groups, and says what is lost; excluded pages are skipped by capture, training and export.

### C23. Reading setup and reusable reading models

- New table `reading_model` (name, dataset ids, word list ids, folder, trained-on hash, trained at) and `book.reading_model_id`. Files in `<library>/models/<folder>/` (the line-search reader moves here from the book folder).
- Language model: learns from the labels and proofread lines of the **chosen datasets** and the chosen word lists, not from "the book's own" Training Data.
- **Fairness rule kept:** balanced copies per group, min samples a setting, no weighting by group size or frequency; frequency only in the language model.
- Reading setup screen as in section 3, including adding and removing datasets. **Train** is offered when the choice changed; two books with the same choice use the same trained model.
- **Files:** `app/db.py`, `app/migrations`, `app/linesearch.py` (paths, training sources), `app/dictionary.py` (sources), `app/readers.py` (letter checker unchanged), `app/api.py`, `frontend/src/screens/ReadingSetup.tsx` (replaces `Dictionary.tsx` as the tab), tests.

### C24. Fold-fair measuring without "same book"

- A book's page and a dataset's page are the *same page* when their `sha256` is equal. Measure leaves out, for each fold, the letters, labels and corrections of datasets' pages that match the tested pages. Pages of the book that are in no dataset need nothing left out.
- **Gate (must pass before C24 is done):** on a copy of your library, Measure after the split gives the same numbers as before it, on the same 99 checked lines (fold-fair 7.32% for our reader, Tesseract 3.80%), and a line-by-line page you can check by eye. Both printed and handwritten are tried; I will say if a number exists for only one.
- **Files:** `app/linesearch.py` (`measure`), `app/dictionary.py` (`book_model_without`), tests.

### C25. Later, if wanted

- Make the line search use the stored line image instead of the cut letters' masks, then Prepare stops cutting letters (faster, nothing ungrouped to store). Needs its own measurement first.
- Copy pages of a book into a dataset ("use these pages for training too").

## 5. Decisions (answered 2026-10-14)

1. **Datasets are chosen in a Reading setup tab** (word lists inside it), and datasets can be managed there: add, remove, create, open.
2. **Reading models are shared and reusable.**
3. **Existing books are split** into a linked dataset and book.
4. **Datasets take uploads too.** Existing files are moved (copied and verified) into the uploads folder, whose path is an app-level setting.
5. **Order:** C19 is the first chunk (names, hide Cut letters, export page selection; no data change). Then C20 onward. Each chunk is its own commit, and I stop after each for your check.

6. **Migration is automatic and silent** (decision 6 in section 2), including when the uploads folder is changed in settings.

## 6. Changes from the original plan

None yet.

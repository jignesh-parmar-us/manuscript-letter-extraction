# Cutting only between the page borders

A plan, not built. Page preparation (`prepare.py`, Phase 1 C1) erases border lines and cuts inside the
densest rectangle of ink. On pages with faint, broken borders the border is not erased, the rectangle
grows to take it in, and every line ends (or starts) with a sliver of border cut as a "letter". This
plan finds the borders another way, cuts only between them, and cuts the affected Read Book pages
again, except pages with hand-checked work.

Status: **plan, answered, not built** (2026-10-14).

---

## 1. What happens today

1. `ruled_lines` erases long straight runs of ink: a vertical run must be unbroken for
   `rule_min_frac` (0.15) × page height, about 273 px on a 1825 px page.
2. `text_block` takes the densest rectangle of what is left, plus `block_pad_px` (15).
3. Everything outside the rectangle is dropped. Margin notes (વ૦ સૂ૦, ॥૧૧॥, ક ૧૧) hold little ink and
   always fall outside: they are never cut or read. Tesseract reads only line images from inside.

Borders are never used as limits; they are only erased when they are found.

## 2. What goes wrong

The 1944 book's borders are grey and broken: a thin line next to a thick one. After the black-ink
threshold, a border column has ink in only 7–55% of rows, in pieces of 10–230 px (measured on 18.jpg,
columns 3322–3378). No piece reaches 273 px, so most of the border stays as ink. It is close enough
to the text for the rectangle to take it in.

Measured on Vachnamrut Printed 1944 Training Data, Read Book, 2026-10-14 (rough count: a letter that
starts within 5 px of the inner border, or crosses it):

| | |
|---|---|
| Read Book pages cut | 85 |
| pages with border slivers | 49 |
| lines ending or starting with a sliver | about 530 |
| pages with a sliver on every line | 26 (1, 4–7, 9, 11, 13, 14, 16–18, 24–26, 29, 34, 37, 40, 41, 46, 48, 56, 58, 63, 65) |
| fine | the `Untitled-*` pages: their rectangle sits inside the borders |

Checked by eye: 18.jpg line 3, 5.jpg line 4 (right border), 44.jpg line 2 (left border).
None of the affected pages has been read yet, so no text is wrong so far. Once read, a sliver would
come out as "।" or a stray letter at the end of the line.

Separate, not a border problem: `WhatsApp Image 2026-10-13 at 8.32.43 PM.jpeg` (a photo) takes in the
dark page edge on the right and starts at the top of the photo. Section 7 covers it.

## 3. The fix

### 3a. Find vertical borders from the column profile, not from unbroken runs

A border is a narrow band of columns that:
- has ink in many rows spread over most of the text height (`border_min_cover`, e.g. 0.5 of the rows
  of the text rectangle, counting a row when it has ink anywhere in a band `rule_slant_px` wide);
- is narrow (`border_max_width_px`, e.g. 40 px, for the thin and thick line together);
- is separated from the text by a gap of plain paper (`border_min_gap_px`, e.g. 6 px) in which
  hardly any row has ink.

The coverage test uses a lighter ink mask than the letters do (`border_max_rel_l`, e.g. 0.8 × paper),
so a grey border counts as one line instead of dashes. Text columns fail the narrow-and-gap test: a
column of text has neighbours with ink on both sides.

Only the left and right borders matter for the slivers. Top and bottom borders are already handled,
because the rectangle's rows are cut where text lines stop.

### 3b. Cut only between the inner borders

When a left border or a right border is found, the text rectangle is clipped to the inside of the
inner line (the line next to the text), and all ink outside it is dropped, the border included.
A page without a found border keeps today's rectangle, so pages with no borders, or with borders
that are already erased, do not change.

### 3c. Show it

The ink overlay (`--debug`, `_ink.png`) draws found borders in another colour, so a wrong border
can be seen.

### Printed and handwritten

The same code runs for both. Handwritten pages may have hand-drawn borders (wavy, uneven) or none.
The check in section 5 includes the handwritten book; if a hand-drawn border is missed, the page
keeps today's rectangle. That is no worse than now.

### Settings (new, in `Config`, tuned in `docs/TUNING.md`)

| Setting | Starting value | Meaning |
|---|---|---|
| `border_max_rel_l` | 0.8 | lighter ink mask used only to find borders |
| `border_min_cover` | 0.5 | share of the text rows a border band must cover |
| `border_max_width_px` | 40 | widest band still called a border (thin + thick line) |
| `border_min_gap_px` | 6 | plain paper needed between the border and the text |
| `border_clip` | true | off: today's behaviour |

The numbers are first guesses; they get tuned on the pages in section 5.

## 4. Cutting the pages again

Only **Read Book** pages of Vachnamrut Printed 1944 Training Data (book 6). Training Data pages are
not cut again: they hold reviewed groups and labels. If they have the same slivers, that is a
separate question to ask.

1. **Back up** the library (`sqlite3 .backup`) and the book's `read/` folder to
   `~/Documents/Manuscript Letters backups/<date>-before-border-recut/`, and say where.
2. **Protected pages are never cut again.** Cutting a page deletes its lines, and with them their
   line truth, whole-line readings and edits (`ON DELETE CASCADE`). A page is protected when any of
   its lines has line truth, or an edited or reviewed whole line, or when its page text is proofread
   or edited. The list is worked out when the step runs, not copied from here. Today it is:
   `Untitled-15, 16, 26, 27, 28, 33, 41, 51, 52, 53` and the WhatsApp photos of 8.30.59 PM and
   8.31.19 PM. Only **8.31.19 PM** has slivers (9 of 13 lines); it stays as it is. You can fix it by
   hand or tell me to cut it again (its 3 checked lines would be lost).
3. **Cut again** only the unprotected pages whose cut area changes with the fix: same as
   `Cut again` in Read Book (`Library.recut_page`). Their unedited Tesseract and our-reader readings go
   with the old lines and are made again by Read.
4. **Report**: pages cut again, pages skipped and why, slivers before and after (the count in
   section 2).

## 5. Checking it

- **Slivers**: the count from section 2, before and after, on all 85 Read Book pages, plus a page
  of overlay images (cut area and found borders) to check by eye.
- **No change where none is wanted**: the cut area stays the same on the `Untitled-*` pages and on
  the handwritten book's pages without a border (a small check over every page of books 5 and 6).
- **Reading quality**: in a scratchpad copy of the library, cut the hand-checked pages again with the
  fix and score the readings on line truth, fold-fair, before and after, with the line-by-line page.
  The real hand-checked pages are not touched. Expected: the same or a little better, because those
  pages had no slivers.
- **Tests**: a synthetic page with a broken thin + thick border on each side (`tests/synthetic.py`):
  no letter is cut from the border, the text is unchanged; a page without a border keeps today's
  rectangle; a margin number outside the border is still dropped.

## 6. Files

- `src/letter_extractor/prepare.py`: `vertical_borders`, clipping in `prepare_page`, overlay colour.
- `src/letter_extractor/config.py`: the settings above.
- `tests/test_prepare.py` (or `test_letters.py`), `tests/synthetic.py`: the border page.
- `docs/IMPLEMENTATION_PLAN.md` (C1): record the change; `docs/TUNING.md`: the numbers.
- `docs/help/tech-cutting.html`: how the cut area is found.

## 7. Out of scope (answered 2026-10-14)

Left out of this plan:
1. **Training Data pages** with the same slivers: not counted, not cut again.
2. **WhatsApp 8.31.19 PM**: stays protected and keeps its slivers.
3. **WhatsApp 8.32.43 PM** (photo, dark page edge kept): not handled here.

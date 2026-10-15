# Font Maker: Plan, Phase 2 (F7–F13)

Phase 1 (F0–F6, `FONT_PLAN.md`) builds a working Devanagari font from a book's letter groups. Phase 2 makes it
easier to try, fills its gaps **in the book's own style** instead of from Noto, and makes words join cleanly.

**Status:** F7 done (2026-10-16). Written 2026-10-16; all questions answered the same day (section 10). Next: F8; built when you say so, possibly several chunks in one go.
Same rules as Phase 1 (`FONT_PLAN.md`, section 1): everything in `font-maker/`, the library read-only, light
tests (tiny made-up images, no full-book runs in tests), only the changed module's tests while building.

**Building time:** about **39–47 hours** in total; F7 alone ≈ 7 h (with the downloads).

## 0. Where Phase 1 left off (book 6, measured 2026-10-16)

| | |
|---|---|
| Glyphs | 532 (47 letters, 485 aksharas); 116 made only from system-generated letters (place estimated) |
| Missing | 29 characters: the vowel signs alone (ा ि ी ु ू ृ े ै ो ौ ॉ), marks (ं ँ ः ़), virama ्, ई ऊ ऋ ऑ औ ङ ञ ळ ऽ ॐ, single danda ।, digits ० ३ |
| On book 6's 119 hand-checked lines (5,857 aksharas) | 98.7 % the book's own glyph, 1.2 % hold a missing letter, 0.1 % pieced together. Most frequent gaps: ई र्ण र्त्त वृं व्य पृ छ्युं ह्र त्नी श्रे र्मां |
| Caveat | Those lines are from the same pages the groups were cut from, so 98.7 % flatters the font. New text (another Vachanamrut edition, a letter) has more aksharas the book never printed; they fall back to single letters, and every vowel sign alone is missing. No other book has read or hand-checked text yet, so F7 adds a way to measure on your own texts. |
| Open from F6 | The check by eye in Word on the Mac (the two short-i rules) |

What Phase 2 changes, in one picture:

| Today (Phase 1) | After Phase 2 |
|---|---|
| Try it: a text box and a second, marked copy of the same text (confusing: both look the same when every akshara is the book's) | **One text box with a letters palette** like the reading app's, its keys drawn in the font and coloured by coverage; a one-line check below; **download** the text as image, text, PDF or Word (F7) |
| Coverage judged on sample lines | Coverage measured on fixed **test texts**: book 6's hand-checked lines and texts you add (F7) |
| Words: each akshara's own headline, small steps between them | **One even headline** through a word, strokes of one weight (F8) |
| A vowel sign alone, the virama, ं: a box or Noto | **Cut from the book's aksharas** (का − क = ा), placed on any consonant by GPOS marks (F9) |
| A conjunct without a group (ख्र, व्य): letters with a visible halant | **Half forms, reph and rakar** from the book's conjuncts, so it is put together the way print does (F10) |
| ई ळ । ० ३: box or Noto | **Generate** (। from ॥, ई from इ + a sign …), or **draw / upload** one yourself (F11) |
| One book per font | Several books / datasets (F12, after Phase 3 C19) |
| Devanagari shapes only | Optionally a font for a book printed in **Gujarati** shapes (F13) |

## 1. Decisions taken from Phase 1 (unchanged)

- Devanagari only by default (`"script": "devanagari"`); F13 adds Gujarati as an option, not a change.
- Anything not from the book's own pages is **always marked**: "made by the system" (generated copies),
  "filled" (Noto), and new in Phase 2 "generated" (made by Font Maker in the book's style, F9–F11) and "drawn"
  (by you, F11). The screens use their own colour for each. In the font itself only filled letters keep their
  line under them (setting); generated and drawn letters are marked **on Font Maker's screens only**
  (decided 2026-10-16, section 10 question 4).
- Fairness rule: when a shape is made from many aksharas (a vowel sign from का खा गा …), **each akshara counts
  once**, never by group size or how often it is printed.
- No database tables; Font Maker's files stay in `<library>/fonts/<id>/`.

## 2. F7: The letters palette, one check line and downloads on the Try it tab (≈ 7 h)

**What:** an on-screen **letters palette** like the reading app's (`frontend/src/components/LetterPalette.tsx`,
used by Line truth and Text), so you can write Devanagari without a Devanagari keyboard, and see at a glance
what the font has; one text box instead of two; and downloads of the text in the font.

```
┌ Try it ───────────────────────────────────────────────────────────────────────────┐
│ [श्री स्वामिनारायण…] [वचनामृत…] [भक्त धर्म…] [My test texts ▾]          Size ──●── 48 │
│ ┌────────────────────────────────────────────────────────────────────────────────┐ │
│ │ श्री स्वामिनारायण भगवान|                                     (in the font)       │ │
│ └────────────────────────────────────────────────────────────────────────────────┘ │
│ Letters  [Letters] [Book's aksharas]  [Space] [New line] [⌫ letter] [⌫ akshara]    │
│ Download [Image] [Text] [PDF] [Word]                                              │
│  Vowels      अ आ इ ई▢ उ ऊ▢ ऋ▢ ए ऐ ओ औ▢                                               │
│  Consonants  क ख ग घ ङ▢ च छ ज झ ञ▢ ट ठ ड ढ ण त थ द ध न प फ ब भ म य र ल ळ▢ व श ष स ह     │
│  Conjuncts   क्ष त्र ज्ञ श्र                                                         │
│  Joined      र्◌ ◌्र                                                                │
│  Signs       ◌ा ◌ि ◌ी ◌ु ◌ू ◌ृ ◌े ◌ै ◌ो ◌ौ ◌् ◌ं ◌ः ◌ँ ◌़        (▢ missing, yellow: filled) │
│  Digits      ० १ २ ३ ४ ५ ६ ७ ८ ९        Punctuation । ॥ ऽ ॐ                         │
│ ✓ 11 aksharas, all the book's own.                                                 │
│   (or: 14 aksharas: 12 the book's own · not the book's: किं (filled ं) · ख्र (pieced)) │
└───────────────────────────────────────────────────────────────────────────────────┘
```

Details:

1. **Same keys as the reading app:** vowels, consonants, conjuncts (क्ष त्र ज्ञ श्र), joined letters (reph र्
   before a letter, rakar ्र after it), vowel signs / halant / marks (drawn on a dotted circle ◌), digits,
   punctuation. The lists are **copied** from `LetterPalette.tsx` into `font-maker/frontend/src/letters.ts`
   (the two screens share no code, `FONT_PLAN.md` section 1), with a comment to keep them in step. A small
   screen test checks the copy still has every key of the reading app's lists (it reads that file as text,
   so it needs no React from the other app).
2. **Keys drawn in the font being tried**, so a key shows the book's letter, not a system font's. Each key is
   coloured by coverage: the book's (plain), generated (dotted), filled (yellow), missing (red, ▢).
3. **Devanagari keys only** (decided 2026-10-16: no Gujarati key switch for now; the reading app's switch can
   be copied later if a Gujarati-shaped font, F13, needs it).
4. **The book's aksharas** (second page of the palette, decided 2026-10-16): every akshara glyph of the
   font, grouped by its first consonant (क: का कि की कु कू के कै को कौ कं क्त क्ष …), with a search box (type क्र to
   see क्र क्रि …). One click types the whole akshara instead of क then ि. **A key types the same Unicode
   characters as the single keys would** (कि = U+0915 U+093F, in the usual order), so the text is the same
   either way and works in Word, search and any other font; the page is only a shortcut, and the quickest way
   to see what the book printed.
5. **Writing:** a key inserts at the cursor (as Line truth does); typing with the Mac's own keyboard still
   works. **⌫ letter** removes one character before the cursor, **⌫ akshara** the whole akshara (कि at
   once). Space and New line keys. The last 12 keys used are kept as a row (per viewer, browser storage).
6. **One text box, one check line** (replaces F6's second, marked copy, which looked the same as the box
   whenever every akshara was the book's own): under the box a single line, "✓ 11 aksharas, all the book's
   own", or the count and the aksharas that are not the book's, each in its colour (pieced, generated,
   filled, missing, other) with the reason ("filled ं"). Clicking one selects it in the text box.
7. **Copy** button (the text, to paste anywhere and set the font there).
8. **Download the text** (decided 2026-10-16), each with the newest build:

   | Format | What you get | How |
   |---|---|---|
   | **Image** (.png) | the text as a picture, in the font, white background, at a chosen size (e.g. 2× for print) | the backend shapes the text with HarfBuzz and draws the glyph outlines (the same shaping as the Try it box), antialiased; no font needed to view it |
   | **Text** (.txt) | the plain Devanagari text (UTF-8) | as typed; shows in any font where it is opened |
   | **PDF** (.pdf) | one page per screenful, the text in the font as vector shapes, sharp at any zoom | the same shaping; each glyph written as a PDF path (no new package). The PDF text is not searchable or copyable in Phase 2 (a hidden text layer can come later) |
   | **Word** (.docx) | a Word document with the text in this font, **with the font embedded**, so it shows on a computer without the font | a small .docx written directly (zip of XML, no new package); the font is embedded the way Word does it (obfuscated `.odttf` in `word/fonts/`). Word for Mac shows embedded fonts from version 16.17; if Word ignores it, the document still names the font, which then must be installed |

   The file name is the font's name and the date (`Vachnamrut-1944-2026-10-16.pdf`). Light: one text is drawn
   once per click; no background job. Image and PDF use `uharfbuzz`, which then becomes a runtime package
   (`font-maker/requirements.txt`), not only a test one.
9. **Test texts:** your own texts to measure the font on, kept in the font project (`texts.json`: name,
   text). The dropdown loads one; **Save as test text** stores the current text. Book 6's hand-checked lines
   (`line_truth`, read-only) are always there as "Hand-checked lines of <book>".
10. **Coverage on the test texts** (Build tab, after each build): per text, the share of aksharas that are the
   book's own / pieced / generated / filled / missing, and the 20 most frequent gaps, with the numbers of the
   build before. This is the before/after measure for every Phase 2 chunk.

Files: `frontend/src/LetterPalette.tsx` (Font Maker's copy), `letters.ts`, `TryIt.tsx`; backend `texts.py`
(test texts, the hand-checked lines read-only), `export.py` (image, text, PDF, Word), routes
`GET/PUT/DELETE /api/fonts/{id}/texts`, `GET /api/fonts/{id}/coverage/texts`,
`POST /api/fonts/{id}/export/{png|txt|pdf|docx}`.
Tests: backend 3 (texts stored, coverage of a text against a made-up report; the PNG and PDF of a made-up
font have the shaped glyphs' ink / paths; the .docx opens as a zip with the text and an embedded font that
de-obfuscates to the .ttf); screen 2 (a key inserts at the cursor and ⌫ akshara removes कि at once; the
palette copy has every key of the reading app). The check by eye: open each download on the Mac (Preview,
TextEdit, Word).

**Done (2026-10-16).** As planned, with these details:
- **Palette:** `frontend/src/LetterPalette.tsx` (Font Maker's own), keys from `letters.ts` (a copy of the reading
  app's 80 keys; `letters.test.ts` reads the reading app's file as text and checks every key is here). Keys
  are drawn in the font being tried and coloured (book / pieced / filled / missing, from the build's
  labels and fills). **Book's aksharas:** a row of first letters, then that letter's aksharas; or a search.
  **Used last:** the last 12 keys, per viewer (browser storage). ⌫ akshara uses a copy of the reading app's
  akshara splitting (`letters.ts`, as `ocr/aksharas.py`).
- **One check line** replaces F6's marked copy: "✓ N aksharas, all the book's own", or the count and each
  akshara that is not, once, with its reason ("missing ळ", "filled ं", "pieced") and ×n; a click selects it
  in the box. `tryit.classify` now gives every piece its `start` and a non-book akshara its `detail`.
- **Downloads** (`export.py`, `POST /api/fonts/{id}/export/{png|pdf|docx}`; .txt by the screen), named
  `<font>-<date>.<ext>`:
  - Image: drawn 4× and scaled down; each glyph filled only in its own box (first version filled a whole-page
    mask per glyph: 12.7 s for 4 lines of book 6; now 1.4 s).
  - PDF: A4, 18 pt, lines wrapped at spaces; **each glyph stored once as a form and placed where used** (first
    version wrote every outline again: 6 s and 2.8 MB for 40 lines; now 1 s and 592 KB). Text not searchable.
  - Word: a hand-written .docx (8 parts), the font in `word/fonts/font1.odttf`, scrambled with the key in
    `fontTable.xml`; every line a paragraph in the font (also as the complex-script font, `w:cs`). Not yet
    opened in Word: part of the open Word check.
- **Test texts** (`texts.py`, `texts.json`): yours (save, delete) and "Hand-checked lines of <book>" (all
  `line_truth` lines of the font's books, read-only). Each build now also keeps its report next to its .ttf
  (`<file>.ttf.report.json`), so the Build tab's **Test texts** table shows the newest build and the one
  before: aksharas, the book's own / pieced / filled / missing, the 20 most frequent gaps.
- `uharfbuzz` is now a normal requirement (image and PDF), not only for tests.
- Help page: a section "Try it: write and download".
- Checked on book 6 (scratchpad build): 40 hand-checked lines to PDF (2 pages) and 4 to an image, in the
  book's letters, as by eye.
- Tests: backend 3 (test texts with the build before; image ink, PDF forms placed, .docx with the text and the
  font that unscrambles to the .ttf; check-line positions and reasons), the whole run ≈ 2.7 s; screen 4 (the
  palette copy has every key of the reading app; akshara splitting and ⌫ akshara; the check line; a key types
  at the cursor).

## 3. F8: One even headline (≈ 4 h)

**Why:** each akshara glyph is cut and averaged on its own, so its headline (शिरोरेखा) sits a pixel or two
higher or lower and is a little thicker or thinner than its neighbour's. In a word the line then steps.

**How:**
1. Measure the headline in every glyph image: the band of rows near the top that is ink across most of the
   width (as the reading app finds headlines, `app/headlines.py`, but on the glyph image).
2. The font's headline: the median top and median thickness over the book's glyphs (each glyph once).
3. Redraw each glyph's band at the font's top and thickness, as a straight bar from the glyph's left to right
   edge (keeping the parts that rise above it: े ै ं, the top of ई), and close any gap at the ends, so the
   bars of neighbours touch (F3 measured a letter gap of 0 for book 6).
4. Only the headline is evened (decided 2026-10-16: no stroke-weight evening).
5. Kept as a setting per font (`clean_headline`), on by default for printed books; the glyph dialog shows
   before / after; any glyph can opt out (some letters have no headline: ध, भ partly, थ).

Tests: a made-up glyph with its bar 2 px off moves to the font's line; a glyph without a bar is left alone.
Judged by eye on the Try it tab (words of the test texts) and on the "On the line" view.

## 4. F9: Vowel signs, marks and the virama in the book's style (≈ 9 h)

**Why:** the most common gap. A vowel sign alone (ा ि ी ु ू ृ े ै ो ौ), the marks (ं ँ ः ़) and the virama are
never cut alone in a printed book, so every akshara the book did not print falls back to a box or Noto.

**How (cut from the book's aksharas):**
1. For a sign S, find every pair the font has: a consonant glyph C and the akshara glyph C+S (क / का, ख / खा …).
2. Line the two up: same baseline (F3), and the best shift of C inside C+S (the shift with the most overlap).
3. **The sign is C+S minus C** (C grown by 1–2 px first, so its edge does not stay behind). Keep the largest
   piece in the expected place (above the headline for े ै ं ँ, right of the consonant for ा ी ो ौ, left for ि,
   below the baseline for ु ू ृ ्).
4. Average the pieces over all pairs, each pair once (fairness rule), as F2 averages copies; the copies'
   agreement shows how reliable the sign is. Fewer than 3 pairs: mark it "few examples".
5. **Where it sits:** from the same pairs, where S sits against C: for spacing signs (ा ी ो ौ, ि) its offset
   from C's right (or left) edge; for marks above / below, its offset from C's top-right end of the headline /
   its foot.
6. **Into the font:** spacing signs (ा ी ो ौ) as glyphs with their own width; ि with its stem; marks above and
   below (े ै ं ँ ु ू ृ ्) as **zero-width marks with anchors** (GPOS `abvm` / `blwm` mark-to-base, GDEF mark
   class). Every consonant glyph gets a base anchor (top-right of the headline, foot of the stem: measured in
   F3/F8). So ं sits on any consonant without an akshara glyph of its own (किं, गुरुं).
7. Marked **generated** on Font Maker's screens (its own colour), not in the font (decided 2026-10-16).
   Filled from Noto stays possible per sign; generated wins when both exist and you choose it.

Screen: Build tab, Missing list: **Generate** (enabled now) per sign and "Generate all"; the glyph dialog of a
generated sign shows its pieces from each pair and the average.
Tests: made-up "consonant" and "consonant + bar on the right" images give back the bar; a mark gets its
anchor; HarfBuzz puts ं over a made-up consonant without an akshara glyph at the anchor.
Measure: coverage on the test texts (F7) before / after; by eye on the Try it tab.

## 5. F10: Half forms, reph and rakar: conjuncts the book did not print (≈ 9 h)

**Why:** a conjunct without a group (ख्र, व्य, र्ण, ह्र — the most frequent gaps on book 6's lines after ई) is
shown as letters with a halant. Print joins them: a half form (ख्), a reph (र् as a hook above), a rakar (्र
as a stroke below).

**How:**
1. **Half forms** from the book's conjunct aksharas: क्त − त (aligned on the right) = half क; averaged over
   every conjunct with that first letter (each once). Book 6 has e.g. क्त क्ष त्य द्ध न्य प्र ष्ट स्त्र ….
2. **Reph** from र्x aksharas (book 6: र्य र्म र्श र्त र्व र्थ र्ष र्ख र्ध्व र्ल … , 30 groups): र्x − x = the
   hook; its place over the end of x's headline (anchor, as F9).
3. **Rakar** from x्र aksharas (प्र ग्र द्र क्र ब्र भ्र त्र श्र …): x्र − x = the stroke below; for ट ड the
   bottom churn.
4. Into the font with the features text engines expect for Devanagari: `half` (क ् → k.half), `rphf` (र ् →
   reph), `blwf` / `rkrf` (् र → rakar), plus `abvs` / `blws` placement by anchors. The book's own conjunct
   glyphs (F5's ligatures) still win where they exist (they are tried first).
5. This changes how engines reorder ि and the reph, so F5's rule orders are checked again with HarfBuzz,
   and once more by eye in Word (Phase 1's open check).

Marked generated, as F9. Tests: made-up conjunct − second letter = the half form; HarfBuzz shapes a conjunct
without its own glyph as half form + full letter; र्य keeps its own glyph. Measure: coverage on the test
texts, the "pieced" share should fall.

## 6. F11: Missing letters: generate, draw or upload (≈ 5 h)

1. **Generate** what can be made from the book's own parts:
   - । from ॥ (one of its two strokes); ० from the bowl of ३ or ६ if they exist, else not generated;
   - ई from इ + the hook of ी (F9), ऊ from उ + ू (F9), औ from अ + ौ, ऑ from अ + ॉ, ॐ not generated.
   Each marked generated, with the parts it was made from shown in its dialog.
2. **Draw:** a small drawing pad in the glyph dialog (pen, eraser, the font's headline and baseline as
   guides, the book's neighbouring letters shown faintly for size). The drawing is a glyph image like any
   other and is traced by F4. Marked **drawn**.
3. **Upload:** a PNG of a letter (a scan from another page or book), cut to its ink, scaled to the font's
   letters, marked **drawn**.
4. Choices stay in the font project (`font.json`: `generated`, `drawn` with their files in `glyphs/`), never
   in the library.

Tests: । from a made-up ॥; an uploaded image becomes a glyph at the font's height.

## 7. F12: A font from several books or datasets (≈ 4 h; after Phase 3 C19)

- `sources` is already a list in `font.json`. After Phase 3 a source is a **dataset**; the New font screen and
  Settings pick one or more.
- One glyph per label over all sources: the group with the most copies (as F5 does for duplicates), or one
  source first, the others only for labels it lacks (a setting).
- Metrics (F3) per source, scaled to one line height, so letters from two scans of different size match.
- Waits for `docs/implementation_plan_phase3_lean.md` C19 (datasets).

## 8. F13: A font for a book printed in Gujarati shapes (≈ 3 h)

- Setting `"script": "gujarati"` (decided in Phase 1: Devanagari only *for book 6*): the groups are reached
  from `label_guj`, scripts `gjr2` / `gujr`, missing list and fill from Noto Serif Gujarati (OFL), the letter
  writer's keys in Gujarati, the help page's Gujarati keyboard.
- Same steps F2–F11, because the labels are stored in Devanagari and converted; Gujarati has no headline, so
  F8's headline cleaning is off for such a font.

## 9. Later still (not in Phase 2)

- Kerning between letter pairs (book 6's letters touch through the headline; little to gain for print).
- Fonts from handwritten books (one shape per group fits print better than handwriting; a handwritten font
  would need several shapes per letter and `calt` alternates).
- Synthetic training lines for the reader (set aside, brainstorm of 2026-10-15).

## 10. Order and questions

Suggested order: **F7** (small, makes every later step easy to judge) → **F8** → **F9** → **F10** → **F11**;
F12 after Phase 3 C19; F13 when a Gujarati-printed book needs a font.

Answers (2026-10-16):

1. **Letter writer:** the reading app's **letters palette** (F7). Also wanted: **downloading the text as image,
   text, PDF and Word** (added to F7, point 8).
2. **Keys:** Devanagari only; no Gujarati keys for now.
3. **The book's aksharas as keys:** yes, as a second page of the palette (485 for book 6), grouped by
   consonant. Each key types the same Unicode characters as the single keys (कि = क + ि), so the text is the
   same either way (F7 point 4).
4. **Generated letters:** marked on Font Maker's screens only, not in the font.
5. **F8:** only the headline.
6. **Order:** F7 → F8 → F9 → F10 → F11 is fine; you may ask for several chunks in one go.

Also from the same day: the Try it tab's **two areas** (the text box and, below it, a marked copy) looked the
same whenever every akshara was the book's own. F7 point 6 replaces the copy with one check line.

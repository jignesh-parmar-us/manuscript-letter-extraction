# Font Maker: Plan, Phase 1 (F0–F6)

Make an installable font from a book's letter groups, so that typing क in Word, Pages or a browser
draws the book's own क. **Devanagari only** (decided 2026-10-15, see section 7, decision 5). Phase 1 builds a small separate app (Font Maker) in this project. In it you pick a
book, build its font, type into a test box to see the result, and download the font.

**Status:** F0, F1 and F2 done (2026-10-15). Plan written 2026-10-15; decisions answered the same day (section 7). Next: F3.
First book: 6, *Vachnamrut Printed 1944 Training Data*.

**Building time:** about **18–22 hours**.

## 0. The idea in one picture

| Today | After Phase 1 |
|---|---|
| A book's letters are cut, grouped and labelled (541 labelled groups, 9,455 samples for book 6) | Font Maker reads those groups and builds `<name>.ttf` from them |
| The groups are only used for reading | The font can be installed on the Mac and used in Word, Pages, TextEdit and browsers, for **Devanagari** typing |
| — | A test page: type, see it in the book's letters, see which aksharas are missing or filled from a normal font |

Words used here:

- **Font project:** one font being built: its name, source book(s), its choices (group statuses, left-out
  groups, chosen copies, filled characters) and its builds. Stored as files in the library folder. It adds
  nothing to `library.db`.
- **Glyph:** one shape in the font.
- **Base glyph:** the shape for one Unicode character (क, अ, १, ।).
- **Akshara glyph (ligature):** the shape for a whole group such as का, कि, क्ष or स्त्री. The font tells the
  text engine to swap "क + ा" for this shape.
- **Missing:** a character the book's groups give no shape for.
- **Filled:** a missing character whose shape is taken from a normal Devanagari font (Noto, see
  F5). It is always marked as filled.
- **Coverage:** which typed aksharas the font draws in the book's letters, which are filled, and which are
  missing.

## 1. Kept apart from the reading app

The aim is that Font Maker does not mix with the reading app and does not slow down its tests. Everything
that belongs to it lives in **one top-level folder, `font-maker/`**: code, screen, tests, docs and its own
package files. It could later move to its own repository unchanged.

```
font-maker/
  README.md               what it is, how to start and test it
  pyproject.toml          package "font-maker" (Python name font_maker); needs letter-extractor
  requirements.txt        fontTools, potracer (pure Python, no binary); tests also uharfbuzz, httpx
  package.json            shortcuts: npm --prefix font-maker run build / test / typecheck
  src/font_maker/         __main__.py, main.py, api.py, store.py, glyphs.py, metrics.py, trace.py, build.py
    data/                 Noto Serif Devanagari + licence (fill font)
    static/               the built screen
  frontend/               Vite + React + TypeScript, its own node_modules
  tests/                  backend tests (seconds)
  docs/FONT_PLAN.md       this plan
  docs/help/font.html     the help page
```

| | Reading app (today) | Font Maker (new) |
|---|---|---|
| Start | `PYTHONPATH=src .venv/bin/python -m letter_extractor.app` (port 8675) | `PYTHONPATH=src:font-maker/src .venv/bin/python -m font_maker --browser --port 8676` |
| Backend tests | `discover -s tests` (≈ 12 min) | `PYTHONPATH=src:font-maker/src .venv/bin/python -m unittest discover -s font-maker/tests` (seconds) |
| Screen | `npm run build`, `npm test` (≈ 1.5 min) | `npm --prefix font-maker run build`, `npm --prefix font-maker test` |
| Python packages | `requirements.txt` | `font-maker/requirements.txt`, same `.venv` |
| Data | reads and writes `library.db` | **reads `library.db` read-only**, writes only into `<library>/fonts/` |

Neither app's tests run the other's: the reading app's `discover -s tests` and `npm test` do not look inside
`font-maker/`, and Font Maker's commands only look inside it.

Rules:

- **One-way imports.** `font_maker` may import `letter_extractor.app.db` (the tables),
  `letter_extractor.ocr.aksharas` (akshara splitting). Nothing in `letter_extractor` or `tests/` imports `font_maker` or `fontTools`. A small test in
  `font-maker/tests/` checks this.
- **Read-only database.** Font Maker opens `library.db` as `file:…?mode=ro` with its own engine. It does
  **not** use `Library()`, because that runs migrations. If the database's `alembic_version` is not the one
  Font Maker knows, it says so and stops instead of guessing. Both apps can run at the same time (WAL).
- **Same library folder.** It uses the folder the reading app remembers (its settings file), or `--library`.
- **Looks the same.** `font-maker/frontend/` imports `../../frontend/src/styles.css`, so there is one
  stylesheet. Components are not shared in Phase 1.
- **Light on the CPU.** Font Maker is a lightweight project. Tests are few and small: made-up images of a
  few pixels, a temporary library with a handful of rows, no real book, and no full font build of a whole
  book. Only the tests of the changed module are run while building; the whole `font-maker/tests` suite
  should take seconds. The screen has a few smoke tests, not one per button.
- The root `CLAUDE.md` and `README.md` get a short pointer to `font-maker/README.md`. Nothing else outside
  `font-maker/` changes.

## 2. Where things are stored

```
<library>/fonts/<font folder>/          folder named by a fixed id (f0001, …), so renaming never moves it
  font.json          name, source books, group statuses, left-out groups, chosen copies, filled characters,
                     settings, build number
  glyphs/glyphs.json  computed, per glyph: copies used, average or one copy, how well the copies agree,
                     and a fingerprint of what it was made from (F2)
  glyphs/<code>-<fingerprint>.png  the cleaned, enlarged image of each glyph (what gets traced)
  builds/<name>-<n>.ttf   every build is kept; the newest is shown and downloaded
  report.json        the newest build's coverage: glyphs, filled and missing characters, groups left out and why
```

`font.json` keeps **`sources: [book ids]`** as a list from the start. Phase 1 shows a single book choice.
After Phase 3 a source becomes a dataset (see `docs/implementation_plan_phase3_lean.md`), and a font can draw
from several.

**No database tables (decided 2026-10-15).** Font Maker's data stays in these files, not in new tables:
`library.db` stays read-only for Font Maker, only the reading app changes its tables, and deleting a font
stays "delete its folder". Your choices are small, and everything else can be recomputed from the library.
A link table in `library.db` (e.g. "this group is used in font X") can come with Phase 3 if wanted.

**Choices are kept even when groups change.** The reading app can re-cut, merge or delete groups after a
choice was made. Every choice is therefore saved with its group id **and** the label at that time, e.g.
`{"group": 812, "label": "कि", "sample": 40211}`. When a font opens, the choices are checked against the
library in one query. If the group or the sample is gone, or the sample has moved to another group, that
glyph goes back to the system pick and is marked **"your pick was lost"**. A choice is never dropped silently.

**Deleting a font project** removes only its folder in `fonts/`, after a confirmation that names the font and
its number of builds. Groups, samples and labels are never touched. A font already installed on the Mac
stays installed. The help page says how to remove it there (Font Book).

## 3. How a glyph is made (F2–F4)

1. **Which groups (by status):** the font project's setting **Group statuses**. The default is **labelled**:
   groups you reviewed and labelled (book 6: 541, plus the danda group and 8 digit groups). As an option,
   **auto** groups that already have a (suggested) label can be added. Their glyphs are marked "not reviewed"
   in the grid. Groups with status `reviewed` have no label, so they cannot become a glyph. The screen shows
   their count with that reason. A label of more than one akshara (cut errors such as खाखा, रव्य, रहे, रेर,
   सरिये, भक्त) is left out automatically and listed in the report.
2. **Which copies:** the group's samples (not deleted), sorted by `distance` (closest to the group's centre
   first). The best N are used (setting `copies`, default 8). This is about picking clean copies, not
   weighting; every group gives exactly one glyph.
3. **Ink only:** each copy's `_mask.png` (book 6 has masks) cuts the ink away from the paper.
4. **System pick:** the best copies are aligned on their ink (shift only), scaled ×4, averaged and
   thresholded. Averaging smooths out print speckle and scanning edges, which a single 66-px cut cannot do.
   When the copies disagree too much (low overlap after alignment, e.g. a mixed group), the system uses the
   single best copy instead of the average. The grid shows which one it used ("average of 8" / "copy").
5. **Your pick:** for any glyph you can choose **one copy** from all its samples, go back to the
   **system pick**, or **leave the group out**. Stored in `font.json`. **This never changes the group, its
   samples or its labels.**
6. **Height on the line:** each sample's place on its line (`sample.y/h` against `line.y/h`) gives where the
   glyph sits. One baseline is measured per line, from the bottom edge of letters with no below-the-line
   part (e.g. क, म, न). The glyph's offset is the median over its copies. One scale is used for the whole
   font, from the median line height.
7. **Width and spacing:** advance width = median ink width + side gap. The side gap is measured from the gaps
   between neighbouring samples on the same line (median). There is no kerning in Phase 1.
8. **Tracing:** the chosen image becomes curves with potrace (`potracer`), giving TrueType outlines through
   `fontTools`.

The images are saved in `glyphs/`, so every glyph can be checked by eye.

## 4. How the font maps Unicode (F5)

- **Devanagari only.** Each group gives one glyph, reached from its Devanagari label (`label_dev`, the
  canonical label). Typing क shows the book's shape; typing Gujarati (ક) does **not** use this font (the
  program shows its normal Gujarati font). Reason: book 6 is printed in Devanagari letter shapes (with the
  headline), so mapping them to Gujarati characters would show Devanagari shapes for Gujarati text.
  Script tags `dev2`/`deva`. `font.json` keeps `"script": "devanagari"`, so a book written in Gujarati shapes
  can later get `"gujarati"` (section 6).
- **Single-character groups** (क, अ, १, …) → base glyphs in the character map. The danda (।, ॥) too.
- **Multi-character groups** (का, कि, क्ष, र्य, स्त्री, …) → akshara glyphs, with a GSUB ligature rule
  `क ा → ka_aa`.
- **Short i (ि):** text engines move it in front of the consonant *before* the rules run. The rule for कि
  must therefore match `ि क`, and for क्ति it must match `ि क ् त`. Phase 1 builds no half forms or reph
  forms (`half`, `rphf`, `blwf`). That keeps the other aksharas in typed order, so their rules match the
  characters as typed.
- **Missing characters** (book 6: a vowel sign alone, the virama, ळ, ई, ऊ, ऋ, ०, ३, and rarer ones such as
  ङ, ञ, ॠ, ऽ, ॐ): shown as **missing** by default. In the
  font they are a clearly marked box. The Glyphs screen and the test page list them. Each missing character
  has two buttons:
  - **Fill from normal font** (Phase 1): copies the shape from Noto Serif Devanagari,
    scaled to this font's height. The result is marked **filled** in `font.json`, in the report and on every
    screen (its own colour), and it can be taken out again.
  - **Generate** (shown, disabled, "next phase"): later it will make the shape in the book's style (cut a vowel
    sign out of the aksharas, or generate it).
- **Filled stays visible outside the app too:** setting **Mark filled characters in the font** (on by
  default) draws a thin line under each filled glyph. The mark therefore shows in Word as well. It can be
  turned off for a clean font.
- **Aksharas with no group of their own** (e.g. ખ્ર) are put together from the base glyphs in typed order.
  With no half forms in Phase 1 this shows the virama (ખ્ ર). The test page marks such aksharas **pieced
  together**.
- Every build gets a new version number in the font (`<n>`). macOS and Word keep old copies of a font with
  the same version, so a rebuilt font could otherwise show the old shapes.
- Format: **TrueType (.ttf)**. Word can embed it into a .docx (Word → Preferences → Save → Embed fonts).
- **Name:** the font project's name (default: the book's name) is the font family name. Renaming takes effect
  at the next build.

**Checking the rules without Word.** `font-maker/tests/` shapes test strings with HarfBuzz (`uharfbuzz`, tests only),
the same engine Chrome uses. This checks that कि, क्ष, र्य, क्ति etc. come out as the expected akshara glyphs.
Word and Pages on the Mac use their own engines, so F6 includes one check by eye in Word.

**Fill font:** Noto Serif Devanagari is kept in `font_maker/data/` with its licence (SIL
Open Font License). The OFL allows copying their shapes into another font. The result is under the OFL too,
and must not be called "Noto". Phase 1 only copies outlines of single characters, not Noto's rules.

## 5. Chunks

### F0: Skeleton (≈ 2 h)
- The `font-maker/` folder as in section 1: `pyproject.toml`, `requirements.txt`, `package.json`, `README.md`.
- `src/font_maker/`: `__main__.py`, `main.py` (start, like `letter_extractor/app/main.py`: session token,
  browser or window, default port 8676), `api.py` (FastAPI), `store.py` (read-only database + `fonts/`).
- `frontend/` (Vite + React + TypeScript), built into `src/font_maker/static/`.
- `tests/` with the import-separation test and the read-only check.
- A short pointer in the root `CLAUDE.md` and `README.md`.

**Done (2026-10-15).** As planned, with these differences:
- `requirements.txt` adds nothing yet (it only includes the main one): fontTools and potracer come with F4/F5,
  uharfbuzz with the F5 tests.
- The screen's packages are pinned to the exact versions of the reading app's screen, and its
  `package-lock.json` started as a copy of that one. Plain `^` ranges made npm fail on vitest's optional
  browser plugins.
- The built screen (`src/font_maker/static/`) and `node_modules/` are not committed (`font-maker/.gitignore`).
- The library is opened through Python's `sqlite3` with a `file:` address and `mode=ro`, so a library path
  with spaces works.
- Tests: 4 backend tests (0.4 s), 1 screen smoke test.

### F1: Main page: books and font projects (≈ 2.5 h)
- `GET /api/sources`: the books with writing type and group counts per status (and how many can become glyphs).
- Main page: the font projects (name, source book, glyphs, last build) and **New font**: pick a book, name
  prefilled with the book's name and editable, group statuses (default: labelled).
- Font project: **Rename** at any time (the folder keeps its id). **Delete** asks for confirmation (section 2).
- API: `GET/POST /api/fonts`, `GET/PATCH/DELETE /api/fonts/{id}`.
- Tests: create / rename / delete only touch `fonts/`. The library database is unchanged (checksum).

**Done (2026-10-15).** As planned, with these details:
- `font_maker/projects.py` keeps the font projects. `font.json` already holds the later choices, still
  empty: `left_out`, `picks`, `filled`, and `settings` with `copies: 8, mark_filled: true`. Font names are
  unique (case does not matter), because two installed fonts with the same name would clash in Word. Every
  check runs before the folder is made, so a refused "New font" leaves nothing behind.
- `store.sources()` counts the groups per status and the **usable** ones (a label of exactly one akshara,
  checked with `ocr.aksharas.split_aksharas`). Book 6 on 2026-10-15: 550 labelled groups, 544 usable;
  172 auto groups, 11 of them with a label.
- Screen: `#/` Fonts (list with Delete, and New font), `#/fonts/<id>` one font (Rename, Groups to use,
  Delete). Delete asks first and says the book's groups are not changed. The confirm dialog is a copy of
  the reading app's, because the two screens share no code.
- Tests: 2 backend tests (sources; create / refuse / rename / delete, database checksum unchanged) and
  2 screen smoke tests (name prefilled from the book; Delete asks first).

### F2: Glyph images (≈ 3.5 h)
- `font_maker/glyphs.py`: steps 1–5 of section 3. Results saved in `glyphs/`. Pure numpy/OpenCV.
- Screen **Glyphs**: a grid of every glyph (Devanagari label, image, "average of N" / "copy" / "your
  pick", "not reviewed" for auto groups). Clicking one shows its copies, where you pick one, go back to the
  system pick, or leave the group out. Filters: left out, not reviewed, missing, filled.
- **Kept fast: no large file is read or written per click.**
  - Sizes for book 6: `font.json` with every group picked is about 35 KB; `glyphs.json` about 110 KB. Nothing
    grows with the number of samples.
  - The backend loads `glyphs.json` once when a font opens and keeps it in memory. A click (pick a copy, go
    back to the system pick, leave out) remakes **only that glyph** (≈ 8 small images). It rewrites only the
    small `font.json` (well under 5 ms). The screen gets back only that glyph, not the whole list.
  - `glyphs.json` is written once after a batch of work, and after a single-glyph change. It is never
    re-read on a click.
  - The fingerprint is made from ids, labels and settings, without opening any image. Opening a font
    therefore recomputes only the glyphs whose group changed. The first time a font is made, all ≈ 550
    glyphs are computed in the background with progress (≈ 4,400 small mask images, one pass); after that,
    work is incremental.
  - Glyph image files have the fingerprint in their name, so the browser caches them, and a changed glyph
    gets a new address. The grid loads images lazily (`loading="lazy"`).
  - The lost-pick check is one query for the font's group and sample ids. No images are read.
- Tests (light, no timing checks): averaging and alignment on 3 made-up 10×10 images; the fallback to one
  copy when copies disagree; a pick is stored with group and label, and a deleted sample turns it into
  "your pick was lost"; a second open with nothing changed recomputes **no** glyph (counted, not timed); a pick
  remakes exactly one glyph; the library database unchanged.

**Done (2026-10-15).** As planned, with these differences:
- **How much copies agree** is the median overlap (IoU) of **every pair** of aligned copies, not the overlap of
  each copy with the average. With only two copies the average holds both shapes, so that comparison always
  looked good (the test caught a square and a bar being averaged). Below `min_agree` (0.6, in the font's
  settings) the single best copy is used.
- Choices: `system`, `copy` (one copy), `left_out`, `keep` (use in the font again). `picks` and `left_out` in
  `font.json` are keyed by group id; each entry keeps the group id and the label. Choosing again on a glyph
  whose pick was lost forgets that pick (unless the choice is a new copy). The "lost" list has a **Forget**
  button.
- Opening the Glyphs tab runs the check in the background (`POST …/glyphs/check`); the screen asks for
  progress once a second only while it runs. When nothing changed, no file is written.
- Filters in Phase 1 F2: all, your picks, copies disagree, left out, not reviewed, your pick was lost.
  *Missing* and *filled* come with F5, where those characters are found.
- Groups without any copy are skipped (book 6: 532 of the 544 usable groups have copies).
- Check on book 6, read-only, written only to the scratchpad: 40 glyphs in 0.28 s (all 532 ≈ 4 s, once);
  28 averaged, 12 one copy. The shapes are clean. Book 6 is printed in Devanagari letter shapes (with the
  headline), which led to decision 5 (Devanagari only). The Glyphs grid shows the Devanagari label first, the
  Gujarati one after it (muted).
- Tests: 3 backend tests (images; counted remaking, a pick, a lost pick; the API with files), 1 screen smoke
  test. The whole `font-maker/tests` run takes ≈ 1 s.

### F3: Metrics (≈ 2 h)
- `font_maker/metrics.py`: baseline, scale, vertical offset and advance width (section 3, steps 6–7).
- Tests: made-up lines with known baselines give the expected offsets.

### F4: Tracing (≈ 2 h)
- `font_maker/trace.py`: image → curves (potrace), in font units, with holes the right way round (ઠ, ઢ, ૦).
- Tests: a ring traces to an outer and an inner curve. A filled square has the expected area.

### F5: Build the font, missing and filled (≈ 4 h)
- `font_maker/build.py`: base glyphs, akshara glyphs, GSUB ligature rules for Devanagari (short-i order), names,
  version number, `.notdef` and missing boxes, filled glyphs from Noto with their mark. Writes
  `builds/<name>-<n>.ttf` and `report.json`.
- **Build font** button: runs in the background with progress (book 6: about 560 glyphs). It shows the
  coverage: glyphs made, groups left out (and why), filled characters, missing characters.
- Missing list with **Fill from normal font** (per character and "fill all"), **Remove fill**, and
  **Generate** (disabled, "next phase").
- Tests: HarfBuzz shaping of का, कि, क्ति, क्ष, र्य, १२; Gujarati text does not use the font's glyphs; a
  missing character gives the missing box; a filled
  one gives the Noto shape with its mark, and without the mark when the setting is off.

### F6: Test page and download (≈ 2 h)
- Screen **Try it**: a text box. The newest build is loaded with `@font-face` from
  `/files/fonts/{id}/builds/<file>`, with the build number in the address so the browser does not keep an old
  copy. It has a size slider and a few sample sentences in Devanagari.
- Below the box, every akshara the font cannot draw fully in the book's letters is marked in its own colour:
  **missing**, **filled**, or **pieced together**, with a list. `POST /api/fonts/{id}/coverage` splits the
  text with `ocr.aksharas.split_aksharas` and checks it against the build's report.
- **Download .ttf** and a short help page `font-maker/docs/help/font.html` (served at `/help/font.html`): install the font (double-click → Install),
  update it after a rebuild, remove it (Font Book), use it in Word and Pages, embed it in a .docx, and what
  the underline on filled characters means.
- One check by eye in Word on this Mac (Devanagari), with a screenshot in the plan.

## 6. Left for later (Phase 2+)

- **Generate** for missing characters: vowel signs, the virama and half-letters cut out of the aksharas, or
  shapes generated in the book's style. Then aksharas without their own group can be put together properly
  (half forms, reph, vowel-sign placement over every consonant).
- Hand-drawing or uploading missing letters.
- Kerning and smoother outlines.
- A font from several books / datasets.
- **A Gujarati font** from a book written in Gujarati letter shapes: the setting `"script": "gujarati"` maps the
  groups to Gujarati characters (`label_guj`, tags `gjr2`/`gujr`, fill from Noto Serif Gujarati). Not needed for
  book 6.
- Synthetic training lines for the reader (set aside; see the brainstorm of 2026-10-15).
- Fonts from handwritten books. They work the same way, but one shape per group fits print far better than
  handwriting.

## 7. Decisions (answered 2026-10-15)

1. **Name:** defaults to the book's name. It can be edited when creating the font project and afterwards.
   A font project can be deleted after a confirmation.
2. **Groups:** reviewed groups (status `labelled`: reviewed with a label) by default. The project's group
   status setting can add `auto` groups with a label. `reviewed` groups without a label cannot be used.
3. **Missing characters:** shown as missing. Each has **Fill from normal font** (Phase 1, Noto), always
   marked as filled (in the app, and by default with an underline in the font itself), and **Generate**
   (next phase).
4. **Glyph choice:** the system picks the best (average of the best copies, or the single best copy), and you
   can pick any copy instead.
5. **Scripts:** ~~both Gujarati and Devanagari~~ **Devanagari only** (changed 2026-10-15, after F2 showed that
   book 6 is printed in Devanagari letter shapes). Gujarati typing is not mapped to these shapes.
6. **Port:** 8676.

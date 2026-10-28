# Custom fonts in Read Book → Text (T1–T4)

**Status:** T1–T4 built (2026-10-17): the font store, the font tabs and +, downloads in the font, help and README.

Show and download a book's text in a font of your choice. Next to the script tabs ગુજરાતી / देवनागरी, a **+**
adds a font: upload a `.ttf` / `.otf` / `.ttc`, or pick one built in Font Maker. Each added font is a tab; clicking it
shows the text in that font, and the downloads (PDF, picture, Word) use it.

Display and export only: reading, groups, labels and line truth are not touched. Works the same for printed
and handwritten books (only the text is used).

## Decisions (2026-10-17)

| Question | Decision |
|---|---|
| Where fonts live | Across the library: `<library>/display_fonts/`, every book sees the same tabs |
| Word | Use the font by name, and **embed** it in the .docx when the font allows it |
| Font Maker fonts | Not listed as tabs automatically: **+ → From Font Maker…** picks one, which then becomes a tab |
| Old-style (non-Unicode) fonts (Shree-Lipi, Terafont, Kruti Dev, …) | **Warn** and do not add; a converter is later work (L1) |

## How it works

- **Unicode fonts only.** The text stays the same; only the font changes. The browser shapes the letters
  (conjuncts, vowel signs) as with any other Unicode font; Word does the same.
- **Which text a font tab shows.** Each font knows its scripts from its character map (fontTools): a Gujarati
  font shows the Gujarati text, a Devanagari font the Devanagari text, a font with both keeps the script last
  chosen. Font Maker's fonts are Devanagari.
- **Missing letters.** A font's characters are listed (Gujarati and Devanagari blocks only); the screen counts
  the characters of the page that the font lacks ("⚠ 3 missing" on the tab, the characters in its tooltip) and
  highlights those aksharas. Missing characters fall back to the normal fonts.
- **Old-style fonts** have none of the Gujarati / Devanagari characters: the upload is refused with a message
  explaining why (their letters sit on English key codes, so the text would show as nonsense).

## Chunks

### T1 Backend: the font store — built
- `src/letter_extractor/app/fonts.py`: `<library>/display_fonts/<id>.json` (+ `<id>.ttf|.otf` for an upload).
  - `inspect(data)`: family name, scripts, characters, whether it may be embedded (OS/2 `fsType`: not
    "restricted"; and TrueType outlines, since Word embeds only TrueType), whether it has OpenType joining rules
    (`GSUB`; Gujarati MT has only Apple's `morx`, so conjuncts may not join in Word on Windows: said in the tab's
    tooltip), refuses old-style fonts and files that are not fonts (`FontError`).
  - **Font collections (.ttc)**: the Gujarati and Devanagari fonts of macOS (Gujarati Sangam MN, Kohinoor
    Gujarati, Shree714, ITF Devanagari) are all collections, which browsers and Word cannot load: an uploaded
    collection is saved as its Regular font (or its first) on its own. Checked on this Mac: all six load, with
    the right script.
  - The refusal message says the font has no Gujarati or Devanagari letters and names old-style fonts as the
    likely reason (an ordinary font such as Arial is refused with the same message: from the character map alone
    the two cannot be told apart).
  - An upload's id is the first 12 hex digits of its SHA-256: the same file twice is one font.
  - A Font Maker font is a **reference** (`{"source": "fontmaker", "project": "f0001"}`): it always uses the
    project's latest build in `<library>/fonts/<project>/builds/`, read-only (Font Maker owns that folder;
    `letter_extractor` still never imports `font_maker`). Removing its tab removes only the reference.
- API (`api.py`): `GET /api/fonts`, `POST /api/fonts/upload?name=` (the file as the body; .ttf, .otf or .ttc), `GET /api/fonts/fontmaker`
  (Font Maker's built fonts), `POST /api/fonts/fontmaker {"project"}`, `DELETE /api/fonts/{id}`,
  `GET /files/fonts/{id}` (the font file, for the screen).
- `fonttools` becomes a dependency of the reading app (pure Python; Font Maker already used it).

### T2 Screen: font tabs and + — built
- `frontend/src/components/ScriptTabs.tsx`, used by Whole lines (both engines) and the hidden Cut letters view:
  ગુજરાતી | देवनागरी | one tab per added font (✕ removes it, after a confirm) | **+** (Upload a font file… /
  From Font Maker…).
- The chosen tab is remembered in the browser (`text-font`); a removed font falls back to the script tabs.
- **Size matching** (added after a first look: a custom font looked smaller than ગુજરાતી / देवनागरी at the same
  font size, since fonts draw their letters at different sizes). The screen draws a few letters (કગમનરસ /
  कगमनरस) in the custom font and in the normal fonts, and loads the font with `size-adjust` = the ratio of their
  heights (kept between 0.7 and 1.6; `matchScale`). The screen, the PDF and the pictures use the scaled font;
  the Word file gets the same scale on its font size (`&scale=`, 14 pt × scale). Letters the font lacks stay in
  the normal fonts at the normal size.
- **A− / A+** on the chosen font's tab: your size on top of the matched one, in steps of 5% (0.5× to 2×); the
  percentage shows when it is not 100%, and clicking it goes back to the matched size. Kept with the font in the
  library (`"size"` in its `.json`, `PATCH /api/fonts/{id} {"size"}`), so every book, browser and Word file uses
  it. Each size is a face of its own (`display-font-<id>-<version>-<percent>`), since size-adjust is fixed when a
  face is loaded; the match is measured once per font file.
- The browser loads a font with the FontFace API under an internal name (`display-font-<id>`); the text and
  the aligned text use it through the CSS variable `--text-font`.

### T3 Downloads in the font — built
- **PDF**: still printed by the browser (its print dialog, Save as PDF), as before; only the print text's font
  changes, and the browser embeds the font in the PDF.
- **Picture**: drawn on the canvas after the font has loaded.
- **Word**: `/files/texts/...&font=<id>`: the runs ask for the font's family name, and the font is embedded
  (`word/fonts/font1.odttf`, obfuscated as ECMA-376 §17.8.1 says, `w:embedTrueTypeFonts` in the settings)
  when it may be. Otherwise the name only: the file looks right where that font is installed.
- **.txt** has no font: unchanged.

### T4 Help and README — built
- `docs/help/workflow.html` (Read Book → Text) and the README describe the font tabs.

## Later
- **L1 Old-style fonts:** a converter per font family (a mapping table plus reordering: the short-i sign
  before its consonant, reph after the syllable), one family at a time, tested on hand-checked lines.
- **L2** The same font tabs on Line truth and the other text screens, if wanted.

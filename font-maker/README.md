# Font Maker

Build an installable font from a book's letter groups, so that typing Devanagari (क) in Word, Pages or a
browser draws the book's own letters (Devanagari only; see the plan, section 7). A small separate app in this project. It reads the reading app's library
(`library.db`) **read-only** and writes only into `<library>/fonts/`.

Plan and status: [docs/FONT_PLAN.md](docs/FONT_PLAN.md) (F0–F6). Done: F0 (the skeleton: app, screen, tests) and F1 (the main page: pick a book, create, rename and
delete fonts; a font's files are in `<library>/fonts/<id>/`) and F2 (Glyphs: one image per
group from its best copies; pick a copy yourself or leave a group out).

## Run (macOS, zsh, from the project folder)

```sh
npm --prefix font-maker/frontend install        # once
npm --prefix font-maker run build               # build the screen (again after changes in font-maker/frontend/)
PYTHONPATH=src:font-maker/src .venv/bin/python -m font_maker --browser          # port 8676
PYTHONPATH=src:font-maker/src .venv/bin/python -m font_maker --library DIR      # another library folder
```

Without `--browser` it opens in its own window (pywebview), like the reading app. Both apps can run at the
same time.

## Test (light: a few seconds)

```sh
PYTHONPATH=src:font-maker/src .venv/bin/python -m unittest discover -s font-maker/tests
npm --prefix font-maker test
npm --prefix font-maker run typecheck
```

The reading app's tests (`discover -s tests`, `npm test`) do not run these, and these do not run theirs.

## Layout

```
src/font_maker/   main.py (start), api.py (backend), store.py (read-only library),
                  projects.py (font projects), glyphs.py (glyph images)
frontend/         the screen (React); uses the reading app's stylesheet (../frontend/src/styles.css)
tests/            backend tests
docs/             the plan; help pages from F6
```

Font Maker may import `letter_extractor` (tables, akshara splitting, script mapping); `letter_extractor`
never imports Font Maker (checked by `tests/test_f0.py`).

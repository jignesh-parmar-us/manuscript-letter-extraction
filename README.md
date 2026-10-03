# manuscript-letter-extraction

Letter extraction. Read every page in an input folder, cut out every letter with its matras, group identical letters, and write an image of each one to an output folder. A person maps each unique letter to its Gujarati Unicode text (for example the image of कि is mapped to કિ).

Requirements: [docs/requirements-fetch-text.md](docs/requirements-fetch-text.md). Plan and chunks: [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).

**Status:** C0 (read the input folder), C1 (page preparation), C2 (line detection) and C3a (first cut into stroke pieces) are done. Joining and splitting pieces into letters (C3b) is next.

## Install

Python 3.10 or newer on Windows or macOS.

```
pip install -r requirements.txt
```

## Use

```
export PYTHONPATH=src          (macOS / Linux)          set PYTHONPATH=src          (Windows)
python -m letter_extractor --input samples --output out --debug
```

Options:

| Option | Meaning |
|---|---|
| `--input`, `-i` | Folder with the page images (`.jpg .jpeg .png .tif .tiff .bmp`), read in name order (page2 before page10). Only read, never changed. |
| `--output`, `-o` | Folder for the results; created if missing. Must differ from the input folder. |
| `--config`, `-c` | JSON file that overrides settings in [config.py](src/letter_extractor/config.py), for example `{"black_max_rel_l": 0.6, "red": {"min_speck_px": 4}}`. |
| `--workers`, `-w` | Parallel processes (default: automatic). |
| `--debug` | Save an overlay of each step to `<output>/debug/`. |

The exit code is 0 if every page is OK, 1 if some pages failed, and 2 for a folder or config error.

## Output so far

- `report.csv`: one row per file with status (`OK`, `NO_TEXT`, `FAILED`, `IGNORED`), message, page size, text block (`block_x/y/w/h`), black and red ink pixel counts, number of lines, line spacing, number of stroke pieces, specks dropped, and seconds. Files that cannot be read are `FAILED` and do not stop the run; files that are not images are `IGNORED`.
- `lines/<page>_L01.png`, ...: one image per text line, cut from the original page with a small margin. Matras that reach into the neighbouring lines are kept; ink of the neighbouring lines is filled in from the paper around it.
- `debug/<page>_ink.png` (with `--debug`): black ink in black, red ink in red, removed ruled lines in blue, everything outside the text block greyed out, text block outlined in green.
- `debug/<page>_lines.png` (with `--debug`): each line's ink in its own colour (a matra in the wrong colour is on the wrong line), traced headlines as thin dark lines, boundaries between lines dashed.
- `debug/<page>_pieces.png` (with `--debug`): stroke pieces in alternating colours with their numbers, a thin red line at every cut, and ink outside the pieces (upper and lower matras, left for C3b) in light purple.

## How page preparation works (C1)

1. **Paper:** dark areas touching the image edge are the scanner background.
2. **Paper tone:** the local paper colour is a wide median (151 px) on a quarter-size copy, so uneven tone and stains are followed. A narrower window is pulled towards the ink colour inside dense red text.
3. **Ink:** red ink is clearly redder (Lab a*) and somewhat darker than the local paper; black ink is much darker than the local paper. The yellow border band is not red, so it is not ink.
4. **Ruled lines:** straight ink runs longer than 15% of the page are border rules and are removed from the ink.
5. **Text block:** the main run of ink-dense columns and rows. Folio numbers in the margin cover only a few lines, so they fall outside it.
6. **Specks:** blobs smaller than `min_speck_px` (set separately for red and black ink) are removed.

Raw scans and pages cleaned by the border remover both work. Letters that touch a border rule may lose the pixels where they cross it, so cleaned pages are preferred.

## How line detection works (C2)

1. **Headlines:** only horizontal ink runs (25 px or longer) are used, so stems, dandas and matras drop out. Their row profile has one peak per line; the line spacing comes from its autocorrelation (about 112 px on the samples) unless `line_spacing_px` is set.
2. **Tracing:** each headline is followed in 150 px windows near its peak. Windows far from a smooth curve through all windows (dandas, runs of big matras) are replaced by the curve, so slope and gentle waves are followed but not jumps.
3. **Main zone and boundaries:** the main zone ends where the ink below the headlines drops off (about 57 px). Between two lines the boundary follows the emptiest rows below that.
4. **Matras to lines:** every ink blob is assigned whole. A blob touching one headline belongs to that line, even if it reaches past the boundary. A blob touching two headlines (two lines' matras touching) is split at the boundary. A detached blob (anusvara, a dot, a loose matra) goes to the line it is closer to: just above the headline below, or just below the main zone above.
5. **Ink colour per line:** `red` or `black` if at least 80% of the line's ink has that colour, otherwise `mixed`.

On both sample pages all 11 lines are found, and a page takes about 2 s (without `--debug`).

## How the first cut works (C3a)

The headline is drawn letter by letter. Between two letters it either has a gap or, where the strokes overlap, thins out sharply. On the sample pages the red headlines are almost continuous but thin to 1-3 px at every join, so looking only for empty columns misses most red letter boundaries.

1. **Headline thickness** is measured in every column, in a band from 8 px above to 4 px below the traced headline (letter bodies start lower).
2. **Breaks:** a run of columns where the headline is thinner than half its typical thickness, and somewhere thinner than 30% of it. Runs narrower than `min_break_px` are ignored. Limits are set separately for red and black ink.
3. **Cuts:** inside a break the cut goes through each empty column run of the main zone, otherwise through the column with the least ink. A danda or digit standing in a gap becomes its own piece.
4. **Pieces** take the line's ink in their columns, from just above the headline to the bottom of the main zone. Pieces with less ink than `min_piece_ink_px` are dropped as specks. Each piece records its ink colour, the width of its headline ink and the width of its stems, for C3b.

Result on the sample pages: about 36-46 pieces per line. As in the trial in the requirements, black lines show most letter boundaries, with extra pieces where vowel bars (ा ी) have their own short headline and missed cuts where headlines run into each other. Red lines have more of both: about a quarter of their pieces are narrow (bars, ि hooks) and a fifth are wider than 1.6 x the typical piece. C3b corrects these.

## Tests

```
PYTHONPATH=src python -m unittest discover -s tests -v
```

Synthetic pages ([tests/synthetic.py](tests/synthetic.py)) check folder handling, ink masks line detection (sloped and wavy headlines within 2 px, detached marks on the right line) and the first cut (gaps and thin joins cut, tiny gaps and continuous headlines not, a danda as its own piece, in red and black ink) against known values. The sample pages in `samples/` check the text block, ink colours and 11 lines per page on real scans.

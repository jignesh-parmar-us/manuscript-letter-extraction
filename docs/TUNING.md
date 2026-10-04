# Letter Cutting: Tuning Results

Section 8.4 of the requirements asks for steps 1 to 4 (page preparation, lines, first cut, join and split rules) to be checked by drawing the cuts on the sample pages and counting three kinds of error. This file records that check for C3b.

## Method

- Run on `samples/page1.jpg` and `samples/page2.jpg` with the default `config.py`, at commit "Join and split stroke pieces into letters (C3b)".
- Four lines were counted letter by letter, by eye, from the colour-coded letter overlays (`--debug` writes `debug/<page>_letters.png`) and the letter images. They cover both inks and both pages. The other lines were checked by eye only, not counted.
- A letter counts as **correct** when exactly one sample holds it, with all its matras and nothing of its neighbours.
- **Missed split:** two letters in one sample. **Extra split:** one letter in two samples, or a part of a letter (a vowel bar, a matra) in a sample of its own or in the neighbour's sample. **Wrong matra:** an upper or lower mark given to the neighbouring letter.

## Result

| Line | Ink | Letters in the line | Correct | Missed splits | Extra splits | Wrong matras |
|---|---|---|---|---|---|---|
| page 1, line 1 | red | 34 | 31 | 0 | 2 | 1 |
| page 1, line 2 | red | 37 | 31 | 2 | 1 | 1 |
| page 1, line 10 | black (red dandas) | 45 | 42 | 0 | 2 | 0 |
| page 2, line 3 | black | 38 | 38 | 0 | 0 | 0 |
| **Total** | | **154** | **142 (92%)** | **2** | **5** | **2** |

Black lines are cut almost perfectly (80 of 83, and those three errors are dandas). Red lines are 62 of 71 (87%).

Other numbers from the same run (`report.csv`):

| | page 1 | page 2 |
|---|---|---|
| Stroke pieces (C3a) | 434 | 424 |
| Letter samples (C3b) | 429 | 425 |
| ...of which dandas / digits | 25 / 6 | 2 / 0 |
| Seconds per page (one worker, no `--debug`) | 6.9 | 6.0 |

## Errors seen, and their cause

| Error | Example | Cause | Possible fix |
|---|---|---|---|
| Vowel bar at the start of the next letter | ज्ञा + नं → ज्ञ + ानं | The aa bar's headline runs into the next letter with no thinning, so C3a puts the bar in the next piece. The mirror case of the short-i stem, which rule 2 already handles. | A "leading bar" rule: a tall narrow stroke at the left end of a letter, with an empty body gap after it, moves to the letter before. |
| ii bar split off | श्री → श्र + ी | The ii bar's headline touches the consonant and the bar carries part of the next letter's ink, so its part passes the "has a letter body" check. | Measure each part's body without the bar stroke. |
| Lower matra on the next letter | the u of तुं, the u of सु | The u hook touches the next letter's body more than its own. | Prefer the letter whose stem the mark continues (vertical contact) over side contact. |
| Danda split or missed | ॥ as two samples; a red ॥ in a black line as a letter | The two strokes are further apart than `double_danda_gap_ratio`, or one stroke carries a speck that makes it look like a bar. | Use ink colour (red dandas in black lines) and the fact that dandas come in pairs. |
| Left half of a letter taken as a danda | ध → danda + letter | The old-form dha has a free-standing left stroke. | Allow a "danda" only if no letter follows within a small gap. |
| Touching letters not split | र + को, स + र्वे | The bodies touch below the headline, so there is no empty column for a cut, and the pair is narrower than `split_force_ratio`. | Lower `split_force_ratio` for red ink only, or a second cue such as two stems. |

These cases are what the review screen (C9) will fix by hand: a join or a split of two samples. On these pages that is about 1 correction per 13 letters, and fewer on black ink.

## How to repeat the check

```
PYTHONPATH=src python -m letter_extractor -i samples -o out --debug
```

Open `out/debug/page1_letters.png`. Each letter has its own colour along the line, a box around it, dandas are grey, digits magenta, and letters made by a split have a dashed red box. `out/samples.csv` lists the rules applied to each letter (`rules` column).

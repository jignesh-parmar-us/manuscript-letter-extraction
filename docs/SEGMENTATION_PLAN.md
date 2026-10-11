# Reading lines without Tesseract: segmentation by recognition

Plan for reading printed lines with our own data (the labelled groups, the letter reader and the language model) instead of Tesseract, by **sliding along the line and recognising letters as we go**, rather than cutting letters first. Agreed to plan on 2026-10-11; every stage is measured on the user's checked lines and has a stop point.

Status: **stage 1 passed** (2026-10-11): the reader names 94.9% of real windows right at exact boundaries (gate: 90%). Stage 2 is next. Nothing is built into the app yet.

---

## 1. Why

**What we know** (measured on the 73 checked lines of the printed 1933 book, `TUNING_PHASE2.md`, 2026-10-11):

| Way of reading | Characters wrong |
|---|---|
| Tesseract, whole lines, + language model | 4.45% |
| Tesseract, whole lines | 5.06% |
| App: cut letters, Tesseract + groups + language model | 5.39% |
| App: cut letters, groups + reader + language model, **no Tesseract** | 27.7% |

- The letter reader is 96% right on **cleanly cut** letters (C14 test pages), but the no-Tesseract route is 27.7% wrong: **cutting is the bottleneck**, not recognising.
- Tesseract stays confident when it is wrong, so it cannot mark its own mistakes for proofreading.

**The idea** (the user's, 2026-10-10 and 2026-10-11): don't cut letters by strokes. Put letters on the line one by one, keep the one that fits, move past it, continue. The labels are already whole aksharas as they appear on the page (conjuncts, reph forms, letters with their matras: 404 reviewed groups, 8,943 letters), so the visual order problems of Devanagari (ि drawn before its consonant, र् over the next letter) are mostly inside the labelled images already.

**The earlier attempt** (2026-10-10 prototype, `TUNING_PHASE2.md`): matching candidate stretches of a line against the groups' fingerprints with dynamic programming read 70–89% of the characters wrong. The matcher could not say "this is *not* a whole letter": half a letter, two letters, or a letter with a neighbour's matra looked close enough to some group. This plan fixes exactly that.

## 2. Goal and success

- **Main goal:** a reader of printed lines that needs no Tesseract, built from the book's own data.
- **Realistic first target:** about 10–15% of the characters wrong (estimate, not a measurement).
- **Stretch target:** reach Tesseract (5%) or Tesseract + language model (4.5%). Unlikely without much more work.
- **Likely real win even at about 10%:** a **second opinion** beside Tesseract. Where the two disagree, the letter is probably wrong: real uncertain marks for proofreading, and a vote between two different engines may beat both.

## 3. Approach

1. **A matcher that knows what is not a letter.** The letter reader gets one more class, *not a letter*, trained on wrong windows generated automatically from the labelled lines: half a letter, two letters together, a letter shifted by a few pixels, a vowel bar alone.
2. **Realistic training windows.** Letters are learned as a sliding window sees them: the whole line's ink in the letter's columns, including neighbours' overhanging matras and bars, not only the clean mask.
3. **One search over the line.** Candidate positions every few pixels; window widths from a bar to a wide conjunct (about 0.3 to 2.5 × the book's typical letter width). Each step scores:
   - the reader's log probability of the label (and of *not a letter*),
   - a penalty for an unusual width for that label,
   - the language model's log probability of the label after the previous two (trigrams, as in C15).

   A beam search (states: position on the line, last two aksharas) finds the best path; the labels on the path are the text. No Tesseract, no prior cutting.
4. **Spaces** from wide empty column runs between steps (printed books), as `text_space_gap` does today.

## 4. Data

| What | Where it comes from |
|---|---|
| Letter windows (positives) | Reviewed letters of the Training Data pages: their box columns on the line's ink mask (`Line` image + `Sample` boxes); labels from their groups |
| Not-a-letter windows (negatives) | Generated from the same lines: left/right halves of letters, two neighbouring letters, windows shifted by 15–40% of a letter width, bars and matras alone |
| Language model | As in C15: labels in reading order + proofread lines + the book's word lists |
| Test set | The checked lines (Line truth, `line_truth`), Read Book pages |

**Fairness rule** (memory `measure-on-hand-checked-lines`): the checked pages are also Training Data pages, so every test rebuilds the reader and the language model **without the tested pages** (4 folds of 2 pages), and corrections made on those pages are not used.

## 5. Stages

Each stage is an experiment on a copy of the library first (scripts in the scratchpad, results in `TUNING_PHASE2.md`); only a stage that passes its gate is built into the app.

### Stage 1. The upper limit (about 45 minutes)

**Question:** if the search found exactly the right letter boundaries, how often would the reader name each window right, with the neighbours' ink included?

- Take the reviewed letters of the Training Data lines; their accepted boxes are the right boundaries.
- For each, the window is the box's column span of the **whole line's** ink mask (neighbours' overhang included).
- Read each window with a reader trained without its page (folds by page); compare with the same letters as clean masks.
- Report: accuracy on windows vs clean masks; per frequency band (common / middle / rare labels); the most common confusions.

**Gate:** continue only if windows are read right **≥ 90%** of the time. Below that, the search cannot do better and the plan stops (the reader would need a different input first, see Risks).

### Stage 2. A reader that knows what is not a letter (about 1 day)

- Generate the negatives (Section 4) and train the reader with the extra class, on realistic windows (positives as in stage 1) plus the clean masks.
- Measure on held-out pages: accuracy on real letter windows; share of negatives called *not a letter*; share of negatives called a letter with probability ≥ 0.9 (the dangerous case).

**Gate:** continue if real windows stay ≥ 90% right and fewer than about 5% of the negatives are confidently called a letter.

### Stage 3. The line search with the language model (1–2 days)

- Beam search over each checked line (Section 3), with the stage-2 reader and the fold's language model.
- Tune on Training Data lines with labels (not on the checked lines): beam width, width penalty, language-model weight, the step between positions.
- Score on the 73 checked lines: character error rate on all lines and on the lines not in the word list; a line-by-line comparison page (like the earlier one) so each difference can be checked by eye; time per line.

**Gate:** continue to stage 4 if the error rate is **≤ 15%**. Below about 6% it is a reader in its own right and worth building into the app.

### Stage 4. A second opinion beside Tesseract (about half a day)

- Align the stage-3 reading with Tesseract's whole-line reading (akshara by akshara, dynamic programming as in `ocr/align.py`).
- Where they agree: sure. Where they disagree: uncertain, and pick by a vote (Tesseract's confidence, the reader's probability, the language model).
- Measure: error rate of the vote; how many of Tesseract's mistakes fall on the uncertain letters (today almost none are marked); share of letters marked.

**Gate:** worth building if the vote beats Tesseract + language model (4.45%), or if the uncertain marks catch most mistakes while marking a small share of letters.

### Stage 5. Into the app (only for what passed)

- A third choice in Read Book → Text (beside *Whole lines (Tesseract)* and *Cut letters*), or uncertain marks in Whole lines from the second opinion.
- Tests, the help pages (`parts.html`, `tech-reading.html`), the plan and `TUNING_PHASE2.md` updated in the same commit (memory `document-approach-changes-in-plan`).

## 6. What success looks like at each stop

| Result | What we do |
|---|---|
| Stage 1 below 90% | Stop. Recognition on real windows is the problem; consider a better reader input (larger context, the page image instead of the mask) or the trained line recognizer (C18). |
| Stage 3 above 15% | Stop for printed books; keep the findings for handwriting. |
| Stage 3 at 6–15% | Use as a second opinion (stage 4). |
| Stage 3 below 6% | A reader of its own; build it in, and compare again with Tesseract. |
| Stage 4 beats 4.45% | Build the vote into Whole lines. |

## 7. Risks

- **Overlapping marks:** matras and the reph overhang neighbours; a window with foreign ink may be misread. Stage 1 measures this directly.
- **Rare labels:** rare letters (1–19 samples) are 17% of the letters and were about 85% right even on clean letters; with min samples 1 the reader knows 87% of them. The language model helps, the word list most.
- **Not-a-letter examples that are too easy:** generated negatives may not cover every real mistake; stage 3 shows the remaining ones, which become new negatives.
- **Speed:** about 800 positions × 30 widths per line; the linear reader is a matrix product, so about a second per line is expected. The network reader would be slower.
- **The truth was typed from Tesseract's reading,** which slightly favours Tesseract in every comparison.

## 8. Files (when built into the app)

| File | What |
|---|---|
| `src/letter_extractor/ocr/segment.py` | the line search (windows, scores, beam search) |
| `src/letter_extractor/app/readers.py` | training with the *not a letter* class and window examples |
| `src/letter_extractor/app/wholelines.py` | the second opinion, if stage 4 passes |
| `tests/test_segment.py` | search on synthetic lines; the not-a-letter class; fairness of folds |
| `docs/TUNING_PHASE2.md` | each stage's numbers |

## 9. Results log

| Stage | Date | Result | Decision |
|---|---|---|---|
| 1 | 2026-10-11 | Windows with the neighbours' ink, exact boundaries: 94.6% right (clean masks 95.3%); shifted by up to 10%: 89.7%. Training variants: 50 per label 94.7% (rare 80.7%, but shifted 87.1%); **balanced weights 94.9%** (common 98.4, middle 97.7, rare 79.5, shifted 89.7). 169 of 1,521 rare test letters had labels only on their own page. Mistakes are mostly top marks (ता→तां, मा→मां, ता→तो). | Passed; stage 2 with balanced weights |
| 2 | | | |
| 3 | | | |
| 4 | | | |

# Reading lines without Tesseract: segmentation by recognition

Plan for reading printed lines with our own data (the labelled groups, the letter reader and the language model) instead of Tesseract, by **sliding along the line and recognising letters as we go**, rather than cutting letters first. Agreed to plan on 2026-10-11; every stage is measured on the user's checked lines and has a stop point.

Status: **stages 1 and 2 passed** (2026-10-11). Stage 1: the reader names 94.9% of real windows right at exact boundaries (gate: 90%). Stage 2: with a *not a letter* class and a tolerance band, 92.4% of real windows right and only 1.4% of wrong windows confidently called a letter (gates: 90%, 5%). Stage 3: reading lines without Tesseract, 11.1% of the characters wrong on the 73 checked lines (gate: 15%). Stage 4: as a vote the line search makes the text worse (5.78% against 4.45%), but as **uncertain marks** where it disagrees with Tesseract + language model it marks 19.4% of the aksharas and catches 88% of the remaining mistakes. Stage 5, speed: `ocr/segment.py` with a boundary every 9 px and unlikely windows dropped reads a line in **6.6 s** (about 40 s before) at **10.2%** wrong on the 73 lines (11.1% before). **Built (2026-10-11): Text → Whole lines → Second opinion** trains the line search reader on the book's reviewed letters (first time), reads the pages read whole again and marks the aksharas where it differs as uncertain. **Since 2026-10-12 its own tab, Text → Whole lines (our reader)** (asked by the user, for a clear separation): its reading shown like Tesseract's, Retrain, and a fold-fair Measure on the checked lines.

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

- A third choice in Read Book → Text (beside *Whole lines (Tesseract)* and *Cut letters*), or uncertain marks in Whole lines from the second opinion. **Built: the marks** (`app/linesearch.py`, the *Second opinion* button; the line search's reading kept per line as `whole_line.search_dev`, migration 0013). The vote failed in stage 4, so at first there was no third choice.
- **Changes from the original plan (2026-10-12): the third choice is built after all, as a view, not a vote.** The user asked for the line search in its own tab, *Whole lines (our reader)*, to review and measure it apart from Tesseract. `WholeLinesView` takes an `engine` ("tesseract" | "search"); the line search keeps each akshara with its columns on the line and its ink rows as a box on the page (`whole_line.search_aksharas`, `search_at`, migration 0014; `ocr/segment.read_line` now marks a word gap on the letter after it), so the tab has the same views, clicks and aligned text. Where Tesseract reads differently is highlighted (the marks, seen from the other side). **One corrected text and one ✓ per line**, shared by both tabs (correcting twice would make two truths). The *Second opinion* button moved to the new tab as *Read all pages*; the marks stay in the Tesseract tab. **Retrain:** the reader keeps a hash of the reviewed letters it learned (label, place); when they change, the tab says so and offers *Retrain and read all pages*. **Measure** (`linesearch.measure`, a job): the checked lines of the Read Book pages, scored fold-fair, since every Read Book page is also a Training Data page: the pages with checked lines in 4 folds, for each the reader and the language model rebuilt without those pages (`dictionary.book_model_without`: their labels and proofread lines left out, word lists kept), as in stages 3 and 4. Beside it Tesseract alone and Tesseract + language model as read whole (that model knows every page), and the marks' share and catch; every line is listed to check by eye. Kept in `line-search/measure.json`.
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
| `src/letter_extractor/app/wholelines.py` | the second opinion's marks; the lines as our reader read them (`engine="search"`) |
| `src/letter_extractor/app/linesearch.py` | the reader (training, Retrain check), reading pages, the fold-fair Measure |
| `frontend/src/screens/WholeLinesView.tsx` | both tabs: Whole lines (Tesseract) and Whole lines (our reader) |
| `tests/test_segment.py` | search on synthetic lines; the not-a-letter class; fairness of folds |
| `docs/TUNING_PHASE2.md` | each stage's numbers |

## 9. Results log

| Stage | Date | Result | Decision |
|---|---|---|---|
| 1 | 2026-10-11 | Windows with the neighbours' ink, exact boundaries: 94.6% right (clean masks 95.3%); shifted by up to 10%: 89.7%. Training variants: 50 per label 94.7% (rare 80.7%, but shifted 87.1%); **balanced weights 94.9%** (common 98.4, middle 97.7, rare 79.5, shifted 89.7). 169 of 1,521 rare test letters had labels only on their own page. Mistakes are mostly top marks (ता→तां, मा→मां, ता→तो). | Passed; stage 2 with balanced weights |
| 2 | 2026-10-11 | Negatives (halves, the letter with its neighbour, windows shifted 25–45%): 43,092. With all negatives weighing as much as all letters and no varied copies: real windows 88.6% right, 6.4% called *not a letter*, shifted ≤ 10% only 69.8%; weights 0.5 / 0.25 hardly changed it (89.7 / 89.8%). **With a tolerance band** (windows shifted 3–10% and the varied copies count as the letter; negatives at weight 0.25): exact windows **92.4%** (common 95.9, middle 96.5, rare 74.3), shifted ≤ 10% 87.0%, real letters called *not a letter* 1.6%; negatives called *not a letter* 95.8%, confidently called a letter **1.4%**. | Passed; stage 3 with this reader |
| 3 | 2026-10-11 | Beam search over each checked line with the stage-2 reader (linear, tolerance band), a width penalty and the language model (word list + labels of the other pages); reader and language model without the tested pages; settings chosen on the other half of the pages. Candidate boundaries only at gaps and thin points below the headline: **30.1%** (197 stretches of touching letters could not be read at all). **A boundary every 6 px** plus those points: **11.1%** (10.2 / 11.7% on the two halves); about 13,000 windows read per line, about 1 minute per line in plain Python. | Passed; stage 4 (second opinion) |
| 4 | 2026-10-11 | Tesseract (whole line) aligned with the stage-3 reading akshara by akshara. Vote (the stage-3 akshara as one more candidate for the language model, weight chosen on the other half): **5.78%**, worse than Tesseract + language model (**4.45%**) at every weight (0.25–2: 5.8–7.0%). Uncertain marks where the two disagree: **19.4%** of the aksharas marked, **244 of 277 (88%)** of the remaining wrong aksharas among them. | Marks pass (most mistakes caught on a fifth of the letters); the vote does not. Stage 5: speed first, then the marks in Whole lines |
| 5 (speed) | 2026-10-11 | The search as a module (`ocr/segment.py`) with the window features computed in one batch (same numbers, 1.6x faster). Fold 0 (18 lines; stage 3 there 9.56%): boundary every 6 px **10.21%**, 19.9 s/line, 14,422 windows; every 9 px **9.32%**, 11.3 s; 6 px + dropping windows whose best letter is under 5% 10.33%, 17.5 s (4,170 kept). **Every 9 px + dropping, all 73 lines: 10.18%** (stage 3: 11.11%), **6.6 s per line**, 7,632 windows (2,345 kept). The 6 px rerun differs from stage 3 by the readers' random training (0.6 points). | 9 px + dropping are the defaults; about 7 s per line (a 30-line page in 3–4 minutes) is fit for a background job. Next: the marks in Whole lines |
| 5 (in the app) | 2026-10-11 | **Text → Whole lines → Second opinion** tried on a copy of the library, book 6, page Untitled-15.jpg (the only Read Book page read whole there, 13 lines). Learning the letters (first time only): 8,946 reviewed letters, 412 labels, **7 minutes** (the test suite ran at the same time). Reading: **84 s for 13 lines** (6.5 s per line). Marked: **73 of 651 aksharas (11.2%)**. In the first three lines the marks fall on real Tesseract problems (पोा with a stray vowel sign, वार््ती with a doubled virama, दत्तांत, साहित, रहे, ते, थो), some on the line search's own mistakes (मां→ना, री→ले: it is wrong on about 10% of the characters alone, so a mark means *check this*), and a mistake both readers share is not marked (करयो, probably कर्यो). Not measured on this page: it has no checked lines. | Works. Open: a way to learn the letters again from the app after more reviews (the API has `retrain`; no button yet); measure the marks on new checked lines from Read Book pages (the 73 are Training Data pages); possibly a faster first training. |
| 5 (own tab) | 2026-10-12 | **Text → Whole lines (our reader)** on a copy of the library (book 6, after the user's group cleanup): the reader is reported as out of date (`changed`); Untitled-58.jpg read in 70 s (13 lines), every akshara with its box; 74 of 639 aksharas where Tesseract reads differently; line 2 reads उपर्य (Tesseract: उपस्य / परय in other lines). **Measure** (fold-fair, 4 folds of 2 pages, 8,048–8,219 letters per fold, 42 minutes): on the 73 checked lines (6,675 characters) our reader **9.99%** wrong (stage 5: 10.18%), Tesseract 5.03%, Tesseract + language model 4.12% (that model knows every page); the marks cover **15.6%** of the aksharas and catch **215 of 255 (84%)** of the mistakes left by Tesseract + language model (stage 4: 19.4%, 88%). | Retrain and Measure are buttons; every reviewed line from either tab joins the measure. |
| 6 (learning from corrections) | 2026-10-12 | 99 checked lines on 10 pages (the user corrected Untitled-52, 53). A harness caches each fold's training windows and its lines' windows (`segment.line_windows`, `linesearch._training_set`) to try readers quickly, fold-fair (4 folds by page). Linear reader, 15 epochs: **8.38%** (new pages 52, 53: 4.89%); 40 epochs 8.14% (4.24%); one hidden layer (384) 7.52% (5.11%). Tesseract 4.69–4.75% (3.80–3.93%). 2.8% of the checked aksharas had no class at all (हे in an unreviewed group, rare conjuncts); the most common confusion बा→वा came from ब / बा letters inside the व / वा groups. **Learning from corrections**: each checked line of the other folds' pages cut into the aksharas of its text by forced alignment (`segment.align`: known aksharas by the reader, unknown ones by the window being a letter and its width) and its windows added as examples (3,200–4,100 per fold, 33–45 new labels; no line rejected): **7.32%**, new pages **3.93%** against Tesseract 3.80%. | Built: Retrain learns from the checked lines (40 epochs), Measure does per fold; Retrain only trains, reading is separate. Next: vowel-sign confusions (नी→नो, री→रो, पा→पो). |
| 6b (2026-10-13) | 2026-10-13 | Language model weight 0.35 (one run, within the noise of row 6c): 6.86% (new pages 3.76%, Tesseract 3.80%); weight 0 16.4%, 1 and more worse. Neural network with corrections 7.50%; close-ups of the marks 7.96% (`TUNING_PHASE2.md`). | Weight 0.35 to confirm with more lines; network and close-ups dropped. Reading the base and the marks separately is planned and parked in `SPLIT_READING_PLAN.md`. |
| 6c (letters on no line) | 2026-10-13 | Fresh copy of the library: learning the reviewed System generated letters from their picture (they are on no line). One run (seed 0) said 7.88% → 6.94%, but over **three seeds** it is 7.26% without and 7.23% with them: **no measurable effect**. The same three seeds explain the apparent drop between two copies of the library (one unlucky run): a single training run moves by up to about 1 point by chance. | Kept (`linesearch._training_set`, `unlined`): it does no harm and a reviewed group of even one letter must be usable (`CLAUDE.md`); unreviewed generated letters not learned. **From now on compare variants over several seeds** (`tools/harness/run.py --seed`). |
| 5 (borders) | 2026-10-12 | The user saw both readers read the **page border** (pages Untitled-51, 52; a few lines of 53, 65, 66). Tesseract writes it as `\|`, `!`, `I`, `]`; our reader as `???` or folds it into a made-up first word (शांत्यां for रना…). On the edges of all 299 Read Book lines: the border sits close to the text (9–13 px, so a gap rule fails) but is thin, broken and taller than the letters; the ॥ dandas are 28–35 px wide, 52–59 px tall and solid. `segment.clear_borders` peels thin edge pieces that are taller than the line's letters, broken and out of the letters' band, or specks: 36 of 44 border edges cleared (the other 8 have no border in our reader's ink), **no danda**, 11 more edges (specks and right-hand borders Tesseract missed; all checked by eye). Untitled-51 and 52 re-read (26 lines, the current reader): **12.6% → 7.5%** wrong against the checked text (Tesseract's text without `\|` where not checked). Tesseract's border marks at the line edges are left out when shown, downloaded and measured (`wholelines.trim_edges`). | Built. A few lines still start with `?` (part of a border kept). |

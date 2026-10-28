# Reading the letter and its vowel sign separately (idea 4)

A plan, not built. Our reader (Text → Whole lines (our reader), `docs/plans/done/SEGMENTATION_PLAN.md`) recognises every akshara as one whole picture: नी, नो, ना and ने are four unrelated classes. This plan reads an akshara as its **base** (consonant, conjunct or vowel) **plus its marks** (vowel signs, anusvara, halant, reph), each judged on its own, and combines them.

Status: **parked** (2026-10-13). Proposed by Claude when the remaining errors turned out to be mostly vowel signs; kept so it is not lost. Pick it up if the cheaper improvements stall (see section 2).

---

## 1. Why

**Where our reader stands** (fold-fair, 4 folds by page, 99 checked lines of the printed 1933 book, `TUNING_PHASE2.md`):

| Reader | Characters wrong | Untitled-52, 53 (newest pages) |
|---|---|---|
| Our reader: linear, learning from corrections, language model 0.5 (in the app) | 7.32% | 3.93% |
| same, language model 0.35 (one run; runs differ by about 1 point by chance) | 6.86% | 3.76% |
| Tesseract, whole lines | 4.69% | 3.80% |

**The errors left are mostly vowel signs**: नी→नो (6), र→रे, री→रो, ती→तो, पा→पो, न→ने, त→ता, कों→को, ई→इ. The letter is right, the small mark is wrong.

**Why the whole-akshara reader struggles with them:**
- A window is shrunk to 40 px and looked at as a 20 × 20 picture (`ocr/features.py`): a ी hook or a ो mark gets a few pixels.
- Every akshara is its own class, so the examples are split thin: न is learned separately inside नी, नो, ना, ने, नि, नु…; a rare combination (बी, a conjunct with a vowel sign) has few or no examples. Before learning from corrections, 2.8% of the checked aksharas had no class at all.

**Already tried, did not help** (`TUNING_PHASE2.md`, 2026-10-12/13):
- a neural network reader (one hidden layer, 384): 7.50% against 7.32%;
- close-ups of each window's top strip, bottom strip and right side added to the features: 7.96% / 8.43% (worse: about 400 more numbers, mostly the neighbours' ink, which a single reader for all aksharas cannot sort out);
- a stronger language model: worse at every weight above 0.5.

## 2. When to pick it up

After the cheaper steps, if our reader is still behind Tesseract on the checked lines:
1. the language model weight (0.35 looked best; to be confirmed with more lines);
2. learning the System generated letters (measured 2026-10-13: no measurable effect over three seeds, kept);
3. more checked lines (every corrected page adds about 4,000 training letters and makes the measure surer).

## 3. The idea

An akshara is a base plus marks in fixed places:

| Slot | Values (Devanagari; Gujarati the same shapes) | Where in the window |
|---|---|---|
| base | consonant, conjunct (क्ष, त्र, स्त, र्य as printed…), vowel (अ इ उ ए…) | the body, below the headline |
| top | none, े, ै, ं, ँ, reph र् (drawn above), ो/ौ's top stroke | above the headline |
| right | none, ा (bar), ी (bar with a hook) | the right edge |
| left | none, ि (bar with a hook, drawn before the base) | the left edge |
| bottom | none, ु, ू, ृ, ् | below the body |

ो is the right bar plus the top stroke of े, ौ the bar plus ै: the slots combine.

**Reading:** P(akshara) = P(base) × P(top) × P(right) × P(left) × P(bottom), each from its own small reader. The search (`segment.search`) asks each window for its best few aksharas; the combined reader gives them by combining the best few values of each slot, so it can offer combinations it has never seen as a whole (बी from ब and ी).

**Learning:** every labelled letter teaches every slot. नी teaches base न, right ी, top none…; नो teaches base न again. The base न gets the examples of all its forms, and a mark gets the examples of all its bases. The labels are decomposed by their Unicode code points, so no new labelling is needed.

## 4. Design choices to make first

1. **One window, several heads** (start here): the same window, its whole-window features for the base, and features of the slot's zone for each mark. Each head learns only its slot, which is what the failed close-up experiment could not do: there, one reader had to learn every akshara from all zones at once.
2. **Or cut the window into zones first** (headline row, right bar columns) and read each zone on its own. More exact, more ways to go wrong (the headline is not always straight, ि's hook reaches over the previous letter).
3. **Not a letter** stays a class of the base head (halves, neighbours, shifted windows, as now).
4. **The width penalty** of the search uses the base's usual width plus the right and left marks' widths, so unseen combinations get a sensible width too.
5. **The language model** stays on whole aksharas (it does not see the ink).

## 5. Stages, each with a stop point

Each stage runs on a copy of the library first, measured fold-fair on the checked lines (memory: measure on hand-checked lines). The experiments' harness (cached training windows and line windows per fold, `scratchpad/harness*` in the 2026-10-12/13 sessions) should first be moved into the repository (`tools/harness/`), or it is lost with the session.

| Stage | What | Gate (continue if) | Effort |
|---|---|---|---|
| 0 | Move the harness into `tools/harness/`; one command builds the caches, one runs a variant | the baseline reproduces 7.32% | ½ day |
| 1 | Decompose every label into slots; report bases and mark values, and labels that do not decompose | every label decomposes, or the exceptions are few and listed | ½ day |
| 2 | The heads on clean windows of held-out pages (as stage 1 of the Segmentation plan): akshara accuracy against today's reader, and on the vowel-sign pairs alone | at least today's accuracy, and better on the vowel-sign pairs | 1 day |
| 3 | The combined reader in the search (harness), 99+ checked lines | below the best whole-akshara reader of that day | 1 day |
| 4 | Into the app: Retrain / Read / Measure unchanged for the user; `meta.json` says which reader | the app's Measure confirms stage 3 | ½–1 day |

**Stop:** if stage 2 is not better on the vowel-sign pairs, the marks are not separable with these features; note why in `TUNING_PHASE2.md` and keep the whole-akshara reader.

## 6. Risks

- **ि and reph** are drawn away from their base (ि before it, र् above the next letter). In the labels they belong to the akshara, and the windows hold the whole akshara, so the slots see them; but a window that cuts ि off reads a wrong left slot.
- **Conjunct shapes** vary (half forms, stacked forms, the wide र्य of this print): they stay whole base classes; only what is attached to them is factored.
- **Independent errors multiply**: five slots each 99% right give about 95% for the akshara. The heads must be good, or the product needs a correction (a whole-akshara score as a sixth factor for seen combinations).
- **Measuring**: the checked text typed from one reader's reading favours that reader a little (the first 73 lines from Tesseract's).

## 7. Files (when built)

| File | What |
|---|---|
| `src/letter_extractor/ocr/aksharas.py` | decomposing a label into its slots |
| `src/letter_extractor/ocr/features.py` | zone features per slot |
| `src/letter_extractor/ocr/reader.py` | a reader with several heads (or several readers) |
| `src/letter_extractor/ocr/segment.py` | the search asking the combined reader for each window's best aksharas |
| `src/letter_extractor/app/linesearch.py` | training the heads (reviewed letters, letters on no line, checked lines) |
| `tools/harness/` | the experiments' harness |
| `docs/TUNING_PHASE2.md` | each stage's numbers |

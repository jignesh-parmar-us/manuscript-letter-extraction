# Tuning notes, Phase 2

Measured numbers behind the Phase 2 defaults (`docs/implementation_plan_phase2.md`), per chunk, like `TUNING.md` for Phase 1.

## C10. Tesseract languages and image preparation (2026-10-04)

**Setup:** Tesseract 5.5.3 (MacPorts) with `hin`, `mar`, `san` and `script/Devanagari`. Line images from Phase 1 (`lines/*.png`): the 7 printed pages of `samples/blackandwhite/` (91 lines) and the handwritten `samples/page1.jpg`, `page2.jpg` (red and black ink). `--psm 7` (one line), hOCR with character boxes.

**Character error rate (CER)** in code points, after removing spaces, against my own transcription of 4 lines. "h" is the letter-body height Tesseract gets (0 = the line image as it is, binarized, with a 10 px border):

| Line | san h0 | hin h0 | mar h0 | script/Devanagari h0 | script/Devanagari h40 | script/Devanagari h50 |
|---|---|---|---|---|---|---|
| printed, Untitled-15 L03 | 0.19 | 0.12 | 0.09 | **0.06** | 0.12 | 0.11 |
| printed, Untitled-26 L05 | 0.16 | 0.08 | 0.10 | 0.10 | 0.10 | 0.07 |
| printed, Untitled-41 L08 | 0.09 | **0.01** | 0.02 | 0.02 | 0.01 | 0.02 |
| handwritten, page1 L03 | 0.43 | 0.44 | 0.48 | **0.35** | 0.37 | 0.32 |

`san+hin` was no better than `hin` and twice as slow. Grayscale instead of the binarized image made no difference (within one or two letters per line).

**Findings:**
- **Printed:** about 5% of code points are wrong with `script/Devanagari` or `mar`. The errors are mostly half-letters and rare conjuncts (छ्यु read as ङयु, वृ as द). `script/Devanagari` and `mar` read ल as ळ in places. For the Gujarati mapping this matters, so the group vote (C11) and the user's review must catch it.
- **Handwritten (this hand):** about 30 to 35% of code points are wrong. That is more than the plan expected ("little or none"), because this scribe's hand is regular. One wrong code point usually spoils a whole akshara, so per-akshara accuracy is lower still. Votes over a whole group (C11) might still give useful suggestions for common letters. C12 measures this. Until then, Tesseract is not the default reader for handwritten books.
- **Confidence is not a signal:** the mean character confidence was 98% on printed lines and **95% on handwritten lines**, where a third of the characters are wrong. Tesseract's confidence cannot separate right from wrong readings. C11's `suggest_min_confidence` filter will have little effect; the group vote and its share have to do that work.
- **Scaling** to a letter-body height of 30 to 60 px changed single letters both ways, with no clear winner on these lines. The default is no scaling (`ocr_letter_height = 0`). The printed bodies are 50 to 65 px tall, already in Tesseract's good range. The setting stays for scans at very different resolutions.
- **Speed** (this Intel Core i5 Mac): `script/Devanagari` takes about 1.8 s per printed line, `hin` about 0.35 s. A 91-line book takes about 3 minutes with `script/Devanagari`. This is acceptable for a background job.

**Defaults set:** `ocr_langs = "script/Devanagari"`, `ocr_psm = 7`, `ocr_letter_height = 0`. To be checked again on all lines in C12, where the user's final labels give a real ground truth.

## C11. Matching readings to samples, and group votes (2026-10-05)

**Setup:** a copy of the user's library (the app's database and book folders; the library itself was not changed). Book 1, "Vachnamrut Black and White": the 7 printed pages of `samples/blackandwhite/`, 91 lines, 4,571 samples in 277 groups, of which the user had labelled 27 (916 samples). These labels are the ground truth. Book 2, "Vachnamrut Printed": 23 printed pages, 302 lines, 14,570 samples, no labels. Default settings: `script/Devanagari`, `align_min_overlap` 0.6, `align_sure_overlap` 0.8, `suggest_min_votes` 3, `suggest_min_share` 0.6. 7 Tesseract processes at once on this 8-core Mac.

| | Book 1 (7 pages) | Book 2 (23 pages) |
|---|---|---|
| Time for the whole book | 31 s | 117 s |
| Lines refused (fewer than half of the samples matched) | 2 of 91 | 7 of 302 |
| Samples with a reading | 3,392 of 4,571 (74%) | 10,917 of 14,570 (75%) |
| Groups with ≥ 5 samples that get a suggestion | 50 of 158 (32%) | 90 of 332 (27%) |

**Accuracy against the user's labels (book 1):**
- **Per sample:** 761 of the 916 labelled samples got a reading; 574 of them (75%) are the label.
- **Per group, as if unlabelled:** 13 of the 27 labelled groups would get a suggestion, and **all 13 are right**. 14 get none: too few readings in the small groups, and split votes in the big ones.

**Why readings and labels differ:** almost entirely the **ा bar**. The most common mismatches are त read as ता (33), न as ना (22), प as पा (12) and त as तो (10). On this print, Phase 1 often cuts the ा bar off as a sample of its own, or joins it to the letter on the right. Tesseract reads ता, and its box for the ा is too far left (about 15 px) to show which sample holds the bar. A rule that dropped the bar sign when the next sample is a narrow bar was tried: it changed the per-sample accuracy from 75.4% to 75.8% and made no group suggestion right that was not before, so it was removed. The vote handles these groups safely: त 30 against ता 33 is no suggestion, not a wrong one.

**Why so few groups get a suggestion:** most groups of this print are **mixed**. Phase 1's grouping puts different letters together (g0009: ता 29, ना 25; g0013: नि 22, ने 13; g0017: वि 23, दि 10), or the same letter with and without its vowel bar. Of the 108 groups (≥ 5 samples) in book 1 without a suggestion, 12 had fewer than 3 readings and 93 had a winning share below 0.6. A lower `suggest_min_share` would suggest one label for a mixed group, so it stays at 0.6. The API returns each group's 3 most common readings, so C12 can mark mixed groups and help split them, after which the parts get suggestions.

**Confidence** stays useless as a filter (C10): readings that agree with the labels averaged 98.6, those that do not 97.9. At `suggest_min_confidence` 80 all 761 pass; even at 95, 169 of the 187 wrong readings would pass.

**Defaults kept:** all C11 settings as planned. The plan's target, a suggestion for 70% of groups with ≥ 5 samples, is not met (32%, 27%). The cause is the grouping, not the reading, so the target moves to C12: after mixed groups are split with the help of the readings.

## C12. Suggestions in the Review tab (2026-10-05)

**Accuracy by share band**, from the app's own check ("Checked against your labels" in the Review tab, `GET /api/books/{id}/suggestion-accuracy`), on book 1 with its 27 labelled groups:

| Share of the winning reading | Right | Wrong |
|---|---|---|
| 90% or more | 5 | 0 |
| 75 to 90% | 5 | 0 |
| below 75% (down to 60%) | 3 | 0 |
| no suggestion | 14 groups | |

13 of 13 suggestions are right in every band, but 13 groups are too few to set the bulk-accept threshold. **`bulk_accept_share` stays at 0.9** until the user has reviewed a whole printed book; then this table is measured again (the plan's C12 "done when").

**Splitting mixed groups, simulated** on a second copy of book 1: for every unlabelled group without a suggestion, the samples of each other reading with at least 2 samples were moved to a new group (what "click a reading, then New group" does). This splits blindly by reading, including त-shaped letters read as ता, which a person looking at the images would not do, so it is an estimate only:

| | Groups with ≥ 5 samples | With a suggestion |
|---|---|---|
| before | 158 | 50 (32%) |
| after one round (101 splits) | 182 | 103 (57%) |
| after a second round (25 more) | 183 | 108 (59%) |

The plan's 70% is therefore not reached by splitting alone. Most of the rest are groups whose readings are spread over many texts, or where the ा bar splits the vote (C11); they are left to the person reviewing.

**Screen check** (headless Chrome on a copy of the library): the suggestion chip, the badges on samples read otherwise (in g0009 they mark exactly the ना, मा and सा samples in a ता group), the readings of unsure samples, and the side panel.

## C12b. Fixing cuts with Tesseract's readings (2026-10-05)

**Setup:** a copy of the user's library, book 3 "Vachnamrut Printed 1933": 23 printed pages, 302 lines, 14,569 samples, 77 labelled groups, read with Tesseract (C11). Defaults: `recut_window` 0.3, `recut_min_width` 0.45, `recut_min_group` 5, `group_distance` 0.55.

**How often the cuts are wrong:** 1,325 of the 10,917 samples with a reading (12%) were read as 2 or 3 aksharas (अम, ईक, तेउ, णते, केव, रूप, वच): several letters left in one sample.

**Checking the new pieces:**
- **Reading each piece again with Tesseract** (single character, `--psm 10`, or single word, `--psm 8`) was tried first: only 16 of 120 sampled splits passed, although most cuts were in the right place. Tesseract cannot read one letter cut out of its word (क came back as ">", "|", "h"). Dropped.
- **By shape:** a piece is kept when its fingerprint is within `group_distance` of the centre of a group with ≥ 5 samples, and it is at least 0.45 x the line's median sample width. Of 1,384 split candidates, 874 passed before the width rule; by eye, about 9 of 12 random ones were right. The wrong ones cut a vowel bar off (क|ा) or cut through ॥: hence the width rule and splitting only samples of kind "letter".
- **Joins:** a first version joined any 2 or 3 samples inside one akshara: 511 joins, of which about half joined two real letters (हत, श्वेत, नेर, अन्य), because Tesseract's box of an akshara often reaches into the next letter. Now only a letter-sized sample with narrow fragments is joined: 126 joins, by eye about 26 of 30 right (रा, जी, आ, मां, तां, वि, थि, अं, लि, श्री).

**Result** (one run, 78 s): **725 samples split** into 1,460 new ones, **126 joined**, 706 candidates refused by the checks. For the new samples near a labelled group, their reading equals that group's label for 75% of the splits (481 of 638) and 70% of the joins (16 of 23), the same as for ordinary samples (C11: 75%), so the pieces behave like normal letters. The most common disagreements are look-alikes (ने / ते 29) and the ा bar (क / का 11).

**Vowel bars and placement (2026-10-06).** The user found that in g0004 of book 3, 28 samples read as आ were अ alone: Phase 1 had cut the ा bar off as a sample of its own (2 of 6 looked at) or joined it to the next letter (ावे, ागल, ाहार: 4 of 6). The join rule never saw these: Tesseract's box of the bar lies over the अ, so the alignment matched आ to the अ sample alone. Two more causes: आ ओ औ are characters of their own in Unicode, not अ + sign, so "ends in a bar sign" missed them.

- **Bar rule** (`left_bar`): the next sample starts with a tall stroke (ink in ≥ 60% of the rows below the headline, at most 0.35 letter widths) and a gap. First run on a fresh copy of the user's library (after the user's own Fix cuts run): 657 bars moved. By eye the new ता group then held ताथ, तात and ोता pieces: a letter that itself began with the previous letter's bar (ो|त), and bad pieces from the earlier run. Guards added: a letter that starts with a bar is left alone; the letter with its bar may be at most 0.6 letter widths wider than before; samples put into a new group must look alike (within `group_distance` of their own centre).
- **With the guards:** 586 bars moved, 43 more splits, 3 joins (67 s; the user's earlier run had done most splits). 705 of 1,258 new samples were placed by reading and shape, into 40 new groups (labelled, not reviewed). By eye the new आ (21), ता (45), ना (56) groups hold only that letter. In g0004, the samples read as आ went from 28 to 9, and जा from 18 to 5.

## C12c. Cutting by Tesseract's reading (2026-10-06)

**Asked for by the user:** offer cutting by Tesseract at capture, as an alternative to the shape cut (C3a, C3b), and see how accurate it is. Phase 1 still finds the lines; each line is cut into the aksharas Tesseract reads, at the least-ink column (headline rows left out) within 0.3 letter widths of its boundary. Cuts closer than `tesseract_cut_min_gap` (0.3) letter widths are not made.

**Three transcribed lines** (from C10): akshara counts, against the truth:

| Line | Truth | Cut by Tesseract | Cut by shapes |
|---|---|---|---|
| Untitled-15 L03 | 51 | 52 | 57 |
| Untitled-26 L05 | 52 | 50 | 46 |
| Untitled-41 L08 | 46 | 47 | 51 |

By eye on Untitled-41 L08: the Tesseract cut keeps the vowel bars on their letters (ता, रे, कां, के, ने) and the conjuncts whole (स्वा, क्त, श्री), but misses some boundaries (श्री | जि) and once made two cuts a few pixels apart (hence the minimum gap). The shape cut finds more boundaries but cuts bars off (क | ां, ह | ा) and conjuncts in two (स | ्वा).

**Whole books, both ways** (new scratch books from the same pages; the shape-cut book then read with Tesseract as in C11):

| | 7 pages: shapes | 7 pages: Tesseract | 23 pages: shapes | 23 pages: Tesseract |
|---|---|---|---|---|
| Time (cutting + reading) | 71 s | 87 s | 255 s | 234 s |
| Samples | 4,604 | 4,253 | 14,570 | 14,290 |
| Unsure | 688 | 563 | 2,145 | 1,995 |
| Groups | 253 | 200 | 531 | 399 |
| Groups ≥ 5 samples with a suggestion | 43 / 149 (29%) | 47 / 132 (36%) | 90 / 332 (27%) | 96 / 282 (34%) |
| Mixed groups (two strong readings) | 34 | 33 | 53 | 52 |
| Samples read as 2+ letters | 291 | 218 | 1,325 | 583 |

40 random samples of the 7-page books, by eye: about 30 clean single letters cut by Tesseract against about 26 cut by shapes. The Tesseract cut's errors are mostly two letters left together (सर्वे, नांव) where Tesseract's boundary was unclear, and a few vowel bars on the wrong letter.

**Labels at capture** (added the same day, asked for by the user): a new scratch book of the 23 pages cut by Tesseract got 77 labelled groups at capture (46 groups merged into them, 58 unsure samples placed): 24% of the 14,290 samples labelled without a step by the user. By eye the groups looked at are right (जे, इ; क्त mostly the क्त ligature, a few pieces with a stray dot or bar). The labelling itself takes about 4 s; the rest stay in mixed groups (no reading with 60% of the votes).

**Conclusion:** on print, cutting by Tesseract is better (less than half as many multi-letter samples, fewer groups, more suggestions, every sample read), but not by a wide margin, and the number of mixed groups is the same. It stays an option per book; the default remains the shape cut, which is the only one that works on handwriting. Fix cuts (C12b) can still be run after either cut.

## C12e. aa bars cut onto the next letter (2026-10-07)

**Reported by the user:** most wrong letters are words with the aa sign: નાર cut as ન + ાર. Words like રવિ must not become રા + વ.

**Seen on book 6** (a copy of the user's library, cut by Tesseract's reading): letters labelled र that hold ा + र (कार, खार, तार); the old bar check of Fix cuts (`recut.left_bar`) also flags plain र (its curve), so it could not be reused.

**The i sign** (ि of रवि) is the danger: a bar before its letter. In this print its hook does not touch the bar: 2 to 3 white rows lie between the hook and the headline, so "ink rising from the bar" misses it. What tells it: a wide mark above the headline starting over the bar. The e sign of the next letter (तारे) looks the same there; telling the two apart by the height of the mark's left end recovered 45 more aa bars but also took the broken hook of बुद्धि, so it was dropped: any wide mark over the bar leaves the letter alone.

| Rule (book 6, 14,141 letters) | Found | Right, of those looked at |
|---|---|---|
| Bar + gap + letter, no hook test | 248 | about half (the rest ि of रि, नि, वि) |
| + hook = ink rising from the bar | 214 | still many ि |
| + hook = a wide mark starting over the bar (kept) | 136 | about 38 of 40 |
| + the letter before has no bar of its own (kept) | 126 | the 10 left out follow ग, ण, श (a stem standing apart) and one double bar |
| e sign told from the i hook by its left end (dropped) | 181 | took the broken hook of बुद्धि |

**Fixing book 6** (`fix_bars` on a copy): 126 bars, 15 s; 171 of the 252 new letters went into groups by shape (वा 16, र 15, या 11, ना 10, ता 8 ...), 81 to Unsure. Undo and redo restore exactly; running it again finds 1. Book 3: 61, book 2: 65 (planned only).

**The e sign of the next letter** (2026-10-08, reported for ક્યારે): on a fresh copy of book 6 (already fixed once), 182 letters start with a bar but have a wide mark over it. By the height of the mark's left end above the headline: 37 high (read as रे 11, ने 6, ते 5, वे 4 ... but also वि, रि, द्दि), 145 low (नि 22, रि 21, वि 19, ति 11 ...: the i hook). Shape and reading together (left end high, read with े or ै and no ि): 32 letters, all right by eye, among them 5 ક્યારે. Book 3 (cut by shape, read by Tesseract): 228 plain bars + 20 under an e sign, 25 and 20 looked at, all right. (Book 3's earlier count of 61 was taken before the "letter before has a bar of its own" test was fixed.)

**The stem of ण** (2026-10-08, reported by the user): book 6 has 278 letters labelled or read ण; 172 hold their stem, 106 do not. Their stem went to the next letter (51, refused because of the stem's foot curling left, or because nothing followed it) or stood alone (52, often labelled ण itself). Allowing the foot and joining lone bars with a piece of headline: 76 joins and 26 moves on the book (with ग stems, ा and ो bars cut off the same way); 30 joins and 30 moves looked at: 2 joins were the ि of हि and रि, removed by the lean of the mark above (right: ि; left: ो); after that, all right. Applied on a copy: 102 fixes in 26 s, 76 letters fewer, undo and redo exact.

**A soft bar edge** (2026-10-08, the user's माटे samples 71215, 71071, 75571, 82356): each refused by "letter body left of the bar", which was the bar's own edge, one column with 14% to 64% ink. Letting any partly inked columns count as the edge found 499 more on book 6, many wrong (the loop of म, स, व taken as the edge); limited to two columns: 368, then 129 more at 10% ink. Of these, looked at with the cut drawn: nearly all right (ા bars, ો bars, the stems of ण, ग and श), and one wrong kind: a lone bar that is the ि of the next letter whose hook sits on that letter (ते|नि). Checking the next letter for an i hook without a bar of its own (shape, or Tesseract's ि) drops 18, mostly those ि and a few unclear ones. Book 6 now: 572 fixes, all 4 samples among them.

**The aa of a whole ण, ग, श** (2026-10-08): 17 letters on book 6 where the letter before is one of these with its stem, and the next starts with or is a bar. Read by Tesseract as णा/गा/शा: 15, all real; as ण/ग: 2, not (पण|काय, ग|ल्य). With the reading as the condition: 13 taken in one run, 2 more in a second run (their शा was itself changed by a fix next to it). Book 6: 583 fixes.

**Handwriting** (book 5): 22 found, about half wrong (the rule cut the left stroke of प, स and others). Left out: printed books only.

## Segmentation plan, stage 1: the reader on real windows (2026-10-11)

`docs/SEGMENTATION_PLAN.md`. Book 6, the 8,946 reviewed single-akshara letters of the 23 Training Data pages, each read by a reader trained without its page (4 folds by page, labels with 1 or more letters). A window is the letter box's columns of the whole line's ink (every sample of the line pasted together), so neighbours' overhanging marks are included.

| Training | Clean mask | Window, exact | Window shifted ≤ 10% | Window: common / middle / rare |
|---|---|---|---|---|
| As today (3–30 varied copies, more for rare labels) | 95.3% | 94.6% | 89.7% | 98.8 / 97.1 / 77.4% |
| 50 per label (50 spread over pages and lines; small groups filled with varied copies) | 95.3% | 94.7% | 87.1% | 97.5 / 97.5 / 80.7% |
| **Balanced weights** (all letters and copies, each label's total weight equal) | 95.6% | **94.9%** | 89.7% | 98.4 / 97.7 / 79.5% |

Bands by the label's letters: common 100+ (4,452 letters), middle 20–99 (2,973), rare 1–19 (1,521; 169 of them have a label found only on their own page, so the fold's reader cannot know it). Commonest window mistakes: ता→तां, मा→मां, ता→तो, अ→अं, र→रे (top marks). Gate (≥ 90% at exact boundaries): passed.

## Segmentation plan, stage 5: the second opinion in the app (2026-10-11)

Text → Whole lines → **Second opinion** (`app/linesearch.py`), on a copy of the library, book 6, page Untitled-15.jpg (13 lines, no checked lines on it):

| Step | Result |
|---|---|
| Learning the letters (first time) | 8,946 reviewed letters, 412 labels, 412 s (the test suite ran at the same time) |
| Reading the page | 84 s for 13 lines (6.5 s per line) |
| Marked uncertain | 73 of 651 aksharas (11.2%); on the 73 checked lines 19.4% |

Seen in the first three lines: marks on Tesseract's stray signs and doubled viramas (पोा, वार््ती) and on likely misreadings (दत्तांत, साहित, रहे, ते, थो); some marks are the line search's own mistakes (मां→ना, री→ले); a mistake both make is not marked (करयो). Next: check Read Book lines in Whole lines (✓ makes them checked lines) to measure the marks on Read Book pages.

## Segmentation plan, stage 5: a faster line search (2026-10-11)

`ocr/segment.py`, the stage-3 search as a module; the window features in one batch (`features_batch`, the same numbers, 0.76 -> 0.48 ms per window). Readers retrained per fold as in stage 3; settings bonus 4, language model 0.5, width 1.

| Variant | Lines | Wrong | Stage 3 on the same lines | Seconds per line | Windows | Kept |
|---|---|---|---|---|---|---|
| A boundary every 6 px | 18 (fold 0) | 10.21% | 9.56% | 19.9 | 14,422 | 14,422 |
| B every 9 px | 18 | 9.32% | 9.56% | 11.3 | 8,526 | 8,526 |
| C 6 px + windows under 5% dropped | 18 | 10.33% | 9.56% | 17.5 | 14,422 | 4,170 |
| **D 9 px + dropped** | **73** | **10.18%** | 11.11% | **6.6** | 7,632 | 2,345 |

Dropping windows saves little time (their features are still computed) but does not hurt; most of the time is the features. D is the default. A and stage 3 differ only by the readers' random training.

## Segmentation plan, stage 4: the line search as a second opinion (2026-10-11)

The 73 checked lines; Tesseract's whole-line reading (aksharas, confidences, alternatives) aligned with the stage-3 reading (settings from the other half of the pages) by akshara (difflib); the language model as in stage 3.

| | Characters wrong |
|---|---|
| Tesseract alone | 5.06% |
| Tesseract + language model | **4.45%** |
| Line search alone | 11.11% |
| Vote: the differing aligned stage-3 akshara as one more candidate (weight 0.25 / 0.5 / 1 / 2) | 5.78 / 6.25 / 6.62 / 7.01% |

**Uncertain marks** where the line search disagrees with Tesseract + language model: 19.4% of the aksharas marked, and 244 of the 277 aksharas still wrong (88%) among them. Tesseract alone marks 0.2% (its confidence stays high when it is wrong).

## Segmentation plan, stage 3: reading lines without Tesseract (2026-10-11)

The 73 checked lines; each line's ink is its Read Book samples pasted together (used only as ink). Windows between candidate boundaries, 0.2–2.4 × the typical letter width (54 px), read by the stage-2 reader (linear, labels + *not a letter*); beam search (beam 10, best 4 labels per window) scoring log p(label) + a bonus per letter (4) − a width penalty (log of width / the label's median width, σ 0.3) + 0.5 × the language model (word list + labels of the other pages). Folds of 2 pages; settings chosen on one half of the pages, scored on the other.

| Candidate boundaries | Characters wrong |
|---|---|
| Gaps and thin points below the headline only | 30.1% (197 unreadable stretches where letters touch) |
| **Every 6 px + gaps and thin points** | **11.1%** (halves: 10.2%, 11.7%) |

For comparison: Tesseract on whole lines 5.06%, + language model 4.45%; the letter route without Tesseract 27.7%.

## Segmentation plan, stage 2: a reader that knows "not a letter" (2026-10-11)

Same letters and folds as stage 1. Negatives made from the same lines (43,092): left and right halves, the letter with its right neighbour, windows shifted 25–45% of its width. One extra class *not a letter*; balanced weights per label.

| Training | Exact windows right | Shifted ≤ 10% right | Real called *not a letter* | Negatives called *not a letter* | Negatives called a letter ≥ 0.9 |
|---|---|---|---|---|---|
| Negatives weigh as much as all letters; clean masks + exact windows only | 88.6% | 69.8% | 6.4% | 98.7% | 0.6% |
| Negatives at 0.5 | 89.7% | 71.5% | 5.0% | 98.4% | 0.7% |
| Negatives at 0.25 | 89.8% | 72.1% | 4.1% | 98.3% | 0.9% |
| **Negatives at 0.25 + tolerance band** (windows shifted 3–10% and varied copies count as the letter) | **92.4%** | **87.0%** | 1.6% | 95.8% | **1.4%** |

With the band: common 95.9%, middle 96.5%, rare 74.3% (stage 1 without *not a letter*: 79.5%). Labels most often given confidently to wrong windows: व, र, त, प, म, न (simple shapes that halves of wider letters resemble). Gates (≥ 90%, < 5%): passed.

## Checked lines: every way of reading (2026-10-11)

**Truth:** 73 lines checked by hand in Line truth (8 Read Book pages of the printed 1933 book; 6,677 characters). The pages are also Training Data pages, so for the letter route the groups, the reader and the language model were rebuilt without the tested pages (4 folds of 2 pages) and the user's corrections were not used. CER = edit distance in code points, spaces and the border "|" left out. The truth was typed from Tesseract's whole-line reading, which slightly favours it.

| Way of reading | All 73 lines | 62 lines not in the word list |
|---|---|---|
| Tesseract, whole line (Otsu, unscaled, `script/Devanagari`, psm 7) | 5.06% | 4.92% |
| ... + language model (word list + labels of the other pages), weight 1, gain 3 | **4.45%** | **4.41%** |
| ... letters scaled to 36 px / grey, paper flattened / grey 36 px / psm 13 | 5.1 / 5.3 / 5.2 / 5.6% | |
| ... models mar / hin / san | 6.8 / 7.3 / 12.3% | |
| Letter route: Tesseract only | 6.14% | 6.02% |
| ... + groups | 6.07% | 5.89% |
| ... + groups + language model with word list | 5.39% | 5.31% |
| ... + reader + language model with word list | 7.47% | 7.51% |
| ... + reader | 8.94% | 8.66% |
| No Tesseract: groups + reader + language model with word list | 27.72% | 27.73% |
| No Tesseract: groups only | 36.86% | 36.46% |

Tesseract's commonest mistakes (whole lines): ल read as ळ (ळा->ला 9, ळे->छे, ळ->ल, ळि->लि), र्य read as रय (10), vowel signs (सा->स, ता->तो, पा->पो, न->ने, र->रे), म->भ, त्र->ब्र. The word list (a modern edition of the Vachanamrut, 5,546 lines, 113,527 aksharas) holds 14% of the checked text word for word.

## C15. The language model (2026-10-10)

**Measured** as the reader in conversion (book 6, 4 folds by page): each fold's model learned only from the label sequences of the other pages' lines (about 7,000 aksharas; stretches end at unlabelled letters), the readers too; after the production vote, each uncertain letter got candidates (Tesseract with its confidence, the reader's best three, the two nearest groups; weights 1, 1, 0.5) and `correct_line` chose.

| lm weight, min gain | Reviewed letters: CER, changed (fixed / broke) | All labelled letters: CER, changed (fixed / broke) |
|---|---|---|
| no language model | 9.80% | 8.34% |
| 0.5, 0 | 9.62%, 82 (42 / 17) | 7.15%, 522 (294 / 73) |
| 0.5, 3 | 9.20%, 33 (22 / 3) | 7.28%, 218 (163 / 8) |
| 1.0, 1 | 9.62%, 77 (37 / 15) | 6.83%, 502 (312 / 60) |
| **1.0, 3 (kept)** | **9.20%, 60 (30 / 9)** | **6.91%, 401 (266 / 34)** |
| 2.0, 3 | 9.86%, 71 (31 / 13) | 6.95%, 496 (304 / 61) |

On by default (`language_model`). **On the 3 Read Book pages** (model from the book's 9,636 labelled aksharas and 1 proofread line): 28 to 30 letters changed a page; of 32 looked at by eye, 17 fixed (ओआ->आ, नाम->म, यथा->था, पा->पो, त्र->ब्र...), 6 broken (सो->मां, छा->ला, गि->नि, a box of two letters read as a word label), the rest wrong either way. Converting 3 pages: 30 s (16 s without; the model is built once and kept). An imported full text of the book should help far more than 7,000 aksharas of labels.

## C14 in conversion: the letter reader as a reader of the text (2026-10-10)

**Measured** on book 6 (copy), its 23 training pages in 4 folds by page: each page read by a reader trained on the other pages (reviewed letters, labels with 5 or more) and by group centres without its letters; Tesseract's readings as in C16b (gap-filled). Truth: stretches of 3 or more letters in labelled groups.

| Rule | Reviewed letters (914): CER / letters wrong / marked / mistakes marked | All labelled letters (7,837): CER / marked / mistakes marked |
|---|---|---|
| Tesseract only | 10.8% / 14.1% / 0.1% / 1% | 8.8% / 0.2% / 2% |
| Tesseract + groups (C16b) | 10.4% / 13.3% / 13.0% / 69% | 8.5% / 11.7% / 67% |
| reader alone | 16.0% / 14.9% / 11.7% / 66% | |
| three readers vote (reader sure at 0.95) | 8.5% / 8.6% / 11.1% / 82% | 9.3% / **27.6%** / 79% |
| **vote, only on letters the reader was taught (built)** | **9.8%** / 12.4% / 10.9% / 69% | **8.3%** / 10.6% / 64% |

Thresholds 0.8 to 0.97 for the vote differ little (CER 9.1 to 8.4%). "Tesseract wins on labels the reader does not know" was worse (CER 10.0%: Tesseract often reads common letters as rare ones). The unreviewed labels came mostly from Tesseract, so the second column flatters Tesseract.

**Why the guard:** the reader learns only reviewed groups; on this book the म group (155 letters) and पा (39) were not reviewed, so the reader read every म as ग and every पा as या, at 99 to 100%. Without the guard, 40% of the Read Book letters were marked uncertain (239 of 608 on page 1).

**On the 3 Read Book pages** (no truth): uncertain letters 73 to 82 a page (Tesseract + groups) -> 93 to 98 (with the reader); 20 letters changed on page 1, by eye 9 fixed (त, जे, अ, उ, वृ...), about 6 broken (all on boxes holding two letters or a stray bar: र्म, नांव, ।जे), the rest wrong either way. Converting 3 pages: 16 s (was 18 s).

## C16b. Converting pages into text (2026-10-10)

**Data:** a copy of the user's library, book 6 (printed, cut by Tesseract's reading): 3 Read Book pages from a PDF (1,826 letters), and 8 training pages with the user's reviewed labels as the truth.

**Uncertain letters on the Read Book pages:** marking every disagreement between Tesseract and the nearest labelled group made 369 letters (20%) uncertain; 353 of them were disagreements, 16 a group too far with no Tesseract reading. Looking at 24 disagreements: Tesseract right about 12 times, the group about 6, neither about 5; when Tesseract was at least 95 sure and the group further than 0.45, Tesseract was right 10 of 11 times. Leaving those certain:

| A disagreement is uncertain when the group is within | Uncertain letters |
|---|---|
| (always) | 369 (20%) |
| 0.50 or Tesseract below 95 | 307 (17%) |
| **0.45 or Tesseract below 95 (kept)** | 244 (13%) |
| 0.40 or Tesseract below 95 | 184 (10%) |

**Tesseract alone on reviewed letters** (8 training pages, 1,577 letters whose group is reviewed; the groups' second opinion left out, since a training letter would vote for its own group): 1,331 right (84.4%). Of the 246 mistakes, 66 are marked uncertain and 180 are confident: the groups and the letter reader (C14) are needed to catch those. Most common: letters the alignment could not place (shown as ?), extra aksharas on ण (हण, रण, पण), जे read as ज, क as का (C14's note), छे as ळे or ठे.

**Speed:** about 6 s a page (13 lines read by Tesseract, 3 at a time on the development laptop).

**Whole page, line text, or letters?** (asked by the user, 2026-10-10). No training page has every letter reviewed yet, so the truth is every stretch of 3 or more reviewed letters in a row: 259 stretches, 1,684 characters, on all 23 training pages. Tesseract only, no groups; character error rate (CER):

| How Tesseract's reading becomes text | CER |
|---|---|
| (d) the whole page (Tesseract finds the lines itself, mode 3 / mode 6) | 17.7% / 17.4% |
| (a) each line image, Tesseract's text as it is | 16.4% |
| (b) each line image, its aksharas put on the cut letters (C11's alignment) | 13.1% |
| **(c) as (b), and letters the alignment cannot place take Tesseract's characters over them (kept)** | **10.8%** |

(a) and (d) are scored on the characters whose boxes fall inside each stretch, so a character at a stretch's edge can be counted wrongly: they lose a little to that, but not 6 points. The whole page is faster (about 3 s a page) but worse: on these slanted, close-set pages the app's own line finding gives Tesseract cleaner lines. (c) filled a gap in 30 of the 259 stretches.

**Tesseract's confidence does not mark its mistakes:** on the 3 Read Book pages, "Tesseract only" marks 8 of 1,826 letters uncertain (0.4%), although about 1 character in 6 is wrong; with the groups' second opinion, 237 (13%). The marks come from the groups, as C10 found for handwriting.

## C14. The letter reader (2026-10-10)

**Data:** a copy of the user's library, book 6 (printed): the 4,091 letters of reviewed groups, 4,040 of them single letters (not words); 93 labels with at least 5 letters (3,780 letters), 146 labels with fewer (left out by default). Test pages: 3 of 23 (535 letters); validation pages: 2.

| Reader (shape features: 20 x 20 image, HOG on 40 px, size) | Test letters right | Labels with 20+ letters |
|---|---|---|
| **linear (kept: better on validation)** | **96.1 to 96.4%** | **96.8 to 97.2%** |
| network, one hidden layer of 384 | 95.3% | |
| Tesseract on the same letters (C16b) | 84.4% | |

Letters read with at least 90% probability: 96% of all, and 98.1% of them right. Most confused: अ/अं, था/या, सा/ता. Worst labels on the test pages: सा 78% (9 letters), की 80% (5), ए 83% (6), का 88% (8). The test letters are cleanly cut (they are in reviewed groups); on Read Book pages with cutting mistakes the reader will do worse.

**Time:** the whole training in the app 77 s (296 s before the features were computed once); reading all 13,952 letters of the book 44 s.

**"Check these":** 23 letters read as another label with at least 90% probability (each by a reader that did not learn from its page), all in reviewed groups. By eye about 18 are real mistakes in the groups (for example था letters in the या group, letters whose group label lacks their ं) and the rest false alarms.

**Cutting by matching the groups** (the user's idea, 2026-10-10; a prototype, not in the app): every line cut at candidate points, every run of 1 to 4 pieces scored by its distance to the nearest labelled group centre, the cheapest sequence chosen, "ask the user" where nothing matches. On the reviewed characters: 70% CER with cuts at the gaps of the letter bodies, 89% with cuts at the stroke pieces, against 10.8% for Tesseract with gaps filled. Fingerprints cannot tell half a letter or two letters from a letter. To be tried again with the letter reader trained with "not a letter" examples.

## C13. Suggestions from other labelled books (2026-10-06)

**No handwritten book is labelled yet**, so the plan's measurement (two handwritten pages, one suggesting the other) waits for the user's labels. Measured on print instead, on a copy of the user's library: book 3 "Vachnamrut Printed 1933" (cut by shapes, 82 labelled groups) suggests for book 4 "Vachnamrut Printed 1933 Tesseract Cuts" (the same 23 pages cut by Tesseract and grouped on their own; its labels reviewed by the user are the truth). Since the two books share pages, the reference centres are built only from book 3's samples on half of the pages, and only book 4's samples on the other half are judged (both ways round).

**Within one book** (book 3, its own labelled groups split by page) every reading was right: a sample lies near the centre of its own group almost by definition. This is not a fair test, and is not used.

**Across the two books** (book 4's groups labelled or reviewed by the user are judged; those labelled at capture are left out):

| Distance limit | k | Samples read | Of them right | Groups right / wrong / none (both halves) |
|---|---|---|---|---|
| 0.40 | 5 | 902 + 966 | 93% | 29 / 1 / 43, 28 / 1 / 44 |
| 0.45 | 1 to 9 | 1,078 + 1,174 | 90% | 30 / 1 / 42, 29 / 1 / 43 |
| **0.50** | 5 | 1,214 + 1,312 | 89% | **31 / 1 / 41, 30 / 1 / 42** |
| 0.55 (`group_distance`) | 1 to 9 | 1,305 + 1,380 | 86 to 87% | 31 / 5 / 37, 30 / 4 / 39 |

The number of voting groups (k) makes no difference: within the distance limit there is usually only one labelled group. The limit does: 0.55, the grouping distance, adds 4 wrong suggestions for 1 more right. **`books_distance` = 0.5.** Wrong readings are look-alikes (ते / ने, रि / वि, स / र). About half of the target groups get no suggestion: their letter is not labelled in the reference half, or too few of their samples were read.

**The real job** on the copy, book 4 from books 1 and 3 (109 reference groups): 3.2 s for 14,302 samples; 5,513 read; 47 groups with a suggestion. Against book 4's 114 labelled groups (with the 37 labelled at capture): 42 of 48 suggestions right; wrong pairs व / य, ते / ने, वे / ने, बा / वा, बे / ने. (Inflated: the books share pages; the page-split numbers above are the fair ones.)

## C12d. Groups that mix two letters (2026-10-06)

**Reported by the user** on book 3 "Vachnamrut Printed 1933": g0001 read as ने 351, ते 152, मे 20; g0002 as न 105, ना 70, म 57; g0003 as प 92, व 36, वा 26. The user asked to tell these letters apart at grouping, for handwriting too, without splitting one letter into several groups by its strokes.

**What the mixing is**, by looking at the samples: the ते in g0001, the म in g0002 and the व in g0003 really are those letters: grouping errors. The ना in g0002 are न: Tesseract read the ा bar that Phase 1 had cut onto the next letter. Reading errors, not grouping errors.

**Data:** the masks of book 3's 11,646 letters with a Tesseract reading (and, for a first look, the 2,341 read as one of the 9 letters above, with ना → न and वा → व, since those readings are mostly न and व). Readings are an imperfect truth (C11: about 90% right on print), so purity numbers are low and only comparisons count.

**The fingerprint is not the weak part.** On the 9 letters, a sample's nearest neighbour has its reading in 91% of cases with the current fingerprint (48 px, 24 px pixels, HOG 6 x 6) and with every variant tried (32 px pixels, HOG 8 x 8, 64 px / 32 px / HOG 8 x 8, less blur, more HOG weight, loop features): 90.8 to 91.8%. The groups mix because the grouping radius (0.55) is wide enough to hold ने and ते together.

**Approaches tried and dropped:**
- **A smaller grouping distance:** at 0.40 the 9 letters' groups are 95% pure, but 530 groups instead of 187, most of them tiny.
- **Splitting groups in two by shape** (2-means, halves ≥ 10 samples and ≥ 0.25 apart): the 9 letters went from 73% to 90% purity with 24 more groups, but on the whole book 41 of the 96 candidate splits divided one letter by stroke weight or slant (क | क, त | त, प | प, र | र, छे | छे, seen by eye). Gap and spread tests did not separate these from real splits. This is the over-splitting the user asked to avoid.
- **Even strokes** (thinned to a skeleton, thickened to one width, so stroke weight cannot matter): at the same number of groups no purer (53.0% against 52.9%), and each common letter kept only 57% of its samples in its largest group instead of 89%.

**Splitting by reading, checked by shape** (kept): in a group, the samples read as another letter than the main reading form a candidate; its shape centre is compared with the main reading's. Over all groups of book 3 (sub-reading with ≥ 5 samples and 10% of its group), the distances fall in two clear bands: misreadings of the same shape are close (न / ना 0.10, त / ता 0.06, क / का 0.07, प / पा 0.10, अ / आ 0.12, व / वा 0.16, at most 0.22), real different letters far (ने / ते 0.32, न / म 0.36, नि / ति 0.31, य / व 0.41, ह / इ 0.46, भ / ध 0.48, अ / ज 0.49). **`split_distance` = 0.25** lies in the gap; one real pair below it (वे / बे 0.23) stays together, the safe side. A group with one reading is never split, however varied its strokes.

| Book 3, all 11,646 read letters | Groups (≥ 5) | Purity | Mixed groups (≥ 5) |
|---|---|---|---|
| Current grouping | 252 | 52.9% | 46 |
| Split by shape (dropped) | 388 | 59.7% | 73 |
| **Split by reading, shape-checked** | 333 | **63.8%** | **28** |
| The 9 confusable letters | 190 → 200 groups | 72.6% → 92.3% | |

**On the real book** (a copy of the user's library, `split_mixed`): 81 groups split, 1,115 letters moved. g0001 lost its 152 ते (ने 351 and 20 मे stay: too few to leave); g0002 lost its 57 म and 34 मा, and kept its 70 ना, which are misread न; g0003 lost its 36 व and 26 वा, and kept 23 पा (misreadings).

**Handwriting** (no labels yet): the two handwritten sample pages read with Tesseract, the noisiest reader (about a third wrong, C10): one split in 854 letters, 6 त-shaped letters out of a group that mixed त and न. The shape check keeps reading noise from splitting groups. With the labelled-books reader (C13) the same rule applies on handwriting.

## Whole lines (our reader): the fold-fair Measure in the app (2026-10-12)

Text → Whole lines (our reader) → **Measure** (`linesearch.measure`) on a copy of the library, book 6, after the user's group cleanup. The 8 pages with checked lines in 4 folds of 2; for each, the reader and the language model trained without them (word lists kept). 42 minutes.

| Fold | Pages left out | Letters trained on | Minutes |
|---|---|---|---|
| 1 | Untitled-15, 28 | 8,048 | 13.4 |
| 2 | Untitled-16, 33 | 8,095 | 10.9 |
| 3 | Untitled-26, 41 | 8,219 | 9.1 |
| 4 | Untitled-27, 51 | 8,132 | 8.9 |

| On 73 checked lines (6,675 characters) | Characters wrong |
|---|---|
| Our reader (line search), fold-fair | **9.99%** |
| Tesseract, whole lines | 5.03% |
| Tesseract + language model (the model knows every page) | 4.12% |

Marks where our reader differs from Tesseract + language model: **15.6%** of the aksharas, **215 of 255 (84%)** of the remaining mistakes (stage 4: 19.4%, 244 of 277). The cleanup changed our reader little (stage 5: 10.18%).

## Page borders at the line edges (2026-10-12)

Seen by the user: both readers read the page border (Untitled-51, 52; a few lines of 53, 65, 66). Edge pieces of all 299 Read Book lines of book 6, by what Tesseract read there: 44 border edges (`|`, `!`), 4 danda edges, 550 others. Border pieces: 1–22 px wide, 74–147 px tall (letters: median 67), broken (40–85% of their height inked), 9–13 px from the text. ॥: 28–35 × 52–59 px, solid.

| Rule (`segment.clear_borders`) | Border edges cleared | Danda edges touched | Other edges touched |
|---|---|---|---|
| outermost piece only, ≤ 0.2 × letter width, tall or broken | 20 of 44 | 0 | 5 (right borders) |
| pieces peeled one by one, ≤ 0.45 ×, taller than letters / broken and out of the band / specks | **36 of 44** | **0** | 11 (specks, right borders; checked by eye) |

The 8 border edges left have no border in our reader's ink (the cut letters left it out). Re-reading Untitled-51 and 52 (26 lines, the current reader): **12.6% → 7.5%** of the characters wrong against the checked text (11 lines) or Tesseract's text without `|` (15 lines).

## Learning from corrections (2026-10-12)

Fold-fair, 4 folds by page, on 99 checked lines (8,961 characters; the user corrected Untitled-52 and 53, 26 lines). A harness caches each fold's training windows and the windows of its checked lines, so readers and settings are tried without recomputing features. ZWNJ / ZWJ are left out of the scoring from here on (typed text has them, no reader writes them: 3 false errors).

| Our reader | Characters wrong | New pages (52, 53) |
|---|---|---|
| linear, 15 epochs (as built) | 8.38% | 4.89% |
| linear, 40 epochs | 8.14% | 4.24% |
| one hidden layer (384), 15 epochs | 7.52% | 5.11% |
| **linear, 40 epochs, learning from the other folds' checked lines** | **7.32%** | **3.93%** |
| Tesseract (whole lines) | 4.69% | 3.80% |
| Tesseract + language model (knows every page) | 3.78% | — |

Why the reader lagged: 2.8% of the checked aksharas had no class (हे: its group not reviewed and its letters not on a line; क्ष्मी, त्सं, र्ष, र्ण, ई…); बा→वा, the most common confusion, came from ब / बा letters inside the व / वा groups (195 वा letters against 1 बा). Learning from corrections: each checked line cut into the aksharas of its text (`segment.align`), its windows added as examples (3,235–4,096 letters per fold, 33–45 new labels). Left: vowel signs (नी→नो 6, र→रे, री→रो, ती→तो, पा→पो), a few ब→व.

## Language model weight, neural network, close-ups of the marks (2026-10-13)

Same harness and lines as above (fold-fair, 99 checked lines), the reader learning from the other folds' corrections.

| Variant | Characters wrong | New pages (52, 53) |
|---|---|---|
| linear, 40 epochs, language model 0 (off) | 16.38% | 13.23% |
| linear, 40 epochs, language model 0.25 | 7.31% | 3.93% |
| **linear, 40 epochs, language model 0.35** | **6.86%** | **3.76%** |
| linear, 40 epochs, language model 0.5 (in the app) | 7.32% | 3.93% |
| linear, 40 epochs, language model 1 / 1.5 / 2 / 3 | 9.36 / 11.34 / 12.97 / 16.38% | 4.72 / 5.50 / 6.59 / 8.30% |
| one hidden layer (384), 20 epochs, language model 0.5 / 1 / 1.5 / 2 | 7.50 / 7.88 / 8.68 / 9.98% | 4.32 / 4.59 / 4.59 / 5.37% |
| linear + close-ups (top 35% and bottom 30% of the window at 16 × 8, its right 35% at 8 × 16: 384 more numbers), language model 0.25 / 0.5 | 8.43 / 7.96% | 5.55 / 5.15% |
| Tesseract | 4.69% | 3.80% |

The language model is needed (off: 16%) but overrules clear letters above 0.5; the curve between 0.25 and 0.5 is uneven (one character in 2,200 on the new pages separates 3.76% from 3.80%), so 0.35 is to be confirmed with more lines. The network and the close-ups do not help. The remaining errors are vowel signs: `SPLIT_READING_PLAN.md` (parked) describes reading the base and the marks separately.

## Pages at another scale: photos of cards (2026-10-13)

Book 6, Read Book pages `WhatsApp Image 2026-10-13 at 8.30.59 PM.jpeg` (line spacing 45) and `8.31.19 PM.jpeg` (41): letters about 25-29 px high against about 67 px on the training pages (spacing 106). Both are photos of the same card, so the first three lines have the same text. Scored on the 7 hand-checked lines (4 + 3), the reader trained **without both pages** (letters, corrections and language-model text left out; one copy of the library, one seed, language model on), ink not rescaled vs. rescaled to the training spacing:

| Line | chars | before (no scale) | after (page scale) | Tesseract |
|---|---|---|---|---|
| 8.30.59 line 1 | 99 | 83 | 16 | 9 |
| 8.30.59 line 2 | 93 | 75 | 7 | 8 |
| 8.30.59 line 3 | 92 | 71 | 9 | 6 |
| 8.30.59 line 4 | 88 | 70 | 10 | 11 |
| 8.31.19 line 1 | 99 | 82 | 10 | 8 |
| 8.31.19 line 2 | 93 | 75 | 9 | 5 |
| 8.31.19 line 3 | 92 | 72 | 9 | 9 |
| **all 7** | 656 | **80.5%** wrong | **10.7%** wrong | **8.5%** wrong |

Only 7 lines of one card and one seed, but the gain is far beyond the ±1 point of a run. The remaining gap to Tesseract (2 points) is not shown to be real at this size. Pages near the training spacing (105-107, all other pages of the book) are read exactly as before (factor 1; unit test). Not measured: the 99 older checked lines again (their pages are not rescaled, so unchanged by construction); handwritten books (their training pages' spacing is 112; a page within 20% is not rescaled).

## Letters on no line: System generated letters (2026-10-13)

Our reader learned only letters on a line (it cuts each letter's window from its line), so the System generated groups (letters made from parts of other letters, on no page) were left out. Now a reviewed letter on no line is learned from its picture and its varied copies (no "not a letter" pieces). A fresh copy of the library (after the user's व / वा cleanup; 17 reviewed generated groups with 99 letters, 110 unreviewed with 658), fold-fair, 99 checked lines, learning from corrections:

| Our reader | Language model 0.35 | 0.5 | New pages (0.5) |
|---|---|---|---|
| without letters on no line | 7.62% | 7.88% | 5.33% |
| **+ reviewed generated letters** (in the app) | 7.00% | **6.94%** | **4.15%** |
| + all generated letters, reviewed or not | 7.04% | 6.97% | 4.37% |
| Tesseract | 4.69% | | 3.80% |

**Corrected the same day: these are single runs, and a run moves by up to about 1 point by chance.** The same variants with other random seeds (`LetterReader` start and training order; `tools/harness/run.py --seed`), language model 0.5:

| Seed | Copy of 2026-10-12, without letters on no line | Fresh copy, without | Fresh copy, + reviewed generated letters |
|---|---|---|---|
| 0 | 7.32% | 7.88% | 6.94% |
| 1 | 7.23% | 7.03% | 7.08% |
| 2 | 7.58% | 6.87% | 7.67% |
| **average** | **7.38%** | **7.26%** | **7.23%** |

- The reviewed generated letters have **no measurable effect** (7.26% against 7.23%). They stay in the training: no harm, and a reviewed group of even one letter must be usable.
- The "drop" between the two copies was one unlucky run: the 99 checked lines are identical in both (ink and text); the training letters differ by about 20 per fold (the user's व / वा cleanup), and on average the fresh copy is slightly better.
- The language model weights 0.35 and 0.5 (and the earlier single-run comparisons of about half a point) are within this noise: the app stays at 0.5.
- From now on: compare a variant over at least three seeds, and trust only differences clearly larger than about 1 point.

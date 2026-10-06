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

**Conclusion:** on print, cutting by Tesseract is better (less than half as many multi-letter samples, fewer groups, more suggestions, every sample read), but not by a wide margin, and the number of mixed groups is the same. It stays an option per book; the default remains the shape cut, which is the only one that works on handwriting. Fix cuts (C12b) can still be run after either cut.

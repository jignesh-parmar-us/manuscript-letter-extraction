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

**Handwriting** (book 5): 22 found, about half wrong (the rule cut the left stroke of प, स and others). Left out: printed books only.

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

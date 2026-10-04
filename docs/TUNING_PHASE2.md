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

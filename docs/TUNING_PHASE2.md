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

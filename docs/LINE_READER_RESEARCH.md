# Reading whole lines without feeding glyphs (research, 2026-10-19)

Brainstorm only. No code changed.

## 1. The problem

Today a new book needs about a week of glyph work: cut letters, group them, label every group.
The goal: **teach a reader from lines of text instead of from single letters.**

| Today (letter route) | Wanted (line route) |
|---|---|
| Cut the line into pieces, label each piece | Give a line picture and its typed text, nothing more |
| `[શ્રી] [ગ] [ણે] [શા] [ય]` → 5 labels to make | picture of the line + `શ્રી ગણેશાય નમઃ` → 1 typed line |
| A wrong cut means a wrong letter | No cuts, so no cut mistakes |

## 2. How a line reader works without cuts (CNN-LSTM-CTC, also called CRNN)

1. A **CNN** looks at the line picture in thin vertical slices (say 200 slices).
2. An **LSTM** reads the slices left to right (and right to left), so each slice knows its neighbours.
3. **CTC** gives every slice a letter or "blank" (`-`), then joins repeats and drops blanks:

```
slices : શ શ - ્ર ્ર ી - ગ ગ - ણ ે - શ ા ા - ય
result : શ્રી ગણેશાય
```

During training CTC finds by itself which slices belong to which letter. That is why only the typed line
is needed, never the letter boxes.

Almost every modern option in the list is this same idea in a different package:

| Name in the list | What it really is |
|---|---|
| CNN-LSTM-CTC / CRNN | The method itself (above) |
| Synthetic CRNN/CTC | The same, trained on lines **we render** from fonts and text |
| Tesseract 4/5 | Already a CNN-LSTM-CTC line reader. It can be **fine-tuned** (`tesstrain`) |
| Kraken | A ready CNN-LSTM-CTC tool for manuscripts; also finds lines as polygons |
| PyLaia | The same kind of tool as Kraken, for handwriting; fewer helpers around it |
| Polygon tracing (no cuts) | Finding each **line** as a shape (Kraken does this). It still needs a line reader after it |
| TrOCR (Hugging Face) | A big transformer line reader. Strong, but heavy and trained mostly on English |
| Spatial Graph Reassembly | Joining broken pieces (fragments, strokes) by position. Not a reader; it does not remove the glyph work |

## 3. Where the training lines come from

No glyphs, but the reader still needs lines with their text. Three sources:

1. **Line truth we already have** (Read Book → Line truth). Every checked line is a training line.
2. **Correct, don't type:** the current reader reads a page, you fix the mistakes in the text (about 30 s a
   line instead of labelling letters). Train again, read the next pages, fix fewer mistakes each round.
3. **Synthetic lines (printed books):** take Gujarati / Devanagari text, render it with similar fonts
   (also the fonts from Font Maker), add noise, blur, slant and faded ink. Thousands of lines in minutes.
   Example: the text `ભગવાન શ્રીકૃષ્ણ બોલ્યા` rendered in 5 fonts × 4 noise levels = 20 training lines.
   For handwriting synthetic lines help less; there real corrected lines matter most.

Rough sizes (from what is usually reported, to be measured here):
- Fine-tuning an existing model: **100–300 lines** of the book already help.
- Training from zero: **a few thousand lines**, so only with synthetic lines.

## 4. The options, compared for this repo

Limit to remember: on this Intel Mac with Python 3.14, PyTorch does not install (that is why the letter
reader is written in NumPy). Kraken, PyLaia and TrOCR all need PyTorch, so they need a **separate Python
(3.11) environment** or a cloud computer (e.g. Colab with a GPU) for training.

| Option | Needs PyTorch | Printed | Handwritten | Work to try | Verdict |
|---|---|---|---|---|---|
| **A. Fine-tune Tesseract** on line truth + synthetic lines | No | Good | Fair | Small (1–2 days) | **Try first** |
| **B. Kraken** in its own environment | Yes | Good | **Good** | Medium (2–4 days) | **Try second**, mainly for handwriting |
| C. PyLaia | Yes | Good | Good | Medium | Same as Kraken with fewer helpers; skip unless Kraken fails |
| D. Own CRNN in NumPy | No | ? | ? | Large (weeks; CTC and LSTM by hand, slow on CPU) | Skip |
| E. TrOCR | Yes, and a GPU | Good after much training | Good after much training | Large | Skip for now |
| F. Spatial Graph Reassembly | – | – | – | – | Not a reader; skip |

### A. Fine-tune Tesseract (no new install)
- `tesstrain` takes pairs `line.png` + `line.gt.txt`. We already export `lines/*.png` + `.txt`.
- Start from `guj` (or `script/Gujarati`, `script/Devanagari`) and train on the book's lines.
- Example: Tesseract reads `ગણેસાય`; after training on 200 lines of this book it learns `ગણેશાય`.
- Runs on the Mac's CPU. The "Whole lines (Tesseract)" route stays the same; only the model file changes.

### B. Kraken (best fit for manuscripts)
- `ketos train` on the same line pairs; `kraken segment` finds lines as polygons (handy for slanted or
  wavy handwritten lines, where today's line cutting struggles).
- Install: a new venv with Python 3.11 and CPU PyTorch, called from the app as a separate program
  (like Tesseract is today), so the main app keeps Python 3.14.
- Training on CPU: hours for a few hundred lines; minutes on a cloud GPU.

**Does every book need hours of training? No.** The long training happens once:

1. **Base model, once (hours).** Train one Gujarati/Devanagari model on all books' line truth plus
   synthetic lines (overnight on the CPU, or minutes on a cloud GPU). Kraken also has some ready
   Devanagari models that might serve as the start; to be checked.
2. **Each new book, a short fine-tune.** Start from the base model and train on 100–300 corrected lines of
   the book: likely tens of minutes to about an hour on the CPU, in the background while you keep correcting.
   Example: a printed book in a font close to one already learned may need only 50 lines; a new
   handwriting style needs more lines and a longer run.
3. **Sometimes no training.** A printed book in a known font can be read straight away; fine-tune only if
   there are too many mistakes.

| Step | How often | Rough time (CPU) |
|---|---|---|
| Base model | Once (again now and then, when many new books are added) | Hours |
| Fine-tune for a book | Once per book, or skipped | Tens of minutes to ~1 hour |
| Correct–retrain rounds | 2–3 times per book | A short run each |
| Reading pages | Every page | Seconds |

These times are usual reports, not measured here; the first trial on one book gives the real numbers.

## 5. Things to decide

1. **Fairness rule.** A line reader learns from real lines, so common letters are seen more often. The
   rule says letter frequency belongs only in the language model. Options: accept it for the line reader,
   or balance with synthetic lines that are rich in rare letters (e.g. lines full of `ઋ`, `ૠ`, `ઙ`, `ક્ષ્મ`).
2. **Where the glyph work still helps.** Cut letters stay useful for Font Maker and for highlighting
   letters on the page; they are no longer needed for reading.
3. **How to judge.** As always: on hand-checked Line truth, fold-fair (leave out the tested pages),
   before/after numbers and a line-by-line page. Check one printed and one handwritten book.

## 6. Suggested order

1. **Tesseract fine-tune** on the 1933 printed book's line truth (+ synthetic lines). Compare with today's
   Tesseract and our reader on the same checked lines.
2. **Kraken** in its own environment on one handwritten book, same comparison.
3. If either clearly wins, make it a choice in Reading setup, and change "Training Data" for a new book
   from "label letters" to "correct lines".

Expected gain in effort: from about a week of glyph labelling to about **1–2 days of correcting lines**
per new book, less for a printed book that synthetic lines cover well.

## 7. Idea: place the glyphs along the line (template matching)

Instead of asking "what letter is this window?", ask **"does the glyph `वा` fit here?"**: slide each
letter's glyph along the ink (blank space skipped), keep every good fit, and let the search and the
language model pick the best line, as today.

**The `व` inside `वा` problem.** `व` fits inside `वा`. So a fit must explain *all* the ink:
- glyph ink with no page ink under it costs points,
- page ink that no glyph covers costs points.

| Way (word `भगवान`) | What happens to the ink | Result |
|---|---|---|
| `भ` · `ग` · `वा` · `न` | All ink covered, nothing extra | **Best** |
| `भ` · `ग` · `व` · `न` | The `ा` stroke is left uncovered | Loses points |
| `भ` · `ग` · `व` · `ा` · `न` | `ा` alone is not an akshara | Not allowed |

**What it would do better.** Glyphs are matched at full size, so the small marks of `नी`/`नो`, `री`/`रो`
are not lost in a 20 × 20 picture. In a printed book every `ग` looks the same, so one or a few glyphs
per letter fit well. The glyphs could come from Font Maker.

**Where it is weak.** Handwriting (every `ग` differs), thick or faded ink, size changes, and speed
(about 400 labels × positions). It still needs the glyphs, so it does not remove the glyph work.

### What the research numbers say

Lower is better. CER = characters wrong, WER = words wrong.

| Study | Books | Tesseract | Other | Template / line reader |
|---|---|---|---|---|
| Ocular, Berg-Kirkpatrick et al. 2013 (glyph fitting + language model) | Old Bailey, English, 1715–1905 | CER 29.6%, WER 54.8% | ABBYY: 15.1%, 40.0% | **CER 9.7%, WER 24.1%** |
| same | Trove, Australian newspapers, 1800s | CER 37.5%, WER 59.3% | ABBYY: 22.9%, 49.2% | **CER 14.9%, WER 33.0%** |
| Mathew et al. (IIIT Hyderabad, "Towards Deployable OCR models for Indic languages") | Printed **Gujarati** | CER 3.1% | Google: 4.8% | CRNN line reader: **2.3%** |
| same | Printed **Hindi** | CER 5.0% | Google: 2.7% | CRNN line reader: **2.0%** |

What this means for us:
- **Ocular is the strongest case for your idea.** It fits glyph shapes along the line with a language
  model, much like your idea, and on old, uneven print it made about a third of Tesseract's character
  mistakes (9.7% against 29.6%).
  It needed **no labelled letters**: it started from ordinary computer fonts and learned the book's own
  shapes by itself. But the tests were on English (26 letters). On Gujarati / Devanagari there are
  hundreds of aksharas and letters joined by the headline, which is much harder. No numbers found for that.
- **Old-style template matching on Indian scripts** (the 1970–2000 systems) is described in reviews as
  very sensitive to noise and changes of shape. No fair comparison with Tesseract was found.
- **Line readers (CRNN/CTC)** beat Tesseract on printed Gujarati and Hindi, but they were trained on a large
  set (about 8,600 Gujarati lines).
- **For our book:** Tesseract 4.7%, our reader 7.3% (section 5 of `OUR_READER.md`). Studies on other
  books can't tell us which would win here. Only a test on our checked lines can.

### What Ocular is

A program for reading **old printed books**, made at UC Berkeley (Berg-Kirkpatrick, Durrett, Klein, 2013).
Instead of learning "what does this picture say?", it imagines **how a printer would have printed the
text**, and looks for the text whose imagined print looks most like the real page.

How it imagines printing (like a printing press with metal letters):
1. **Text:** a language model suggests likely text, e.g. `भगवान`.
2. **Letter shapes:** each letter has its glyph in this book's font.
3. **Spacing:** a little space left and right of each letter.
4. **Wobble:** a letter may sit a little higher or lower.
5. **Ink:** a letter may be printed a bit too dark or too light.

It draws this "fake print", compares it pixel by pixel with the page, and the best-fitting text wins.

How it learns the book's font **without labelled letters**:
1. Start from ordinary computer fonts (in the paper: the standard Ubuntu fonts).
2. Read the book with them; many letters are wrong, the language model fixes some.
3. Take every place read as `ग` and redraw the `ग` shape to fit those places better.
4. Read again with the better shapes; repeat. After a few rounds the glyphs look like the book's font.

Limits for us: built for printed Latin letters (English, later other European languages); no Gujarati or
Devanagari version known. It places each letter as a separate block, while our letters are joined by the
headline and form hundreds of aksharas. Printed books only: handwriting is not "the same metal letter
every time". The code is open source (Java), believed to be at `github.com/tberg12/ocular` (not checked).

**What we could borrow** (not Ocular itself): start from Font Maker's glyphs or a similar Gujarati /
Devanagari font, read the book with our search and language model, redraw each glyph from where it was
read, and repeat. For printed books this could turn "label every letter" into "check the glyphs after a
few rounds".

**Verdict:** for printed books it is worth a small test, as **a fourth check in today's search**
("how well does the glyph explain the ink"), not a new reader. Test it on the 99 checked lines, fold-fair,
over a few random starts. Then try one handwritten book, where I expect it to help less.

Sources: Berg-Kirkpatrick, Durrett, Klein, *Unsupervised Transcription of Historical Documents*, ACL 2013,
Table 1 (https://www.cs.utexas.edu/~gdurrett/papers/berg-durrett-klein-acl2013.pdf); Mathew, Mondal,
Jawahar, *Towards Deployable OCR models for Indic languages*, Table 4 (https://arxiv.org/pdf/2205.06740);
review of Devanagari recognition (https://arxiv.org/pdf/1101.2491).

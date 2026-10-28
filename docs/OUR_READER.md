# How our reader works (simple explanation, 2026-10-19)

The app's own reader: **Read Book → Text → Whole lines (our reader)**. Code: `ocr/segment.py` (the line
search), `ocr/reader.py` (the letter reader), `ocr/language.py` (the language model). The full help page is
`docs/help/our-reader.html`; the measurements are in `docs/plans/done/SEGMENTATION_PLAN.md` and `docs/TUNING_PHASE2.md`.

## 1. The three ways the app reads a page

| Way | What it does | Learns from this book? |
|---|---|---|
| **Whole lines (Tesseract)** | A ready-made reader gets each line picture as it is | No (only the language model can correct it) |
| **Whole lines (our reader)** | Tries every place a letter could start and end, keeps the best reading | Yes: your groups and checked lines |
| **Cut letters** (legacy, hidden) | Cuts the page into letters first, reads each letter alone | Yes, but a wrong cut means a wrong letter |

## 2. How our reader reads one line

Example: the word **भगवान** (in Gujarati the same idea: ભગવાન). It has 4 aksharas: `भ` `ग` `वा` `न`.
The numbers below are made up to show the idea; real lines have many more of them.

**Step 0. The picture.** The app takes the black-and-white ink of the line. Think of it as a strip
220 pixels wide:

```
  भ      ग      वा       न
|------|------|---------|------|
0      50     100       170    220   (pixels from the left)
```

**Step 1. Possible cut places.** The reader does not know where one letter ends. So it marks many
places where a letter *could* start or end: every 9 pixels, plus every gap and every thin spot in the ink.

```
places: 0, 9, 18, ... 50 (gap), ... 100 (thin spot), ... 135, ... 170 (gap), ... 220
```

**Step 2. Windows.** Every piece between two places (not too narrow, not too wide) is a "window" to
look at. A few of them:

| Window (pixels) | What is really in it |
|---|---|
| 0–50 | `भ` |
| 50–100 | `ग` |
| 0–100 | `भग` (two letters) |
| 100–135 | `व` (only the left part of `वा`) |
| 135–170 | the `ा` stroke alone |
| 100–170 | `वा` |
| 170–220 | `न` |

**Step 3. The letter reader guesses each window.** For every window it says what it looks like, and also
"**not a letter**" when it sees half a letter or two letters together:

| Window | Reader's guess |
|---|---|
| 0–50 | `भ` 90% |
| 50–100 | `ग` 60%, `रा` 30% (they look alike in print) |
| 0–100 | not a letter 85% |
| 100–135 | `व` 70% |
| 135–170 | not a letter 90% |
| 100–170 | `वा` 80% |
| 170–220 | `न` 90% |

**Step 4. The search: which windows, side by side, make the best word?** It tries the ways to cover
the strip from left to right and gives each way points:

| Way | Letters | Why it wins or loses |
|---|---|---|
| A | `भ` · `ग` · `वा` · `न` | every window is a sure letter, widths look normal, and `भगवान` is a common word → **best** |
| B | `भ` · `ग` · `व` · (`ा` alone) · `न` | the `ा` window is "not a letter" → many points lost |
| C | `भ` · `रा` · `वा` · `न` | the reader gave `रा` only 30%, and the language model has never seen `भरावान` → loses |
| D | (`भग` as one) · `वा` · `न` | the 0–100 window is "not a letter" → loses |

So three checks decide: **how sure the letter reader is**, **is the width normal for that letter**, and
**does the language model know this order of letters**. (There are millions of ways on a long line; the
search keeps only the 10 best so far as it walks along, so it stays fast.)

**Step 5. The text.** The winner, way A, gives `भगवान`, a space where the gap is wide, and a box for each
akshara on the page (so you can click it).

**Why this helps:** a reader that cuts first and reads after is stuck with a wrong cut (for example `व`
and `ा` cut apart). Our reader tries all cuts and lets the letters and the words decide. In the real book it reads the wide `र्य`
of `उपर्य` correctly, where Tesseract reads `उपरय`.

## 3. The two helpers inside

**The letter reader** turns a window into a score for each letter. The window is shrunk to 20 × 20 pixels
plus stroke directions and size (about 1,300 numbers). It is a simple **linear** reader ("ink here makes
`क` more likely"). A neural network was tried and was not better on this book (7.5% against 7.3%).

**The language model** never looks at the ink. It only knows which aksharas follow each other in this
book (from your labels in reading order, proofread lines and word lists).
Example: after `भग` it has nearly always seen `वा` (भगवान), so when the reader is unsure between `वा` and
`बा`, it picks `वा`. Where the shape is clear, the letter reader wins. Its weight is 0.5; at 0 (off) the
reader gets 16.4% wrong, at 3 it starts to overrule clear letters.

## 4. What it learns from

| From | What it gives | Example |
|---|---|---|
| Your reviewed groups | Each letter, a little shifted and varied: about 9,000 letters | the `र्य` group, narrow and wide |
| Made-up "not a letter" pieces | Halves, a letter with its neighbour | left half of `य`, `य` + `प` |
| Your checked lines | Each line cut into the aksharas of your text, each piece an example: 3,000–4,000 more | `हे`, `क्ष्मी`, `ई` (no reviewed group) |

Fairness: every label counts the same in total. `वा` with 195 letters does not outweigh `बा` with 1.

**Retrain** (about half an hour) learns again; **Read** reads pages (2 lines at a time); **Measure**
(about 4 hours) scores it fairly on your checked lines, leaving out the tested pages.

## 5. How good it is (printed 1933 book, 99 checked lines, fold-fair, 2026-10-13)

| Reader | Characters wrong | New pages 52, 53 |
|---|---|---|
| Our reader, first version (11 Oct) | 10.2% | – |
| + page borders removed (12 Oct) | 8.4% | 4.9% |
| + learning from your corrections (now) | **7.3%** | **3.9%** |
| Tesseract | 4.7% | 3.8% |

One training run can differ from another by about 1 point by chance. So on the whole book Tesseract is still
better. On new pages the two are about equal. Where the two disagree, the app marks the aksharas
(**Second opinion**): about a fifth of the aksharas are marked, and most of Tesseract's mistakes fall on them.

## 6. Strong and weak points

| Strong | Weak |
|---|---|
| Learns this book's own shapes (the wide `र्य`) | Needs cut and grouped letters first: **about a week of glyph work per book** |
| No cut mistakes in the final reading: it picks the cuts itself | Vowel signs are hard: `नी`/`नो`, `री`/`रो`, `पा`/`पो` differ by a few pixels at 20 × 20 |
| Every akshara has its box on the page | Slow: about 7 s per line before 16 October (faster now, not yet measured) |
| Works with handwriting too (it follows the book's ink and sizes) | Only knows letters it has seen; a missing group means a `?` |
| A good second opinion beside Tesseract | Letter frequency enters only through the language model, by design |

## 7. How it compares with a line reader (see `docs/research/line_reader.md`)

| | Our reader | Line reader (Tesseract fine-tune, Kraken) |
|---|---|---|
| Teaches with | Letters (groups) + checked lines | Checked lines only |
| Finds letter boundaries | By trying all windows (search) | Learns them itself (CTC) |
| Work for a new book | About a week of glyph labelling | About 1–2 days of correcting lines (estimate) |
| Letter boxes on the page | Yes | Only rough positions |

Our reader already learns from checked lines (section 4). A line reader would make the glyph step
optional. The groups would stay useful for Font Maker, for checking groups, and for the boxes on the page.

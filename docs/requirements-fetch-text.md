# Requirements: Letter Extraction and OCR for Manuscripts (Devanagari to Gujarati Unicode)

## 1. Overview

The goal is to **convert scanned manuscript pages into Gujarati Unicode text.** The manuscripts are written in Devanagari script; the output text is in Gujarati script.

There is no OCR engine that reads this hand reliably, so the project builds one in three phases:

1. **Phase 1: Letter extraction.** Read every page in an input folder, cut out every letter with its matras, group identical letters, and write an image of each one to an output folder. A person maps each unique letter to its **Gujarati Unicode** text (for example the image of कि is mapped to કિ).
2. **Phase 2: OCR training.** Use the mapped letter images as training data for a recognizer that learns this scribe's hand.
3. **Phase 3: Conversion.** Run the trained recognizer on whole manuscripts and write Gujarati Unicode text, one text file per page.

Phase 1 is the focus of this document. Phases 2 and 3 are described so that Phase 1 produces what they need.

## 2. Sample Analysis (`samples/page1.jpg`, `samples/page2.jpg`)

**Image**
- Each page is a JPEG of 3684 x 1808 px, landscape, about 100 ppi. There are 11 text lines per page, about 110 px apart. Main letters are about 60 to 80 px tall, including the headline.
- The page has a ruled border, margin folio numbers, a black scanner background and uneven paper tone. The border can be removed first with the border remover app (`samples/cleaned/` shows the result).

**Script and language**
- **Devanagari script.** The language is Sanskrit verse followed by old Gujarati prose (for example छे, केवुं, ते), all written in Devanagari.
- **Old letterforms** differ from modern printed Devanagari. Examples: अ is written in an older form that looks like ल्ल, and ख looks like रव. The training data must come from these manuscripts, not from modern fonts.
- **Conjuncts** (joined consonants) are common: श्री, ज्ञ, क्ष, ह्म, च्चि, श्च, स्व, र्य.

**Headline and letter spacing**
- There are no spaces between words.
- The headline (shirorekha) is **drawn letter by letter, with a small break between most letters.** This is the main cue for splitting letters (see Section 6).
- The breaks separate **pen strokes, not always whole letters:**
  - The ा, ी, ो, ौ bar has its own short piece of headline, so a break often falls between a consonant and its vowel bar (वा, धा, मो).
  - Some letters have a break inside them (for example in the old अ and in क्ष).
  - In places the headlines of neighbouring letters touch or overlap, so there is no break (for example in छेतेकेवुंछे).
- **Matras sit in three zones:** above the headline (ि ी े ै ो ौ, anusvara ं, reph र्), on the main line (ा ी ो), and below it (ु ू ृ, halant ्). Upper and lower matras often touch the neighbouring lines.

**Ink**
- Red ink for the opening verses, black ink for the later lines. Red dandas (।, ॥) and verse numbers appear inside black lines.
- The red ink is lighter and its headline is thinner and more broken than the black ink's. Stroke width varies with the pen, with some bleed and fading.

**Trial result.** A quick test on `page1.jpg` measured the breaks along each headline. It found all 11 lines. On black lines most letter boundaries were found, with extra breaks at vowel bars and missed breaks where headlines touch. On red lines there were far too many breaks, because of the thin, broken headline. Headline breaks are therefore a good **starting point**, but they need the follow-up rules in FR-5.

## 3. Definitions

- **Letter (akshara):** the unit this project extracts. It is one written syllable: an independent vowel (अ, इ, ...), or a consonant or conjunct together with its matra and any anusvara (ं), chandrabindu (ँ), visarga (ः) or reph (र्). Examples: क, कि, कु, के, कों, श्री, क्षे, र्म.
- **Stroke piece:** a piece of ink between two headline breaks. A letter is made of one or more stroke pieces.
- **Label:** the **Gujarati Unicode** text of a letter, for example કિ for कि, શ્રી for श्री, ર્મ for र्म.
- **Unique letter (class):** all letters with the same label belong to one class. For example, every कि on every page belongs to class કિ.
- **Sample:** one cut-out image of one letter on one page. A class has many samples.

## 4. Devanagari to Gujarati Mapping

- Gujarati Unicode (U+0A80 to U+0AFF) follows the same layout as Devanagari (U+0900 to U+097F). Most characters map **one to one** at a fixed offset: क U+0915 → ક U+0A95, ि U+093F → િ U+0ABF.
- Conjuncts, reph and halant are encoded the same way in both scripts, so क्ष (क + ् + ष) becomes ક્ષ (ક + ્ + ષ).
- Exceptions need a mapping table:
  - **Danda:** Gujarati has no danda of its own. Use the Devanagari । U+0964 and ॥ U+0965 in the Gujarati text.
  - **Digits:** १२३ → ૧૨૩ (or Western 123, as a setting).
  - **Rare Devanagari letters** that have no Gujarati equivalent (for example ऴ, ऩ, ऱ) must be listed and handled by a rule.
- The app may store labels in Devanagari internally and convert them to Gujarati on output with this table. This avoids typing errors during labeling. The output is always Gujarati.
- The mapping table must be a **file the user can edit** (CSV or JSON).

## 5. Functional Requirements: Phase 1 (Letter Extraction)

### FR-1: Folder-Based Input
- The user gives an **input folder**. The app reads every supported image in it (JPEG, PNG, TIFF), in name order.
- Files that cannot be read are skipped and listed in the report. One bad file must not stop the run.

### FR-2: Page Preparation
- Find the **text block** and ignore everything outside it: the border, margin numbers, scanner background and tape marks.
- Separate **ink from paper** for both red and black ink, despite uneven paper tone and stains. Red ink must be handled with its own settings, because it is lighter and thinner.
- Optionally run the border remover first, or accept already cleaned pages.

### FR-3: Line Detection
- Find each text line and its **headline**: the strongest horizontal run of ink in the line.
- Follow the headline along the line, **allowing for slight slope and waviness**. Do not assume it is perfectly straight.
- Give every matra above or below the headline to the correct line.

### FR-4: Headline-Break Splitting (first cut)
- Scan along the headline and find the **breaks**: columns with no ink in the headline band.
- Ignore breaks narrower than a set minimum (about 2 px) and ink specks smaller than a set size.
- Cut the line at each break into **stroke pieces**. Each piece includes all ink below its part of the headline, down to the bottom of the main zone.

### FR-5: Join and Split Rules (from stroke pieces to letters)
Headline breaks do not match letter boundaries exactly, so the stroke pieces are corrected with these rules:

- **Join vowel bars:** a narrow piece that is only a vertical bar with a short headline is the ा / ी / ो / ौ bar. Join it to the piece on its **left**.
- **Join the ि matra:** the ि hook is written to the **left** of its consonant. Join it to the piece on its **right**.
- **Join broken letters:** a piece that is too narrow to be a letter, and has no bar shape, is joined to the neighbour it touches most.
- **Split wide pieces:** a piece wider than a set limit (for example 1.6 times the typical letter width) probably holds two or more letters whose headlines touch. Split it at the **thinnest point in the main zone below the headline** (where the vertical ink profile is lowest).
- **Attach upper and lower marks:** each mark above the headline (matras, anusvara, reph, chandrabindu) and below the main zone (ु ू ृ ्) is attached to the letter it overlaps most.
- **Conjuncts stay whole:** a conjunct such as क्ष or श्री is one letter. Do not split it, even if it has a break inside.
- **Dandas, digits and punctuation** are kept as their own category (FR-9).
- All limits (minimum break width, minimum and maximum letter width, bar shape) are **settings in the config file**, with separate values for red and black ink.

### FR-6: Letter Samples
- For each letter, save its **bounding box** and an **ink mask** (which pixels belong to it), so ink from neighbouring letters is left out of the image.
- Save every letter's page, line and position in reading order. Phase 3 needs this order to rebuild the text.

### FR-7: Grouping and Labeling
- Group samples that look alike **across all pages**, using shape similarity (Section 7).
- Show each group to the user, who types or picks its **label** once for the whole group.
- Optionally, show a **suggested label** for each group from an AI model or an earlier trained recognizer. The user confirms or corrects it.
- Samples the app could not place in a group go to **"unsure"** for the user to label one by one.

### FR-8: Review Screen
- The user can view every group, label or rename a group, merge two groups, split a group, move a single sample to another group, and delete false detections (stains, specks).
- The user can **fix a wrong cut** by joining two neighbouring samples or splitting one sample. Wrong cuts are the most common error, so this must be quick.
- Review decisions are saved, so they are not lost when the app runs again.

### FR-9: Output Folder
The user gives an **output folder**, which the app creates if it does not exist. It contains:

- **`dataset/` – training images, one folder per class.** Every sample is kept, not just one example, because OCR training needs many examples per letter.
  - The folder name is safe on Windows and macOS: a transliteration plus Unicode code points, for example `ki__U0A95-U0ABF/`. A file inside the folder records the real Gujarati label (કિ).
  - Each image is a PNG crop with a small margin. The default is the **original crop** (paper background). Options: a **normalized** black-on-white version, and a fixed size (for example 64 x 64 px) for training.
  - Separate groups for **independent vowels, consonants with matras, conjuncts, digits and punctuation.**
- **`lines/` – line images with their text.** One image per text line with a matching `.txt` file of its Gujarati text, built from the labeled letters in reading order. These are needed for line-level training (Section 7.2).
- **`letters.csv`** with one row per class: Gujarati label, Devanagari form, Unicode code points, transliteration, number of samples, and an example image.
- **`samples.csv`** with one row per sample: page, line, position, bounding box, ink colour, class and label confidence. This lets any sample be traced back to the page.
- **Overview sheet** (`overview.html` and/or `overview.png`): one example of every class in a grid, sorted in alphabet order (vowels, then consonants from ક to હ, then conjuncts), with its label and sample count. This shows at a glance which letters exist and which have too few samples.
- **`unsure/`** for samples not yet labeled.

### FR-10: Report
- Write a run summary: pages processed, lines, letters found, number of classes, classes with fewer than a set number of samples, unsure count and skipped files.

## 6. Functional Requirements: Phases 2 and 3 (OCR Training and Conversion)

### FR-11: Training (Phase 2)
- Train a recognizer from the Phase 1 output (`dataset/` and/or `lines/`).
- Hold back part of the labeled data for testing, and report accuracy per class, so weak letters can be seen and given more samples.
- Training can be repeated as more manuscripts are reviewed. Each new book adds to the dataset.

### FR-12: Conversion (Phase 3)
- Input: a folder of manuscript pages. Output: **one UTF-8 text file per page in Gujarati Unicode**, keeping the line breaks of the manuscript.
- Mark letters with low confidence (for example with a setting such as `[?]`, or in a side file), so a person can check them.
- Keep the dandas (।, ॥) and verse numbers as written.
- Words have no spaces in the manuscript, so the text output has no spaces either. **Splitting into words is out of scope**, but it could be added later as a separate step.
- Optional: a side-by-side view of the page image and its text for proofreading.

## 7. Non-Functional Requirements

- **Platform:** a desktop app for Windows and macOS, the same as the border remover, with a command-line version for batch use.
- **Offline by default:** everything must work without internet. AI label suggestions from a cloud service may be offered only as an opt-in, because the manuscripts may be private.
- **Performance:** Phase 1 cutting about 10 seconds per page or less on a normal laptop, without labeling. Batches of hundreds of pages must work.
- **Non-destructive:** never change or delete the input images.
- **Traceable:** every sample and every converted letter can be traced back to its page and position.
- **Adjustable:** all thresholds live in one config file, as in the border remover.

## 8. Suggested Approach

### 8.1 Pipeline

```
input pages
  → 1. prepare page      (border removal, crop to text block, ink mask for red and black ink)
  → 2. find lines        (find and follow each headline)
  → 3. first cut         (split at headline breaks → stroke pieces)
  → 4. join and split    (vowel bars, ि, broken letters, wide pieces, upper and lower marks)
  → 5. group             (shape similarity across all pages)
  → 6. label and review  (user gives each group its Gujarati label and fixes wrong cuts)
  → 7. write dataset     (class folders, line images with text, CSV files, overview)
  → 8. train recognizer  (Phase 2)
  → 9. convert pages     (Phase 3: Gujarati text per page)
```

Steps 1 to 4 use standard image processing (OpenCV), as in the border remover.

### 8.2 Grouping (step 5)
- Turn each sample into a shape fingerprint. Start simple, for example a resized ink image or HOG features. Move to features from a small neural network if needed.
- Group samples whose fingerprints are close. Similar-looking letters (व/ब, घ/ध, म/भ) may land in one group and need splitting in review.
- The user then labels a few hundred groups instead of thousands of separate letters.
- Once a first recognizer exists (Phase 2), it **suggests labels** for new books, and review becomes mainly confirming.

### 8.3 Recognizer (Phase 2)
Two kinds of recognizer fit this project. The dataset supports both.

| Kind | How it works | Strengths | Weaknesses |
|---|---|---|---|
| **Letter classifier** | Takes one cut-out letter image and returns its class. A small neural network trained on `dataset/` | Simple, quick to train, easy to understand; uses the letter images directly | Only as good as the cutting. A wrong cut gives a wrong letter. Rare conjuncts with few samples are weak |
| **Line recognizer (HTR)** (for example **Kraken**, used by eScriptorium) | Takes a whole line image and returns its text, with no letter cutting | Not affected by cutting errors; the standard method for handwritten manuscripts; handles touching letters | Needs line images with correct text (`lines/`); more data and training time |

**Recommendation:** start with the **letter classifier**, because Phase 1 produces its training data directly and its results are easy to check. Produce `lines/` from the start as well, and move to a **line recognizer** once a few hundred lines are reviewed. This usually gives the best accuracy on manuscripts, because cutting errors stop mattering.

### 8.4 First Step
Before building the full app, build steps 1 to 4 for the two sample pages. Draw the cuts on the page and count three kinds of error: missed breaks, extra breaks, and wrongly attached matras. Tune the join and split rules until most letters are cut correctly, with separate settings for red and black ink. This decides how much the review screen will be needed.

## 9. Open Questions

1. **Digits:** should digits be written in Gujarati (૧૨૩) or Western (123) in the text output?
2. **Rare letters:** how should Devanagari letters with no Gujarati equivalent be written, if they appear?
3. **Classes:** should letters with anusvara (કં) and visarga (કઃ) be their own classes, or should the marks be a separate class? Separate marks give fewer classes and more samples per class, which helps training.
4. **Red and black ink:** should they share classes (recommended) or be kept separate?
5. **Cloud use:** may page images be sent to a cloud AI service for label suggestions, or must everything stay on the computer?
6. **Other manuscripts:** will this run on other hands or scripts (for example Gujarati-script manuscripts)? This decides how general the cutting rules must be.
7. **Word spacing:** is unspaced Gujarati text acceptable as the final result, or is word splitting needed later?

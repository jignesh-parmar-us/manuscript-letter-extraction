# Adding a new book

How to turn a folder of page images into clean letters with clean labels, with as little hand work as possible, and get it ready for training the letter reader.

The same guide is in the app: the **Help** link at the top right opens [docs/help/new-book.html](help/new-book.html). Change both together.

**New here, or lost?** [The steps in order](help/workflow.html) shows the whole route as a flowchart, from creating a book to downloading its text (also linked at the top of the guide in the app). [How it works](help/tech.html) explains each step technically: cutting, grouping and labels, training and the reader, reading a book (algorithms, scores, image processing).

## 1. Before you start

- **One folder per book** with its page images (JPG, PNG, TIFF or BMP), in page order by name (page2 comes before page10). The app only reads this folder; it never changes your images.
- **Printed or handwritten?** This decides how the letters are cut and who suggests labels: printed books are read by Tesseract; handwritten books learn from the books you have already labelled.
- **For printed books, Tesseract must be installed** (see [INSTALL_TESSERACT.md](INSTALL_TESSERACT.md)). The Review groups section says so if it is missing.
- **Keep your older labelled books** until the new book has learned from them ([section 6](#6-replacing-old-books)): their labels are the fastest way to label the new one.

## 2. A printed book

About 10 minutes of waiting for 20 to 25 pages, and a few clicks. Expect about a quarter of the letters to be labelled right after capture, and more after step 4 if you have other labelled books.

1. **Create the book.** **Books** → **New book**: a name, the folder with the page images, and Writing **Printed**.
2. **Choose the cutting before the first capture.** **Pages & capture** → **Cutting into letters** → **By Tesseract's reading**. Each line is cut into the letters Tesseract reads: about half as many letters left joined as with the shape cut.
3. **Capture.** **Capture letters**, then wait (about 4 to 5 minutes for 23 pages). ા bars cut onto the next letter (નાર as ન + ાર) are given back to their letter. At the end, every letter has Tesseract's reading, groups that mixed two letters are split, and the groups Tesseract is sure about are labelled, marked *not reviewed*.
4. **Learn from your other labelled books.** **Review groups** → **Details**: tick the labelled books of the same kind of print, then **Suggest from labelled books** (a few seconds). Each letter gets the label of the closest group you labelled there; where Tesseract and your books agree, the group's suggestion says so.
5. **Split mixed groups**, once. Letters read as another letter *and* shaped differently move to a group of their own. A group of one letter is never split by its strokes.
6. **Accept the sure suggestions.** **Accept N with ≥ 90 %**. One **Undo** takes it all back.
7. **Review** as in [section 4](#4-reviewing-the-labels).

> **Tip:** books cut by Tesseract do not need **Fix cuts with Tesseract**: their cuts already follow its reading. Fix cuts is for printed books cut by the shapes of the ink.

## 3. A handwritten book

Tesseract reads handwriting poorly (about a third of the letters wrong), so the labels come from you and from your other handwritten books.

1. **Create the book.** **Books** → **New book**, Writing **Handwritten**. The cutting stays **By the shapes of the ink**.
2. **Capture.** **Capture letters**.
3. **If you have another labelled handwritten book in the same hand:** **Review groups** → **Suggest from labelled books**, then **Split mixed groups** and **Accept N with ≥ 90 %**.
4. **Otherwise, label the biggest groups by hand.** Sort the group list **by size** and label the largest 30 to 50 groups: they hold most of the letters. Use **Letters…** or type in Gujarati or Devanagari. These labels are what the letter reader (C14) learns this hand from, and what the next handwritten book will learn from.
5. **Unsure:** accept the suggested groups (→) for the letters that clearly belong to one.

## 4. Reviewing the labels

Labels given by Tesseract or by other books are marked *not reviewed*. Check them in this order; the first steps do the most good. You do not need to finish every group.

| Where | What to do |
|---|---|
| Group list: **Show → Not reviewed**, **by size** | Open the big groups first. Look at the letter images: letters read differently carry a small coloured badge. If a badge is wrong (the letter is right where it is), click it to remove that reading, or select several letters and **Remove readings**. If it is right (the letter is in the wrong group), click the green chip on the left of the letter to move it to the group with that label, or select several and **Move to their readings**. If all is right, tick **Reviewed**; if not, fix the label or move the wrong letters out. |
| One letter selected | It is shown on its line with four letters on each side, to judge a doubtful label. **Open on its page** (or a double-click) opens it in the **Pages** tab to fix its cut; fix as many letters there as you need, then **← Back to …** returns to the same letter in the group. |
| **Show → Mixed readings** | Groups whose letters were read as two letters. Click a reading under the group's name to select its letters, then **New group**. |
| **Show → Suggested** | Accept, change or reject each suggestion. **Merge into gXXXX** appears when another group already has that label. |
| **Unsure** | Select letters with a green reading and click **Accept readings**, or accept the suggested groups (→). |
| **Letter overview** | Which letters have a group (green), are only suggested (amber) or are missing (grey): every consonant with every vowel sign and with ્ ં ઃ ઁ ઼ (ક્, કં, કઃ, કઁ, ક઼), and every other label below the table. Tick the rakar ્ર and reph ર્ rows to see joined letters (ક્ર, ટ્ર, ર્ક). |
| **Move to…** (on selected letters) | Click a letter in the table: the letters go into its group, or into a new group with that label. Unlabelled groups are listed newest first below it. |

> **Remember:** every change can be undone (**Undo**, or Ctrl/Cmd+Z). Locked groups never change until you unlock them.

## 5. Training the letter reader

**Training Data → Readers → Train** teaches a letter reader your reviewed letters (about a minute). Train again whenever you have reviewed or corrected more: each training makes a new reader, and older ones are kept.

- **Not every label is needed.** It learns only from labelled letters; labels with fewer letters than the minimum you choose (5 by default, down to 1) are left out and listed. Its report shows how many letters of pages it did not learn from it reads right, and the accuracy of every letter, so you see which ones need more samples.
- **Wrong labels are the problem.** A group labelled ने that still holds ते letters teaches the reader that both are ने. That is why the review matters more than the number of labels.
- **It learns only from groups you reviewed**, unless you tick *also groups not reviewed*.
- **Check these** (Review groups, side bar) lists the letters the reader is sure are in the wrong group: **Move to …**, or **It is right** if the reader is wrong. Fix them, then train again.
- **The reader also reads the Read Book text** when you convert (section 7), on the letters it was taught: a big group you have not reviewed is a letter it does not know. Review the big groups, train again, then convert again.
- **Good enough to start:** the big groups reviewed, and the mixed ones split.

## 6. Replacing old books

1. **Make the new book first** and run **Suggest from labelled books** with the old books ticked, so their labels reach the new one.
2. **Accept and review** in the new book (sections 2 and 4).
3. **Then delete the old books.** **Books** → **Delete**. This removes only the book's letters, groups and labels in the library; your page images are never touched. It cannot be undone.

> **Tip:** keep at least one labelled book of each kind (one printed, one handwritten): new books of the same kind learn from it.

## 7. Reading the whole book (Read Book)

Every book has two parts in the section menu: **Training Data** (everything above) and **Read Book**, the whole book to turn into text.

1. **Read Book → Upload & capture.** Type the path of the book's **PDF** and click **Use this PDF** (its pages become images in the book folder), or choose a **folder of page images**.
2. **Cut the pages.** The pages are cut into lines and letters in the background, a few at a time. Stopping keeps the pages already cut; the next **Cut the remaining pages** continues.
3. **Book pages** shows each page with its letters, to fix cuts (draw a box, join, split, delete). Read Book letters are never grouped automatically; only the letters you correct in the Text view (step 6) go into groups.
4. **A page that reads badly:** **Use for training** moves it to Training Data, where its letters go to Unsure to be labelled.

5. **Text:** **Convert all pages** (or one page). Each page is shown beside its text: **Tesseract only** shows what Tesseract read, **Tesseract + your groups** adds your groups' check, which is what marks most mistakes (Tesseract is confident even when it is wrong). Uncertain letters are highlighted on both, and clicking one shows it on the page and what each reader read. **Download** the page or the whole book as .txt, Word, PDF or a picture, with uncertain letters as `[?]`, `[?ક]` or the best guess.

6. **Proofread** in the Text view: click a wrong letter (or **Next uncertain ▶**) and type the right one, then **Correct**. The correction labels that letter, so it shows in Review groups and the next reader training learns from it; **Undo** takes it back. **Two letters…** splits a box (click where the letters meet), **Join with the next** joins two boxes, **Not a letter** deletes a speck. Click **✓** at the end of a line once its text is right: converting again keeps proofread lines, and the proofread lines measure how many characters the conversion gets wrong.

7. **Dictionary:** the language model corrects some uncertain letters when you convert, from the text it knows (underlined in the Text view, still marked uncertain). It learns from your labels and proofread lines; **Import** a UTF-8 text file in Gujarati or Devanagari (the full text of the book, or works like it) to give it much more, then convert again. Untick *Use the language model* to turn it off.

8. **Line truth:** type what a few lines really say (Tesseract's reading of the whole line is filled in: correct it and press Enter). 30 to 50 lines from a few pages are the test set every way of reading is measured on, independent of how the letters were cut.

> **Printed books** are read by Tesseract and checked against your labelled groups; **handwritten books** by your groups alone for now, so their text is rough until the letter reader. Every letter you correct teaches the next reader training.

## 8. If something goes wrong

| What you see | What to do |
|---|---|
| The Tesseract buttons are greyed out | Tesseract or its Devanagari model is missing: hover over the button for the reason, and see [INSTALL_TESSERACT.md](INSTALL_TESSERACT.md). |
| **Capture again** asks before it starts | The book has labels or changes made by hand, and capturing again would discard them. Labels given automatically do not count. To try other settings without losing work, make a new book from the same folder instead. |
| "No other book with labels yet" | Suggestions from labelled books need another book of the same writing with labelled groups. Label the biggest groups of one book first. |
| A group mixes two letters | Click one of its readings to select those letters, then **New group**; or run **Split mixed groups**. |
| A ા bar on the next letter (નાર cut as ન + ાર) | On printed books: **Fix ા bars** in the Label suggestions bar (one undo). Bars with the hook of િ above them (રવિ) are never moved. ક્યારે (cut as ક્ય + ારે) is fixed when Tesseract read the letter as રે. A stem cut off from its letter (ણ split in two) is joined back to it. Running it a second time catches the few letters that changed twice. The fixed letters keep Tesseract's readings, so there is no need to read the book again. Books captured since this was added get it at capture. |
| Letters cut wrongly (two letters in one, a vowel bar on its own) | On printed books cut by shapes: **Fix cuts with Tesseract**. On any book: the **Pages** tab's **Join**, **Split** and **Draw a box**. |
| Something went wrong after a click | **Undo**. Fixing cuts, accepting suggestions and splitting groups are each one undo step. |

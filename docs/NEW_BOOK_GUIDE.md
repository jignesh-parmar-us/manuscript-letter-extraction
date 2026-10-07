# Adding a new book

How to turn a folder of page images into clean letters with clean labels, with as little hand work as possible, and get it ready for training the letter reader.

The same guide is in the app: the **Help** link at the top right opens [docs/help/new-book.html](help/new-book.html). Change both together.

## 1. Before you start

- **One folder per book** with its page images (JPG, PNG, TIFF or BMP), in page order by name (page2 comes before page10). The app only reads this folder; it never changes your images.
- **Printed or handwritten?** This decides how the letters are cut and who suggests labels: printed books are read by Tesseract; handwritten books learn from the books you have already labelled.
- **For printed books, Tesseract must be installed** (see [INSTALL_TESSERACT.md](INSTALL_TESSERACT.md)). The Review groups section says so if it is missing.
- **Keep your older labelled books** until the new book has learned from them ([section 6](#6-replacing-old-books)): their labels are the fastest way to label the new one.

## 2. A printed book

About 10 minutes of waiting for 20 to 25 pages, and a few clicks. Expect about a quarter of the letters to be labelled right after capture, and more after step 4 if you have other labelled books.

1. **Create the book.** **Books** → **New book**: a name, the folder with the page images, and Writing **Printed**.
2. **Choose the cutting before the first capture.** **Pages & capture** → **Cutting into letters** → **By Tesseract's reading**. Each line is cut into the letters Tesseract reads: about half as many letters left joined as with the shape cut.
3. **Capture.** **Capture letters**, then wait (about 4 to 5 minutes for 23 pages). At the end, every letter has Tesseract's reading, groups that mixed two letters are split, and the groups Tesseract is sure about are labelled, marked *not reviewed*.
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
| Group list: **Show → Not reviewed**, **by size** | Open the big groups first. Look at the letter images: letters read differently carry a small coloured badge. If a badge is wrong (the letter is right where it is), click it to remove that reading, or select several letters and **Remove readings**. If all is right, tick **Reviewed**; if not, fix the label or move the wrong letters out. |
| **Show → Mixed readings** | Groups whose letters were read as two letters. Click a reading under the group's name to select its letters, then **New group**. |
| **Show → Suggested** | Accept, change or reject each suggestion. **Merge into gXXXX** appears when another group already has that label. |
| **Unsure** | Select letters with a green reading and click **Accept readings**, or accept the suggested groups (→). |
| **Letter overview** | Which letters have a group (green), are only suggested (amber) or are missing (grey), and every other label below the table. Tick the rakar ્ર and reph ર્ rows to see joined letters (ક્ર, ટ્ર, ર્ક). |
| **Move to…** (on selected letters) | Click a letter in the table: the letters go into its group, or into a new group with that label. Unlabelled groups are listed newest first below it. |

> **Remember:** every change can be undone (**Undo**, or Ctrl/Cmd+Z). Locked groups never change until you unlock them.

## 5. When is a book ready for training?

The letter reader (C14) is the next part of the app. This is how it is planned to work.

- **Not every label is needed.** The letter reader will learn only from labelled letters; letters with fewer than 5 samples will be left out and listed. Its report will show the accuracy of every letter, so you see which ones need more samples.
- **Wrong labels are the problem.** A group labelled ने that still holds ते letters teaches the reader that both are ने. That is why the review matters more than the number of labels.
- **By default it will learn only from groups you labelled or reviewed.** The labels given at capture or by suggestions count once you have reviewed them; including them unreviewed will be an option.
- **Good enough to start:** the big groups reviewed, and the mixed ones split. You can train again whenever you have reviewed more.

## 6. Replacing old books

1. **Make the new book first** and run **Suggest from labelled books** with the old books ticked, so their labels reach the new one.
2. **Accept and review** in the new book (sections 2 and 4).
3. **Then delete the old books.** **Books** → **Delete**. This removes only the book's letters, groups and labels in the library; your page images are never touched. It cannot be undone.

> **Tip:** keep at least one labelled book of each kind (one printed, one handwritten): new books of the same kind learn from it.

## 7. If something goes wrong

| What you see | What to do |
|---|---|
| The Tesseract buttons are greyed out | Tesseract or its Devanagari model is missing: hover over the button for the reason, and see [INSTALL_TESSERACT.md](INSTALL_TESSERACT.md). |
| **Capture again** asks before it starts | The book has labels or changes made by hand, and capturing again would discard them. Labels given automatically do not count. To try other settings without losing work, make a new book from the same folder instead. |
| "No other book with labels yet" | Suggestions from labelled books need another book of the same writing with labelled groups. Label the biggest groups of one book first. |
| A group mixes two letters | Click one of its readings to select those letters, then **New group**; or run **Split mixed groups**. |
| Letters cut wrongly (two letters in one, a vowel bar on its own) | On printed books cut by shapes: **Fix cuts with Tesseract**. On any book: the **Pages** tab's **Join**, **Split** and **Draw a box**. |
| Something went wrong after a click | **Undo**. Fixing cuts, accepting suggestions and splitting groups are each one undo step. |

"""C16b: reading pages into text: the rules, a page, the stored text, the downloads and the Word file."""
import io
import json
import sys
import unittest
import zipfile
from pathlib import Path
from unittest import mock
from xml.dom import minidom

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import appbook                                                      # noqa: E402
from fastapi.testclient import TestClient                           # noqa: E402
from letter_extractor.app.api import create_app                    # noqa: E402
from letter_extractor.app.db import LetterGroup, Page, PageText, Sample   # noqa: E402
from letter_extractor.app.library import LibraryError              # noqa: E402
from letter_extractor.app.texts import convert_book, convert_page, page_text   # noqa: E402
from letter_extractor.config import Config                          # noqa: E402
from letter_extractor.ocr.convert import LetterText, choose, line_text, mark_spaces, taught, vote   # noqa: E402
from letter_extractor.ocr.docx import write_docx                    # noqa: E402
from sqlalchemy import func, select                                 # noqa: E402


class RuleTests(unittest.TestCase):
    cfg = Config()

    def test_agreeing_readers_make_a_sure_letter(self):
        self.assertEqual(choose(("क", 92), ("क", 0.3), self.cfg), ("क", 0.99, "both", False))

    def test_a_disagreement_is_uncertain_unless_tesseract_is_very_sure_and_the_group_far(self):
        text, conf, source, uncertain = choose(("क", 92), ("फ", 0.3), self.cfg)
        self.assertEqual((text, source, uncertain), ("क", "tesseract", True))       # sure enough to keep
        self.assertEqual(choose(("क", 70), ("फ", 0.3), self.cfg)[:3], ("फ", 0.4, "groups"))
        text, conf, source, uncertain = choose(("क", 98), ("फ", 0.5), self.cfg)      # group far, Tesseract sure
        self.assertEqual((text, source, uncertain), ("क", "tesseract", False))
        self.assertTrue(choose(("क", 98), ("फ", 0.4), self.cfg)[3])                  # group close: uncertain

    def test_one_reader_alone(self):
        self.assertEqual(choose(("क", 95), None, self.cfg)[1:], (0.76, "tesseract", False))
        self.assertTrue(choose(("क", 60), None, self.cfg)[3])                       # 0.48: uncertain
        self.assertEqual(choose(None, ("क", 0.2), self.cfg), ("क", 0.8, "groups", False))
        self.assertEqual(choose(None, ("क", 0.7), self.cfg), ("", 0.0, "none", True))   # beyond group_distance
        self.assertEqual(choose(None, None, self.cfg, kind="danda")[0], "।")

    def test_with_a_letter_reader_the_three_readers_vote(self):
        c = self.cfg
        self.assertEqual(vote(("क", 70), ("क", 0.6), None, c)[2:], ("tesseract+reader", False))     # agree: sure
        self.assertEqual(vote(("क", 99), ("फ", 0.97), ("फ", 0.3), c)[::2], ("फ", "reader+groups"))  # two against one
        self.assertFalse(vote(("क", 99), ("फ", 0.97), ("फ", 0.3), c)[3])                          # ...reader sure
        self.assertTrue(vote(("क", 99), ("फ", 0.8), ("फ", 0.3), c)[3])                            # ...reader not sure
        self.assertEqual(vote(("क", 80), ("फ", 0.97), ("क", 0.3), c)[::3], ("क", True))           # reader sure, outvoted
        self.assertEqual(vote(("क", 80), ("फ", 0.8), ("क", 0.3), c)[::3], ("क", False))
        self.assertEqual(vote(("क", 99), ("फ", 0.97), ("ग", 0.3), c)[::3], ("फ", True))           # nobody agrees
        self.assertEqual(vote(("क", 99), ("फ", 0.8), None, c)[::3], ("क", True))
        self.assertEqual(vote(None, ("फ", 0.97), None, c)[::3], ("फ", False))                     # handwriting
        self.assertEqual(vote(None, ("फ", 0.97), ("ग", 0.3), c)[::3], ("फ", True))

    def test_the_reader_votes_only_on_letters_it_was_taught(self):
        known = {"क", "फ"}
        self.assertTrue(taught(("क", 90), None, known, self.cfg))
        self.assertFalse(taught(("म", 99), ("ग", 0.2), known, self.cfg))     # a म group it never learned from
        self.assertTrue(taught(None, None, known, self.cfg))
        self.assertFalse(taught(None, ("म", 0.2), known, self.cfg))

    def test_spaces_and_markers(self):
        def letter(x, text="क", uncertain=False):
            return LetterText(1, 1, (x, 0, 20, 30), text, 0.9, "both", uncertain)
        row = [letter(0), letter(22), letter(60, "ख", True), letter(82, "")]
        mark_spaces(row, self.cfg, printed=True)
        self.assertEqual([x.space_before for x in row], [False, False, True, False])
        self.assertEqual(line_text(row), "कक ख?")
        self.assertEqual(line_text(row, "mark"), "कक [?][?]")
        self.assertEqual(line_text(row, "guess"), "कक [?ख][?]")
        hand = [letter(0), letter(60)]
        mark_spaces(hand, self.cfg, printed=False)
        self.assertFalse(hand[1].space_before)                                       # no spaces in handwriting


class DocxTests(unittest.TestCase):
    def test_a_word_file_with_one_paragraph_per_line_and_a_page_each(self):
        data = write_docx([("1 · p1", ["નારાયણ", "સ્વામી"]), ("2 · p2", ["ક્યારે"])])
        z = zipfile.ZipFile(io.BytesIO(data))
        self.assertEqual(set(z.namelist()), {"[Content_Types].xml", "_rels/.rels", "word/document.xml"})
        doc = minidom.parseString(z.read("word/document.xml"))
        texts = [t.firstChild.data for t in doc.getElementsByTagName("w:t")]
        self.assertEqual(texts, ["1 · p1", "નારાયણ", "સ્વામી", "2 · p2", "ક્યારે"])
        breaks = [b for b in doc.getElementsByTagName("w:br") if b.getAttribute("w:type") == "page"]
        self.assertEqual(len(breaks), 1)


class ConvertTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.lib, self.book, _ = appbook.fresh_copy()
        self.lib.set_book_writing(self.book, "printed")
        self.lib.set_book_config(self.book, Config(language_model=False))       # the rules alone (C15: test_language)
        with self.lib.session() as s:
            self.page = s.scalar(select(Page.id).where(Page.book_id == self.book).order_by(Page.id))
            g = s.scalars(select(LetterGroup).join(Sample, Sample.group_id == LetterGroup.id)
                          .where(Sample.page_id == self.page).order_by(LetterGroup.id)).first()
            g.label_dev, g.label_guj, g.status = "क", "ક", "labelled"
            self.labelled = set(s.scalars(select(Sample.id).where(Sample.group_id == g.id, Sample.page_id == self.page)))
            self.all = list(s.scalars(select(Sample.id).where(Sample.page_id == self.page, Sample.deleted.is_(False))))

    def tearDown(self):
        appbook.cleanup(self.tmp, self.lib)

    def read_as(self, readings):
        return mock.patch("letter_extractor.app.texts._read_lines", return_value=readings)

    def test_a_page_becomes_text_traceable_to_its_letters(self):
        other = next(i for i in self.all if i not in self.labelled)
        readings = {i: ("क", 97.0) for i in self.labelled} | {other: ("ख", 60.0)}
        with self.read_as(readings):
            r = convert_page(self.lib, self.page, reader=lambda rgb: None)
        self.assertEqual(r["readers"], ["tesseract", "groups"])
        got = page_text(self.lib, self.page)
        letters = {x["sample_id"]: x for line in got["lines"] for x in line}
        self.assertEqual(set(letters), set(self.all))                                # every letter, once
        for i in self.labelled:
            self.assertEqual((letters[i]["text_dev"], letters[i]["source"], letters[i]["uncertain"]), ("क", "both", False))
        self.assertTrue(letters[other]["uncertain"])                                 # 0.48: unsure
        self.assertEqual(got["text_guj"].count("ક"), got["text_dev"].count("क"))     # mapped to Gujarati
        self.assertEqual(got["uncertain"], sum(x["uncertain"] for x in letters.values()))
        book = self.lib.get_book(self.book)
        with self.lib.session() as s:
            page = s.get(Page, self.page)
            stem = Path(page.file).stem
        folder = self.lib.book_dir(book) / "text" / "training"
        saved = json.loads((folder / f"{stem}.json").read_text(encoding="utf-8"))
        self.assertEqual(len([x for line in saved["lines"] for x in line]), len(self.all))
        self.assertIn("[?]", (folder / f"{stem}.txt").read_text(encoding="utf-8"))
        with self.read_as({}):                                                       # converting again replaces it
            convert_page(self.lib, self.page, reader=lambda rgb: None)
        with self.lib.session() as s:
            self.assertEqual(s.scalar(select(func.count(PageText.id)).where(PageText.page_id == self.page)), 1)

    def test_a_letter_the_alignment_cannot_place_takes_tesseracts_characters_over_it(self):
        from letter_extractor.app import texts as T
        from letter_extractor.app.db import Line
        from letter_extractor.ocr.tesseract import Char, LineReading, Word
        with self.lib.session() as s:
            line = s.scalars(select(Line).where(Line.page_id == self.page).order_by(Line.number)).first()
            smps = s.scalars(select(Sample).where(Sample.line_id == line.id, Sample.deleted.is_(False))
                             .order_by(Sample.x)).all()
            book = self.lib.get_book(self.book)
            cfg = self.lib.book_config(book)
            dx = max(0, line.x - cfg.line_margin_px)
            first = smps[0]
            # one character over the first letter only: too few for the alignment, which refuses the line
            char = Char("क", (first.x - dx + 2, 5, max(4, first.w - 4), 30), 88.0)
            reading = LineReading([Word(char.box, 88.0, [char])], "", 1.0)
            got = T._read_lines(self.lib, book, cfg, [line], {line.id: smps}, lambda rgb: reading)
        self.assertEqual(got, {first.id: ("क", 88.0)})

    def test_tesseract_alone_is_kept_beside_the_combined_reading(self):
        other = next(i for i in self.all if i not in self.labelled)
        disagree = next(iter(self.labelled))
        readings = {i: ("क", 97.0) for i in self.labelled} | {disagree: ("ख", 92.0), other: ("ग", 96.0)}
        with self.read_as(readings):
            convert_page(self.lib, self.page, reader=lambda rgb: None)
        got = page_text(self.lib, self.page)
        letters = {x["sample_id"]: x for line in got["lines"] for x in line}
        x = letters[disagree]
        self.assertEqual((x["text_dev"], x["uncertain"]), ("ख", True))          # the group (क, close) disagrees
        self.assertEqual((x["t_text_dev"], x["t_uncertain"]), ("ख", False))      # Tesseract alone: 0.74, sure
        self.assertEqual(got["uncertain_tesseract"], sum(v["t_uncertain"] for v in letters.values()))
        c = TestClient(create_app(self.lib, "t"))
        url = f"/files/texts/{self.book}?format=txt&part=training&marker=mark&page_id={self.page}&token=t"
        both, alone = c.get(url).text, c.get(url + "&readers=tesseract").text
        self.assertGreater(both.count("[?]"), alone.count("[?]"))
        c.close()

    def test_handwriting_reads_with_the_labelled_groups_only(self):
        self.lib.set_book_writing(self.book, "handwritten")
        r = convert_page(self.lib, self.page)
        self.assertEqual(r["readers"], ["groups"])
        letters = {x["sample_id"]: x for line in page_text(self.lib, self.page)["lines"] for x in line}
        self.assertTrue(all(letters[i]["text_dev"] == "क" for i in self.labelled))
        self.assertTrue(all(not x["space"] for x in letters.values()))

    def test_a_book_without_read_pages(self):
        with self.assertRaises(LibraryError):
            convert_book(self.lib, self.book, part="read")

    def test_text_and_downloads_in_the_api(self):
        with self.read_as({i: ("क", 97.0) for i in self.labelled}):
            convert_book(self.lib, self.book, part="training", reader=lambda rgb: None)
        c = TestClient(create_app(self.lib, "t"))
        h = {"X-Token": "t"}
        self.assertEqual(c.get(f"/api/pages/{self.page}/text", headers=h).json()["page_id"], self.page)
        listed = c.get(f"/api/books/{self.book}/texts?part=training", headers=h).json()
        self.assertIn(self.page, [t["page_id"] for t in listed])
        r = c.get(f"/files/texts/{self.book}?format=txt&part=training&marker=none&page_id={self.page}&token=t")
        self.assertEqual(r.status_code, 200)
        self.assertIn("ક", r.text)
        self.assertNotIn("[?", r.text)                                               # no marks asked for
        r = c.get(f"/files/texts/{self.book}?format=docx&part=training&token=t")
        self.assertIn("attachment", r.headers["content-disposition"])
        zipfile.ZipFile(io.BytesIO(r.content)).testzip()
        self.assertEqual(c.get(f"/api/pages/999999/text", headers=h).status_code, 404)
        c.close()

    def test_page_images_download_as_one_pdf(self):
        import pypdfium2 as pdfium
        with self.lib.session() as s:
            n = s.scalar(select(func.count(Page.id)).where(Page.book_id == self.book, Page.part == "training"))
        c = TestClient(create_app(self.lib, "t"))
        r = c.get(f"/files/page-images/{self.book}?part=training&page_id={self.page}&token=t")
        self.assertEqual((r.status_code, r.headers["content-type"]), (200, "application/pdf"))
        self.assertIn("attachment", r.headers["content-disposition"])
        self.assertEqual(len(pdfium.PdfDocument(r.content)), 1)
        r = c.get(f"/files/page-images/{self.book}?part=training&token=t")
        self.assertEqual(len(pdfium.PdfDocument(r.content)), n)                      # a PDF page for each page
        r = c.get(f"/files/page-images/{self.book}?part=training&page_ids={self.page},999999&token=t")
        self.assertEqual(len(pdfium.PdfDocument(r.content)), 1)                      # only the ticked pages (C19)
        self.assertEqual(c.get(f"/files/page-images/{self.book}?part=read&token=t").status_code, 404)
        c.close()


if __name__ == "__main__":
    unittest.main()

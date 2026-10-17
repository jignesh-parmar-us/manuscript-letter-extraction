"""F7: test texts with their coverage per build, and the downloads (image, PDF, Word).

Light on purpose: F5's tiny font (squares), one hand-checked line.
"""
import io
import tempfile
import unittest
import re
import zipfile
import zlib
from pathlib import Path

import cv2
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from letter_extractor.app.db import BOOK, Book, Line, LineTruth, Page, ReadingModel, ReadingModelDataset
from font_maker import export
from font_maker.glyphs import GlyphMaker
from font_maker.projects import Projects
from font_maker.store import Store
from font_maker.texts import Texts
from font_maker.tryit import classify
from test_f0 import make_library
from test_f5 import make_font_groups


class F7Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_library(Path(self.tmp.name))
        make_font_groups(self.root)
        engine = create_engine(f"sqlite:///{self.root / 'library.db'}")
        with Session(engine) as s:                        # one hand-checked line, on a book that reads with dataset 1
            model = ReadingModel(name="Test book", folder="0002-test-book")
            s.add(model)
            s.flush()
            s.add(ReadingModelDataset(model_id=model.id, dataset_id=1))
            book = Book(name="Test book", kind=BOOK, folder="0002-test-book", input_dir="", reading_model_id=model.id)
            s.add(book)
            s.flush()
            page = Page(book_id=book.id, file="p.png", part="read", folder="read")
            s.add(page)
            s.flush()
            line = Line(page_id=page.id, number=1, x=0, y=0, w=10, h=10, ink="black", image="l.png")
            s.add(line)
            s.flush()
            s.add(LineTruth(line_id=line.id, text_dev="का कि ग", tesseract_dev=""))
            s.commit()
        engine.dispose()
        self.store = Store(self.root)
        self.projects = Projects(self.store.fonts_dir)
        self.font = self.projects.create("Test Font", [1])["id"]
        self.maker = GlyphMaker(self.store, self.projects)
        self.texts = Texts(self.store, self.projects)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_texts_and_their_coverage_with_the_build_before(self):
        saved = self.texts.save(self.font, "Letter", "क का")
        self.assertEqual([t["name"] for t in self.texts.list(self.font)], ["Hand-checked lines of Test book", "Letter"])
        self.maker.build(self.font)
        self.projects.set_filled(self.font, ["ग"], True)
        self.maker.build(self.font)
        truth = self.texts.coverage(self.font, self.maker.reports(self.font))[0]
        newest, before = truth["builds"]
        self.assertEqual((newest["build"], newest["book"], newest["filled"]), (2, 2, 1))
        self.assertEqual((before["build"], before["missing"]), (1, 1))
        self.assertEqual(newest["gaps"], [("ग", 1)])
        self.texts.delete(self.font, saved["id"])
        self.assertEqual(len(self.texts.list(self.font)), 1)

    def test_downloads_have_the_text_in_the_font(self):
        report = self.maker.build(self.font)
        path = self.store.fonts_dir / self.font / "builds" / report["file"]
        img = cv2.imdecode(np.frombuffer(export.png(path, "का कि\nक", 48), np.uint8), cv2.IMREAD_GRAYSCALE)
        self.assertLess(img.min(), 100)                                    # ink
        self.assertGreater(img.shape[0], img.shape[1] * 0.3)               # two lines

        data = export.pdf(path, "का कि", 18)
        self.assertTrue(data.startswith(b"%PDF-1.4"))
        streams = [zlib.decompress(s).decode() for s in re.findall(rb"stream\n(.*?)\nendstream", data, re.S)]
        self.assertEqual(sum(s.endswith("\nf") for s in streams), 2)      # two glyphs, stored once each
        self.assertEqual(streams[-1].count(" Do "), 2)                      # and placed on the page

        with zipfile.ZipFile(io.BytesIO(export.docx(path, "Test Font", "का कि\nक", 18))) as z:
            doc = z.read("word/document.xml").decode()
            table = z.read("word/fontTable.xml").decode()
            key = re.search(r'w:fontKey="(\{[^}]+\})"', table).group(1)
            self.assertEqual(export.obfuscate(z.read("word/fonts/font1.odttf"), key), path.read_bytes())
        self.assertEqual(doc.count("<w:p>"), 2)
        self.assertIn('w:cs="Test Font"', doc)

    def test_check_line_has_positions_and_reasons(self):
        out = classify("कि गा", {"labels": ["कि", "ा"], "filled": [], "missing": ["ग"]})
        ga = out["aksharas"][-1]
        self.assertEqual((ga["text"], ga["start"], ga["kind"], ga["detail"]), ("गा", 3, "missing", [{"char": "ग", "kind": "missing"}]))


if __name__ == "__main__":
    unittest.main()

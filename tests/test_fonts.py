"""Custom fonts for the text screens (T1, T3; docs/CUSTOM_FONT_PLAN.md): the library's font store, its API and
the font in Word files."""
import io
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient                           # noqa: E402
from letter_extractor.app.api import create_app                    # noqa: E402
from letter_extractor.app.fonts import FontError, FontNotFound, Fonts, from_collection, inspect   # noqa: E402
from letter_extractor.app.library import Library                   # noqa: E402
from letter_extractor.ocr.docx import obfuscate, write_docx         # noqa: E402

GUJARATI = range(0x0A95, 0x0AB9 + 1)
DEVANAGARI = range(0x0915, 0x0939 + 1)


def make_font(chars, family="Test Sans", fs_type=0, cff=False) -> bytes:
    """A tiny font with an empty square for every character of `chars` (code points)."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.t2CharStringPen import T2CharStringPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    names = [".notdef"] + [f"u{c:04X}" for c in chars]
    fb = FontBuilder(1000, isTTF=not cff)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap({c: f"u{c:04X}" for c in chars})

    def draw(pen):
        pen.moveTo((100, 0))
        pen.lineTo((100, 500))
        pen.lineTo((400, 500))
        pen.lineTo((400, 0))
        pen.closePath()
    if cff:
        strings = {}
        for n in names:
            pen = T2CharStringPen(500, None)
            draw(pen)
            strings[n] = pen.getCharString()
        fb.setupCFF(family.replace(" ", ""), {"FullName": family}, strings, {})
    else:
        glyphs = {}
        for n in names:
            pen = TTGlyphPen(None)
            draw(pen)
            glyphs[n] = pen.glyph()
        fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({n: (500, 100) for n in names})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": family, "styleName": "Regular"})
    fb.setupOS2(fsType=fs_type)
    fb.setupPost()
    out = io.BytesIO()
    fb.save(out)
    return out.getvalue()


class InspectTests(unittest.TestCase):
    def test_scripts_chars_and_embedding(self):
        info = inspect(make_font([*GUJARATI, 0x0964]))
        self.assertEqual((info.family, info.scripts, info.embeddable), ("Test Sans", ["gujarati"], True))
        self.assertFalse(info.joins)                      # no OpenType rules in the test font
        self.assertIn("ક", info.chars)
        self.assertIn("।", info.chars)                    # the danda, used in Gujarati text too
        self.assertEqual(inspect(make_font([*DEVANAGARI, *GUJARATI])).scripts, ["gujarati", "devanagari"])
        self.assertFalse(inspect(make_font(GUJARATI, fs_type=0x0002)).embeddable)    # restricted
        self.assertTrue(inspect(make_font(GUJARATI, fs_type=0x0008)).embeddable)     # editable
        self.assertFalse(inspect(make_font(GUJARATI, cff=True)).embeddable)          # Word embeds TrueType only

    def test_refused(self):
        with self.assertRaises(FontError) as e:
            inspect(make_font(range(0x21, 0x7F)))        # an old-style font: letters on English key codes
        self.assertIn("no Gujarati or Devanagari letters", str(e.exception))
        with self.assertRaises(FontError):
            inspect(b"not a font at all, just some bytes......")
        with self.assertRaises(FontError):
            inspect(b"ttcf" + bytes(40))

    def test_collection(self):
        from fontTools.ttLib import TTFont
        from fontTools.ttLib.ttCollection import TTCollection
        bold, regular = make_font(DEVANAGARI, "Coll"), make_font(GUJARATI, "Coll")
        ttc = TTCollection()
        ttc.fonts = [TTFont(io.BytesIO(bold)), TTFont(io.BytesIO(regular))]
        ttc.fonts[0]["name"].setName("Bold", 2, 3, 1, 0x409)
        ttc.fonts[0]["name"].setName("Bold", 2, 1, 0, 0)
        out = io.BytesIO()
        ttc.save(out)
        self.assertEqual(inspect(from_collection(out.getvalue())).scripts, ["gujarati"])   # the Regular one
        with tempfile.TemporaryDirectory() as d:
            got = Fonts(Path(d)).add_upload("Gujarati Sangam MN.ttc", out.getvalue())
            self.assertEqual(got["scripts"], ["gujarati"])
            self.assertTrue((Path(d) / "display_fonts" / f"{got['id']}.ttf").is_file())


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fonts = Fonts(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fontmaker_project(self, pid="f0001", name="Book Six", build=True):
        folder = self.tmp / "fonts" / pid
        (folder / "builds").mkdir(parents=True)
        (folder / "font.json").write_text(json.dumps({"id": pid, "name": name}), encoding="utf-8")
        if build:
            (folder / "builds" / "BookSix-1.ttf").write_bytes(make_font(DEVANAGARI, "Book Six"))
        return folder

    def test_upload_list_remove(self):
        data = make_font(GUJARATI, "Saral Gujarati")
        got = self.fonts.add_upload("saral.ttf", data)
        self.assertEqual((got["name"], got["source"], got["scripts"]), ("Saral Gujarati", "upload", ["gujarati"]))
        self.assertEqual(self.fonts.add_upload("copy.ttf", data)["id"], got["id"])    # the same file: one font
        self.assertEqual([f["id"] for f in self.fonts.list()], [got["id"]])
        self.assertEqual(self.fonts.path(got["id"]).read_bytes(), data)
        self.assertEqual(self.fonts.for_word(got["id"]), ("Saral Gujarati", data))
        with self.assertRaises(FontError):
            self.fonts.add_upload("saral.woff", data)
        self.fonts.remove(got["id"])
        self.assertEqual(self.fonts.list(), [])
        self.assertEqual(list((self.tmp / "display_fonts").iterdir()), [])
        with self.assertRaises(FontNotFound):
            self.fonts.path("../library")

    def test_fontmaker_reference(self):
        folder = self.fontmaker_project()
        self.fontmaker_project("f0002", "Not built", build=False)
        self.assertEqual([(f["project"], f["added"]) for f in self.fonts.fontmaker_fonts()], [("f0001", False)])
        got = self.fonts.add_fontmaker("f0001")
        self.assertEqual((got["id"], got["name"], got["scripts"]), ("fm-f0001", "Book Six", ["devanagari"]))
        self.assertTrue(self.fonts.fontmaker_fonts()[0]["added"])
        with self.assertRaises(FontError):
            self.fonts.add_fontmaker("f0002")
        self.fonts.remove("fm-f0001")                     # the reference only: Font Maker's files stay
        self.assertTrue((folder / "builds" / "BookSix-1.ttf").is_file())
        self.assertEqual(self.fonts.list(), [])


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.lib = Library(self.tmp / "lib")
        self.client = TestClient(create_app(self.lib, "t"), headers={"X-Token": "t"})

    def tearDown(self):
        self.client.close()
        self.lib.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_routes(self):
        c = self.client
        data = make_font(GUJARATI)
        got = c.post("/api/fonts/upload", params={"name": "t.ttf"}, content=data).json()
        self.assertEqual([f["id"] for f in c.get("/api/fonts").json()], [got["id"]])
        r = c.get(f"/files/fonts/{got['id']}")
        self.assertEqual((r.status_code, r.content), (200, data))
        old = c.post("/api/fonts/upload", params={"name": "old.ttf"}, content=make_font(range(0x21, 0x7F)))
        self.assertEqual(old.status_code, 400)
        self.assertIn("old-style", old.json()["detail"])          # the warning names old-style fonts
        self.assertEqual(got["size"], 1.0)
        self.assertEqual(c.patch(f"/api/fonts/{got['id']}", json={"size": 1.1}).json()["size"], 1.1)   # A+
        self.assertEqual(c.get("/api/fonts").json()[0]["size"], 1.1)
        self.assertEqual(c.patch(f"/api/fonts/{got['id']}", json={"size": 9}).status_code, 422)
        self.assertEqual(c.get("/api/fonts/fontmaker").json(), [])
        self.assertEqual(c.post("/api/fonts/fontmaker", json={"project": "f0001"}).status_code, 404)
        self.assertEqual(c.delete(f"/api/fonts/{got['id']}").status_code, 204)
        self.assertEqual(c.get(f"/files/fonts/{got['id']}").status_code, 404)
        self.assertEqual(c.get("/api/fonts").json(), [])


class WordTests(unittest.TestCase):
    def test_obfuscation_round_trip(self):
        data = make_font(GUJARATI)
        key = "{0D5C0B6A-1234-4F00-9ABC-00112233AABB}"
        hidden = obfuscate(data, key)
        self.assertNotEqual(hidden[:32], data[:32])
        self.assertEqual(hidden[32:], data[32:])
        self.assertEqual(hidden[0], data[0] ^ 0xBB)      # the key's last byte comes first
        self.assertEqual(obfuscate(hidden, key), data)

    def test_font_named_and_embedded(self):
        data = make_font(GUJARATI, 'Saral "Bold"')
        z = zipfile.ZipFile(io.BytesIO(write_docx([("", ["નારાયણ"])], 'Saral "Bold"', data)))
        doc = z.read("word/document.xml").decode()
        self.assertIn('w:cs="Saral &quot;Bold&quot;"', doc)
        table = z.read("word/fontTable.xml").decode()
        key = table.split('w:fontKey="')[1].split('"')[0]
        self.assertEqual(obfuscate(z.read("word/fonts/font1.odttf"), key), data)
        self.assertIn("embedTrueTypeFonts", z.read("word/settings.xml").decode())
        self.assertIn("odttf", z.read("[Content_Types].xml").decode())
        bigger = zipfile.ZipFile(io.BytesIO(write_docx([("", ["નારાયણ"])], "Saral", None, 1.25)))
        self.assertIn('<w:sz w:val="35"/>', bigger.read("word/document.xml").decode())   # 14 pt × 1.25
        plain = zipfile.ZipFile(io.BytesIO(write_docx([("", ["નારાયણ"])], "Shruti")))   # name only
        self.assertNotIn("word/fontTable.xml", plain.namelist())
        self.assertIn('w:cs="Shruti"', plain.read("word/document.xml").decode())


if __name__ == "__main__":
    unittest.main()

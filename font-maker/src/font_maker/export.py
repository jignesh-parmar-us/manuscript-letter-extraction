"""Downloads (F7): a text in the newest build of the font, as an image, a PDF or a Word document.

  - **Image (.png)** and **PDF:** the text is shaped with HarfBuzz (the same shaping as the Try it box in
    Chrome) and each glyph's outline is drawn, so they need no font to be viewed. The image is drawn 4 times
    larger and scaled down (smooth edges); the PDF has every glyph as a vector path (sharp at any zoom), on A4
    pages, lines wrapped at spaces; each glyph is stored once in the PDF (a form) and placed where it is
    used, and the image fills each glyph only in its own small box, so both stay quick. The PDF's text
    cannot be searched or copied (no text layer yet).
  - **Word (.docx):** a small document written directly (a zip of XML, no extra package), every line a
    paragraph in this font, with the font **embedded** the way Word embeds fonts: `word/fonts/font1.odttf`,
    whose first 32 bytes are XORed with a key that `fontTable.xml` names (ECMA-376 part 1, 17.8.1). Word for
    Mac shows embedded fonts from version 16.17; otherwise the document still names the font.
  - Text (.txt) is made by the screen itself.
"""
from __future__ import annotations

import io
import uuid
import zipfile
import zlib
from pathlib import Path
from typing import Dict, List, Tuple
from xml.sax.saxutils import escape

import cv2
import numpy as np
import uharfbuzz as hb
from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont

SUPER = 4                    # the image is drawn this many times larger, then scaled down
MAX_SIDE = 12000             # pixels: a larger image is drawn smaller
A4 = (595.0, 842.0)          # points
MARGIN = 50.0

Glyph = Tuple[str, float, float, int]          # name, x, y (font units), cluster


class _Font:
    def __init__(self, path: Path):
        self.tt = TTFont(path)
        self.glyphs = self.tt.getGlyphSet()
        self.hb = hb.Font(hb.Face(hb.Blob.from_file_path(str(path))))
        self.upm = self.tt["head"].unitsPerEm
        self.ascent = self.tt["hhea"].ascent
        self.descent = self.tt["hhea"].descent             # negative

    def shape(self, line: str) -> Tuple[List[Glyph], float]:
        buf = hb.Buffer()
        buf.add_str(line)
        buf.guess_segment_properties()
        hb.shape(self.hb, buf, {})
        out, x = [], 0.0
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            out.append((self.hb.glyph_to_string(info.codepoint), x + pos.x_offset, pos.y_offset, info.cluster))
            x += pos.x_advance
        return out, x


def _wrap(font: _Font, line: str, width: float) -> List[Tuple[List[Glyph], float]]:
    """The shaped line, broken at spaces so no part is wider than `width` (font units)."""
    glyphs, total = font.shape(line)
    if total <= width or not glyphs:
        return [(glyphs, total)]
    parts, start_x, last_space, cur = [], 0.0, None, []
    for g in glyphs:
        if g[0] == "space":
            last_space = len(cur)
        cur.append(g)
        if g[1] - start_x > width and last_space is not None:
            head, tail = cur[:last_space], cur[last_space + 1:]
            parts.append([(n, x - start_x, y, c) for n, x, y, c in head])
            start_x = tail[0][1] if tail else g[1]
            cur, last_space = tail, None
    parts.append([(n, x - start_x, y, c) for n, x, y, c in cur])
    out = []
    for p in parts:
        right = max((x + font.glyphs[n].width for n, x, _, _ in p), default=0.0)
        out.append((p, right))
    return out


class _Polygons(BasePen):
    """A glyph's contours as polygons (curves sampled), in font units."""

    def __init__(self, glyphset):
        super().__init__(glyphset)
        self.polys: List[List[Tuple[float, float]]] = []
        self.cur: List[Tuple[float, float]] = []

    def _moveTo(self, p):
        self.cur = [p]

    def _lineTo(self, p):
        self.cur.append(p)

    def _curveToOne(self, a, b, c):
        p0 = np.array(self.cur[-1])
        a, b, c = np.array(a), np.array(b), np.array(c)
        for t in np.linspace(1 / 6, 1, 6):
            self.cur.append(tuple((1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * a + 3 * (1 - t) * t * t * b + t ** 3 * c))

    def _qCurveToOne(self, a, c):
        p0, a, c = np.array(self.cur[-1]), np.array(a), np.array(c)
        for t in np.linspace(1 / 6, 1, 6):
            self.cur.append(tuple((1 - t) ** 2 * p0 + 2 * (1 - t) * t * a + t * t * c))

    def _closePath(self):
        if len(self.cur) > 2:
            self.polys.append(self.cur)
        self.cur = []


def png(path: Path, text: str, px_per_em: int = 64) -> bytes:
    """The text as a picture (black on white), one line per line of text."""
    font = _Font(path)
    lines = [font.shape(line) for line in text.split("\n")]
    line_h = font.ascent - font.descent
    pad = 0.3 * font.upm
    w_units = max((w for _, w in lines), default=0.0) + 2 * pad
    h_units = len(lines) * line_h + 2 * pad
    scale = px_per_em / font.upm
    scale = min(scale, MAX_SIDE / max(w_units, 1), MAX_SIDE / max(h_units, 1))
    s = scale * SUPER
    ink = np.zeros((max(1, int(h_units * s)), max(1, int(w_units * s))), np.uint8)
    shapes: Dict[str, List[np.ndarray]] = {}                # each glyph's contours, made once (font units)
    for k, (glyphs, _) in enumerate(lines):
        base = pad + font.ascent + k * line_h
        for name, x, y, _ in glyphs:
            if name not in shapes:
                pen = _Polygons(font.glyphs)
                font.glyphs[name].draw(pen)
                shapes[name] = [np.array(p, np.float64) for p in pen.polys]
            if not shapes[name]:
                continue
            pts = [np.column_stack(((pad + x + p[:, 0]) * s, (base - y - p[:, 1]) * s)) for p in shapes[name]]
            x0, y0 = (int(np.floor(min(q[:, i].min() for q in pts))) for i in (0, 1))
            x1, y1 = (int(np.ceil(max(q[:, i].max() for q in pts))) + 1 for i in (0, 1))
            x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, ink.shape[1]), min(y1, ink.shape[0])
            if x1 <= x0 or y1 <= y0:
                continue
            mask = np.zeros((y1 - y0, x1 - x0), np.uint8)   # only the glyph's own box
            for q in pts:                                   # within one glyph holes are inside outers
                one = np.zeros_like(mask)
                cv2.fillPoly(one, [(q - (x0, y0)).round().astype(np.int32)], 1)
                mask ^= one
            ink[y0:y1, x0:x1] |= mask                       # neighbours may overlap (joined headlines)
    small = cv2.resize(ink.astype(np.float32), (max(1, ink.shape[1] // SUPER), max(1, ink.shape[0] // SUPER)),
                       interpolation=cv2.INTER_AREA)
    ok, data = cv2.imencode(".png", (255 - small * 255).clip(0, 255).astype(np.uint8))
    return data.tobytes()


class _PdfPath(BasePen):
    """A glyph's outline as PDF path operators, in font units (PDF y points up, like the font)."""

    def __init__(self, glyphset):
        super().__init__(glyphset)
        self.ops: List[str] = []
        self.last = (0, 0)

    def _moveTo(self, p):
        self.ops.append(f"{p[0]:g} {p[1]:g} m")
        self.last = p

    def _lineTo(self, p):
        self.ops.append(f"{p[0]:g} {p[1]:g} l")
        self.last = p

    def _curveToOne(self, a, b, c):
        self.ops.append(f"{a[0]:g} {a[1]:g} {b[0]:g} {b[1]:g} {c[0]:g} {c[1]:g} c")
        self.last = c

    def _qCurveToOne(self, a, c):
        p0 = self.last                                      # a quadratic curve as a cubic one
        c1 = (p0[0] + 2 / 3 * (a[0] - p0[0]), p0[1] + 2 / 3 * (a[1] - p0[1]))
        c2 = (c[0] + 2 / 3 * (a[0] - c[0]), c[1] + 2 / 3 * (a[1] - c[1]))
        self._curveToOne(tuple(round(v, 1) for v in c1), tuple(round(v, 1) for v in c2), c)

    def _closePath(self):
        self.ops.append("h")


def pdf(path: Path, text: str, size_pt: float = 18.0) -> bytes:
    """The text on A4 pages as vector shapes: each glyph is stored once (a form) and placed where it is used."""
    font = _Font(path)
    k = size_pt / font.upm
    line_h = (font.ascent - font.descent) * k * 1.15
    width_units = (A4[0] - 2 * MARGIN) / k
    rows = [part for line in text.split("\n") for part in _wrap(font, line, width_units)]
    per_page = max(1, int((A4[1] - 2 * MARGIN) // line_h))
    pages = [rows[i:i + per_page] for i in range(0, len(rows), per_page)] or [[]]

    forms: Dict[str, int] = {}                               # glyph name -> form number
    form_ops: List[str] = []
    streams = []
    for page in pages:
        ops = ["0 g"]
        for n, (glyphs, _) in enumerate(page):
            base = A4[1] - MARGIN - font.ascent * k - n * line_h
            for name, x, y, _ in glyphs:
                if name not in forms:
                    pen = _PdfPath(font.glyphs)
                    font.glyphs[name].draw(pen)
                    forms[name] = len(form_ops)
                    form_ops.append("\n".join(pen.ops + ["f"]) if pen.ops else "")
                if form_ops[forms[name]]:
                    ops.append(f"q {k:.5f} 0 0 {k:.5f} {MARGIN + x * k:.2f} {base + y * k:.2f} cm /G{forms[name]} Do Q")
        streams.append(zlib.compress("\n".join(ops).encode("ascii")))

    # objects: 1 catalog, 2 pages, then the forms, then per page its page and its content
    objects: List[bytes] = [b"", b""]
    form_ids = []
    for body in form_ops:
        data = zlib.compress(body.encode("ascii"))
        form_ids.append(len(objects) + 1)
        objects.append(b"<< /Type /XObject /Subtype /Form /BBox [-5000 -5000 10000 10000] /Resources << >> "
                       + f"/Length {len(data)} /Filter /FlateDecode >>\nstream\n".encode() + data + b"\nendstream")
    xobjects = " ".join(f"/G{i} {fid} 0 R" for i, fid in enumerate(form_ids))
    page_ids = []
    for stream in streams:
        page_ids.append(len(objects) + 1)
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {A4[0]:.0f} {A4[1]:.0f}] "
                       f"/Contents {len(objects) + 2} 0 R /Resources << /XObject << {xobjects} >> >> >>".encode())
        objects.append(f"<< /Length {len(stream)} /Filter /FlateDecode >>\nstream\n".encode() + stream + b"\nendstream")
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = " ".join(f"{i} 0 R" for i in page_ids)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode()

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for n, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(f"{n} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def obfuscate(font: bytes, key: str) -> bytes:
    """Word's embedded-font scrambling (it undoes itself): the first 32 bytes XORed with the key's 16 bytes,
    taken from the GUID `{…}` in reverse order."""
    k = bytes.fromhex(key.strip("{}").replace("-", ""))[::-1]
    head = bytes(b ^ k[i % 16] for i, b in enumerate(font[:32]))
    return head + font[32:]


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def docx(path: Path, family: str, text: str, size_pt: float = 18.0) -> bytes:
    """A Word document with the text in this font, the font embedded."""
    key = "{" + str(uuid.uuid4()).upper() + "}"
    fam = escape(family, {'"': "&quot;"})
    half_pt = int(round(size_pt * 2))
    run = (f'<w:rPr><w:rFonts w:ascii="{fam}" w:hAnsi="{fam}" w:cs="{fam}"/><w:sz w:val="{half_pt}"/>'
           f'<w:szCs w:val="{half_pt}"/><w:lang w:bidi="hi-IN"/></w:rPr>')
    paras = "".join(f'<w:p><w:r>{run}<w:t xml:space="preserve">{escape(line)}</w:t></w:r></w:p>'
                    for line in text.split("\n"))
    files = {
        "[Content_Types].xml":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="odttf" ContentType="application/vnd.openxmlformats-officedocument.obfuscatedFont"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/fontTable.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml"/>'
            '<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
            '</Types>',
        "_rels/.rels":
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{REL}">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>',
        "word/_rels/document.xml.rels":
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{REL}">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable" Target="fontTable.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>'
            '</Relationships>',
        "word/_rels/fontTable.xml.rels":
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{REL}">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/font" Target="fonts/font1.odttf"/>'
            '</Relationships>',
        "word/document.xml":
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{W}" xmlns:r="{R}">'
            f'<w:body>{paras}<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
            '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" w:header="0" w:footer="0" w:gutter="0"/>'
            '</w:sectPr></w:body></w:document>',
        "word/fontTable.xml":
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:fonts xmlns:w="{W}" xmlns:r="{R}">'
            f'<w:font w:name="{fam}"><w:charset w:val="00"/><w:family w:val="auto"/><w:pitch w:val="variable"/>'
            f'<w:embedRegular r:id="rId1" w:fontKey="{key}"/></w:font></w:fonts>',
        "word/settings.xml":
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:settings xmlns:w="{W}">'
            '<w:embedTrueTypeFonts/></w:settings>',
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in files.items():
            z.writestr(name, body)
        z.writestr("word/fonts/font1.odttf", obfuscate(Path(path).read_bytes(), key))
    return out.getvalue()

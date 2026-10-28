"""A small Word (.docx) writer for converted text (C16b), without a new package.

A .docx file is a zip of a few XML files. Each manuscript line becomes a paragraph; each page starts on
a new page, after a small heading with its name. The text is set in a Gujarati font (Shruti, which
Windows has; Word substitutes a Gujarati font where it is missing) at 14 pt; Word joins the letters
itself (conjuncts and vowel signs), as browsers do.

A custom font (T3, docs/plans/done/CUSTOM_FONT_PLAN.md): the runs ask for its family name, and when its bytes are given
the font is embedded in the file (`word/fonts/font1.odttf`, obfuscated as ECMA-376 Part 1 §17.8.1 says), so
the text looks the same on a computer without that font.
"""
from __future__ import annotations

import io
import uuid
import zipfile
from typing import List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

FONT = "Shruti"

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
{extra}</Types>"""

_EMBEDDED_TYPES = """<Default Extension="odttf" ContentType="application/vnd.openxmlformats-officedocument.obfuscatedFont"/>
<Override PartName="/word/fontTable.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml"/>
<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
"""

_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_RELS_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
_DOCUMENT_RELS = (_RELS_HEAD + f'<Relationship Id="rId1" Type="{_REL}/fontTable" Target="fontTable.xml"/>'
                  f'<Relationship Id="rId2" Type="{_REL}/settings" Target="settings.xml"/></Relationships>')
_FONT_RELS = _RELS_HEAD + f'<Relationship Id="rId1" Type="{_REL}/font" Target="fonts/font1.odttf"/></Relationships>'

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def obfuscate(font: bytes, key: str) -> bytes:
    """A font as Word keeps an embedded font: its first 32 bytes XOR-ed with the bytes of the GUID `key`
    ("{XXXXXXXX-XXXX-...}") in reverse order (ECMA-376 Part 1 §17.8.1). Doing it twice gives the font back."""
    digits = key.strip("{}").replace("-", "")
    k = bytes(int(digits[i:i + 2], 16) for i in range(30, -2, -2))
    head = bytes(b ^ k[i % 16] for i, b in enumerate(font[:32]))
    return head + font[32:]


def _run(text: str, size: int, bold: bool = False, font: str = FONT) -> str:
    font = escape(font, {'"': "&quot;"})
    fonts = f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}" w:cs="{font}"/>'
    props = f"<w:rPr>{fonts}{'<w:b/><w:bCs/>' if bold else ''}<w:sz w:val=\"{size}\"/><w:szCs w:val=\"{size}\"/><w:lang w:bidi=\"gu-IN\"/></w:rPr>"
    return f'<w:r>{props}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def _paragraph(text: str, size: int = 28, bold: bool = False, page_break: bool = False, font: str = FONT) -> str:
    brk = '<w:r><w:br w:type="page"/></w:r>' if page_break else ""
    return f"<w:p>{brk}{_run(text, size, bold, font) if text else ''}</w:p>"


def write_docx(pages: Sequence[Tuple[str, List[str]]], font: Optional[str] = None,
               embed: Optional[bytes] = None, scale: float = 1.0) -> bytes:
    """A Word file of (page heading, lines) pairs. Returns the file's bytes. `font`: the family name of the text
    (default Shruti); `embed`: that font's file, embedded in the Word file; `scale`: the text's size against 14 pt
    (a custom font whose letters are drawn smaller than the normal fonts' is set larger)."""
    font = font or FONT
    size = max(2, round(28 * scale))          # half-points
    body: List[str] = []
    for i, (heading, lines) in enumerate(pages):
        if heading:
            body.append(_paragraph(heading, size=20, bold=True, page_break=i > 0, font=font))
        elif i > 0:
            body.append(_paragraph("", page_break=True))
        body += [_paragraph(line, size=size, font=font) for line in lines]
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document {_NS}><w:body>'
                + "".join(body) + "<w:sectPr/></w:body></w:document>")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES.format(extra=_EMBEDDED_TYPES if embed else ""))
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/document.xml", document)
        if embed:
            key = "{" + str(uuid.uuid4()).upper() + "}"
            name = escape(font, {'"': "&quot;"})
            z.writestr("word/_rels/document.xml.rels", _DOCUMENT_RELS)
            z.writestr("word/settings.xml", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                                            f"<w:settings {_NS}><w:embedTrueTypeFonts/></w:settings>")
            z.writestr("word/fontTable.xml", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                                             f'<w:fonts {_NS} xmlns:r="{_REL}"><w:font w:name="{name}">'
                                             f'<w:charset w:val="00"/><w:embedRegular r:id="rId1" w:fontKey="{key}"/>'
                                             "</w:font></w:fonts>")
            z.writestr("word/_rels/fontTable.xml.rels", _FONT_RELS)
            z.writestr("word/fonts/font1.odttf", obfuscate(embed, key))
    return out.getvalue()

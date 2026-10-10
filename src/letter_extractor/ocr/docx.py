"""A small Word (.docx) writer for converted text (C16b), without a new package.

A .docx file is a zip of a few XML files. Each manuscript line becomes a paragraph; each page starts on
a new page, after a small heading with its name. The text is set in a Gujarati font (Shruti, which
Windows has; Word substitutes a Gujarati font where it is missing) at 14 pt; Word joins the letters
itself (conjuncts and vowel signs), as browsers do.
"""
from __future__ import annotations

import io
import zipfile
from typing import List, Sequence, Tuple
from xml.sax.saxutils import escape

FONT = "Shruti"

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _run(text: str, size: int, bold: bool = False) -> str:
    fonts = f'<w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:cs="{FONT}"/>'
    props = f"<w:rPr>{fonts}{'<w:b/><w:bCs/>' if bold else ''}<w:sz w:val=\"{size}\"/><w:szCs w:val=\"{size}\"/><w:lang w:bidi=\"gu-IN\"/></w:rPr>"
    return f'<w:r>{props}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def _paragraph(text: str, size: int = 28, bold: bool = False, page_break: bool = False) -> str:
    brk = '<w:r><w:br w:type="page"/></w:r>' if page_break else ""
    return f"<w:p>{brk}{_run(text, size, bold) if text else ''}</w:p>"


def write_docx(pages: Sequence[Tuple[str, List[str]]]) -> bytes:
    """A Word file of (page heading, lines) pairs. Returns the file's bytes."""
    body: List[str] = []
    for i, (heading, lines) in enumerate(pages):
        if heading:
            body.append(_paragraph(heading, size=20, bold=True, page_break=i > 0))
        elif i > 0:
            body.append(_paragraph("", page_break=True))
        body += [_paragraph(line) for line in lines]
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document {_NS}><w:body>'
                + "".join(body) + "<w:sectPr/></w:body></w:document>")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/document.xml", document)
    return out.getvalue()

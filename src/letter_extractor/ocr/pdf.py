"""PDF pages to images for Read Book (C16a), with pypdfium2.

Every page is drawn at `dpi` and saved as a JPEG (quality 95: a manuscript page at 300 dpi is about
1 MB, where a PNG would be several) named page-0001.jpg, page-0002.jpg ... so the files sort in page
order. The PDF itself is only read.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional


@dataclass
class PageDone:
    """Progress of one page, in the form the app's jobs show (file, status, message, seconds)."""
    file: str
    status: str
    message: str
    seconds: float


class PdfError(ValueError):
    pass


def pdf_pages(pdf: Path, out: Path, dpi: int = 300, progress: Optional[Callable] = None,
              cancel: Optional[Callable[[], bool]] = None) -> List[str]:
    """Draw every page of `pdf` into `out` (made if needed). Returns the file names in page order."""
    import pypdfium2 as pdfium
    try:
        doc = pdfium.PdfDocument(str(pdf))
    except Exception as e:                               # pdfium raises its own error types
        raise PdfError(f"{Path(pdf).name} could not be opened as a PDF: {e}") from e
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    names: List[str] = []
    try:
        total = len(doc)
        if total == 0:
            raise PdfError(f"{Path(pdf).name} has no pages.")
        for i in range(total):
            if cancel and cancel():
                break
            t = time.time()
            page = doc[i]
            image = page.render(scale=dpi / 72).to_pil()
            name = f"page-{i + 1:04d}.jpg"
            image.convert("RGB").save(out / name, quality=95)
            page.close()
            names.append(name)
            if progress:
                progress(i + 1, total, PageDone(name, "OK", f"{image.width} x {image.height} px", time.time() - t))
    finally:
        doc.close()
    return names

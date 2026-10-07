"""Fixing cuts and adding samples by hand (C5f, FR-8).

- `crop_sample`   a new sample from the ink inside a box drawn on a page (source "cropped")
- `join_samples`  two or more samples of one page become one (source "joined")
- `split_sample`  a sample is cut in two at a column (source "split")
- `upload_sample` a letter image from a file (source "uploaded", no page position)
- `line_context`  a picture of a sample on its line, with its neighbours, for the review screens

New samples start unsure, with an image, an ink mask and a fingerprint, so the review screens show a
suggested group for them. Every operation is an action of `actions.py`: replaced samples are marked
deleted (not removed) and new ones are recorded as "did not exist before", so undo and redo work.

The ink of a page comes from page preparation (C1), computed when first needed and cached in the
book folder (`cache/<page>_ink.npz`, checked against the page's checksum).
"""
from __future__ import annotations

import base64
import io
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select

from .. import io_utils
from ..features import fingerprint
from ..letters import Letter, letter_image
from ..prepare import PreparedPage, prepare_page
from .actions import ActionError, _Change, _result
from .db import Book, Line, Page, Sample
from .library import Library, NotFound, file_sha256

Box = Tuple[int, int, int, int]


# ---- the ink of a page ----------------------------------------------------------------------------
def page_ink(lib: Library, book: Book, page: Page) -> PreparedPage:
    """The page with its black and red ink masks (C1), cached in the book folder."""
    src = Path(book.input_dir) / page.file
    if not src.is_file():
        raise ActionError(f"The page image {page.file} is missing from the input folder.")
    rgb, _ = io_utils.load_image(src)
    cache = lib.book_dir(book) / "cache" / f"{Path(page.file).stem}_ink.npz"
    if cache.is_file():
        data = np.load(cache)
        if str(data["sha256"]) == page.sha256 and tuple(data["shape"]) == rgb.shape[:2]:
            h, w = rgb.shape[:2]
            black = np.unpackbits(data["black"])[: h * w].reshape(h, w).astype(bool)
            red = np.unpackbits(data["red"])[: h * w].reshape(h, w).astype(bool)
            none = np.zeros((h, w), bool)
            return PreparedPage(rgb=rgb, paper=~none, black=black, red=red, rules=none, block=None)
    prepared = prepare_page(rgb, lib.book_config(book))
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache, sha256=np.array(page.sha256 or file_sha256(src)), shape=np.array(rgb.shape[:2]),
                        black=np.packbits(prepared.black), red=np.packbits(prepared.red))
    return prepared


# ---- helpers ------------------------------------------------------------------------------------------
def _tight(mask: np.ndarray, x: int, y: int) -> Optional[Tuple[Box, np.ndarray]]:
    """Crop a mask placed at (x, y) to its ink: (box in page coordinates, cropped mask)."""
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        return None
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    return (int(x + x0), int(y + y0), int(x1 - x0), int(y1 - y0)), mask[y0:y1, x0:x1].copy()


def _sample_mask(lib: Library, book: Book, smp: Sample) -> np.ndarray:
    if not smp.mask:
        raise ActionError(f"Sample {smp.id} has no ink mask (it was captured before masks were kept).")
    with Image.open(lib.book_dir(book) / smp.mask) as im:
        return np.asarray(im.convert("L")) > 127


def _line_for(s, page_id: int, box: Box) -> Optional[Line]:
    """The line of the page that the box overlaps most vertically (or the nearest one)."""
    lines = s.scalars(select(Line).where(Line.page_id == page_id)).all()
    if not lines:
        return None
    x, y, w, h = box

    def score(ln: Line):
        overlap = min(y + h, ln.y + ln.h) - max(y, ln.y)
        return (overlap, -abs((y + h / 2) - (ln.y + ln.h / 2)))
    return max(lines, key=score)


def _ink_colour(prepared: PreparedPage, box: Box, mask: np.ndarray) -> str:
    x, y, w, h = box
    red = int((prepared.red[y:y + h, x:x + w] & mask).sum())
    return "red" if 2 * red > int(mask.sum()) else "black"


def _new_sample(s, ch: _Change, lib: Library, book: Book, page: Optional[Page], prepared: Optional[PreparedPage],
                box: Box, mask: np.ndarray, source: str, kind: str = "letter", rgb_crop: Optional[np.ndarray] = None,
                spacing: Optional[float] = None) -> Sample:
    """Store a new sample: image, mask, fingerprint, database row; recorded as created by `ch`."""
    cfg = lib.book_config(book)
    stem = Path(page.file).stem if page is not None else "_uploaded"
    name = f"manual_{uuid.uuid4().hex[:10]}"
    folder = lib.book_dir(book) / "letters" / stem
    folder.mkdir(parents=True, exist_ok=True)
    if rgb_crop is None:
        rgb_crop = letter_image(prepared, Letter(line=0, pos=0, box=box, mask=mask, ink="black", kind=kind, pieces=1),
                                cfg)
    io_utils.save_image(np.ascontiguousarray(rgb_crop), folder / f"{name}.png", io_utils.ImageMeta(format="PNG"))
    Image.fromarray(mask.astype(np.uint8) * 255).save(folder / f"{name}_mask.png")
    line = _line_for(s, page.id, box) if page is not None else None
    sp = spacing or (page.line_spacing if page is not None and page.line_spacing else 1.6 * box[3])
    smp = Sample(book_id=book.id, page_id=page.id if page is not None else None,
                 line_id=line.id if line else None, line_number=line.number if line else 0, pos=0,
                 x=box[0], y=box[1], w=box[2], h=box[3],
                 ink=_ink_colour(prepared, box, mask) if prepared is not None else "black", kind=kind, pieces=1,
                 rules=source, image=f"letters/{stem}/{name}.png", mask=f"letters/{stem}/{name}_mask.png",
                 fingerprint=fingerprint(mask, float(sp), cfg).tobytes(), source=source, deleted=True)
    s.add(smp)
    s.flush()
    ch.created(smp)
    smp.deleted = False
    return smp


def _book_page(s, book_id: int, page_id: int) -> Tuple[Book, Page]:
    book = s.get(Book, book_id)
    page = s.get(Page, page_id)
    if book is None or page is None or page.book_id != book_id:
        raise NotFound(f"No page with id {page_id} in this book.")
    return book, page


def _sample_dict(smp: Sample) -> Dict:
    return {"id": smp.id, "page_id": smp.page_id, "box": [smp.x, smp.y, smp.w, smp.h], "ink": smp.ink,
            "source": smp.source, "line": smp.line_number}


# ---- operations ---------------------------------------------------------------------------------------
def crop_sample(lib: Library, book_id: int, page_id: int, box: Box) -> Dict:
    """A new sample from the ink inside `box` (x, y, w, h in page pixels). Returns the sample and the
    samples it overlaps (the screen offers to delete them)."""
    with lib.session() as s:
        book, page = _book_page(s, book_id, page_id)
        prepared = page_ink(lib, book, page)
        H, W = prepared.ink.shape
        x, y, w, h = (int(v) for v in box)
        x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
        if x1 - x0 < 3 or y1 - y0 < 3:
            raise ActionError("Draw a larger box around the letter.")
        tight = _tight(prepared.ink[y0:y1, x0:x1], x0, y0)
        if tight is None:
            raise ActionError("There is no ink inside the box.")
        new_box, mask = tight
        ch = _Change(s, book_id)
        smp = _new_sample(s, ch, lib, book, page, prepared, new_box, mask, "cropped")
        nx, ny, nw, nh = new_box
        overlapping = []
        for other in s.scalars(select(Sample).where(Sample.page_id == page_id, Sample.deleted.is_(False),
                                                    Sample.id != smp.id)):
            ox = min(nx + nw, other.x + other.w) - max(nx, other.x)
            oy = min(ny + nh, other.y + other.h) - max(ny, other.y)
            if ox > 0 and oy > 0 and ox * oy >= 0.3 * other.w * other.h:
                overlapping.append(other.id)
        a = ch.finish("crop", {"sample": smp.id, "page": page.file})
        return _result(a, sample=_sample_dict(smp), overlapping=overlapping)


def join_samples(lib: Library, book_id: int, sample_ids: List[int]) -> Dict:
    """Two or more samples of one page become one sample (their ink together)."""
    with lib.session() as s:
        ch = _Change(s, book_id)
        smps = ch.samples(sample_ids)
        if len(smps) < 2:
            raise ActionError("Select at least two samples to join.")
        pages = {x.page_id for x in smps}
        if len(pages) != 1 or None in pages:
            raise ActionError("Only samples of the same page can be joined.")
        book, page = _book_page(s, book_id, pages.pop())
        x0, y0 = min(x.x for x in smps), min(x.y for x in smps)
        x1, y1 = max(x.x + x.w for x in smps), max(x.y + x.h for x in smps)
        mask = np.zeros((y1 - y0, x1 - x0), bool)
        for x in smps:
            mask[x.y - y0:x.y - y0 + x.h, x.x - x0:x.x - x0 + x.w] |= _sample_mask(lib, book, x)
        prepared = page_ink(lib, book, page)
        new_box, mask = _tight(mask, x0, y0)
        for x in smps:
            x.deleted, x.group_id = True, None
        smp = _new_sample(s, ch, lib, book, page, prepared, new_box, mask, "joined")
        a = ch.finish("join", {"samples": len(smps), "sample": smp.id})
        return _result(a, sample=_sample_dict(smp))


def split_sample(lib: Library, book_id: int, sample_id: int, x_cut: int) -> Dict:
    """Cut a sample in two at page column `x_cut`: the ink left of it and the ink from it on."""
    with lib.session() as s:
        ch = _Change(s, book_id)
        (smp,) = ch.samples([sample_id])
        if smp.page_id is None:
            raise ActionError("An uploaded sample cannot be split.")
        book, page = _book_page(s, book_id, smp.page_id)
        cut = int(x_cut) - smp.x
        if not 0 < cut < smp.w:
            raise ActionError("Split inside the sample.")
        mask = _sample_mask(lib, book, smp)
        left, right = mask.copy(), mask.copy()
        left[:, cut:] = False
        right[:, :cut] = False
        parts = [_tight(left, smp.x, smp.y), _tight(right, smp.x, smp.y)]
        if any(p is None for p in parts):
            raise ActionError("There is no ink on one side of the cut.")
        prepared = page_ink(lib, book, page)
        smp.deleted, smp.group_id = True, None
        new = [_new_sample(s, ch, lib, book, page, prepared, b, m, "split", kind=smp.kind) for b, m in parts]
        a = ch.finish("split", {"sample": sample_id, "into": [x.id for x in new]})
        return _result(a, samples=[_sample_dict(x) for x in new])


def ink_of_image(rgb: np.ndarray) -> np.ndarray:
    """Ink of a single letter image, with the colour rules of page preparation (C1) but no text
    block: the paper colour is the median of the image border."""
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    L, A = lab[..., 0], lab[..., 1]
    border = np.concatenate([L[0], L[-1], L[:, 0], L[:, -1]])
    border_a = np.concatenate([A[0], A[-1], A[:, 0], A[:, -1]])
    paper_l, paper_a = float(np.median(border)), float(np.median(border_a))
    red = (A - paper_a >= 14) & (paper_l - L >= 8)
    black = ~red & (L < 0.62 * paper_l)
    ink = (red | black).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    keep = stats[:, cv2.CC_STAT_AREA] >= 5
    keep[0] = False
    return keep[labels]


def upload_sample(lib: Library, book_id: int, filename: str, data_base64: str) -> Dict:
    """A letter image from a file: its ink becomes the mask; it has no page position."""
    try:
        raw = base64.b64decode(data_base64, validate=True)
        with Image.open(io.BytesIO(raw)) as im:
            rgb = np.asarray(im.convert("RGB"))
    except (ValueError, UnidentifiedImageError, OSError) as e:
        raise ActionError(f"{filename} is not an image file.") from e
    mask = ink_of_image(rgb)
    tight = _tight(mask, 0, 0)
    if tight is None:
        raise ActionError(f"No ink found in {filename}.")
    (x, y, w, h), mask = tight
    m = 4
    crop = rgb[max(0, y - m):y + h + m, max(0, x - m):x + w + m]
    with lib.session() as s:
        book = s.get(Book, book_id)
        if book is None:
            raise NotFound(f"No book with id {book_id}.")
        spacing = s.scalar(select(Page.line_spacing).where(Page.book_id == book_id, Page.line_spacing > 0))
        ch = _Change(s, book_id)
        smp = _new_sample(s, ch, lib, book, None, None, (0, 0, w, h), mask, "uploaded", rgb_crop=crop,
                          spacing=spacing or None)
        smp.rules = f"uploaded: {Path(filename).name}"
        a = ch.finish("upload", {"sample": smp.id, "file": Path(filename).name})
        return _result(a, sample=_sample_dict(smp))


# ---- a sample on its line ---------------------------------------------------------------------------
CONTEXT_COLOUR = (194, 65, 12)  # the app's accent


def line_context(lib: Library, sample_id: int, around: int = 4, height: int = 96) -> bytes:
    """PNG of the page around a sample: `around` samples before and after it on its line, with the
    sample outlined, scaled to `height` pixels (never up). Uploaded samples have no page."""
    with lib.session() as s:
        smp = s.get(Sample, sample_id)
        if smp is None or smp.page_id is None:
            raise NotFound(f"No sample on a page with id {sample_id}.")
        page = s.get(Page, smp.page_id)
        book = s.get(Book, page.book_id)
        line = s.scalars(select(Sample).where(Sample.page_id == smp.page_id, Sample.line_number == smp.line_number,
                                              Sample.deleted.is_(False)).order_by(Sample.pos, Sample.x)).all()
        ids = [m.id for m in line]
        at = ids.index(smp.id) if smp.id in ids else None
        near = line[max(0, at - around):at + around + 1] if at is not None else [smp]
        boxes = [(m.x, m.y, m.w, m.h) for m in near] + [(smp.x, smp.y, smp.w, smp.h)]
        target = Path(book.input_dir) / page.file
        box = (smp.x, smp.y, smp.w, smp.h)
    if not target.is_file():
        raise NotFound(f"The input page {page.file} is missing.")
    margin = max(6, box[3] // 4)
    x0 = min(b[0] for b in boxes) - margin
    y0 = min(b[1] for b in boxes) - margin
    x1 = max(b[0] + b[2] for b in boxes) + margin
    y1 = max(b[1] + b[3] for b in boxes) + margin
    with Image.open(target) as im:
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(im.width, x1), min(im.height, y1)
        crop = im.convert("RGB").crop((x0, y0, x1, y1))
    scale = min(1.0, height / max(1, crop.height))
    if scale < 1:
        crop = crop.resize((max(1, round(crop.width * scale)), max(1, round(crop.height * scale))), Image.LANCZOS)
    rgb = np.array(crop)  # a writable copy to draw on
    bx, by = round((box[0] - x0) * scale), round((box[1] - y0) * scale)
    bw, bh = round(box[2] * scale), round(box[3] * scale)
    cv2.rectangle(rgb, (bx - 2, by - 2), (bx + bw + 1, by + bh + 1), CONTEXT_COLOUR, 2)
    out = io.BytesIO()
    Image.fromarray(rgb).save(out, format="PNG")
    return out.getvalue()

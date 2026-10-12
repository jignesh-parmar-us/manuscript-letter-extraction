"""Headlines given back to samples cut before the rule finder kept them (prepare.ruled_lines).

Page preparation used to remove every straight horizontal ink run longer than `rule_min_frac` of the page
as a border rule, and on printed pages that included the headline (shirorekha) of long words: their
samples were cut without it. Cutting a page again would undo the review done on it, so this gives the
headline back to the existing samples instead: each keeps its id, group and label; its mask gets the
headline ink above and inside its columns, and its box, image and fingerprint follow; the touched
groups' centres and distances are recomputed.

- `affected(lib, book_id)`         the groups with samples that lost a headline, for review
- `restore(lib, book_id, codes)`   give the headline back to the samples of those groups
- `undo(lib, backup)`              put the samples of one `restore` back as they were

`restore` keeps the old files and values in `<book>/headline-backup/<time>/` (`backup.json`); it is not a
review action (the review's undo does not reach it).

    python -m letter_extractor.app.headlines list <book id>
    python -m letter_extractor.app.headlines fix <book id> <group code> [...]
    python -m letter_extractor.app.headlines undo <book id> <backup folder>
"""
from __future__ import annotations

import json
import shutil
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image
from sqlalchemy import select

from .. import io_utils
from ..config import Config
from ..features import fingerprint
from ..letters import Letter, letter_image
from ..prepare import PreparedPage, prepare_page, ruled_lines
from .centres import recompute
from .db import Book, LetterGroup, Page, Sample
from .library import Library, NotFound
from .samples import _sample_mask, _tight

MIN_PIXELS = 20        # a sample lost a headline if at least this much of it comes back
ABOVE_PX = 20          # headline ink is looked for up to this far above the sample's box


def _lost(rgb: np.ndarray, cfg: Config) -> Tuple[PreparedPage, np.ndarray]:
    """The page prepared now, and its ink that the old rule finder removed (every long horizontal run)."""
    page = prepare_page(rgb, cfg)
    old = ruled_lines(page.ink | page.rules, replace(cfg, rule_headline_frac=2.0))   # 2.0: no headline kept
    return page, page.ink & old


def _given_back(lost: np.ndarray, smp: Sample, mask: np.ndarray) -> Optional[Tuple[Tuple[int, int, int, int], np.ndarray]]:
    """The sample's new box and mask: its mask with the lost ink in its columns, from `ABOVE_PX` above its box
    to its bottom. None if less than `MIN_PIXELS` come back."""
    H, W = lost.shape
    y0 = max(0, smp.y - ABOVE_PX)
    x1, y1 = min(W, smp.x + smp.w), min(H, smp.y + smp.h)
    full = lost[y0:y1, smp.x:x1].copy()
    had = np.zeros_like(full)
    had[smp.y - y0:smp.y - y0 + mask.shape[0], :mask.shape[1]] = mask[:y1 - smp.y, :x1 - smp.x]
    if int((full & ~had).sum()) < MIN_PIXELS:          # nothing missing (or given back already)
        return None
    return _tight(full | had, smp.x, y0)


def _pages(lib: Library, book: Book, s, page_ids: Optional[Iterable[int]] = None):
    q = select(Page).where(Page.book_id == book.id)
    if page_ids is not None:
        q = q.where(Page.id.in_(list(page_ids)))
    for page in s.scalars(q.order_by(Page.id)):
        src = lib.page_path(book, page)
        if src.is_file():
            yield page, src


def affected(lib: Library, book_id: int, progress=print) -> List[Dict]:
    """Per group (and unsure), the samples whose headline comes back: largest share first."""
    out: Dict[Optional[int], Dict] = {}
    with lib.session() as s:
        book = s.get(Book, book_id)
        if book is None:
            raise NotFound(f"No book with id {book_id}.")
        cfg = lib.book_config(book)
        groups = {g.id: g for g in s.scalars(select(LetterGroup).where(LetterGroup.book_id == book_id))}
        size: Dict[Optional[int], int] = {}
        for gid in s.scalars(select(Sample.group_id).where(Sample.book_id == book_id, Sample.deleted.is_(False))):
            size[gid] = size.get(gid, 0) + 1
        for page, src in _pages(lib, book, s):
            smps = s.scalars(select(Sample).where(Sample.page_id == page.id, Sample.deleted.is_(False),
                                                  Sample.mask != "")).all()
            if not smps:
                continue
            progress(f"{page.file}")
            rgb, _ = io_utils.load_image(src)
            _, lost = _lost(rgb, cfg)
            if not lost.any():
                continue
            for smp in smps:
                new = _given_back(lost, smp, _sample_mask(lib, book, smp))
                if new is None:
                    continue
                g = groups.get(smp.group_id)
                row = out.setdefault(smp.group_id, {
                    "group": g.code if g else "unsure", "label": g.label_guj if g else "", "status": g.status if g else "",
                    "samples": size.get(smp.group_id, 0), "affected": 0, "sample_ids": []})
                row["affected"] += 1
                row["sample_ids"].append(smp.id)
    rows = list(out.values())
    rows.sort(key=lambda r: (-r["affected"] / max(1, r["samples"]), r["group"]))
    return rows


def restore(lib: Library, book_id: int, codes: Iterable[str], progress=print) -> Dict:
    """Give the headline back to the samples of the groups `codes` ("unsure" for samples in no group)."""
    codes = set(codes)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    with lib.session() as s:
        book = s.get(Book, book_id)
        if book is None:
            raise NotFound(f"No book with id {book_id}.")
        cfg = lib.book_config(book)
        folder = lib.book_dir(book)
        groups = {g.code: g for g in s.scalars(select(LetterGroup).where(LetterGroup.book_id == book_id))}
        unknown = codes - set(groups) - {"unsure"}
        if unknown:
            raise NotFound(f"No groups {', '.join(sorted(unknown))} in this book.")
        locked = sorted(c for c in codes if c in groups and groups[c].locked)
        if locked:
            raise NotFound(f"Locked groups {', '.join(locked)}: unlock them first.")
        ids = [groups[c].id for c in codes if c in groups]
        q = select(Sample).where(Sample.book_id == book_id, Sample.deleted.is_(False), Sample.mask != "",
                                 Sample.page_id.is_not(None))
        cond = Sample.group_id.in_(ids)
        if "unsure" in codes:
            cond = cond | Sample.group_id.is_(None)
        smps = s.scalars(q.where(cond)).all()
        by_page: Dict[int, List[Sample]] = {}
        for smp in smps:
            by_page.setdefault(smp.page_id, []).append(smp)
        backup = folder / "headline-backup" / stamp
        saved = []
        for page, src in _pages(lib, book, s, by_page):
            progress(f"{page.file}")
            rgb, _ = io_utils.load_image(src)
            prepared, lost = _lost(rgb, cfg)
            spacing = float(page.line_spacing) if page.line_spacing else None
            for smp in by_page[page.id]:
                new = _given_back(lost, smp, _sample_mask(lib, book, smp))
                if new is None:
                    continue
                box, mask = new
                for rel in (smp.image, smp.mask):
                    (backup / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(folder / rel, backup / rel)
                saved.append({"id": smp.id, "box": [smp.x, smp.y, smp.w, smp.h], "image": smp.image, "mask": smp.mask,
                              "fingerprint": smp.fingerprint.hex() if smp.fingerprint is not None else None})
                rgb_crop = letter_image(prepared, Letter(line=0, pos=0, box=box, mask=mask, ink=smp.ink, kind=smp.kind,
                                                         pieces=smp.pieces), cfg)
                io_utils.save_image(np.ascontiguousarray(rgb_crop), folder / smp.image, io_utils.ImageMeta(format="PNG"))
                Image.fromarray(mask.astype(np.uint8) * 255).save(folder / smp.mask)
                smp.x, smp.y, smp.w, smp.h = box
                smp.fingerprint = fingerprint(mask, spacing or 1.6 * smp.h, cfg).tobytes()
        if saved:
            backup.mkdir(parents=True, exist_ok=True)
            (backup / "backup.json").write_text(json.dumps({"book_id": book_id, "groups": sorted(codes),
                                                            "samples": saved}, indent=1))
        s.flush()
        recompute(s, ids)
    return {"samples": len(saved), "backup": str(backup) if saved else None}


def undo(lib: Library, book_id: int, backup: Path) -> Dict:
    """Put the samples of one `restore` back: files, box and fingerprint; centres recomputed."""
    data = json.loads((backup / "backup.json").read_text())
    if data["book_id"] != book_id:
        raise NotFound(f"That backup is of book {data['book_id']}.")
    with lib.session() as s:
        book = s.get(Book, book_id)
        folder = lib.book_dir(book)
        gids = set()
        for row in data["samples"]:
            smp = s.get(Sample, row["id"])
            if smp is None:
                continue
            for rel in (row["image"], row["mask"]):
                shutil.copy2(backup / rel, folder / rel)
            smp.x, smp.y, smp.w, smp.h = row["box"]
            smp.fingerprint = bytes.fromhex(row["fingerprint"]) if row["fingerprint"] else None
            if smp.group_id is not None:
                gids.add(smp.group_id)
        s.flush()
        recompute(s, sorted(gids))
    return {"samples": len(data["samples"])}


def main(argv: List[str]) -> int:
    from .library import default_library_dir
    lib = Library(default_library_dir())
    cmd, book_id, rest = argv[0], int(argv[1]), argv[2:]
    if cmd == "list":
        rows = affected(lib, book_id, progress=lambda m: print(m, file=sys.stderr))
        print(f"{'group':8} {'label':8} {'status':9} {'affected':>8} {'of':>5}")
        for r in rows:
            print(f"{r['group']:8} {r['label']:8} {r['status']:9} {r['affected']:>8} {r['samples']:>5}")
        print(f"{sum(r['affected'] for r in rows)} samples in {len(rows)} groups")
    elif cmd == "fix":
        print(restore(lib, book_id, rest, progress=lambda m: print(m, file=sys.stderr)))
    elif cmd == "undo":
        print(undo(lib, book_id, Path(rest[0])))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

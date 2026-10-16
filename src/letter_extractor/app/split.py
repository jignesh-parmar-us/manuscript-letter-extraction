"""Split the rows of a library from before Phase 3 into datasets and books (C20).

Before C20 one row held both parts: its Training Data (pages cut, grouped, reviewed, labelled) and its Read Book
pages (read). Migration 0017 makes every row a dataset; this module separates them:

* A row with Read Book pages **and** Training Data keeps its id, name, Training Data, groups, labels, letter
  checker and the undo history of its Training Data, as a **dataset**. A new **book** row with the same name
  gets its Read Book pages, with their lines, whole-line readings, line truth, page texts, letters (never
  grouped) and the undo history of those letters, its Read Book folder or PDF, settings and letter checker,
  and a reading model (C23) learning from the dataset. The book's files move from the dataset's folder to its own:
  `read/`, `line-search/` (our reader, its Measure and caches), `text/read/` and `cache/read-*`.
* A row with Read Book pages and **no** Training Data becomes a book in place (no empty dataset).
* A row without Read Book pages stays a dataset.

Page image files are never moved or changed (the rows keep pointing where they are). It refuses, before changing
anything, a row whose pages were moved between the parts (their files are in the other part's folders), Read Book
letters in a group, or an undo step that touches letters of both parts.

    python -m letter_extractor.app.split --library DIR            what would be split (nothing changes)
    python -m letter_extractor.app.split --library DIR --run      back up, split, compare the counts

The app refuses to open a library that still needs splitting (`Library.unsplit_books`).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, select

from .db import BOOK, DATASET, Action, Book, LetterGroup, Line, LineTruth, OcrReading, Page, PageText, Sample, \
    WholeLine, WordList, now
from .library import Library, LibraryError, _slug

# the files of a book inside its row's folder (C16a-C19): what moves to the new book's folder
BOOK_FOLDERS = ("read", "line-search", "text/read")
BOOK_CACHE = "cache/read-*"


# ---- counts --------------------------------------------------------------------------------------
def counts(lib: Library) -> Dict[str, int]:
    """What must be the same before and after the split, in the whole library (the rows are not: a row split in
    two makes one more)."""
    with lib.session() as s:
        def n(q):
            return s.scalar(q) or 0
        reviewed = LetterGroup.status != "auto"
        return {
            "training pages": n(select(func.count(Page.id)).where(Page.part == "training")),
            "read pages": n(select(func.count(Page.id)).where(Page.part == "read")),
            "lines": n(select(func.count(Line.id))),
            "training letters": n(select(func.count(Sample.id)).where(Sample.part == "training")),
            "read letters": n(select(func.count(Sample.id)).where(Sample.part == "read")),
            "groups": n(select(func.count(LetterGroup.id))),
            "reviewed groups": n(select(func.count(LetterGroup.id)).where(reviewed)),
            "labelled groups": n(select(func.count(LetterGroup.id)).where(LetterGroup.label_dev != "")),
            "letters in reviewed groups": n(select(func.count(Sample.id)).join(LetterGroup, Sample.group_id == LetterGroup.id)
                                            .where(reviewed, Sample.deleted.is_(False))),
            "line truth": n(select(func.count(LineTruth.id))),
            "checked lines (text)": n(select(func.count(LineTruth.id)).where(LineTruth.text_dev != "")),
            "whole lines": n(select(func.count(WholeLine.id))),
            "reviewed whole lines": n(select(func.count(WholeLine.id)).where(WholeLine.reviewed.is_(True))),
            "page texts": n(select(func.count(PageText.id))),
            "readings": n(select(func.count(OcrReading.id))),
            "undo steps": n(select(func.count(Action.id))),
            "word lists": n(select(func.count(WordList.id))),
        }


def _row_counts(s, book_id: int) -> Dict[str, int]:
    """One row's parts: what moves (read) and what stays (training)."""
    def n(q):
        return s.scalar(q) or 0
    on_read = Page.part == "read"
    lines_of = select(Line.id).join(Page, Line.page_id == Page.id).where(Page.book_id == book_id, on_read)
    return {
        "training pages": n(select(func.count(Page.id)).where(Page.book_id == book_id, Page.part == "training")),
        "read pages": n(select(func.count(Page.id)).where(Page.book_id == book_id, on_read)),
        "read lines": n(select(func.count()).select_from(lines_of.subquery())),
        "training letters": n(select(func.count(Sample.id)).where(Sample.book_id == book_id, Sample.part == "training")),
        "read letters": n(select(func.count(Sample.id)).where(Sample.book_id == book_id, Sample.part == "read")),
        "groups": n(select(func.count(LetterGroup.id)).where(LetterGroup.book_id == book_id)),
        "line truth": n(select(func.count(LineTruth.id)).where(LineTruth.line_id.in_(lines_of))),
        "whole lines": n(select(func.count(WholeLine.id)).where(WholeLine.line_id.in_(lines_of))),
        "page texts": n(select(func.count(PageText.id)).join(Page, PageText.page_id == Page.id)
                        .where(Page.book_id == book_id, on_read)),
    }


# ---- the plan --------------------------------------------------------------------------------------
def _action_parts(s, book_id: int) -> Tuple[List[int], List[int], List[int]]:
    """The row's undo steps by the part of the letters they touch: (read only, both parts, none or training)."""
    part = dict(s.execute(select(Sample.id, Sample.part).where(Sample.book_id == book_id)).all())
    read, mixed, other = [], [], []
    for aid, payload in s.execute(select(Action.id, Action.payload).where(Action.book_id == book_id)
                                  .order_by(Action.id)).all():
        data = json.loads(payload or "{}")
        ids = {int(k) for k in (data.get("samples_before") or {})} | {int(k) for k in (data.get("samples_after") or {})}
        parts = {part.get(i) for i in ids} - {None}
        (read if parts == {"read"} else mixed if len(parts) > 1 else other).append(aid)
    return read, mixed, other


def plan(lib: Library) -> List[Dict]:
    """What the split does to each row that needs it (`how`: "split" or "book"), and `problems` that stop it."""
    out = []
    for row in lib.unsplit_books():
        with lib.session() as s:
            b = s.get(Book, row["id"])
            c = _row_counts(s, b.id)
            problems = []
            moved = s.scalar(select(func.count(Page.id)).where(Page.book_id == b.id, Page.part != Page.folder)) or 0
            if moved:
                problems.append(f"{moved} pages were moved between Training Data and Read Book (Use for training / "
                                "reading): their files are in the other part's folders. Move them back first.")
            grouped = s.scalar(select(func.count(Sample.id)).where(Sample.book_id == b.id, Sample.part == "read",
                                                                   Sample.group_id.is_not(None))) or 0
            if grouped:
                problems.append(f"{grouped} Read Book letters are in groups (corrected in Cut letters).")
            read_steps, mixed, _ = _action_parts(s, b.id)
            if mixed:
                problems.append(f"{len(mixed)} undo steps touch letters of both parts (first: {mixed[0]}).")
            has_training = c["training pages"] or c["training letters"] or c["groups"]
        out.append({"id": b.id, "name": b.name, "how": "split" if has_training else "book",
                    "counts": c, "undo steps moved": len(read_steps) if has_training else 0,
                    "folders moved": [f for f in BOOK_FOLDERS if (lib.book_dir(b) / f).exists()] if has_training else [],
                    "problems": problems})
    return out


# ---- the split ----------------------------------------------------------------------------------------
def _move(src: Path, dst: Path, done: List[Tuple[Path, Path]]) -> None:
    if not src.exists():
        return
    if dst.exists():
        raise LibraryError(f"Cannot move {src} to {dst}: it exists already.")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)                                   # same disk: a rename, nothing is copied
    done.append((src, dst))


def split_library(lib: Library) -> Dict:
    """Split every row that needs it (see the module notes). All or nothing: the database changes in one
    transaction, and the folders moved so far are moved back if anything fails. Returns the counts before and
    after (they must be equal) and what was done per row."""
    steps = plan(lib)
    bad = [f"'{p['name']}': {x}" for p in steps for x in p["problems"]]
    if bad:
        raise LibraryError("Nothing was split. " + " ".join(bad))
    before = counts(lib)
    moved: List[Tuple[Path, Path]] = []
    done = []
    try:
        with lib.session() as s:
            for p in steps:
                d = s.get(Book, p["id"])
                if p["how"] == "book":                    # Read Book only: it becomes a book in place
                    d.kind = BOOK
                    Library._new_model(s, d, [])            # C23: its reading model, no dataset yet
                    done.append({"dataset": None, "book": d.id, "name": d.name})
                    continue
                if s.scalar(select(Book.id).where(Book.kind == BOOK, Book.name == d.name)) is not None:
                    raise LibraryError(f"A book named '{d.name}' exists already; rename it first.")
                b = Book(name=d.name, kind=BOOK, folder=f"new-{d.id}", input_dir="", settings=d.settings,
                         writing=d.writing, read_dir=d.read_dir, read_pdf=d.read_pdf, reader_id=d.reader_id,
                         created_at=d.created_at, updated_at=now(), captured_at=None)
                s.add(b)
                s.flush()
                b.folder = f"{b.id:04d}-{_slug(d.name)}"
                Library._new_model(s, b, [d.id])            # C23: the book's reading model learns from the dataset
                read_pages = select(Page.id).where(Page.book_id == d.id, Page.part == "read")
                read_steps, _, _ = _action_parts(s, d.id)
                s.execute(Sample.__table__.update().where(Sample.book_id == d.id, Sample.part == "read")
                          .values(book_id=b.id))
                s.execute(Page.__table__.update().where(Page.id.in_(read_pages.scalar_subquery()))
                          .values(book_id=b.id))
                if read_steps:
                    s.execute(Action.__table__.update().where(Action.id.in_(read_steps)).values(book_id=b.id))
                for w in s.scalars(select(WordList)):    # the book's Dictionary (word lists) stays its own
                    ids = json.loads(w.books or "[]")
                    if d.id in ids and b.id not in ids:
                        w.books = json.dumps(sorted(ids + [b.id]))
                d.read_dir, d.read_pdf, d.updated_at = "", "", now()
                s.flush()
                src, dst = lib.root / "books" / d.folder, lib.root / "books" / b.folder
                dst.mkdir(parents=True, exist_ok=False)
                moved.append((dst, dst))                  # the new folder: removed again if the split fails
                for f in BOOK_FOLDERS:
                    _move(src / f, dst / f, moved)
                for f in sorted(src.glob(BOOK_CACHE)):
                    _move(f, dst / "cache" / f.name, moved)
                done.append({"dataset": d.id, "book": b.id, "name": d.name, "folder": b.folder,
                             "dataset counts": _row_counts(s, d.id), "book counts": _row_counts(s, b.id),
                             "undo steps moved": len(read_steps)})
            left = s.scalar(select(func.count(Book.id)).where(Book.kind == DATASET, Book.id.in_(
                select(Page.book_id).where(Page.part == "read")))) or 0
            if left:
                raise LibraryError(f"{left} datasets still hold Read Book pages after the split; nothing was kept.")
    except BaseException:
        for src, dst in reversed(moved):
            if src == dst:
                shutil.rmtree(dst, ignore_errors=True)
            elif dst.exists():
                dst.rename(src)
        raise
    lib._folders.clear()
    after = counts(lib)
    return {"before": before, "after": after, "same": before == after, "rows": done}


# ---- backup -----------------------------------------------------------------------------------------
def backup(library: Path, target: Optional[Path] = None) -> Path:
    """A copy of the whole library folder beside it (`<library> backup <date time>`): the database through
    SQLite's backup (consistent even if it was not closed cleanly), everything else copied (on a Mac as APFS
    clones: instant, no extra space until a file changes)."""
    library = Path(library)
    target = Path(target) if target else library.with_name(f"{library.name} backup {datetime.now():%Y-%m-%d %H%M%S}")
    if target.exists():
        raise LibraryError(f"The backup folder exists already: {target}")
    target.mkdir(parents=True)
    for item in library.iterdir():
        if item.name.startswith("library.db"):
            continue
        if sys.platform == "darwin":
            subprocess.run(["cp", "-cR", str(item), str(target / item.name)], check=True)
        elif item.is_dir():
            shutil.copytree(item, target / item.name)
        else:
            shutil.copy2(item, target / item.name)
    src = sqlite3.connect(f"file:{library / 'library.db'}?mode=ro", uri=True)
    dst = sqlite3.connect(target / "library.db")
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target


# ---- command line ------------------------------------------------------------------------------------
def _table(rows: Dict[str, int], other: Optional[Dict[str, int]] = None) -> str:
    width = max(len(k) for k in rows)
    lines = []
    for k, v in rows.items():
        mark = "" if other is None else ("  same" if other.get(k) == v else f"  DIFFERENT: {other.get(k)}")
        lines.append(f"  {k:<{width}}  {v:>8}" + ("" if other is None else f"  {other.get(k):>8}{mark}"))
    return "\n".join(lines)


def main(argv=None) -> int:
    from .main import library_dir
    p = argparse.ArgumentParser(prog="python -m letter_extractor.app.split",
                                description="Split a library from before Phase 3 into datasets and books (C20).")
    p.add_argument("--library", help="library folder (default: the app's)")
    p.add_argument("--run", action="store_true", help="back up the library, then split it (without it: only show)")
    p.add_argument("--backup", help="where the backup goes (default: beside the library, with the date)")
    p.add_argument("--no-backup", action="store_true", help="no backup (only for a copy of a library)")
    args = p.parse_args(argv)
    root = library_dir(args.library)
    lib = Library(root)
    try:
        steps = plan(lib)
        if not steps:
            print(f"{root}: nothing to split.")
            return 0
        for st in steps:
            what = "dataset + book" if st["how"] == "split" else "book only (no Training Data)"
            print(f"\n{st['id']} '{st['name']}': {what}")
            print(_table(st["counts"]))
            if st["how"] == "split":
                print(f"  undo steps that move to the book: {st['undo steps moved']}; folders: "
                      f"{', '.join(st['folders moved']) or 'none'}")
            for x in st["problems"]:
                print(f"  PROBLEM: {x}")
        if not args.run:
            print("\nNothing was changed. Add --run to back up and split.")
            return 0
        if any(st["problems"] for st in steps):
            print("\nNothing was changed: solve the problems first.", file=sys.stderr)
            return 1
        if not args.no_backup:
            lib.close()
            where = backup(root, Path(args.backup) if args.backup else None)
            print(f"\nBackup: {where}")
            lib = Library(root)
        result = split_library(lib)
        print("\nCounts (before, after):")
        print(_table(result["before"], result["after"]))
        for r in result["rows"]:
            if r["dataset"] is None:
                print(f"\n{r['book']} '{r['name']}' is now a book.")
            else:
                print(f"\n'{r['name']}': dataset {r['dataset']} keeps the Training Data, book {r['book']} "
                      f"(books/{r['folder']}) has the Read Book pages; {r['undo steps moved']} undo steps moved.")
                print("  dataset now:\n" + _table(r["dataset counts"]))
                print("  book now:\n" + _table(r["book counts"]))
        print("\nAll counts are the same." if result["same"] else "\nCOUNTS DIFFER: check before using the library.")
        return 0 if result["same"] else 1
    finally:
        lib.close()


if __name__ == "__main__":
    sys.exit(main())

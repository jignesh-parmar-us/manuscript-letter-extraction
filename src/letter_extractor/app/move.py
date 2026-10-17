"""Page images move into the uploads folder (Phase 3, C26; full plan, decisions 2 and 6).

Before C21 a dataset read its Training Data pages from a folder of the user's own (`input_dir`) and a book its Read
Book pages from one too (`read_dir`). From C21 on, new rows keep their pages in the uploads folder
(`<uploads>/datasets/<row folder>/`, `<uploads>/books/<row folder>/`). This module brings the older rows there, so
nothing depends on a folder outside the app (five rows of the user's library read `~/Downloads/black and white`):

* **Existing rows, once per library** (`move_existing`, run by the app at start before the screen opens): every
  page image of the row's folder (its pages, also excluded and not prepared ones, and the images that are not pages
  yet, so the page list stays the same) is copied into the row's upload folder under its own name, as an APFS clone
  on a Mac (no extra space). Each copy is checked against its original by SHA-256; then the row's folder is switched.
  A row whose folder or a page image is missing, or whose copy does not match, is not switched: it keeps working
  from the original, and it is tried again at the next start. Rows made later with *Use this folder* stay where
  they are. Originals are never changed or deleted; the folders no row uses any more are listed.
  Before the first copy the library database is backed up (`<library> backups/<date> before moving pages/`): the
  only database change is the rows' folder paths, and no file is changed in place.
* **When the uploads setting changes** (`move_uploads`, a job): every row's upload folder is copied from the old
  uploads folder into the new one the same way, and the rows that used it are switched. If anything fails, the
  copies are removed and nothing is switched (the setting is then not changed either). The old folder stays.

Letters, lines, thumbnails and checked lines are kept by page and file name, not by folder, so they do not change.
A book read from a PDF is not moved: its pages are the app's own already (`books/<folder>/read/pages/`).

    python -m letter_extractor.app.move --library DIR          what would be moved (nothing changes)
    python -m letter_extractor.app.move --library DIR --run    back up the database, then move
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
from typing import Callable, Dict, List, Optional

from sqlalchemy import select

from .. import io_utils
from .db import BOOK, DATASET, Book, Page
from .library import KIND_WORD, Cancelled, Library, LibraryError, file_sha256

STATE = "page-moves.json"          # in the library folder: what is still to move, and the last notice
SayFn = Callable[[str], None]


# ---- copying ---------------------------------------------------------------------------------------
def _clone(src: Path, dst: Path) -> None:
    """Copy `src` to `dst` (an APFS clone on a Mac: instant, no extra space until one of them changes), through a
    hidden part file, so a half copy never has the page's name."""
    part = dst.with_name(f".{dst.name}.part")
    part.unlink(missing_ok=True)
    if sys.platform == "darwin":
        if subprocess.run(["cp", "-c", str(src), str(part)], capture_output=True).returncode:
            shutil.copy2(src, part)                    # another disk or file system: a normal copy
    else:
        shutil.copy2(src, part)
    part.rename(dst)


def _copy_all(files: List[Path], target: Path, progress: Optional[Callable[[str], None]] = None,
              cancel: Optional[Callable[[], bool]] = None) -> List[Path]:
    """Copy `files` into `target` and check each copy by its hash. Returns the copies made (a file of the same
    name and content already there is used as it is). On a problem the copies made are removed again and
    LibraryError says which file."""
    made: List[Path] = []
    target.mkdir(parents=True, exist_ok=True)
    try:
        for src in files:
            if cancel and cancel():
                raise Cancelled("Cancelled; nothing was moved.")
            if progress:
                progress(src.name)
            dst = target / src.name
            want = file_sha256(src)
            if dst.exists():
                if dst.is_file() and file_sha256(dst) == want:
                    continue
                raise LibraryError(f"{dst} exists already with other content.")
            _clone(src, dst)
            made.append(dst)
            if file_sha256(dst) != want:
                raise LibraryError(f"The copy of {src.name} does not match the original.")
    except BaseException:
        for f in made:
            f.unlink(missing_ok=True)
        raise
    return made


# ---- existing rows ---------------------------------------------------------------------------------
def _row_folder(book: Book) -> str:
    """The folder of a row's own page images: a dataset's Training Data folder, a book's Read Book folder (not a
    PDF's pages, which are in the book folder already); '' when it has none."""
    if book.kind == DATASET:
        return book.input_dir or ""
    return "" if book.read_pdf else (book.read_dir or "")


def row_plan(lib: Library, book: Book, uploads: Path) -> Optional[Dict]:
    """What moving one row means, or None when it has nothing to move (no folder, or its upload folder already):
    {id, name, kind, source, target, files, problems}."""
    source = _row_folder(book)
    if not source:
        return None
    target = lib.upload_dir(book, uploads)
    src = Path(source)
    if src.resolve() == target:
        return None
    part = "training" if book.kind == DATASET else "read"
    with lib.session() as s:
        pages = list(s.scalars(select(Page.file).where(Page.book_id == book.id, Page.folder == part)
                               .order_by(Page.number, Page.id)))
    problems: List[str] = []
    files: List[str] = []
    if not src.is_dir():
        problems.append(f"its folder {src} is not there")
    else:
        missing = [f for f in pages if not (src / f).is_file()]
        if missing:
            problems.append(f"{len(missing)} page image{'s' * (len(missing) != 1)} missing in {src} "
                            f"(first: {missing[0]})")
        images = [p.name for p in io_utils.scan_folder(src)[0]]
        files = list(dict.fromkeys([f for f in pages if f not in missing] + images))
    return {"id": book.id, "name": book.name, "kind": book.kind, "source": str(src), "target": str(target),
            "files": files, "problems": problems}


def move_plan(lib: Library, uploads: Path, ids: Optional[List[int]] = None) -> List[Dict]:
    """The rows (all, or those of `ids`) whose page images are not in their upload folder yet."""
    with lib.session() as s:
        q = select(Book).order_by(Book.id)
        books = s.scalars(q.where(Book.id.in_(ids)) if ids is not None else q).all()
    return [p for p in (row_plan(lib, b, uploads) for b in books) if p is not None]


def move_row(lib: Library, plan: Dict, progress: Optional[Callable[[str], None]] = None) -> Dict:
    """Copy, check and switch one row (a plan of `row_plan` without problems). LibraryError when a copy fails:
    then the row is unchanged and its copies are removed."""
    target = Path(plan["target"])
    _copy_all([Path(plan["source"]) / f for f in plan["files"]], target, progress)
    with lib.session() as s:
        b = s.get(Book, plan["id"])
        if b.kind == DATASET:
            b.input_dir = str(target)
        else:
            b.read_dir = str(target)
    return {"id": plan["id"], "name": plan["name"], "kind": plan["kind"], "from": plan["source"],
            "to": str(target), "files": len(plan["files"])}


def backup_db(library: Path) -> Path:
    """The library database, copied through SQLite's backup (consistent while the app has it open) into
    `<library> backups/<date time> before moving pages/library.db`."""
    library = Path(library)
    folder = library.with_name(f"{library.name} backups") / f"{datetime.now():%Y-%m-%d %H%M%S} before moving pages"
    folder.mkdir(parents=True, exist_ok=False)
    src = sqlite3.connect(f"file:{library / 'library.db'}?mode=ro", uri=True)
    dst = sqlite3.connect(folder / "library.db")
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return folder


def load_state(lib: Library) -> Dict:
    try:
        return json.loads((lib.root / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(lib: Library, state: Dict) -> None:
    (lib.root / STATE).write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _unused(lib: Library, folders: List[str]) -> List[str]:
    """Of `folders`, those no row reads its pages from any more."""
    with lib.session() as s:
        used = {str(Path(f).resolve()) for f in s.scalars(select(Book.input_dir)) if f}
        used |= {str(Path(f).resolve()) for f in s.scalars(select(Book.read_dir)) if f}
    return sorted({f for f in folders if str(Path(f).resolve()) not in used})


def move_existing(lib: Library, uploads: Path, backup: bool = True, say: Optional[SayFn] = None) -> Optional[Dict]:
    """Move the page images of the rows from before C26 into the uploads folder (see the module notes), once per
    library: the rows still to move are kept in `page-moves.json`. Returns the report, or None when there was
    nothing to do. A new report becomes the notice the screens show once (`notice`, `seen`)."""
    state = load_state(lib)
    existing = state.get("existing", {})
    if existing.get("done"):
        return None
    ids = existing.get("pending")                    # None at the first start: every row there is now
    plans = move_plan(lib, uploads, ids)
    ready = [p for p in plans if not p["problems"]]
    report: Dict = {"moved": [], "failed": [{"id": p["id"], "name": p["name"], "problem": "; ".join(p["problems"])}
                                            for p in plans if p["problems"]], "backup": "", "old_folders": []}
    if ready:
        if backup:
            report["backup"] = str(backup_db(lib.root))
            if say:
                say(f"Moving page images into the uploads folder ({uploads}); database backup: {report['backup']}")
        for p in ready:
            try:
                report["moved"].append(move_row(lib, p))
                if say:
                    say(f"  {KIND_WORD[p['kind']]} '{p['name']}': {len(p['files'])} page images moved")
            except LibraryError as e:
                report["failed"].append({"id": p["id"], "name": p["name"], "problem": str(e)})
        report["old_folders"] = _unused(lib, [m["from"] for m in report["moved"]])
    for f in report["failed"]:
        if say:
            say(f"  '{f['name']}' not moved: {f['problem']}")
    pending = [f["id"] for f in report["failed"]]
    state["existing"] = {"done": not pending, "pending": pending}
    if not plans:
        _save_state(lib, state)
        return None
    report["at"] = datetime.now().isoformat(timespec="seconds")
    last = state.get("notice") or {}
    same = report["moved"] == [] and last.get("failed") == report["failed"]
    if not same:                                     # a failure repeated at every start is shown once
        state["notice"] = {**report, "seen": False}
    _save_state(lib, state)
    return report


def notice(lib: Library) -> Optional[Dict]:
    """The last move's report while it is not seen yet (the screens show it once), else None."""
    n = load_state(lib).get("notice")
    return n if n and not n.get("seen") else None


def notice_seen(lib: Library) -> None:
    state = load_state(lib)
    if state.get("notice"):
        state["notice"]["seen"] = True
        _save_state(lib, state)


# ---- the uploads setting changes -------------------------------------------------------------------
def move_uploads(lib: Library, old: Path, new: Path, progress: Optional[Callable[[int, int, str], None]] = None,
                 cancel: Optional[Callable[[], bool]] = None) -> Dict:
    """Copy every row's upload folder from `old` into `new` (all its files: page images, a book's PDF), check each
    copy, then switch the rows that read their pages from there. All or nothing: on a problem every copy is removed,
    no row is switched, and LibraryError says why. The old folder is left as it is."""
    old, new = Path(old).expanduser().resolve(), Path(new).expanduser().resolve()
    if old == new:
        return {"rows": 0, "files": 0, "old": str(old)}
    if old in new.parents:
        raise LibraryError(f"The new uploads folder is inside the old one ({old}): choose another folder.")
    with lib.session() as s:
        books = s.scalars(select(Book).order_by(Book.id)).all()
    todo = []
    for b in books:
        src = lib.upload_dir(b, old)
        if src.is_dir():
            files = sorted(p for p in src.iterdir() if p.is_file() and not p.name.startswith("."))
            todo.append((b, src, lib.upload_dir(b, new), files))
    total = sum(len(t[3]) for t in todo)
    made: List[Path] = []
    done = 0
    try:
        for b, src, dst, files in todo:
            def step(name: str) -> None:
                nonlocal done
                done += 1
                if progress:
                    progress(done, total, name)
            made += _copy_all(files, dst, step, cancel)
        with lib.session() as s:
            for b, src, dst, _ in todo:
                row = s.get(Book, b.id)
                if row.input_dir and Path(row.input_dir).resolve() == src:
                    row.input_dir = str(dst)
                if row.read_dir and Path(row.read_dir).resolve() == src:
                    row.read_dir = str(dst)
    except BaseException:
        for f in made:
            f.unlink(missing_ok=True)
        raise
    return {"rows": len(todo), "files": total, "old": str(old)}


# ---- command line ------------------------------------------------------------------------------------
def main(argv=None) -> int:
    from .main import library_dir, uploads_dir
    p = argparse.ArgumentParser(prog="python -m letter_extractor.app.move",
                                description="Move the page images of older rows into the uploads folder (C26).")
    p.add_argument("--library", help="library folder (default: the app's)")
    p.add_argument("--run", action="store_true", help="back up the database, then move (without it: only show)")
    p.add_argument("--no-backup", action="store_true", help="no backup (only for a copy of a library)")
    args = p.parse_args(argv)
    root = library_dir(args.library)
    uploads = uploads_dir(root)
    lib = Library(root)
    try:
        state = load_state(lib).get("existing", {})
        if state.get("done"):
            print(f"{root}: the existing rows were moved already.")
            return 0
        plans = move_plan(lib, uploads, state.get("pending"))
        if not plans:
            print(f"{root}: nothing to move.")
            return 0
        print(f"Uploads folder: {uploads}")
        for pl in plans:
            print(f"\n{pl['id']} {KIND_WORD[pl['kind']]} '{pl['name']}': {len(pl['files'])} page images\n"
                  f"  from {pl['source']}\n  to   {pl['target']}")
            for x in pl["problems"]:
                print(f"  NOT MOVED: {x}")
        if not args.run:
            print("\nNothing was changed. Add --run to back up the database and move.")
            return 0
        report = move_existing(lib, uploads, backup=not args.no_backup, say=print)
        if report and report["old_folders"]:
            print("\nNo row uses these folders any more (nothing was deleted):\n  " + "\n  ".join(report["old_folders"]))
        return 1 if report and report["failed"] else 0
    finally:
        lib.close()


if __name__ == "__main__":
    sys.exit(main())

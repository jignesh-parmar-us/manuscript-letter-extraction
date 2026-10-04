"""A small captured book for the app tests: built once, then copied for every test."""
import shutil
import sys
import tempfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import synthetic                                                    # noqa: E402
from letter_extractor.app.db import LetterGroup, Sample            # noqa: E402
from letter_extractor.app.library import Library                    # noqa: E402
from sqlalchemy import select                                       # noqa: E402

_TEMPLATE = None


def add_page(folder: Path, name: str, n_lines: int = 3) -> None:
    rgb, _ = synthetic.make_letters_page(n_lines=n_lines)
    Image.fromarray(rgb).save(folder / name)


def _template() -> Path:
    """Library with one book 'Synthetic' (2 pages, captured), created once per test run."""
    global _TEMPLATE
    if _TEMPLATE is None:
        root = Path(tempfile.mkdtemp(prefix="appbook-"))
        pages = root / "pages"
        pages.mkdir()
        add_page(pages, "p1.png")
        add_page(pages, "p2.png")
        lib = Library(root / "lib")
        book = lib.create_book("Synthetic", pages)
        lib.capture(book.id)
        lib.close()
        _TEMPLATE = root
    return _TEMPLATE


def fresh_copy():
    """(temp dir, Library, book id, pages folder): a private copy of the captured book."""
    tmp = Path(tempfile.mkdtemp(prefix="appbook-copy-"))
    shutil.copytree(_template(), tmp / "t")
    lib = Library(tmp / "t" / "lib")
    book = lib.list_books()[0]
    # the copied book still points at the template's pages: point it at the copy
    with lib.session() as s:
        from letter_extractor.app.db import Book
        s.get(Book, book["id"]).input_dir = str(tmp / "t" / "pages")
    return tmp, lib, book["id"], tmp / "t" / "pages"


def state(lib: Library, book_id: int):
    """Everything an action may change, to compare before / after undo."""
    with lib.session() as s:
        samples = [(x.id, x.group_id, x.deleted, x.kind, None if x.distance is None else round(x.distance, 5))
                   for x in s.scalars(select(Sample).where(Sample.book_id == book_id).order_by(Sample.id))]
        groups = [(g.id, g.code, g.kind, g.label_dev, g.label_guj, g.status, g.locked)
                  for g in s.scalars(select(LetterGroup).where(LetterGroup.book_id == book_id)
                                     .order_by(LetterGroup.id))]
    return samples, groups


def groups_with_members(lib: Library, book_id: int):
    """{group id: [sample ids]} for the book."""
    with lib.session() as s:
        out = {}
        for g in s.scalars(select(LetterGroup).where(LetterGroup.book_id == book_id).order_by(LetterGroup.id)):
            out[g.id] = [m.id for m in s.scalars(select(Sample).where(Sample.group_id == g.id,
                                                                     Sample.deleted.is_(False)))]
        return out


def cleanup(tmp: Path, lib: Library) -> None:
    lib.close()
    shutil.rmtree(tmp, ignore_errors=True)

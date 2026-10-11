"""Request bodies of the API (C5c). Responses are plain JSON objects built in api.py."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


Writing = Literal["handwritten", "printed"]


class BookCreate(BaseModel):
    name: str
    input_dir: str
    settings: Optional[Dict[str, Any]] = None     # overrides of the default Config
    writing: Writing = "handwritten"


class BookUpdate(BaseModel):
    name: Optional[str] = None
    writing: Optional[Writing] = None


class Force(BaseModel):
    force: bool = False                           # confirm discarding manual work


class SampleIds(BaseModel):
    sample_ids: List[int] = Field(min_length=1)


class Move(SampleIds):
    group_id: Optional[int] = None                # None: to unsure


class Merge(BaseModel):
    target_id: int
    source_ids: List[int] = Field(min_length=1)


class GroupRef(BaseModel):
    group_id: int


class Label(GroupRef):
    text: str                                     # Devanagari or Gujarati; "" clears the label


class Status(GroupRef):
    reviewed: Optional[bool] = None
    locked: Optional[bool] = None


class LibraryChoice(BaseModel):
    path: str


class Accepted(BaseModel):
    group_id: int
    label_dev: str                                # the suggestion the user saw


class AcceptSuggestions(BaseModel):
    items: List[Accepted] = Field(min_length=1)


class RejectSuggestion(GroupRef):
    label_dev: str


class RemoveReadings(SampleIds):
    engine: Optional[Literal["tesseract", "books", "reader"]] = None   # None: the book's main reader


class LabelSamples(SampleIds):
    text: str                                     # Devanagari or Gujarati


class SuggestRequest(BaseModel):
    engine: Literal["tesseract", "books"] = "tesseract"   # Tesseract (C11) or other labelled books (C13)
    books: Optional[List[int]] = None             # engine "books": the books to learn from (None: the default ones)


class BookSettings(BaseModel):
    settings: Optional[Dict[str, Any]] = None     # overrides of the default Config; None: defaults


class Crop(BaseModel):
    page_id: int
    box: List[int] = Field(min_length=4, max_length=4)   # x, y, w, h in page pixels


class Split(BaseModel):
    sample_id: int
    x: int                                        # page column to cut at


class Upload(BaseModel):
    filename: str
    data: str                                     # the file, base64 encoded


class ExportRequest(BaseModel):
    folder: Optional[str] = None                  # None: <book>/exports/<date and time>
    image: Optional[str] = None                   # original | normalized | fixed64; None: the book's setting


class HelpPage(BaseModel):
    page: str                                     # a file of docs/help/, for example "new-book.html"


class FolderPath(BaseModel):
    path: str


class ReadSource(BaseModel):
    """Read Book pages (C16a): a folder of images or a PDF file, replacing earlier ones if `force`."""
    path: str
    force: bool = False


class ConvertRequest(BaseModel):
    """Convert pages into text (C16b): the given pages, or every page of a part."""
    page_ids: Optional[List[int]] = None
    part: Literal["training", "read"] = "read"
    mode: Literal["letters", "lines"] = "letters"     # "lines": Tesseract reads whole lines, no letter cutting


class TrainRequest(BaseModel):
    """Train a letter reader (C14)."""
    books: Optional[List[int]] = None              # the books to learn from (default: this one)
    min_samples: int = Field(5, ge=1)              # the least letters a label needs (asked for: down to 1)
    include_unreviewed: bool = False               # also groups labelled automatically and not reviewed
    include_words: bool = False                    # also word labels (several aksharas)
    name: str = ""


class WholeLineEdit(BaseModel):
    """A line read whole: its correction (None: unchanged; "": removed) and / or reviewed; `shown` is the text
    the user saw (kept as the checked line when it is marked reviewed without a correction)."""
    text: Optional[str] = None
    reviewed: Optional[bool] = None
    shown: str = ""


class LineTruthText(BaseModel):
    """The checked text of a line (Gujarati or Devanagari; empty: not checked) and what Tesseract read."""
    text: str = ""
    tesseract: str = ""


class WordListImport(BaseModel):
    """Import a text file as a word list (C15), used by `book_id` if given."""
    path: str
    name: str = ""
    book_id: Optional[int] = None


class WordListUse(BaseModel):
    book_id: int
    use: bool = True


class Proofread(BaseModel):
    """Mark a line of a converted page proofread, or not (C17): `line` is its index on the page."""
    line: int = Field(ge=0)
    proofread: bool = True


class ReaderChoice(BaseModel):
    reader_id: Optional[int] = None                 # None: no reader for this book


class PagePart(BaseModel):
    part: Literal["training", "read"]
    force: bool = False

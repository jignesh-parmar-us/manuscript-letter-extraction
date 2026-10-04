"""Request bodies of the API (C5c). Responses are plain JSON objects built in api.py."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class BookCreate(BaseModel):
    name: str
    input_dir: str
    settings: Optional[Dict[str, Any]] = None     # overrides of the default Config


class BookRename(BaseModel):
    name: str


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

"""Database models of the review app (C5a).

One library = one SQLite file (`library.db`). Everything goes through SQLAlchemy, and the schema is
created and changed only by Alembic migrations (`migrations/`), so the same models can later run on
MySQL or PostgreSQL.

File paths (letter, mask and line images) are stored relative to the book's folder in the library;
input pages are stored as the book's input folder plus the file name, with a SHA-256 checksum.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (Boolean, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text,
                        TypeDecorator, UniqueConstraint, event)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Timestamps in UTC. SQLite stores no time zone, so values read back are marked as UTC again."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class Base(DeclarativeBase):
    pass


class Book(Base):
    """A manuscript: its input folder, the settings it was cut with, and everything found in it."""
    __tablename__ = "book"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    folder: Mapped[str] = mapped_column(String(200), unique=True)    # books/<folder> in the library
    input_dir: Mapped[str] = mapped_column(Text)
    settings: Mapped[str] = mapped_column(Text, default="{}")         # Config as JSON
    writing: Mapped[str] = mapped_column(String(12), default="handwritten")   # handwritten | printed (C10)
    # Read Book (C16a): a folder of images, or the name of an uploaded PDF whose pages are in read/pages/
    read_dir: Mapped[str] = mapped_column(Text, default="")
    read_pdf: Mapped[str] = mapped_column(String(500), default="")
    reader_id: Mapped[Optional[int]] = mapped_column(ForeignKey("reader.id", ondelete="SET NULL"), nullable=True)  # C14
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now, onupdate=now)
    captured_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)

    pages: Mapped[List["Page"]] = relationship(back_populates="book", cascade="all, delete-orphan",
                                               order_by="Page.id")
    groups: Mapped[List["LetterGroup"]] = relationship(back_populates="book", cascade="all, delete-orphan",
                                                       order_by="LetterGroup.id")


class Page(Base):
    __tablename__ = "page"
    __table_args__ = (UniqueConstraint("book_id", "folder", "file", name="uq_page_book_folder_file"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("book.id", ondelete="CASCADE"), index=True)
    file: Mapped[str] = mapped_column(String(500))                   # file name in its folder
    part: Mapped[str] = mapped_column(String(10), default="training")    # training | read: how it is used (C16a)
    folder: Mapped[str] = mapped_column(String(10), default="training")  # training | read: where its file is
    number: Mapped[int] = mapped_column(Integer, default=0)              # its place in the book
    sha256: Mapped[str] = mapped_column(String(64), default="")
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="OK")    # as in report.csv
    message: Mapped[str] = mapped_column(Text, default="")
    line_spacing: Mapped[float] = mapped_column(Float, default=0.0)
    seconds: Mapped[float] = mapped_column(Float, default=0.0)

    book: Mapped[Book] = relationship(back_populates="pages")
    lines: Mapped[List["Line"]] = relationship(back_populates="page", cascade="all, delete-orphan",
                                               order_by="Line.number")


class Line(Base):
    __tablename__ = "line"
    __table_args__ = (UniqueConstraint("page_id", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("page.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    x: Mapped[int] = mapped_column(Integer)
    y: Mapped[int] = mapped_column(Integer)
    w: Mapped[int] = mapped_column(Integer)
    h: Mapped[int] = mapped_column(Integer)
    ink: Mapped[str] = mapped_column(String(10))
    image: Mapped[str] = mapped_column(String(500))

    page: Mapped[Page] = relationship(back_populates="lines")


class LetterGroup(Base):
    """A group of samples that are the same letter. Its label is stored in Devanagari (the canonical
    form) and, derived from it, in Gujarati."""
    __tablename__ = "letter_group"
    __table_args__ = (UniqueConstraint("book_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("book.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(20))                     # g0001, ...
    kind: Mapped[str] = mapped_column(String(10), default="letter")   # letter | danda | digit
    label_dev: Mapped[str] = mapped_column(String(50), default="")
    label_guj: Mapped[str] = mapped_column(String(50), default="")
    status: Mapped[str] = mapped_column(String(10), default="auto")   # auto | reviewed | labelled
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    rejected_dev: Mapped[str] = mapped_column(String(50), default="")   # suggested label the user rejected (C11)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now, onupdate=now)

    book: Mapped[Book] = relationship(back_populates="groups")
    samples: Mapped[List["Sample"]] = relationship(back_populates="group")


class Sample(Base):
    """One cut-out letter. `group_id` empty means the sample is unsure."""
    __tablename__ = "sample"
    # the letter counts read only this index, not the rows (about 6 KB each, the fingerprint): migration 0008
    __table_args__ = (Index("ix_sample_counts", "book_id", "part", "deleted", "group_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("book.id", ondelete="CASCADE"), index=True)
    page_id: Mapped[Optional[int]] = mapped_column(ForeignKey("page.id", ondelete="CASCADE"), index=True,
                                                   nullable=True)        # empty for uploaded samples
    part: Mapped[str] = mapped_column(String(10), default="training", index=True)   # its page's part (C16a)
    line_id: Mapped[Optional[int]] = mapped_column(ForeignKey("line.id", ondelete="CASCADE"), nullable=True)
    line_number: Mapped[int] = mapped_column(Integer, default=0)
    pos: Mapped[int] = mapped_column(Integer, default=0)                  # reading order within the line
    x: Mapped[int] = mapped_column(Integer, default=0)
    y: Mapped[int] = mapped_column(Integer, default=0)
    w: Mapped[int] = mapped_column(Integer, default=0)
    h: Mapped[int] = mapped_column(Integer, default=0)
    ink: Mapped[str] = mapped_column(String(10), default="black")
    kind: Mapped[str] = mapped_column(String(10), default="letter")
    pieces: Mapped[int] = mapped_column(Integer, default=1)
    rules: Mapped[str] = mapped_column(Text, default="")
    image: Mapped[str] = mapped_column(String(500))
    mask: Mapped[str] = mapped_column(String(500), default="")
    fingerprint: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)   # float32 vector
    source: Mapped[str] = mapped_column(String(10), default="auto")   # auto | cropped | joined | split | uploaded
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    group_id: Mapped[Optional[int]] = mapped_column(ForeignKey("letter_group.id", ondelete="SET NULL"),
                                                    index=True, nullable=True)
    distance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)

    group: Mapped[Optional[LetterGroup]] = relationship(back_populates="samples")


class OcrRun(Base):
    """One run of a reader over a book (C11): Tesseract now, other books and the classifier later.
    Only the newest finished run per engine is kept."""
    __tablename__ = "ocr_run"
    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("book.id", ondelete="CASCADE"), index=True)
    engine: Mapped[str] = mapped_column(String(20))                   # tesseract | books | classifier
    settings: Mapped[str] = mapped_column(Text, default="{}")         # what it ran with, as JSON
    result: Mapped[str] = mapped_column(Text, default="{}")           # its counts, as JSON
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)


class OcrReading(Base):
    """What a run read for one sample; samples it could not match get no row."""
    __tablename__ = "ocr_reading"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("ocr_run.id", ondelete="CASCADE"), index=True)
    sample_id: Mapped[int] = mapped_column(ForeignKey("sample.id", ondelete="CASCADE"), index=True)
    text_dev: Mapped[str] = mapped_column(String(50))                 # Devanagari NFC, a valid label
    confidence: Mapped[float] = mapped_column(Float)                  # 0 to 100
    alternatives: Mapped[str] = mapped_column(Text, default="[]")     # per character: [[text, confidence], ...]
    overlap: Mapped[float] = mapped_column(Float, default=0.0)


class Reader(Base):
    """A trained letter reader (C14). Readers belong to the library: one trained on several books can be
    the active reader of another. Its files are in <library>/readers/<folder>/ (reader.npz, reader.json)."""
    __tablename__ = "reader"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    folder: Mapped[str] = mapped_column(String(200), unique=True)
    kind: Mapped[str] = mapped_column(String(30), default="features-linear")     # features-linear | features-mlp
    classes: Mapped[str] = mapped_column(Text, default="[]")                       # JSON: labels (Devanagari NFC)
    trained_on: Mapped[str] = mapped_column(Text, default="{}")                    # JSON: books, counts, choices
    accuracy: Mapped[str] = mapped_column(Text, default="{}")                      # JSON: overall, per label
    report: Mapped[str] = mapped_column(Text, default="{}")                        # JSON: confusions, check list
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class PageText(Base):
    """A page converted into text (C16b): one row per page, replaced when it is converted again.
    `letters` holds every letter with its sample, box, text, confidence, source and whether it is
    uncertain, line by line, so each letter of the text can be traced to the page. `proofread` (C17)
    maps a proofread line's number to its text when it was marked; converting again keeps those lines."""
    __tablename__ = "page_text"
    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("page.id", ondelete="CASCADE"), unique=True, index=True)
    text_dev: Mapped[str] = mapped_column(Text, default="")                # plain, line breaks kept
    text_guj: Mapped[str] = mapped_column(Text, default="")
    letters: Mapped[str] = mapped_column(Text, default="[]")               # JSON, per line a list of letters
    uncertain: Mapped[int] = mapped_column(Integer, default=0)
    readers: Mapped[str] = mapped_column(String(100), default="")          # e.g. "tesseract+groups"
    converted_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)
    proofread: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")   # JSON {line: text_dev}
    edited_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)


class Action(Base):
    """Every change made by the user, for undo and history (C5c). `payload` is JSON."""
    __tablename__ = "action"
    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("book.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    payload: Mapped[str] = mapped_column(Text, default="{}")
    undone: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record) -> None:
    """SQLite only: enforce foreign keys (cascades) and use write-ahead logging (safe, fast saves)."""
    module = type(dbapi_connection).__module__
    if "sqlite" in module:
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

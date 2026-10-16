"""Datasets and books become separate things (Phase 3, C20): `book.kind` (dataset | book, every existing row is
a dataset), `book.read_dataset_id` (the dataset a book learns from), and a name unique per kind instead of in
the whole library (a dataset and the book read with it may share a name).

Only the schema changes here. Splitting existing rows that hold both Training Data and Read Book pages is a
separate command (`python -m letter_extractor.app.split`), run after a backup and a dry run: see split.py.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

# the unique constraints of the first migration have no names in SQLite: name them to drop one
NAMES = {"uq": "uq_%(table_name)s_%(column_0_name)s"}


def upgrade() -> None:
    with op.batch_alter_table("book", naming_convention=NAMES) as batch:
        batch.add_column(sa.Column("kind", sa.String(10), nullable=False, server_default="dataset"))
        batch.add_column(sa.Column("read_dataset_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_book_read_dataset", "book", ["read_dataset_id"], ["id"], ondelete="SET NULL")
        batch.drop_constraint("uq_book_name", type_="unique")
        batch.create_unique_constraint("uq_book_kind_name", ["kind", "name"])


def downgrade() -> None:
    with op.batch_alter_table("book", naming_convention=NAMES) as batch:
        batch.drop_constraint("uq_book_kind_name", type_="unique")
        batch.create_unique_constraint("uq_book_name", ["name"])
        batch.drop_constraint("fk_book_read_dataset", type_="foreignkey")
        batch.drop_column("read_dataset_id")
        batch.drop_column("kind")

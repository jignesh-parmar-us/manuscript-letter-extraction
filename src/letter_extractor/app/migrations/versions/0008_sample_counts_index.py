"""An index for counting a book's letters (speed).

The book list, the header and the Review side bar count letters by book, part, deleted and group
(42 counts for the book list of the user's library). Each count read every matching row, and a row is
about 6 KB (the fingerprint): 0.1 to 0.17 s per count, 1.7 s for the book list. This index holds all
four columns, so the counts read only the index.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-10
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_sample_counts", "sample", ["book_id", "part", "deleted", "group_id"])


def downgrade() -> None:
    op.drop_index("ix_sample_counts", table_name="sample")

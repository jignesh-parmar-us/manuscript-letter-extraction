"""Word lists for the language model (C15): imported text files and the books that use them.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-10
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "word_list",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("file", sa.String(200), nullable=False, unique=True),
        sa.Column("lines", sa.Integer(), nullable=False),
        sa.Column("aksharas", sa.Integer(), nullable=False),
        sa.Column("books", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("word_list")

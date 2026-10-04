"""First schema: books, pages, lines, letter groups, samples, actions.

Revision ID: 0001
Revises:
Create Date: 2026-10-04
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "book",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column("folder", sa.String(200), nullable=False, unique=True),
        sa.Column("input_dir", sa.Text(), nullable=False),
        sa.Column("settings", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "page",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("book.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file", sa.String(500), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("line_spacing", sa.Float(), nullable=False),
        sa.Column("seconds", sa.Float(), nullable=False),
        sa.UniqueConstraint("book_id", "file"),
    )
    op.create_index("ix_page_book_id", "page", ["book_id"])
    op.create_table(
        "line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("page_id", sa.Integer(), sa.ForeignKey("page.id", ondelete="CASCADE"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("x", sa.Integer(), nullable=False),
        sa.Column("y", sa.Integer(), nullable=False),
        sa.Column("w", sa.Integer(), nullable=False),
        sa.Column("h", sa.Integer(), nullable=False),
        sa.Column("ink", sa.String(10), nullable=False),
        sa.Column("image", sa.String(500), nullable=False),
        sa.UniqueConstraint("page_id", "number"),
    )
    op.create_index("ix_line_page_id", "line", ["page_id"])
    op.create_table(
        "letter_group",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("book.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("label_dev", sa.String(50), nullable=False),
        sa.Column("label_guj", sa.String(50), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("book_id", "code"),
    )
    op.create_index("ix_letter_group_book_id", "letter_group", ["book_id"])
    op.create_table(
        "sample",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("book.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_id", sa.Integer(), sa.ForeignKey("page.id", ondelete="CASCADE"), nullable=True),
        sa.Column("line_id", sa.Integer(), sa.ForeignKey("line.id", ondelete="CASCADE"), nullable=True),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("pos", sa.Integer(), nullable=False),
        sa.Column("x", sa.Integer(), nullable=False),
        sa.Column("y", sa.Integer(), nullable=False),
        sa.Column("w", sa.Integer(), nullable=False),
        sa.Column("h", sa.Integer(), nullable=False),
        sa.Column("ink", sa.String(10), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("pieces", sa.Integer(), nullable=False),
        sa.Column("rules", sa.Text(), nullable=False),
        sa.Column("image", sa.String(500), nullable=False),
        sa.Column("mask", sa.String(500), nullable=False),
        sa.Column("fingerprint", sa.LargeBinary(), nullable=True),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("deleted", sa.Boolean(), nullable=False),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("letter_group.id", ondelete="SET NULL"), nullable=True),
        sa.Column("distance", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sample_book_id", "sample", ["book_id"])
    op.create_index("ix_sample_page_id", "sample", ["page_id"])
    op.create_index("ix_sample_group_id", "sample", ["group_id"])
    op.create_table(
        "action",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("book.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("undone", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_action_book_id", "action", ["book_id"])


def downgrade() -> None:
    for table in ("action", "sample", "letter_group", "line", "page", "book"):
        op.drop_table(table)

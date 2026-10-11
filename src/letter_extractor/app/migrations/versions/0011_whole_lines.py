"""Whole lines: Read Book lines read by Tesseract as whole images, without letter cutting.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-11
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "whole_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("line_id", sa.Integer(), sa.ForeignKey("line.id", ondelete="CASCADE"), nullable=False),
        sa.Column("engine", sa.String(20), nullable=False),
        sa.Column("text_dev", sa.Text(), nullable=False),
        sa.Column("aksharas", sa.Text(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_whole_line_line_id", "whole_line", ["line_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_whole_line_line_id", table_name="whole_line")
    op.drop_table("whole_line")

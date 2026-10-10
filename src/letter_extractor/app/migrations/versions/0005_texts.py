"""Pages converted into text (C16b): page_text, one row per page.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-10
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "page_text",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("page_id", sa.Integer(), sa.ForeignKey("page.id", ondelete="CASCADE"), nullable=False),
        sa.Column("text_dev", sa.Text(), nullable=False),
        sa.Column("text_guj", sa.Text(), nullable=False),
        sa.Column("letters", sa.Text(), nullable=False),
        sa.Column("uncertain", sa.Integer(), nullable=False),
        sa.Column("readers", sa.String(100), nullable=False),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_page_text_page_id", "page_text", ["page_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_page_text_page_id", "page_text")
    op.drop_table("page_text")

"""The line truth screen: the checked text of lines, the test set for comparing ways of reading.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-11
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "line_truth",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("line_id", sa.Integer(), sa.ForeignKey("line.id", ondelete="CASCADE"), nullable=False),
        sa.Column("text_dev", sa.Text(), nullable=False),
        sa.Column("tesseract_dev", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_line_truth_line_id", "line_truth", ["line_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_line_truth_line_id", table_name="line_truth")
    op.drop_table("line_truth")

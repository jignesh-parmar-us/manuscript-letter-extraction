"""OCR runs and their readings per sample; the label a user rejected for a group (C11).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-05
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ocr_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("book.id", ondelete="CASCADE"), nullable=False),
        sa.Column("engine", sa.String(20), nullable=False),
        sa.Column("settings", sa.Text(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ocr_run_book_id", "ocr_run", ["book_id"])
    op.create_table(
        "ocr_reading",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("ocr_run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sample_id", sa.Integer(), sa.ForeignKey("sample.id", ondelete="CASCADE"), nullable=False),
        sa.Column("text_dev", sa.String(50), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("alternatives", sa.Text(), nullable=False),
        sa.Column("overlap", sa.Float(), nullable=False),
    )
    op.create_index("ix_ocr_reading_run_id", "ocr_reading", ["run_id"])
    op.create_index("ix_ocr_reading_sample_id", "ocr_reading", ["sample_id"])
    with op.batch_alter_table("letter_group") as batch:
        batch.add_column(sa.Column("rejected_dev", sa.String(50), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("letter_group") as batch:
        batch.drop_column("rejected_dev")
    op.drop_table("ocr_reading")
    op.drop_table("ocr_run")

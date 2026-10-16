"""An index on sample.line_id: "the letters of this line" (the line search's training, Measure, reading) read the
whole sample table without it, about 130,000 rows on the development library (docs/SPEED_PLAN.md, S5).

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-16
"""
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_sample_line_id", "sample", ["line_id"])


def downgrade() -> None:
    op.drop_index("ix_sample_line_id", table_name="sample")

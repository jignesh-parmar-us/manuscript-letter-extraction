"""Whole lines: the line search's reading of a line, a second opinion that marks where it differs.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-11
"""
import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("whole_line", sa.Column("search_dev", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("whole_line") as batch:
        batch.drop_column("search_dev")

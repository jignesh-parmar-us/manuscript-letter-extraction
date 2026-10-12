"""Whole lines (our reader): the line search's aksharas with their places on the page, and when it read.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-12
"""
import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("whole_line", sa.Column("search_aksharas", sa.Text(), nullable=False, server_default="[]"))
    op.add_column("whole_line", sa.Column("search_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("whole_line") as batch:
        batch.drop_column("search_at")
        batch.drop_column("search_aksharas")

"""Proofreading (C17): the proofread lines of each converted page.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-10
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # plain ADD COLUMN: no table rebuild, so nothing can cascade
    op.add_column("page_text", sa.Column("proofread", sa.Text(), nullable=False, server_default="{}"))
    op.add_column("page_text", sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("page_text") as batch:
        batch.drop_column("edited_at")
        batch.drop_column("proofread")

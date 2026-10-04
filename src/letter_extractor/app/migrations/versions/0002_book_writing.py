"""How a book is written: handwritten or printed (C10). Existing books become handwritten.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-04
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("book") as batch:
        batch.add_column(sa.Column("writing", sa.String(12), nullable=False, server_default="handwritten"))


def downgrade() -> None:
    with op.batch_alter_table("book") as batch:
        batch.drop_column("writing")

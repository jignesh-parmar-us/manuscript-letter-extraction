"""Possible mix-ups: a letter the user said is in the right group (not a mix-up), for that group's label.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-12
"""
import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sample", sa.Column("confirmed_label", sa.String(50), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("sample") as batch:
        batch.drop_column("confirmed_label")

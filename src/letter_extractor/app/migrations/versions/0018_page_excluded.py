"""Excluded pages (Phase 3, C22): `page.excluded`. An excluded page is kept with everything on it but skipped:
in a book by Prepare, reading, Measure and export; in a dataset by capture, training and export. A page whose file
is not prepared (or captured) yet is excluded with a row of its own that has no lines (library.set_page_excluded).

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("page") as batch:
        batch.add_column(sa.Column("excluded", sa.Boolean(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("page") as batch:
        batch.drop_column("excluded")

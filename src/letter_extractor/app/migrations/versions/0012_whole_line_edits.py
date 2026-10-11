"""Whole lines: the user's correction of a line and whether it is reviewed.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-11
"""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("whole_line", sa.Column("edited_dev", sa.Text(), nullable=False, server_default=""))
    op.add_column("whole_line", sa.Column("reviewed", sa.Boolean(), nullable=False, server_default="0"))
    op.add_column("whole_line", sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("whole_line") as batch:
        batch.drop_column("edited_at")
        batch.drop_column("reviewed")
        batch.drop_column("edited_dev")

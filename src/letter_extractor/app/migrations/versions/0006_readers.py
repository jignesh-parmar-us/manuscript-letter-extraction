"""Trained letter readers (C14): the reader table, and each book's active reader.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-10
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reader",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("folder", sa.String(200), nullable=False, unique=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("classes", sa.Text(), nullable=False),
        sa.Column("trained_on", sa.Text(), nullable=False),
        sa.Column("accuracy", sa.Text(), nullable=False),
        sa.Column("report", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    with op.batch_alter_table("book") as batch:
        batch.add_column(sa.Column("reader_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_book_reader", "reader", ["reader_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("book") as batch:
        batch.drop_constraint("fk_book_reader", type_="foreignkey")
        batch.drop_column("reader_id")
    op.drop_table("reader")

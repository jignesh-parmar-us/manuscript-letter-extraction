"""The two parts of a book (C16a): Training Data and Read Book.

Book + read_dir (the Read Book folder of images; empty = none) and read_pdf (the name of an uploaded
PDF whose pages were turned into images in the book's read/pages/ folder). Page + part (training |
read: how the page is used), folder (training | read: which folder its file is in; they differ only
for a page moved across) and number (its place in the book); a page file is unique per book and
folder. Sample + part, the part of its page, so the review screens can leave Read Book letters out.
Existing pages and samples become training ones.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-10
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

# SQLite reflects the old unnamed unique constraint without a name: this gives it one to drop
NAMING = {"uq": "uq_%(table_name)s_%(column_0_name)s_%(column_1_name)s"}


def upgrade() -> None:
    with op.batch_alter_table("book") as batch:
        batch.add_column(sa.Column("read_dir", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("read_pdf", sa.String(500), nullable=False, server_default=""))
    with op.batch_alter_table("page", recreate="always", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("part", sa.String(10), nullable=False, server_default="training"))
        batch.add_column(sa.Column("folder", sa.String(10), nullable=False, server_default="training"))
        batch.add_column(sa.Column("number", sa.Integer(), nullable=False, server_default="0"))
        batch.drop_constraint("uq_page_book_id_file", type_="unique")
        batch.create_unique_constraint("uq_page_book_folder_file", ["book_id", "folder", "file"])
    with op.batch_alter_table("sample") as batch:
        batch.add_column(sa.Column("part", sa.String(10), nullable=False, server_default="training"))
        batch.create_index("ix_sample_part", ["part"])


def downgrade() -> None:
    with op.batch_alter_table("sample") as batch:
        batch.drop_index("ix_sample_part")
        batch.drop_column("part")
    op.execute("DELETE FROM page WHERE part != 'training' OR folder != 'training'")
    with op.batch_alter_table("page", recreate="always") as batch:
        batch.drop_constraint("uq_page_book_folder_file", type_="unique")
        batch.create_unique_constraint("uq_page_book_id_file", ["book_id", "file"])
        batch.drop_column("number")
        batch.drop_column("folder")
        batch.drop_column("part")
    with op.batch_alter_table("book") as batch:
        batch.drop_column("read_pdf")
        batch.drop_column("read_dir")

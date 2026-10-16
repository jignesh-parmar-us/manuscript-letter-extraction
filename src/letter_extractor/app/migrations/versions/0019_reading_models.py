"""Reading models (Phase 3, C23): what a book reads with, trained from the datasets it chooses.

- `reading_model` (name, folder in <library>/models/): each book gets its own (lean plan, decision 6); the table
  is built so that books could share one later.
- `reading_model_dataset` (model, dataset): the datasets a model learns from, several allowed; a deleted dataset
  leaves every model (ON DELETE CASCADE).
- `book.reading_model_id` replaces `book.read_dataset_id` (C20's one linked dataset): every book gets a model named
  like it, its folder named like the book's folder, learning from that dataset (none if it had none).

No file is moved here: the line-search reader moves from the book folder to the model folder the first time it is
used (linesearch._folder), a rename on the same disk.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reading_model",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("folder", sa.String(200), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "reading_model_dataset",
        sa.Column("model_id", sa.Integer(), sa.ForeignKey("reading_model.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("dataset_id", sa.Integer(), sa.ForeignKey("book.id", ondelete="CASCADE"), primary_key=True),
    )
    with op.batch_alter_table("book") as batch:
        batch.add_column(sa.Column("reading_model_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_book_reading_model", "reading_model", ["reading_model_id"], ["id"],
                                 ondelete="SET NULL")
    conn = op.get_bind()
    books = conn.execute(sa.text("SELECT id, name, folder, read_dataset_id, created_at FROM book "
                                 "WHERE kind = 'book' ORDER BY id")).fetchall()
    for bid, name, folder, dataset, created in books:
        conn.execute(sa.text("INSERT INTO reading_model (name, folder, created_at) VALUES (:n, :f, :c)"),
                     {"n": name, "f": folder, "c": created})
        mid = conn.execute(sa.text("SELECT id FROM reading_model WHERE folder = :f"), {"f": folder}).scalar()
        if dataset is not None:
            conn.execute(sa.text("INSERT INTO reading_model_dataset (model_id, dataset_id) VALUES (:m, :d)"),
                         {"m": mid, "d": dataset})
        conn.execute(sa.text("UPDATE book SET reading_model_id = :m WHERE id = :b"), {"m": mid, "b": bid})
    with op.batch_alter_table("book") as batch:
        batch.drop_constraint("fk_book_read_dataset", type_="foreignkey")
        batch.drop_column("read_dataset_id")


def downgrade() -> None:
    with op.batch_alter_table("book") as batch:
        batch.add_column(sa.Column("read_dataset_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_book_read_dataset", "book", ["read_dataset_id"], ["id"], ondelete="SET NULL")
    op.execute("UPDATE book SET read_dataset_id = (SELECT min(dataset_id) FROM reading_model_dataset "
               "WHERE model_id = book.reading_model_id)")
    with op.batch_alter_table("book") as batch:
        batch.drop_constraint("fk_book_reading_model", type_="foreignkey")
        batch.drop_column("reading_model_id")
    op.drop_table("reading_model_dataset")
    op.drop_table("reading_model")

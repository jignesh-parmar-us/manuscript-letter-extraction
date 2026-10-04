"""Alembic environment: run by `library.migrate()` with an open connection (no alembic.ini needed)."""
from alembic import context

from letter_extractor.app.db import Base

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("Migrations are run by letter_extractor.app.library, which passes a connection.")

context.configure(connection=connection, target_metadata=Base.metadata,
                  render_as_batch=True)       # batch mode: ALTER TABLE also works on SQLite
with context.begin_transaction():
    context.run_migrations()

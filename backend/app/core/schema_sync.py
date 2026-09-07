"""
Adds any model columns that don't exist yet in the actual database.

Background: `Base.metadata.create_all()` only creates whole tables
that are missing -- it never ALTERs an existing table to add columns
the model gained after that table was first created. On a hackathon
build without Alembic, that means any column added to a model later
(e.g. Inspection.cctv_feed_url, added after the inspections table
already existed in someone's local Postgres) silently never appears
in the real database. The app then crashes the instant it tries to
INSERT/UPDATE that column, with
"column ... of relation ... does not exist".

This module closes that gap generically, for every mapped table: it
diffs the model's declared columns against the database's actual
columns and ADD COLUMNs whatever's missing.

New columns are always added as NULLable, regardless of the model's
own nullable=False/True. Retroactively enforcing NOT NULL on a table
that may already have rows requires a real backfill (what value goes
in the existing rows?), which is out of scope for an automatic
startup self-heal -- the application layer (Pydantic schemas / the
column's Python-side `default=`) still enforces the "real" constraint
for anything written going forward. Safe to call on every startup: a
fresh database, or one already matching the models, has nothing to
add.
"""
import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.database import Base

logger = logging.getLogger(__name__)


def add_missing_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                # Brand-new table -- create_all() (called right before
                # this, in the lifespan startup) already created it
                # with every current column. Nothing to do.
                continue

            existing_columns = {
                col["name"] for col in inspector.get_columns(table.name)
            }

            for column in table.columns:
                if column.name in existing_columns:
                    continue

                col_type = column.type.compile(dialect=engine.dialect)
                logger.warning(
                    "Adding missing column %s.%s (%s)",
                    table.name,
                    column.name,
                    col_type,
                )
                conn.execute(
                    text(
                        f'ALTER TABLE "{table.name}" '
                        f'ADD COLUMN "{column.name}" {col_type}'
                    )
                )

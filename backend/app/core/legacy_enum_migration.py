"""
One-time, idempotent self-heal for Postgres enum columns.

Background: User.role, Inspection.status, Inspection.inspection_type,
and Project.entity_type are all
`Enum(SomePyEnum, values_callable=lambda e: [m.value for m in e])`
columns -- meaning the DB should store the enum's lowercase *values*
("admin", "pending", ...) rather than SQLAlchemy's older default of
storing the enum member *names* ("ADMIN", "PENDING", ...).

Any database created before `values_callable` was added still has a
Postgres enum TYPE whose labels are the old uppercase names, plus rows
using those labels. `Base.metadata.create_all()` only creates tables/
types that don't exist yet, so it silently leaves such a stale type in
place -- the app then crashes the instant it reads an affected row,
since the current model no longer recognizes "ADMIN" etc.

This module detects that mismatch per enum column and migrates the
Postgres type + column in place: rename the old type, create a new one
with the correct (lowercase) labels, cast the column over with
`lower()`, drop the old type. It's safe to call on every startup --
a fresh database or an already-migrated one has nothing to fix here.
"""
import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.models.user import User, UserRole
from app.models.inspection import Inspection, InspectionStatus, InspectionType
from app.models.project import Project, EntityType

logger = logging.getLogger(__name__)

# (table, column name, Python enum class backing that column)
_ENUM_COLUMNS = [
    (User.__table__, "role", UserRole),
    (Inspection.__table__, "status", InspectionStatus),
    (Inspection.__table__, "inspection_type", InspectionType),
    (Project.__table__, "entity_type", EntityType),
]


def normalize_legacy_enum_types(engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        # SQLite/etc. store enums as plain VARCHAR with a CHECK
        # constraint, not a native type -- nothing to migrate there.
        return

    with engine.begin() as conn:
        for table, column_name, enum_cls in _ENUM_COLUMNS:
            column = table.c[column_name]
            type_name = column.type.name
            expected_values = [member.value for member in enum_cls]

            existing_labels = conn.execute(
                text(
                    "SELECT e.enumlabel FROM pg_type t "
                    "JOIN pg_enum e ON t.oid = e.enumtypid "
                    "WHERE t.typname = :type_name "
                    "ORDER BY e.enumsortorder"
                ),
                {"type_name": type_name},
            ).scalars().all()

            if not existing_labels:
                # Type doesn't exist yet -- create_all (called right
                # before this) will have made it fresh with the
                # correct values already. Nothing to do.
                continue

            if set(existing_labels) == set(expected_values):
                # Already using current values.
                continue

            logger.warning(
                "Migrating legacy Postgres enum type %r on %s.%s: %s -> %s",
                type_name,
                table.name,
                column_name,
                existing_labels,
                expected_values,
            )

            legacy_type_name = f"{type_name}_legacy"
            table_ident = f'"{table.name}"'
            column_ident = f'"{column_name}"'
            new_values_sql = ", ".join(f"'{v}'" for v in expected_values)

            conn.execute(text(f'ALTER TYPE "{type_name}" RENAME TO "{legacy_type_name}"'))
            conn.execute(text(f'CREATE TYPE "{type_name}" AS ENUM ({new_values_sql})'))
            conn.execute(
                text(
                    f'ALTER TABLE {table_ident} '
                    f'ALTER COLUMN {column_ident} TYPE "{type_name}" '
                    f'USING (lower({column_ident}::text)::"{type_name}")'
                )
            )
            conn.execute(text(f'DROP TYPE "{legacy_type_name}"'))

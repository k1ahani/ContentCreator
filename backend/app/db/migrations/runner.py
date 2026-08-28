"""Migration runner.

Migrations are plain ``.sql`` files in ``versions/`` named
``NNNN_description.sql``. They are applied in filename order, each inside a
single transaction, and recorded in ``schema_migrations``. There is no "down"
direction on purpose: this is a local single-user application, and a reversible
migration system would be more machinery than it earns. To undo, restore the
database file (or delete ``storage/app.db`` to start clean).

To add a migration: drop a new file with the next number into ``versions/``.
The runner picks it up on the next start. See docs/DATABASE.md.

Why statements are split by hand instead of using ``executescript``: with
``isolation_level=None`` an explicit ``BEGIN`` is open, and ``executescript``
commits any pending transaction before it runs - which would silently defeat
the per-migration atomicity we want. The splitter below is string-literal aware
and sufficient for DDL; migrations must therefore not contain triggers with
``BEGIN ... END`` bodies (use application code instead).
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.logging import get_logger
from app.db.connection import Database

logger = get_logger(__name__)

VERSIONS_DIR = Path(__file__).parent / "versions"
_FILENAME_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")

_BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    applied_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


def split_statements(sql: str) -> list[str]:
    """Split a SQL script into individual statements.

    Handles ``--`` line comments and single-quoted literals (including the
    doubled ``''`` escape). Does not handle ``BEGIN ... END`` trigger bodies,
    which migrations are not allowed to contain.
    """
    statements: list[str] = []
    current: list[str] = []
    in_string = False
    in_line_comment = False
    index = 0
    length = len(sql)

    while index < length:
        char = sql[index]

        if in_line_comment:
            if char == "\n":
                in_line_comment = False
                current.append(char)
            index += 1
            continue

        if in_string:
            current.append(char)
            if char == "'":
                # A doubled quote is an escaped quote, not a terminator.
                if index + 1 < length and sql[index + 1] == "'":
                    current.append(sql[index + 1])
                    index += 2
                    continue
                in_string = False
            index += 1
            continue

        if char == "-" and index + 1 < length and sql[index + 1] == "-":
            in_line_comment = True
            index += 2
            continue

        if char == "'":
            in_string = True
            current.append(char)
            index += 1
            continue

        if char == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            index += 1
            continue

        current.append(char)
        index += 1

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def discover_migrations() -> list[tuple[str, Path]]:
    """Return ``(version, path)`` pairs sorted by version."""
    found: list[tuple[str, Path]] = []
    for file in sorted(VERSIONS_DIR.glob("*.sql")):
        match = _FILENAME_RE.match(file.name)
        if not match:
            raise ValueError(
                f"migration {file.name!r} does not match NNNN_description.sql"
            )
        found.append((match.group(1), file))

    versions = [version for version, _ in found]
    if len(set(versions)) != len(versions):
        raise ValueError(f"duplicate migration version numbers: {versions}")
    return found


def applied_versions(db: Database) -> set[str]:
    rows = db.query_all("SELECT version FROM schema_migrations")
    return {row["version"] for row in rows}


def migrate(db: Database) -> list[str]:
    """Apply every pending migration. Returns the versions applied."""
    db.execute(_BOOTSTRAP)
    already = applied_versions(db)
    newly_applied: list[str] = []
    conn = db.connection

    for version, file in discover_migrations():
        if version in already:
            continue
        statements = split_statements(file.read_text(encoding="utf-8"))
        logger.info("applying migration %s (%s), %d statements", version, file.name, len(statements))

        conn.execute("BEGIN")
        try:
            for statement in statements:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_migrations (version, filename) VALUES (?, ?)",
                (version, file.name),
            )
        except Exception:
            conn.execute("ROLLBACK")
            logger.exception("migration %s failed and was rolled back", version)
            raise
        conn.execute("COMMIT")
        newly_applied.append(version)

    if newly_applied:
        logger.info("applied %d migration(s): %s", len(newly_applied), newly_applied)
    else:
        logger.debug("database schema is up to date")
    return newly_applied

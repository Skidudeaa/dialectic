"""
Minimal SQL migration runner.

WHY: CREATE TABLE IF NOT EXISTS works until it doesn't — schema changes
(ADD COLUMN, new indexes) need tracked migrations. This runner is
deliberately simple: numbered .sql files, a schema_migrations table,
and sequential application. No rollback, no down migrations — for a
2-user system, manual intervention on migration failure is acceptable.
"""

import logging
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "sql"


def run_migrations(conn: sqlite3.Connection) -> int:
    """Apply pending migrations. Returns count applied.

    WHY: Each migration runs in its own implicit transaction via
    executescript(). The version is recorded after successful execution.
    If a migration fails, the schema_migrations table shows exactly
    where it stopped.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version  INTEGER PRIMARY KEY,
            name     TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()

    applied = {
        row[0] for row in conn.execute("SELECT version FROM schema_migrations")
    }

    migrations = sorted(MIGRATIONS_DIR.glob("*.sql"))
    count = 0
    for path in migrations:
        # Parse version from filename: 001_create_tables.sql → 1
        stem = path.stem
        try:
            version = int(stem.split("_", 1)[0])
        except (ValueError, IndexError):
            log.warning("Skipping non-versioned migration file: %s", path.name)
            continue

        if version in applied:
            continue

        sql = path.read_text()
        log.info("Applying migration %03d: %s", version, stem)
        try:
            # WHY executescript: handles multi-statement SQL (CREATE TABLE
            # + CREATE INDEX in one file). It auto-commits.
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                (version, stem),
            )
            conn.commit()
            count += 1
            log.info("Migration %03d applied successfully", version)
        except Exception:
            log.exception("Migration %03d FAILED: %s", version, stem)
            raise

    return count

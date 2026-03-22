"""
SQLite database connection and schema management.

ARCHITECTURE: Single WAL-mode database with async access via aiosqlite.
WHY: Zero-setup local storage with concurrent read/write support.
TRADEOFF: Single-file DB limits to ~22K writes/sec — more than sufficient
for expected peak of ~35 events/sec.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

import aiosqlite

from cc_sidecar.constants import DATABASE_PATH, DATA_DIR, DIR_MODE, FILE_MODE

logger = logging.getLogger(__name__)

# WHY: Schema lives alongside the code so it can be applied on first run
# without external file dependencies.
_SCHEMA_PATH = Path(__file__).parent.parent.parent / "schema.sql"


async def get_connection(
    db_path: Optional[Path] = None,
) -> aiosqlite.Connection:
    """
    Open a WAL-mode SQLite connection.

    Creates the database directory and file if they don't exist,
    with secure permissions (0700 dir, 0600 file).
    """
    path = db_path or DATABASE_PATH
    path.parent.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)

    db = await aiosqlite.connect(str(path))

    # WHY: WAL mode allows concurrent readers while writing.
    await db.execute("PRAGMA journal_mode = WAL")
    # WHY: Prevents SQLITE_BUSY errors during concurrent access.
    await db.execute("PRAGMA busy_timeout = 5000")
    # WHY: Incremental vacuum reclaims space without full lock.
    await db.execute("PRAGMA auto_vacuum = INCREMENTAL")
    # WHY: Foreign keys off for out-of-order spool replay tolerance.
    await db.execute("PRAGMA foreign_keys = OFF")

    # Enable row factory for dict-like access
    db.row_factory = aiosqlite.Row

    return db


async def apply_schema(db: aiosqlite.Connection) -> None:
    """
    Apply the schema DDL idempotently.

    All CREATE statements use IF NOT EXISTS, so this is safe to call
    on every daemon startup.
    """
    schema_sql = _SCHEMA_PATH.read_text()

    # WHY: Split on semicolons and execute individually because
    # aiosqlite.executescript commits implicitly and we want
    # explicit transaction control.
    statements = [s.strip() for s in schema_sql.split(";") if s.strip()]
    for stmt in statements:
        # Skip PRAGMA statements that were already set in get_connection
        if stmt.upper().startswith("PRAGMA"):
            continue
        try:
            await db.execute(stmt)
        except sqlite3.OperationalError as e:
            # Log but don't crash on benign errors (e.g., index already exists)
            if "already exists" not in str(e):
                logger.warning("Schema statement failed: %s — %s", stmt[:80], e)

    await db.commit()
    logger.info("Schema applied successfully")


async def get_schema_version(db: aiosqlite.Connection) -> int:
    """Return the current schema version, or 0 if not set."""
    try:
        cursor = await db.execute(
            "SELECT value FROM schema_meta WHERE key = 'version'"
        )
        row = await cursor.fetchone()
        return int(row[0]) if row else 0
    except sqlite3.OperationalError:
        return 0


async def run_incremental_vacuum(db: aiosqlite.Connection, pages: int = 100) -> None:
    """
    Reclaim space from deleted rows without full database lock.

    WHY: Full VACUUM locks the entire database. Incremental vacuum
    frees a bounded number of pages per call.
    """
    await db.execute(f"PRAGMA incremental_vacuum({pages})")
    await db.commit()


def get_sync_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """
    Synchronous SQLite connection for the emit CLI and tests.

    WHY: The emit CLI must be fast and simple — no asyncio overhead.
    """
    path = db_path or DATABASE_PATH
    path.parent.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)

    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.row_factory = sqlite3.Row
    return conn

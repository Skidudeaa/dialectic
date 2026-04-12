"""
SQLite connection factory with WAL mode and pragmas.

WHY: Per-operation connections avoid SQLite's thread-affinity constraint.
asyncio.to_thread() may dispatch each call to a different thread from
the pool, and sqlite3.Connection objects cannot be shared across threads.
Opening a connection per operation is <1ms for SQLite and sidesteps this.
"""

import sqlite3
from pathlib import Path

# WHY: Default path lives alongside the web package in data/, matching
# the existing web/data/ convention. Overridable for tests (:memory:).
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "tradingdesk.db"


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Create a configured SQLite connection.

    WHY pragmas:
      WAL mode: readers never block writers, writers never block readers.
      busy_timeout=5000: wait up to 5s for write lock instead of failing.
      foreign_keys=ON: enforce referential integrity.
      synchronous=NORMAL: safe with WAL — survives process crash. Only loses
        data on OS crash/power loss, same risk as the current fsync+rename.
    """
    path = str(db_path) if db_path else str(DEFAULT_DB_PATH)
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn

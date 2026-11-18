"""Small, local SQLite schema and readiness checks."""

from contextlib import closing
from pathlib import Path
import sqlite3


def initialize(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=2)) as connection:
        with connection:
            connection.execute('CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)')
            connection.execute('INSERT OR IGNORE INTO schema_version VALUES (1)')


def is_ready(path: Path) -> bool:
    try:
        # Read-only probes must never recreate a removed database.
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)) as connection:
            return connection.execute('SELECT version FROM schema_version').fetchall() == [(1,)]
    except sqlite3.Error:
        return False

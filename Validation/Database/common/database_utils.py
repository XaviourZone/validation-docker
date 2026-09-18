"""
common/database_utils.py - SQLite connection helpers for the Validation Database component.

SQLite settings applied on every connection:
    PRAGMA foreign_keys = ON
    PRAGMA journal_mode = WAL
    PRAGMA synchronous = NORMAL
    PRAGMA temp_store = MEMORY
    PRAGMA cache_size = -8000   (8 MB page cache)

WAL mode allows concurrent readers while a writer is active, important for
the Data Parser reading while the PANS importer writes.

No username, password, host or port required - SQLite is file-based.
"""

import sqlite3
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_PRAGMAS = [
    "PRAGMA foreign_keys = ON",
    "PRAGMA journal_mode = WAL",
    "PRAGMA synchronous = NORMAL",
    "PRAGMA temp_store = MEMORY",
    "PRAGMA cache_size = -8000",
]


def open_database(db_path, timeout=30.0):
    """
    Open a SQLite database and apply standard PRAGMAs.

    Parameters
    ----------
    db_path : str or Path
    timeout : float  busy-wait timeout in seconds

    Returns
    -------
    sqlite3.Connection with row_factory = sqlite3.Row
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), timeout=timeout)
    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()
    for pragma in _PRAGMAS:
        cursor.execute(pragma)

    result = cursor.execute("PRAGMA journal_mode").fetchone()
    journal_mode = result[0] if result else "unknown"
    if journal_mode.lower() != "wal":
        log.warning("journal_mode is '%s', not WAL.", journal_mode)

    conn.commit()
    log.debug("Opened database: %s (journal_mode=%s)", db_path, journal_mode)
    return conn


def integrity_check(conn):
    """Run SQLite integrity check. Returns True if result is 'ok'."""
    result = conn.execute("PRAGMA integrity_check").fetchone()
    ok = result and result[0].lower() == "ok"
    if not ok:
        log.error("Integrity check failed: %s", result[0] if result else "no result")
    return bool(ok)


def get_table_row_counts(conn):
    """Return {table_name: row_count} for all non-system tables."""
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    counts = {}
    for (name,) in tables:
        count = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        counts[name] = count
    return counts


def create_import_tracking_tables(conn):
    """
    Create import_batch and import_file tracking tables if they do not exist.
    These tables are local to each database (WRS/PANS/NSC each have their own).
    """
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS import_batch (
            batch_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            source_system    TEXT NOT NULL,
            source_region    TEXT,
            started_at       TEXT NOT NULL,
            completed_at     TEXT,
            status           TEXT NOT NULL DEFAULT 'RUNNING',
            files_discovered INTEGER DEFAULT 0,
            files_loaded     INTEGER DEFAULT 0,
            files_skipped    INTEGER DEFAULT 0,
            rows_loaded      INTEGER DEFAULT 0,
            error_count      INTEGER DEFAULT 0,
            release_name     TEXT,
            remarks          TEXT
        );

        CREATE TABLE IF NOT EXISTS import_file (
            file_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id         INTEGER NOT NULL REFERENCES import_batch(batch_id),
            source_system    TEXT NOT NULL,
            source_region    TEXT,
            file_name        TEXT NOT NULL,
            file_path        TEXT NOT NULL,
            file_hash_sha256 TEXT,
            file_size_bytes  INTEGER,
            target_table     TEXT,
            discovered_at    TEXT,
            loaded_at        TEXT,
            status           TEXT NOT NULL DEFAULT 'PENDING',
            rows_loaded      INTEGER DEFAULT 0,
            error_message    TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_import_file_hash
            ON import_file(file_hash_sha256);

        CREATE INDEX IF NOT EXISTS idx_import_file_batch
            ON import_file(batch_id);
    """)
    conn.commit()

"""Persistent SQLite state store for duplicate prevention and file lifecycle tracking."""

import sqlite3
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional

from ..utils.time import now_iso


class FileState(str, Enum):
    """File processing lifecycle states."""
    DISCOVERED = "DISCOVERED"
    WAITING_FOR_STABILITY = "WAITING_FOR_STABILITY"
    READY = "READY"
    QUEUED = "QUEUED"
    SENDING = "SENDING"
    SENT = "SENT"
    PROCESSED = "PROCESSED"
    RETRYING = "RETRYING"
    FAILED = "FAILED"


@dataclass
class RouterFileState:
    """Represents a persisted file record."""
    source: str
    filename: str
    file_path: str
    file_size: int
    mtime: float
    file_hash: str
    message_id: str
    status: FileState
    attempt_count: int
    first_seen: str
    last_attempt: Optional[str] = None
    acknowledged_at: Optional[str] = None
    destination: Optional[str] = None
    last_error: Optional[str] = None


class FileStateStore:
    """Thread-safe SQLite store for router file operational states."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS file_states (
        source TEXT NOT NULL,
        filename TEXT NOT NULL,
        file_path TEXT NOT NULL,
        file_size INTEGER NOT NULL,
        mtime REAL NOT NULL,
        file_hash TEXT NOT NULL,
        message_id TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL,
        attempt_count INTEGER DEFAULT 0,
        first_seen TEXT NOT NULL,
        last_attempt TEXT,
        acknowledged_at TEXT,
        destination TEXT,
        last_error TEXT,
        PRIMARY KEY (source, filename, file_hash)
    );
    CREATE INDEX IF NOT EXISTS idx_file_states_status ON file_states(status);
    CREATE INDEX IF NOT EXISTS idx_file_states_msg_id ON file_states(message_id);
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                conn.executescript(self.SCHEMA)
                conn.commit()
            finally:
                conn.close()

    def is_already_processed(self, source: str, filename: str, file_hash: str) -> bool:
        """Check if file has already been successfully acknowledged/processed."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    """
                    SELECT status FROM file_states
                    WHERE source = ? AND filename = ? AND file_hash = ?
                    """,
                    (source, filename, file_hash),
                )
                row = cursor.fetchone()
                if not row:
                    return False
                return row["status"] in (FileState.SENT.value, FileState.PROCESSED.value)
            finally:
                conn.close()

    def is_in_flight_or_processed(self, source: str, filename: str, file_hash: str) -> bool:
        """Check if file is already active in queue, in delivery, retrying, or processed."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    """
                    SELECT status FROM file_states
                    WHERE source = ? AND filename = ? AND file_hash = ?
                    """,
                    (source, filename, file_hash),
                )
                row = cursor.fetchone()
                if not row:
                    return False
                return row["status"] in (
                    FileState.READY.value,
                    FileState.QUEUED.value,
                    FileState.SENDING.value,
                    FileState.SENT.value,
                    FileState.PROCESSED.value,
                    FileState.RETRYING.value,
                    FileState.FAILED.value,
                )
            finally:
                conn.close()

    def get_state(self, source: str, filename: str, file_hash: str) -> Optional[RouterFileState]:
        """Fetch file state by primary key."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    """
                    SELECT * FROM file_states
                    WHERE source = ? AND filename = ? AND file_hash = ?
                    """,
                    (source, filename, file_hash),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return self._row_to_state(row)
            finally:
                conn.close()

    def get_by_message_id(self, message_id: str) -> Optional[RouterFileState]:
        """Fetch file state by unique message_id."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT * FROM file_states WHERE message_id = ?",
                    (message_id,)
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return self._row_to_state(row)
            finally:
                conn.close()

    def record_discovered(
        self,
        source: str,
        filename: str,
        file_path: str,
        file_size: int,
        mtime: float,
        file_hash: str,
        message_id: str,
        status: FileState = FileState.DISCOVERED,
    ) -> RouterFileState:
        """Insert or update a newly discovered file."""
        now = now_iso()
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    INSERT INTO file_states (
                        source, filename, file_path, file_size, mtime, file_hash,
                        message_id, status, attempt_count, first_seen
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                    ON CONFLICT(source, filename, file_hash) DO UPDATE SET
                        file_path = excluded.file_path,
                        file_size = excluded.file_size,
                        mtime = excluded.mtime,
                        file_hash = excluded.file_hash,
                        message_id = excluded.message_id,
                        status = excluded.status
                    """,
                    (
                        source, filename, str(file_path), file_size, mtime, file_hash,
                        message_id, status.value, now
                    ),
                )
                conn.commit()
                return RouterFileState(
                    source=source,
                    filename=filename,
                    file_path=str(file_path),
                    file_size=file_size,
                    mtime=mtime,
                    file_hash=file_hash,
                    message_id=message_id,
                    status=status,
                    attempt_count=0,
                    first_seen=now
                )
            finally:
                conn.close()

    def update_status(
        self,
        message_id: str,
        status: FileState,
        error: Optional[str] = None,
        destination: Optional[str] = None,
    ) -> None:
        """Update lifecycle status and optional error/destination."""
        now = now_iso()
        with self._lock:
            conn = self._get_connection()
            try:
                if status in (FileState.SENT, FileState.PROCESSED):
                    conn.execute(
                        """
                        UPDATE file_states
                        SET status = ?, acknowledged_at = ?, last_error = NULL
                        WHERE message_id = ?
                        """,
                        (status.value, now, message_id),
                    )
                elif status == FileState.QUEUED:
                    conn.execute(
                        """
                        UPDATE file_states
                        SET status = ?, destination = ?
                        WHERE message_id = ?
                        """,
                        (status.value, destination, message_id),
                    )
                elif status in (FileState.RETRYING, FileState.FAILED, FileState.DISCOVERED):
                    conn.execute(
                        """
                        UPDATE file_states
                        SET status = ?, last_error = ?, last_attempt = ?
                        WHERE message_id = ?
                        """,
                        (status.value, error, now, message_id),
                    )
                else:
                    conn.execute(
                        "UPDATE file_states SET status = ? WHERE message_id = ?",
                        (status.value, message_id),
                    )
                conn.commit()
            finally:
                conn.close()

    def increment_attempt(self, message_id: str, error: Optional[str] = None) -> int:
        """Increment attempt count and record last attempt timestamp."""
        now = now_iso()
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    UPDATE file_states
                    SET attempt_count = attempt_count + 1,
                        last_attempt = ?,
                        last_error = ?
                    WHERE message_id = ?
                    """,
                    (now, error, message_id),
                )
                conn.commit()
                cursor = conn.execute(
                    "SELECT attempt_count FROM file_states WHERE message_id = ?",
                    (message_id,)
                )
                row = cursor.fetchone()
                return row["attempt_count"] if row else 1
            finally:
                conn.close()

    def get_incomplete_records(self) -> List[RouterFileState]:
        """Fetch records that were interrupted (e.g. QUEUED, SENDING, RETRYING) across restarts."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    """
                    SELECT * FROM file_states
                    WHERE status IN ('READY', 'QUEUED', 'SENDING', 'RETRYING')
                    """
                )
                return [self._row_to_state(row) for row in cursor.fetchall()]
            finally:
                conn.close()

    def reset_interrupted_states(self) -> int:
        """Reset uncompleted file states from previous crash/restart to DISCOVERED so they can resume."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    """
                    UPDATE file_states
                    SET status = 'DISCOVERED'
                    WHERE status IN ('READY', 'QUEUED', 'SENDING', 'RETRYING')
                    """
                )
                conn.commit()
                return cursor.rowcount
            finally:
                conn.close()

    def get_stats(self) -> dict:
        """Return counts grouped by status."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT status, COUNT(*) as count FROM file_states GROUP BY status"
                )
                counts = {row["status"]: row["count"] for row in cursor.fetchall()}
                return counts
            finally:
                conn.close()

    def _row_to_state(self, row: sqlite3.Row) -> RouterFileState:
        return RouterFileState(
            source=row["source"],
            filename=row["filename"],
            file_path=row["file_path"],
            file_size=row["file_size"],
            mtime=row["mtime"],
            file_hash=row["file_hash"],
            message_id=row["message_id"],
            status=FileState(row["status"]),
            attempt_count=row["attempt_count"],
            first_seen=row["first_seen"],
            last_attempt=row["last_attempt"],
            acknowledged_at=row["acknowledged_at"],
            destination=row["destination"],
            last_error=row["last_error"],
        )

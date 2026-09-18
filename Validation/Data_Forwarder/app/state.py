import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


class DeliveryState:
    """Persistent delivery state; safe for service restart."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS deliveries (
                    output_id TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    state TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    delivered_at TEXT,
                    PRIMARY KEY(output_id, destination)
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_delivery_state ON deliveries(state)")

    def _connect(self):
        return sqlite3.connect(str(self.path), timeout=30)

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    def get(self, output_id, destination):
        with self._lock, self._connect() as db:
            row = db.execute("SELECT output_id,destination,sha256,filename,state,attempts,last_error FROM deliveries WHERE output_id=? AND destination=?", (output_id, destination)).fetchone()
        if not row:
            return None
        return dict(zip(("output_id","destination","sha256","filename","state","attempts","last_error"), row))

    def ensure(self, output_id, destination, sha256, filename):
        now = self._now()
        with self._lock, self._connect() as db:
            db.execute("""
                INSERT INTO deliveries(output_id,destination,sha256,filename,state,attempts,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(output_id,destination) DO UPDATE SET sha256=excluded.sha256, filename=excluded.filename, updated_at=excluded.updated_at
            """, (output_id, destination, sha256, filename, "PENDING", 0, now, now))

    def mark(self, output_id, destination, state, attempts=None, error=None):
        now = self._now()
        with self._lock, self._connect() as db:
            if state == "DELIVERED":
                db.execute("UPDATE deliveries SET state=?,attempts=COALESCE(?,attempts),last_error=NULL,updated_at=?,delivered_at=? WHERE output_id=? AND destination=?", (state, attempts, now, now, output_id, destination))
            else:
                db.execute("UPDATE deliveries SET state=?,attempts=COALESCE(?,attempts),last_error=?,updated_at=? WHERE output_id=? AND destination=?", (state, attempts, error, now, output_id, destination))

    def counts(self):
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT state,COUNT(*) FROM deliveries GROUP BY state").fetchall()
        return {state: count for state, count in rows}

    def recent(self, limit=20):
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT output_id,destination,filename,state,attempts,last_error,updated_at FROM deliveries ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        keys = ("output_id","destination","filename","state","attempts","last_error","updated_at")
        return [dict(zip(keys, row)) for row in rows]

"""Persistent AIS message and per-MMSI vessel state.

Keeps latest valid static/voyage/kinematic fields and a bounded message history.
Position history metadata is kept separately from last-message timestamp so a
Type 5/static message cannot corrupt the time interval used for movement checks.
"""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

AIS_STATE_FIELDS = (
    "imo", "vessel_name", "callsign", "vessel_type", "length", "width",
    "draught", "destination", "eta", "nav_status", "rot", "sog", "cog",
    "true_heading", "latitude", "longitude",
)


def _default_path() -> Path:
    cur = Path(__file__).resolve()
    for parent in [cur, *cur.parents]:
        candidate = parent / "Validation" / "state" / "ais_state.db"
        if candidate.parent.exists():
            return candidate
    return Path("Validation/state/ais_state.db").resolve()


class AISStateDB:
    """SQLite-backed AIS state cache, keyed by MMSI."""

    def __init__(self, db_path: Optional[Path] = None, history_limit: int = 100):
        self.path = Path(db_path or _default_path())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.history_limit = max(10, int(history_limit))
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS ais_vessel_state (
                mmsi INTEGER PRIMARY KEY,
                state_json TEXT NOT NULL,
                last_message_type INTEGER,
                last_timestamp TEXT,
                last_source TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ais_message_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mmsi INTEGER NOT NULL,
                message_type INTEGER NOT NULL,
                timestamp TEXT,
                source TEXT,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ais_message_mmsi_type
                ON ais_message_state(mmsi, message_type, id DESC);
        """)
        self._conn.commit()

    def merge_record(self, record: Any) -> Any:
        mmsi = getattr(record, "mmsi", None)
        if not mmsi or not (100000000 <= int(mmsi) <= 999999999):
            return record
        mmsi = int(mmsi)
        msg_type = getattr(record, "app_message_id", None)
        now = datetime.now(timezone.utc).isoformat()
        incoming = {}
        for field in AIS_STATE_FIELDS:
            value = getattr(record, field, None)
            if value is not None and value != "":
                incoming[field] = value

        with self._lock:
            row = self._conn.execute(
                "SELECT state_json FROM ais_vessel_state WHERE mmsi=?", (mmsi,)
            ).fetchone()
            state: Dict[str, Any] = json.loads(row["state_json"]) if row else {}

            # Preserve the previous valid position independently of last message time.
            if incoming.get("latitude") is not None and incoming.get("longitude") is not None:
                state["last_position_latitude"] = incoming["latitude"]
                state["last_position_longitude"] = incoming["longitude"]
                state["last_position_timestamp"] = getattr(record, "timestamp", None)
                state["last_position_source"] = getattr(record, "source", None)

            state.update(incoming)
            if msg_type is not None:
                state["last_message_type"] = int(msg_type)
            state["last_timestamp"] = getattr(record, "timestamp", None)
            state["last_source"] = getattr(record, "source", None)

            self._conn.execute(
                """INSERT INTO ais_vessel_state
                   (mmsi,state_json,last_message_type,last_timestamp,last_source,updated_at)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(mmsi) DO UPDATE SET
                     state_json=excluded.state_json,
                     last_message_type=excluded.last_message_type,
                     last_timestamp=excluded.last_timestamp,
                     last_source=excluded.last_source,
                     updated_at=excluded.updated_at""",
                (mmsi, json.dumps(state, ensure_ascii=False), msg_type,
                 getattr(record, "timestamp", None), getattr(record, "source", None), now),
            )
            if msg_type is not None:
                self._conn.execute(
                    "INSERT INTO ais_message_state(mmsi,message_type,timestamp,source,payload_json,updated_at) VALUES (?,?,?,?,?,?)",
                    (mmsi, int(msg_type), getattr(record, "timestamp", None),
                     getattr(record, "source", None), json.dumps(incoming, ensure_ascii=False), now),
                )
                self._conn.execute(
                    """DELETE FROM ais_message_state WHERE mmsi=? AND id NOT IN
                       (SELECT id FROM ais_message_state WHERE mmsi=? ORDER BY id DESC LIMIT ?)""",
                    (mmsi, mmsi, self.history_limit),
                )
            self._conn.commit()

        for field in AIS_STATE_FIELDS:
            if getattr(record, field, None) in (None, "") and field in state:
                try:
                    setattr(record, field, state[field])
                except Exception:
                    pass
        return record

    def get(self, mmsi: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM ais_vessel_state WHERE mmsi=?", (int(mmsi),)).fetchone()
        if not row:
            return None
        data = json.loads(row["state_json"])
        data.update({"mmsi": int(row["mmsi"]), "last_message_type": row["last_message_type"],
                     "last_timestamp": row["last_timestamp"], "last_source": row["last_source"],
                     "updated_at": row["updated_at"]})
        return data

    def recent_messages(self, mmsi: int, limit: int = 20):
        with self._lock:
            rows = self._conn.execute(
                "SELECT mmsi,message_type,timestamp,source,payload_json,updated_at FROM ais_message_state WHERE mmsi=? ORDER BY id DESC LIMIT ?",
                (int(mmsi), int(limit)),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            result.append(item)
        return result

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass

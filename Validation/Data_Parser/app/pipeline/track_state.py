"""
Track-state database.

Maintains ONE record per MMSI (updated in-place on every transmission).
Does NOT accumulate history.

Active rule: track.flag.active = (last_tx_age_seconds < 3 * 3600)
"""

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("parser.trackstate")

ACTIVE_THRESHOLD_SECONDS = 3 * 3600  # 3 hours


def _find_default_state_db() -> Path:
    cur = Path(__file__).resolve()
    for parent in [cur, *cur.parents]:
        cand = parent / "Validation" / "state" / "track_state.db"
        if cand.parent.exists():
            return cand
    return Path("Validation/state/track_state.db").resolve()


class TrackStateDB:
    """SQLite-backed track state store (one record per MMSI)."""

    CREATE_SQL = """
    CREATE TABLE IF NOT EXISTS track_state (
        mmsi            INTEGER PRIMARY KEY,
        imo             INTEGER,
        vessel_name     TEXT,
        last_latitude   REAL,
        last_longitude  REAL,
        last_tx_iso     TEXT,
        last_tx_epoch_s INTEGER,
        source          TEXT,
        updated_at      TEXT
    );
    """

    def __init__(self, db_path: Optional[Path] = None):
        target_path = db_path or _find_default_state_db()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(target_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._conn.execute(self.CREATE_SQL)
        self._conn.commit()
        log.info(f"TrackStateDB initialised at {target_path}")

    def upsert(
        self,
        mmsi: int,
        imo: Optional[int],
        vessel_name: Optional[str],
        latitude: Optional[float],
        longitude: Optional[float],
        tx_timestamp_iso: Optional[str],
        source: str,
    ) -> bool:
        """
        Insert or update the track state for this MMSI.
        Returns True if this is an active track (last tx < 3 hours ago).
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        epoch_s = None
        if tx_timestamp_iso:
            try:
                epoch_s = _iso_to_epoch_s(tx_timestamp_iso)
            except Exception:
                epoch_s = None

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO track_state
                    (mmsi, imo, vessel_name, last_latitude, last_longitude,
                     last_tx_iso, last_tx_epoch_s, source, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mmsi) DO UPDATE SET
                    imo            = COALESCE(excluded.imo, imo),
                    vessel_name    = COALESCE(excluded.vessel_name, vessel_name),
                    last_latitude  = COALESCE(excluded.last_latitude, last_latitude),
                    last_longitude = COALESCE(excluded.last_longitude, last_longitude),
                    last_tx_iso    = excluded.last_tx_iso,
                    last_tx_epoch_s= excluded.last_tx_epoch_s,
                    source         = excluded.source,
                    updated_at     = excluded.updated_at
                """,
                (mmsi, imo, vessel_name, latitude, longitude,
                 str(tx_timestamp_iso or now_iso), epoch_s, source, now_iso),
            )
            self._conn.commit()

        # Determine active flag from the (possibly just-written) epoch
        if epoch_s is None:
            return True  # assume active if we can't parse the timestamp
        now_s = int(datetime.now(timezone.utc).timestamp())
        return (now_s - epoch_s) < ACTIVE_THRESHOLD_SECONDS

    def is_active(self, mmsi: int) -> bool:
        """Check the active flag for an MMSI without updating."""
        with self._lock:
            row = self._conn.execute(
                "SELECT last_tx_epoch_s FROM track_state WHERE mmsi=? LIMIT 1", (mmsi,)
            ).fetchone()
        if row is None or row["last_tx_epoch_s"] is None:
            return False
        now_s = int(datetime.now(timezone.utc).timestamp())
        return (now_s - row["last_tx_epoch_s"]) < ACTIVE_THRESHOLD_SECONDS

    def get_track(self, mmsi: int) -> Optional[dict]:
        """Fetch current state for an MMSI."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM track_state WHERE mmsi=? LIMIT 1", (mmsi,)
            ).fetchone()
        return dict(row) if row else None

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass


def _iso_to_epoch_s(val: Any) -> int:
    if val is None:
        raise ValueError("Timestamp is None")
    if isinstance(val, (int, float)):
        ival = int(val)
        return ival // 1000 if ival >= 100_000_000_000 else ival

    val_str = str(val).strip()
    if not val_str:
        raise ValueError("Empty timestamp string")

    # If numeric string
    try:
        fval = float(val_str)
        ival = int(fval)
        return ival // 1000 if ival >= 100_000_000_000 else ival
    except (ValueError, TypeError):
        pass

    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
    ):
        try:
            iso_clean = val_str.replace("Z", "+00:00")
            from datetime import datetime, timezone
            dt = datetime.strptime(iso_clean, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            continue
    raise ValueError(f"Cannot parse timestamp: {val!r}")


"""
Track-state database.

Maintains ONE operational track record per MMSI (updated in-place on every transmission).
Also maintains ONE cumulative last-known reference record per MMSI. The reference record
is updated on every transaction and is used only when the current transaction and
WRS/PANS/NSC cannot supply a value.

Active rule: track.flag.active = (last_tx_age_seconds < 3 * 3600)
"""

import json
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


# Fields used for cumulative last-known MMSI fallback. Dynamic position,
# kinematic and timestamp fields are deliberately excluded so stale movement
# data is never silently carried into a later transaction.
MMSI_REFERENCE_FIELDS = (
    "ais.lenToBow", "ais.lenToStern", "ais.navStatus", "ais.typeAndCargo",
    "ais.widthToPort", "ais.widthToStarboard", "cat.annotation", "cat.category",
    "cat.identity", "foreign.track.number", "id.callsign", "id.imo", "id.mmsi",
    "id.mmsi.destination", "vessel.beam", "vessel.description", "vessel.draft",
    "vessel.grosstonnage", "vessel.length", "vessel.name",
    "voyage.arrival", "voyage.departure", "voyage.destination", "voyage.eta",
    "voyage.etd", "voyage.origin",
)


class TrackStateDB:
    """SQLite-backed operational track state plus one cumulative MMSI reference per vessel."""

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
        self._conn.execute(self.CREATE_REFERENCE_SQL)
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
        reference_values: Optional[dict[str, Any]] = None,
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

            # Merge non-empty current values into the unique MMSI reference.
            # Existing values are retained when the current transaction is blank.
            if reference_values:
                clean = {
                    key: value for key, value in reference_values.items()
                    if key in MMSI_REFERENCE_FIELDS and value not in (None, "")
                }
                if clean:
                    row = self._conn.execute(
                        "SELECT values_json FROM mmsi_reference WHERE mmsi=? LIMIT 1",
                        (mmsi,),
                    ).fetchone()
                    merged = {}
                    if row and row["values_json"]:
                        try:
                            merged = json.loads(row["values_json"]) or {}
                        except (TypeError, ValueError):
                            log.warning("Invalid MMSI reference JSON for MMSI=%s; rebuilding", mmsi)
                    merged.update(clean)
                    self._conn.execute(
                        """
                        INSERT INTO mmsi_reference
                            (mmsi, values_json, last_tx_iso, last_source, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(mmsi) DO UPDATE SET
                            values_json = excluded.values_json,
                            last_tx_iso = excluded.last_tx_iso,
                            last_source = excluded.last_source,
                            updated_at  = excluded.updated_at
                        """,
                        (mmsi, json.dumps(merged, ensure_ascii=False, default=str),
                         str(tx_timestamp_iso or now_iso), source, now_iso),
                    )
            self._conn.commit()

        # Determine active flag from the (possibly just-written) epoch
        if epoch_s is None:
            return True  # assume active if we can't parse the timestamp
        now_s = int(datetime.now(timezone.utc).timestamp())
        return (now_s - epoch_s) < ACTIVE_THRESHOLD_SECONDS

    def get_reference(self, mmsi: int) -> dict[str, Any]:
        """Return cumulative last-known reference values for an MMSI."""
        with self._lock:
            row = self._conn.execute(
                "SELECT values_json FROM mmsi_reference WHERE mmsi=? LIMIT 1", (mmsi,)
            ).fetchone()
        if row is None or not row["values_json"]:
            return {}
        try:
            values = json.loads(row["values_json"])
            return values if isinstance(values, dict) else {}
        except (TypeError, ValueError):
            log.warning("Invalid MMSI reference JSON for MMSI=%s", mmsi)
            return {}

    def reference_count(self) -> int:
        """Return the number of unique MMSI reference records."""
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM mmsi_reference").fetchone()
        return int(row["n"]) if row else 0

    def get_reference_metadata(self, mmsi: int) -> Optional[dict]:
        """Return reference metadata without exposing internal SQLite rows."""
        with self._lock:
            row = self._conn.execute(
                "SELECT mmsi, last_tx_iso, last_source, updated_at FROM mmsi_reference WHERE mmsi=? LIMIT 1",
                (mmsi,),
            ).fetchone()
        return dict(row) if row else None

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


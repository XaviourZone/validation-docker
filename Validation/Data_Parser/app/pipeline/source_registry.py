"""
Source-to-source-ID mapping registry backed by a small SQLite table.
All source IDs are resolved here; parsers never hard-code numeric IDs.
"""

import math
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, Optional


# Canonical source ID constants (as defined by the downstream consumer)
SOURCE_ID_MAP: Dict[str, int] = {
    "NONE":    0,
    "NAIS":   37,
    "SAIS":   38,
    "LRIT":   40,
    "SAC":    41,
    "VATMSW": 223,
    "VATMSE": 245,
    "MSIS":   250,
}

# Port → source name mapping (port 10004 carries BOTH VATMS sources;
# the actual source is determined from source field in the envelope)
PORT_SOURCE_MAP: Dict[int, str] = {
    10001: "SAIS",
    10002: "MSIS",
    10003: "LRIT",
    10004: "VATMS",   # resolved to VATMSE/VATMSW per envelope.source
    10005: "NAIS",
}

# Envelope source-name → numeric source ID
ENVELOPE_SOURCE_TO_ID: Dict[str, int] = {
    "SAIS_IOR":    SOURCE_ID_MAP["SAIS"],
    "SAIS_GLOBAL": SOURCE_ID_MAP["SAIS"],
    "MSIS":        SOURCE_ID_MAP["MSIS"],
    "LRIT":        SOURCE_ID_MAP["LRIT"],
    "VATMS_EAST":  SOURCE_ID_MAP["VATMSE"],
    "VATMS_WEST":  SOURCE_ID_MAP["VATMSW"],
    "NAIS":        SOURCE_ID_MAP["NAIS"],
}

# Envelope source-name → human label for remarks
ENVELOPE_SOURCE_TO_LABEL: Dict[str, str] = {
    "SAIS_IOR":    "IMAC SAIS",
    "SAIS_GLOBAL": "IMAC SAIS",
    "MSIS":        "IMAC MSIS",
    "LRIT":        "IMAC LRIT",
    "VATMS_EAST":  "IMAC VATMSE",
    "VATMS_WEST":  "IMAC VATMSW",
    "NAIS":        "IMAC NAIS",
}


def get_source_id(source_name: str) -> int:
    """Return numeric source ID for a given envelope source name."""
    return ENVELOPE_SOURCE_TO_ID.get(source_name, SOURCE_ID_MAP["NONE"])


def get_source_label(source_name: str) -> str:
    """Return human-readable source label for remarks."""
    return ENVELOPE_SOURCE_TO_LABEL.get(source_name, f"UNKNOWN({source_name})")


# ──────────────────────────────────────────────────────────────────────────────
# Conversion helpers matching the downstream XML parser contract exactly
# ──────────────────────────────────────────────────────────────────────────────

DEG_TO_RAD = math.pi / 180.0


def deg_to_rad(degrees: float) -> float:
    """Convert decimal degrees to radians (for lat/lon, COG, heading)."""
    return degrees * DEG_TO_RAD


def knots_to_ms(knots: float) -> float:
    """
    Convert knots to m/s.

    The downstream consumer does:
        int(float(value) / 0.001)
    which scales m/s to integer tenths-of-mm/s.
    We must supply m/s so the consumer gets the correct integer.
    1 knot = 0.514444 m/s
    """
    return knots * 0.514444


def iso_to_epoch_ms(val: Any) -> Optional[int]:
    """
    Parse an ISO-8601 UTC timestamp string or epoch integer/float and return epoch milliseconds.
    The downstream consumer calls timestamp_ms(value) which expects an integer
    epoch-millisecond value.
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        ival = int(val)
        return ival if ival >= 100_000_000_000 else ival * 1000

    val_str = str(val).strip()
    if not val_str or val_str.lower() in ("none", "null", ""):
        return None

    # Handle direct numeric epoch strings (e.g. "1789127933000" or "1789127933")
    try:
        fval = float(val_str)
        ival = int(fval)
        return ival if ival >= 100_000_000_000 else ival * 1000
    except (ValueError, TypeError):
        pass

    from datetime import datetime, timezone
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
            dt = datetime.strptime(val_str.replace("Z", "+00:00"), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    return None


def is_valid_mmsi(mmsi: Any) -> bool:
    """A valid MMSI is a 9-digit positive integer."""
    if mmsi is None:
        return False
    try:
        val = int(mmsi)
        return 100_000_000 <= val <= 999_999_999
    except (ValueError, TypeError):
        return False


def is_valid_imo(imo: Any) -> bool:
    """A valid IMO is a 7-digit positive integer."""
    if imo is None:
        return False
    try:
        val = int(imo)
        return 1_000_000 <= val <= 9_999_999
    except (ValueError, TypeError):
        return False


def sanitize_string(s: Optional[str]) -> str:
    """
    Remove characters that would break XML well-formedness.
    The downstream consumer passes these through sanitize_string().
    """
    if not s:
        return ""
    # Strip null bytes and XML-invalid control chars (keep tabs, newlines if needed)
    result = "".join(c for c in str(s) if ord(c) >= 0x20 or c in "\t\n\r")
    return result.strip()


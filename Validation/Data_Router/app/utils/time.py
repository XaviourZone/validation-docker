"""Time utility helpers for timestamps and ISO-8601 formatting."""

from datetime import datetime, timezone


def now_utc() -> datetime:
    """Return current datetime with UTC timezone."""
    return datetime.now(timezone.utc)


def now_iso() -> str:
    """Return current UTC timestamp formatted as ISO-8601 string."""
    return now_utc().isoformat()


def to_iso(dt: datetime) -> str:
    """Convert a datetime to ISO-8601 string in UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()


def epoch_to_iso(timestamp: float) -> str:
    """Convert Unix epoch timestamp float to ISO-8601 string."""
    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    return dt.isoformat()

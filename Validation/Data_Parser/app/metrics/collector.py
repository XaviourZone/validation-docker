"""Thread-safe metrics collector for Data Parser service."""

from datetime import datetime, timezone
import threading
import time
from typing import Any, Dict, Optional


class ParserMetricsCollector:
    """Tracks operational parsing metrics and source distribution."""

    def __init__(self):
        self._lock = threading.Lock()
        self._start_time = time.time()
        self._messages_received = 0
        self._messages_parsed = 0
        self._messages_rejected = 0
        self._total_records = 0
        self._parse_errors = 0
        self._last_processed_at: Optional[str] = None
        self._last_error: Optional[str] = None
        self._source_counts: Dict[str, int] = {}
        self._source_records: Dict[str, int] = {}

    def record_parse_result(self, source: str, records_parsed: int, records_rejected: int, errors: list):
        with self._lock:
            self._messages_received += 1
            if records_parsed > 0 or (records_rejected == 0 and not errors):
                self._messages_parsed += 1
            else:
                self._messages_rejected += 1

            self._total_records += records_parsed
            self._parse_errors += len(errors)
            if errors:
                self._last_error = errors[-1]

            self._last_processed_at = datetime.now(timezone.utc).isoformat()
            self._source_counts[source] = self._source_counts.get(source, 0) + 1
            self._source_records[source] = self._source_records.get(source, 0) + records_parsed

    def get_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            uptime = max(0.1, time.time() - self._start_time)
            rate = round(self._total_records / uptime, 2)
            return {
                "uptime_seconds": round(uptime, 1),
                "messages_received": self._messages_received,
                "messages_parsed": self._messages_parsed,
                "messages_rejected": self._messages_rejected,
                "total_records_produced": self._total_records,
                "parse_errors": self._parse_errors,
                "processing_rate_records_sec": rate,
                "last_processed_at": self._last_processed_at,
                "last_error": self._last_error,
                "source_distribution": dict(self._source_counts),
                "records_by_source": dict(self._source_records),
            }

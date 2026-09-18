"""Operational metrics collection for Data Router."""

import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, Optional

from ..utils.time import now_iso


@dataclass
class SourceMetrics:
    """Operational metrics tracked for a single input source."""
    source_name: str
    enabled: bool = True
    running: bool = False
    connected: bool = False
    files_discovered: int = 0
    files_processed: int = 0
    files_failed: int = 0
    messages_received: int = 0
    messages_routed: int = 0
    messages_acknowledged: int = 0
    messages_failed: int = 0
    retry_count: int = 0
    last_received_at: Optional[str] = None
    last_delivery_at: Optional[str] = None
    last_error: Optional[str] = None


class MetricsCollector:
    """Thread-safe collector for router-wide and per-source operational statistics."""

    def __init__(self):
        self._lock = threading.Lock()
        self._sources: Dict[str, SourceMetrics] = {}
        self._start_time = time.time()

    def _get_or_create_locked(self, source_name: str) -> SourceMetrics:
        if source_name not in self._sources:
            self._sources[source_name] = SourceMetrics(source_name=source_name)
        return self._sources[source_name]

    def register_source(self, source_name: str, enabled: bool = True) -> None:
        """Register a source in the metrics registry."""
        with self._lock:
            if source_name not in self._sources:
                self._sources[source_name] = SourceMetrics(source_name=source_name, enabled=enabled)

    def set_source_state(self, source_name: str, running: Optional[bool] = None, connected: Optional[bool] = None) -> None:
        """Update active/connected state of a source."""
        with self._lock:
            sm = self._get_or_create_locked(source_name)
            if running is not None:
                sm.running = running
            if connected is not None:
                sm.connected = connected

    def record_discovered(self, source_name: str) -> None:
        with self._lock:
            sm = self._get_or_create_locked(source_name)
            sm.files_discovered += 1

    def record_received(self, source_name: str) -> None:
        with self._lock:
            sm = self._get_or_create_locked(source_name)
            sm.messages_received += 1
            sm.last_received_at = now_iso()

    def record_routed(self, source_name: str) -> None:
        with self._lock:
            sm = self._get_or_create_locked(source_name)
            sm.messages_routed += 1

    def record_acknowledged(self, source_name: str, is_file: bool = False) -> None:
        with self._lock:
            sm = self._get_or_create_locked(source_name)
            sm.messages_acknowledged += 1
            sm.last_delivery_at = now_iso()
            if is_file:
                sm.files_processed += 1

    def record_retry(self, source_name: str) -> None:
        with self._lock:
            sm = self._get_or_create_locked(source_name)
            sm.retry_count += 1

    def record_failed(self, source_name: str, is_file: bool = False, error: Optional[str] = None) -> None:
        with self._lock:
            sm = self._get_or_create_locked(source_name)
            sm.messages_failed += 1
            sm.last_error = error
            if is_file:
                sm.files_failed += 1

    def record_error(self, source_name: str, error: str) -> None:
        with self._lock:
            sm = self._get_or_create_locked(source_name)
            sm.last_error = error

    def snapshot(self) -> dict:
        """Return a complete dictionary snapshot of all metrics."""
        with self._lock:
            uptime = time.time() - self._start_time
            total_received = sum(s.messages_received for s in self._sources.values())
            total_acked = sum(s.messages_acknowledged for s in self._sources.values())
            total_failed = sum(s.messages_failed for s in self._sources.values())

            return {
                "uptime_seconds": round(uptime, 2),
                "totals": {
                    "received": total_received,
                    "acknowledged": total_acked,
                    "failed": total_failed,
                    "throughput_msg_per_sec": round(total_acked / max(1.0, uptime), 2),
                },
                "sources": {name: asdict(sm) for name, sm in self._sources.items()}
            }

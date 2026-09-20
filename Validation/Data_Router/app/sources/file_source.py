"""File and folder input manager with stability detection and duplicate suppression."""

import fnmatch
import logging
import os
from pathlib import Path
import threading
from typing import Dict, Optional, Set, Tuple

from .base_source import BaseSource
from ..config.models import FileSourceConfig
from ..logging.logger import log_event
from ..monitoring.metrics import MetricsCollector
from ..queue.item import RoutingEnvelope
from ..reliability.state import FileState, FileStateStore
from ..routing.router import RoutingEngine
from ..utils.filesystem import FileSnapshot, is_file_stable
from ..utils.hashing import compute_file_hash, generate_file_message_id
from ..utils.time import now_iso


class FileSourceManager(BaseSource):
    """Monitors a source directory for incoming files, confirms stability, and routes envelopes."""

    def __init__(
        self,
        config: FileSourceConfig,
        base_inflow_dir: Path,
        routing_engine: RoutingEngine,
        state_store: Optional[FileStateStore] = None,
        metrics_collector: Optional[MetricsCollector] = None,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(config, logger)
        self.file_config = config
        self.routing_engine = routing_engine
        self.state_store = state_store
        self.metrics_collector = metrics_collector

        raw_folder = Path(config.folder)
        if raw_folder.is_absolute():
            host_mount = os.environ.get("VALIDATION_HOST_FILESYSTEM_ROOT", "").strip()
            if host_mount:
                self.folder_path = Path(host_mount) / str(raw_folder).lstrip("/\\")
            else:
                self.folder_path = raw_folder
        else:
            self.folder_path = base_inflow_dir / raw_folder

        self._running = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._stability_snapshots: Dict[Path, FileSnapshot] = {}
        self._in_flight_files: Set[Tuple[str, str]] = set()

    def is_running(self) -> bool:
        return self._running

    def is_connected(self) -> bool:
        return self.folder_path.exists() and os.access(self.folder_path, os.R_OK)

    def start(self) -> None:
        """Start the file monitoring poller thread."""
        if self._running:
            return

        self.folder_path.mkdir(parents=True, exist_ok=True)
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._scan_loop,
            name=f"FilePoller-{self.name}",
            daemon=True,
        )
        self._thread.start()
        if self.metrics_collector:
            self.metrics_collector.set_source_state(
                self.name, running=True, connected=self.is_connected()
            )

        self.logger.info(
            f"File source '{self.name}' monitoring started on {self.folder_path.resolve()}"
        )

    def stop(self) -> None:
        """Stop file monitoring gracefully."""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None
        if self.metrics_collector:
            self.metrics_collector.set_source_state(self.name, running=False)

        self.logger.info(f"File source '{self.name}' monitoring stopped")

    def _scan_loop(self) -> None:
        """Continuous directory scanning loop."""
        poll_interval = self.file_config.poll_interval_seconds

        while not self._stop_event.is_set():
            try:
                if self.is_connected():
                    self._scan_directory()
                else:
                    self.logger.warning(
                        f"File source '{self.name}' directory is inaccessible: {self.folder_path}"
                    )
                    if self.metrics_collector:
                        self.metrics_collector.set_source_state(self.name, connected=False)
            except Exception as e:
                self.logger.exception(f"Error scanning folder for source '{self.name}': {e}")
                if self.metrics_collector:
                    self.metrics_collector.record_error(self.name, str(e))

            self._stop_event.wait(timeout=poll_interval)

    def _scan_directory(self) -> None:
        """Inspect directory for files matching configured patterns."""
        current_files: Set[Path] = set()

        try:
            entries = os.scandir(self.folder_path)
        except OSError as e:
            self.logger.error(f"Failed to list directory {self.folder_path}: {e}")
            return

        with entries:
            for entry in entries:
                if not entry.is_file():
                    continue

                path = Path(entry.path)
                filename = entry.name

                if not any(
                    fnmatch.fnmatch(filename, pat)
                    for pat in self.file_config.file_patterns
                ):
                    continue

                current_files.add(path)
                self._process_candidate_file(path)

        for tracked_path in list(self._stability_snapshots.keys()):
            if tracked_path not in current_files:
                del self._stability_snapshots[tracked_path]

    def _process_candidate_file(self, file_path: Path) -> None:
        """Evaluate file stability and route if ready and not duplicated."""
        prev_snapshot = self._stability_snapshots.get(file_path)
        stable, curr_snapshot = is_file_stable(
            file_path=file_path,
            previous_snapshot=prev_snapshot,
            min_stability_seconds=self.file_config.stability_window_seconds,
        )

        if curr_snapshot:
            self._stability_snapshots[file_path] = curr_snapshot

        if not stable:
            if prev_snapshot is None:
                log_event(
                    self.logger,
                    logging.INFO,
                    event="file_detected",
                    source=self.name,
                    filename=file_path.name,
                )
                if self.metrics_collector:
                    self.metrics_collector.record_discovered(self.name)
            return

        try:
            file_size = curr_snapshot.size
            mtime = curr_snapshot.mtime
            file_hash = compute_file_hash(file_path)
        except Exception as e:
            self.logger.warning(f"Failed to read/hash file {file_path}: {e}")
            return

        file_key = (file_path.name, file_hash)

        if file_key in self._in_flight_files:
            return

        if (
            self.state_store
            and self.state_store.is_in_flight_or_processed(
                self.name, file_path.name, file_hash
            )
        ):
            log_event(
                self.logger,
                logging.DEBUG,
                event="file_skipped_duplicate",
                source=self.name,
                filename=file_path.name,
                hash=file_hash[:12],
            )
            return

        self._in_flight_files.add(file_key)

        try:
            message_id = generate_file_message_id(
                source=self.name,
                filename=file_path.name,
                file_size=file_size,
                mtime=mtime,
                file_hash=file_hash,
            )

            if self.state_store:
                self.state_store.record_discovered(
                    source=self.name,
                    filename=file_path.name,
                    file_path=str(file_path.resolve()),
                    file_size=file_size,
                    mtime=mtime,
                    file_hash=file_hash,
                    message_id=message_id,
                    status=FileState.READY,
                )

            try:
                content = self._read_file_content(file_path)
            except Exception as e:
                self.logger.error(f"Failed to read content of file {file_path}: {e}")
                if self.state_store:
                    self.state_store.update_status(
                        message_id, FileState.DISCOVERED, error=str(e)
                    )
                return

            envelope = RoutingEnvelope(
                message_id=message_id,
                source=self.name,
                input_type="FILE",
                received_at=now_iso(),
                payload=content,
                filename=file_path.name,
                file_size=file_size,
                file_hash=file_hash,
            )

            if self.metrics_collector:
                self.metrics_collector.record_received(self.name)

            routed = self.routing_engine.route(envelope)
            if not routed:
                if self.state_store:
                    self.state_store.update_status(
                        message_id,
                        FileState.DISCOVERED,
                        error="Router queue rejected or no route available",
                    )
                log_event(
                    self.logger,
                    logging.WARNING,
                    event="file_route_congested",
                    source=self.name,
                    filename=file_path.name,
                    message_id=message_id,
                )
        finally:
            # Persistent SQLite state is the authoritative lifetime record.
            # This in-memory set only prevents concurrent duplicate submission
            # during the current scan operation and must always be released.
            self._in_flight_files.discard(file_key)

    def _read_file_content(self, file_path: Path) -> str:
        """Safely read text file content, falling back to latin-1 if invalid utf-8."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except UnicodeDecodeError:
            with open(file_path, "r", encoding="latin-1") as f:
                return f.read()

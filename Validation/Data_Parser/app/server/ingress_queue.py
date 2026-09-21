"""Durable parser ingress queue.

The Router receives a file-level ACK as soon as the complete envelope has been
atomically persisted to the parser's local state volume. A background worker
then performs the existing parse -> normalize -> enrich -> XML pipeline.

This removes the dependency between Router ACK timeout and the processing time
of a large MSIS/LRIT/SAIS file while retaining restart recovery.
"""

import hashlib
import json
import logging
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from ..models.common import ParserEnvelope


class DurableIngressQueue:
    """File-backed durable queue for parser envelopes."""

    def __init__(
        self,
        root_dir: Path,
        endpoint_name: str,
        processor: Any,
        parser: Any,
        metrics_collector: Any,
        logger: Optional[logging.Logger] = None,
        poll_interval: float = 0.25,
    ):
        self.root_dir = Path(root_dir) / self._safe_name(endpoint_name)
        self.pending_dir = self.root_dir / "pending"
        self.done_dir = self.root_dir / "done"
        self.failed_dir = self.root_dir / "failed"
        for directory in (self.pending_dir, self.done_dir, self.failed_dir):
            directory.mkdir(parents=True, exist_ok=True)

        self.endpoint_name = endpoint_name
        self.processor = processor
        self.parser = parser
        self.metrics_collector = metrics_collector
        self.logger = logger or logging.getLogger("parser.ingress")
        self.poll_interval = max(0.05, float(poll_interval))

        self._running = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._wake_event = threading.Event()
        self._claim_lock = threading.Lock()

    @staticmethod
    def _safe_name(value: str) -> str:
        return "".join(c if c.isalnum() or c in "._-" else "_" for c in str(value))[:80]

    @staticmethod
    def _message_key(message_id: str) -> str:
        return hashlib.sha256(str(message_id).encode("utf-8")).hexdigest()

    def _path_for(self, directory: Path, message_id: str) -> Path:
        return directory / f"{self._message_key(message_id)}.json"

    def enqueue(self, envelope: ParserEnvelope) -> bool:
        """Durably accept an envelope. Returns False only if it cannot be persisted."""
        pending = self._path_for(self.pending_dir, envelope.message_id)
        done = self._path_for(self.done_dir, envelope.message_id)
        failed = self._path_for(self.failed_dir, envelope.message_id)

        # A duplicate caused by a lost ACK is safe: it must not create a second
        # processing job. A failed job is moved back to pending for another
        # processing attempt when the Router retries the same message.
        if done.exists() or pending.exists():
            self._wake_event.set()
            return True

        if failed.exists():
            try:
                failed.replace(pending)
                self.logger.warning(
                    "Requeued previously failed parser envelope %s", envelope.message_id
                )
                self._wake_event.set()
                return True
            except OSError as exc:
                self.logger.error(
                    "Could not requeue failed parser envelope %s: %s",
                    envelope.message_id,
                    exc,
                )
                return False

        payload = {
            "message_id": envelope.message_id,
            "source": envelope.source,
            "input_type": envelope.input_type,
            "received_at": envelope.received_at,
            "payload": envelope.payload,
            "filename": envelope.filename,
            "file_size": envelope.file_size,
            "file_hash": envelope.file_hash,
            "accepted_at": time.time(),
        }

        temp = pending.with_name(pending.name + ".part")
        try:
            temp.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(temp, pending)
            self.logger.info(
                "Parser ingress accepted source=%s file=%s message_id=%s",
                envelope.source,
                envelope.filename,
                envelope.message_id,
            )
            self._wake_event.set()
            return True
        except Exception as exc:
            try:
                temp.unlink(missing_ok=True)
            except Exception:
                pass
            self.logger.error(
                "Failed to persist parser envelope %s: %s",
                envelope.message_id,
                exc,
            )
            return False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._worker_loop,
            name=f"ParserIngress-{self.endpoint_name}",
            daemon=True,
        )
        self._thread.start()
        self.logger.info(
            "Durable parser ingress started for %s at %s",
            self.endpoint_name,
            self.root_dir,
        )

    def stop(self, timeout: float = 5.0) -> None:
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        self._wake_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=max(0.1, timeout))
        self._thread = None

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            processed = self._process_one_pending()
            if not processed:
                self._wake_event.wait(self.poll_interval)
                self._wake_event.clear()

    def _process_one_pending(self) -> bool:
        with self._claim_lock:
            files = sorted(self.pending_dir.glob("*.json"))
            if not files:
                return False
            path = files[0]

            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                envelope = ParserEnvelope.from_dict(data)
            except Exception as exc:
                self.logger.error(
                    "Invalid durable parser envelope %s: %s", path.name, exc
                )
                self._move_to_failed(path, reason=f"invalid envelope: {exc}")
                return True

        started = time.monotonic()
        try:
            result, _generated_xml = self.processor.process_envelope(
                envelope=envelope,
                fallback_source_parser=self.parser,
            )

            self.metrics_collector.record_parse_result(
                source=envelope.source,
                records_parsed=result.records_parsed,
                records_rejected=result.records_rejected,
                errors=result.errors,
            )

            if result.success:
                self._move_to_done(path)
                self.logger.info(
                    "Parser processing complete source=%s file=%s message_id=%s "
                    "records=%d rejected=%d elapsed=%.2fs",
                    envelope.source,
                    envelope.filename,
                    envelope.message_id,
                    result.records_parsed,
                    result.records_rejected,
                    time.monotonic() - started,
                )
            else:
                self._move_to_failed(
                    path,
                    reason="; ".join(result.errors[:10]) or "parser returned unsuccessful result",
                )
                self.logger.error(
                    "Parser processing failed source=%s file=%s message_id=%s "
                    "elapsed=%.2fs",
                    envelope.source,
                    envelope.filename,
                    envelope.message_id,
                    time.monotonic() - started,
                )
        except Exception as exc:
            self.logger.exception(
                "Unhandled parser processing error source=%s file=%s message_id=%s",
                envelope.source,
                envelope.filename,
                envelope.message_id,
            )
            self._move_to_failed(path, reason=str(exc))

        return True

    def _move_to_done(self, path: Path) -> None:
        target = self.done_dir / path.name
        try:
            path.replace(target)
        except FileNotFoundError:
            pass

    def _move_to_failed(self, path: Path, reason: str) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {"message_id": path.stem}
        data["failure_reason"] = reason
        data["failed_at"] = time.time()
        temp = self.failed_dir / (path.name + ".part")
        target = self.failed_dir / path.name
        try:
            temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(temp, target)
            path.unlink(missing_ok=True)
        except Exception as exc:
            self.logger.error("Failed to persist parser failure state %s: %s", path, exc)
            try:
                temp.unlink(missing_ok=True)
            except Exception:
                pass

    def pending_count(self) -> int:
        return sum(1 for _ in self.pending_dir.glob("*.json"))

    def done_count(self) -> int:
        return sum(1 for _ in self.done_dir.glob("*.json"))

    def failed_count(self) -> int:
        return sum(1 for _ in self.failed_dir.glob("*.json"))

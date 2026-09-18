"""Health evaluation and embedded HTTP monitoring status server."""

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from typing import Any, Dict, Optional

from .metrics import MetricsCollector
from ..config.models import MonitoringConfig
from ..queue.manager import BoundedQueueManager
from ..transport.connection_manager import ParserConnectionManager


class HealthEvaluator:
    """Evaluates the composite operational health of the Data Router Service."""

    def __init__(
        self,
        queue_manager: BoundedQueueManager,
        connection_manager: ParserConnectionManager,
        metrics_collector: MetricsCollector,
    ):
        self.queue_manager = queue_manager
        self.connection_manager = connection_manager
        self.metrics_collector = metrics_collector

    def evaluate(self) -> dict:
        """Produce composite health report."""
        # Queue health
        q_depth = self.queue_manager.depth
        q_capacity = self.queue_manager.max_size
        q_ratio = q_depth / max(1, q_capacity)

        if q_ratio >= 0.95:
            queue_health = "CRITICAL"
        elif q_ratio >= self.queue_manager.config.high_watermark_ratio:
            queue_health = "WARNING"
        else:
            queue_health = "HEALTHY"

        # Destination health
        dest_health = self.connection_manager.get_destination_health()

        # Metrics snapshot
        metrics = self.metrics_collector.snapshot()

        overall = "HEALTHY"
        if queue_health == "CRITICAL":
            overall = "DEGRADED"

        return {
            "service": "validation-data-router",
            "overall_status": overall,
            "queue_health": {
                "status": queue_health,
                "current_depth": q_depth,
                "max_capacity": q_capacity,
                "utilization_pct": round(q_ratio * 100, 1),
            },
            "destinations": dest_health,
            "metrics": metrics,
        }


class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Threaded HTTP server for handling concurrent status inquiries."""
    daemon_threads = True
    allow_reuse_address = True


class _StatusHandler(BaseHTTPRequestHandler):
    """HTTP request handler for /health, /status, and /metrics."""

    evaluator: HealthEvaluator
    logger: logging.Logger

    def do_GET(self) -> None:
        if self.path in ("/health", "/healthz"):
            self._handle_health()
        elif self.path in ("/status", "/"):
            self._handle_status()
        elif self.path == "/metrics":
            self._handle_metrics()
        else:
            self.send_error(404, "Not Found")

    def _handle_health(self) -> None:
        report = self.evaluator.evaluate()
        status_code = 200 if report["overall_status"] == "HEALTHY" else 503
        data = {
            "status": report["overall_status"],
            "queue": report["queue_health"]["status"],
            "uptime_seconds": report["metrics"]["uptime_seconds"],
        }
        self._respond_json(status_code, data)

    def _handle_status(self) -> None:
        report = self.evaluator.evaluate()
        self._respond_json(200, report)

    def _handle_metrics(self) -> None:
        report = self.evaluator.evaluate()
        self._respond_json(200, report["metrics"])

    def _respond_json(self, status_code: int, data: Any) -> None:
        payload = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress verbose default access logging to avoid log pollution
        pass


class MonitoringServer:
    """Embedded HTTP monitoring daemon exposing health and operational status."""

    def __init__(
        self,
        config: MonitoringConfig,
        evaluator: HealthEvaluator,
        logger: Optional[logging.Logger] = None,
    ):
        self.config = config
        self.evaluator = evaluator
        self.logger = logger or logging.getLogger("router")
        self._server: Optional[_ThreadedHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the embedded HTTP status server."""
        if not self.config.enabled:
            return

        host = self.config.http_host
        port = self.config.http_port

        class HandlerWithContext(_StatusHandler):
            evaluator = self.evaluator
            logger = self.logger

        try:
            self._server = _ThreadedHTTPServer((host, port), HandlerWithContext)
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                name="MonitoringHTTPServer",
                daemon=True,
            )
            self._thread.start()
            self.logger.info(f"Monitoring HTTP status server active on http://{host}:{port}/status")
        except Exception as e:
            self.logger.warning(f"Could not bind monitoring HTTP server on {host}:{port}: {e}")

    def stop(self) -> None:
        """Stop the HTTP status server."""
        if self._server:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self._server = None

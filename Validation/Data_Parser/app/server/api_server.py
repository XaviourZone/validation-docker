"""HTTP Status and Metrics API Server for Data Parser service."""

from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from typing import Any, Dict, List, Optional

from ..metrics.collector import ParserMetricsCollector


class ParserAPIHandler(SimpleHTTPRequestHandler):
    """Handles REST endpoints for Data Parser status and telemetry."""

    metrics_collector: ParserMetricsCollector
    endpoint_names: List[str]
    logger: logging.Logger

    def do_GET(self):
        if self.path == "/health":
            metrics = self.metrics_collector.get_snapshot()
            self._json_response({
                "status": "HEALTHY",
                "uptime_seconds": metrics["uptime_seconds"],
                "reachable": True,
            })
            return

        if self.path == "/status":
            metrics = self.metrics_collector.get_snapshot()
            self._json_response({
                "service": "validation-data-parser",
                "overall_status": "OPERATIONAL",
                "reachable": True,
                "endpoints": self.endpoint_names,
                "metrics": metrics,
            })
            return

        if self.path == "/metrics":
            self._json_response(self.metrics_collector.get_snapshot())
            return

        self.send_response(HTTPStatus.NOT_FOUND)
        self.end_headers()

    def _json_response(self, data: Any, status: HTTPStatus = HTTPStatus.OK):
        try:
            payload = json.dumps(data, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass

    def log_message(self, format: str, *args: Any):
        pass


class ParserAPIServer:
    """Manages the lifecycle of the Parser HTTP status server."""

    def __init__(
        self,
        host: str,
        port: int,
        metrics_collector: ParserMetricsCollector,
        endpoint_names: List[str],
        logger: Optional[logging.Logger] = None,
    ):
        self.host = host
        self.port = port
        self.metrics_collector = metrics_collector
        self.endpoint_names = endpoint_names
        self.logger = logger or logging.getLogger("parser")
        self._server: Optional[ThreadingHTTPServer] = None

    def start(self):
        ParserAPIHandler.metrics_collector = self.metrics_collector
        ParserAPIHandler.endpoint_names = self.endpoint_names
        ParserAPIHandler.logger = self.logger

        self._server = ThreadingHTTPServer((self.host, self.port), ParserAPIHandler)
        self.logger.info(f"Data Parser API listening on http://{self.host}:{self.port}")
        self._server.serve_forever()

    def shutdown(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

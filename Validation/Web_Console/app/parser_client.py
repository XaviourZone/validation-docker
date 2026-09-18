"""Client for inspecting and interacting with Data Parser Service."""

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


class ParserClient:
    """Queries Data Parser HTTP status and metrics endpoints."""

    def __init__(self, api_url: str = "http://127.0.0.1:8081", logger: Optional[logging.Logger] = None):
        self.api_url = api_url.rstrip("/")
        self.logger = logger or logging.getLogger("web_console")

    def _http_get(self, endpoint: str, timeout: float = 2.0) -> Optional[dict]:
        url = f"{self.api_url}{endpoint}"
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None
        return None

    def get_health(self) -> Dict[str, Any]:
        data = self._http_get("/health")
        if data:
            return {
                "status": data.get("status", "HEALTHY"),
                "uptime_seconds": data.get("uptime_seconds", 0.0),
                "reachable": True,
            }
        return {
            "status": "OFFLINE",
            "uptime_seconds": 0.0,
            "reachable": False,
        }

    def get_status(self) -> Dict[str, Any]:
        data = self._http_get("/status")
        if data:
            data["reachable"] = True
            return data
        return {
            "service": "validation-data-parser",
            "overall_status": "OFFLINE",
            "reachable": False,
            "endpoints": ["SAIS", "MSIS", "LRIT", "VATMS", "NAIS"],
            "metrics": {
                "uptime_seconds": 0.0,
                "messages_received": 0,
                "messages_parsed": 0,
                "messages_rejected": 0,
                "total_records_produced": 0,
                "parse_errors": 0,
                "processing_rate_records_sec": 0.0,
                "last_processed_at": None,
                "last_error": None,
                "source_distribution": {},
                "records_by_source": {},
            },
        }

    def get_metrics(self) -> Dict[str, Any]:
        data = self._http_get("/metrics")
        if data:
            return data
        return {
            "uptime_seconds": 0.0,
            "messages_received": 0,
            "messages_parsed": 0,
            "messages_rejected": 0,
            "total_records_produced": 0,
            "parse_errors": 0,
            "processing_rate_records_sec": 0.0,
            "last_processed_at": None,
            "last_error": None,
            "source_distribution": {},
            "records_by_source": {},
        }

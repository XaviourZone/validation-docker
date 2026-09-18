"""Client for Data Forwarder telemetry."""

import json
import logging
import urllib.request


class ForwarderClient:
    def __init__(self, api_url="http://127.0.0.1:8082", logger=None):
        self.api_url = api_url.rstrip("/")
        self.logger = logger or logging.getLogger("web_console")

    def _get(self, endpoint):
        try:
            req = urllib.request.Request(f"{self.api_url}{endpoint}", headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=2) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    def get_health(self):
        data = self._get("/health")
        if data:
            return {"status": data.get("status", "READY"), "reachable": True, "running": bool(data.get("running", True))}
        return {"status": "OFFLINE", "reachable": False, "running": False}

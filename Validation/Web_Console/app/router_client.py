"""Client for inspecting and interacting with Data Router Service."""

import json
import logging
import os
import re
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml


class RouterClient:
    """Queries Data Router HTTP status endpoints and operational state."""

    def __init__(
        self,
        api_url: str = "http://127.0.0.1:8080",
        config_path: str = "Validation/Data_Router/config/sources.yaml",
        log_path: str = "Validation/Data_Router/logs/router.log",
        state_db_path: str = "Validation/Data_Router/state/router_state.db",
        workspace_root: Optional[Path] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.api_url = api_url.rstrip("/")
        self.workspace_root = workspace_root or Path.cwd()
        self.config_path = self._resolve_path(config_path)
        self.log_path = self._resolve_path(log_path)
        self.state_db_path = self._resolve_path(state_db_path)
        self.logger = logger or logging.getLogger("web_console")

    def _resolve_path(self, p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else self.workspace_root / path

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
        """Fetch router health or return OFFLINE."""
        data = self._http_get("/health")
        if data:
            return {
                "status": data.get("status", "HEALTHY"),
                "queue": data.get("queue", "HEALTHY"),
                "uptime_seconds": data.get("uptime_seconds", 0.0),
                "reachable": True,
            }
        return {
            "status": "OFFLINE",
            "queue": "UNKNOWN",
            "uptime_seconds": 0.0,
            "reachable": False,
        }

    def get_status(self) -> Dict[str, Any]:
        """Fetch full router operational status."""
        data = self._http_get("/status")
        if data:
            data["reachable"] = True
            return data

        # Fallback if router daemon HTTP server is down
        return {
            "service": "validation-data-router",
            "overall_status": "OFFLINE",
            "reachable": False,
            "queue_health": {
                "status": "UNKNOWN",
                "current_depth": 0,
                "max_capacity": 10000,
                "utilization_pct": 0.0,
            },
            "destinations": {},
            "metrics": {
                "uptime_seconds": 0.0,
                "totals": {"received": 0, "acknowledged": 0, "failed": 0, "throughput_msg_per_sec": 0.0},
                "sources": {}
            }
        }

    def get_metrics(self) -> Dict[str, Any]:
        """Fetch router metrics snapshot."""
        data = self._http_get("/metrics")
        if data:
            return data
        return {
            "uptime_seconds": 0.0,
            "totals": {"received": 0, "acknowledged": 0, "failed": 0, "throughput_msg_per_sec": 0.0},
            "sources": {}
        }

    def get_sources(self) -> List[Dict[str, Any]]:
        """Return comprehensive list of configured sources and live metrics."""
        # Read configured sources from sources.yaml
        config_sources = {}
        destinations = {}
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    raw_cfg = yaml.safe_load(f) or {}
                    config_sources = raw_cfg.get("sources", {})
                    destinations = raw_cfg.get("parser_destinations", {})
            except Exception as e:
                self.logger.error(f"Error reading sources config: {e}")

        # Fetch live metrics from HTTP
        status_data = self.get_status()
        live_sources = status_data.get("metrics", {}).get("sources", {})
        live_destinations = status_data.get("destinations", {})

        result = []
        for src_name, cfg in config_sources.items():
            stype = cfg.get("type", "file").upper()
            parser_name = cfg.get("parser", "UNKNOWN")
            dest_cfg = destinations.get(parser_name, {})
            dest_str = f"{dest_cfg.get('host', '127.0.0.1')}:{dest_cfg.get('port', 0)}"

            metrics = live_sources.get(src_name, {})
            is_running = metrics.get("running", False)
            is_connected = metrics.get("connected", False)

            if not status_data.get("reachable"):
                status_label = "STOPPED"
            elif not cfg.get("enabled", True):
                status_label = "DISABLED"
            elif is_connected or is_running:
                status_label = "CONNECTED" if stype == "TCP" else "RUNNING"
            else:
                status_label = "DISCONNECTED" if stype == "TCP" else "IDLE"

            port_num = str(dest_cfg.get("port", 0))

            # Format human-readable input configuration summary
            if stype == "FILE":
                pats = ", ".join(cfg.get("file_patterns", ["*"]))
                input_config_str = f"folder: {cfg.get('folder', src_name)} ({pats})"
            else:
                input_config_str = f"{cfg.get('remote_host', '-')}:{cfg.get('remote_port', '-')} ({cfg.get('framing', 'line')})"

            last_act = metrics.get("last_delivery_at") or metrics.get("last_received_at")

            result.append({
                "source_name": src_name,
                "type": stype,
                "enabled": cfg.get("enabled", True),
                "status": status_label,
                "running": is_running,
                "connected": is_connected,
                "parser": parser_name,
                "destination": dest_str,
                "destination_port": port_num,
                "input_config": input_config_str,
                "raw_config": cfg,
                "files_discovered": metrics.get("files_discovered", 0),
                "messages_received": metrics.get("messages_received", 0),
                "messages_routed": metrics.get("messages_routed", 0),
                "messages_acknowledged": metrics.get("messages_acknowledged", 0),
                "messages_failed": metrics.get("messages_failed", 0),
                "retry_count": metrics.get("retry_count", 0),
                "last_received_at": metrics.get("last_received_at"),
                "last_delivery_at": metrics.get("last_delivery_at"),
                "last_activity": last_act,
                "last_error": metrics.get("last_error"),
            })

        return result

    def get_queue_view(self) -> Dict[str, Any]:
        """Fetch queue depth and item distribution from status & SQLite state."""
        status_data = self.get_status()
        q_health = status_data.get("queue_health", {})

        state_counts = {}
        if self.state_db_path.exists():
            try:
                conn = sqlite3.connect(f"file:{self.state_db_path}?mode=ro", uri=True)
                cursor = conn.cursor()
                cursor.execute("SELECT status, COUNT(*) FROM file_states GROUP BY status")
                state_counts = dict(cursor.fetchall())
                conn.close()
            except Exception:
                pass

        return {
            "current_depth": q_health.get("current_depth", 0),
            "max_capacity": q_health.get("max_capacity", 10000),
            "utilization_pct": q_health.get("utilization_pct", 0.0),
            "status": q_health.get("status", "UNKNOWN"),
            "states": {
                "READY": state_counts.get("READY", 0),
                "QUEUED": state_counts.get("QUEUED", 0),
                "SENDING": state_counts.get("SENDING", 0),
                "RETRYING": state_counts.get("RETRYING", 0),
                "ACKNOWLEDGED": state_counts.get("ACKNOWLEDGED", 0),
                "PROCESSED": state_counts.get("PROCESSED", 0),
                "FAILED": state_counts.get("FAILED", 0),
            }
        }

    def get_activity(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Parse structured operational events from router log."""
        if not self.log_path.exists():
            return []

        events = []
        try:
            with open(self.log_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            for line in reversed(lines):
                if len(events) >= limit:
                    break
                line = line.strip()
                if not line:
                    continue

                # Parse key-value tokens: event=XYZ source=ABC message_id=...
                kv = {}
                for m in re.finditer(r'(\w+)=(?:"([^"]*)"|(\S+))', line):
                    k = m.group(1)
                    v = m.group(2) if m.group(2) is not None else m.group(3)
                    kv[k] = v

                # Match line timestamp: e.g. 2026-09-17 00:15:30,123
                time_match = re.match(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:,\d+)?)", line)
                timestamp = time_match.group(1) if time_match else None

                event_name = kv.get("event")
                if event_name:
                    events.append({
                        "timestamp": timestamp,
                        "event": event_name,
                        "source": kv.get("source", "ROUTER"),
                        "filename": kv.get("filename"),
                        "message_id": kv.get("message_id"),
                        "destination": kv.get("destination"),
                        "attempt": kv.get("attempt"),
                        "error": kv.get("error"),
                        "raw": line,
                    })
        except Exception as e:
            self.logger.error(f"Error parsing activity log: {e}")

        return events

    def get_errors(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return recent error records from log and state database."""
        errors = []
        
        # 1. From SQLite state store
        if self.state_db_path.exists():
            try:
                conn = sqlite3.connect(f"file:{self.state_db_path}?mode=ro", uri=True)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT source, filename, message_id, status, attempt_count, last_attempt, last_error
                    FROM file_states
                    WHERE status IN ('RETRYING', 'FAILED') OR last_error IS NOT NULL
                    ORDER BY last_attempt DESC LIMIT ?
                    """,
                    (limit,)
                )
                for row in cursor.fetchall():
                    errors.append({
                        "source": row["source"],
                        "filename": row["filename"],
                        "message_id": row["message_id"],
                        "status": row["status"],
                        "attempt_count": row["attempt_count"],
                        "timestamp": row["last_attempt"],
                        "message": row["last_error"],
                        "type": "DELIVERY_ERROR" if row["status"] == "FAILED" else "RETRY_ALERT"
                    })
                conn.close()
            except Exception:
                pass

        # 2. From log lines if state DB had few or none
        if len(errors) < limit and self.log_path.exists():
            try:
                with open(self.log_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in reversed(f.readlines()):
                        if len(errors) >= limit:
                            break
                        if "ERROR" in line or "WARNING" in line:
                            kv = dict(re.findall(r'(\w+)=(?:"([^"]*)"|(\S+))', line))
                            if kv.get("error"):
                                errors.append({
                                    "source": kv.get("source", "ROUTER"),
                                    "filename": kv.get("filename"),
                                    "message_id": kv.get("message_id"),
                                    "status": kv.get("event", "ERROR").upper(),
                                    "attempt_count": kv.get("attempt", 1),
                                    "timestamp": None,
                                    "message": kv.get("error"),
                                    "type": "LOG_ERROR"
                                })
            except Exception:
                pass

        return errors[:limit]

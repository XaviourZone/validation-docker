"""Overall Validation System status evaluator across the three runtime services."""

from typing import Any, Dict
from .router_client import RouterClient


class SystemStatusEvaluator:
    """Aggregates truthful status across Router, Parser and Forwarder."""

    def __init__(self, router_client: RouterClient, parser_client: Any = None, forwarder_client: Any = None):
        self.router_client = router_client
        self.parser_client = parser_client
        self.forwarder_client = forwarder_client

    def get_system_status(self) -> Dict[str, Any]:
        router_health = self.router_client.get_health()
        router_status = "RUNNING" if router_health.get("reachable") else "STOPPED"

        parser_status = "STOPPED"
        parser_health = "OFFLINE"
        parser_uptime = 0.0
        if self.parser_client:
            try:
                p = self.parser_client.get_health()
                if p.get("reachable"):
                    parser_status = "RUNNING"
                    parser_health = "HEALTHY"
                    parser_uptime = p.get("uptime_seconds", 0.0)
            except Exception:
                parser_status = "NOT RUNNING"

        forwarder_status = "STOPPED"
        forwarder_health = "OFFLINE"
        if self.forwarder_client:
            try:
                f = self.forwarder_client.get_health()
                if f.get("reachable") and f.get("running"):
                    forwarder_status = "RUNNING"
                    forwarder_health = f.get("status", "READY")
            except Exception:
                forwarder_status = "NOT RUNNING"

        modules = [
            {
                "id": "router", "name": "Data Router", "stage": 1,
                "status": router_status, "implemented": True,
                "description": "Ingestion, provenance tagging, queuing & delivery to parsers",
                "health": router_health.get("status", "OFFLINE"),
                "uptime": router_health.get("uptime_seconds", 0.0),
            },
            {
                "id": "parser", "name": "Data Parser", "stage": 2,
                "status": parser_status, "implemented": True,
                "description": "Source parsing, decoding, normalization, correlation & enrichment",
                "health": parser_health, "uptime": parser_uptime,
            },
            {
                "id": "forwarder", "name": "Data Forwarder", "stage": 3,
                "status": forwarder_status, "implemented": True,
                "description": "Final XML delivery to configured downstream destinations",
                "health": forwarder_health, "uptime": 0.0,
            },
        ]

        if router_status == "RUNNING" and parser_status == "RUNNING" and forwarder_status == "RUNNING":
            overall, health = "OPERATIONAL", "HEALTHY"
        elif router_status == "RUNNING":
            overall, health = "PIPELINE DEGRADED", "DEGRADED"
        else:
            overall, health = "ROUTER OFFLINE", "DEGRADED"

        return {
            "system_name": "Validation Maritime Pipeline",
            "overall_health": health,
            "overall_status": overall,
            "modules": modules,
        }

"""HTTP Server and REST API handler for Validation Web Console."""

import json
import logging
import mimetypes
import os
import re
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
import urllib.parse
import yaml

from .config_manager import RouterConfigManager
from .router_client import RouterClient
from .service_control.base import BaseServiceController
from .system_status import SystemStatusEvaluator


class WebConsoleHandler(SimpleHTTPRequestHandler):
    """Handles HTTP requests for Web Console dashboard, static assets, and REST APIs."""

    # Injected by the server instance
    router_client: RouterClient
    system_status: SystemStatusEvaluator
    service_controller: BaseServiceController
    config_manager: RouterConfigManager
    router_service_name: str
    parser_service_name: str
    static_dir: Path
    template_path: Path
    parser_client: Any = None
    database_client: Any = None
    logger: logging.Logger

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # Static assets
        if path.startswith("/static/"):
            self._serve_static(path)
            return

        # Dashboard HTML
        if path in ("/", "/index.html"):
            self._serve_dashboard()
            return

        # REST API endpoints
        if path == "/api/system/status":
            self._json_response(self.system_status.get_system_status())
            return
        if path == "/api/database/status":
            if self.database_client:
                self._json_response({
                    "wrs": self.database_client.get_wrs_status(),
                    "pans": self.database_client.get_pans_status(),
                    "nsc": self.database_client.get_nsc_status()
                })
            else:
                self._error_response(HTTPStatus.NOT_FOUND, "Database client not available")
            return
        if path == "/api/router/status":
            status_data = self.router_client.get_status()
            svc_info = self.service_controller.get_service_status(self.router_service_name)
            svc_status = svc_info.get("status", "UNKNOWN")
            if status_data.get("reachable"):
                effective_status = "RUNNING"
            elif svc_status in ("STARTING", "STOPPING", "FAILED"):
                effective_status = svc_status
            elif svc_status == "RUNNING" and not status_data.get("reachable"):
                effective_status = "STARTING"
            else:
                effective_status = "STOPPED"
            status_data["service_status"] = effective_status
            status_data["service_info"] = svc_info
            self._json_response(status_data)
            return
        if path == "/api/router/health":
            self._json_response(self.router_client.get_health())
            return
        if path == "/api/router/metrics":
            self._json_response(self.router_client.get_metrics())
            return
        if path == "/api/router/sources":
            self._json_response(self.router_client.get_sources())
            return
        if path == "/api/router/config":
            self._json_response({
                "sources": self.config_manager.get_sources(),
                "parser_destinations": self.config_manager.get_parser_destinations()
            })
            return
        if path == "/api/router/parser-destinations":
            self._json_response(self.config_manager.get_parser_destinations())
            return
        if path == "/api/router/audit":
            params = urllib.parse.parse_qs(parsed.query)
            limit = int(params.get("limit", [50])[0])
            self._json_response(self.config_manager.get_audit_log(limit=limit))
            return
        if path == "/api/router/queue":
            self._json_response(self.router_client.get_queue_view())
            return
        if path == "/api/router/activity":
            params = urllib.parse.parse_qs(parsed.query)
            limit = int(params.get("limit", [50])[0])
            self._json_response(self.router_client.get_activity(limit=limit))
            return
        if path == "/api/router/errors":
            params = urllib.parse.parse_qs(parsed.query)
            limit = int(params.get("limit", [20])[0])
            self._json_response(self.router_client.get_errors(limit=limit))
            return

        # Parser status endpoints
        if path == "/api/parser/status":
            if self.parser_client:
                self._json_response(self.parser_client.get_status())
            else:
                self._json_response({
                    "service": "validation-data-parser",
                    "overall_status": "NOT IMPLEMENTED",
                    "reachable": False,
                    "metrics": {}
                })
            return
        if path == "/api/parser/metrics":
            if self.parser_client:
                self._json_response(self.parser_client.get_metrics())
            else:
                self._json_response({
                    "messages_received": 0,
                    "messages_parsed": 0,
                    "messages_rejected": 0,
                    "parse_errors": 0,
                    "status": "NOT IMPLEMENTED"
                })
            return

        # 404 Not Found
        self._error_response(HTTPStatus.NOT_FOUND, f"Endpoint not found: {path}")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # Read optional JSON request body
        content_length = int(self.headers.get("Content-Length", 0))
        body = {}
        if content_length > 0:
            try:
                raw_data = self.rfile.read(content_length)
                body = json.loads(raw_data.decode("utf-8"))
            except Exception as e:
                self._error_response(HTTPStatus.BAD_REQUEST, f"Invalid JSON body: {str(e)}")
                return

        # Router Service Controls
        if path == "/api/router/start":
            res = self.service_controller.start_service(self.router_service_name)
            self._json_response(res, status=HTTPStatus.OK if res.get("success") else HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if path == "/api/router/stop":
            res = self.service_controller.stop_service(self.router_service_name)
            self._json_response(res, status=HTTPStatus.OK if res.get("success") else HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if path == "/api/router/restart":
            res = self.service_controller.restart_service(self.router_service_name)
            self._json_response(res, status=HTTPStatus.OK if res.get("success") else HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if path == "/api/router/reload":
            res = self.service_controller.reload_configuration(self.router_service_name)
            self._json_response(res, status=HTTPStatus.OK if res.get("success") else HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if path == "/api/router/validate-config":
            self._handle_validate_config()
            return

        # Database Controls
        if path == "/api/database/wrs/refresh":
            res = self.database_client.refresh_wrs()
            self._json_response(res, status=HTTPStatus.OK if res.get("success") else HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if path == "/api/database/wrs/clear":
            res = self.database_client.clear_wrs()
            self._json_response(res, status=HTTPStatus.OK if res.get("success") else HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if path == "/api/database/nsc/refresh":
            res = self.database_client.refresh_nsc()
            self._json_response(res, status=HTTPStatus.OK if res.get("success") else HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if path == "/api/database/nsc/clear":
            res = self.database_client.clear_nsc()
            self._json_response(res, status=HTTPStatus.OK if res.get("success") else HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if path == "/api/database/pans/start":
            res = self.service_controller.start_service("validation-pans-importer.service")
            self._json_response(res, status=HTTPStatus.OK if res.get("success") else HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if path == "/api/database/pans/stop":
            res = self.service_controller.stop_service("validation-pans-importer.service")
            self._json_response(res, status=HTTPStatus.OK if res.get("success") else HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if path == "/api/database/pans/process":
            res = self.database_client.process_pans_now()
            self._json_response(res, status=HTTPStatus.OK if res.get("success") else HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if path == "/api/database/pans/clear":
            res = self.database_client.clear_pans()
            self._json_response(res, status=HTTPStatus.OK if res.get("success") else HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        # Source Configuration Management APIs
        if path == "/api/router/sources/validate":
            is_new = bool(body.get("is_new", False))
            is_valid, errors, normalized = self.config_manager.validate_source_payload(body, is_new=is_new)
            resp = {
                "valid": is_valid,
                "errors": errors,
                "normalized": normalized,
                "message": "Source configuration is valid" if is_valid else f"Validation failed with {len(errors)} error(s)"
            }
            self._json_response(resp, status=HTTPStatus.OK if is_valid else HTTPStatus.UNPROCESSABLE_ENTITY)
            return

        if path == "/api/router/sources/save":
            is_new = bool(body.get("is_new", False))
            success, msg, norm = self.config_manager.save_source(body, is_new=is_new)
            resp = {
                "success": success,
                "message": msg,
                "reload_required": True,
                "source": norm.get("source_name") or body.get("source_name") or body.get("name"),
                "effective_config": norm
            }
            self._json_response(resp, status=HTTPStatus.OK if success else HTTPStatus.UNPROCESSABLE_ENTITY)
            return

        if path == "/api/router/sources/rename":
            old_name = str(body.get("old_source_name") or "").strip()
            new_name = str(body.get("new_source_name") or "").strip()
            success, msg = self.config_manager.rename_source(old_name, new_name)
            self._json_response({
                "success": success,
                "message": msg,
                "reload_required": True,
                "source": new_name if success else old_name,
            }, status=HTTPStatus.OK if success else HTTPStatus.UNPROCESSABLE_ENTITY)
            return

        # Delete source
        match_delete = re.match(r"^/api/router/sources/([^/]+)/delete$", path)
        if match_delete:
            source_name = match_delete.group(1)
            success, msg = self.config_manager.delete_source(source_name)
            self._json_response({
                "success": success,
                "message": msg,
                "reload_required": True,
                "source": source_name
            }, status=HTTPStatus.OK if success else HTTPStatus.BAD_REQUEST)
            return

        # Source enable/disable controls
        match_src_action = re.match(r"^/api/router/sources/([^/]+)/(enable|disable)$", path)
        if match_src_action:
            source_name = match_src_action.group(1)
            action = match_src_action.group(2)
            enable = (action == "enable")
            success, msg = self.config_manager.toggle_source(source_name, enable)
            self._json_response({
                "success": success,
                "message": msg,
                "reload_required": True,
                "source": source_name,
                "enabled": enable
            }, status=HTTPStatus.OK if success else HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        # Parser service controls
        if path == "/api/parser/start":
            res = self.service_controller.start_service(self.parser_service_name)
            self._json_response(res, status=HTTPStatus.OK if res.get("success") else HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if path == "/api/parser/stop":
            res = self.service_controller.stop_service(self.parser_service_name)
            self._json_response(res, status=HTTPStatus.OK if res.get("success") else HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if path == "/api/parser/restart":
            res = self.service_controller.restart_service(self.parser_service_name)
            self._json_response(res, status=HTTPStatus.OK if res.get("success") else HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self._error_response(HTTPStatus.NOT_FOUND, f"Endpoint not found or method not allowed: {path}")

    def _serve_dashboard(self):
        if not self.template_path.exists():
            self._error_response(HTTPStatus.NOT_FOUND, "Dashboard template index.html not found.")
            return

        try:
            with open(self.template_path, "rb") as f:
                content = f.read()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self._error_response(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error reading dashboard: {str(e)}")

    def _serve_static(self, path: str):
        rel_path = path[len("/static/"):]
        file_path = self.static_dir / rel_path
        
        # Security: prevent path traversal attacks
        try:
            resolved = file_path.resolve()
            if not str(resolved).startswith(str(self.static_dir.resolve())):
                self._error_response(HTTPStatus.FORBIDDEN, "Forbidden")
                return
        except Exception:
            self._error_response(HTTPStatus.FORBIDDEN, "Forbidden")
            return

        if not resolved.exists() or not resolved.is_file():
            self._error_response(HTTPStatus.NOT_FOUND, f"Static asset not found: {path}")
            return

        mime_type, _ = mimetypes.guess_type(str(resolved))
        if not mime_type:
            mime_type = "application/octet-stream"

        try:
            with open(resolved, "rb") as f:
                content = f.read()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "max-age=3600")
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self._error_response(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error reading asset: {str(e)}")

    def _handle_validate_config(self):
        config_path = self.router_client.config_path
        if not config_path.exists():
            self._json_response({
                "valid": False,
                "message": f"Config file does not exist: {config_path}"
            }, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            
            if not isinstance(data, dict):
                raise ValueError("Config YAML root must be a mapping dictionary")
            
            sources = data.get("sources", {})
            destinations = data.get("parser_destinations", {})
            
            if not sources:
                raise ValueError("Config contains no sources definition")
            
            # Verify source references
            errors = []
            for name, scfg in sources.items():
                pname = scfg.get("parser")
                if not pname:
                    errors.append(f"Source '{name}' missing 'parser' field")
                elif pname not in destinations:
                    errors.append(f"Source '{name}' targets unknown destination '{pname}'")

            if errors:
                self._json_response({
                    "valid": False,
                    "errors": errors,
                    "message": f"Validation failed with {len(errors)} error(s)"
                }, status=HTTPStatus.UNPROCESSABLE_ENTITY)
            else:
                self._json_response({
                    "valid": True,
                    "message": f"Configuration is valid ({len(sources)} sources, {len(destinations)} destinations)",
                    "source_count": len(sources),
                    "destination_count": len(destinations)
                })
        except Exception as e:
            self._json_response({
                "valid": False,
                "message": f"YAML Syntax / Validation Error: {str(e)}"
            }, status=HTTPStatus.BAD_REQUEST)

    def _handle_source_toggle(self, source_name: str, enable: bool):
        config_path = self.router_client.config_path
        if not config_path.exists():
            self._json_response({
                "success": False,
                "message": f"Config file not found: {config_path}"
            }, status=HTTPStatus.NOT_FOUND)
            return

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            sources = data.get("sources", {})
            if source_name not in sources:
                self._json_response({
                    "success": False,
                    "message": f"Source '{source_name}' not defined in configuration"
                }, status=HTTPStatus.NOT_FOUND)
                return

            current_enabled = sources[source_name].get("enabled", True)
            if current_enabled == enable:
                action_str = "already enabled" if enable else "already disabled"
                self._json_response({
                    "success": True,
                    "message": f"Source '{source_name}' is {action_str}",
                    "source": source_name,
                    "enabled": enable
                })
                return

            # Update configuration safely
            sources[source_name]["enabled"] = enable
            data["sources"] = sources

            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, default_flow_style=False, sort_keys=False)

            action_str = "enabled" if enable else "disabled"
            self.logger.info(f"Source '{source_name}' {action_str} in configuration.")
            
            self._json_response({
                "success": True,
                "message": f"Source '{source_name}' successfully {action_str}. Reload router to apply.",
                "source": source_name,
                "enabled": enable
            })
        except Exception as e:
            self._json_response({
                "success": False,
                "message": f"Failed to update source '{source_name}': {str(e)}"
            }, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _json_response(self, data: Any, status: HTTPStatus = HTTPStatus.OK):
        try:
            payload = json.dumps(data, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass

    def _error_response(self, status: HTTPStatus, message: str):
        try:
            payload = json.dumps({"error": True, "status": status.value, "message": message}).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass

    def log_message(self, format: str, *args: Any):
        """Forward access logs through the standard logger instead of stderr."""
        if hasattr(self, "logger") and self.logger:
            self.logger.debug(f"{self.address_string()} - {format % args}")


class WebConsoleServer:
    """Manages the lifecycle of the Validation Web Console server."""

    def __init__(
        self,
        host: str,
        port: int,
        router_client: RouterClient,
        system_status: SystemStatusEvaluator,
        service_controller: BaseServiceController,
        static_dir: Path,
        template_path: Path,
        router_service_name: str = "validation-router.service",
        parser_service_name: str = "validation-parser.service",
        parser_client: Any = None,
        config_manager: Optional[RouterConfigManager] = None,
        database_client: Any = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.host = host
        self.port = port
        self.router_client = router_client
        self.system_status = system_status
        self.service_controller = service_controller
        self.static_dir = static_dir
        self.template_path = template_path
        self.router_service_name = router_service_name
        self.parser_service_name = parser_service_name
        self.parser_client = parser_client
        self.database_client = database_client
        self.config_manager = config_manager or RouterConfigManager(
            config_path=router_client.config_path,
            workspace_root=router_client.workspace_root,
            logger=logger,
        )
        self.logger = logger or logging.getLogger("web_console")
        self._server: Optional[ThreadingHTTPServer] = None

    def start(self):
        """Start the HTTP server."""
        # Attach context to the request handler class
        WebConsoleHandler.router_client = self.router_client
        WebConsoleHandler.system_status = self.system_status
        WebConsoleHandler.service_controller = self.service_controller
        WebConsoleHandler.config_manager = self.config_manager
        WebConsoleHandler.router_service_name = self.router_service_name
        WebConsoleHandler.parser_service_name = self.parser_service_name
        WebConsoleHandler.static_dir = self.static_dir
        WebConsoleHandler.template_path = self.template_path
        WebConsoleHandler.parser_client = self.parser_client
        WebConsoleHandler.database_client = self.database_client
        WebConsoleHandler.logger = self.logger

        self._server = ThreadingHTTPServer((self.host, self.port), WebConsoleHandler)
        self.logger.info(f"Validation Web Console listening on http://{self.host}:{self.port}")
        self._server.serve_forever()

    def shutdown(self):
        """Stop the HTTP server cleanly."""
        if self._server:
            self.logger.info("Stopping Validation Web Console server...")
            self._server.shutdown()
            self._server.server_close()
            self._server = None

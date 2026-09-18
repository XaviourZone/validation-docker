"""Web Console API extension for Router source browsing and parser mappings."""
import json
import os
import tempfile
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml
from Validation.Data_Parser.app.pipeline.mapping_manager import ParserMappingManager, default_mapping_for

ALLOWED_FILE_PATTERNS = ["*.csv", "*.xml", "*.json", "*.txt", "*.nmea", "*.log", "*"]


def _atomic_yaml(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def install_router_admin_extension(handler_class, workspace_root, config_manager, logger):
    if getattr(handler_class, "_router_admin_extension_installed", False):
        return
    handler_class._router_admin_extension_installed = True
    handler_class.router_admin_workspace_root = Path(workspace_root)
    handler_class.router_admin_config_manager = config_manager
    handler_class.router_admin_logger = logger
    handler_class.router_mapping_manager = ParserMappingManager(
        Path(workspace_root) / "Validation" / "Data_Parser" / "config" / "parser_mappings.yaml"
    )

    original_get = handler_class.do_GET
    original_post = handler_class.do_POST

    def do_get(self):
        path = urlparse(self.path).path
        if path == "/api/router/filesystem/browse":
            self._router_browse()
            return
        if path == "/api/router/filesystem/patterns":
            self._json_response({"patterns": ALLOWED_FILE_PATTERNS})
            return
        if path == "/api/parser/mapping/fields":
            self._json_response({"fields": self.router_mapping_manager.fields()})
            return
        if path == "/api/parser/mapping/parsers":
            names = self.router_mapping_manager.parser_names()
            configured = list(self.router_admin_config_manager.get_parser_destinations().keys())
            for name in configured:
                if name not in names:
                    names.append(name)
            self._json_response({"parsers": names})
            return
        if path == "/api/parser/mapping":
            query = parse_qs(urlparse(self.path).query)
            name = (query.get("parser") or [""])[0]
            if not name:
                self._json_response({"error": "parser query parameter is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            mapping = self.router_mapping_manager.get(name)
            if not mapping.get("fields") or all(not v for v in mapping["fields"].values()):
                mapping = default_mapping_for(name)
            self._json_response({"parser": name, "mapping": mapping})
            return
        if path == "/api/parser/ais-state":
            query = parse_qs(urlparse(self.path).query)
            try:
                mmsi = int((query.get("mmsi") or [""])[0])
                from Validation.Data_Parser.app.pipeline.ais_state import AISStateDB
                db = AISStateDB()
                self._json_response({
                    "mmsi": mmsi,
                    "state": db.get(mmsi),
                    "recent_messages": db.recent_messages(mmsi),
                })
                db.close()
            except Exception as exc:
                self._json_response({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        return original_get(self)

    def do_post(self):
        path = urlparse(self.path).path
        if path == "/api/parser/mapping/save":
            self._router_save_mapping()
            return
        # Kept as an API for future controlled provisioning; the operator UI
        # deliberately does not expose Add Parser.
        if path == "/api/parser/mapping/create":
            self._router_create_parser()
            return
        return original_post(self)

    def _router_browse(self):
        query = parse_qs(urlparse(self.path).query)
        raw = (query.get("path") or [""])[0]
        if raw:
            path = Path(raw).expanduser()
        elif os.name == "nt":
            roots = []
            for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                root = Path(f"{letter}:\\")
                if root.exists():
                    roots.append({"name": str(root), "path": str(root), "readable": os.access(root, os.R_OK | os.X_OK)})
            self._json_response({"roots": roots})
            return
        else:
            path = Path("/")

        try:
            path = path.resolve()
            if not path.exists() or not path.is_dir():
                self._json_response({"error": f"Directory does not exist: {path}"}, status=HTTPStatus.NOT_FOUND)
                return
            entries = []
            for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                if not child.is_dir() or child.name.startswith("."):
                    continue
                try:
                    readable = os.access(child, os.R_OK | os.X_OK)
                except OSError:
                    readable = False
                entries.append({"name": child.name, "path": str(child), "readable": readable})
            self._json_response({
                "path": str(path),
                "parent": str(path.parent) if path.parent != path else None,
                "entries": entries,
            })
        except Exception as exc:
            self._json_response({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def _router_save_mapping(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            name = str(body.get("parser") or "").strip()
            saved = self.router_mapping_manager.save(name, body.get("mapping") or {})
            self._json_response({"success": True, "parser": name, "mapping": saved})
        except Exception as exc:
            self._json_response({"success": False, "error": str(exc)}, status=HTTPStatus.UNPROCESSABLE_ENTITY)

    def _router_create_parser(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            name = str(body.get("parser") or "").strip()
            port = int(body.get("port", 0))
            if not name or not name.replace("_", "").replace("-", "").isalnum():
                raise ValueError("Parser name must contain only letters, numbers, '_' or '-'")
            if not 1 <= port <= 65535:
                raise ValueError("Parser port must be between 1 and 65535")

            parser_cfg_path = self.router_admin_workspace_root / "Validation" / "Data_Parser" / "config" / "parser.yaml"
            parser_cfg = yaml.safe_load(parser_cfg_path.read_text(encoding="utf-8")) or {}
            endpoints = parser_cfg.setdefault("endpoints", {})
            if name in endpoints:
                raise ValueError(f"Parser '{name}' already exists")
            if any(int(v.get("port", 0)) == port for v in endpoints.values()):
                raise ValueError(f"Parser port {port} is already configured")

            router_raw = self.router_admin_config_manager.get_raw_config()
            parser_destinations = router_raw.setdefault("parser_destinations", {})
            if name in parser_destinations:
                raise ValueError(f"Router parser destination '{name}' already exists")
            if any(int(v.get("port", 0)) == port for v in parser_destinations.values()):
                raise ValueError(f"Router parser destination port {port} is already configured")

            endpoints[name] = {"port": port, "sources": [], "framing": "ndjson"}
            parser_destinations[name] = {
                "host": "127.0.0.1",
                "port": port,
                "framing": "ndjson",
                "timeout_seconds": 5.0,
                "keep_alive": True,
            }
            _atomic_yaml(parser_cfg_path, parser_cfg)
            with self.router_admin_config_manager._lock:
                self.router_admin_config_manager._atomic_write_unlocked(router_raw)
            self.router_mapping_manager.save(name, default_mapping_for(name))

            try:
                result = self.service_controller.restart_service("validation-parser.service")
            except Exception as exc:
                result = {"success": False, "message": f"Parser mapping created; parser restart pending: {exc}"}
            self._json_response({"success": True, "parser": name, "port": port, "restart": result})
        except Exception as exc:
            self._json_response({"success": False, "error": str(exc)}, status=HTTPStatus.UNPROCESSABLE_ENTITY)

    handler_class.do_GET = do_get
    handler_class.do_POST = do_post
    handler_class._router_browse = _router_browse
    handler_class._router_save_mapping = _router_save_mapping
    handler_class._router_create_parser = _router_create_parser

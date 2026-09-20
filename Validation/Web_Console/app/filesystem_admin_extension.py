"""Cross-platform folder browsing for operator configuration dialogs."""

import os
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def install_filesystem_admin_extension(handler_class, logger):
    if getattr(handler_class, "_filesystem_admin_extension_installed", False):
        return
    handler_class._filesystem_admin_extension_installed = True
    handler_class.filesystem_admin_logger = logger
    original_get = handler_class.do_GET

    def do_get(self):
        if urlparse(self.path).path == "/api/router/filesystem/browse":
            self._filesystem_browse()
            return
        return original_get(self)

    def _host_mount_root():
        return Path(os.environ.get("VALIDATION_HOST_FILESYSTEM_ROOT", "/opt/validation/hostfs")).resolve()

    def _host_to_container(host_path: Path) -> Path:
        root = _host_mount_root()
        relative = Path(str(host_path)).resolve().relative_to(Path("/"))
        return (root / relative).resolve()

    def _container_to_host(container_path: Path) -> Path:
        root = _host_mount_root()
        relative = container_path.resolve().relative_to(root)
        return (Path("/") / relative).resolve()

    def _roots():
        root = _host_mount_root()
        if root.exists() and root.is_dir():
            return [{"name": "/", "path": "/", "readable": True}]
        return [{"name": str(Path.cwd()), "path": str(Path.cwd()), "readable": True}]

    def filesystem_browse(self):
        query = parse_qs(urlparse(self.path).query)
        raw = (query.get("path") or [""])[0].strip()
        try:
            # Start directly at the host filesystem root. Do not show a
            # second artificial "root" row; the operator should immediately
            # see the actual top-level folders.
            if not raw:
                raw = "/"
            # The operator browser works in host filesystem coordinates.
            # Docker exposes the host root read-only at VALIDATION_HOST_FILESYSTEM_ROOT.
            candidate = Path(raw).expanduser()
            if not candidate.is_absolute():
                candidate = Path("/") / candidate
            host_path = candidate.resolve()
            try:
                path = _host_to_container(host_path)
            except (ValueError, OSError) as exc:
                self._json_response({"error": f"Invalid host path: {exc}"}, status=HTTPStatus.BAD_REQUEST)
                return
            if not path.exists() or not path.is_dir():
                self._json_response({"error": f"Directory does not exist: {host_path}"}, status=HTTPStatus.NOT_FOUND)
                return
            logical_path = "/" if str(host_path) == "/" else str(host_path)
            entries = []
            for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                if not child.is_dir() or child.name.startswith("."):
                    continue
                try:
                    readable = os.access(child, os.R_OK | os.X_OK)
                except OSError:
                    readable = False
                child_host = _container_to_host(child)
                entries.append({"name": child.name, "path": str(child_host), "logical_path": str(child_host), "readable": readable})
            self._json_response({
                "path": str(host_path),
                "logical_path": logical_path,
                "parent": str(host_path.parent) if host_path != Path("/") else None,
                "entries": entries,
            })
        except (OSError, ValueError) as exc:
            self._json_response({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    handler_class.do_GET = do_get
    handler_class._filesystem_browse = filesystem_browse

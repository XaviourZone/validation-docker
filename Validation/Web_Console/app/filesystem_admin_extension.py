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

    def _roots():
        if os.name == "nt":
            result = []
            for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                root = Path(f"{letter}:\\")
                if root.exists():
                    result.append(root)
            return result or [Path.cwd()]
        return [Path("/")]

    def filesystem_browse(self):
        query = parse_qs(urlparse(self.path).query)
        raw = (query.get("path") or [""])[0].strip()
        try:
            if not raw:
                self._json_response({"roots": [
                    {"name": str(p), "path": str(p), "readable": os.access(p, os.R_OK | os.X_OK)}
                    for p in _roots()
                ]})
                return
            path = Path(raw).expanduser().resolve()
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
        except (OSError, ValueError) as exc:
            self._json_response({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    handler_class.do_GET = do_get
    handler_class._filesystem_browse = filesystem_browse

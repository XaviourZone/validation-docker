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
        # Data Router file sources are configured relative to DATA_INFLOW.
        # The Web Console container exposes that host directory at this path.
        data_inflow = Path(os.environ.get("VALIDATION_DATA_INFLOW_ROOT", "/opt/validation/DATA_INFLOW")).resolve()
        if data_inflow.exists() and data_inflow.is_dir():
            return [data_inflow]
        return [Path.cwd()]

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
            data_root = Path(os.environ.get("VALIDATION_DATA_INFLOW_ROOT", "/opt/validation/DATA_INFLOW")).resolve()
            # Accept the configured relative folder (e.g. SAIS_IOR) as well
            # as the container-visible absolute path.
            candidate = Path(raw).expanduser()
            if not candidate.is_absolute():
                candidate = data_root / candidate
            path = candidate.resolve()
            try:
                path.relative_to(data_root)
            except ValueError:
                self._json_response({"error": "Folder is outside the Data Inflow root."}, status=HTTPStatus.FORBIDDEN)
                return
            if not path.exists() or not path.is_dir():
                self._json_response({"error": f"Directory does not exist: {path}"}, status=HTTPStatus.NOT_FOUND)
                return
            relative = path.relative_to(data_root)
            logical_path = "" if str(relative) == "." else relative.as_posix()
            entries = []
            for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                if not child.is_dir() or child.name.startswith("."):
                    continue
                try:
                    readable = os.access(child, os.R_OK | os.X_OK)
                except OSError:
                    readable = False
                child_relative = child.relative_to(data_root)
                child_logical = "" if str(child_relative) == "." else child_relative.as_posix()
                entries.append({"name": child.name, "path": str(child), "logical_path": child_logical, "readable": readable})
            self._json_response({
                "path": str(path),
                "logical_path": logical_path,
                "parent": str(path.parent) if path.parent != path else None,
                "entries": entries,
            })
        except (OSError, ValueError) as exc:
            self._json_response({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    handler_class.do_GET = do_get
    handler_class._filesystem_browse = filesystem_browse

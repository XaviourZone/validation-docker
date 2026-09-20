"""Web Console extension for operator-managed reference-data inputs."""

import json
import os
import tempfile
from email import policy
from email.parser import BytesParser
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlparse

DEFAULT_DATABASE_CONFIG = "Validation/Database/config/database.yaml"
DEFAULT_BROWSE_ROOT = "runtime/reference"


def _atomic_yaml(path: Path, data):
    import yaml
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


def _resolve_named_dir(parent: Path, names):
    wanted = {str(name).casefold() for name in names}
    if not parent.is_dir():
        return None
    for child in parent.iterdir():
        if child.is_dir() and child.name.casefold() in wanted:
            return child.resolve()
    return None


def _validate_folder(path: str, required_subdirs=()):
    folder = Path(path).expanduser().resolve()
    if not folder.exists() or not folder.is_dir():
        raise ValueError(f"Directory does not exist: {folder}")
    if not os.access(folder, os.R_OK | os.X_OK):
        raise ValueError(f"Directory is not readable: {folder}")

    children = {}
    for key, names in required_subdirs:
        child = _resolve_named_dir(folder, names)
        if child is None:
            raise ValueError(
                f"Required {key} folder not found inside {folder}: {', '.join(names)}"
            )
        if not os.access(child, os.R_OK | os.X_OK):
            raise ValueError(f"{key} folder is not readable: {child}")
        children[key] = str(child)

    return folder, children


def _read_multipart(handler):
    content_type = handler.headers.get("Content-Type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise ValueError("Expected multipart/form-data upload")

    length = int(handler.headers.get("Content-Length", 0))
    if length <= 0:
        raise ValueError("Upload body is empty")

    max_bytes = int(
        os.environ.get("VALIDATION_MAX_UPLOAD_BYTES", str(250 * 1024 * 1024))
    )
    if length > max_bytes:
        raise ValueError(
            f"Upload exceeds maximum size of {max_bytes // (1024 * 1024)} MB"
        )

    body = handler.rfile.read(length)
    envelope = (
        f"Content-Type: {content_type}\r\n"
        "MIME-Version: 1.0\r\n"
        "\r\n"
    ).encode("utf-8") + body

    message = BytesParser(policy=policy.default).parsebytes(envelope)
    if not message.is_multipart():
        raise ValueError("Malformed multipart upload")

    parts = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        if name:
            parts[name] = {
                "filename": filename,
                "data": part.get_payload(decode=True) or b"",
            }
    return parts


def install_database_admin_extension(handler_class, workspace_root, service_controller, logger):
    if getattr(handler_class, "_database_admin_extension_installed", False):
        return

    handler_class._database_admin_extension_installed = True

    configured = os.environ.get("VALIDATION_DATABASE_CONFIG")
    handler_class.database_admin_config_path = (
        Path(configured)
        if configured
        else Path(workspace_root) / DEFAULT_DATABASE_CONFIG
    )

    browse_root = os.environ.get(
        "VALIDATION_DATABASE_BROWSE_ROOT",
        str(Path(workspace_root) / DEFAULT_BROWSE_ROOT),
    )
    handler_class.database_admin_browse_root = Path(browse_root).expanduser().resolve()
    handler_class.database_admin_service_controller = service_controller
    handler_class.database_admin_logger = logger

    original_get = handler_class.do_GET
    original_post = handler_class.do_POST

    def do_get(self):
        path = urlparse(self.path).path

        if path == "/api/database/filesystem/browse":
            self._database_browse()
            return
        if path == "/api/database/wrs/config":
            self._database_reference_config("wrs")
            return
        if path == "/api/database/pans/config":
            self._database_reference_config("pans")
            return
        if path == "/api/database/nsc/config":
            self._database_reference_config("nsc")
            return

        return original_get(self)

    def do_post(self):
        path = urlparse(self.path).path

        if path == "/api/database/wrs/config":
            self._database_save_reference_folder("wrs")
            return
        if path == "/api/database/pans/config":
            self._database_save_reference_folder("pans")
            return
        if path == "/api/database/nsc/upload":
            self._database_upload_nsc()
            return

        return original_post(self)

    def _browse_roots(self):
        root = self.database_admin_browse_root
        return [root] if root.exists() and root.is_dir() else [Path.cwd()]

    def _database_browse(self):
        query = parse_qs(urlparse(self.path).query)
        raw = (query.get("path") or [""])[0].strip()

        try:
            if not raw:
                roots = self._browse_roots()
                self._json_response(
                    {
                        "roots": [
                            {
                                "name": str(root),
                                "path": str(root),
                                "readable": os.access(root, os.R_OK | os.X_OK),
                            }
                            for root in roots
                        ]
                    }
                )
                return

            path = Path(raw).expanduser().resolve()
            root = self.database_admin_browse_root
            try:
                path.relative_to(root)
            except ValueError:
                raise ValueError(
                    f"Folder is outside the permitted reference-data root: {root}"
                )

            if not path.exists() or not path.is_dir():
                self._json_response(
                    {"error": f"Directory does not exist: {path}"},
                    status=HTTPStatus.NOT_FOUND,
                )
                return

            entries = []
            for child in sorted(
                path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())
            ):
                if not child.is_dir() or child.name.startswith("."):
                    continue
                try:
                    readable = os.access(child, os.R_OK | os.X_OK)
                except OSError:
                    readable = False
                entries.append(
                    {
                        "name": child.name,
                        "path": str(child),
                        "readable": readable,
                    }
                )

            self._json_response(
                {
                    "path": str(path),
                    "parent": str(path.parent) if path.parent != path else None,
                    "entries": entries,
                }
            )
        except Exception as exc:
            self._json_response({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def _read_database_config(self):
        import yaml

        if not self.database_admin_config_path.exists():
            return {}
        return yaml.safe_load(
            self.database_admin_config_path.read_text(encoding="utf-8")
        ) or {}

    def _database_reference_config(self, kind):
        cfg = self._read_database_config()
        entry = (cfg.get("imports", {}) or {}).get(kind, {}) or {}
        raw = str(entry.get("input_dir", ""))
        payload = {"input_dir": raw}

        if kind == "wrs":
            root = Path(raw).expanduser()
            if not root.is_absolute():
                root = (self.database_admin_config_path.parent / root).resolve()
            else:
                root = root.resolve()

            datasets = _resolve_named_dir(root, ("Datasets", "datasets"))
            decode = _resolve_named_dir(
                root, ("Decode files", "decode", "Decode Files", "decode files")
            )
            payload.update(
                {
                    "datasets_dir": str(datasets) if datasets else "",
                    "decode_dir": str(decode) if decode else "",
                    "valid_structure": bool(datasets and decode),
                }
            )

        elif kind == "pans":
            payload.update(
                {
                    "poll_interval_seconds": float(
                        entry.get("poll_interval_seconds", 2.0)
                    ),
                    "stability_seconds": float(
                        entry.get("stability_seconds", 1.0)
                    ),
                }
            )

        elif kind == "nsc":
            root = Path(raw).expanduser()
            payload.update(
                {
                    "east_dir": str(root / "EAST"),
                    "west_dir": str(root / "WEST"),
                }
            )

        self._json_response(payload)

    def _save_config_entry(self, kind, folder):
        cfg = self._read_database_config()
        entry = cfg.setdefault("imports", {}).setdefault(kind, {})
        entry["input_dir"] = folder

        if kind == "wrs":
            entry.setdefault("staging_db", "runtime/reference/wrs_staging.db")
            entry.setdefault("batch_size", 10000)
        elif kind == "pans":
            entry.setdefault("poll_interval_seconds", 2.0)
            entry.setdefault("stability_seconds", 1.0)
            entry.setdefault("batch_size", 500)
        elif kind == "nsc":
            entry.setdefault("staging_db", "runtime/reference/nsc_staging.db")
            entry.setdefault("batch_size", 5000)

        _atomic_yaml(self.database_admin_config_path, cfg)

    def _database_save_reference_folder(self, kind):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            folder = str(body.get("input_dir", "")).strip()

            if not folder:
                raise ValueError(f"{kind.upper()} source folder is required")

            if kind == "wrs":
                path, children = _validate_folder(
                    folder,
                    (
                        ("Datasets", ("Datasets", "datasets")),
                        (
                            "Decode files",
                            ("Decode files", "decode", "Decode Files", "decode files"),
                        ),
                    ),
                )
            else:
                path, children = _validate_folder(folder)

            self._save_config_entry(kind, str(path))

            self._json_response(
                {
                    "success": True,
                    "kind": kind,
                    "input_dir": str(path),
                    "children": children,
                    "message": f"{kind.upper()} source folder saved",
                }
            )
        except Exception as exc:
            self._json_response(
                {"success": False, "error": str(exc)},
                status=HTTPStatus.UNPROCESSABLE_ENTITY,
            )

    def _database_upload_nsc(self):
        try:
            parts = _read_multipart(self)
            uploads = {}

            for region in ("east", "west"):
                part = parts.get(region)
                if not part or not part.get("filename"):
                    continue

                filename = Path(part["filename"]).name
                suffix = Path(filename).suffix.lower()

                if suffix not in (".xlsx", ".csv"):
                    raise ValueError(
                        f"NSC {region.upper()} accepts only .xlsx or .csv files"
                    )

                data = part["data"]
                if not data:
                    raise ValueError(f"NSC {region.upper()} file is empty")

                uploads[region] = (suffix, data)

            if not uploads:
                raise ValueError("Select at least one NSC EAST or NSC WEST file")

            cfg = self._read_database_config()
            root_value = str(
                (cfg.get("imports", {}) or {})
                .get("nsc", {})
                .get("input_dir", "")
            ).strip()

            root = (
                Path(root_value).expanduser().resolve()
                if root_value
                else self.database_admin_browse_root / "NSC" / "RAW_DATA"
            )

            east_dir = root / "EAST"
            west_dir = root / "WEST"
            east_dir.mkdir(parents=True, exist_ok=True)
            west_dir.mkdir(parents=True, exist_ok=True)

            saved = {}
            for region, (suffix, data) in uploads.items():
                target_dir = east_dir if region == "east" else west_dir
                archive_dir = root / "_archive" / region.upper()
                archive_dir.mkdir(parents=True, exist_ok=True)

                for old in target_dir.iterdir():
                    if old.is_file() and old.suffix.lower() in (
                        ".xlsx",
                        ".xls",
                        ".csv",
                    ):
                        stamp = __import__("datetime").datetime.now().strftime(
                            "%Y%m%d_%H%M%S"
                        )
                        old.replace(archive_dir / f"{stamp}_{old.name}")

                target = target_dir / f"NSC_{region.upper()}{suffix}"
                fd, temp_name = tempfile.mkstemp(
                    prefix=target.stem + ".",
                    suffix=target.suffix,
                    dir=str(target_dir),
                )
                try:
                    with os.fdopen(fd, "wb") as fh:
                        fh.write(data)
                    os.replace(temp_name, target)
                finally:
                    try:
                        os.unlink(temp_name)
                    except FileNotFoundError:
                        pass

                saved[region] = str(target)

            database_client = getattr(self, "database_client", None)
            refresh = database_client.refresh_nsc() if database_client else None

            self._json_response(
                {
                    "success": True,
                    "saved": saved,
                    "refresh": refresh,
                    "message": "NSC files uploaded; database update started",
                }
            )
        except Exception as exc:
            self._json_response(
                {"success": False, "error": str(exc)},
                status=HTTPStatus.UNPROCESSABLE_ENTITY,
            )

    handler_class.do_GET = do_get
    handler_class.do_POST = do_post
    handler_class._database_browse = _database_browse
    handler_class._database_reference_config = _database_reference_config
    handler_class._database_save_reference_folder = _database_save_reference_folder
    handler_class._database_upload_nsc = _database_upload_nsc

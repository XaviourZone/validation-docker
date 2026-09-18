"""Local credential store for Forwarder destinations.

Secrets are stored outside YAML configuration and are never returned by the API.
The file is created with owner-only permissions on POSIX systems.
"""

import json
import os
import tempfile
from pathlib import Path
from threading import RLock


class SecretStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def _read(self):
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=str(self.path.parent))
        try:
            if os.name != "nt":
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
                fh.write("\n")
            os.replace(tmp_name, self.path)
            if os.name != "nt":
                os.chmod(self.path, 0o600)
        finally:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass

    def get(self, destination: str):
        with self._lock:
            data = self._read()
            value = data.get(destination)
            # Backward compatibility for the pre-Web-Console destination name.
            # This lets an existing offline installation continue delivering after
            # the operational destination was renamed to D-DIODE-01.
            if not value and destination == "D-DIODE-01":
                value = data.get("downstream")
            return value

    def has(self, destination: str) -> bool:
        value = self.get(destination)
        return isinstance(value, str) and bool(value)

    def set(self, destination: str, password: str):
        if not isinstance(password, str) or not password:
            raise ValueError("password must not be empty")
        with self._lock:
            data = self._read()
            data[destination] = password
            self._write(data)

    def delete(self, destination: str):
        with self._lock:
            data = self._read()
            if destination in data:
                del data[destination]
                self._write(data)

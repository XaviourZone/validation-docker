import hashlib
import logging
import threading
import time
from pathlib import Path

import yaml

from .config import ForwarderConfig, load_config
from .secrets import SecretStore
from .state import DeliveryState
from .transport import transport_for


class ForwarderService:
    def __init__(self, config: ForwarderConfig, logger=None):
        self.config = config
        self.log = logger or logging.getLogger("forwarder")
        self.state = DeliveryState(config.spool.state_db)
        self.running = False
        self._thread = None
        self._lock = threading.RLock()
        self._last_error = None
        self._last_success = None
        for path in (config.spool.input_dir, config.spool.archive_dir, config.spool.failed_dir):
            path.mkdir(parents=True, exist_ok=True)

    def start(self):
        with self._lock:
            if self.running:
                return
            self.running = True
            self._thread = threading.Thread(target=self._loop, name="ForwarderWorker", daemon=True)
            self._thread.start()
        self.log.info("Data Forwarder started")

    def stop(self):
        with self._lock:
            self.running = False
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5)
        self.log.info("Data Forwarder stopped")

    def reload_config(self):
        root = self.config.config_path.parents[3]
        new_config = load_config(self.config.config_path, root)
        with self._lock:
            old_state_path = self.config.spool.state_db
            self.config = new_config
            if new_config.spool.state_db != old_state_path:
                self.state = DeliveryState(new_config.spool.state_db)
            for path in (new_config.spool.input_dir, new_config.spool.archive_dir, new_config.spool.failed_dir):
                path.mkdir(parents=True, exist_ok=True)
        self.log.info("Data Forwarder configuration reloaded")

    def _loop(self):
        while self.running:
            try:
                self.process_once()
            except Exception:
                self.log.exception("Unhandled Forwarder loop error")
            time.sleep(max(0.1, self.config.spool.poll_interval_seconds))

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _output_id(path: Path, sha256: str) -> str:
        return f"{path.stem}:{sha256[:16]}"

    def process_once(self):
        files = sorted(self.config.spool.input_dir.glob("*.xml"))
        if not files:
            return
        enabled = [d for d in self.config.destinations.values() if d.enabled]
        if not enabled:
            return
        for path in files:
            if not self.running:
                break
            self._process_file(path, enabled)

    def _process_file(self, path: Path, destinations):
        try:
            sha = self._sha256(path)
        except OSError as exc:
            self._last_error = str(exc)
            self.log.error("Cannot read Forwarder output %s: %s", path, exc)
            return
        output_id = self._output_id(path, sha)
        all_delivered = True
        for dest in destinations:
            current = self.state.get(output_id, dest.name)
            if current and current["state"] == "DELIVERED" and current["sha256"] == sha:
                continue
            self.state.ensure(output_id, dest.name, sha, path.name)
            ok = self._deliver_with_retry(path, output_id, dest)
            all_delivered = all_delivered and ok
        if all_delivered:
            archive_target = self.config.spool.archive_dir / path.name
            if archive_target.exists():
                archive_target = self.config.spool.archive_dir / f"{path.stem}_{sha[:12]}{path.suffix}"
            try:
                path.replace(archive_target)
            except OSError as exc:
                self._last_error = str(exc)
                self.log.error("Delivered but could not archive %s: %s", path, exc)

    def _deliver_with_retry(self, path, output_id, destination):
        transport = transport_for(destination)
        delay = self.config.retry.initial_delay_seconds
        for attempt in range(1, self.config.retry.max_attempts + 1):
            self.state.mark(output_id, destination.name, "TRANSFERRING", attempts=attempt)
            try:
                transport.deliver(path, destination)
                self.state.mark(output_id, destination.name, "DELIVERED", attempts=attempt)
                self._last_success = time.time()
                self._last_error = None
                self.log.info("Delivered %s to %s", path.name, destination.name)
                return True
            except Exception as exc:
                last_error = str(exc)
                self._last_error = last_error
                if attempt < self.config.retry.max_attempts:
                    self.state.mark(output_id, destination.name, "RETRYING", attempts=attempt, error=last_error)
                    time.sleep(delay)
                    delay = min(self.config.retry.max_delay_seconds, delay * self.config.retry.multiplier)
                else:
                    self.state.mark(output_id, destination.name, "FAILED", attempts=attempt, error=last_error)
                    self.log.error("Delivery failed for %s to %s: %s", path.name, destination.name, last_error)
        return False

    def destinations_view(self):
        secrets = SecretStore(self.config.spool.secret_file)
        return [{
            "name": d.name,
            "enabled": d.enabled,
            "protocol": d.protocol,
            "host": d.host,
            "port": d.port,
            "remote_path": d.remote_path,
            "username": d.username,
            "private_key_file": d.private_key_file,
            "password_configured": secrets.has(d.name),
            "connect_timeout_seconds": d.connect_timeout_seconds,
            "verify_remote_size": d.verify_remote_size,
        } for d in self.config.destinations.values()]

    def save_destination(self, payload):
        name = str(payload.get("name", "")).strip()
        if not name or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for ch in name):
            raise ValueError("Destination name must contain only letters, numbers, '_' or '-'")
        protocol = str(payload.get("protocol", "sftp")).lower()
        if protocol not in {"sftp", "filesystem"}:
            raise ValueError("Unsupported protocol")
        enabled = bool(payload.get("enabled", False))
        host = str(payload.get("host", "")).strip()
        port = int(payload.get("port", 22 if protocol == "sftp" else 1))
        remote_path = str(payload.get("remote_path", "")).strip()
        username = str(payload.get("username", "")).strip()
        private_key_file = str(payload.get("private_key_file", "")).strip()
        if protocol == "sftp" and (not host or not remote_path or not username):
            raise ValueError("SFTP requires destination host, remote path and username")
        if port < 1 or port > 65535:
            raise ValueError("Port must be between 1 and 65535")
        with self._lock:
            raw = yaml.safe_load(self.config.config_path.read_text(encoding="utf-8")) or {}
            destinations = raw.setdefault("destinations", {})
            old = destinations.get(name, {}) or {}
            destinations[name] = {
                "enabled": enabled,
                "protocol": protocol,
                "host": host,
                "port": port,
                "remote_path": remote_path,
                "username": username,
                "private_key_file": private_key_file,
                "connect_timeout_seconds": int(payload.get("connect_timeout_seconds", old.get("connect_timeout_seconds", 10))),
                "verify_remote_size": bool(payload.get("verify_remote_size", old.get("verify_remote_size", True))),
            }
            tmp = self.config.config_path.with_suffix(self.config.config_path.suffix + ".tmp")
            tmp.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
            tmp.replace(self.config.config_path)
            password = payload.get("password")
            if password:
                SecretStore(self.config.spool.secret_file).set(name, str(password))
            self.reload_config()
        return {"success": True, "destination": name}

    def delete_destination(self, name):
        with self._lock:
            if name not in self.config.destinations:
                raise KeyError(f"Destination '{name}' not found")
            raw = yaml.safe_load(self.config.config_path.read_text(encoding="utf-8")) or {}
            raw.setdefault("destinations", {}).pop(name, None)
            tmp = self.config.config_path.with_suffix(self.config.config_path.suffix + ".tmp")
            tmp.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
            tmp.replace(self.config.config_path)
            SecretStore(self.config.spool.secret_file).delete(name)
            self.reload_config()
        return {"success": True, "destination": name}

    def test_destination(self, name):
        dest = self.config.destinations.get(name)
        if not dest:
            raise KeyError(f"Destination '{name}' not found")
        transport_for(dest).test_connection(dest)
        return {"success": True, "destination": name, "message": "Destination connection/path test succeeded"}

    def metrics(self):
        counts = self.state.counts()
        pending = len(list(self.config.spool.input_dir.glob("*.xml")))
        return {
            "pending_files": pending,
            "states": counts,
            "destinations": self.destinations_view(),
            "last_error": self._last_error,
            "last_success_epoch": self._last_success,
        }

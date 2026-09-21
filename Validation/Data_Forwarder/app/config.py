from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict
import os
import yaml


@dataclass
class DestinationConfig:
    name: str
    enabled: bool = False
    protocol: str = "filesystem"
    host: str = ""
    port: int = 0
    remote_path: str = ""
    username: str = ""
    private_key_file: str = ""
    password_file: Path = Path("")
    connect_timeout_seconds: int = 10
    verify_remote_size: bool = True


@dataclass
class RetryConfig:
    max_attempts: int = 5
    initial_delay_seconds: float = 2.0
    max_delay_seconds: float = 60.0
    multiplier: float = 2.0


@dataclass
class SpoolConfig:
    input_dir: Path
    archive_dir: Path
    failed_dir: Path
    state_db: Path
    secret_file: Path
    poll_interval_seconds: float = 1.0
    claim_timeout_seconds: int = 300


@dataclass
class ForwarderConfig:
    http_host: str
    http_port: int
    config_path: Path
    spool: SpoolConfig
    retry: RetryConfig
    destinations: Dict[str, DestinationConfig] = field(default_factory=dict)
    log_level: str = "INFO"


def _path(root: Path, value: str) -> Path:
    p = Path(os.path.expandvars(value)).expanduser()
    return p if p.is_absolute() else root / p


def _filesystem_destination_path(root: Path, value: str) -> Path:
    """Resolve a host-selected local destination inside the Forwarder container."""
    p = Path(os.path.expandvars(value)).expanduser()
    if not p.is_absolute():
        return root / p

    host_root = os.environ.get("VALIDATION_HOST_FILESYSTEM_ROOT", "").strip()
    if host_root:
        return Path(host_root) / str(p).lstrip("/\\")
    return p


def load_config(path: Path, root: Path) -> ForwarderConfig:
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    server = raw.get("server", {})
    spool_raw = raw.get("spool", {})
    retry_raw = raw.get("retry", {})
    secret_file = _path(root, spool_raw.get("secret_file", "Validation/Data_Forwarder/state/forwarder_secrets.json"))

    spool = SpoolConfig(
        input_dir=_path(root, spool_raw.get("input_dir", "spool/pending")),
        archive_dir=_path(root, spool_raw.get("archive_dir", "spool/delivered")),
        failed_dir=_path(root, spool_raw.get("failed_dir", "spool/failed")),
        state_db=_path(root, spool_raw.get("state_db", "state/forwarder.db")),
        secret_file=secret_file,
        poll_interval_seconds=float(spool_raw.get("poll_interval_seconds", 1)),
        claim_timeout_seconds=int(spool_raw.get("claim_timeout_seconds", 300)),
    )
    retry = RetryConfig(
        max_attempts=int(retry_raw.get("max_attempts", 5)),
        initial_delay_seconds=float(retry_raw.get("initial_delay_seconds", 2)),
        max_delay_seconds=float(retry_raw.get("max_delay_seconds", 60)),
        multiplier=float(retry_raw.get("multiplier", 2)),
    )
    destinations = {}
    for name, value in (raw.get("destinations", {}) or {}).items():
        value = value or {}
        protocol = str(value.get("protocol", "filesystem")).lower()
        remote_path = str(value.get("remote_path", ""))
        if protocol == "filesystem":
            remote_path = str(_filesystem_destination_path(root, remote_path))
        destinations[name] = DestinationConfig(
            name=name,
            enabled=bool(value.get("enabled", False)),
            protocol=protocol,
            host=str(value.get("host", "")),
            port=int(value.get("port", 0)),
            remote_path=remote_path,
            username=str(value.get("username", "")),
            private_key_file=str(value.get("private_key_file", "")),
            password_file=secret_file,
            connect_timeout_seconds=int(value.get("connect_timeout_seconds", 10)),
            verify_remote_size=bool(value.get("verify_remote_size", True)),
        )
    return ForwarderConfig(
        http_host=str(server.get("http_host", "127.0.0.1")),
        http_port=int(server.get("http_port", 8082)),
        config_path=path,
        spool=spool,
        retry=retry,
        destinations=destinations,
        log_level=str((raw.get("logging", {}) or {}).get("level", "INFO")),
    )

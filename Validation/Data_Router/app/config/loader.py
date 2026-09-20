"""Configuration loader and validator for Validation Data Router."""

from pathlib import Path
from typing import Any, Dict, List, Tuple, Union
import yaml

from .models import (
    DataInflowConfig,
    FileSourceConfig,
    TCPSourceConfig,
    FramingType,
    MonitoringConfig,
    ParserDestinationConfig,
    QueueConfig,
    RetryConfig,
    RouterConfig,
    SourceConfig,
    SourceType,
    StateConfig,
)


class ConfigurationError(Exception):
    """Raised when configuration validation fails."""
    pass


def parse_raw_dict(raw: Dict[str, Any]) -> RouterConfig:
    """Parse raw dictionary into structured RouterConfig dataclasses."""
    # 1. Data Inflow
    inflow_dict = raw.get("data_inflow", {})
    inflow_cfg = DataInflowConfig(base_dir=inflow_dict.get("base_dir", "DATA_INFLOW"))

    # 2. Parser Destinations
    parser_destinations: Dict[str, ParserDestinationConfig] = {}
    for name, dest_dict in raw.get("parser_destinations", {}).items():
        parser_destinations[name] = ParserDestinationConfig(
            name=name,
            host=dest_dict.get("host", "127.0.0.1"),
            port=int(dest_dict.get("port", 10001)),
            framing=dest_dict.get("framing", "ndjson"),
            timeout_seconds=float(dest_dict.get("timeout_seconds", 5.0)),
            keep_alive=bool(dest_dict.get("keep_alive", True)),
        )

    # 3. Sources
    sources: Dict[str, SourceConfig] = {}
    for src_name, src_dict in raw.get("sources", {}).items():
        stype = src_dict.get("type", "").lower()
        parser_name = src_dict.get("parser", "")
        enabled = bool(src_dict.get("enabled", True))

        if stype == SourceType.FILE.value:
            sources[src_name] = FileSourceConfig(
                name=src_name,
                type=SourceType.FILE,
                parser=parser_name,
                enabled=enabled,
                folder=src_dict.get("folder", src_name),
                poll_interval_seconds=float(src_dict.get("poll_interval_seconds", 1.0)),
                stability_window_seconds=float(src_dict.get("stability_window_seconds", 1.0)),
                file_patterns=src_dict.get("file_patterns", ["*.csv", "*.txt", "*"]),
                preserve_file=bool(src_dict.get("preserve_file", False)),
                processed_folder=str(src_dict.get("processed_folder", "")),
            )
        elif stype == SourceType.TCP.value:
            framing_val = src_dict.get("framing", "line").lower()
            try:
                framing = FramingType(framing_val)
            except ValueError:
                framing = FramingType.LINE

            sources[src_name] = TCPSourceConfig(
                name=src_name,
                type=SourceType.TCP,
                parser=parser_name,
                enabled=enabled,
                remote_host=src_dict.get("remote_host", "127.0.0.1"),
                remote_port=int(src_dict.get("remote_port", 0)),
                framing=framing,
                delimiter=src_dict.get("delimiter", "\n"),
                max_line_length=int(src_dict.get("max_line_length", 65536)),
                reconnect_initial_delay=float(src_dict.get("reconnect_initial_delay", 2.0)),
                reconnect_max_delay=float(src_dict.get("reconnect_max_delay", 60.0)),
                reconnect_multiplier=float(src_dict.get("reconnect_multiplier", 2.0)),
            )
        else:
            raise ConfigurationError(f"Source '{src_name}' has unknown type '{stype}' (expected 'file' or 'tcp')")

    # 4. Retry
    retry_dict = raw.get("retry", {})
    retry_cfg = RetryConfig(
        max_attempts=int(retry_dict.get("max_attempts", 5)),
        initial_delay_seconds=float(retry_dict.get("initial_delay_seconds", 2.0)),
        max_delay_seconds=float(retry_dict.get("max_delay_seconds", 60.0)),
        backoff_multiplier=float(retry_dict.get("backoff_multiplier", 2.0)),
    )

    # 5. Queue
    queue_dict = raw.get("queue", {})
    queue_cfg = QueueConfig(
        max_size=int(queue_dict.get("max_size", 10000)),
        worker_count=int(queue_dict.get("worker_count", 4)),
        high_watermark_ratio=float(queue_dict.get("high_watermark_ratio", 0.8)),
    )

    # 6. Monitoring
    mon_dict = raw.get("monitoring", {})
    mon_cfg = MonitoringConfig(
        enabled=bool(mon_dict.get("enabled", True)),
        http_host=mon_dict.get("http_host", "127.0.0.1"),
        http_port=int(mon_dict.get("http_port", 8080)),
    )

    # 7. State
    state_dict = raw.get("state", {})
    state_cfg = StateConfig(db_path=state_dict.get("db_path", "state/router_state.db"))

    return RouterConfig(
        data_inflow=inflow_cfg,
        parser_destinations=parser_destinations,
        sources=sources,
        retry=retry_cfg,
        queue=queue_cfg,
        monitoring=mon_cfg,
        state=state_cfg,
    )


def validate_config(config: RouterConfig) -> List[str]:
    """Perform rigorous semantic validation on RouterConfig. Returns list of errors."""
    errors: List[str] = []

    # Validate parser destinations
    if not config.parser_destinations:
        errors.append("No parser destinations configured in 'parser_destinations'.")

    for dest_name, dest in config.parser_destinations.items():
        if not (1 <= dest.port <= 65535):
            errors.append(f"Parser destination '{dest_name}' has invalid port {dest.port} (must be 1-65535).")
        if not dest.host:
            errors.append(f"Parser destination '{dest_name}' has empty host.")

    # Validate sources
    if not config.sources:
        errors.append("No sources configured in 'sources'.")

    for src_name, src in config.sources.items():
        if not src.parser:
            errors.append(f"Source '{src_name}' has no 'parser' specified.")
        elif src.parser not in config.parser_destinations:
            errors.append(
                f"Source '{src_name}' references parser destination '{src.parser}' which does not exist in 'parser_destinations'."
            )

        if isinstance(src, FileSourceConfig):
            if not src.folder:
                errors.append(f"File source '{src_name}' has empty 'folder'.")
            if src.poll_interval_seconds <= 0:
                errors.append(f"File source '{src_name}' poll_interval_seconds must be > 0.")
            if src.stability_window_seconds <= 0:
                errors.append(f"File source '{src_name}' stability_window_seconds must be > 0.")

        elif isinstance(src, TCPSourceConfig):
            if src.enabled:
                if not (1 <= src.remote_port <= 65535):
                    errors.append(
                        f"Enabled TCP source '{src_name}' has invalid remote_port {src.remote_port} (must be 1-65535)."
                    )
                if not src.remote_host or src.remote_host == "CHANGE_ME":
                    errors.append(
                        f"Enabled TCP source '{src_name}' has invalid remote_host '{src.remote_host}'."
                    )

    # Validate retry
    if config.retry.max_attempts < 1:
        errors.append("Retry max_attempts must be at least 1.")
    if config.retry.initial_delay_seconds <= 0:
        errors.append("Retry initial_delay_seconds must be > 0.")
    if config.retry.max_delay_seconds < config.retry.initial_delay_seconds:
        errors.append("Retry max_delay_seconds must be >= initial_delay_seconds.")

    # Validate queue
    if config.queue.max_size < 10:
        errors.append("Queue max_size must be at least 10.")
    if config.queue.worker_count < 1:
        errors.append("Queue worker_count must be at least 1.")

    return errors


def load_config(config_path: Union[str, Path]) -> RouterConfig:
    """Load configuration from a YAML file, validate, and return RouterConfig."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path.resolve()}")

    with open(path, "r", encoding="utf-8") as f:
        try:
            raw = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            raise ConfigurationError(f"Failed to parse YAML configuration: {exc}") from exc

    config = parse_raw_dict(raw)
    errors = validate_config(config)
    if errors:
        error_msg = "\n  - " + "\n  - ".join(errors)
        raise ConfigurationError(f"Configuration validation failed with {len(errors)} error(s):{error_msg}")

    return config

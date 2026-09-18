"""Structured operational logger for Validation Data Router."""

import logging
import logging.config
import os
from pathlib import Path
from typing import Any, Optional
import yaml


ROUTER_LOGGER_NAME = "router"


def setup_logging(config_path: Optional[str] = None, base_dir: Optional[Path] = None) -> logging.Logger:
    """Initialize structured rotating logging from YAML or safe defaults."""
    if base_dir is None:
        base_dir = Path.cwd()

    logs_dir = base_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    loaded = False
    if config_path:
        cfg_file = Path(config_path)
        if cfg_file.exists():
            try:
                with open(cfg_file, "r", encoding="utf-8") as f:
                    config_dict = yaml.safe_load(f)
                    
                    # Update file handler path to be relative to logs_dir or base_dir
                    for h_name, h_dict in config_dict.get("handlers", {}).items():
                        if "filename" in h_dict:
                            log_path = base_dir / h_dict["filename"]
                            log_path.parent.mkdir(parents=True, exist_ok=True)
                            h_dict["filename"] = str(log_path)
                    
                    logging.config.dictConfig(config_dict)
                    loaded = True
            except Exception as e:
                print(f"[WARN] Failed to load logging config from {cfg_file}: {e}. Falling back to default.")

    if not loaded:
        # Default robust rotating file handler + console handler
        logger = logging.getLogger(ROUTER_LOGGER_NAME)
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()

        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        log_file = logs_dir / "router.log"
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            filename=str(log_file),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logging.getLogger(ROUTER_LOGGER_NAME)


def get_router_logger() -> logging.Logger:
    """Get the standard Data Router logger."""
    return logging.getLogger(ROUTER_LOGGER_NAME)


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    source: Optional[str] = None,
    message_id: Optional[str] = None,
    filename: Optional[str] = None,
    destination: Optional[str] = None,
    error: Optional[Any] = None,
    **kwargs: Any
) -> None:
    """Log an operational event with structured key=value formatting."""
    parts = []
    if source:
        parts.append(f"source={source}")
    if filename:
        parts.append(f"file={filename}")
    if message_id:
        parts.append(f"message_id={message_id}")
    if destination:
        parts.append(f"destination={destination}")
    parts.append(f"event={event}")
    if error:
        parts.append(f"error=\"{error}\"")

    for k, v in kwargs.items():
        if v is not None:
            parts.append(f"{k}={v}")

    msg = " ".join(parts)
    logger.log(level, msg)

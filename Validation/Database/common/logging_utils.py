"""
common/logging_utils.py - Structured logging setup for all database importers.
"""

import logging
import os
from pathlib import Path


def setup_logger(name: str, log_dir: Path = None, level=logging.INFO) -> logging.Logger:
    """
    Configure and return a named logger.

    If log_dir is provided, log to <log_dir>/<name>.log as well as stdout.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if logger.handlers:
        return logger  # already configured

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # Console handler
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # File handler
    if log_dir:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{name}.log"
        fh = logging.FileHandler(str(log_file), encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger

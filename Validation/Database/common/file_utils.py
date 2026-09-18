"""
common/file_utils.py - File stability detection and SHA-256 hashing.
Used by WRS, PANS and NSC importers.
"""

import hashlib
import os
import time
from pathlib import Path


def sha256_file(path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def is_file_stable(path, stability_seconds=1.0, poll_interval=0.25) -> bool:
    """
    Return True when a file has not changed size for stability_seconds.
    Gives up after stability_seconds * 12 iterations.
    """
    path = Path(path)
    if not path.exists():
        return False

    deadline = time.monotonic() + stability_seconds * 12
    last_size = -1
    stable_since = None

    while time.monotonic() < deadline:
        try:
            size = path.stat().st_size
        except OSError:
            return False

        if size != last_size:
            last_size = size
            stable_since = time.monotonic()
        elif stable_since is not None:
            if time.monotonic() - stable_since >= stability_seconds:
                return True

        time.sleep(poll_interval)

    return False


def discover_files(directory, extensions=None) -> list:
    """
    Return sorted list of Path objects in directory matching extensions.
    extensions: list of lowercase extensions including dot, e.g. [".csv", ".xml"]
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []
    result = []
    for p in sorted(directory.iterdir()):
        if p.is_file():
            if extensions is None or p.suffix.lower() in extensions:
                result.append(p)
    return result

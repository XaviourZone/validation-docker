"""Hashing and deterministic message-ID helpers for Data Router files/TCP messages."""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path


def compute_file_hash(file_path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Return SHA-256 of the file contents without loading the whole file into RAM."""
    digest = hashlib.sha256()
    with open(file_path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def generate_file_message_id(
    source: str,
    filename: str,
    file_size: int,
    mtime: float,
    file_hash: str,
) -> str:
    """Generate a stable file message ID from source and file identity metadata."""
    identity = f"{source.lower()}|{filename}|{file_size}|{mtime:.6f}|{file_hash}"
    token = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    return f"file:{source.lower()}:{token}"


def generate_tcp_message_id(source: str) -> str:
    """Generate a unique message ID for each TCP-delivered frame."""
    entropy = f"{source.lower()}|{time.time_ns()}|{os.getpid()}"
    token = hashlib.sha256(entropy.encode("utf-8")).hexdigest()[:32]
    return f"tcp:{source.lower()}:{token}"

"""Filesystem utilities for safe file access, stability checking, and metadata."""

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple


@dataclass(frozen=True)
class FileSnapshot:
    """Snapshot of file metadata at a point in time."""
    path: Path
    size: int
    mtime: float
    accessible: bool
    captured_at: float = 0.0


def get_file_snapshot(file_path: Path) -> Optional[FileSnapshot]:
    """Capture file size, mtime, and check if file is accessible for reading."""
    try:
        stat_result = file_path.stat()
        accessible = is_file_readable(file_path)
        return FileSnapshot(
            path=file_path,
            size=stat_result.st_size,
            mtime=stat_result.st_mtime,
            accessible=accessible,
            captured_at=time.time(),
        )
    except (FileNotFoundError, PermissionError, OSError):
        return None


def is_file_readable(file_path: Path) -> bool:
    """Test whether a file can be opened for reading without error or lock contention."""
    try:
        with open(file_path, "rb") as f:
            f.read(1)
        return True
    except (PermissionError, OSError):
        return False


def is_file_stable(
    file_path: Path,
    previous_snapshot: Optional[FileSnapshot],
    min_stability_seconds: float = 1.0
) -> Tuple[bool, Optional[FileSnapshot]]:
    """Determine if a file has finished being written/copied.
    
    A file is deemed stable if:
    1. It exists and is readable.
    2. Its size and modification time match previous_snapshot.
    3. The elapsed observation time since previous_snapshot is at least min_stability_seconds.
    4. Its size is greater than 0 (or empty files if allowed).
    """
    current = get_file_snapshot(file_path)
    if current is None or not current.accessible:
        return False, None

    if previous_snapshot is None:
        return False, current

    # If size or mtime changed, the file is still being modified
    if current.size != previous_snapshot.size or current.mtime != previous_snapshot.mtime:
        return False, current

    # Check elapsed observation time
    elapsed = current.captured_at - previous_snapshot.captured_at
    if elapsed >= min_stability_seconds:
        return True, current

    # Keep original previous_snapshot's captured_at so elapsed time accumulates
    accumulated_snapshot = FileSnapshot(
        path=current.path,
        size=current.size,
        mtime=current.mtime,
        accessible=current.accessible,
        captured_at=previous_snapshot.captured_at,
    )
    return False, accumulated_snapshot


def ensure_directory(path: Path) -> Path:
    """Ensure directory exists, create if not present."""
    path.mkdir(parents=True, exist_ok=True)
    return path

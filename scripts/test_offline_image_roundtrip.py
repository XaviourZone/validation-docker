#!/usr/bin/env python3
"""Validate Docker image save/load as an offline deployment round trip."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def run(command: list[str]) -> None:
    print("$ " + " ".join(command))
    subprocess.run(command, check=True)


def main() -> int:
    image = sys.argv[1] if len(sys.argv) > 1 else "validation/parser:dev"

    with tempfile.TemporaryDirectory(prefix="validation-offline-") as tmp:
        bundle = Path(tmp) / "validation-image.tar"
        run(["docker", "image", "inspect", image])
        run(["docker", "save", "--output", str(bundle), image])
        if not bundle.exists() or bundle.stat().st_size == 0:
            raise RuntimeError("Docker save produced no image bundle")
        run(["docker", "load", "--input", str(bundle)])

    print("PASS: offline Docker image save/load round trip")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

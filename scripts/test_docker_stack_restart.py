#!/usr/bin/env python3
"""Smoke-test the deployed Compose stack through restart/recovery.

Builds are performed by the validation gate. This script tags the gate image
as the Compose image, starts Parser/Router/Forwarder/Web, verifies service
endpoints, restarts the service stack, verifies recovery, and always cleans up.
"""

from __future__ import annotations

import os
import subprocess
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = "validation-gate-stack"


def run(*args: str) -> None:
    subprocess.run(
        ["docker", "compose", "--project-name", PROJECT, *args],
        cwd=ROOT,
        check=True,
        env={**os.environ, "COMPOSE_PROJECT_NAME": PROJECT},
    )


def http_ready(url: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def wait_for(url: str, seconds: int = 45) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if http_ready(url):
            return
        time.sleep(1)
    raise RuntimeError(f"Service did not become ready: {url}")


def main() -> int:
    try:
        subprocess.run(
            ["docker", "tag", "validation/parser:gate", "validation/parser:dev"],
            cwd=ROOT,
            check=True,
        )

        run("up", "-d", "parser", "router", "forwarder", "web")
        wait_for("http://127.0.0.1:8081/health")
        wait_for("http://127.0.0.1:8080/status")
        wait_for("http://127.0.0.1:8082/health")
        wait_for("http://127.0.0.1:8088/")

        run("restart", "parser", "router", "forwarder", "web")
        wait_for("http://127.0.0.1:8081/health")
        wait_for("http://127.0.0.1:8080/status")
        wait_for("http://127.0.0.1:8082/health")
        wait_for("http://127.0.0.1:8088/")

        print("PASS: Docker Compose service restart/recovery")
        return 0
    finally:
        subprocess.run(
            ["docker", "compose", "--project-name", PROJECT, "down", "--remove-orphans"],
            cwd=ROOT,
            env={**os.environ, "COMPOSE_PROJECT_NAME": PROJECT},
            check=False,
        )


if __name__ == "__main__":
    raise SystemExit(main())

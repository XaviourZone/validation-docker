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


def run(*args: str, compose_files=None) -> None:
    command = ["docker", "compose", "--project-name", PROJECT]
    for compose_file in compose_files or []:
        command.extend(["-f", str(compose_file)])
    command.extend(args)
    subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        env={**os.environ, "COMPOSE_PROJECT_NAME": PROJECT},
    )

def write_isolated_port_override() -> Path:
    """Map all host-facing test ports to an isolated high-port range."""
    path = ROOT / ".validation-gate-compose-ports.yml"
    path.write_text(
        """services:
  parser:
    ports:
      - "11001:10001"
      - "11002:10002"
      - "11003:10003"
      - "11004:10004"
      - "11005:10005"
      - "11081:8081"
  router:
    ports:
      - "11080:8080"
  forwarder:
    ports:
      - "11082:8082"
  web:
    ports:
      - "11088:8088"
""",
        encoding="utf-8",
    )
    return path


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
    override = write_isolated_port_override()
    compose_files = [ROOT / "docker-compose.yml", override]
    try:
        subprocess.run(
            ["docker", "tag", "validation/parser:gate", "validation/parser:dev"],
            cwd=ROOT,
            check=True,
        )

        run("up", "-d", "parser", "router", "forwarder", "web", compose_files=compose_files)
        wait_for("http://127.0.0.1:11081/health")
        wait_for("http://127.0.0.1:11080/status")
        wait_for("http://127.0.0.1:11082/health")
        wait_for("http://127.0.0.1:11088/")

        run("restart", "parser", "router", "forwarder", "web", compose_files=compose_files)
        wait_for("http://127.0.0.1:11081/health")
        wait_for("http://127.0.0.1:11080/status")
        wait_for("http://127.0.0.1:11082/health")
        wait_for("http://127.0.0.1:11088/")

        print("PASS: Docker Compose service restart/recovery")
        return 0
    finally:
        subprocess.run(
            [
                "docker", "compose", "--project-name", PROJECT,
                "-f", str(ROOT / "docker-compose.yml"),
                "-f", str(override),
                "down", "--remove-orphans",
            ],
            cwd=ROOT,
            env={**os.environ, "COMPOSE_PROJECT_NAME": PROJECT},
            check=False,
        )
        try:
            override.unlink()
        except FileNotFoundError:
            pass



if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${ROOT}/offline/docker-static"
mkdir -p "${OUT}"

DOCKER_VERSION="24.0.9"
COMPOSE_VERSION="v2.20.2"
DOCKER_URL="https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_VERSION}.tgz"
COMPOSE_URL="https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-x86_64"

echo "=== Validation Offline Docker Bundle Builder ==="
echo "Target: Ubuntu 18.04.3 x86_64 / kernel 5.0.0-23"
echo

if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "ERROR: This bundle targets x86_64." >&2
  exit 1
fi

rm -f "${OUT}/docker-${DOCKER_VERSION}.tgz" "${OUT}/docker-compose-linux-x86_64"

echo "[1/4] Downloading Docker Engine static bundle..."
curl -fL --retry 3 -o "${OUT}/docker-${DOCKER_VERSION}.tgz" "${DOCKER_URL}"

echo "[2/4] Downloading Docker Compose..."
curl -fL --retry 3 -o "${OUT}/docker-compose-linux-x86_64" "${COMPOSE_URL}"

chmod 0644 "${OUT}/docker-${DOCKER_VERSION}.tgz" "${OUT}/docker-compose-linux-x86_64"

echo "[3/4] Writing checksums..."
(
  cd "${OUT}"
  sha256sum docker-${DOCKER_VERSION}.tgz docker-compose-linux-x86_64 > SHA256SUMS
)

echo "[4/4] Bundle contents..."
ls -lh "${OUT}"

echo
echo "Static Docker bundle ready."

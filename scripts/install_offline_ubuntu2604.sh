#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEB_DIR="${ROOT}/offline/docker-debs"
IMAGE_TAR="${ROOT}/offline/images/validation-parser-dev.tar"
BASE_TAR="${ROOT}/offline/images/python-3.14-slim.tar"

echo "=== Validation Offline Production Installer (Ubuntu 26.04) ==="

if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "ERROR: This installer targets x86_64." >&2
  exit 1
fi

if [[ ! -f /etc/os-release ]] || ! grep -q '^VERSION_ID="26.04"$' /etc/os-release; then
  echo "ERROR: This installer targets Ubuntu 26.04." >&2
  . /etc/os-release 2>/dev/null || true
  echo "Detected: ${PRETTY_NAME:-unknown}" >&2
  exit 1
fi

if [[ ! -d "${DEB_DIR}" ]] || ! compgen -G "${DEB_DIR}/*.deb" >/dev/null; then
  echo "ERROR: offline/docker-debs contains no DEB packages." >&2
  exit 1
fi

if [[ ! -f "${IMAGE_TAR}" ]]; then
  echo "ERROR: ${IMAGE_TAR} is missing." >&2
  exit 1
fi

echo "[1/5] Verifying DEB checksums..."
if [[ -f "${DEB_DIR}/SHA256SUMS" ]]; then
  (cd "${DEB_DIR}" && sha256sum -c SHA256SUMS)
fi

echo "[2/5] Installing Docker Engine, Compose and dependencies..."
sudo apt-get install -y "${DEB_DIR}"/*.deb

echo "[3/5] Enabling Docker..."
sudo systemctl enable --now docker

echo "[4/5] Loading Validation image..."
if [[ -f "${BASE_TAR}" ]]; then
  sudo docker load -i "${BASE_TAR}"
fi
sudo docker load -i "${IMAGE_TAR}"

echo "[5/5] Verifying Docker and Validation image..."
docker --version
docker compose version
docker image inspect validation/parser:dev --format '{{.RepoTags}} {{.Id}}'

echo
echo "Next:"
echo "  docker compose up -d --no-build"
echo "  docker compose ps"

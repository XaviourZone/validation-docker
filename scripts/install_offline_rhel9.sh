#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RPM_DIR="${ROOT}/offline/docker-rpms"
IMAGE_TAR="${ROOT}/offline/images/validation-parser-dev.tar"
BASE_TAR="${ROOT}/offline/images/python-3.14-slim.tar"

echo "=== Validation Offline Production Installer ==="

if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "ERROR: This installer targets x86_64." >&2
  exit 1
fi
if [[ ! -f /etc/redhat-release ]] || ! grep -Eq 'release 9([.]|$)' /etc/redhat-release; then
  echo "ERROR: This installer targets RHEL 9." >&2
  cat /etc/redhat-release 2>/dev/null || true
  exit 1
fi
if [[ ! -d "${RPM_DIR}" ]] || ! compgen -G "${RPM_DIR}/*.rpm" >/dev/null; then
  echo "ERROR: offline/docker-rpms contains no RPMs." >&2
  exit 1
fi
if [[ ! -f "${IMAGE_TAR}" ]]; then
  echo "ERROR: ${IMAGE_TAR} is missing." >&2
  exit 1
fi

echo "[1/3] Verifying RPM checksums..."
if [[ -f "${RPM_DIR}/SHA256SUMS" ]]; then
  (cd "${RPM_DIR}" && sha256sum -c SHA256SUMS)
fi

echo "[2/3] Installing Docker Engine and dependencies..."
sudo dnf install -y "${RPM_DIR}"/*.rpm

echo "[3/3] Enabling Docker and loading Validation image..."
sudo systemctl enable --now docker
if [[ -f "${BASE_TAR}" ]]; then
  sudo docker load -i "${BASE_TAR}"
fi
sudo docker load -i "${IMAGE_TAR}"

docker --version
docker compose version
docker image inspect validation/parser:dev --format '{{.RepoTags}} {{.Id}}'

echo
echo "Next:"
echo "  docker compose up -d --no-build"
echo "  docker compose ps"

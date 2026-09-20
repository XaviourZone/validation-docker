#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${ROOT}/offline/docker-rpms"
mkdir -p "${OUT}"

if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "ERROR: This bundle targets RHEL 9 x86_64. Current architecture: $(uname -m)" >&2
  exit 1
fi

if [[ -f /etc/redhat-release ]] && ! grep -Eq 'release 9([.]|$)' /etc/redhat-release; then
  echo "ERROR: Run this downloader on an RHEL 9 build/download machine matching production." >&2
  cat /etc/redhat-release >&2 || true
  exit 1
fi

if ! command -v dnf >/dev/null 2>&1; then
  echo "ERROR: dnf is required. Run this on an internet-connected RHEL 9 x86_64 machine." >&2
  exit 1
fi

echo "[1/4] Installing download helper..."
sudo dnf -y install dnf-plugins-core

echo "[2/4] Enabling Docker CE repository..."
sudo dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo

echo "[3/4] Downloading Docker Engine and all RPM dependencies..."
rm -f "${OUT}"/*.rpm
dnf download --resolve --alldeps --destdir "${OUT}" \
  docker-ce-29.8.1-1.el9 \
  docker-ce-cli-29.8.1-1.el9 \
  containerd.io-2.3.5-1.el9 \
  docker-buildx-plugin-0.37.1-1.el9 \
  docker-compose-plugin-5.5.1-1.el9

echo "[4/4] Writing package manifest..."
(
  cd "${OUT}"
  sha256sum ./*.rpm > SHA256SUMS
)
echo
echo "Docker offline RPM bundle ready:"
echo "  ${OUT}"
ls -lh "${OUT}"

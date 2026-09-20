#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${ROOT}/offline/docker-debs"
mkdir -p "${OUT}"

echo "=== Validation Offline Docker Bundle Builder (Ubuntu 26.04) ==="

if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "ERROR: This bundle targets Ubuntu 26.04 x86_64. Current architecture: $(uname -m)" >&2
  exit 1
fi

if [[ ! -f /etc/os-release ]] || ! grep -q '^VERSION_ID="26.04"$' /etc/os-release; then
  echo "ERROR: Run this downloader on an internet-connected Ubuntu 26.04 x86_64 machine." >&2
  . /etc/os-release 2>/dev/null || true
  echo "Detected: ${PRETTY_NAME:-unknown}" >&2
  exit 1
fi

if ! command -v apt-get >/dev/null 2>&1 || ! command -v apt-cache >/dev/null 2>&1; then
  echo "ERROR: apt-get/apt-cache are required." >&2
  exit 1
fi

echo "[1/4] Refreshing package metadata..."
sudo apt-get update

echo "[2/4] Downloading Docker Engine packages and package dependencies..."
rm -f "${OUT}"/*.deb "${OUT}/SHA256SUMS"

sudo apt-get install -y --download-only --reinstall --download-dir="${OUT}"   docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "[3/4] Verifying required Docker packages are present..."
for pattern in 'docker-ce_[0-9]*_amd64.deb' 'docker-ce-cli_[0-9]*_amd64.deb'                'containerd.io_[0-9]*_amd64.deb' 'docker-buildx-plugin_[0-9]*_amd64.deb'                'docker-compose-plugin_[0-9]*_amd64.deb'; do
  compgen -G "${OUT}/${pattern}" >/dev/null || {
    echo "ERROR: Required package missing: ${pattern}" >&2
    exit 1
  }
done

echo "[4/4] Writing package manifest..."
(
  cd "${OUT}"
  sha256sum ./*.deb > SHA256SUMS
)

echo
echo "Docker offline DEB bundle ready:"
echo "  ${OUT}"
ls -lh "${OUT}"

#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUNDLE="${ROOT}/offline/docker-static"
IMAGE_TAR="${ROOT}/offline/images/validation-parser-dev.tar"

echo "=== Validation Offline Docker Installer (Ubuntu 18.04 x86_64) ==="

if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "ERROR: x86_64 is required." >&2
  exit 1
fi

if [[ ! -f /etc/os-release ]] || ! grep -q '^VERSION_ID="18.04"$' /etc/os-release; then
  echo "ERROR: This installer targets Ubuntu 18.04." >&2
  . /etc/os-release 2>/dev/null || true
  echo "Detected: ${PRETTY_NAME:-unknown}" >&2
  exit 1
fi

KERNEL_MAJOR="$(uname -r | cut -d. -f1)"
KERNEL_MINOR="$(uname -r | cut -d. -f2)"
if (( KERNEL_MAJOR < 3 || (KERNEL_MAJOR == 3 && KERNEL_MINOR < 10) )); then
  echo "ERROR: Linux kernel 3.10 or newer is required." >&2
  exit 1
fi

if [[ ! -f "${BUNDLE}/docker-24.0.2.tgz" || ! -f "${BUNDLE}/docker-compose-linux-x86_64" ]]; then
  echo "ERROR: offline/docker-static bundle is incomplete." >&2
  exit 1
fi

if [[ ! -f "${IMAGE_TAR}" ]]; then
  echo "ERROR: ${IMAGE_TAR} is missing." >&2
  exit 1
fi

echo "[1/6] Verifying bundle checksums..."
if [[ -f "${BUNDLE}/SHA256SUMS" ]]; then
  (cd "${BUNDLE}" && sha256sum -c SHA256SUMS)
fi

echo "[2/6] Installing Docker static binaries..."
sudo tar -xzf "${BUNDLE}/docker-24.0.2.tgz" -C /usr/local/bin --strip-components=1

echo "[3/6] Installing Docker Compose..."
sudo install -Dm755 "${BUNDLE}/docker-compose-linux-x86_64" /usr/local/libexec/docker/cli-plugins/docker-compose
sudo ln -sf /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/bin/docker-compose

echo "[4/6] Installing systemd service..."
sudo tee /etc/systemd/system/docker.service >/dev/null <<'SERVICE'
[Unit]
Description=Docker Application Container Engine
Documentation=https://docs.docker.com
After=network-online.target firewalld.service
Wants=network-online.target
RequiresMountsFor=/var/lib/docker

[Service]
Type=notify
ExecStart=/usr/local/bin/dockerd
ExecReload=/bin/kill -s HUP $MAINPID
TimeoutStartSec=0
Restart=on-failure
RestartSec=5
LimitNOFILE=1048576
LimitNPROC=infinity
LimitCORE=infinity
TasksMax=infinity

[Install]
WantedBy=multi-user.target
SERVICE

sudo systemctl daemon-reload
sudo systemctl enable --now docker

echo "[5/6] Loading Validation image..."
sudo docker load -i "${IMAGE_TAR}"

echo "[6/6] Verifying installation..."
docker --version
docker compose version
docker info >/dev/null
docker image inspect validation/parser:dev --format '{{.RepoTags}} {{.Id}}'

echo
echo "Docker installation complete."
echo "Next:"
echo "  cd ${ROOT}"
echo "  docker compose up -d --no-build"
echo "  docker compose ps"

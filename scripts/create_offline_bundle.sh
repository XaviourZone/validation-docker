#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUNDLE_DIR="${1:-${REPO_DIR}/../validation-offline-ubuntu1804}"
IMAGE="validation/parser:dev"
DOCKER_ENGINE_VERSION="20.10.24"
COMPOSE_VERSION="v2.20.2"

command -v docker >/dev/null 2>&1 || { echo "ERROR: docker is required on the connected build machine."; exit 1; }
docker info >/dev/null 2>&1 || { echo "ERROR: Docker daemon is not available."; exit 1; }
command -v rsync >/dev/null 2>&1 || { echo "ERROR: rsync is required on the connected build machine."; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "ERROR: curl is required on the connected build machine."; exit 1; }

mkdir -p "$BUNDLE_DIR/docker-runtime" "$BUNDLE_DIR/image" "$BUNDLE_DIR/project" "$BUNDLE_DIR/install"

echo "==> Building $IMAGE with all application dependencies..."
docker build -f "$REPO_DIR/docker/Dockerfile" -t "$IMAGE" "$REPO_DIR"

echo "==> Saving application image..."
docker save "$IMAGE" -o "$BUNDLE_DIR/image/validation-parser-dev.tar"

echo "==> Copying project files..."
rsync -a --delete \
  --exclude='.git/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.pytest_cache/' \
  --exclude='.venv/' \
  --exclude='venv/' \
  --exclude='validation-offline-ubuntu1804/' \
  "$REPO_DIR/" "$BUNDLE_DIR/project/"

echo "==> Downloading Docker Engine $DOCKER_ENGINE_VERSION..."
curl -fL "https://download.docker.com/linux/static/stable/x86_64/docker-$DOCKER_ENGINE_VERSION.tgz" \
  -o "$BUNDLE_DIR/docker-runtime/docker-$DOCKER_ENGINE_VERSION.tgz"

echo "==> Downloading Docker Compose $COMPOSE_VERSION..."
curl -fL "https://github.com/docker/compose/releases/download/$COMPOSE_VERSION/docker-compose-linux-x86_64" \
  -o "$BUNDLE_DIR/docker-runtime/docker-compose-linux-x86_64"
chmod +x "$BUNDLE_DIR/docker-runtime/docker-compose-linux-x86_64"

cat > "$BUNDLE_DIR/install/install_and_start.sh" <<'EOS'
#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="$BASE_DIR/project"
DOCKER_DIR="$BASE_DIR/docker-runtime"
IMAGE_TAR="$BASE_DIR/image/validation-parser-dev.tar"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Please run with sudo: sudo ./install/install_and_start.sh"
  exit 1
fi

if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "ERROR: This bundle targets x86_64/amd64 Ubuntu 18.04.3."
  exit 1
fi

[[ -f "$IMAGE_TAR" ]] || { echo "ERROR: Missing image tar: $IMAGE_TAR"; exit 1; }
command -v iptables >/dev/null 2>&1 || { echo "ERROR: iptables is required on the Ubuntu host."; exit 1; }
command -v ps >/dev/null 2>&1 || { echo "ERROR: procps/ps is required on the Ubuntu host."; exit 1; }

echo "==> Installing bundled Docker Engine..."
install -d -m 0755 /usr/local/bin
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
tar -xzf "$DOCKER_DIR/docker-20.10.24.tgz" -C "$TMP"
install -m 0755 "$TMP/docker/"* /usr/local/bin/

echo "==> Installing bundled Docker Compose..."
install -d -m 0755 /usr/local/lib/docker/cli-plugins
install -m 0755 "$DOCKER_DIR/docker-compose-linux-x86_64" /usr/local/lib/docker/cli-plugins/docker-compose

install -d -m 0755 /etc/docker
if [[ ! -f /etc/docker/daemon.json ]]; then
  cat > /etc/docker/daemon.json <<'JSON'
{
  "storage-driver": "overlay2",
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "3"
  }
}
JSON
fi

cat > /etc/systemd/system/docker.service <<'SERVICE'
[Unit]
Description=Docker Engine (Validation offline bundle)
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
ExecStart=/usr/local/bin/dockerd --host=unix:///var/run/docker.sock
ExecReload=/bin/kill -s HUP $MAINPID
TimeoutStartSec=0
Restart=on-failure
RestartSec=2
LimitNOFILE=1048576
LimitNPROC=infinity
LimitCORE=infinity

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable docker.service
systemctl start docker.service || systemctl restart docker.service

echo "==> Waiting for Docker daemon..."
for i in {1..30}; do
  if docker info >/dev/null 2>&1; then break; fi
  sleep 1
done
docker info >/dev/null 2>&1 || { journalctl -u docker.service --no-pager -n 80; exit 1; }

echo "==> Loading Validation image..."
docker load -i "$IMAGE_TAR"

echo "==> Preparing runtime folders..."
cd "$PROJECT_DIR"
mkdir -p \
  runtime/data_inflow/SAIS_IOR runtime/data_inflow/SAIS_GLOBAL runtime/data_inflow/MSIS runtime/data_inflow/LRIT \
  runtime/spool/pending runtime/spool/delivered runtime/spool/failed \
  runtime/router-state runtime/router-logs runtime/parser-logs runtime/parser-state \
  runtime/forwarder-state runtime/reference

echo "==> Starting Validation without build/pull..."
docker compose version
docker compose up -d --no-build --force-recreate
sleep 5
docker compose ps

echo
echo "============================================================"
echo " Validation offline stack started"
echo " Web Console: http://localhost:8088"
echo " Router API : http://localhost:8080"
echo " Parser API : http://localhost:8081"
echo " Forwarder  : http://localhost:8082"
echo "============================================================"
EOS
chmod +x "$BUNDLE_DIR/install/install_and_start.sh"

echo "==> Creating transfer checksums..."
(cd "$BUNDLE_DIR" && find docker-runtime image project -type f -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)

echo
echo "============================================================"
echo " Offline bundle ready:"
echo " $BUNDLE_DIR"
echo "============================================================"
echo "Copy this ONE folder to the Ubuntu 18.04.3 VM."
echo "On the VM run:"
echo "  sudo ./install/install_and_start.sh"

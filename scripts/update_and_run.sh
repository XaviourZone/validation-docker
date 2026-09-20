#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

COMPOSE="./offline/docker-static/docker-compose-linux-x86_64"
DOCKER_HOST_SOCKET="unix:///var/run/docker.sock"

if [[ ! -x "$COMPOSE" ]]; then
  echo "ERROR: Docker Compose binary not found: $COMPOSE"
  exit 1
fi

echo "==> Pulling latest Validation changes..."
git pull --ff-only origin dev/validation-full-build

echo "==> Checking Docker daemon..."
sudo "$COMPOSE" -H "$DOCKER_HOST_SOCKET" version >/dev/null

echo "==> Building updated Validation image..."
sudo "$COMPOSE" -H "$DOCKER_HOST_SOCKET" build parser

echo "==> Starting Validation stack..."
sudo "$COMPOSE" -H "$DOCKER_HOST_SOCKET" up -d --no-build --force-recreate

echo
echo "==> Validation services"
sudo "$COMPOSE" -H "$DOCKER_HOST_SOCKET" ps

echo
echo "================================================"
echo " Validation UI: http://localhost:8088"
echo "================================================"

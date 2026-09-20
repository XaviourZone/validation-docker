#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

# Use the system Docker CLI/Compose first. The current VM has a matching
# Docker 29.x client/server and requires API >= 1.44, while older Compose
# bundles can force an incompatible API version. Keep the static bundle only
# as a fallback for older/offline hosts.
if command -v docker >/dev/null 2>&1 && docker version >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
else
  REPO_COMPOSE="$REPO_DIR/offline/docker-static/docker-compose-linux-x86_64"
  DESKTOP_COMPOSE="$HOME/Desktop/validation-docker/offline/docker-static/docker-compose-linux-x86_64"
  if [[ -x "$REPO_COMPOSE" ]]; then
    COMPOSE=(sudo "$REPO_COMPOSE" -H unix:///var/run/docker.sock)
  elif [[ -x "$DESKTOP_COMPOSE" ]]; then
    COMPOSE=(sudo "$DESKTOP_COMPOSE" -H unix:///var/run/docker.sock)
  else
    echo "ERROR: No usable Docker Compose found."
    exit 1
  fi
fi

echo "==> Pulling latest Validation changes..."
git pull --ff-only origin dev/validation-full-build

echo "==> Checking Docker Compose..."
"${COMPOSE[@]}" version

echo "==> Building updated Validation image..."
"${COMPOSE[@]}" build parser

echo "==> Starting Validation stack..."
"${COMPOSE[@]}" up -d --no-build --force-recreate

echo
echo "==> Validation services"
"${COMPOSE[@]}" ps

echo
echo "================================================"
echo " Validation UI: http://localhost:8088"
echo "================================================"

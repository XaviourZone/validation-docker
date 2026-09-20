#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

# Prefer the bundled static Compose binary when present.
# Otherwise use the system docker compose command.
BUNDLED_COMPOSE="$REPO_DIR/offline/docker-static/docker-compose-linux-x86_64"
if [[ -x "$BUNDLED_COMPOSE" ]]; then
  COMPOSE=(sudo "$BUNDLED_COMPOSE" -H unix:///var/run/docker.sock)
elif command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
else
  echo "ERROR: No usable Docker Compose found."
  echo "       Bundled binary: $BUNDLED_COMPOSE"
  echo "       System command: docker compose"
  exit 1
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

#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

# The host used for this project may have a Docker API-version mismatch.
# Prefer the known-good static Compose binary from ~/Desktop when the repo
# does not contain its offline copy. Fall back to the repo copy, then system
# docker compose.
REPO_COMPOSE="$REPO_DIR/offline/docker-static/docker-compose-linux-x86_64"
DESKTOP_COMPOSE="$HOME/Desktop/validation-docker/offline/docker-static/docker-compose-linux-x86_64"

if [[ -x "$REPO_COMPOSE" ]]; then
  COMPOSE=(sudo "$REPO_COMPOSE" -H unix:///var/run/docker.sock)
elif [[ -x "$DESKTOP_COMPOSE" ]]; then
  COMPOSE=(sudo "$DESKTOP_COMPOSE" -H unix:///var/run/docker.sock)
elif command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
else
  echo "ERROR: No usable Docker Compose found."
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

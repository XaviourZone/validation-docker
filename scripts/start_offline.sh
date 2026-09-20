#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="$BASE_DIR/project"

if [[ "$(id -u)" -ne 0 ]]; then
  exec sudo "$0" "$@"
fi

command -v docker >/dev/null 2>&1 || {
  echo "ERROR: Docker is not installed. Run install_and_start.sh first."
  exit 1
}

cd "$PROJECT_DIR"
docker compose up -d --no-build --force-recreate
docker compose ps
echo "Validation UI: http://localhost:8088"

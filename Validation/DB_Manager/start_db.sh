#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# If PostgreSQL is installed as a system service, this command may require sudo.
if command -v systemctl >/dev/null 2>&1; then
  if ! systemctl is-active --quiet postgresql 2>/dev/null; then
    echo "PostgreSQL service is not active. Starting it..."
    sudo systemctl start postgresql
  fi
fi
python3 Validation/DB_Manager/db_manager.py

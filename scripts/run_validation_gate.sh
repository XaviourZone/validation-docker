#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 scripts/validation_gate.py --integration --docker

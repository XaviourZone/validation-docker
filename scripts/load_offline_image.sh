#!/usr/bin/env bash
set -euo pipefail

BUNDLE="${1:-validation-parser-dev.tar}"

if [[ ! -f "${BUNDLE}" ]]; then
  echo "ERROR: image bundle not found: ${BUNDLE}" >&2
  exit 1
fi

echo "Loading Docker image bundle: ${BUNDLE}"
docker load --input "${BUNDLE}"
echo "Offline image load completed."

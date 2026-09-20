#!/usr/bin/env bash
set -euo pipefail

IMAGE="${1:-validation/parser:dev}"
OUTPUT="${2:-validation-parser-dev.tar}"

echo "Exporting Docker image: ${IMAGE}"
docker image inspect "${IMAGE}" >/dev/null
docker save --output "${OUTPUT}" "${IMAGE}"
echo "Offline image bundle created: ${OUTPUT}"

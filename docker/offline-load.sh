#!/bin/sh
set -eu

BUNDLE_DIR="${1:-.}"
IMAGE_TAR="$BUNDLE_DIR/validation-parser-dev.tar"

[ -f "$IMAGE_TAR" ] || { echo "Missing $IMAGE_TAR" >&2; exit 1; }

docker load -i "$IMAGE_TAR"
docker compose -f "$BUNDLE_DIR/docker-compose.yml" up -d

printf '%s\n' "Validation Docker stack started."

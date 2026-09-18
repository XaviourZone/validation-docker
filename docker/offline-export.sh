#!/bin/sh
set -eu

IMAGE="${VALIDATION_IMAGE:-validation/parser:dev}"
OUT_DIR="${1:-offline-bundle}"

mkdir -p "$OUT_DIR"
docker save "$IMAGE" -o "$OUT_DIR/validation-parser-dev.tar"
cp docker-compose.yml "$OUT_DIR/"
cp -r docker "$OUT_DIR/"
cp -r Validation "$OUT_DIR/"
mkdir -p "$OUT_DIR/runtime/data_inflow/SAIS_IOR" "$OUT_DIR/runtime/data_inflow/SAIS_GLOBAL" "$OUT_DIR/runtime/data_inflow/MSIS" "$OUT_DIR/runtime/data_inflow/LRIT"
mkdir -p "$OUT_DIR/runtime/spool" "$OUT_DIR/runtime/router-state" "$OUT_DIR/runtime/router-logs" "$OUT_DIR/runtime/parser-logs" "$OUT_DIR/runtime/reference"

printf '%s\n' "Offline bundle created at: $OUT_DIR"
printf '%s\n' "Transfer the complete directory to the offline host."

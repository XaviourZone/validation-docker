#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WHEELS="${ROOT}/offline/python-wheels"
IMAGES="${ROOT}/offline/images"
mkdir -p "${WHEELS}" "${IMAGES}"

echo "=== Validation Offline Bundle Builder ==="

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: Docker is required on the internet-connected build machine." >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker daemon is not available." >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3/pip is required only on this internet-connected build machine." >&2
  exit 1
fi

echo "[1/5] Collecting Python wheels for Python 3.14 amd64..."
rm -f "${WHEELS}"/*.whl
python3 -m pip download --only-binary=:all: --dest "${WHEELS}" \
  --platform manylinux_2_17_x86_64 --implementation cp --python-version 3.14 --abi cp314 \
  -r "${ROOT}/Validation/Data_Parser/requirements.txt" \
  -r "${ROOT}/Validation/Data_Router/requirements.txt" \
  -r "${ROOT}/Validation/Data_Forwarder/requirements.txt" \
  -r "${ROOT}/Validation/Web_Console/requirements.txt" \
  -r "${ROOT}/Validation/Database/requirements.txt"

echo "[2/5] Pulling Python base image..."
docker pull python:3.14-slim
rm -f "${IMAGES}/python-3.14-slim.tar"
docker save -o "${IMAGES}/python-3.14-slim.tar" python:3.14-slim

 echo "[3/5] Building Validation application image..."
docker compose build --no-cache parser

echo "[4/5] Exporting application image..."
rm -f "${IMAGES}/validation-parser-dev.tar"
docker save -o "${IMAGES}/validation-parser-dev.tar" validation/parser:dev
sha256sum "${IMAGES}/python-3.14-slim.tar" "${IMAGES}/validation-parser-dev.tar" > "${IMAGES}/SHA256SUMS"

echo "[5/5] Writing Python wheel manifest..."
(
  cd "${WHEELS}"
  sha256sum ./*.whl > SHA256SUMS
)

echo
echo "Offline application bundle ready."
echo "Python wheels: ${WHEELS}"
echo "Docker image : ${IMAGES}/validation-parser-dev.tar"
echo "Production does not need Python."
echo "Load with: docker load -i offline/images/validation-parser-dev.tar"
echo "Start with: docker compose up -d --no-build"

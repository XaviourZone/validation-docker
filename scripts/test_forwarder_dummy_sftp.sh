#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

python3 -m unittest Validation.Data_Forwarder.tests.test_dummy_sftp_e2e -v

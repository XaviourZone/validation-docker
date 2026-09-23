"""Editable PostgreSQL/DB Manager settings.

Keep this file local to the deployment if credentials or paths are site-specific.
No credentials are required by default when PostgreSQL is configured for local
peer/trust/passwordless local access. If a password is required, set it here or
through the environment variable VALIDATION_PG_PASSWORD.
"""
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]

PG_HOST = os.getenv("VALIDATION_PG_HOST", "127.0.0.1")
PG_PORT = int(os.getenv("VALIDATION_PG_PORT", "5432"))
PG_DATABASE = os.getenv("VALIDATION_PG_DATABASE", "validation")
PG_USER = os.getenv("VALIDATION_PG_USER", "validation")
PG_PASSWORD = os.getenv("VALIDATION_PG_PASSWORD", "")

WEB_HOST = os.getenv("VALIDATION_DB_WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("VALIDATION_DB_WEB_PORT", "5050"))

PANS_INPUT_DIR = Path(os.getenv("VALIDATION_PANS_INPUT_DIR", str(ROOT / "DB_Data" / "PANS")))
WRS_INPUT_DIR = Path(os.getenv("VALIDATION_WRS_INPUT_DIR", str(ROOT / "DB_Data" / "WRS")))
NSC_INPUT_DIR = Path(os.getenv("VALIDATION_NSC_INPUT_DIR", str(ROOT / "DB_Data" / "NSC")))

PANS_POLL_SECONDS = float(os.getenv("VALIDATION_PANS_POLL_SECONDS", "2"))
PANS_STABILITY_SECONDS = float(os.getenv("VALIDATION_PANS_STABILITY_SECONDS", "1"))

# Optional local PostgreSQL binaries for START_DB helpers.
PG_CTL_PATH = os.getenv("VALIDATION_PG_CTL", "")
PG_DATA_DIR = os.getenv("VALIDATION_PG_DATA", "")

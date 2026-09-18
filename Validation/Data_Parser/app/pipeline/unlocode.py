"""Offline UN/LOCODE destination resolver.

The bundled JSON dictionary is generated from the UNECE/UNCEFACT UN/LOCODE
2025-1 vocabulary. Runtime lookup is local/offline and never calls a service.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

_CACHE: Optional[Dict[str, str]] = None


def _default_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    return root / "config" / "unlocode.json"


def _load() -> Dict[str, str]:
    global _CACHE
    if _CACHE is None:
        path = _default_path()
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            _CACHE = {
                str(code).strip().upper(): str(name).strip()
                for code, name in data.items()
                if str(code).strip() and str(name).strip()
            }
        except FileNotFoundError:
            _CACHE = {}
        except Exception:
            _CACHE = {}
    return _CACHE


def resolve_destination(value: Any) -> Any:
    """Convert a 5-character UN/LOCODE to its local dictionary name.

    Values that are not valid-looking UN/LOCODEs or are not present in the
    dictionary are returned unchanged. Existing human-readable destinations
    are therefore preserved.
    """
    if value is None:
        return value

    text = str(value).strip()
    if not text:
        return value

    code = "".join(text.upper().split())
    if len(code) != 5 or not code[:2].isalpha() or not code[2:].isalnum():
        return value

    return _load().get(code, value)

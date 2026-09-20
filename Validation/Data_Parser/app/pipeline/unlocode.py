"""Offline UN/LOCODE destination resolver.

The bundled JSON dictionary is generated from the UNECE/UNCEFACT UN/LOCODE
2025-1 vocabulary. Runtime lookup is local/offline and never calls a service.
"""

import json
from pathlib import Path
import unicodedata
from typing import Any, Dict, Optional

_CACHE: Optional[Dict[str, str]] = None
_NAME_CACHE: Optional[Dict[str, str]] = None


def _default_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    return root / "config" / "unlocode.json"


def _load() -> Dict[str, str]:
    global _CACHE, _NAME_CACHE
    if _CACHE is None:
        path = _default_path()
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                data = {}
            _CACHE = {
                str(code).strip().upper().replace(" ", ""): str(name).strip()
                for code, name in data.items()
                if str(code).strip() and str(name).strip()
            }
            # Build a reverse name index once so a destination that is already
            # a human-readable UN/LOCODE name can also be canonicalised.
            _NAME_CACHE = {}
            for code, name in _CACHE.items():
                key = _normalise_name(name)
                if key and key not in _NAME_CACHE:
                    _NAME_CACHE[key] = name
        except FileNotFoundError:
            _CACHE = {}
            _NAME_CACHE = {}
        except Exception:
            _CACHE = {}
            _NAME_CACHE = {}
    return _CACHE


def _normalise_name(value: Any) -> str:
    text = str(value or "").strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.upper().split())


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
    mapping = _load()

    # First handle a five-character UN/LOCODE, with or without the
    # conventional display space (for example ADALV or AD ALV).
    if len(code) == 5 and code[:2].isalpha() and code[2:].isalnum():
        return mapping.get(code, value)

    # If the incoming value is already a destination name, canonicalise it
    # against the same offline UN/LOCODE dictionary. Unknown/free-text
    # destinations remain unchanged.
    name_map = _NAME_CACHE or {}
    return name_map.get(_normalise_name(text), value)

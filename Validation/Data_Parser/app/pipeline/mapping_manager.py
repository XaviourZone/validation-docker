"""Configuration manager for the 41 canonical XML parser fields."""

import copy
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from .normalizer import LOGICAL_FIELDS_41

SOURCE_KINDS = {"incoming", "ais_state", "wrs", "pans", "nsc", "default"}


def _default_path() -> Path:
    cur = Path(__file__).resolve()
    for parent in [cur, *cur.parents]:
        candidate = parent / "Validation" / "Data_Parser" / "config" / "parser_mappings.yaml"
        if candidate.parent.exists():
            return candidate
    return Path("Validation/Data_Parser/config/parser_mappings.yaml").resolve()


class ParserMappingManager:
    """Reads and atomically writes parser mapping definitions."""

    def __init__(self, path: Path = None):
        self.path = Path(path or os.environ.get("VALIDATION_PARSER_MAPPINGS", _default_path()))
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def fields() -> List[str]:
        return list(LOGICAL_FIELDS_41)

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"parsers": {}}
        with self.path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            raise ValueError("Parser mapping YAML root must be a mapping")
        return data

    def parser_names(self) -> List[str]:
        return list((self.load().get("parsers") or {}).keys())

    def get(self, parser_name: str) -> Dict[str, Any]:
        parsers = self.load().get("parsers") or {}
        parser = copy.deepcopy(parsers.get(parser_name, {}))
        parser.setdefault("format", "auto")
        parser.setdefault("fields", {})
        for field in LOGICAL_FIELDS_41:
            parser["fields"].setdefault(field, [])
        return parser

    def save(self, parser_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = str(parser_name or "").strip()
        if not name or not name.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Parser name must contain only letters, numbers, '_' or '-'")
        if not isinstance(payload, dict):
            raise ValueError("Mapping payload must be a JSON object")
        fmt = str(payload.get("format", "auto")).lower()
        if fmt not in {"auto", "csv", "json", "xml", "text"}:
            raise ValueError("format must be auto, csv, json, xml or text")
        fields = payload.get("fields") or {}
        if not isinstance(fields, dict):
            raise ValueError("fields must be an object")

        normalized: Dict[str, List[str]] = {}
        for target in LOGICAL_FIELDS_41:
            raw = fields.get(target, [])
            if isinstance(raw, str):
                raw = [raw]
            if not isinstance(raw, list):
                raise ValueError(f"Mapping for '{target}' must be a list")
            candidates = []
            for candidate in raw:
                candidate = str(candidate).strip()
                if not candidate:
                    continue
                if ":" in candidate:
                    kind, path = candidate.split(":", 1)
                    if kind not in SOURCE_KINDS or not path:
                        raise ValueError(f"Invalid mapping source '{candidate}' for '{target}'")
                candidates.append(candidate)
            normalized[target] = candidates

        data = self.load()
        data.setdefault("parsers", {})[name] = {"format": fmt, "fields": normalized}
        self._atomic_write(data)
        return data["parsers"][name]

    def _atomic_write(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)
            os.replace(tmp_name, self.path)
        finally:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass


def default_mapping_for(parser_name: str = "GENERIC") -> Dict[str, Any]:
    """Create a safe default mapping with the established fallback order."""
    fields = {}
    aliases = {
        "id.mmsi": "mmsi", "id.imo": "imo", "id.callsign": "callsign",
        "vessel.name": "vessel_name", "ais.typeAndCargo": "vessel_type",
        "vessel.length": "length", "vessel.beam": "width", "vessel.draft": "draught",
        "kinematic.pos.lla.lat": "latitude", "kinematic.pos.lla.lon": "longitude",
        "kinematic.speed": "sog", "kinematic.course.true": "cog",
        "kinematic.heading.true": "true_heading", "ais.navStatus": "nav_status",
        "voyage.destination": "destination", "voyage.eta": "eta",
        "app.message.id": "message_type",
    }
    for target in LOGICAL_FIELDS_41:
        incoming_key = aliases.get(target)
        candidates = [f"incoming:{incoming_key}"] if incoming_key else []
        # AIS state is second priority for fields that commonly repeat in static reports.
        if incoming_key in {"imo", "callsign", "vessel_name", "vessel_type", "length", "width", "draught", "destination", "eta", "nav_status"}:
            candidates.append(f"ais_state:{incoming_key}")
        fields[target] = candidates
    return {"format": "auto", "fields": fields}

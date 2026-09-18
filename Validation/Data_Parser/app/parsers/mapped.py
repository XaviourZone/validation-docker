"""Generic parser driven by the Web Console 41-field mapping definition."""

import csv
import io
import json
import xml.etree.ElementTree as ET
from typing import Any, Dict, List

from ..models.common import CommonVesselRecord, ParseResult, ParserEnvelope
from ..pipeline.mapping_manager import ParserMappingManager
from .base import BaseParser


def _number(value, integer=False):
    if value in (None, "", "null", "None"):
        return None
    try:
        f = float(str(value).strip())
        return int(f) if integer else f
    except (ValueError, TypeError):
        return None


def _text(value):
    if value is None:
        return None
    s = str(value).strip()
    return s or None


class MappedParser(BaseParser):
    """Parses CSV/JSON/XML/text input using operator-configured field mappings."""

    def __init__(self, parser_name: str, mapping_manager: ParserMappingManager = None):
        self._parser_name = parser_name
        self.mapping_manager = mapping_manager or ParserMappingManager()

    @property
    def parser_name(self) -> str:
        return self._parser_name

    def _records_from_payload(self, payload: str, fmt: str) -> List[Dict[str, Any]]:
        text = payload or ""
        if fmt == "auto":
            stripped = text.lstrip()
            if stripped.startswith("{") or stripped.startswith("["):
                fmt = "json"
            elif stripped.startswith("<"):
                fmt = "xml"
            elif text.splitlines() and "," in text.splitlines()[0]:
                fmt = "csv"
            else:
                fmt = "text"
        if fmt == "csv":
            return [dict(row) for row in csv.DictReader(io.StringIO(text))]
        if fmt == "json":
            data = json.loads(text)
            if isinstance(data, list):
                return [x if isinstance(x, dict) else {"value": x} for x in data]
            return [data if isinstance(data, dict) else {"value": data}]
        if fmt == "xml":
            root = ET.fromstring(text)
            values = {}
            for node in root.iter():
                if len(node) == 0 and node.text and node.text.strip():
                    values[node.tag.split("}")[-1]] = node.text.strip()
            return [values]
        return [{"raw": line} for line in text.splitlines() if line.strip()] or [{"raw": text}]

    def _value(self, incoming: Dict[str, Any], candidates: List[str]):
        for candidate in candidates or []:
            if ":" not in candidate:
                continue
            kind, key = candidate.split(":", 1)
            if kind == "incoming":
                if key in incoming and incoming[key] not in (None, ""):
                    return incoming[key]
                low = key.lower()
                for actual, value in incoming.items():
                    if str(actual).lower() == low and value not in (None, ""):
                        return value
            elif kind == "default":
                return key
        return None

    def parse(self, envelope: ParserEnvelope) -> ParseResult:
        config = self.mapping_manager.get(self._parser_name)
        fmt = str(config.get("format", "auto")).lower()
        fields = config.get("fields") or {}
        records: List[CommonVesselRecord] = []
        errors: List[str] = []
        try:
            rows = self._records_from_payload(envelope.payload or "", fmt)
        except Exception as exc:
            return ParseResult(envelope.message_id, envelope.source, False, 0, 1, [], [f"Mapped parser input error: {exc}"])

        for index, incoming in enumerate(rows, 1):
            try:
                values = {logical: self._value(incoming, candidates) for logical, candidates in fields.items()}
                mmsi = _number(values.get("id.mmsi"), True)
                timestamp = _text(values.get("timestamp.source")) or envelope.received_at
                record = CommonVesselRecord(
                    source=envelope.source,
                    message_id=envelope.message_id,
                    record_id=f"{envelope.source}:{envelope.message_id}:{index}:{mmsi or 'unknown'}",
                    timestamp=timestamp,
                    mmsi=mmsi,
                    imo=_number(values.get("id.imo"), True),
                    callsign=_text(values.get("id.callsign")),
                    vessel_name=_text(values.get("vessel.name")),
                    latitude=_number(values.get("kinematic.pos.lla.lat")),
                    longitude=_number(values.get("kinematic.pos.lla.lon")),
                    sog=_number(values.get("kinematic.speed")),
                    cog=_number(values.get("kinematic.course.true")),
                    true_heading=_number(values.get("kinematic.heading.true")),
                    nav_status=_number(values.get("ais.navStatus"), True),
                    vessel_type=_text(values.get("ais.typeAndCargo")),
                    length=_number(values.get("vessel.length")),
                    width=_number(values.get("vessel.beam")),
                    draught=_number(values.get("vessel.draft")),
                    destination=_text(values.get("voyage.destination")),
                    eta=_text(values.get("voyage.eta")),
                    app_message_id=_number(values.get("app.message.id"), True),
                    raw_payload=json.dumps(incoming, ensure_ascii=False),
                )
                record.raw_attributes = {"incoming": incoming}
                records.append(record)
            except Exception as exc:
                errors.append(f"Row {index} parse failed: {exc}")

        return ParseResult(envelope.message_id, envelope.source, not errors and bool(records), len(records), len(errors), records, errors)

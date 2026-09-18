"""MSIS Parser for tabular CSV feeds with column headers."""

import csv
import io
from typing import List, Optional

from ..models.common import CommonVesselRecord, ParseResult, ParserEnvelope
from .base import BaseParser


def _safe_float(val: Optional[str]) -> Optional[float]:
    if not val or val.strip().lower() in ("none", "null", "", "nan"):
        return None
    try:
        return float(val.strip())
    except (ValueError, TypeError):
        return None


def _safe_int(val: Optional[str]) -> Optional[int]:
    if not val or val.strip().lower() in ("none", "null", "", "nan"):
        return None
    try:
        f = float(val.strip())
        return int(f) if f != 0 else None
    except (ValueError, TypeError):
        return None


def _safe_str(val: Optional[str]) -> Optional[str]:
    if not val or val.strip().lower() in ("none", "null", "", "nan"):
        return None
    s = val.strip().strip('"').strip()
    return s if s else None


def _first(row, *names):
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


class MSISParser(BaseParser):
    """Parses already-decoded AIS tabular CSV data with headers."""

    @property
    def parser_name(self) -> str:
        return "MSIS"

    def parse(self, envelope: ParserEnvelope) -> ParseResult:
        source = envelope.source
        message_id = envelope.message_id
        raw_text = envelope.payload or ""
        records: List[CommonVesselRecord] = []
        errors: List[str] = []
        parsed_count = 0
        rejected_count = 0

        if not raw_text.strip():
            return ParseResult(message_id=message_id, source=source, success=True, records_parsed=0, records_rejected=0, records=[], errors=[])

        reader = csv.DictReader(io.StringIO(raw_text))
        for line_idx, row in enumerate(reader, 1):
            try:
                mmsi_val = _safe_int(_first(row, "mmsi", "MMSI"))
                rec_id = f"{source}:{message_id}:{line_idx}:{mmsi_val or 'unknown'}"
                timestamp = _safe_str(_first(row, "updated", "timestamp", "time")) or envelope.received_at
                rec = CommonVesselRecord(
                    source=source,
                    message_id=message_id,
                    record_id=rec_id,
                    timestamp=timestamp,
                    mmsi=mmsi_val,
                    imo=_safe_int(_first(row, "imo", "IMO")),
                    vessel_name=_safe_str(_first(row, "ship_name", "vessel_name", "name")),
                    callsign=_safe_str(_first(row, "callsign", "call_sign")),
                    latitude=_safe_float(_first(row, "latitude", "lat")),
                    longitude=_safe_float(_first(row, "longitude", "lon", "lng")),
                    sog=_safe_float(_first(row, "sog", "speed")),
                    cog=_safe_float(_first(row, "cog", "course")),
                    true_heading=_safe_float(_first(row, "true_heading", "heading")),
                    nav_status=_safe_int(_first(row, "navigation_status", "navigatetion_status", "nav_status")),
                    rot=_safe_float(_first(row, "rate_of_turn", "rot")),
                    draught=_safe_float(_first(row, "draught", "draft")),
                    vessel_type=_safe_str(_first(row, "type_and_cargo", "vessel_type", "type")),
                    destination=_safe_str(_first(row, "destination", "voyage_destination")),
                    eta=_safe_str(_first(row, "eta", "ETA")),
                    length=_safe_float(_first(row, "length", "loa")),
                    width=_safe_float(_first(row, "width", "beam")),
                )
                records.append(rec)
                parsed_count += 1
            except Exception as e:
                rejected_count += 1
                errors.append(f"Row {line_idx} parse failed: {str(e)}")

        success = parsed_count > 0 or len(errors) == 0
        return ParseResult(message_id=message_id, source=source, success=success, records_parsed=parsed_count, records_rejected=rejected_count, records=records, errors=errors)

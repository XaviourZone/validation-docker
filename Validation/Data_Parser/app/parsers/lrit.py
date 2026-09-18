"""LRIT Parser for tabular CSV feeds without column headers."""

import csv
import io
from typing import List

from ..models.common import CommonVesselRecord, ParseResult, ParserEnvelope
from .base import BaseParser
from .msis import _safe_float, _safe_int, _safe_str


class LRITParser(BaseParser):
    """Parses LRIT position records formatted as headerless 20-column CSV."""

    @property
    def parser_name(self) -> str:
        return "LRIT"

    def parse(self, envelope: ParserEnvelope) -> ParseResult:
        source = envelope.source
        message_id = envelope.message_id
        raw_text = envelope.payload or ""

        records: List[CommonVesselRecord] = []
        errors: List[str] = []
        parsed_count = 0
        rejected_count = 0

        # Many LRIT files are 0-byte or empty lines (normal periodic poll)
        if not raw_text.strip():
            return ParseResult(
                message_id=message_id,
                source=source,
                success=True,
                records_parsed=0,
                records_rejected=0,
                records=[],
                errors=[],
            )

        reader = csv.reader(io.StringIO(raw_text))
        for line_idx, cols in enumerate(reader, 1):
            if not cols:
                continue

            # Check if this happens to be a header line (e.g. starting with 'mmsi')
            if line_idx == 1 and cols[0].strip().lower() == "mmsi":
                continue

            try:
                # Ensure at least 13 columns for position/identity
                if len(cols) < 13:
                    raise ValueError(f"Fewer columns than expected: {len(cols)}")

                mmsi_val = _safe_int(cols[0])
                rec_id = f"{source}:{message_id}:{line_idx}:{mmsi_val or 'unknown'}"
                timestamp = _safe_str(cols[8]) if len(cols) > 8 else None
                record_time = timestamp or envelope.received_at

                rec = CommonVesselRecord(
                    source=source,
                    message_id=message_id,
                    record_id=rec_id,
                    timestamp=record_time,
                    mmsi=mmsi_val,
                    latitude=_safe_float(cols[1]),
                    longitude=_safe_float(cols[2]),
                    sog=_safe_float(cols[3]) if len(cols) > 3 else None,
                    cog=_safe_float(cols[4]) if len(cols) > 4 else None,
                    true_heading=_safe_float(cols[5]) if len(cols) > 5 else None,
                    nav_status=_safe_int(cols[7]) if len(cols) > 7 else None,
                    vessel_name=_safe_str(cols[11]) if len(cols) > 11 else None,
                    imo=_safe_int(cols[12]) if len(cols) > 12 else None,
                    callsign=_safe_str(cols[13]) if len(cols) > 13 else None,
                    length=_safe_float(cols[14]) if len(cols) > 14 else None,
                    width=_safe_float(cols[15]) if len(cols) > 15 else None,
                    draught=_safe_float(cols[16]) if len(cols) > 16 else None,
                    destination=_safe_str(cols[17]) if len(cols) > 17 else None,
                    vessel_type=_safe_str(cols[18]) if len(cols) > 18 else None,
                    eta=_safe_str(cols[19]) if len(cols) > 19 else None,
                    raw_payload=",".join(cols),
                )
                records.append(rec)
                parsed_count += 1
            except Exception as e:
                rejected_count += 1
                errors.append(f"Line {line_idx} parse failed: {str(e)}")

        success = parsed_count > 0 or len(errors) == 0

        return ParseResult(
            message_id=message_id,
            source=source,
            success=success,
            records_parsed=parsed_count,
            records_rejected=rejected_count,
            records=records,
            errors=errors,
        )

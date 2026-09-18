"""VATMS Parser for East (NMEA !WSVDM) and West (Transas $TMVTD) feeds."""

from datetime import datetime, timezone
import re
from typing import Dict, List, Optional, Tuple

from ..models.common import CommonVesselRecord, ParseResult, ParserEnvelope
from .base import BaseParser
from .sais import SAISParser, decode_6bit_ascii, to_signed_int, _checksum_ok


class VATMSParser(BaseParser):
    """Parses VATMS_EAST (NMEA VDM) and VATMS_WEST (Transas Marine $TMVTD) streams."""

    def __init__(self):
        self._sais_parser = SAISParser()

    @property
    def parser_name(self) -> str:
        return "VATMS"

    def parse(self, envelope: ParserEnvelope) -> ParseResult:
        source = envelope.source
        message_id = envelope.message_id
        raw_text = envelope.payload or ""

        records: List[CommonVesselRecord] = []
        errors: List[str] = []
        parsed_count = 0
        rejected_count = 0

        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

        for line_idx, line in enumerate(lines, 1):
            try:
                # Dispatch based on sentence type
                if line.startswith("$TMVTD"):
                    record = self._parse_tmvtd(source, message_id, line_idx, line, envelope.received_at)
                elif line.startswith("!"):
                    # NMEA VDM sentence (!WSVDM, !AIVDM)
                    record = self._sais_parser._parse_line(source, message_id, line_idx, line)
                else:
                    continue

                if record:
                    records.append(record)
                    parsed_count += 1
            except Exception as e:
                rejected_count += 1
                errors.append(f"Line {line_idx} parse failed: {str(e)} | Line: {line[:60]}")

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

    def _parse_tmvtd(
        self, source: str, message_id: str, line_num: int, line: str, default_time: str
    ) -> Optional[CommonVesselRecord]:
        """Parse Transas Marine target data sentence $TMVTD."""
        parts = line.split(",")
        if len(parts) < 14:
            raise ValueError("Malformed TMVTD sentence: fewer than 14 fields")

        if not _checksum_ok(line):
            raise ValueError("TMVTD checksum validation failed")

        # Drop/delete target messages are control records, not vessel tracks.
        if parts[-1].startswith("D*") or "D*" in parts[-1]:
            return None

        date_str = parts[1].strip()
        time_str = parts[2].strip()

        ts = default_time
        if len(date_str) == 6 and len(time_str) >= 6:
            try:
                ts = f"20{date_str[0:2]}-{date_str[2:4]}-{date_str[4:6]}T{time_str[0:2]}:{time_str[2:4]}:{time_str[4:6]}Z"
            except Exception:
                ts = default_time

        # Coordinates conversion
        lat_str = parts[6].strip() if len(parts) > 6 else ""
        lat_hemi = parts[7].strip() if len(parts) > 7 else "N"
        lon_str = parts[8].strip() if len(parts) > 8 else ""
        lon_hemi = parts[9].strip() if len(parts) > 9 else "E"

        lat = None
        if lat_str and len(lat_str) >= 4:
            try:
                deg = float(lat_str[:2])
                minutes = float(lat_str[2:])
                lat_val = deg + minutes / 60.0
                lat = -lat_val if lat_hemi == "S" else lat_val
            except Exception:
                pass

        lon = None
        if lon_str and len(lon_str) >= 5:
            try:
                deg = float(lon_str[:3])
                minutes = float(lon_str[3:])
                lon_val = deg + minutes / 60.0
                lon = -lon_val if lon_hemi == "W" else lon_val
            except Exception:
                pass

        cog = float(parts[10]) if len(parts) > 10 and parts[10].strip() else None
        sog = float(parts[12]) if len(parts) > 12 and parts[12].strip() else None
        name = parts[5].strip() if len(parts) > 5 and parts[5].strip() else None
        stype = parts[14].strip() if len(parts) > 14 and parts[14].strip() else None
        callsign = parts[15].strip() if len(parts) > 15 and parts[15].strip() else None

        length = float(parts[16]) / 100.0 if len(parts) > 16 and parts[16].strip() else None
        width = float(parts[17]) / 100.0 if len(parts) > 17 and parts[17].strip() else None
        draught = float(parts[18]) / 100.0 if len(parts) > 18 and parts[18].strip() else None

        mmsi = int(parts[20]) if len(parts) > 20 and parts[20].strip().isdigit() else None
        imo = int(parts[23]) if len(parts) > 23 and parts[23].strip().isdigit() else None

        rec_id = f"{source}:{message_id}:{line_num}:{mmsi or parts[4].strip()}"

        return CommonVesselRecord(
            source=source,
            message_id=message_id,
            record_id=rec_id,
            timestamp=ts,
            mmsi=mmsi,
            imo=imo,
            vessel_name=name,
            callsign=callsign,
            latitude=lat,
            longitude=lon,
            sog=sog,
            cog=cog,
            vessel_type=stype,
            length=length,
            width=width,
            draught=draught,
            raw_payload=line,
        )

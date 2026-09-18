"""SAIS parser for NMEA AIS sentences with IEC 61162 Tag Blocks.

The parser recognizes AIS message types 1-27. Detailed vessel fields are decoded
where they are applicable; message types without vessel-state fields are still
accepted and retained with MMSI, message type, timestamp and raw payload so they
are not silently discarded. Type 5/19/21/24 static information is suitable for
the persistent per-MMSI AIS state cache.
"""

from datetime import datetime, timezone
import re
from typing import Dict, List, Optional, Tuple

from ..models.common import CommonVesselRecord, ParseResult, ParserEnvelope
from .base import BaseParser

AIS_CHARSET = "@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_ !\"#$%&'()*+,-./0123456789:;<=>?"
SUPPORTED_AIS_TYPES = set(range(1, 28))


def decode_6bit_ascii(payload: str) -> str:
    bits = []
    for c in payload:
        val = ord(c) - 48
        if val > 40:
            val -= 8
        if 0 <= val <= 63:
            bits.append(f"{val:06b}")
        else:
            raise ValueError(f"Invalid AIS 6-bit ASCII character: {c}")
    return "".join(bits)


def decode_ais_string(bit_str: str) -> str:
    chars = []
    for i in range(0, len(bit_str) - 5, 6):
        code = int(bit_str[i:i + 6], 2)
        if code < len(AIS_CHARSET):
            c = AIS_CHARSET[code]
            if c != "@":
                chars.append(c)
    return "".join(chars).strip()


def to_signed_int(bits: str) -> int:
    val = int(bits, 2)
    n = len(bits)
    if val >= (1 << (n - 1)):
        val -= 1 << n
    return val


def _checksum_ok(sentence: str) -> bool:
    if "*" not in sentence:
        return True
    body, supplied = sentence.rsplit("*", 1)
    supplied = supplied[:2]
    if len(supplied) != 2:
        return False
    checksum = 0
    for ch in body[1:]:
        checksum ^= ord(ch)
    try:
        return checksum == int(supplied, 16)
    except ValueError:
        return False


def _bits(bit_str: str, start: int, end: int) -> Optional[str]:
    if len(bit_str) < end:
        return None
    return bit_str[start:end]


def _int(bit_str: str, start: int, end: int) -> Optional[int]:
    value = _bits(bit_str, start, end)
    return int(value, 2) if value is not None else None


class SAISParser(BaseParser):
    """Parses SAIS_IOR, SAIS_GLOBAL and other standard AIS NMEA feeds."""

    def __init__(self):
        self._fragment_cache: Dict[Tuple[str, str, int], Dict[int, Tuple[str, Optional[str]]]] = {}
        self._fragment_meta: Dict[Tuple[str, str, int], Tuple[Optional[int], Optional[int]]] = {}

    @property
    def parser_name(self) -> str:
        return "SAIS"

    def parse(self, envelope: ParserEnvelope) -> ParseResult:
        source = envelope.source
        message_id = envelope.message_id
        lines = [line.strip() for line in (envelope.payload or "").splitlines() if line.strip()]
        records: List[CommonVesselRecord] = []
        errors: List[str] = []
        for line_idx, line in enumerate(lines, 1):
            try:
                record = self._parse_line(source, message_id, line_idx, line)
                if record is not None:
                    records.append(record)
            except Exception as exc:
                errors.append(f"Line {line_idx} parse failed: {exc} | Raw: {line[:120]}")
        return ParseResult(
            message_id=message_id,
            source=source,
            success=(not lines) or bool(records),
            records_parsed=len(records),
            records_rejected=len(errors),
            records=records,
            errors=errors,
        )

    def _parse_line(self, source: str, message_id: str, line_num: int, line: str) -> Optional[CommonVesselRecord]:
        tag_timestamp_iso = None
        nmea_sentence = line
        if line.startswith("\\"):
            tag_end = line.find("\\", 1)
            if tag_end != -1:
                tag_block = line[1:tag_end]
                nmea_sentence = line[tag_end + 1:].lstrip()
                match = re.search(r"\bc:(\d+)\b", tag_block)
                if match:
                    tag_timestamp_iso = datetime.fromtimestamp(int(match.group(1)), tz=timezone.utc).isoformat()

        record_time = tag_timestamp_iso or datetime.now(timezone.utc).isoformat()
        if not (nmea_sentence.startswith("!") or nmea_sentence.startswith("$")):
            raise ValueError("Malformed NMEA sentence: unsupported sentence prefix")
        if not _checksum_ok(nmea_sentence):
            raise ValueError("NMEA checksum validation failed")

        parts = nmea_sentence.split(",")
        if len(parts) < 6:
            raise ValueError("Malformed NMEA sentence: fewer than 6 comma-delimited fields")
        total = int(parts[1]) if parts[1].isdigit() else 1
        seq = int(parts[2]) if parts[2].isdigit() else 1
        seq_id = parts[3]
        payload = parts[5]
        fill_bits = 0
        if len(parts) > 6:
            fill_part = parts[6].split("*", 1)[0]
            try:
                fill_bits = int(fill_part or 0)
            except ValueError:
                fill_bits = 0

        if total > 1:
            # Physical-line contract: every NMEA fragment must produce one
            # output record. A fragment that cannot yet be fully reassembled
            # emits only facts available from that fragment/cache; the final
            # fragment additionally emits the complete decoded AIS message.
            key = (source, seq_id, total)
            cache = self._fragment_cache.setdefault(key, {})
            cache[seq] = (payload, record_time)

            if seq == 1:
                first_bits = decode_6bit_ascii(payload)
                if len(first_bits) >= 38:
                    self._fragment_meta[key] = (
                        int(first_bits[0:6], 2),
                        int(first_bits[8:38], 2),
                    )

            if len(cache) < total:
                meta = self._fragment_meta.get(key, (None, None))
                fragment_record = CommonVesselRecord(
                    source=source,
                    message_id=message_id,
                    record_id=f"{source}:{message_id}:{line_num}:fragment-{seq}",
                    timestamp=record_time,
                    mmsi=meta[1],
                    app_message_id=meta[0],
                    raw_payload=line,
                    raw_attributes={
                        "multipart": True,
                        "fragment_number": seq,
                        "fragment_count": total,
                        "sequence_id": seq_id,
                        "complete_decode": False,
                    },
                )
                return fragment_record

            payload = "".join(cache[i][0] for i in range(1, total + 1))
            record_time = cache.get(1, (payload, record_time))[1] or record_time
            self._fragment_cache.pop(key, None)
            self._fragment_meta.pop(key, None)

        bit_str = decode_6bit_ascii(payload)
        if fill_bits:
            bit_str = bit_str[:-fill_bits]
        if len(bit_str) < 38:
            raise ValueError("Malformed AIS payload: fewer than 38 decoded bits")

        msg_type = int(bit_str[0:6], 2)
        mmsi = int(bit_str[8:38], 2)
        rec = CommonVesselRecord(
            source=source,
            message_id=message_id,
            record_id=f"{source}:{message_id}:{line_num}:{mmsi}",
            timestamp=record_time,
            mmsi=mmsi,
            app_message_id=msg_type,
            raw_payload=line,
        )
        if msg_type not in SUPPORTED_AIS_TYPES:
            raise ValueError(f"Unsupported AIS message type {msg_type}")

        # Types 1/2/3: Class A position report.
        if msg_type in (1, 2, 3) and len(bit_str) >= 137:
            rec.nav_status = _int(bit_str, 38, 42)
            rot_raw = to_signed_int(bit_str[42:50])
            rec.rot = float(rot_raw) if rot_raw != -128 else None
            sog = _int(bit_str, 50, 60)
            rec.sog = sog / 10.0 if sog is not None and sog != 1023 else None
            lon = to_signed_int(bit_str[61:89])
            lat = to_signed_int(bit_str[89:116])
            rec.longitude = round(lon / 600000.0, 6) if lon != 0x6791AC0 else None
            rec.latitude = round(lat / 600000.0, 6) if lat != 0x3412140 else None
            cog = _int(bit_str, 116, 128)
            rec.cog = cog / 10.0 if cog is not None and cog != 3600 else None
            hdg = _int(bit_str, 128, 137)
            rec.true_heading = float(hdg) if hdg is not None and hdg != 511 else None
            return rec

        # Type 4: Base station report. Position/time is retained for audit/state.
        if msg_type == 4 and len(bit_str) >= 168:
            lon = to_signed_int(bit_str[79:107])
            lat = to_signed_int(bit_str[107:134])
            rec.longitude = round(lon / 600000.0, 6) if lon != 0x6791AC0 else None
            rec.latitude = round(lat / 600000.0, 6) if lat != 0x3412140 else None
            return rec

        # Type 5: Static and voyage related data.
        if msg_type == 5 and len(bit_str) >= 422:
            imo = _int(bit_str, 40, 70)
            rec.imo = imo if imo else None
            rec.callsign = decode_ais_string(bit_str[70:112]) or None
            rec.vessel_name = decode_ais_string(bit_str[112:232]) or None
            vtype = _int(bit_str, 232, 240)
            rec.vessel_type = str(vtype) if vtype not in (None, 0) else None
            bow, stern = _int(bit_str, 240, 249), _int(bit_str, 249, 258)
            port, starboard = _int(bit_str, 258, 264), _int(bit_str, 264, 270)
            rec.len_to_bow = float(bow) if bow is not None else None
            rec.len_to_stern = float(stern) if stern is not None else None
            rec.width_to_port = float(port) if port is not None else None
            rec.width_to_starboard = float(starboard) if starboard is not None else None
            rec.length = float((bow or 0) + (stern or 0)) or None
            rec.width = float((port or 0) + (starboard or 0)) or None
            draught = _int(bit_str, 294, 302)
            rec.draught = round(draught / 10.0, 1) if draught else None
            rec.destination = decode_ais_string(bit_str[302:422]) or None
            return rec

        # Types 6/8/12/14 and related binary/safety messages are accepted with
        # their MMSI/type; the raw payload remains available for application-specific decoding.
        if msg_type in (6, 8, 12, 14, 25, 26):
            return rec

        # Type 7 binary acknowledgement.
        if msg_type == 7:
            return rec

        # Type 9 SAR aircraft position report.
        if msg_type == 9 and len(bit_str) >= 124:
            sog = _int(bit_str, 50, 60)
            rec.sog = sog / 10.0 if sog is not None and sog != 1023 else None
            lon = to_signed_int(bit_str[61:89]); lat = to_signed_int(bit_str[89:116])
            rec.longitude = round(lon / 600000.0, 6) if lon != 0x6791AC0 else None
            rec.latitude = round(lat / 600000.0, 6) if lat != 0x3412140 else None
            cog = _int(bit_str, 116, 124)
            rec.cog = cog * 2.0 if cog is not None and cog != 511 else None
            return rec

        # Types 10/13/15/16/17/20/22/23 contain management/request data; retain raw message.
        if msg_type in (10, 13, 15, 16, 17, 20, 22, 23):
            return rec

        # Type 18: Class B position report.
        if msg_type == 18 and len(bit_str) >= 133:
            sog = _int(bit_str, 46, 56)
            rec.sog = sog / 10.0 if sog is not None and sog != 1023 else None
            lon = to_signed_int(bit_str[57:85]); lat = to_signed_int(bit_str[85:112])
            rec.longitude = round(lon / 600000.0, 6) if lon != 0x6791AC0 else None
            rec.latitude = round(lat / 600000.0, 6) if lat != 0x3412140 else None
            cog = _int(bit_str, 112, 124); rec.cog = cog / 10.0 if cog is not None and cog != 3600 else None
            hdg = _int(bit_str, 124, 133); rec.true_heading = float(hdg) if hdg is not None and hdg != 511 else None
            return rec

        # Type 19: Extended Class B position report, including static vessel data.
        if msg_type == 19 and len(bit_str) >= 309:
            sog = _int(bit_str, 46, 56)
            rec.sog = sog / 10.0 if sog is not None and sog != 1023 else None
            lon = to_signed_int(bit_str[57:85]); lat = to_signed_int(bit_str[85:112])
            rec.longitude = round(lon / 600000.0, 6) if lon != 0x6791AC0 else None
            rec.latitude = round(lat / 600000.0, 6) if lat != 0x3412140 else None
            cog = _int(bit_str, 112, 124); rec.cog = cog / 10.0 if cog is not None and cog != 3600 else None
            hdg = _int(bit_str, 124, 133); rec.true_heading = float(hdg) if hdg is not None and hdg != 511 else None
            rec.vessel_name = decode_ais_string(bit_str[143:263]) or None
            vtype = _int(bit_str, 263, 271); rec.vessel_type = str(vtype) if vtype else None
            bow, stern = _int(bit_str, 271, 280), _int(bit_str, 280, 289)
            port, starboard = _int(bit_str, 289, 295), _int(bit_str, 295, 301)
            rec.length = float((bow or 0) + (stern or 0)) or None
            rec.width = float((port or 0) + (starboard or 0)) or None
            return rec

        # Type 21: Aids-to-Navigation report. Preserve name/type/position/dimensions.
        if msg_type == 21 and len(bit_str) >= 272:
            nav_type = _int(bit_str, 38, 42); rec.vessel_type = str(nav_type) if nav_type else None
            rec.vessel_name = decode_ais_string(bit_str[43:163]) or None
            lon = to_signed_int(bit_str[164:192]); lat = to_signed_int(bit_str[192:219])
            rec.longitude = round(lon / 600000.0, 6) if lon != 0x6791AC0 else None
            rec.latitude = round(lat / 600000.0, 6) if lat != 0x3412140 else None
            bow = _int(bit_str, 219, 228); stern = _int(bit_str, 228, 237)
            port = _int(bit_str, 237, 243); starboard = _int(bit_str, 243, 249)
            rec.length = float((bow or 0) + (stern or 0)) or None
            rec.width = float((port or 0) + (starboard or 0)) or None
            return rec

        # Type 24: Class B static data report, Part A/B.
        if msg_type == 24 and len(bit_str) >= 160:
            part = _int(bit_str, 38, 40)
            if part == 0:
                rec.vessel_name = decode_ais_string(bit_str[40:160]) or None
            elif part == 1:
                vtype = _int(bit_str, 40, 48)
                rec.vessel_type = str(vtype) if vtype else None
                rec.callsign = decode_ais_string(bit_str[90:132]) or None
                if len(bit_str) >= 162:
                    bow, stern = _int(bit_str, 132, 141), _int(bit_str, 141, 150)
                    port, starboard = _int(bit_str, 150, 156), _int(bit_str, 156, 162)
                    rec.length = float((bow or 0) + (stern or 0)) or None
                    rec.width = float((port or 0) + (starboard or 0)) or None
            return rec

        # Type 27: Long-range AIS position report.
        if msg_type == 27 and len(bit_str) >= 96:
            sog = _int(bit_str, 46, 54)
            rec.sog = float(sog) if sog is not None and sog != 127 else None
            cog = _int(bit_str, 55, 64)
            rec.cog = float(cog * 2.0) if cog is not None and cog != 511 else None
            lon = to_signed_int(bit_str[64:84]); lat = to_signed_int(bit_str[84:104])
            rec.longitude = round(lon / 10.0 / 60.0, 6) if lon else None
            rec.latitude = round(lat / 10.0 / 60.0, 6) if lat else None
            return rec

        return rec

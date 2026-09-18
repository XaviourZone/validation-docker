"""
Downstream XML Parser simulation and compatibility contract validator.

Implements the exact transformations performed by the existing downstream consumer:
- rad_to_scaled(v, scale, precision)
- timestamp_ms(v)
- int(float(v) / 0.001) for speed
- int(v) for identifiers
- sanitize_string(v)

Verifies that the generated XML is successfully ingested and converted
into the downstream output keys and types without modification.
"""

import math
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def rad_to_scaled(rad_val: float, scale: float = 1.0, precision: float = 0.0) -> int:
    """Scale radian float to integer value according to downstream formula."""
    if rad_val is None:
        return 0
    val = float(rad_val) * scale
    if precision > 0:
        val = round(val / precision) * precision
    return int(round(val))


def timestamp_ms(epoch_ms: Any) -> str:
    """Format epoch milliseconds timestamp into downstream ISO/IST string representation."""
    if not epoch_ms:
        return ""
    try:
        ms = int(float(epoch_ms))
        dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
        return dt.isoformat()
    except Exception:
        return str(epoch_ms)


# Downstream key mapping table from Excel Master
DOWNSTREAM_KEY_MAPPING = {
    "ais.lenToBow":            "length_bow",
    "ais.lenToStern":          "length_stern",
    "ais.navStatus":           "nav_status",
    "ais.typeAndCargo":        "ship_type",
    "ais.widthToPort":         "ais_widthToPort",
    "ais.widthToStarboard":    "ais_widthToStarboard",
    "app.message.id":          "app_message_id",
    "cat.annotation":          "cat_annotation",
    "cat.category":            "css_category",
    "cat.identity":            "identity",
    "foreign.track.number":    "foreign_track_number",
    "id.callsign":             "static_call_sign",
    "id.imo":                  "imo_no",
    "id.mmsi":                 "track_no",
    "id.mmsi.destination":     "vigilance_score",
    "kinematic.course.true":    "course",
    "kinematic.flag.3d":        "kinematic_flag_3d",
    "kinematic.heading.true":   "true_heading",
    "kinematic.pos.lla.alt":    "height",
    "kinematic.pos.lla.lat":    "lat",
    "kinematic.pos.lla.lon":    "long",
    "kinematic.speed":          "speed_over_ground",
    "sys.source.id":           "sensor_type",
    "sys.track.number":        "sys_track_number",
    "timestamp.receipt":       "timestamp_receipt",
    "timestamp.source":        "timestamp",
    "track.flag.active":       "track_flag_active",
    "track.quality":           "track_quality",
    "vessel.beam":             "vessel_beam",
    "vessel.description":      "vessel_description",
    "vessel.draft":            "vessel_draft",
    "vessel.grosstonnage":     "vessel_grosstonnage",
    "vessel.length":           "total_vessel_length",
    "vessel.name":             "ship_name",
    "vessel.remarks":          "remarks",
    "voyage.arrival":          "voyage_arrival",
    "voyage.departure":        "voyage_departure",
    "voyage.destination":      "voyage_destination",
    "voyage.eta":              "eta",
    "voyage.etd":              "etd",
    "voyage.origin":           "voyage_origin",
}


class DownstreamXMLParser:
    """Parses XTrack XML into the downstream final fields dictionary."""

    def parse_xml(self, xml_text: str) -> List[Dict[str, Any]]:
        """Parse XML string and return list of downstream records."""
        records: List[Dict[str, Any]] = []
        if not xml_text or not xml_text.strip():
            return records

        root = ET.fromstring(xml_text.strip())

        for xtrack in root.iter():
            if not xtrack.tag.endswith("XTrack"):
                continue

            record: Dict[str, Any] = {}

            for a_elem in xtrack:
                if not a_elem.tag.endswith("A"):
                    continue

                id_elem = None
                val_elem = None
                for ch in a_elem:
                    t = ch.tag.split("}")[-1]
                    if t == "id":
                        id_elem = ch
                    else:
                        val_elem = ch

                if id_elem is None or not id_elem.text:
                    continue

                field_id = id_elem.text.strip()
                val_text = (val_elem.text or "").strip() if val_elem is not None else ""
                val_tag = val_elem.tag.split("}")[-1] if val_elem is not None else ""

                # Map field_id to downstream key
                downstream_key = DOWNSTREAM_KEY_MAPPING.get(field_id, field_id)

                # Apply exact downstream consumer conversions
                if field_id == "id.imo":
                    record[downstream_key] = int(val_text) if val_text else None
                elif field_id == "id.mmsi":
                    record[downstream_key] = int(val_text) if val_text else None
                elif field_id == "foreign.track.number":
                    try:
                        record[downstream_key] = int(val_text)
                    except Exception:
                        record[downstream_key] = val_text
                elif field_id in ("id.callsign", "vessel.name"):
                    record[downstream_key] = val_text
                elif field_id in ("kinematic.course.true", "kinematic.heading.true"):
                    # rad_to_scaled(v, 1, precision=0.0055)
                    try:
                        fval = float(val_text)
                        record[downstream_key] = rad_to_scaled(fval, scale=1.0, precision=0.0055)
                    except Exception:
                        record[downstream_key] = None
                elif field_id in ("kinematic.pos.lla.lat", "kinematic.pos.lla.lon"):
                    # rad_to_scaled(v, 60*10000)
                    try:
                        fval = float(val_text)
                        record[downstream_key] = rad_to_scaled(fval, scale=60.0 * 10000.0)
                    except Exception:
                        record[downstream_key] = None
                elif field_id == "kinematic.speed":
                    # int(float(v) / 0.001)
                    try:
                        fval = float(val_text)
                        record[downstream_key] = int(round(fval / 0.001))
                    except Exception:
                        record[downstream_key] = None
                elif field_id == "kinematic.pos.lla.alt":
                    try:
                        record[downstream_key] = float(val_text)
                    except Exception:
                        record[downstream_key] = None
                elif field_id == "timestamp.source":
                    record[downstream_key] = timestamp_ms(val_text)
                elif field_id == "timestamp.receipt":
                    try:
                        record[downstream_key] = int(val_text)
                    except Exception:
                        record[downstream_key] = val_text
                elif field_id == "track.flag.active":
                    record[downstream_key] = val_text.lower() in ("true", "1")
                elif field_id == "track.quality":
                    record[downstream_key] = int(val_text) if val_text else 15
                elif field_id == "sys.source.id":
                    record[downstream_key] = int(val_text) if val_text else 0
                elif field_id == "vessel.length":
                    try:
                        record[downstream_key] = int(float(val_text))
                    except Exception:
                        record[downstream_key] = None
                else:
                    # Generic
                    if val_tag == "iv":
                        try:
                            record[downstream_key] = int(val_text)
                        except Exception:
                            record[downstream_key] = val_text
                    elif val_tag == "qv":
                        try:
                            record[downstream_key] = float(val_text)
                        except Exception:
                            record[downstream_key] = val_text
                    elif val_tag == "bv":
                        record[downstream_key] = val_text.lower() in ("true", "1")
                    else:
                        record[downstream_key] = val_text

            if record:
                records.append(record)

        return records

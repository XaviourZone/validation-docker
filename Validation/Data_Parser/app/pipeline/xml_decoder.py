"""
XML Decoder for Raytheon Athena CTrack XTrack XML payloads.

Decodes physical XML structures:
<ns2:XTracks>
    <ns2:XTrack verbose="true">
        <ns2:A>
            <id>sys.source.id</id>
            <iv>38</iv>
        </ns2:A>
        <ns2:A>
            <id>kinematic.pos.lla.lat</id>
            <qv u="rad">0.7524233669513108</qv>
        </ns2:A>
        ...
    </ns2:XTrack>
</ns2:XTracks>

Extracts:
- logical field name from <id>
- value element type (iv/sv/bv/qv/tv/pos)
- units where specified (e.g. u="rad", u="m/s", u="m", u="deg")
- raw string value (preserved for auditability)
- typed Python value (int, float, bool, str)
"""

import logging
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("parser.xml_decoder")


@dataclass
class DecodedField:
    """Represents a single decoded <A> field from XTrack XML."""
    id: str
    raw_type: str                  # 'iv', 'sv', 'bv', 'qv', 'tv', 'pos'
    unit: Optional[str]            # 'rad', 'm/s', 'm', 'deg', 't', etc.
    raw_value: str                 # Exact string in the element
    value: Any                     # Converted Python type (int, float, str, bool, dict)


@dataclass
class DecodedTrack:
    """Represents a single decoded <XTrack> element."""
    fields: Dict[str, DecodedField] = field(default_factory=dict)
    raw_xml: Optional[str] = None

    def get(self, field_id: str, default: Any = None) -> Any:
        f = self.fields.get(field_id)
        return f.value if f is not None else default

    def get_raw(self, field_id: str) -> Optional[str]:
        f = self.fields.get(field_id)
        return f.raw_value if f is not None else None

    def get_unit(self, field_id: str) -> Optional[str]:
        f = self.fields.get(field_id)
        return f.unit if f is not None else None

    def to_dict(self) -> Dict[str, Any]:
        """Return logical id -> typed value mapping."""
        return {k: v.value for k, v in self.fields.items()}


def parse_typed_element(elem: ET.Element) -> Tuple[str, Optional[str], str, Any]:
    """
    Parse a value element inside <A> (other than <id>).
    Returns (raw_type, unit, raw_value, typed_value).
    """
    # Strip namespace from tag
    tag = elem.tag.split("}")[-1].lower()
    unit = elem.attrib.get("u")
    text = (elem.text or "").strip()

    if tag == "iv":
        # Integer value
        try:
            val = int(float(text))
        except (ValueError, TypeError):
            val = None
        return ("iv", unit, text, val)

    elif tag == "sv":
        # String value
        return ("sv", unit, text, text)

    elif tag == "bv":
        # Boolean value
        val = text.lower() in ("true", "1", "t", "yes")
        return ("bv", unit, text, val)

    elif tag == "tv":
        # Timestamp value (epoch milliseconds)
        try:
            val = int(float(text))
        except (ValueError, TypeError):
            val = None
        return ("tv", unit, text, val)

    elif tag == "qv":
        # Quantity value (float numeric with optional unit)
        try:
            val = float(text)
        except (ValueError, TypeError):
            val = None
        return ("qv", unit, text, val)

    elif tag == "pos":
        # Coordinate pair: <pos><lat u="deg">15.1</lat><lon u="deg">73.1</lon></pos>
        lat_val = None
        lon_val = None
        lat_u = "deg"
        lon_u = "deg"

        for sub in elem:
            sub_tag = sub.tag.split("}")[-1].lower()
            if sub_tag == "lat":
                lat_u = sub.attrib.get("u", "deg")
                try:
                    lat_val = float((sub.text or "").strip())
                except Exception:
                    pass
            elif sub_tag == "lon":
                lon_u = sub.attrib.get("u", "deg")
                try:
                    lon_val = float((sub.text or "").strip())
                except Exception:
                    pass

        return ("pos", lat_u, text or f"{lat_val},{lon_val}", {"lat": lat_val, "lon": lon_val, "u": lat_u})

    else:
        # Fallback for unexpected element tags
        return (tag, unit, text, text)


def decode_xtrack_element(xtrack_elem: ET.Element) -> DecodedTrack:
    """Decode a single <ns2:XTrack> or <XTrack> element."""
    track = DecodedTrack()

    for a_elem in xtrack_elem:
        # Only process <A> elements
        if not a_elem.tag.endswith("A"):
            continue

        id_elem = None
        val_elem = None

        for child in a_elem:
            tag_name = child.tag.split("}")[-1]
            if tag_name == "id":
                id_elem = child
            else:
                val_elem = child

        if id_elem is None or not id_elem.text:
            continue

        logical_id = id_elem.text.strip()
        if not logical_id:
            continue

        if val_elem is not None:
            raw_type, unit, raw_val, typed_val = parse_typed_element(val_elem)
        else:
            raw_type, unit, raw_val, typed_val = ("empty", None, "", None)

        track.fields[logical_id] = DecodedField(
            id=logical_id,
            raw_type=raw_type,
            unit=unit,
            raw_value=raw_val,
            value=typed_val,
        )

    return track


def decode_xml_payload(payload: str) -> List[DecodedTrack]:
    """
    Decode an incoming XML string containing one or more <XTracks>/<XTrack> elements.
    Handles concatenated XML documents or multi-track collections.
    """
    tracks: List[DecodedTrack] = []
    if not payload or not payload.strip():
        return tracks

    # Split on multiple <?xml declarations if present in stream dumps
    chunks: List[str] = []
    if "<?xml" in payload:
        raw_chunks = payload.split("<?xml")
        for rc in raw_chunks:
            rc_str = rc.strip()
            if rc_str:
                chunks.append("<?xml " + rc_str if not rc_str.startswith("version=") else "<?xml " + rc_str)
    else:
        chunks = [payload]

    for chunk in chunks:
        # Clean up chunk
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            root = ET.fromstring(chunk)
        except ET.ParseError as e:
            # Attempt wrapping in root tag if fragmented
            try:
                wrapped = f"<Root xmlns:ns2='http://www.raytheon.com/athena/ctrack/xtrack/1.1'>{chunk}</Root>"
                root = ET.fromstring(wrapped)
            except Exception:
                log.warning(f"Failed to parse XML chunk: {e}")
                continue

        # Find all XTrack elements (with or without namespace)
        for elem in root.iter():
            if elem.tag.endswith("XTrack"):
                try:
                    dt = decode_xtrack_element(elem)
                    if dt.fields:
                        tracks.append(dt)
                except Exception as ex:
                    log.error(f"Error decoding XTrack element: {ex}")

    return tracks

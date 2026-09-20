"""Deterministic Athena XTrack XML generator.

Operational contract:
- generate_document() produces one XML document containing exactly one XTrack.
- The 41 canonical fields are emitted in deterministic master order.
- Missing values are omitted; no filler is fabricated merely to reach 41.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
import xml.sax.saxutils as saxutils
from typing import Any, Dict, List, Optional, Tuple

from .normalizer import LOGICAL_FIELDS_41, NormalizedRecord
from .source_registry import iso_to_epoch_ms, sanitize_string

NS_COMMON = "http://www.raytheon.com/athena/ctrack/common/1.1"
NS_XTRACK = "http://www.raytheon.com/athena/ctrack/xtrack/1.1"

FIELD_SPECS: Dict[str, Tuple[str, Optional[str]]] = {
    "ais.lenToBow": ("qv", "m"), "ais.lenToStern": ("qv", "m"),
    "ais.navStatus": ("sv", None), "ais.typeAndCargo": ("sv", None),
    "ais.widthToPort": ("qv", "m"), "ais.widthToStarboard": ("qv", "m"),
    "app.message.id": ("sv", None), "cat.annotation": ("sv", None),
    "cat.category": ("sv", None), "cat.identity": ("sv", None),
    "foreign.track.number": ("sv", None), "id.callsign": ("sv", None),
    "id.imo": ("iv", None), "id.mmsi": ("iv", None),
    "id.mmsi.destination": ("iv", None), "kinematic.course.true": ("qv", "rad"),
    "kinematic.flag.3d": ("bv", None), "kinematic.heading.true": ("qv", "rad"),
    "kinematic.pos.lla.alt": ("qv", "m"), "kinematic.pos.lla.lat": ("qv", "rad"),
    "kinematic.pos.lla.lon": ("qv", "rad"), "kinematic.speed": ("qv", "m/s"),
    "sys.source.id": ("iv", None), "sys.track.number": ("iv", None),
    "timestamp.receipt": ("tv", None), "timestamp.source": ("tv", None),
    "track.flag.active": ("bv", None), "track.quality": ("iv", None),
    "vessel.beam": ("qv", "m"), "vessel.description": ("sv", None),
    "vessel.draft": ("qv", "m"), "vessel.grosstonnage": ("qv", "t"),
    "vessel.length": ("qv", "m"), "vessel.name": ("sv", None),
    "vessel.remarks": ("sv", None), "voyage.arrival": ("sv", None),
    "voyage.departure": ("sv", None), "voyage.destination": ("sv", None),
    "voyage.eta": ("tv", None), "voyage.etd": ("tv", None),
    "voyage.origin": ("sv", None),
}
CANONICAL_ORDER = list(LOGICAL_FIELDS_41)


class XTrackXMLGenerator:
    def __init__(self, emit_uncontracted_extras: bool = False):
        self.emit_uncontracted_extras = bool(emit_uncontracted_extras)

    @staticmethod
    def _finite(value: Any) -> bool:
        try:
            return math.isfinite(float(value))
        except (TypeError, ValueError):
            return False

    @classmethod
    def _format_value(cls, val_tag: str, value: Any) -> Optional[str]:
        if value is None:
            return None
        # Missing string fields must be omitted, not emitted as empty <sv></sv>.
        if isinstance(value, str) and not value.strip():
            return None
        if val_tag == "bv":
            return "true" if bool(value) else "false"
        if val_tag == "tv":
            epoch = iso_to_epoch_ms(value)
            return str(epoch) if epoch is not None else None
        if val_tag == "iv":
            try:
                return str(int(float(value)))
            except (TypeError, ValueError, OverflowError):
                return None
        if val_tag == "qv":
            return str(value) if cls._finite(value) else None
        return saxutils.escape(sanitize_string(str(value)))

    def generate_document(self, record: NormalizedRecord) -> str:
        """Generate one XML document using the exact downstream wrapper shape."""
        logical = record.to_logical_dict()
        lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            f'<ns2:XTracks xmlns="{NS_COMMON}" xmlns:ns2="{NS_XTRACK}">',
            '    <ns2:XTrack verbose="true">',
        ]

        for field_id in CANONICAL_ORDER:
            val_tag, unit = FIELD_SPECS[field_id]
            value = logical.get(field_id)
            text = self._format_value(val_tag, value)
            if text is None:
                continue
            unit_attr = f' u="{unit}"' if unit else ''
            lines.extend([
                '        <ns2:A>',
                f'            <id>{field_id}</id>',
                f'            <{val_tag}{unit_attr}>{text}</{val_tag}>',
                '        </ns2:A>',
            ])

        lines.extend(['    </ns2:XTrack>', '</ns2:XTracks>'])
        return "\n".join(lines)
    def generate_single_xml(self, record: NormalizedRecord) -> str:
        return self.generate_document(record)

    def generate_batch_xml(self, records: List[NormalizedRecord]) -> str:
        records = list(records)
        if len(records) == 1:
            return self.generate_document(records[0])
        root = ET.Element(f"{{{NS_XTRACK}}}XTracks")
        root.set("xmlns", NS_COMMON)
        root.set("xmlns:ns2", NS_XTRACK)
        for record in records:
            one_root = ET.fromstring(self.generate_document(record))
            one_xtrack = next((n for n in one_root.iter() if n.tag.endswith("XTrack")), None)
            if one_xtrack is not None:
                root.append(one_xtrack)
        return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + ET.tostring(root, encoding="unicode")

    @staticmethod
    def validate_document(xml_text: str) -> int:
        root = ET.fromstring(xml_text)
        xtracks = [n for n in root.iter() if n.tag.endswith("XTrack")]
        if len(xtracks) != 1:
            raise ValueError(f"Expected exactly one XTrack, found {len(xtracks)}")
        seen = set()
        for a in xtracks[0]:
            if not a.tag.endswith("A"):
                continue
            ids = [c for c in a if c.tag.split("}")[-1] == "id"]
            if len(ids) != 1 or not (ids[0].text or "").strip():
                raise ValueError("Invalid A element")
            field_id = ids[0].text.strip()
            if field_id not in LOGICAL_FIELDS_41:
                raise ValueError(f"Unapproved field: {field_id}")
            if field_id in seen:
                raise ValueError(f"Duplicate field: {field_id}")
            seen.add(field_id)
        return len(seen)

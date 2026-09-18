"""
XML Generator constructing physical Raytheon Athena CTrack XTrack XML
conforming strictly to downstream consumer requirements.

Builds:
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<ns2:XTracks xmlns="http://www.raytheon.com/athena/ctrack/common/1.1" xmlns:ns2="http://www.raytheon.com/athena/ctrack/xtrack/1.1">
    <ns2:XTrack verbose="true">
        <ns2:A><id>sys.source.id</id><iv>38</iv></ns2:A>
        <ns2:A><id>kinematic.pos.lla.lat</id><qv u="rad">0.7524233669513108</qv></ns2:A>
        ...
    </ns2:XTrack>
</ns2:XTracks>
"""

import xml.sax.saxutils as saxutils
from typing import Any, Dict, List, Optional

from .normalizer import NormalizedRecord
from .source_registry import iso_to_epoch_ms, sanitize_string


# Field definitions: (id_name, element_tag, unit_attribute)
FIELD_SPECS = {
    # Integers
    "sys.source.id":         ("iv", None),
    "sys.track.number":      ("iv", None),
    "id.mmsi":               ("iv", None),
    "id.imo":                ("iv", None),
    "id.mmsi.destination":   ("iv", None),
    "track.quality":         ("iv", None),

    # Booleans
    "track.flag.active":     ("bv", None),
    "kinematic.flag.3d":     ("bv", None),

    # Quantities
    "kinematic.pos.lla.lat":  ("qv", "rad"),
    "kinematic.pos.lla.lon":  ("qv", "rad"),
    "kinematic.course.true":  ("qv", "rad"),
    "kinematic.heading.true": ("qv", "rad"),
    "kinematic.speed":        ("qv", "m/s"),
    "kinematic.pos.lla.alt":  ("qv", "m"),
    "vessel.length":          ("qv", "m"),
    "vessel.beam":            ("qv", "m"),
    "vessel.draft":           ("qv", "m"),
    "vessel.grosstonnage":    ("qv", "t"),
    "ais.lenToBow":           ("qv", "m"),
    "ais.lenToStern":         ("qv", "m"),
    "ais.widthToPort":        ("qv", "m"),
    "ais.widthToStarboard":   ("qv", "m"),
    "kinematic.rot":          ("qv", "deg/min"),

    # Timestamps
    "timestamp.source":       ("tv", None),
    "timestamp.receipt":      ("tv", None),
    "voyage.eta":             ("tv", None),
    "voyage.etd":             ("tv", None),

    # Strings
    "foreign.track.number":   ("sv", None),
    "app.message.id":         ("sv", None),
    "cat.category":           ("sv", None),
    "cat.identity":           ("sv", None),
    "cat.annotation":         ("sv", None),
    "id.callsign":            ("sv", None),
    "vessel.name":            ("sv", None),
    "vessel.description":     ("sv", None),
    "vessel.remarks":         ("sv", None),
    "ais.navStatus":          ("sv", None),
    "ais.typeAndCargo":       ("sv", None),
    "voyage.arrival":         ("sv", None),
    "voyage.departure":       ("sv", None),
    "voyage.destination":     ("sv", None),
    "voyage.origin":          ("sv", None),
}


class XTrackXMLGenerator:
    """Constructs XTrack XML documents conforming to Raytheon CTrack schema."""

    NS_COMMON = "http://www.raytheon.com/athena/ctrack/common/1.1"
    NS_XTRACK = "http://www.raytheon.com/athena/ctrack/xtrack/1.1"

    def __init__(self):
        pass

    def generate_single_xml(self, record: NormalizedRecord) -> str:
        """Generate XML string for a single normalized record."""
        return self.generate_batch_xml([record])

    def generate_batch_xml(self, records: List[NormalizedRecord]) -> str:
        """Generate XML string containing multiple <ns2:XTrack> elements."""
        lines: List[str] = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            f'<ns2:XTracks xmlns="{self.NS_COMMON}" xmlns:ns2="{self.NS_XTRACK}">',
        ]

        for rec in records:
            lines.append('    <ns2:XTrack verbose="true">')

            logical_dict = rec.to_logical_dict()

            # Append kinematic.rot if available
            if rec.kinematic_rot is not None:
                logical_dict["kinematic.rot"] = rec.kinematic_rot

            for field_id, (val_tag, unit) in FIELD_SPECS.items():
                val = logical_dict.get(field_id)
                if val is None:
                    continue

                # Format value string
                if val_tag == "bv":
                    val_str = "true" if val else "false"
                elif val_tag == "tv":
                    epoch_val = iso_to_epoch_ms(val)
                    if epoch_val is not None:
                        val_str = str(epoch_val)
                    else:
                        continue
                elif val_tag == "iv":
                    try:
                        val_str = str(int(float(val)))
                    except (ValueError, TypeError):
                        continue
                elif val_tag == "qv":
                    val_str = str(val)
                else:
                    clean_str = sanitize_string(str(val))
                    val_str = saxutils.escape(clean_str)

                unit_attr = f' u="{unit}"' if unit else ""
                lines.append(f'        <ns2:A><id>{field_id}</id><{val_tag}{unit_attr}>{val_str}</{val_tag}></ns2:A>')

            lines.append('    </ns2:XTrack>')

        lines.append('</ns2:XTracks>')
        return "\n".join(lines)

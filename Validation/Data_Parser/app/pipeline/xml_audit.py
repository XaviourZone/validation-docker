"""XML contract audit helpers.

These functions are intentionally independent of the live parser so they can
be used against golden XML files, spool directories, and source test runs.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Iterable, List

from .normalizer import LOGICAL_FIELDS_41


def audit_xml(xml_text: str) -> Dict[str, object]:
    root = ET.fromstring(xml_text)
    xtracks = [e for e in root.iter() if e.tag.endswith("XTrack")]
    if len(xtracks) != 1:
        raise ValueError(f"Expected exactly one XTrack; found {len(xtracks)}")

    fields: List[str] = []
    for a in xtracks[0]:
        if not a.tag.endswith("A"):
            continue
        id_nodes = [e for e in a if e.tag.split("}")[-1] == "id"]
        if len(id_nodes) != 1 or not (id_nodes[0].text or "").strip():
            raise ValueError("A element without exactly one id")
        field_id = id_nodes[0].text.strip()
        if field_id not in LOGICAL_FIELDS_41:
            raise ValueError(f"Field outside 41-field contract: {field_id}")
        fields.append(field_id)

    if len(fields) != len(set(fields)):
        raise ValueError("Duplicate canonical field in XTrack")

    present = set(fields)
    return {
        "xtrack_count": 1,
        "tag_count": len(fields),
        "present": fields,
        "missing": [f for f in LOGICAL_FIELDS_41 if f not in present],
        "coverage_percent": round((len(present) / len(LOGICAL_FIELDS_41)) * 100.0, 2),
    }


def audit_file(path: Path) -> Dict[str, object]:
    return audit_xml(path.read_text(encoding="utf-8"))


def audit_directory(directory: Path) -> List[Dict[str, object]]:
    results = []
    for path in sorted(directory.glob("*.xml")):
        result = audit_file(path)
        result["file"] = str(path)
        results.append(result)
    return results

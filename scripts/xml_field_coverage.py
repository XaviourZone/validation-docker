#!/usr/bin/env python3
"""Generate per-XML-record canonical 41-field coverage CSV."""

from __future__ import annotations

import argparse
import csv
import xml.etree.ElementTree as ET
from pathlib import Path

from Validation.Data_Parser.app.pipeline.normalizer import LOGICAL_FIELDS_41


def extract_fields(xml_text: str) -> set[str]:
    root = ET.fromstring(xml_text)
    fields: set[str] = set()
    for node in root.iter():
        if not node.tag.endswith("XTrack"):
            continue
        for a in node:
            if not a.tag.endswith("A"):
                continue
            for child in a:
                if child.tag.split("}")[-1] == "id" and child.text:
                    fields.add(child.text.strip())
    return fields


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate XML field coverage CSV")
    parser.add_argument("xml_dir", type=Path)
    parser.add_argument("output_csv", type=Path)
    args = parser.parse_args()

    files = sorted(args.xml_dir.glob("*.xml"))
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)

    field_names = list(LOGICAL_FIELDS_41)
    with args.output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["xml_file", "xtrack_count", "present_count", "absent_count", *field_names])

        for path in files:
            text = path.read_text(encoding="utf-8")
            root = ET.fromstring(text)
            xtrack_count = sum(1 for node in root.iter() if node.tag.endswith("XTrack"))
            present = extract_fields(text)
            row = [
                path.name,
                xtrack_count,
                len(present),
                len(field_names) - len(present),
                *["PRESENT" if field in present else "ABSENT" for field in field_names],
            ]
            writer.writerow(row)

    print(f"Generated coverage report for {len(files)} XML documents: {args.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

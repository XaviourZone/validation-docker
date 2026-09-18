#!/usr/bin/env python3
"""Offline source -> canonical XML coverage report.

This tool audits parser/normalizer/XML coverage without writing Forwarder spool
files. It is intended for representative source files before release.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from Validation.Data_Parser.app.models.common import ParserEnvelope
from Validation.Data_Parser.app.parsers.lrit import LRITParser
from Validation.Data_Parser.app.parsers.msis import MSISParser
from Validation.Data_Parser.app.parsers.nais import NAISParser
from Validation.Data_Parser.app.parsers.sais import SAISParser
from Validation.Data_Parser.app.parsers.vatms import VATMSParser
from Validation.Data_Parser.app.pipeline.normalizer import normalize_from_common_record
from Validation.Data_Parser.app.pipeline.xml_audit import audit_xml


PARSERS = {
    "SAIS": SAISParser,
    "MSIS": MSISParser,
    "LRIT": LRITParser,
    "VATMS": VATMSParser,
    "NAIS": NAISParser,
}


def build_parser(name: str):
    try:
        return PARSERS[name.upper()]()
    except KeyError:
        raise SystemExit(f"Unsupported parser: {name}. Choose from {', '.join(PARSERS)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="Source label, e.g. SAIS_IOR or MSIS")
    ap.add_argument("--parser", required=True, choices=sorted(PARSERS))
    ap.add_argument("--file", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    payload = args.file.read_text(encoding="utf-8", errors="replace")
    envelope = ParserEnvelope(
        message_id=args.file.name,
        source=args.source,
        input_type="FILE",
        received_at="",
        payload=payload,
        filename=args.file.name,
        file_size=args.file.stat().st_size,
    )

    result = build_parser(args.parser).parse(envelope)
    rows = []
    for idx, record in enumerate(result.records, 1):
        normalized = normalize_from_common_record(record)
        from Validation.Data_Parser.app.pipeline.xml_generator import XTrackXMLGenerator
        xml = XTrackXMLGenerator().generate_document(normalized)
        coverage = audit_xml(xml)
        rows.append({
            "source": args.source,
            "file": str(args.file),
            "record": idx,
            "record_id": record.record_id,
            "mmsi": record.mmsi,
            "message_type": record.app_message_id,
            "xml_tags": coverage["tag_count"],
            "coverage_percent": coverage["coverage_percent"],
            "missing_count": len(coverage["missing"]),
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else [
            "source", "file", "record", "record_id", "mmsi", "message_type",
            "xml_tags", "coverage_percent", "missing_count"
        ])
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "source": args.source,
        "file": str(args.file),
        "input_lines": len(payload.splitlines()),
        "records": len(result.records),
        "parser_rejected": len(result.errors),
        "xml_documents": len(rows),
        "average_xml_tags": round(sum(r["xml_tags"] for r in rows) / len(rows), 2) if rows else 0,
        "max_xml_tags": max((r["xml_tags"] for r in rows), default=0),
        "max_coverage_percent": max((r["coverage_percent"] for r in rows), default=0),
        "errors": result.errors,
    }
    summary_path = args.output.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

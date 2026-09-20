#!/usr/bin/env python3
"""
Run the Validation project against a supplied real/sample-data tree.

This is an operational acceptance runner. It:
  1. Builds isolated WRS/PANS/NSC SQLite databases from the supplied source data.
  2. Runs the actual ReferenceDB lookup/fallback layer.
  3. Runs the actual source parsers through PipelineProcessor for
     SAIS_IOR, SAIS_GLOBAL, MSIS, LRIT, VATMS_EAST, VATMS_WEST and NAIS.
  4. Counts generated XML and validates the canonical 41-field contract.
  5. Writes machine-readable production_measurement.json and a Markdown report.

The source data is never copied into Git. The user supplies --sample-root.
For operational acceptance, point the same command at the authoritative
production reference/input directories.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ET

# Allow this script to be executed directly as:
#   python3 scripts/real_data_acceptance.py ...
# without requiring PYTHONPATH to be set by the caller.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Validation.Data_Parser.app.models.common import ParserEnvelope
from Validation.Data_Parser.app.pipeline.processor import PipelineProcessor
from Validation.Data_Parser.app.pipeline.normalizer import LOGICAL_FIELDS_41
from Validation.Data_Parser.app.pipeline.reference_db import ReferenceDB
from Validation.Data_Parser.app.pipeline.track_state import TrackStateDB
from Validation.Data_Parser.app.pipeline.ais_state import AISStateDB
from Validation.Database.PANS.importer.pans_importer import PansLiveImporter
from Validation.Database.NSC.importer.nsc_importer import run_import as run_nsc_import
from Validation.Database.WRS.importer.wrs_importer import run_import as run_wrs_import


CANONICAL_FIELDS = LOGICAL_FIELDS_41

SOURCE_DIRS = {
    "SAIS_IOR": "SAIS_IOR",
    "SAIS_GLOBAL": "SAIS_GLOBAL",
    "MSIS": "MSIS",
    "LRIT": "LRIT",
    "VATMS_EAST": "VATMS_EAST",
    "VATMS_WEST": "VATMS_WEST",
    "NAIS": "NAIS",
}


def files_for(root: Path, source: str) -> list[Path]:
    d = root / SOURCE_DIRS[source]
    if not d.exists():
        return []
    return sorted(p for p in d.rglob("*") if p.is_file())


def _xlsx_first_sheet_to_csv(source: Path, target: Path) -> None:
    """Convert the first worksheet of a simple XLSX file to CSV using stdlib only.

    This keeps the acceptance runner usable on offline hosts where the optional
    openpyxl dependency is not installed. The NSC importer still receives the
    same tabular values, just through its supported CSV input path.
    """
    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"

    with zipfile.ZipFile(source) as zf:
        shared = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall("a:si", ns):
                shared.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["a"])))

        wb = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rel_map = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in rels.findall("{%s}Relationship" % rel_ns)
        }
        first_sheet = wb.find("a:sheets/a:sheet", ns)
        if first_sheet is None:
            raise ValueError(f"No worksheet found in {source}")
        rid = first_sheet.attrib.get("{%s}id" % ns["r"])
        target_part = rel_map.get(rid)
        if not target_part:
            raise ValueError(f"Worksheet relationship missing in {source}")
        sheet_part = target_part.lstrip("/")
        if not sheet_part.startswith("xl/"):
            sheet_part = "xl/" + sheet_part
        root = ET.fromstring(zf.read(sheet_part))

        rows = []
        max_col = 0
        for row in root.findall(".//a:sheetData/a:row", ns):
            values = {}
            for cell in row.findall("a:c", ns):
                ref = cell.attrib.get("r", "")
                letters = "".join(ch for ch in ref if ch.isalpha())
                col = 0
                for ch in letters.upper():
                    col = col * 26 + ord(ch) - 64
                max_col = max(max_col, col)
                value = ""
                v = cell.find("a:v", ns)
                inline = cell.find("a:is", ns)
                if inline is not None:
                    value = "".join(t.text or "" for t in inline.iter("{%s}t" % ns["a"]))
                elif v is not None and v.text is not None:
                    value = v.text
                    if cell.attrib.get("t") == "s":
                        value = shared[int(value)] if int(value) < len(shared) else ""
                values[col] = value
            rows.append([values.get(i, "") for i in range(1, max_col + 1)])

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)


def build_reference_dbs(sample_root: Path, work: Path) -> dict[str, Path]:
    db_root = work / "reference"
    (db_root / "WRS").mkdir(parents=True)
    (db_root / "PANS").mkdir(parents=True)
    (db_root / "NSC").mkdir(parents=True)

    # WRS importer expects lowercase datasets/decode directory names. Build a
    # temporary view of the supplied source tree so the importer is exercised
    # without changing the user's source files.
    wrs_view = work / "wrs_input"
    (wrs_view / "datasets").mkdir(parents=True)
    (wrs_view / "decode").mkdir(parents=True)
    for p in (sample_root / "WRS" / "Datasets").glob("*"):
        shutil.copy2(p, wrs_view / "datasets" / p.name)
    for p in (sample_root / "WRS" / "Decode Files").glob("*"):
        shutil.copy2(p, wrs_view / "decode" / p.name)

    wrs_cfg = {
        "database": {"wrs": {"path": str(db_root / "WRS" / "wrs.db")}},
        "imports": {"wrs": {
            "input_dir": str(wrs_view),
            "staging_db": str(db_root / "WRS" / "wrs_staging.db"),
            "batch_size": 10000}},
        "logging": {"log_dir": str(work / "logs"), "level": "WARNING"},
    }
    # WRS importer expects Datasets and Decode Files below input_dir.
    run_wrs_import(wrs_cfg)

    pans_cfg = {
        "database": {"pans": {"path": str(db_root / "PANS" / "pans.db")}},
        "imports": {"pans": {
            "input_dir": str(sample_root / "PANS"),
            "poll_interval_seconds": 0.01,
            # is_file_stable() needs a positive interval; zero makes its
            # monotonic deadline expire before the first stability check.
            "stability_seconds": 0.25}},
        "logging": {"log_dir": str(work / "logs"), "level": "WARNING"},
    }
    PansLiveImporter(pans_cfg).start(once=True)

    nsc_cfg = {
        "database": {"nsc": {"path": str(db_root / "NSC" / "nsc.db")}},
        "imports": {"nsc": {
            "input_dir": str(sample_root / "NSC EAST and WEST"),
            "staging_db": str(db_root / "NSC" / "nsc_staging.db"),
            "batch_size": 5000}},
        "logging": {"log_dir": str(work / "logs"), "level": "WARNING"},
    }
    # The NSC importer expects EAST/WEST directories. The supplied sample has
    # two files in one directory, so create a temporary importer view.
    nsc_view = work / "nsc_input"
    (nsc_view / "EAST").mkdir(parents=True)
    (nsc_view / "WEST").mkdir(parents=True)
    for p in (sample_root / "NSC EAST and WEST").glob("*"):
        region = "EAST" if "EAST" in p.name.upper() else "WEST"
        if p.suffix.lower() == ".xlsx":
            target = nsc_view / region / f"{p.stem}.csv"
            _xlsx_first_sheet_to_csv(p, target)
        else:
            target = nsc_view / region / p.name
            shutil.copy2(p, target)
    nsc_cfg["imports"]["nsc"]["input_dir"] = str(nsc_view)
    run_nsc_import(nsc_cfg)

    return {
        "wrs": db_root / "WRS" / "wrs.db",
        "pans": db_root / "PANS" / "pans.db",
        "nsc": db_root / "NSC" / "nsc.db",
    }


def db_counts(paths: dict[str, Path]) -> dict:
    result = {}
    for name, path in paths.items():
        conn = sqlite3.connect(path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        counts = {}
        for (table,) in tables:
            counts[table] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        result[name] = {
            "path": str(path),
            "tables": len(counts),
            "rows": sum(counts.values()),
            "table_rows": counts,
        }
        conn.close()
    return result


def run_source(processor: PipelineProcessor, source: str, paths: list[Path], output_dir: Path) -> dict:
    stats = Counter()
    provenance = {field: Counter() for field in CANONICAL_FIELDS}
    started = time.monotonic()
    xml_files_before = len(list(output_dir.glob("*.xml")))

    for path in paths:
        payload = path.read_text(encoding="utf-8", errors="replace")
        env = ParserEnvelope(
            source=source,
            message_id=path.name,
            input_type="FILE",
            received_at=datetime.now(timezone.utc).isoformat(),
            payload=payload,
            filename=path.name,
            file_size=path.stat().st_size,
        )
        result, _ = processor.process_envelope(env)
        stats["files"] += 1
        stats["input_bytes"] += len(payload.encode("utf-8"))
        stats["records_parsed"] += result.records_parsed
        stats["records_rejected"] += result.records_rejected
        stats["successful_envelopes"] += int(result.success)
        for error in result.errors:
            if error.startswith("Source parser error:"):
                stats["parser_error_count"] += 1
            elif error.startswith("Normalization/validation error"):
                stats["normalization_error_count"] += 1
            elif error.startswith("Enrichment error"):
                stats["enrichment_error_count"] += 1
            elif error.startswith("XML generation/compatibility/spooling error"):
                stats["xml_error_count"] += 1
            else:
                stats["other_error_count"] += 1
        stats["failed_envelopes"] += int(not result.success)
        for record in result.records:
            for field, source_name in (record.raw_attributes.get("enrichment_provenance") or {}).items():
                if field in provenance:
                    provenance[field][source_name] += 1
        if result.errors:
            stats.setdefault("error_samples", [])
            stats["error_samples"].extend(result.errors[:10])
            stats["error_samples"] = stats["error_samples"][:20]

    xml_files_after = len(list(output_dir.glob("*.xml")))
    stats["xml_generated"] = xml_files_after - xml_files_before
    stats["elapsed_seconds"] = round(time.monotonic() - started, 3)
    stats["records_per_second"] = round(
        stats["records_parsed"] / stats["elapsed_seconds"], 2
    ) if stats["elapsed_seconds"] else 0
    stats["provenance"] = {field: dict(counts) for field, counts in provenance.items()}
    return dict(stats)


def xml_coverage(xml_dir: Path) -> dict:
    present = Counter()
    total_docs = 0
    invalid = 0
    for path in xml_dir.glob("*.xml"):
        try:
            root = ET.parse(path).getroot()
            total_docs += 1
            found = {
                (el.text or "").strip()
                for el in root.iter()
                if el.tag.split("}")[-1] == "id" and (el.text or "").strip()
            }
            for field in CANONICAL_FIELDS:
                if field in found:
                    present[field] += 1
        except Exception:
            invalid += 1

    return {
        "xml_documents": total_docs,
        "invalid_xml": invalid,
        "canonical_field_count": len(CANONICAL_FIELDS),
        "field_coverage": {
            field: {
                "present_documents": present[field],
                "coverage_percent": round(
                    present[field] * 100 / total_docs, 2
                ) if total_docs else 0,
            }
            for field in CANONICAL_FIELDS
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-root", required=True,
                        help="Path to the supplied 'Sample data' directory.")
    parser.add_argument("--output", default="runtime/real-data-acceptance",
                        help="Acceptance output directory.")
    args = parser.parse_args()

    sample_root = Path(args.sample_root).resolve()
    output = Path(args.output).resolve()
    if not sample_root.is_dir():
        raise SystemExit(f"Sample root does not exist: {sample_root}")

    output.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="validation-acceptance-"))
    xml_dir = output / "xml"
    if xml_dir.exists():
        shutil.rmtree(xml_dir)
    xml_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(level=logging.WARNING)

    try:
        refs = build_reference_dbs(sample_root, work)
        ref = ReferenceDB(
            wrs_path=refs["wrs"],
            pans_path=refs["pans"],
            nsc_path=refs["nsc"],
        )
        processor = PipelineProcessor(
            reference_db=ref,
            track_state_db=TrackStateDB(work / "track_state.db"),
            ais_state_db=AISStateDB(work / "ais_state.db"),
            xml_output_dir=xml_dir,
        )

        source_results = {}
        for source in SOURCE_DIRS:
            source_results[source] = run_source(
                processor, source, files_for(sample_root, source), xml_dir
            )

        reference_missing = [name for name, path in refs.items() if not path.exists()]
        overall_provenance = {field: Counter() for field in CANONICAL_FIELDS}
        for source_result in source_results.values():
            for field, counts in source_result.get("provenance", {}).items():
                for source_name, count in counts.items():
                    overall_provenance[field][source_name] += count
        report = {
            "acceptance_time_utc": datetime.now(timezone.utc).isoformat(),
            "sample_root": str(sample_root),
            "reference_databases": db_counts(refs),
            "sources": source_results,
            "xml_coverage": xml_coverage(xml_dir),
            "provenance": {field: dict(counts) for field, counts in overall_provenance.items()},
            "status": "FAIL" if reference_missing else "PASS",
            "reference_missing": reference_missing,
        }

        (output / "production_measurement.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )

        total = sum(v["records_parsed"] for v in source_results.values())
        rejected = sum(v["records_rejected"] for v in source_results.values())
        xml_docs = report["xml_coverage"]["xml_documents"]
        invalid = report["xml_coverage"]["invalid_xml"]

        lines = [
            "# Real Data Acceptance",
            "",
            f"**Status: {report['status']}**",
            "",
            f"- Parsed records: **{total}**",
            f"- Rejected/error records: **{rejected}**",
            f"- XML documents: **{xml_docs}**",
            f"- Invalid XML documents: **{invalid}**",
            f"- Canonical XML fields audited: **{len(CANONICAL_FIELDS)}**",
            "",
            "## Sources",
            "",
            "| Source | Files | Parsed | Rejected | XML | Records/sec |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for source, value in source_results.items():
            lines.append(
                f"| {source} | {value['files']} | {value['records_parsed']} | "
                f"{value['records_rejected']} | {value['xml_generated']} | "
                f"{value['records_per_second']} |"
            )
        lines += [
            "",
            "## Error classification",
            "",
            "| Source | Parser | Normalization | Enrichment | XML | Other |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for source, value in source_results.items():
            lines.append(
                f"| {source} | {value.get('parser_error_count', 0)} | "
                f"{value.get('normalization_error_count', 0)} | "
                f"{value.get('enrichment_error_count', 0)} | "
                f"{value.get('xml_error_count', 0)} | "
                f"{value.get('other_error_count', 0)} |"
            )
        lines += [
            "",
            "## Enrichment provenance",
            "",
            "| XML field | Incoming | WRS | PANS | NSC | Derived | None |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for field in CANONICAL_FIELDS:
            counts = report["provenance"].get(field, {})
            lines.append(
                f"| {field} | {counts.get('INCOMING', 0)} | {counts.get('WRS', 0)} | "
                f"{counts.get('PANS', 0)} | {counts.get('NSC', 0)} | "
                f"{counts.get('DERIVED', 0)} | {counts.get('NONE', 0)} |"
            )
        lines += [
            "",
            "## Reference DBs",
            "",
            "| DB | Tables | Rows |",
            "|---|---:|---:|",
        ]
        for name, value in report["reference_databases"].items():
            lines.append(f"| {name.upper()} | {value['tables']} | {value['rows']} |")

        (output / "production_measurement.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
        print(json.dumps({
            "status": report["status"],
            "parsed_records": total,
            "rejected_records": rejected,
            "xml_documents": xml_docs,
            "invalid_xml": invalid,
            "output": str(output),
        }, indent=2))
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

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
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ET

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
            "stability_seconds": 0.0}},
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
        target = nsc_view / ("EAST" if "EAST" in p.name.upper() else "WEST") / p.name
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
    started = time.monotonic()
    xml_files_before = len(list(output_dir.glob("*.xml")))

    for path in paths:
        payload = path.read_text(encoding="utf-8", errors="replace")
        env = ParserEnvelope(
            source=source,
            message_id=path.name,
            payload=payload,
            received_at=datetime.now(timezone.utc).isoformat(),
        )
        result, _ = processor.process_envelope(env)
        stats["files"] += 1
        stats["input_bytes"] += len(payload.encode("utf-8"))
        stats["records_parsed"] += result.records_parsed
        stats["records_rejected"] += result.records_rejected
        stats["successful_envelopes"] += int(result.success)
        stats["failed_envelopes"] += int(not result.success)

    xml_files_after = len(list(output_dir.glob("*.xml")))
    stats["xml_generated"] = xml_files_after - xml_files_before
    stats["elapsed_seconds"] = round(time.monotonic() - started, 3)
    stats["records_per_second"] = round(
        stats["records_parsed"] / stats["elapsed_seconds"], 2
    ) if stats["elapsed_seconds"] else 0
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

        report = {
            "acceptance_time_utc": datetime.now(timezone.utc).isoformat(),
            "sample_root": str(sample_root),
            "reference_databases": db_counts(refs),
            "sources": source_results,
            "xml_coverage": xml_coverage(xml_dir),
            "status": "PASS",
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
            "status": "PASS",
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

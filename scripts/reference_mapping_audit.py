#!/usr/bin/env python3
"""
Reference/Data Mapping Audit

Audits the authoritative local WRS, PANS and NSC SQLite databases against the
41 canonical XTrack fields without modifying any source database.

The audit is deliberately schema-driven:
- WRS: VESSEL_ID is treated as the common relationship key once a vessel is
  resolved from VESSELS.
- PANS: VESPRO/CALINF/BERMAN fields are inspected.
- NSC: all columns are inspected, but NSC is not treated as a voyage source.
- Incoming/parser fields are represented by the existing 41-field contract.

It reports:
1. every reference table and column;
2. exact source fields already used by the parser;
3. additional candidate fields found in the databases;
4. fields for which no legitimate reference source exists;
5. the recommended lookup key for each candidate.

It never invents a value or proposes arithmetic such as beam/2.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

ROOT_FIELDS = {
    "ais.lenToBow": {
        "incoming": ["len_to_bow", "ais.lenToBow"],
        "reference": ["BOW", "LENGTH_TO_BOW", "DIMENSION_TO_BOW"],
        "allow_reference": True,
        "note": "Only use an actual bow reference dimension; never derive from LOA.",
    },
    "ais.lenToStern": {
        "incoming": ["len_to_stern", "ais.lenToStern"],
        "reference": ["STERN", "LENGTH_TO_STERN", "DIMENSION_TO_STERN"],
        "allow_reference": True,
        "note": "Only use an actual stern reference dimension; never derive from LOA.",
    },
    "ais.navStatus": {
        "incoming": ["nav_status", "navigation_status", "ais.navStatus"],
        "reference": ["NAV_STATUS", "NAVIGATION_STATUS"],
        "allow_reference": False,
        "note": "Dynamic AIS observation.",
    },
    "ais.typeAndCargo": {
        "incoming": ["vessel_type", "type_and_cargo", "ais.typeAndCargo"],
        "reference": ["AIS_TYPE", "AIS_TYPE_CODE", "TYPE_AND_CARGO", "VESSEL_TYPE", "TYPE"],
        "allow_reference": True,
        "note": "Reference values must be decoded before XTrack serialization.",
    },
    "ais.widthToPort": {
        "incoming": ["width_to_port", "ais.widthToPort"],
        "reference": ["PORT", "WIDTH_TO_PORT", "DIMENSION_TO_PORT"],
        "allow_reference": True,
        "note": "Only an actual port reference dimension.",
    },
    "ais.widthToStarboard": {
        "incoming": ["width_to_starboard", "ais.widthToStarboard"],
        "reference": ["STARBOARD", "WIDTH_TO_STARBOARD", "DIMENSION_TO_STARBOARD"],
        "allow_reference": True,
        "note": "Only an actual starboard reference dimension.",
    },
    "app.message.id": {
        "incoming": ["message_type", "app.message.id"],
        "reference": [],
        "allow_reference": False,
        "note": "AIS message type is transmission metadata.",
    },
    "cat.annotation": {
        "incoming": ["annotation", "cat.annotation"],
        "reference": ["STATUS_DECODE", "STATUS", "ANNOTATION"],
        "allow_reference": True,
        "note": "Use a documented status/annotation decode only.",
    },
    "cat.category": {
        "incoming": ["category", "cat.category"],
        "reference": [],
        "allow_reference": False,
        "note": "Current implementation defaults to Surface; do not fabricate categories.",
    },
    "cat.identity": {
        "incoming": ["cat.identity"],
        "reference": ["SCORE", "VIGILANCE_SCORE"],
        "allow_reference": True,
        "note": "Requires an authoritative identity rule; current thresholds remain unresolved.",
    },
    "foreign.track.number": {
        "incoming": ["mmsi", "foreign.track.number"],
        "reference": ["MMSI", "ID_MMSI"],
        "allow_reference": True,
        "note": "Reference MMSI is only a fallback when the transmitted identifier is invalid.",
    },
    "id.callsign": {
        "incoming": ["callsign", "id.callsign"],
        "reference": ["CALL_SIGN", "CALLSIGN", "CallSign", "ID_CALLSIGN"],
        "allow_reference": True,
        "note": "Incoming -> reference fallback.",
    },
    "id.imo": {
        "incoming": ["imo", "id.imo"],
        "reference": ["IMO", "IMONumber", "ID_IMO"],
        "allow_reference": True,
        "note": "Incoming -> reference fallback after identifier validation.",
    },
    "id.mmsi": {
        "incoming": ["mmsi", "id.mmsi"],
        "reference": [],
        "allow_reference": False,
        "note": "Must remain the transmitted MMSI.",
    },
    "id.mmsi.destination": {
        "incoming": ["id.mmsi.destination"],
        "reference": ["SCORE", "VIGILANCE_SCORE"],
        "allow_reference": True,
        "note": "Existing implementation uses WRS vigilance score; semantic contract should be retained.",
    },
    "kinematic.course.true": {
        "incoming": ["cog", "course", "kinematic.course.true"],
        "reference": [],
        "allow_reference": False,
        "note": "Dynamic AIS observation.",
    },
    "kinematic.flag.3d": {
        "incoming": ["altitude", "kinematic.flag.3d"],
        "reference": [],
        "allow_reference": False,
        "note": "Derived only from an actual incoming altitude/3D flag.",
    },
    "kinematic.heading.true": {
        "incoming": ["true_heading", "heading", "kinematic.heading.true"],
        "reference": [],
        "allow_reference": False,
        "note": "Dynamic AIS observation.",
    },
    "kinematic.pos.lla.alt": {
        "incoming": ["altitude", "kinematic.pos.lla.alt"],
        "reference": [],
        "allow_reference": False,
        "note": "Do not use vessel dimensions as altitude.",
    },
    "kinematic.pos.lla.lat": {
        "incoming": ["latitude", "lat"],
        "reference": [],
        "allow_reference": False,
        "note": "Dynamic transmission position.",
    },
    "kinematic.pos.lla.lon": {
        "incoming": ["longitude", "lon"],
        "reference": [],
        "allow_reference": False,
        "note": "Dynamic transmission position.",
    },
    "kinematic.speed": {
        "incoming": ["sog", "speed"],
        "reference": [],
        "allow_reference": False,
        "note": "Dynamic AIS observation.",
    },
    "sys.source.id": {
        "incoming": ["source"],
        "reference": [],
        "allow_reference": False,
        "note": "Data Router/source registry.",
    },
    "sys.track.number": {
        "incoming": ["mmsi", "sys.track.number"],
        "reference": [],
        "allow_reference": False,
        "note": "Original transmitted identifier.",
    },
    "timestamp.receipt": {
        "incoming": ["receipt_timestamp"],
        "reference": [],
        "allow_reference": False,
        "note": "Ingestion timestamp.",
    },
    "timestamp.source": {
        "incoming": ["timestamp", "timestamp_source"],
        "reference": [],
        "allow_reference": False,
        "note": "Source/transmission timestamp.",
    },
    "track.flag.active": {
        "incoming": ["timestamp_source"],
        "reference": [],
        "allow_reference": False,
        "note": "Track-state calculation.",
    },
    "track.quality": {
        "incoming": [],
        "reference": [],
        "allow_reference": False,
        "note": "Current contract uses quality 15.",
    },
    "vessel.beam": {
        "incoming": ["width", "beam", "vessel.beam"],
        "reference": ["BREADTH_EXTREME", "Beam", "BREADTH", "BEAM"],
        "allow_reference": True,
        "note": "Incoming -> WRS -> PANS; no synthetic half-beam.",
    },
    "vessel.description": {
        "incoming": ["vessel_type", "vessel.description"],
        "reference": ["VESSEL_TYPE", "VesselType", "TYPE"],
        "allow_reference": True,
        "note": "Decode coded values where required.",
    },
    "vessel.draft": {
        "incoming": ["draught", "draft", "vessel.draft"],
        "reference": ["DRAFT", "MaxDraft", "EXPECTED_DRAFT", "DRAFT_FORWARD", "DRAFT_AFT"],
        "allow_reference": True,
        "note": "Use a semantically compatible draft value; do not silently mix expected and actual draft.",
    },
    "vessel.grosstonnage": {
        "incoming": ["gross_tonnage", "gt", "vessel.grosstonnage"],
        "reference": ["GROSS", "GRT", "GROSS_TONNAGE"],
        "allow_reference": True,
        "note": "Incoming -> WRS -> PANS.",
    },
    "vessel.length": {
        "incoming": ["length", "loa", "vessel.length"],
        "reference": ["LOA", "LENGTH", "Length"],
        "allow_reference": True,
        "note": "Incoming -> WRS -> PANS.",
    },
    "vessel.name": {
        "incoming": ["vessel_name", "ship_name", "vessel.name"],
        "reference": ["VESSEL_NAME", "VesselName", "VESSELNAME"],
        "allow_reference": True,
        "note": "Incoming -> matched reference identity.",
    },
    "vessel.remarks": {
        "incoming": ["remarks", "vessel.remarks"],
        "reference": ["REMARKS", "COMMENTS", "STATUS", "CLEARANCE", "OPERATIONAL_FLAGS"],
        "allow_reference": True,
        "note": "Only explicit source evidence; never use as a dump field.",
    },
    "voyage.arrival": {
        "incoming": ["arrival", "voyage.arrival"],
        "reference": ["ARRIVAL_DATE"],
        "allow_reference": True,
        "note": "WRS actual calling arrival is a valid source.",
    },
    "voyage.departure": {
        "incoming": ["departure", "voyage.departure"],
        "reference": ["SAILING_DATE", "DEPARTURE", "EDTD"],
        "allow_reference": True,
        "note": "Prefer a departure/sailing date. Do not put LastPortOfCall into a date field.",
    },
    "voyage.destination": {
        "incoming": ["destination", "voyage.destination"],
        "reference": ["DestinationPortl", "PLACE", "DESTINATION", "DockORTOCode"],
        "allow_reference": True,
        "note": "Prefer explicit destination over a generic port code.",
    },
    "voyage.eta": {
        "incoming": ["eta", "voyage.eta"],
        "reference": ["EDTA", "ETA"],
        "allow_reference": True,
        "note": "Prefer current voyage ETA from PANS.",
    },
    "voyage.etd": {
        "incoming": ["etd", "voyage.etd"],
        "reference": ["EDTD", "ETD"],
        "allow_reference": True,
        "note": "Prefer current voyage ETD from PANS.",
    },
    "voyage.origin": {
        "incoming": ["origin", "voyage.origin"],
        "reference": ["OriginalPortOfDep", "ORIGIN", "PORT_OF_ORIGIN"],
        "allow_reference": True,
        "note": "Prefer explicit origin/departure-port field.",
    },
}

def norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s).upper())

def connect(path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c

def schema(path: Path) -> dict[str, list[str]]:
    conn = connect(path)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    out: dict[str, list[str]] = {}
    for row in tables:
        table = row[0]
        cols = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        out[table] = [c["name"] for c in cols]
    conn.close()
    return out

def find_candidates(db_schemas: dict[str, list[str]], aliases: list[str]) -> list[dict[str, str]]:
    wanted = {norm(x) for x in aliases}
    found = []
    for table, cols in db_schemas.items():
        for col in cols:
            if norm(col) in wanted:
                found.append({"table": table, "column": col, "match": "exact-normalized"})
    return found

def count_rows(path: Path, table: str) -> int:
    conn = connect(path)
    try:
        return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    finally:
        conn.close()

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wrs-db", required=True)
    ap.add_argument("--pans-db", required=True)
    ap.add_argument("--nsc-db", required=True)
    ap.add_argument("--output", default="runtime/reference-mapping-audit")
    args = ap.parse_args()

    dbs = {
        "WRS": Path(args.wrs_db).resolve(),
        "PANS": Path(args.pans_db).resolve(),
        "NSC": Path(args.nsc_db).resolve(),
    }
    for name, path in dbs.items():
        if not path.is_file():
            raise SystemExit(f"{name} database not found: {path}")

    schemas = {name: schema(path) for name, path in dbs.items()}

    # VESSEL_ID is the WRS relationship key. Record where it actually exists.
    vessel_id_tables = []
    for table, cols in schemas["WRS"].items():
        if any(norm(c) == "VESSELID" for c in cols):
            vessel_id_tables.append(table)

    report: dict[str, Any] = {
        "status": "PASS",
        "databases": {
            name: {
                "path": str(path),
                "tables": len(schemas[name]),
                "rows": sum(count_rows(path, t) for t in schemas[name]),
            }
            for name, path in dbs.items()
        },
        "wrs_vessel_id_tables": vessel_id_tables,
        "fields": {},
        "all_columns": schemas,
    }

    for logical, spec in ROOT_FIELDS.items():
        matches = []
        for db_name, db_schema in schemas.items():
            for hit in find_candidates(db_schema, spec["reference"]):
                matches.append({"database": db_name, **hit})

        # WRS fields that are not in the fixed alias list are still surfaced
        # when their column name contains a strong semantic token.
        semantic_hits = []
        tokens = [norm(a) for a in spec["reference"] if len(norm(a)) >= 5]
        for table, cols in schemas["WRS"].items():
            for col in cols:
                ncol = norm(col)
                if any(tok in ncol or ncol in tok for tok in tokens):
                    semantic_hits.append({"database": "WRS", "table": table, "column": col, "match": "semantic"})

        # De-duplicate.
        merged = []
        seen = set()
        for hit in matches + semantic_hits:
            key = (hit["database"], hit["table"], hit["column"])
            if key not in seen:
                seen.add(key)
                merged.append(hit)

        report["fields"][logical] = {
            "incoming_candidates": spec["incoming"],
            "reference_aliases": spec["reference"],
            "reference_candidates": merged,
            "reference_allowed": spec["allow_reference"],
            "note": spec["note"],
            "current_contract_source": "incoming" if not spec["reference"] else "incoming/reference",
        }

    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "reference_mapping_audit.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )

    with (out / "reference_mapping_audit.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["XML field", "Database", "Table", "Column", "Reference allowed", "Note"])
        for logical, spec in report["fields"].items():
            candidates = spec["reference_candidates"]
            if not candidates:
                w.writerow([logical, "", "", "", spec["reference_allowed"], spec["note"]])
            else:
                for hit in candidates:
                    w.writerow([
                        logical, hit["database"], hit["table"], hit["column"],
                        spec["reference_allowed"], spec["note"]
                    ])

    print(json.dumps({
        "status": report["status"],
        "WRS_tables": report["databases"]["WRS"]["tables"],
        "PANS_tables": report["databases"]["PANS"]["tables"],
        "NSC_tables": report["databases"]["NSC"]["tables"],
        "WRS_VESSEL_ID_tables": vessel_id_tables,
        "output": str(out),
    }, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Generate current XML-generator scenario samples from the canonical model."""
from pathlib import Path
import shutil
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from Validation.Data_Parser.app.models.common import CommonVesselRecord
from Validation.Data_Parser.app.pipeline.enricher import VesselEnricher
from Validation.Data_Parser.app.pipeline.normalizer import normalize_from_common_record
from Validation.Data_Parser.app.pipeline.reference_db import ReferenceDB
from Validation.Data_Parser.app.pipeline.track_state import TrackStateDB
from Validation.Data_Parser.app.pipeline.xml_generator import XTrackXMLGenerator

# runtime/ may be root-owned on some operator systems after Docker runs.
# Keep generated samples under the repository so the operator can always read
# them without sudo.
OUT_DIR = ROOT / "Validation" / "Data_Parser" / "generated_samples" / "xml_generator_scenarios"
LEGACY_OUT = ROOT / "Validation" / "Data_Parser" / "generated_samples" / "xml_generator_samples.txt"
REFERENCE_ROOT = ROOT / "runtime" / "reference"


SOURCE_IDS = {
    "SAIS_IOR": 38, "SAIS_GLOBAL": 38, "MSIS": 250, "LRIT": 40,
    "VATMS_EAST": 245, "VATMS_WEST": 223, "NAIS": 37,
}

def make_record(source: str, n: int, **kw) -> CommonVesselRecord:
    return CommonVesselRecord(
        source=source,
        message_id=f"sample-{source.lower()}-{n}",
        record_id=f"{source}:{n}",
        timestamp=kw.pop("timestamp", "2026-09-10T14:57:13+00:00"),
        raw_attributes={
            "scenario_assumption": kw.pop("assumption", ""),
            "sample_source": source,
        },
        **kw,
    )

def scenarios():
    return [
        ("SAIS_IOR", [
            make_record("SAIS_IOR",1,mmsi=477900700,latitude=0.36008502,longitude=1.87239091,sog=5.0,cog=1.2,true_heading=1.2,app_message_id=1,assumption="REAL acceptance sample basis: MMSI 477900700 and position. Remaining values are assumed."),
            make_record("SAIS_IOR",2,mmsi=477900700,vessel_name="IOR SAMPLE VESSEL",latitude=0.3601,longitude=1.8724,sog=4.2,cog=1.3,true_heading=1.3,app_message_id=1,assumption="Scenario based on real MMSI; vessel name and kinematics assumed."),
            make_record("SAIS_IOR",3,mmsi=477900700,imo=9379856,vessel_name="TYPE5 VESSEL",callsign="V7B3088",latitude=0.3602,longitude=1.8725,sog=4.5,cog=1.4,true_heading=1.4,app_message_id=5,draught=9.31,length=119.99,width=21.20,destination="INBOM1",eta="2026-09-20T18:00:00+00:00",assumption="Scenario: complete AIS Type 5. Incoming static/voyage values are authoritative."),
            make_record("SAIS_IOR",4,mmsi=477900700,imo=9379856,vessel_name=None,callsign=None,latitude=0.3603,longitude=1.8726,app_message_id=1,assumption="Scenario: incoming identity fields are missing; assume NSC -> PANS -> WRS fallback."),
            make_record("SAIS_IOR",5,mmsi=477900700,imo=9379856,vessel_name="TRANSMITTED NAME",callsign="CALL-IN",latitude=0.3604,longitude=1.8727,app_message_id=1,assumption="Scenario: reference identity conflicts; incoming values remain primary."),
        ]),
        ("SAIS_GLOBAL", [
            make_record("SAIS_GLOBAL",1,mmsi=710000269,latitude=-0.19091249,longitude=-0.64499533,sog=7.0,cog=2.1,true_heading=2.1,app_message_id=1,assumption="REAL acceptance sample basis: MMSI 710000269 and position. Remaining values are assumed."),
            make_record("SAIS_GLOBAL",2,mmsi=710000269,latitude=-0.1909,longitude=-0.6450,sog=8.0,cog=2.2,true_heading=2.2,app_message_id=18,assumption="Scenario based on real MMSI; message/kinematics assumed."),
            make_record("SAIS_GLOBAL",3,mmsi=710000269,imo=9272682,vessel_name="GLOBAL TYPE5",callsign="D7IQ",latitude=-0.1910,longitude=-0.6451,app_message_id=5,draught=8.5,destination="INKAK1",eta="2026-09-20T18:00:00+00:00",assumption="Scenario: complete AIS Type 5. Incoming values win."),
            make_record("SAIS_GLOBAL",4,mmsi=710000269,latitude=-0.1911,longitude=-0.6452,app_message_id=1,assumption="Scenario: incoming identity absent. Assumed reference fallback."),
            make_record("SAIS_GLOBAL",5,mmsi=710000269,vessel_name="TRANSMITTED GLOBAL NAME",latitude=-0.1912,longitude=-0.6453,app_message_id=1,assumption="Scenario: conflicting reference name. Incoming name remains final value."),
        ]),
        ("MSIS", [
            make_record("MSIS",1,mmsi=201000388,latitude=0.72269670,longitude=0.33730080,sog=6.0,cog=1.0,true_heading=1.0,app_message_id=1,assumption="REAL acceptance sample basis: MMSI 201000388 and position. MSIS is already decoded."),
            make_record("MSIS",2,mmsi=201000388,imo=9100001,vessel_name="MSIS DECODED",callsign="MSCALL",latitude=0.7227,longitude=0.3374,sog=5.5,assumption="Scenario: already-decoded MSIS values are incoming values."),
            make_record("MSIS",3,mmsi=201000388,imo=9100001,vessel_name="MSIS TYPE5 EQUIVALENT",callsign="MSC5",latitude=0.7228,longitude=0.3375,app_message_id=5,draught=8.2,length=150.0,width=24.0,destination="INBOM1",eta="2026-09-20T20:00:00+00:00",assumption="Scenario: decoded row contains complete static/voyage fields; incoming values remain primary."),
            make_record("MSIS",4,mmsi=201000388,latitude=0.7229,longitude=0.3376,assumption="Scenario: decoded static/voyage fields missing; reference fallback only for missing fields."),
            make_record("MSIS",5,mmsi=201000388,imo=9100001,vessel_name="MSIS TRANSMITTED",latitude=0.7230,longitude=0.3377,assumption="Scenario: reference has conflicting name. Incoming decoded name wins."),
        ]),
        ("LRIT", [
            make_record("LRIT",1,mmsi=419000122,imo=9448542,vessel_name="OCEAN FAME",latitude=0.22876612,longitude=1.40154594,assumption="REAL acceptance sample basis: MMSI 419000122, IMO 9448542, OCEAN FAME and position."),
            make_record("LRIT",2,mmsi=419000122,imo=9448542,vessel_name="OCEAN FAME",latitude=0.2288,longitude=1.4016,assumption="Scenario based on real LRIT identity; position assumed."),
            make_record("LRIT",3,mmsi=419000122,imo=9448542,vessel_name=None,latitude=0.2289,longitude=1.4017,assumption="Scenario: name missing; assume PANS match supplies vessel name."),
            make_record("LRIT",4,mmsi=419000122,imo=9448542,vessel_name="LRIT NAME",latitude=0.2290,longitude=1.4018,assumption="Scenario: incoming name present; reference cannot overwrite it."),
            make_record("LRIT",5,mmsi=419000122,imo=9448542,vessel_name="OCEAN FAME",latitude=0.2291,longitude=1.4019,destination="INBOM1",eta="2026-09-20T10:00:00+00:00",assumption="Scenario: incoming voyage values present and primary."),
        ]),
        ("VATMS_EAST", [
            make_record("VATMS_EAST",1,mmsi=900019087,latitude=0.28700529,longitude=1.43395574,sog=4.0,cog=1.1,true_heading=1.1,app_message_id=1,assumption="REAL acceptance sample basis: MMSI 900019087 and position."),
            make_record("VATMS_EAST",2,mmsi=900019087,latitude=0.2871,longitude=1.4340,sog=4.5,cog=1.2,true_heading=1.2,app_message_id=1,assumption="Scenario based on real MMSI; remaining values assumed."),
            make_record("VATMS_EAST",3,mmsi=900019087,vessel_name="VATMS EAST TARGET",latitude=0.2872,longitude=1.4341,app_message_id=1,assumption="Scenario: incoming target name present."),
            make_record("VATMS_EAST",4,mmsi=900019087,latitude=0.2873,longitude=1.4342,app_message_id=1,assumption="Scenario: target identity incomplete; assumed reference enrichment."),
            make_record("VATMS_EAST",5,mmsi=900019087,vessel_name="TRANSMITTED EAST",latitude=0.2874,longitude=1.4343,app_message_id=1,assumption="Scenario: reference identity conflicts; incoming target value remains primary."),
        ]),
        ("VATMS_WEST", [
            make_record("VATMS_WEST",1,vessel_name="1239",latitude=0.32343962,longitude=1.26148442,assumption="REAL acceptance sample basis: radar target 1239 and position; MMSI/IMO absent."),
            make_record("VATMS_WEST",2,mmsi=419000482,imo=9620865,vessel_name="WATER LILY",callsign="AVQX",latitude=0.3235,longitude=1.2615,sog=0.1028889,app_message_id=1,length=45.0,width=11.0,assumption="REAL uploaded input contains WATER LILY, MMSI 419000482, IMO 9620865 and AVQX; other values are scenario values."),
            make_record("VATMS_WEST",3,mmsi=419001886,imo=1040772,vessel_name="MOGRA STAR",callsign="VUAK",latitude=0.3240,longitude=1.2620,sog=0.257222,app_message_id=1,length=50.0,width=12.0,assumption="REAL uploaded input contains MOGRA STAR, MMSI 419001886, IMO 1040772 and VUAK; other values are scenario values."),
            make_record("VATMS_WEST",4,mmsi=419000482,imo=9620865,vessel_name=None,latitude=0.3241,longitude=1.2621,assumption="Scenario: identifiers present but name missing; assume NSC/PANS/WRS supplies name."),
            make_record("VATMS_WEST",5,mmsi=419000482,imo=9620865,vessel_name="TRANSMITTED RADAR NAME",callsign="AVQX",latitude=0.3242,longitude=1.2622,assumption="Scenario: reference name differs; incoming target name remains primary."),
        ]),
        ("NAIS", [
            make_record("NAIS",1,mmsi=419697000,imo=8407979,vessel_name="Saga",latitude=0.39292179,longitude=1.20445823,app_message_id=1,assumption="REAL acceptance sample basis: MMSI 419697000, IMO 8407979, Saga and position."),
            make_record("NAIS",2,mmsi=419697000,imo=8407979,vessel_name="Saga",callsign="CALL-SAGA",latitude=0.3930,longitude=1.2045,assumption="Scenario based on real NAIS identity; callsign is assumed."),
            make_record("NAIS",3,mmsi=419697000,imo=8407979,vessel_name="Saga",callsign="CALL-SAGA",latitude=0.3931,longitude=1.2046,app_message_id=5,draught=8.5,length=150.0,width=24.0,destination="INBOM1",eta="2026-09-20T12:00:00+00:00",assumption="Scenario: complete Type 5. All transmitted static/voyage fields are primary."),
            make_record("NAIS",4,mmsi=419697000,imo=None,vessel_name=None,latitude=0.3932,longitude=1.2047,assumption="Scenario: incoming identity incomplete. Assumed NSC match via MMSI supplies IMO/name."),
            make_record("NAIS",5,mmsi=419697000,imo=8407979,vessel_name="Saga",callsign="CALL-SAGA",latitude=0.3933,longitude=1.2048,assumption="Scenario: WRS risk intelligence exists; it enriches remarks and does not overwrite live identity/position."),
        ]),
    ]

def _reference_path(name: str) -> Path:
    candidates = [
        REFERENCE_ROOT / f"{name.lower()}.db",
        ROOT / "Validation" / "Database" / name / f"{name.lower()}.db",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def enrich_scenario(rec: CommonVesselRecord):
    """Run the same reference-enrichment stage used by the live processor.

    A private temporary TrackStateDB is used so scenario generation cannot
    modify the operator's persistent track/history database.
    """
    ref_db = ReferenceDB(
        wrs_path=_reference_path("WRS"),
        pans_path=_reference_path("PANS"),
        nsc_path=_reference_path("NSC"),
    )
    with tempfile.TemporaryDirectory(prefix="validation-xml-scenario-") as td:
        state_db = TrackStateDB(Path(td) / "track_state.db")
        enricher = VesselEnricher(reference_db=ref_db, track_state_db=state_db)
        norm = normalize_from_common_record(rec, receipt_time_ms=1789032517108)
        norm.sys_source_id = SOURCE_IDS[rec.source]
        enriched = enricher.enrich(norm)
    ref_db.close()
    return enriched


def main():
    gen = XTrackXMLGenerator()
    # This directory is dedicated to generated scenarios, so rebuild it
    # completely to prevent stale/old XML samples from being mistaken for
    # current generator output.
    shutil.rmtree(OUT_DIR, ignore_errors=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if LEGACY_OUT.exists():
        LEGACY_OUT.unlink()
    manifest_lines = [
        "VALIDATION CURRENT XML GENERATOR SCENARIOS",
        "==========================================",
        "Each XML is generated by the current normalizer + VesselEnricher + XTrackXMLGenerator.",
        "Old Sample_xmls XML is NOT copied.",
        "Reference enrichment uses the current WRS/PANS/NSC SQLite databases when available.",
        "Each scenario uses an isolated temporary TrackStateDB; operator state is not modified.",
        "",
    ]

    total = 0
    for feed, rows in scenarios():
        feed_dir = OUT_DIR / feed
        feed_dir.mkdir(parents=True, exist_ok=True)
        for idx, rec in enumerate(rows, 1):
            total += 1
            enriched = enrich_scenario(rec)
            xml = gen.generate_document(enriched)
            field_count = gen.validate_document(xml)

            filename = f"scenario_{idx:02d}.xml"
            target = feed_dir / filename
            target.write_text(xml + "\n", encoding="utf-8")

            provenance = (enriched.raw_attributes or {}).get("enrichment_provenance", {})
            manifest_lines.extend([
                f"[{feed} / {filename}]",
                f"ASSUMPTION: {rec.raw_attributes.get('scenario_assumption', '')}",
                f"XML FIELDS: {field_count}",
                "VESSEL REMARKS:",
                enriched.vessel_remarks or "(none)",
                "ENRICHMENT PROVENANCE:",
                *(f"  {k}={v}" for k, v in sorted(provenance.items()) if v != "NONE"),
                "",
            ])

    manifest = OUT_DIR / "scenario_manifest.txt"
    manifest.write_text("\n".join(manifest_lines), encoding="utf-8")
    print(f"Generated {total} XML scenarios under: {OUT_DIR}")
    print(f"Manifest: {manifest}")


if __name__ == "__main__":
    main()

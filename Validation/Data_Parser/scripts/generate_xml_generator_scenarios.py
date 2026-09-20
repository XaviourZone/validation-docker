#!/usr/bin/env python3
"""Generate current XML-generator scenario samples from the canonical model."""
from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from Validation.Data_Parser.app.models.common import CommonVesselRecord
from Validation.Data_Parser.app.pipeline.normalizer import normalize_from_common_record
from Validation.Data_Parser.app.pipeline.xml_generator import XTrackXMLGenerator

OUT = ROOT / "runtime" / "xml-generator-scenarios" / "xml_generator_samples.txt"
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

def add_comments(xml_text: str, assumption: str) -> str:
    out, current = [], None
    for line in xml_text.splitlines():
        m = re.search(r"<id>([^<]+)</id>", line)
        if m:
            current = m.group(1)
        if line.strip() == "<ns2:A>":
            out.append(f"        <!-- {current}: {assumption} -->")
        out.append(line)
    return "\n".join(out)

def main():
    gen = XTrackXMLGenerator()
    sections = [
        "VALIDATION CURRENT XML GENERATOR — 35 SCENARIOS",
        "===============================================",
        "Generated by current normalize_from_common_record() + XTrackXMLGenerator.",
        "Old Sample_xmls XML is NOT used as output.",
        "REAL entries are grounded in uploaded/acceptance sample facts.",
        "ASSUMPTION entries are explicit scenarios to exercise current logic paths.",
        "Each case is one XML document containing one XTrack.",
        "",
    ]
    total = 0
    for feed, rows in scenarios():
        sections.append(f"================ {feed} ================\n")
        for idx, rec in enumerate(rows, 1):
            total += 1
            norm = normalize_from_common_record(rec, receipt_time_ms=1789032517108)
            norm.sys_source_id = SOURCE_IDS[feed]
            xml = gen.generate_document(norm)
            gen.validate_document(xml)
            sections.append(f"<!-- {feed} SAMPLE {idx} -->")
            sections.append(f"<!-- INPUT/SCENARIO: {rec.raw_attributes['scenario_assumption']} -->")
            sections.append(add_comments(xml, rec.raw_attributes["scenario_assumption"]))
            sections.append("")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(sections), encoding="utf-8")
    print(f"Generated {total} XML scenarios: {OUT}")

if __name__ == "__main__":
    main()

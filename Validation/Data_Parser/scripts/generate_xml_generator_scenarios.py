#!/usr/bin/env python3
"""Generate annotated XML-generator samples from the Validation canonical model.

This is a local, offline scenario harness. It deliberately uses the CURRENT
XTrackXMLGenerator from Validation/Data_Parser/app/pipeline/xml_generator.py.
It does not reuse old Sample_xmls XML.

The values are derived from real uploaded sample/acceptance data where available.
Where the uploaded material does not expose every source field needed to run a
live WRS/PANS/NSC lookup, the scenario comment explicitly marks the assumption.

Output:
  runtime/xml-generator-scenarios/xml_generator_samples.txt

25 cases:
  5 x SAIS_IOR
  5 x SAIS_GLOBAL
  5 x MSIS
  5 x LRIT
  5 x VATMS_EAST
  5 x VATMS_WEST
  5 x NAIS
"""

from __future__ import annotations

import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from Validation.Data_Parser.app.models.common import CommonVesselRecord
from Validation.Data_Parser.app.pipeline.normalizer import normalize_from_common_record
from Validation.Data_Parser.app.pipeline.xml_generator import XTrackXMLGenerator


OUT = ROOT / "runtime" / "xml-generator-scenarios" / "xml_generator_samples.txt"

SOURCE_IDS = {
    "SAIS_IOR": 38,
    "SAIS_GLOBAL": 38,
    "MSIS": 250,
    "LRIT": 40,
    "VATMS_EAST": 245,
    "VATMS_WEST": 223,
    "NAIS": 37,
}


def record(
    source: str,
    n: int,
    *,
    mmsi=None,
    imo=None,
    name=None,
    callsign=None,
    lat=None,
    lon=None,
    sog=None,
    cog=None,
    heading=None,
    nav_status=None,
    msg_id=None,
    length=None,
    beam=None,
    draft=None,
    destination=None,
    eta=None,
    etd=None,
    origin=None,
    type_cargo=None,
    remarks=None,
    gross=None,
    assumption="",
):
    return CommonVesselRecord(
        source=source,
        message_id=f"sample-{source.lower()}-{n}",
        record_id=f"{source}:{n}",
        timestamp="2026-09-10T14:57:13+00:00",
        mmsi=mmsi,
        imo=imo,
        vessel_name=name,
        callsign=callsign,
        latitude=lat,
        longitude=lon,
        sog=sog,
        cog=cog,
        true_heading=heading,
        nav_status=nav_status,
        app_message_id=msg_id,
        length=length,
        width=beam,
        draught=draft,
        destination=destination,
        eta=eta,
        etd=etd,
        origin=origin,
        vessel_type=type_cargo,
        gross_tonnage=gross,
        raw_attributes={
            "scenario_assumption": assumption,
            "sample_source": source,
        },
    )


def scenarios():
    # Real sample facts used below:
    # SAIS_IOR acceptance sample MMSI 477900700.
    # SAIS_GLOBAL acceptance sample MMSI 710000269.
    # MSIS acceptance sample MMSI 201000388.
    # LRIT acceptance sample MMSI 419000122, IMO 9448542, OCEAN FAME.
    # VATMS_EAST acceptance sample MMSI 900019087.
    # VATMS_WEST acceptance sample had radar target 1239.
    # NAIS acceptance sample MMSI 419697000, IMO 8407979, Saga.
    return [
        ("SAIS_IOR", [
            record("SAIS_IOR", 1, mmsi=477900700, lat=0.36008502, lon=1.87239091,
                   sog=5.0, cog=1.2, heading=1.2, msg_id=1,
                   assumption="REAL SAMPLE FACT: acceptance report identifies MMSI=477900700 and the sample position. Other kinematics are illustrative assumptions."),
            record("SAIS_IOR", 2, mmsi=477900700, lat=0.3601, lon=1.8724,
                   sog=4.2, cog=1.3, heading=1.3, msg_id=1,
                   name="IOR SAMPLE VESSEL", assumption="REAL MMSI from uploaded acceptance sample; vessel name is an illustrative incoming value."),
            record("SAIS_IOR", 3, mmsi=477900700, imo=9379856, name="TYPE5 VESSEL",
                   callsign="V7B3088", length=119.99, beam=21.20, draft=9.31,
                   destination="INBOM1", eta="2026-09-20T18:00:00+00:00",
                   msg_id=5, lat=0.3602, lon=1.8725, assumption="SCENARIO: complete AIS Type 5. Incoming static/voyage values are authoritative."),
            record("SAIS_IOR", 4, mmsi=477900700, imo=9379856, name=None, callsign=None,
                   lat=0.3603, lon=1.8726, msg_id=1,
                   assumption="SCENARIO: incoming identity fields missing. Assumed NSC/PANS/WRS matches exist; current field policy would use NSC -> PANS -> WRS."),
            record("SAIS_IOR", 5, mmsi=477900700, imo=9379856, name="TRANSMITTED NAME",
                   callsign="CALL-IN", lat=0.3604, lon=1.8727, msg_id=1,
                   assumption="SCENARIO: incoming identity conflicts with reference identity. Incoming value remains primary; discrepancy is for remarks/analysis, not silent overwrite."),
        ]),
        ("SAIS_GLOBAL", [
            record("SAIS_GLOBAL", 1, mmsi=710000269, lat=-0.19091249, lon=-0.64499533,
                   sog=7.0, cog=2.1, heading=2.1, msg_id=1,
                   assumption="REAL SAMPLE FACT: acceptance report identifies MMSI=710000269 and the sample position. Other values are illustrative."),
            record("SAIS_GLOBAL", 2, mmsi=710000269, lat=-0.1909, lon=-0.6450,
                   sog=8.0, cog=2.2, heading=2.2, msg_id=18,
                   assumption="REAL MMSI from uploaded acceptance sample; message type/kinematics are illustrative."),
            record("SAIS_GLOBAL", 3, mmsi=710000269, imo=9272682, name="GLOBAL TYPE5",
                   callsign="D7IQ", destination="INKAK1", draft=8.5, msg_id=5,
                   lat=-0.1910, lon=-0.6451, assumption="SCENARIO: complete Type 5 static/voyage data. Incoming values win."),
            record("SAIS_GLOBAL", 4, mmsi=710000269, imo=None, name=None,
                   lat=-0.1911, lon=-0.6452, msg_id=1,
                   assumption="SCENARIO: incoming identity absent. Assumed reference match supplies identity according to field priority."),
            record("SAIS_GLOBAL", 5, mmsi=710000269, name="TRANSMITTED GLOBAL NAME",
                   lat=-0.1912, lon=-0.6453, msg_id=1,
                   assumption="SCENARIO: reference database contains a different name. Incoming name remains final field value."),
        ]),
        ("MSIS", [
            record("MSIS", 1, mmsi=201000388, lat=0.72269670, lon=0.33730080,
                   sog=6.0, cog=1.0, heading=1.0, msg_id=1,
                   assumption="REAL SAMPLE FACT: acceptance report identifies MMSI=201000388 and the sample position. Remaining values illustrative."),
            record("MSIS", 2, mmsi=201000388, imo=9100001, name="MSIS DECODED",
                   callsign="MSCALL", lat=0.7227, lon=0.3374, sog=5.5,
                   assumption="SCENARIO: already-decoded MSIS row. No NMEA six-bit decoding is applied; decoded values are incoming values."),
            record("MSIS", 3, mmsi=201000388, imo=9100001, name="MSIS TYPE5 EQUIVALENT",
                   callsign="MSC5", length=150.0, beam=24.0, draft=8.2,
                   destination="INBOM1", eta="2026-09-20T20:00:00+00:00",
                   msg_id=5, lat=0.7228, lon=0.3375,
                   assumption="SCENARIO: decoded row contains complete static/voyage fields; incoming values remain primary."),
            record("MSIS", 4, mmsi=201000388, name=None, destination=None,
                   lat=0.7229, lon=0.3376,
                   assumption="SCENARIO: decoded row has missing static/voyage fields. Reference fallback is allowed only for those missing fields."),
            record("MSIS", 5, mmsi=201000388, name="MSIS TRANSMITTED",
                   lat=0.7230, lon=0.3377,
                   assumption="SCENARIO: reference has conflicting name. Incoming decoded value wins."),
        ]),
        ("LRIT", [
            record("LRIT", 1, mmsi=419000122, imo=9448542, name="OCEAN FAME",
                   lat=0.22876612, lon=1.40154594, msg_id=None,
                   assumption="REAL SAMPLE FACT: acceptance report identifies MMSI=419000122, IMO=9448542, OCEAN FAME and the sample position."),
            record("LRIT", 2, mmsi=419000122, imo=9448542, name="OCEAN FAME",
                   lat=0.2288, lon=1.4016,
                   assumption="REAL vessel identity from uploaded acceptance report; position is an illustrative second scenario."),
            record("LRIT", 3, mmsi=419000122, imo=9448542, name=None,
                   lat=0.2289, lon=1.4017,
                   assumption="SCENARIO based on real LRIT identity: name missing in incoming row; assumed PANS match supplies OCEAN FAME."),
            record("LRIT", 4, mmsi=419000122, imo=9448542, name="LRIT NAME",
                   destination=None, lat=0.2290, lon=1.4018,
                   assumption="SCENARIO: incoming name is present and therefore remains primary; missing voyage destination may fall back to PANS/WRS."),
            record("LRIT", 5, mmsi=419000122, imo=9448542, name="OCEAN FAME",
                   destination="INBOM1", eta="2026-09-20T10:00:00+00:00",
                   lat=0.2291, lon=1.4019,
                   assumption="SCENARIO: incoming voyage values present; they remain primary over reference voyage values."),
        ]),
        ("VATMS_EAST", [
            record("VATMS_EAST", 1, mmsi=900019087, lat=0.28700529, lon=1.43395574,
                   sog=4.0, cog=1.1, heading=1.1, msg_id=1,
                   assumption="REAL SAMPLE FACT: acceptance report identifies MMSI=900019087 and the sample position. Remaining values illustrative."),
            record("VATMS_EAST", 2, mmsi=900019087, lat=0.2871, lon=1.4340,
                   sog=4.5, cog=1.2, heading=1.2, msg_id=1,
                   assumption="REAL MMSI from uploaded VATMS_EAST sample; remaining fields illustrative."),
            record("VATMS_EAST", 3, mmsi=900019087, name="VATMS EAST TARGET",
                   lat=0.2872, lon=1.4341, msg_id=1,
                   assumption="SCENARIO: radar/AIS target has an incoming target name."),
            record("VATMS_EAST", 4, mmsi=900019087, name=None,
                   lat=0.2873, lon=1.4342, msg_id=1,
                   assumption="SCENARIO: target identity is incomplete; assumed reference databases can enrich static identity."),
            record("VATMS_EAST", 5, mmsi=900019087, name="TRANSMITTED EAST",
                   lat=0.2874, lon=1.4343, msg_id=1,
                   assumption="SCENARIO: reference identity conflicts. Incoming target value remains primary."),
        ]),
        ("VATMS_WEST", [
            record("VATMS_WEST", 1, name="1239", lat=0.32343962, lon=1.26148442,
                   sog=0.0, cog=0.0, heading=0.0,
                   assumption="REAL SAMPLE FACT: acceptance report identifies radar target ID/name 1239 and the sample position; MMSI/IMO absent."),
            record("VATMS_WEST", 2, name="WATER LILY", mmsi=419000482, imo=9620865,
                   callsign="AVQX", lat=0.3235, lon=1.2615, sog=0.1028889,
                   cog=5.64, heading=5.64, length=45.0, beam=11.0,
                   assumption="REAL UPLOADED INPUT FACT: vatms_west contains a WATER LILY $TMVTD record with MMSI=419000482 and IMO=9620865. Position/kinematics here are converted/illustrative for this scenario."),
            record("VATMS_WEST", 3, name="MOGRA STAR", mmsi=419001886, imo=1040772,
                   callsign="VUAK", lat=0.3240, lon=1.2620, sog=0.257222,
                   cog=1.61, heading=1.61, length=50.0, beam=12.0,
                   assumption="REAL UPLOADED INPUT FACT: vatms_west contains MOGRA STAR with MMSI=419001886, IMO=1040772 and callsign VUAK. Other numeric fields are scenario values."),
            record("VATMS_WEST", 4, name=None, mmsi=419000482, imo=9620865,
                   lat=0.3241, lon=1.2621,
                   assumption="SCENARIO: incoming target has identifiers but no name; assumed NSC/PANS/WRS lookup supplies name using configured identity priority."),
            record("VATMS_WEST", 5, name="TRANSMITTED RADAR NAME", mmsi=419000482, imo=9620865,
                   lat=0.3242, lon=1.2622,
                   assumption="SCENARIO: reference has a different vessel name. Incoming target name remains primary."),
        ]),
        ("NAIS", [
            record("NAIS", 1, mmsi=419697000, imo=8407979, name="Saga",
                   lat=0.39292179, lon=1.20445823, msg_id=1,
                   assumption="REAL SAMPLE FACT: acceptance report identifies MMSI=419697000, IMO=8407979, vessel Saga and the sample position."),
            record("NAIS", 2, mmsi=419697000, imo=8407979, name="Saga",
                   callsign="CALL-SAGA", lat=0.3930, lon=1.2045,
                   assumption="REAL identity from uploaded NAIS acceptance sample; callsign is an illustrative incoming value."),
            record("NAIS", 3, mmsi=419697000, imo=8407979, name="Saga",
                   callsign="CALL-SAGA", length=150.0, beam=24.0, draft=8.5,
                   destination="INBOM1", eta="2026-09-20T12:00:00+00:00",
                   msg_id=5, lat=0.3931, lon=1.2046,
                   assumption="SCENARIO: complete Type 5. All transmitted static/voyage fields are primary."),
            record("NAIS", 4, mmsi=419697000, imo=None, name=None,
                   lat=0.3932, lon=1.2047,
                   assumption="SCENARIO: incoming identity incomplete. Assumed NSC match via MMSI supplies IMO/name."),
            record("NAIS", 5, mmsi=419697000, imo=8407979, name="Saga",
                   lat=0.3933, lon=1.2048,
                   assumption="SCENARIO: WRS has AIS spoofing/gap/sanction intelligence for this MMSI. Those are remarks/enrichment and do not overwrite live position/identity."),
        ]),
    ]


def annotate_xml(xml_text: str, assumption: str) -> str:
    # Keep XML valid: XML comments are legal between elements.
    lines = xml_text.splitlines()
    out = []
    current = None
    for line in lines:
        m = re.search(r"<id>([^<]+)</id>", line)
        if m:
            current = m.group(1)
        if line.strip().startswith("<ns2:A>"):
            out.append(f"        <!-- {current or 'field'}: {assumption} -->")
        out.append(line)
    return "\n".join(out)


def main():
    gen = XTrackXMLGenerator()
    sections = [
        "VALIDATION CURRENT XML-GENERATOR SCENARIOS",
        "===========================================",
        "",
        "IMPORTANT: These are NEW outputs generated by the CURRENT",
        "XTrackXMLGenerator. They are not copied from Sample_xmls.",
        "The underlying records are scenario records based on uploaded real",
        "feed samples. Every non-source-derived value is explicitly marked",
        "ASSUMPTION in the XML comments.",
        "",
        "Current contract: one NormalizedRecord -> one XTracks document with",
        "one XTrack. Missing fields are omitted; the generator does not fabricate",
        "all 41 fields.",
        "",
    ]

    total = 0
    for feed, cases in scenarios():
        sections.append(f"\n================ {feed} ================\n")
        for idx, rec in enumerate(cases, 1):
            total += 1
            norm = normalize_from_common_record(rec, receipt_time_ms=1789032517108)
            # Ensure source ID follows the current source registry.
            norm.sys_source_id = SOURCE_IDS[feed]
            xml = gen.generate_document(norm)
            gen.validate_document(xml)
            sections.append(
                f"<!-- CASE {feed} #{idx} -->\n"
                f"<!-- INPUT BASIS: {rec.raw_attributes['scenario_assumption']} -->\n"
                f"{xml}\n"
            )

    sections.append(f"\n<!-- TOTAL CASES: {total} -->\n")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(sections), encoding="utf-8")
    print(f"Wrote {total} annotated XML scenarios to {OUT}")


if __name__ == "__main__":
    main()

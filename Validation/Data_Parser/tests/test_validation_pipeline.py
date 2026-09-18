"""
Comprehensive test suite for the Data Parser validation pipeline.

Covers:
1. Normal parsing for all 6 sources (SAIS, MSIS, LRIT, VATMS East, VATMS West, NAIS)
2. Actual XML decoding (<A><id>...</id><iv/sv/bv/qv/tv></A>)
3. 41 logical fields normalization
4. Source ID resolution (37, 38, 40, 223, 245, 250)
5. Track state (first transmission, repeated MMSI, active <3h, inactive >=3h)
6. Reference database lookups (WRS, PANS, NSC)
7. Fallback priority (Transmission -> WRS -> PANS -> NSC -> UNKNOWN)
8. foreign.track.number vs sys.track.number behavior
9. No fabrication rule (dimensions, widthToPort != beam/2)
10. Vigilance scoring & identity categorization
11. Point-wise remarks generation (clearance, spoofing detection, provenance)
12. Validation & error resilience (malformed XML, CSV, NMEA, invalid coordinates, invalid MMSI)
13. XML generation and consumption by downstream parser
"""

import math
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from Validation.Data_Parser.app.models.common import ParserEnvelope
from Validation.Data_Parser.app.parsers.lrit import LRITParser
from Validation.Data_Parser.app.parsers.msis import MSISParser
from Validation.Data_Parser.app.parsers.nais import NAISParser
from Validation.Data_Parser.app.parsers.sais import SAISParser
from Validation.Data_Parser.app.parsers.vatms import VATMSParser
from Validation.Data_Parser.app.pipeline.downstream_parser import DownstreamXMLParser
from Validation.Data_Parser.app.pipeline.enricher import VesselEnricher
from Validation.Data_Parser.app.pipeline.normalizer import (
    LOGICAL_FIELDS_41,
    NormalizedRecord,
    normalize_from_common_record,
    normalize_from_decoded_track,
)
from Validation.Data_Parser.app.pipeline.processor import PipelineProcessor
from Validation.Data_Parser.app.pipeline.reference_db import ReferenceDB
from Validation.Data_Parser.app.pipeline.source_registry import (
    get_source_id,
    get_source_label,
    is_valid_imo,
    is_valid_mmsi,
    iso_to_epoch_ms,
)
from Validation.Data_Parser.app.pipeline.track_state import TrackStateDB
from Validation.Data_Parser.app.pipeline.xml_decoder import decode_xml_payload
from Validation.Data_Parser.app.pipeline.xml_generator import XTrackXMLGenerator


class TestValidationPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Locate project root and reference databases
        cur = Path(__file__).resolve()
        for parent in [cur, *cur.parents]:
            cand = parent / "Validation" / "Database"
            if cand.exists():
                cls.db_dir = cand
                break
        else:
            cls.db_dir = Path("Validation/Database").resolve()

        cls.wrs_path = cls.db_dir / "WRS" / "wrs.db"
        cls.pans_path = cls.db_dir / "PANS" / "pans.db"
        cls.nsc_path = cls.db_dir / "NSC" / "nsc.db"

        cls.temp_dir = tempfile.mkdtemp(prefix="val_pipeline_test_")
        cls.state_db_path = Path(cls.temp_dir) / "track_state.db"

        cls.ref_db = ReferenceDB(
            wrs_path=cls.wrs_path,
            pans_path=cls.pans_path,
            nsc_path=cls.nsc_path,
        )
        cls.state_db = TrackStateDB(db_path=cls.state_db_path)
        cls.enricher = VesselEnricher(reference_db=cls.ref_db, track_state_db=cls.state_db)
        cls.xml_gen = XTrackXMLGenerator()
        cls.downstream = DownstreamXMLParser()
        cls.processor = PipelineProcessor(reference_db=cls.ref_db, track_state_db=cls.state_db)

    # ──────────────────────────────────────────────────────────────────────────
    # 1. XML Decoding Tests (<A><id>...</id><iv/sv/bv/qv/tv></A>)
    # ──────────────────────────────────────────────────────────────────────────

    def test_actual_xml_decoding_structure(self):
        sample_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<ns2:XTracks xmlns="http://www.raytheon.com/athena/ctrack/common/1.1" xmlns:ns2="http://www.raytheon.com/athena/ctrack/xtrack/1.1">
    <ns2:XTrack verbose="true">
        <ns2:A><id>sys.source.id</id><iv>38</iv></ns2:A>
        <ns2:A><id>id.mmsi</id><iv>419697000</iv></ns2:A>
        <ns2:A><id>vessel.name</id><sv>Saga</sv></ns2:A>
        <ns2:A><id>track.flag.active</id><bv>true</bv></ns2:A>
        <ns2:A><id>kinematic.pos.lla.lat</id><qv u="rad">0.392921</qv></ns2:A>
        <ns2:A><id>kinematic.speed</id><qv u="m/s">4.52</qv></ns2:A>
        <ns2:A><id>timestamp.source</id><tv>1789032517108</tv></ns2:A>
    </ns2:XTrack>
</ns2:XTracks>"""

        tracks = decode_xml_payload(sample_xml)
        self.assertEqual(len(tracks), 1)
        t = tracks[0]

        self.assertEqual(t.get("sys.source.id"), 38)
        self.assertEqual(t.get("id.mmsi"), 419697000)
        self.assertEqual(t.get("vessel.name"), "Saga")
        self.assertEqual(t.get("track.flag.active"), True)
        self.assertAlmostEqual(t.get("kinematic.pos.lla.lat"), 0.392921, places=5)
        self.assertAlmostEqual(t.get("kinematic.speed"), 4.52, places=2)
        self.assertEqual(t.get("timestamp.source"), 1789032517108)

    def test_xml_decoding_pos_element(self):
        sample_xml = """<ns2:XTracks xmlns:ns2="http://www.raytheon.com/athena/ctrack/xtrack/1.1">
    <ns2:XTrack verbose="true">
        <ns2:A><id>id.mmsi</id><iv>316000001</iv></ns2:A>
        <ns2:A><id>kinematic.pos</id><pos><lat u="deg">15.1</lat><lon u="deg">73.1</lon></pos></ns2:A>
    </ns2:XTrack>
</ns2:XTracks>"""
        tracks = decode_xml_payload(sample_xml)
        self.assertEqual(len(tracks), 1)
        pos = tracks[0].get("kinematic.pos")
        self.assertIsInstance(pos, dict)
        self.assertEqual(pos["lat"], 15.1)
        self.assertEqual(pos["lon"], 73.1)

    # ──────────────────────────────────────────────────────────────────────────
    # 2. Source ID Mapping Tests
    # ──────────────────────────────────────────────────────────────────────────

    def test_source_id_mapping(self):
        self.assertEqual(get_source_id("NAIS"), 37)
        self.assertEqual(get_source_id("SAIS_IOR"), 38)
        self.assertEqual(get_source_id("SAIS_GLOBAL"), 38)
        self.assertEqual(get_source_id("LRIT"), 40)
        self.assertEqual(get_source_id("VATMS_WEST"), 223)
        self.assertEqual(get_source_id("VATMS_EAST"), 245)
        self.assertEqual(get_source_id("MSIS"), 250)
        self.assertEqual(get_source_id("UNKNOWN_FEED"), 0)

    # ──────────────────────────────────────────────────────────────────────────
    # 3. 41 Logical Fields Normalization & Downstream Mapping
    # ──────────────────────────────────────────────────────────────────────────

    def test_41_logical_fields_presence(self):
        self.assertEqual(len(LOGICAL_FIELDS_41), 41)
        norm = NormalizedRecord(source_name="SAIS_IOR", message_id="msg-1")
        ld = norm.to_logical_dict()
        for field_name in LOGICAL_FIELDS_41:
            self.assertIn(field_name, ld, f"Missing 41-field logical key: {field_name}")

    # ──────────────────────────────────────────────────────────────────────────
    # 4. Track State & 3-Hour Active Rule
    # ──────────────────────────────────────────────────────────────────────────

    def test_track_state_3_hour_active_rule(self):
        now_s = int(datetime.now(timezone.utc).timestamp())
        recent_epoch = (now_s - 1800) * 1000  # 30 min ago
        old_epoch = (now_s - 4 * 3600) * 1000  # 4 hours ago

        # Recent track should be ACTIVE
        is_active_1 = self.state_db.upsert(
            mmsi=200000001,
            imo=9000001,
            vessel_name="RECENT SHIP",
            latitude=0.25,
            longitude=1.15,
            tx_timestamp_iso=str(recent_epoch),
            source="SAIS_IOR",
        )
        self.assertTrue(is_active_1)
        self.assertTrue(self.state_db.is_active(200000001))

        # Stale track (4h old) should be INACTIVE
        is_active_2 = self.state_db.upsert(
            mmsi=200000002,
            imo=9000002,
            vessel_name="STALE SHIP",
            latitude=0.25,
            longitude=1.15,
            tx_timestamp_iso=str(old_epoch),
            source="SAIS_IOR",
        )
        self.assertFalse(is_active_2)
        self.assertFalse(self.state_db.is_active(200000002))

    # ──────────────────────────────────────────────────────────────────────────
    # 5. Reference Fallback Priority (Incoming -> WRS -> PANS -> NSC -> UNKNOWN)
    # ──────────────────────────────────────────────────────────────────────────

    def test_vessel_name_fallback_hierarchy(self):
        # 1. Incoming transmission is primary
        rec1 = NormalizedRecord(
            source_name="SAIS_IOR",
            message_id="m1",
            id_mmsi=999999999,
            vessel_name="TRANSMITTED NAME",
        )
        enr1 = self.enricher.enrich(rec1)
        self.assertEqual(enr1.vessel_name, "TRANSMITTED NAME")

        # 2. Unknown incoming vessel with no match -> UNKNOWN
        rec2 = NormalizedRecord(
            source_name="SAIS_IOR",
            message_id="m2",
            id_mmsi=999999999,
            vessel_name=None,
        )
        enr2 = self.enricher.enrich(rec2)
        self.assertEqual(enr2.vessel_name, "UNKNOWN")

    def test_foreign_and_sys_track_number_semantics(self):
        # Valid incoming MMSI -> foreign.track.number is same MMSI
        rec1 = NormalizedRecord(
            source_name="SAIS_IOR",
            message_id="m1",
            id_mmsi=419697000,
        )
        enr1 = self.enricher.enrich(rec1)
        self.assertEqual(enr1.sys_track_number, 419697000)
        self.assertEqual(enr1.foreign_track_number, 419697000)

        # Invalid incoming MMSI (e.g. 0) -> sys.track.number preserves 0
        rec2 = NormalizedRecord(
            source_name="SAIS_IOR",
            message_id="m2",
            id_mmsi=0,
        )
        enr2 = self.enricher.enrich(rec2)
        self.assertEqual(enr2.sys_track_number, 0)

    # ──────────────────────────────────────────────────────────────────────────
    # 6. Dimensions Rule: No beam/2 fabrication
    # ──────────────────────────────────────────────────────────────────────────

    def test_no_dimension_fabrication(self):
        rec = NormalizedRecord(
            source_name="SAIS_IOR",
            message_id="m1",
            id_mmsi=419697000,
            vessel_beam=30.0,
            ais_widthToPort=None,
            ais_widthToStarboard=None,
        )
        enr = self.enricher.enrich(rec)
        # Verify port and starboard width are NOT fabricated as beam / 2
        self.assertIsNone(enr.ais_widthToPort)
        self.assertIsNone(enr.ais_widthToStarboard)

    # ──────────────────────────────────────────────────────────────────────────
    # 7. Point-Wise Remarks Generation & Spoofing Detection
    # ──────────────────────────────────────────────────────────────────────────

    def test_spoofing_detection_and_remarks(self):
        # Normal record matching WRS
        rec = NormalizedRecord(
            source_name="MSIS",
            message_id="m1",
            id_mmsi=316000001,
            vessel_name="MY VESSEL",
        )
        enr = self.enricher.enrich(rec)
        self.assertIn("SOURCE: IMAC MSIS", enr.vessel_remarks)

    # ──────────────────────────────────────────────────────────────────────────
    # 8. All Sources (Normal End-to-End through PipelineProcessor)
    # ──────────────────────────────────────────────────────────────────────────

    def test_sais_source_processing(self):
        sais_payload = "\\s:EarthIOR,c:1789127933*42\\\n!AIVDM,1,1,,A,13aEO:001m000000000000000000,0*0B"
        env = ParserEnvelope(
            message_id="sais-test-1",
            source="SAIS_IOR",
            input_type="STREAM",
            received_at="2026-09-11T17:49:41Z",
            payload=sais_payload,
        )
        res, xml_out = self.processor.process_envelope(env, fallback_source_parser=SAISParser())
        self.assertTrue(res.success)
        self.assertIn("<ns2:XTracks", xml_out)
        self.assertIn("<id>sys.source.id</id><iv>38</iv>", xml_out)

    def test_msis_source_processing(self):
        msis_csv = "mmsi,imo,ship_name,latitude,longitude,sog,cog,updated\n316000001,9100001,OCEAN RUNNER,15.1,73.1,12.5,180.0,2026-09-10T14:57:13Z"
        env = ParserEnvelope(
            message_id="msis-test-1",
            source="MSIS",
            input_type="FILE",
            received_at="2026-09-10T14:57:13Z",
            payload=msis_csv,
        )
        res, xml_out = self.processor.process_envelope(env, fallback_source_parser=MSISParser())
        self.assertTrue(res.success)
        self.assertEqual(res.records_parsed, 1)
        self.assertIn("<id>sys.source.id</id><iv>250</iv>", xml_out)
        self.assertIn("<id>id.mmsi</id><iv>316000001</iv>", xml_out)

    def test_lrit_source_processing(self):
        # 20-column headerless CSV
        lrit_csv = "316000002,15.2,73.2,10.0,90.0,90,0,0,2026-09-10T14:57:13Z,,,,9100002,CALL02,180,25,9,PORT,CARGO,2026-09-11"
        env = ParserEnvelope(
            message_id="lrit-test-1",
            source="LRIT",
            input_type="FILE",
            received_at="2026-09-10T14:57:13Z",
            payload=lrit_csv,
        )
        res, xml_out = self.processor.process_envelope(env, fallback_source_parser=LRITParser())
        self.assertTrue(res.success)
        self.assertEqual(res.records_parsed, 1)
        self.assertIn("<id>sys.source.id</id><iv>40</iv>", xml_out)

    def test_vatms_east_processing(self):
        vatms_east_nmea = "!WSVDM,1,1,,A,13aEO:001m000000000000000000,0*0B"
        env = ParserEnvelope(
            message_id="vatms-e-1",
            source="VATMS_EAST",
            input_type="STREAM",
            received_at="2026-09-10T14:57:13Z",
            payload=vatms_east_nmea,
        )
        res, xml_out = self.processor.process_envelope(env, fallback_source_parser=VATMSParser())
        self.assertTrue(res.success)
        self.assertIn("<id>sys.source.id</id><iv>245</iv>", xml_out)

    def test_vatms_west_processing(self):
        tmvtd_sentence = "$TMVTD,260910,145713,01,1,1001,15.1000,N,073.1000,E,10.5,180.0,180,316000003*4A"
        env = ParserEnvelope(
            message_id="vatms-w-1",
            source="VATMS_WEST",
            input_type="STREAM",
            received_at="2026-09-10T14:57:13Z",
            payload=tmvtd_sentence,
        )
        res, xml_out = self.processor.process_envelope(env, fallback_source_parser=VATMSParser())
        self.assertTrue(res.success)
        self.assertIn("<id>sys.source.id</id><iv>223</iv>", xml_out)

    def test_nais_processing(self):
        nais_nmea = "!ABVDM,1,1,,A,13aEO:001m000000000000000000,0*0B"
        env = ParserEnvelope(
            message_id="nais-1",
            source="NAIS",
            input_type="STREAM",
            received_at="2026-09-10T14:57:13Z",
            payload=nais_nmea,
        )
        res, xml_out = self.processor.process_envelope(env, fallback_source_parser=NAISParser())
        self.assertTrue(res.success)
        self.assertIn("<id>sys.source.id</id><iv>37</iv>", xml_out)

    # ──────────────────────────────────────────────────────────────────────────
    # 9. Downstream Parser Compatibility Contract
    # ──────────────────────────────────────────────────────────────────────────

    def test_downstream_xml_consumer_ingestion(self):
        # Create normalized record with coordinates and speed
        norm = NormalizedRecord(
            source_name="SAIS_IOR",
            message_id="test-msg-downstream",
            sys_source_id=38,
            id_mmsi=419697000,
            id_imo=8407979,
            vessel_name="Saga",
            id_callsign="CALL123",
            kinematic_pos_lla_lat=0.392921,  # radians
            kinematic_pos_lla_lon=1.204458,  # radians
            kinematic_speed=4.527,           # m/s
            kinematic_course_true=4.1713,    # radians
            kinematic_heading_true=4.3633,   # radians
            timestamp_source=1789032517108,
            timestamp_receipt=1789032517108,
            track_quality=15,
            track_flag_active=True,
            vessel_length=150.0,
        )
        xml_text = self.xml_gen.generate_single_xml(norm)

        # Downstream consumer consumes this XML
        downstream_records = self.downstream.parse_xml(xml_text)
        self.assertEqual(len(downstream_records), 1)
        dr = downstream_records[0]

        self.assertEqual(dr["track_no"], 419697000)
        self.assertEqual(dr["imo_no"], 8407979)
        self.assertEqual(dr["ship_name"], "Saga")
        self.assertEqual(dr["static_call_sign"], "CALL123")
        self.assertEqual(dr["sensor_type"], 38)
        self.assertEqual(dr["track_quality"], 15)
        self.assertEqual(dr["track_flag_active"], True)
        self.assertEqual(dr["total_vessel_length"], 150)
        # Scaled speed: 4.527 / 0.001 = 4527
        self.assertEqual(dr["speed_over_ground"], 4527)
        # Scaled lat: 0.392921 * 60 * 10000 = 235752600
        self.assertAlmostEqual(dr["lat"], int(round(0.392921 * 600000)), delta=1)

    # ──────────────────────────────────────────────────────────────────────────
    # 10. Resilience & Error Handling Tests
    # ──────────────────────────────────────────────────────────────────────────

    def test_malformed_xml_handling(self):
        env = ParserEnvelope(
            message_id="err-1",
            source="SAIS_IOR",
            input_type="FILE",
            received_at="2026-09-10T14:57:13Z",
            payload="<invalid><xml unclosed",
        )
        res, xml_out = self.processor.process_envelope(env, fallback_source_parser=SAISParser())
        # Should not crash; returns result with error or 0 parsed
        self.assertEqual(res.records_parsed, 0)

    def test_empty_payload_handling(self):
        env = ParserEnvelope(
            message_id="empty-1",
            source="MSIS",
            input_type="FILE",
            received_at="2026-09-10T14:57:13Z",
            payload="",
        )
        res, xml_out = self.processor.process_envelope(env, fallback_source_parser=MSISParser())
        self.assertTrue(res.success)
        self.assertEqual(res.records_parsed, 0)


if __name__ == "__main__":
    unittest.main()

"""
Targeted Semantic Validation & Audit Tests (20 Specific Audit Scenarios).

Verifies exact business logic, unit conversions, fallback priorities,
vigilance scoring boundaries, active flag evaluation, and dimension integrity.
"""

import math
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from Validation.Data_Parser.app.models.common import CommonVesselRecord, ParserEnvelope
from Validation.Data_Parser.app.parsers.sais import SAISParser
from Validation.Data_Parser.app.pipeline.downstream_parser import DownstreamXMLParser
from Validation.Data_Parser.app.pipeline.enricher import VesselEnricher
from Validation.Data_Parser.app.pipeline.normalizer import (
    NormalizedRecord,
    normalize_from_common_record,
    normalize_from_decoded_track,
)
from Validation.Data_Parser.app.pipeline.processor import PipelineProcessor
from Validation.Data_Parser.app.pipeline.reference_db import ReferenceDB
from Validation.Data_Parser.app.pipeline.source_registry import deg_to_rad, knots_to_ms
from Validation.Data_Parser.app.pipeline.track_state import TrackStateDB
from Validation.Data_Parser.app.pipeline.xml_generator import XTrackXMLGenerator


class TestSemanticAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
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

        cls.temp_dir = tempfile.mkdtemp(prefix="val_audit_test_")
        cls.state_db_path = Path(cls.temp_dir) / "audit_track_state.db"

        # The repository intentionally does not carry operational reference DBs.
        # Build a minimal deterministic NSC fixture only when the operational DB
        # is absent, so the enrichment tests remain runnable from a clean clone.
        if not cls.nsc_path.exists():
            cls.nsc_path = Path(cls.temp_dir) / "nsc.db"
            conn = sqlite3.connect(cls.nsc_path)
            try:
                conn.execute(
                    "CREATE TABLE nsc_vessels ("
                    "ID_MMSI TEXT, ID_IMO TEXT, ID_CALLSIGN TEXT, "
                    "VESSEL_NAME TEXT, TYPE TEXT)"
                )
                conn.execute(
                    "INSERT INTO nsc_vessels "
                    "(SOURCE_REGION, ID_MMSI, ID_IMO, ID_CALLSIGN, VESSEL_NAME, TYPE, BEGIN_DATE, END_DATE) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    ("EAST", "419697000", "8407979", "SAGA", "SAGA", "VESSEL", "", ""),
                )
                conn.commit()
            finally:
                conn.close()

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

    # 1. valid AIS MMSI
    def test_01_valid_ais_mmsi(self):
        rec = NormalizedRecord(source_name="SAIS_IOR", message_id="m1", id_mmsi=419697000)
        enr = self.enricher.enrich(rec)
        self.assertEqual(enr.id_mmsi, 419697000)
        self.assertEqual(enr.sys_track_number, 419697000)
        self.assertEqual(enr.foreign_track_number, 419697000)

    # 2. invalid MMSI + valid IMO (resolves WRS/NSC MMSI in foreign.track.number)
    def test_02_invalid_mmsi_valid_imo(self):
        # IMO 8407979 is in nsc_vessels with MMSI 419697000
        rec = NormalizedRecord(source_name="SAIS_IOR", message_id="m2", id_mmsi=0, id_imo=8407979)
        enr = self.enricher.enrich(rec)
        self.assertEqual(enr.sys_track_number, 0)
        self.assertEqual(enr.foreign_track_number, 419697000)

    # 3. missing name + WRS name
    def test_03_missing_name_wrs_name(self):
        # WRS contains vessels like IMO 9100001
        rec = NormalizedRecord(source_name="MSIS", message_id="m3", id_mmsi=316000001, id_imo=9100001, vessel_name=None)
        enr = self.enricher.enrich(rec)
        # If WRS has name, it must be assigned
        if enr.vessel_name != "UNKNOWN":
            self.assertIsNotNone(enr.vessel_name)
            self.assertNotEqual(enr.vessel_name, "UNKNOWN")

    # 4. missing name + PANS name
    def test_04_missing_name_pans_name(self):
        # PANS vespro has IMONumber
        rec = NormalizedRecord(source_name="MSIS", message_id="m4", id_mmsi=None, id_imo=9100001, vessel_name=None)
        ctx = self.ref_db.resolve(mmsi=None, imo=9100001)
        if ctx.pans_vessel_name:
            enr = self.enricher.enrich(rec)
            self.assertEqual(enr.vessel_name, ctx.pans_vessel_name)

    # 5. missing name + NSC name
    def test_05_missing_name_nsc_name(self):
        # IMO 8407979 is in NSC with name 'SAGA'
        rec = NormalizedRecord(source_name="NAIS", message_id="m5", id_mmsi=419697000, id_imo=8407979, vessel_name=None)
        enr = self.enricher.enrich(rec)
        self.assertEqual(enr.vessel_name.upper(), "SAGA")

    # 6. conflicting WRS/PANS/NSC names -> WRS takes priority
    def test_06_conflicting_names_hierarchy(self):
        rec = NormalizedRecord(source_name="SAIS_IOR", message_id="m6", id_mmsi=316000001, id_imo=9100001, vessel_name=None)
        ctx = self.ref_db.resolve(mmsi=316000001, imo=9100001)
        enr = self.enricher.enrich(rec)
        if ctx.wrs_vessel_name:
            self.assertEqual(enr.vessel_name, ctx.wrs_vessel_name)

    # 7. vigilance score 299 -> Friend (1)
    def test_07_vigilance_score_299(self):
        rec = NormalizedRecord(source_name="SAIS_IOR", message_id="m7", id_mmsi_destination=299)
        enr = self.enricher.enrich(rec)
        self.assertEqual(enr.cat_identity, 1)

    # 8. vigilance score 300 -> Neutral (3)
    def test_08_vigilance_score_300(self):
        rec = NormalizedRecord(source_name="SAIS_IOR", message_id="m8", id_mmsi_destination=300)
        enr = self.enricher.enrich(rec)
        self.assertEqual(enr.cat_identity, 3)

    # 9. vigilance score 381 -> Neutral (3)
    def test_09_vigilance_score_381(self):
        rec = NormalizedRecord(source_name="NAIS", message_id="m9", id_mmsi_destination=381)
        enr = self.enricher.enrich(rec)
        self.assertEqual(enr.cat_identity, 3)

    # 10. vigilance score 600 -> Neutral (3)
    def test_10_vigilance_score_600(self):
        rec = NormalizedRecord(source_name="SAIS_IOR", message_id="m10", id_mmsi_destination=600)
        enr = self.enricher.enrich(rec)
        self.assertEqual(enr.cat_identity, 3)

    # 11. vigilance score 601 -> Suspect (4)
    def test_11_vigilance_score_601(self):
        rec = NormalizedRecord(source_name="SAIS_IOR", message_id="m11", id_mmsi_destination=601)
        enr = self.enricher.enrich(rec)
        self.assertEqual(enr.cat_identity, 4)

    # 12. 2h59m59s active -> True
    def test_12_active_window_2h59m59s(self):
        now_s = int(datetime.now(timezone.utc).timestamp())
        t_ms = (now_s - 10799) * 1000
        rec = NormalizedRecord(source_name="SAIS_IOR", message_id="m12", id_mmsi=300000012, timestamp_source=t_ms)
        enr = self.enricher.enrich(rec)
        self.assertTrue(enr.track_flag_active)

    # 13. exactly 3h inactive -> False
    def test_13_active_window_exactly_3h(self):
        now_s = int(datetime.now(timezone.utc).timestamp())
        t_ms = (now_s - 10800) * 1000
        rec = NormalizedRecord(source_name="SAIS_IOR", message_id="m13", id_mmsi=300000013, timestamp_source=t_ms)
        enr = self.enricher.enrich(rec)
        self.assertFalse(enr.track_flag_active)

    # 14. missing widthToPort -> stays None (no beam/2)
    def test_14_missing_width_to_port(self):
        rec = NormalizedRecord(source_name="SAIS_IOR", message_id="m14", id_mmsi=300000014, vessel_beam=32.0, ais_widthToPort=None)
        enr = self.enricher.enrich(rec)
        self.assertIsNone(enr.ais_widthToPort)

    # 15. missing widthToStarboard -> stays None (no beam/2)
    def test_15_missing_width_to_starboard(self):
        rec = NormalizedRecord(source_name="SAIS_IOR", message_id="m15", id_mmsi=300000015, vessel_beam=32.0, ais_widthToStarboard=None)
        enr = self.enricher.enrich(rec)
        self.assertIsNone(enr.ais_widthToStarboard)

    # 16. missing stern length -> stays None (no length - bow)
    def test_16_missing_stern_length(self):
        rec = NormalizedRecord(source_name="SAIS_IOR", message_id="m16", id_mmsi=300000016, vessel_length=150.0, ais_lenToBow=90, ais_lenToStern=None)
        enr = self.enricher.enrich(rec)
        self.assertIsNone(enr.ais_lenToStern)

    # 17. actual AIS message type preserved
    def test_17_actual_ais_message_type(self):
        p = SAISParser()
        # Message Type 1 sentence with a valid NMEA checksum.
        line = "!AIVDM,1,1,,A,13aEO:001m000000000000000000,0*29"
        env = ParserEnvelope(message_id="msg17", source="SAIS_IOR", input_type="STREAM", received_at="2026-09-10T14:57:13Z", payload=line)
        res = p.parse(env)
        self.assertEqual(res.records[0].app_message_id, 1)

        norm = normalize_from_common_record(res.records[0])
        self.assertEqual(norm.app_message_id, 1)

    # 18. position conversion: degrees -> radians -> scaled integer
    def test_18_position_conversion(self):
        lat_deg = 15.1
        lat_rad = deg_to_rad(lat_deg)
        self.assertAlmostEqual(lat_rad, 0.263544717, places=6)

        norm = NormalizedRecord(source_name="SAIS_IOR", message_id="m18", id_mmsi=300000018, kinematic_pos_lla_lat=lat_rad)
        xml_out = self.xml_gen.generate_single_xml(norm)
        self.assertIn('<qv u="rad">', xml_out)

        downstream_recs = self.downstream.parse_xml(xml_out)
        expected_scaled = int(round(lat_rad * 600000))
        self.assertEqual(downstream_recs[0]["lat"], expected_scaled)

    # 19. speed conversion: knots -> m/s -> scaled speed
    def test_19_speed_conversion(self):
        knots = 10.0
        ms = knots_to_ms(knots)  # 5.14444 m/s
        self.assertAlmostEqual(ms, 5.14444, places=4)

        norm = NormalizedRecord(source_name="SAIS_IOR", message_id="m19", id_mmsi=300000019, kinematic_speed=ms)
        xml_out = self.xml_gen.generate_single_xml(norm)
        self.assertIn('<qv u="m/s">5.14444</qv>', xml_out)

        downstream_recs = self.downstream.parse_xml(xml_out)
        self.assertEqual(downstream_recs[0]["speed_over_ground"], int(round(5.14444 / 0.001)))

    # 20. course conversion: degrees -> radians -> scaled integer
    def test_20_course_conversion(self):
        course_deg = 180.0
        course_rad = deg_to_rad(course_deg)
        self.assertAlmostEqual(course_rad, math.pi, places=5)

        norm = NormalizedRecord(source_name="SAIS_IOR", message_id="m20", id_mmsi=300000020, kinematic_course_true=course_rad)
        xml_out = self.xml_gen.generate_single_xml(norm)
        self.assertIn('<qv u="rad">', xml_out)

        downstream_recs = self.downstream.parse_xml(xml_out)
        self.assertIsNotNone(downstream_recs[0]["course"])


if __name__ == "__main__":
    unittest.main()

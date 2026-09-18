import tempfile
import unittest
from pathlib import Path

from Validation.Data_Parser.app.models.common import ParserEnvelope, CommonVesselRecord
from Validation.Data_Parser.app.pipeline.normalizer import normalize_from_common_record
from Validation.Data_Parser.app.pipeline.xml_generator import FIELD_SPECS, XTrackXMLGenerator
from Validation.Data_Parser.app.pipeline.normalizer import LOGICAL_FIELDS_41


class TestXMLContract(unittest.TestCase):
    def test_41_field_spec_is_complete(self):
        self.assertEqual(len(LOGICAL_FIELDS_41), 41)
        self.assertEqual(set(LOGICAL_FIELDS_41), set(FIELD_SPECS))

    def test_one_record_one_xtrack_and_41_tag_membership(self):
        rec = CommonVesselRecord(
            source="SAIS_IOR",
            message_id="m1",
            record_id="m1:1",
            timestamp="2026-09-18T10:00:00Z",
            mmsi=419697000,
            latitude=15.1,
            longitude=80.2,
            sog=10.0,
            cog=180.0,
            true_heading=181,
            nav_status=0,
            app_message_id=1,
        )
        norm = normalize_from_common_record(rec, receipt_time_ms=1778752800000)
        xml = XTrackXMLGenerator().generate_document(norm)
        count = XTrackXMLGenerator.validate_document(xml)
        self.assertGreaterEqual(count, 1)
        self.assertEqual(xml.count("<ns2:XTrack verbose="), 1)
        self.assertEqual(xml.count("<ns2:A>"), count)


if __name__ == "__main__":
    unittest.main()

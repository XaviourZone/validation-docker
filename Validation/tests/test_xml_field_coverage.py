"""Tests for the canonical XML field-coverage reporting helper."""

import tempfile
import unittest
from pathlib import Path

from Validation.Data_Parser.app.pipeline.normalizer import LOGICAL_FIELDS_41
from scripts.xml_field_coverage import extract_fields


class TestXMLFieldCoverage(unittest.TestCase):
    def test_extracts_canonical_ids_per_xtrack(self):
        fields = list(LOGICAL_FIELDS_41)
        xml = (
            '<XTrack xmlns="urn:test">'
            '<A><id>id.mmsi</id><qv u="none">419697000</qv></A>'
            '<A><id>vessel.name</id><sv>SAGA</sv></A>'
            '</XTrack>'
        )
        found = extract_fields(xml)
        self.assertEqual(found, {"id.mmsi", "vessel.name"})
        self.assertEqual(len(fields), 41)

    def test_reporter_can_parse_multiple_documents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "one.xml").write_text(
                '<XTrack xmlns="urn:test"><A><id>id.mmsi</id></A></XTrack>',
                encoding="utf-8",
            )
            (root / "two.xml").write_text(
                '<XTrack xmlns="urn:test"><A><id>vessel.name</id></A></XTrack>',
                encoding="utf-8",
            )
            found = [extract_fields(p.read_text(encoding="utf-8")) for p in sorted(root.glob("*.xml"))]
            self.assertEqual(found, [{"id.mmsi"}, {"vessel.name"}])


if __name__ == "__main__":
    unittest.main()

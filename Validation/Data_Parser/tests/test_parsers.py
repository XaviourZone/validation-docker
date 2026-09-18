"""Automated unit tests for all source-specific parsers against actual SAMPLE_DATA."""

import unittest
from pathlib import Path

from Validation.Data_Parser.app.models.common import ParserEnvelope
from Validation.Data_Parser.app.parsers.lrit import LRITParser
from Validation.Data_Parser.app.parsers.msis import MSISParser
from Validation.Data_Parser.app.parsers.nais import NAISParser
from Validation.Data_Parser.app.parsers.sais import SAISParser
from Validation.Data_Parser.app.parsers.vatms import VATMSParser


class TestParsersWithSampleData(unittest.TestCase):
    """Verifies that each parser handles real sample data without error."""

    @classmethod
    def setUpClass(cls):
        cls.workspace_root = Path(__file__).resolve().parent.parent.parent.parent
        cls.sample_root = cls.workspace_root / "Validation" / "SAMPLE_DATA"

    def test_sais_ior_real_sample(self):
        sample = self.sample_root / "SAIS" / "SAIS_IOR" / "EarthIOR_2026-06-25-14-21-28.csv"
        self.assertTrue(sample.exists())
        content = sample.read_text(encoding="utf-8")

        env = ParserEnvelope("file:sais_ior:1", "SAIS_IOR", "FILE", "2026-09-17T00:00:00Z", content)
        parser = SAISParser()
        result = parser.parse(env)

        self.assertTrue(result.success)
        self.assertGreater(result.records_parsed, 9000)
        self.assertEqual(result.records_rejected, 0)
        self.assertEqual(result.source, "SAIS_IOR")
        # Check first record provenance and coordinates
        rec = result.records[0]
        self.assertEqual(rec.source, "SAIS_IOR")
        self.assertIsNotNone(rec.mmsi)
        self.assertIsNotNone(rec.latitude)
        self.assertIsNotNone(rec.longitude)

    def test_sais_global_real_sample(self):
        sample = self.sample_root / "SAIS" / "SAIS_GLOBAL" / "EarthGLOBAL_2026-06-25-14-21-39.csv"
        self.assertTrue(sample.exists())
        content = sample.read_text(encoding="utf-8")

        env = ParserEnvelope("file:sais_global:2", "SAIS_GLOBAL", "FILE", "2026-09-17T00:00:00Z", content)
        parser = SAISParser()
        result = parser.parse(env)

        self.assertTrue(result.success)
        self.assertGreater(result.records_parsed, 9000)
        self.assertEqual(result.records_rejected, 0)
        self.assertEqual(result.source, "SAIS_GLOBAL")
        self.assertEqual(result.records[0].source, "SAIS_GLOBAL")

    def test_msis_real_sample(self):
        sample = self.sample_root / "MSIS" / "nc3in_20260604_120020.csv"
        self.assertTrue(sample.exists())
        content = sample.read_text(encoding="utf-8")

        env = ParserEnvelope("file:msis:1", "MSIS", "FILE", "2026-09-17T00:00:00Z", content)
        parser = MSISParser()
        result = parser.parse(env)

        self.assertTrue(result.success)
        self.assertEqual(result.records_parsed, 116)
        self.assertEqual(result.records_rejected, 0)
        rec = result.records[0]
        self.assertEqual(rec.source, "MSIS")
        self.assertEqual(rec.mmsi, 224099000)
        self.assertEqual(rec.vessel_name, "TUMBERRY C")
        self.assertEqual(rec.callsign, "EAZX")

    def test_lrit_real_sample_and_empty_file(self):
        sample = self.sample_root / "LRIT" / "LRIT_03062026_093001.csv"
        self.assertTrue(sample.exists())
        content = sample.read_text(encoding="utf-8")

        env = ParserEnvelope("file:lrit:1", "LRIT", "FILE", "2026-09-17T00:00:00Z", content)
        parser = LRITParser()
        result = parser.parse(env)

        self.assertTrue(result.success)
        self.assertEqual(result.records_parsed, 297)
        rec = result.records[0]
        self.assertEqual(rec.source, "LRIT")
        self.assertEqual(rec.mmsi, 419000122)
        self.assertEqual(rec.imo, 9448542)
        self.assertEqual(rec.vessel_name, "OCEAN FAME")

        # Test empty 0-byte file (common in LRIT cron)
        empty_env = ParserEnvelope("file:lrit:empty", "LRIT", "FILE", "2026-09-17T00:00:00Z", "")
        empty_result = parser.parse(empty_env)
        self.assertTrue(empty_result.success)
        self.assertEqual(empty_result.records_parsed, 0)

    def test_vatms_east_real_sample(self):
        sample = self.sample_root / "VATMS" / "VATMS_EAST" / "vatms_east.txt"
        self.assertTrue(sample.exists())
        content = sample.read_text(encoding="utf-8")

        env = ParserEnvelope("tcp:vatms_east:1", "VATMS_EAST", "TCP", "2026-09-17T00:00:00Z", content)
        parser = VATMSParser()
        result = parser.parse(env)

        self.assertTrue(result.success)
        self.assertEqual(result.records_parsed, 248)
        self.assertEqual(result.records[0].source, "VATMS_EAST")

    def test_vatms_west_real_sample(self):
        sample = self.sample_root / "VATMS" / "VATMS_WEST" / "vatms_west.txt"
        self.assertTrue(sample.exists())
        content = sample.read_text(encoding="utf-8")

        env = ParserEnvelope("tcp:vatms_west:1", "VATMS_WEST", "TCP", "2026-09-17T00:00:00Z", content)
        parser = VATMSParser()
        result = parser.parse(env)

        self.assertTrue(result.success)
        self.assertEqual(result.records_parsed, 1523)
        self.assertEqual(result.records[0].source, "VATMS_WEST")

    def test_nais_real_sample(self):
        sample = self.sample_root / "NAIS" / "Nais.txt"
        self.assertTrue(sample.exists())
        content = sample.read_text(encoding="utf-8")

        env = ParserEnvelope("tcp:nais:1", "NAIS", "TCP", "2026-09-17T00:00:00Z", content)
        parser = NAISParser()
        result = parser.parse(env)

        self.assertTrue(result.success)
        self.assertEqual(result.records_parsed, 918)
        self.assertEqual(result.records[0].source, "NAIS")


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from Validation.Data_Parser.app.models.common import CommonVesselRecord, ParseResult, ParserEnvelope
from Validation.Data_Parser.app.pipeline.processor import PipelineProcessor


class IdentityEnricher:
    def enrich(self, record):
        return record


class FakeParser:
    def parse(self, envelope):
        records = [
            CommonVesselRecord(
                source=envelope.source,
                message_id=envelope.message_id,
                record_id=f"{envelope.message_id}:1",
                timestamp="2026-09-18T10:00:00Z",
                mmsi=419000001,
                latitude=10.0,
                longitude=70.0,
                sog=5.0,
                cog=90.0,
                true_heading=90.0,
                app_message_id=1,
            ),
            CommonVesselRecord(
                source=envelope.source,
                message_id=envelope.message_id,
                record_id=f"{envelope.message_id}:2",
                timestamp="2026-09-18T10:00:01Z",
                mmsi=419000002,
                latitude=10.1,
                longitude=70.1,
                sog=6.0,
                cog=91.0,
                true_heading=91.0,
                app_message_id=1,
            ),
        ]
        return ParseResult(
            message_id=envelope.message_id,
            source=envelope.source,
            success=True,
            records_parsed=2,
            records_rejected=0,
            records=records,
            errors=[],
        )


class TestProcessorSpooling(unittest.TestCase):
    def test_two_records_produce_two_xml_documents(self):
        with tempfile.TemporaryDirectory() as tmp:
            processor = PipelineProcessor(xml_output_dir=Path(tmp))
            processor.enricher = IdentityEnricher()

            envelope = ParserEnvelope(
                message_id="file-1",
                source="SAIS_IOR",
                input_type="FILE",
                received_at="2026-09-18T10:00:00Z",
                payload="line1\nline2",
            )

            result, diagnostic = processor.process_envelope(
                envelope,
                fallback_source_parser=FakeParser(),
            )

            self.assertEqual(result.records_parsed, 2)
            self.assertEqual(len(list(Path(tmp).glob("*.xml"))), 2)
            self.assertEqual(diagnostic.count("<ns2:XTrack verbose="), 2)
            self.assertIn("<id>timestamp.receipt</id>", diagnostic)
            self.assertIn("<tv>1789725600000</tv>", diagnostic)


if __name__ == "__main__":
    unittest.main()

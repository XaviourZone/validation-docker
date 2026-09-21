import tempfile
import time
import unittest
from pathlib import Path

from Validation.Data_Parser.app.models.common import ParseResult, ParserEnvelope
from Validation.Data_Parser.app.server.ingress_queue import DurableIngressQueue


class _Metrics:
    def __init__(self):
        self.results = []

    def record_parse_result(self, **kwargs):
        self.results.append(kwargs)


class _Parser:
    pass


class _Processor:
    def __init__(self):
        self.calls = []

    def process_envelope(self, envelope, fallback_source_parser=None):
        self.calls.append(envelope.message_id)
        return (
            ParseResult(
                message_id=envelope.message_id,
                source=envelope.source,
                success=True,
                records_parsed=1,
                records_rejected=0,
                records=[],
                errors=[],
            ),
            "<XTrack/>",
        )


class TestDurableIngressQueue(unittest.TestCase):
    def make_envelope(self, message_id="msg-1"):
        return ParserEnvelope(
            message_id=message_id,
            source="SAIS_GLOBAL",
            input_type="FILE",
            received_at="2026-09-21T00:00:00+00:00",
            payload="!AIVDM,test",
            filename="sample.csv",
            file_size=10,
            file_hash="abc",
        )

    def test_enqueue_is_durable_and_duplicate_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            processor = _Processor()
            queue = DurableIngressQueue(
                root_dir=Path(tmp),
                endpoint_name="SAIS",
                processor=processor,
                parser=_Parser(),
                metrics_collector=_Metrics(),
            )

            envelope = self.make_envelope()
            self.assertTrue(queue.enqueue(envelope))
            self.assertEqual(queue.pending_count(), 1)
            self.assertTrue(queue.enqueue(envelope))
            self.assertEqual(queue.pending_count(), 1)

    def test_worker_processes_pending_and_marks_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            processor = _Processor()
            queue = DurableIngressQueue(
                root_dir=Path(tmp),
                endpoint_name="LRIT",
                processor=processor,
                parser=_Parser(),
                metrics_collector=_Metrics(),
                poll_interval=0.05,
            )

            envelope = self.make_envelope("lrit-1")
            self.assertTrue(queue.enqueue(envelope))
            queue.start()
            try:
                deadline = time.time() + 3
                while time.time() < deadline and queue.done_count() != 1:
                    time.sleep(0.05)
            finally:
                queue.stop()

            self.assertEqual(queue.done_count(), 1)
            self.assertEqual(queue.pending_count(), 0)
            self.assertEqual(processor.calls, ["lrit-1"])


if __name__ == "__main__":
    unittest.main()

"""Integration test for Data Parser TCP endpoint and HTTP status server."""

import json
import socket
import time
import unittest
import urllib.request

from Validation.Data_Parser.app.metrics.collector import ParserMetricsCollector
from Validation.Data_Parser.app.models.common import ParserEnvelope
from Validation.Data_Parser.app.parsers.sais import SAISParser
from Validation.Data_Parser.app.server.api_server import ParserAPIServer
from Validation.Data_Parser.app.server.endpoint import ParserEndpointServer


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestParserServiceIntegration(unittest.TestCase):
    """Verifies TCP NDJSON envelope ingestion, ACK responses, and HTTP telemetry."""

    @classmethod
    def setUpClass(cls):
        cls.tcp_port = find_free_port()
        cls.http_port = find_free_port()
        cls.metrics = ParserMetricsCollector()
        cls.parser = SAISParser()

        cls.endpoint = ParserEndpointServer(
            name="SAIS",
            host="127.0.0.1",
            port=cls.tcp_port,
            parser=cls.parser,
            metrics_collector=cls.metrics,
        )
        cls.endpoint.start()

        cls.api = ParserAPIServer(
            host="127.0.0.1",
            port=cls.http_port,
            metrics_collector=cls.metrics,
            endpoint_names=["SAIS"],
        )
        import threading
        cls.api_thread = threading.Thread(target=cls.api.start, daemon=True)
        cls.api_thread.start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls):
        cls.endpoint.stop()
        cls.api.shutdown()

    def test_tcp_envelope_and_ack(self):
        envelope = {
            "message_id": "file:sais_ior:integration_test",
            "source": "SAIS_IOR",
            "input_type": "FILE",
            "received_at": "2026-09-17T00:00:00Z",
            "payload": "\\s:66,c:1782377468*4C\\!AIVDM,1,1,,B,177hgW001bWc5el;kRfmHl@<00SR,0*47\n",
            "filename": "test.csv",
        }

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect(("127.0.0.1", self.tcp_port))
            s.sendall(json.dumps(envelope).encode("utf-8") + b"\n")

            data = s.recv(4096)
            self.assertTrue(len(data) > 0)
            ack = json.loads(data.decode("utf-8").strip())
            self.assertEqual(ack["status"], "ACK")
            self.assertEqual(ack["message_id"], "file:sais_ior:integration_test")
            self.assertEqual(ack["records_parsed"], 1)

    def test_z_http_api_endpoints(self):
        # /health
        req = urllib.request.Request(f"http://127.0.0.1:{self.http_port}/health")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "HEALTHY")

        # /status
        req = urllib.request.Request(f"http://127.0.0.1:{self.http_port}/status")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["overall_status"], "OPERATIONAL")
            self.assertIn("SAIS", data["endpoints"])

        # /metrics
        req = urllib.request.Request(f"http://127.0.0.1:{self.http_port}/metrics")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            metrics = json.loads(resp.read().decode("utf-8"))
            self.assertIn("messages_received", metrics)
            self.assertIn("total_records_produced", metrics)


if __name__ == "__main__":
    unittest.main()

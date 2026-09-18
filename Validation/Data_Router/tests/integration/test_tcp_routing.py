"""Integration test: TCP feed streaming -> Router framing -> Parser delivery -> ACK."""

import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from Validation.Data_Router.app.config.models import (
    FramingType,
    MonitoringConfig,
    ParserDestinationConfig,
    QueueConfig,
    RetryConfig,
    RouterConfig,
    StateConfig,
    TCPSourceConfig,
)
from Validation.Data_Router.app.monitoring.metrics import MetricsCollector
from Validation.Data_Router.app.queue.manager import BoundedQueueManager
from Validation.Data_Router.app.routing.router import RoutingEngine
from Validation.Data_Router.app.sources.tcp_source import TCPSourceManager
from Validation.Data_Router.app.transport.connection_manager import ParserConnectionManager
from .test_file_routing import MockSingleParser


class MockStreamServer:
    """Ephemeral TCP feed broadcaster for testing."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(5)
        self.sock.settimeout(0.5)
        self.running = True
        self.clients = []
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while self.running:
            try:
                client, _ = self.sock.accept()
                client.settimeout(0.5)
                self.clients.append(client)
            except socket.timeout:
                continue
            except OSError:
                break

    def broadcast_line(self, line: str):
        raw = (line.strip() + "\n").encode("utf-8")
        for c in list(self.clients):
            try:
                c.sendall(raw)
            except Exception:
                self.clients.remove(c)

    def close(self):
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass
        for c in self.clients:
            try:
                c.close()
            except Exception:
                pass


class TestTCPRoutingIntegration(unittest.TestCase):
    """End-to-end integration test for TCP stream source."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "router_state.db"

        self.feed_server = MockStreamServer()
        self.parser = MockSingleParser()

        self.config = RouterConfig(
            parser_destinations={
                "VATMS": ParserDestinationConfig(
                    name="VATMS",
                    host="127.0.0.1",
                    port=self.parser.port,
                    framing="ndjson",
                    timeout_seconds=2.0,
                )
            },
            sources={
                "VATMS_EAST": TCPSourceConfig(
                    name="VATMS_EAST",
                    type="tcp",
                    remote_host="127.0.0.1",
                    remote_port=self.feed_server.port,
                    parser="VATMS",
                    enabled=True,
                    framing=FramingType.LINE,
                    delimiter="\n",
                    reconnect_initial_delay=0.5,
                )
            },
            retry=RetryConfig(max_attempts=2),
            queue=QueueConfig(max_size=100, worker_count=1),
            monitoring=MonitoringConfig(enabled=False),
            state=StateConfig(db_path=str(self.db_path)),
        )

        self.metrics = MetricsCollector()
        self.metrics.register_source("VATMS_EAST")
        self.queue_mgr = BoundedQueueManager(self.config.queue)
        self.conn_mgr = ParserConnectionManager(self.config.parser_destinations)
        self.router = RoutingEngine(
            config=self.config,
            queue_manager=self.queue_mgr,
            connection_manager=self.conn_mgr,
            metrics_collector=self.metrics,
        )
        self.tcp_source = TCPSourceManager(
            config=self.config.sources["VATMS_EAST"],
            routing_engine=self.router,
            metrics_collector=self.metrics,
        )

    def tearDown(self):
        self.tcp_source.stop()
        self.router.stop()
        self.feed_server.close()
        self.parser.close()
        self.temp_dir.cleanup()

    def test_tcp_feed_received_and_routed_to_parser(self):
        self.router.start()
        self.tcp_source.start()

        # Wait for TCP source to connect to mock feed
        time.sleep(1.0)
        self.assertTrue(self.tcp_source.is_connected())

        # Send test message from feed
        test_line = "!ABVDM,1,1,2,B,16?Ul2P0006`OpR6cPRK7;980pEe,0*05"
        self.feed_server.broadcast_line(test_line)

        # Wait for delivery to mock parser
        time.sleep(1.0)

        self.assertGreaterEqual(len(self.parser.received_envelopes), 1)
        env = self.parser.received_envelopes[0]
        self.assertEqual(env["source"], "VATMS_EAST")
        self.assertEqual(env["input_type"], "TCP")
        self.assertEqual(env["payload"], test_line)
        self.assertTrue(env["message_id"].startswith("tcp:vatms_east:"))


if __name__ == "__main__":
    unittest.main()

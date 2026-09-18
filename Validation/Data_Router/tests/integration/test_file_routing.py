"""Integration test: File detection -> Stability -> Envelope -> Queue -> Parser delivery -> ACK -> SQLite state."""

import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from Validation.Data_Router.app.config.models import (
    DataInflowConfig,
    FileSourceConfig,
    MonitoringConfig,
    ParserDestinationConfig,
    QueueConfig,
    RetryConfig,
    RouterConfig,
    StateConfig,
)
from Validation.Data_Router.app.monitoring.metrics import MetricsCollector
from Validation.Data_Router.app.queue.manager import BoundedQueueManager
from Validation.Data_Router.app.reliability.state import FileState, FileStateStore
from Validation.Data_Router.app.routing.router import RoutingEngine
from Validation.Data_Router.app.sources.file_source import FileSourceManager
from Validation.Data_Router.app.transport.connection_manager import ParserConnectionManager


class MockSingleParser:
    """Ephemeral TCP mock parser for integration tests."""

    def __init__(self, port: int = 0):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", port))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(5)
        self.sock.settimeout(0.5)
        self.running = True
        self.clients = []
        self.received_envelopes = []
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while self.running:
            try:
                client, _ = self.sock.accept()
                client.settimeout(0.5)
                self.clients.append(client)
                threading.Thread(target=self._client_handler, args=(client,), daemon=True).start()
            except socket.timeout:
                continue
            except OSError:
                break

    def _client_handler(self, client: socket.socket):
        buf = bytearray()
        while self.running:
            try:
                data = client.recv(4096)
                if not data:
                    break
                buf.extend(data)
                while b"\n" in buf:
                    idx = buf.index(b"\n")
                    line = buf[:idx].decode("utf-8")
                    buf = buf[idx + 1:]
                    if line:
                        env = json.loads(line)
                        self.received_envelopes.append(env)
                        # Send ACK
                        ack = json.dumps({"message_id": env["message_id"], "status": "ACK"}) + "\n"
                        client.sendall(ack.encode("utf-8"))
            except socket.timeout:
                continue
            except Exception:
                break
        try:
            client.close()
        except Exception:
            pass

    def close(self):
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass
        for c in list(self.clients):
            try:
                c.close()
            except Exception:
                pass
        self.clients.clear()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)


class TestFileRoutingIntegration(unittest.TestCase):
    """End-to-end integration test for file source ingestion and parser delivery."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.inflow_dir = self.base_path / "INFLOW"
        self.sais_dir = self.inflow_dir / "SAIS_IOR"
        self.sais_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.base_path / "router_state.db"

        # Start mock parser
        self.parser = MockSingleParser()

        # Build router configuration
        self.config = RouterConfig(
            data_inflow=DataInflowConfig(base_dir=str(self.inflow_dir)),
            parser_destinations={
                "SAIS": ParserDestinationConfig(
                    name="SAIS",
                    host="127.0.0.1",
                    port=self.parser.port,
                    framing="ndjson",
                    timeout_seconds=2.0,
                )
            },
            sources={
                "SAIS_IOR": FileSourceConfig(
                    name="SAIS_IOR",
                    type="file",
                    folder="SAIS_IOR",
                    parser="SAIS",
                    enabled=True,
                    poll_interval_seconds=0.2,
                    stability_window_seconds=0.3,
                )
            },
            retry=RetryConfig(max_attempts=2, initial_delay_seconds=0.5),
            queue=QueueConfig(max_size=100, worker_count=1),
            monitoring=MonitoringConfig(enabled=False),
            state=StateConfig(db_path=str(self.db_path)),
        )

        self.state_store = FileStateStore(self.db_path)
        self.metrics = MetricsCollector()
        self.metrics.register_source("SAIS_IOR")
        self.queue_mgr = BoundedQueueManager(self.config.queue)
        self.conn_mgr = ParserConnectionManager(self.config.parser_destinations)
        self.router = RoutingEngine(
            config=self.config,
            queue_manager=self.queue_mgr,
            connection_manager=self.conn_mgr,
            state_store=self.state_store,
            metrics_collector=self.metrics,
        )
        self.file_source = FileSourceManager(
            config=self.config.sources["SAIS_IOR"],
            base_inflow_dir=self.inflow_dir,
            routing_engine=self.router,
            state_store=self.state_store,
            metrics_collector=self.metrics,
        )

    def tearDown(self):
        self.file_source.stop()
        self.router.stop()
        self.parser.close()
        self.temp_dir.cleanup()

    def test_file_detected_routed_and_acknowledged(self):
        # Start subsystems
        self.router.start()
        self.file_source.start()

        # Drop a test file into SAIS_IOR folder
        sample_csv = "mmsi,lat,lon\n419000122,13.107,80.302\n"
        test_file = self.sais_dir / "sample_001.csv"
        test_file.write_text(sample_csv, encoding="utf-8")

        # Wait for file stability window, polling, routing, delivery & ACK
        max_wait = 10.0
        start_t = time.time()
        delivered = False

        while time.time() - start_t < max_wait:
            if len(self.parser.received_envelopes) > 0:
                delivered = True
                break
            time.sleep(0.2)

        self.assertTrue(delivered, "Envelope was not received by mock parser within timeout")

        # Verify envelope contents
        env = self.parser.received_envelopes[0]
        self.assertEqual(env["source"], "SAIS_IOR")
        self.assertEqual(env["input_type"], "FILE")
        self.assertEqual(env["filename"], "sample_001.csv")
        self.assertEqual(env["payload"], sample_csv)

        # Verify SQLite state is marked PROCESSED
        time.sleep(0.5)
        state_record = self.state_store.get_by_message_id(env["message_id"])
        self.assertIsNotNone(state_record)
        self.assertEqual(state_record.status, FileState.PROCESSED)
        self.assertIsNotNone(state_record.acknowledged_at)


if __name__ == "__main__":
    unittest.main()

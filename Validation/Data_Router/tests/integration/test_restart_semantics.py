"""Restart and Recovery Semantics Integration Tests.

Verifies:
1. Acknowledged File Recovery Semantics:
   - File detected -> queued -> sent -> ACK received -> state recorded in SQLite.
   - Entire Router service is terminated.
   - Router restarted with same state database and inflow folder containing the file.
   - Verifies the acknowledged file is NOT delivered again (0 duplicate deliveries).

2. Interrupted Delivery Recovery Semantics:
   - File detected -> queued -> delivery fails (parser offline) -> state recorded as RETRYING.
   - Router terminated mid-cycle.
   - Parser brought online.
   - Router restarted.
   - Verifies Router picks up uncompleted file and delivers it successfully to parser with ACK.
"""

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


class MockParserReceiver:
    """Mock parser receiver recording delivered envelopes."""

    def __init__(self, port: int = 0):
        self.port = port
        self.sock = None
        self.running = False
        self.clients = []
        self.received_envelopes = []
        self._lock = threading.Lock()
        self._thread = None
        self.start()

    def start(self):
        if self.running:
            return
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", self.port))
        if self.port == 0:
            self.port = self.sock.getsockname()[1]
        self.sock.listen(5)
        self.sock.settimeout(0.5)
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while self.running:
            try:
                client, _ = self.sock.accept()
                client.settimeout(0.5)
                with self._lock:
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
                data = client.recv(16384)
                if not data:
                    break
                buf.extend(data)
                while b"\n" in buf:
                    idx = buf.index(b"\n")
                    line_bytes = buf[:idx]
                    buf = buf[idx + 1:]
                    if line_bytes:
                        env = json.loads(line_bytes.decode("utf-8"))
                        with self._lock:
                            self.received_envelopes.append(env)
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

    def stop(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        with self._lock:
            for c in list(self.clients):
                try:
                    c.close()
                except Exception:
                    pass
            self.clients.clear()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)


class TestRestartSemantics(unittest.TestCase):
    """Explicit verification of restart and recovery semantics."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.inflow_dir = self.base_path / "INFLOW"
        self.msis_dir = self.inflow_dir / "MSIS"
        self.msis_dir.mkdir(parents=True)
        self.state_db = self.base_path / "router_state.db"

        self.mock_parser = MockParserReceiver()

        self.config = RouterConfig(
            data_inflow=DataInflowConfig(base_dir=str(self.inflow_dir)),
            parser_destinations={
                "MSIS": ParserDestinationConfig(
                    name="MSIS", host="127.0.0.1", port=self.mock_parser.port, timeout_seconds=0.5
                )
            },
            sources={
                "MSIS": FileSourceConfig(
                    name="MSIS", type="file", folder="MSIS", parser="MSIS",
                    poll_interval_seconds=0.1, stability_window_seconds=0.2
                )
            },
            queue=QueueConfig(max_size=100, worker_count=1),
            retry=RetryConfig(max_attempts=5, initial_delay_seconds=0.2, max_delay_seconds=1.0),
            state=StateConfig(db_path=str(self.state_db)),
            monitoring=MonitoringConfig(enabled=False),
        )

    def tearDown(self):
        self.mock_parser.stop()
        self.temp_dir.cleanup()

    def test_acknowledged_file_not_delivered_again_after_restart(self):
        """Acknowledged file must be preserved in SQLite and skipped after complete service restart."""
        # 1. Start Phase 1: Initialize router and source
        state_store_1 = FileStateStore(self.state_db)
        metrics_1 = MetricsCollector()
        queue_mgr_1 = BoundedQueueManager(self.config.queue)
        conn_mgr_1 = ParserConnectionManager(self.config.parser_destinations)
        router_1 = RoutingEngine(self.config, queue_mgr_1, conn_mgr_1, state_store_1, metrics_1)
        src_1 = FileSourceManager(self.config.sources["MSIS"], self.inflow_dir, router_1, state_store_1, metrics_1)

        router_1.start()
        src_1.start()

        # Drop file
        test_file = self.msis_dir / "msis_restart_test.csv"
        content = "mmsi,latitude,longitude\n219023392,55.21642,11.742363\n"
        test_file.write_text(content, encoding="utf-8")

        # Wait for delivery and ACK
        start_wait = time.time()
        while time.time() - start_wait < 5.0:
            if len(self.mock_parser.received_envelopes) == 1:
                break
            time.sleep(0.1)

        self.assertEqual(len(self.mock_parser.received_envelopes), 1)

        # 2. Terminate service completely (Phase 1 shutdown)
        src_1.stop()
        router_1.stop()
        conn_mgr_1.disconnect_all()

        # Verify state in SQLite is PROCESSED / ACKNOWLEDGED
        stats = state_store_1.get_stats()
        self.assertIn("PROCESSED", stats)

        # Clear mock parser envelope list
        self.mock_parser.received_envelopes.clear()

        # 3. Start Phase 2: Fresh router startup against same database and file
        state_store_2 = FileStateStore(self.state_db)
        metrics_2 = MetricsCollector()
        queue_mgr_2 = BoundedQueueManager(self.config.queue)
        conn_mgr_2 = ParserConnectionManager(self.config.parser_destinations)
        router_2 = RoutingEngine(self.config, queue_mgr_2, conn_mgr_2, state_store_2, metrics_2)
        src_2 = FileSourceManager(self.config.sources["MSIS"], self.inflow_dir, router_2, state_store_2, metrics_2)

        router_2.start()
        src_2.start()

        # Let the poller scan the directory multiple times
        time.sleep(1.0)

        src_2.stop()
        router_2.stop()
        conn_mgr_2.disconnect_all()

        # Verify zero deliveries occurred in Phase 2
        self.assertEqual(
            len(self.mock_parser.received_envelopes), 0,
            "Duplicate delivery occurred! File was re-sent after service restart."
        )

    def test_interrupted_file_resumes_safely_after_restart(self):
        """File interrupted during delivery resumes and succeeds on service restart."""
        # 1. Stop parser so delivery cannot complete in Phase 1
        self.mock_parser.stop()

        state_store_1 = FileStateStore(self.state_db)
        metrics_1 = MetricsCollector()
        queue_mgr_1 = BoundedQueueManager(self.config.queue)
        conn_mgr_1 = ParserConnectionManager(self.config.parser_destinations)
        router_1 = RoutingEngine(self.config, queue_mgr_1, conn_mgr_1, state_store_1, metrics_1)
        src_1 = FileSourceManager(self.config.sources["MSIS"], self.inflow_dir, router_1, state_store_1, metrics_1)

        router_1.start()
        src_1.start()

        test_file = self.msis_dir / "msis_interrupted_test.csv"
        content = "mmsi,latitude,longitude\n431002524,32.719383,128.94176\n"
        test_file.write_text(content, encoding="utf-8")

        # Wait for detection and failed delivery attempt
        start_wait = time.time()
        while time.time() - start_wait < 5.0:
            if metrics_1.snapshot()["sources"].get("MSIS", {}).get("retry_count", 0) >= 1:
                break
            time.sleep(0.1)

        # 2. Terminate service mid-retry
        src_1.stop()
        router_1.stop()
        conn_mgr_1.disconnect_all()

        # Verify state in SQLite shows RETRYING
        stats = state_store_1.get_stats()
        self.assertIn("RETRYING", stats)

        # 3. Bring parser online
        self.mock_parser.start()

        # 4. Restart service (Phase 2)
        state_store_2 = FileStateStore(self.state_db)
        metrics_2 = MetricsCollector()
        queue_mgr_2 = BoundedQueueManager(self.config.queue)
        conn_mgr_2 = ParserConnectionManager(self.config.parser_destinations)
        router_2 = RoutingEngine(self.config, queue_mgr_2, conn_mgr_2, state_store_2, metrics_2)
        src_2 = FileSourceManager(self.config.sources["MSIS"], self.inflow_dir, router_2, state_store_2, metrics_2)

        router_2.start()
        src_2.start()

        # Wait for file to be rescanned and delivered
        start_wait = time.time()
        delivered = False
        while time.time() - start_wait < 5.0:
            if len(self.mock_parser.received_envelopes) == 1:
                delivered = True
                break
            time.sleep(0.1)

        src_2.stop()
        router_2.stop()
        conn_mgr_2.disconnect_all()

        self.assertTrue(delivered, "Interrupted file was not delivered upon service restart")
        env = self.mock_parser.received_envelopes[0]
        self.assertEqual(env["filename"], test_file.name)
        self.assertEqual(env["payload"], content)

        # Verify final state is PROCESSED
        final_stats = state_store_2.get_stats()
        self.assertIn("PROCESSED", final_stats)


if __name__ == "__main__":
    unittest.main()

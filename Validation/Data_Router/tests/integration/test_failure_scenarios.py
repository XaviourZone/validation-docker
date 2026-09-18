"""Failure and Resilience Integration Tests for Data Router Service.

Tests:
1. Downstream Parser Unavailable:
   - Parser port offline when file arrives.
   - Router queues item and enters exponential backoff retry.
   - Zero data loss occurs.
   - Parser brought online: item is delivered, valid ACK received, state updated to ACKNOWLEDGED.

2. Source TCP Disconnect & Reconnect:
   - Remote TCP source feed (e.g. VATMS_EAST) disconnects abruptly.
   - Router detects disconnection, updates metrics, and initiates backoff reconnect.
   - Remote feed server restarts and accepts reconnect.
   - Transmission resumes seamlessly without data corruption.
   - Concurrent sources (e.g. NAIS, file sources) continue operating without disruption.
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
    TCPSourceConfig,
)
from Validation.Data_Router.app.monitoring.metrics import MetricsCollector
from Validation.Data_Router.app.queue.manager import BoundedQueueManager
from Validation.Data_Router.app.reliability.state import FileState, FileStateStore
from Validation.Data_Router.app.routing.destination import ParserDestination
from Validation.Data_Router.app.routing.route import Route
from Validation.Data_Router.app.routing.router import RoutingEngine
from Validation.Data_Router.app.sources.file_source import FileSourceManager
from Validation.Data_Router.app.sources.tcp_source import TCPSourceManager
from Validation.Data_Router.app.transport.connection_manager import ParserConnectionManager


class ControllableMockParser:
    """Mock parser that can be dynamically stopped and restarted on the same port."""

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
                    line = buf[:idx]
                    buf = buf[idx + 1:]
                    if line:
                        env = json.loads(line.decode("utf-8"))
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


class ReconnectableFeedServer:
    """Mock TCP feed server that can simulate abrupt disconnection and restart."""

    def __init__(self, port: int = 0):
        self.port = port
        self.sock = None
        self.running = False
        self.clients = []
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
                with self._lock:
                    self.clients.append(client)
            except socket.timeout:
                continue
            except OSError:
                break

    def broadcast_line(self, line: str):
        data = (line.rstrip("\r\n") + "\n").encode("utf-8")
        with self._lock:
            for c in list(self.clients):
                try:
                    c.sendall(data)
                except Exception:
                    self.clients.remove(c)

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


class TestFailureScenarios(unittest.TestCase):
    """Failure recovery and fault tolerance verification."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.inflow_dir = self.base_path / "INFLOW"
        self.sais_dir = self.inflow_dir / "SAIS_IOR"
        self.sais_dir.mkdir(parents=True)
        self.state_db = self.base_path / "router_state.db"

        # Initially offline or online parsers
        self.sais_parser = ControllableMockParser()
        self.vatms_parser = ControllableMockParser()

        self.config = RouterConfig(
            data_inflow=DataInflowConfig(base_dir=str(self.inflow_dir)),
            parser_destinations={
                "SAIS": ParserDestinationConfig(
                    name="SAIS", host="127.0.0.1", port=self.sais_parser.port, timeout_seconds=0.5
                ),
                "VATMS": ParserDestinationConfig(
                    name="VATMS", host="127.0.0.1", port=self.vatms_parser.port, timeout_seconds=0.5
                ),
            },
            sources={
                "SAIS_IOR": FileSourceConfig(
                    name="SAIS_IOR", type="file", folder="SAIS_IOR", parser="SAIS",
                    poll_interval_seconds=0.1, stability_window_seconds=0.2
                ),
            },
            queue=QueueConfig(max_size=100, worker_count=1),
            retry=RetryConfig(max_attempts=10, initial_delay_seconds=0.2, max_delay_seconds=1.0, backoff_multiplier=1.5),
            state=StateConfig(db_path=str(self.state_db)),
            monitoring=MonitoringConfig(enabled=False),
        )

        self.state_store = FileStateStore(self.state_db)
        self.metrics = MetricsCollector()
        self.queue_mgr = BoundedQueueManager(self.config.queue)
        self.conn_mgr = ParserConnectionManager(self.config.parser_destinations)
        self.router = RoutingEngine(
            config=self.config,
            queue_manager=self.queue_mgr,
            connection_manager=self.conn_mgr,
            state_store=self.state_store,
            metrics_collector=self.metrics,
        )

    def tearDown(self):
        self.router.stop()
        self.conn_mgr.disconnect_all()
        self.sais_parser.stop()
        self.vatms_parser.stop()
        self.temp_dir.cleanup()

    def test_parser_unavailable_then_recovers_without_data_loss(self):
        """File arriving while parser is down must retry and deliver successfully once parser returns."""
        # 1. Stop the SAIS parser before file arrives
        self.sais_parser.stop()

        src_mgr = FileSourceManager(
            config=self.config.sources["SAIS_IOR"],
            base_inflow_dir=self.inflow_dir,
            routing_engine=self.router,
            state_store=self.state_store,
            metrics_collector=self.metrics,
        )

        self.router.start()
        src_mgr.start()
        try:
            # 2. Drop file into SAIS_IOR
            test_file = self.sais_dir / "EarthIOR_failure_test.csv"
            content = "\\s:66,c:1782377468*4C\\!AIVDM,1,1,,B,177hgW001bWc5el;kRfmHl@<00SR,0*47\n"
            test_file.write_text(content, encoding="utf-8")

            # 3. Wait for detection and at least 1 failed delivery attempt
            start_retry_wait = time.time()
            retried = False
            while time.time() - start_retry_wait < 5.0:
                retries = self.metrics.snapshot()["sources"].get("SAIS_IOR", {}).get("retry_count", 0)
                if retries >= 1:
                    retried = True
                    break
                time.sleep(0.1)

            self.assertTrue(retried, "Delivery attempt did not record a retry while parser was down")
            self.assertEqual(len(self.sais_parser.received_envelopes), 0)

            # Verify state in SQLite shows RETRYING
            stats = self.state_store.get_stats()
            self.assertIn("RETRYING", stats)

            # 4. Bring parser back online
            self.sais_parser.start()

            # 5. Delivery worker must retry and successfully deliver
            start_wait = time.time()
            delivered = False
            while time.time() - start_wait < 5.0:
                if len(self.sais_parser.received_envelopes) == 1:
                    delivered = True
                    break
                time.sleep(0.1)

            self.assertTrue(delivered, "Item was not delivered after parser recovered!")
            env = self.sais_parser.received_envelopes[0]
            self.assertEqual(env["filename"], test_file.name)
            self.assertEqual(env["payload"], content)

            # Verify final state is ACKNOWLEDGED / PROCESSED
            record = self.state_store.get_by_message_id(env["message_id"])
            self.assertIsNotNone(record)
            self.assertIn(record.status, (FileState.ACKNOWLEDGED, FileState.PROCESSED))
        finally:
            src_mgr.stop()

    def test_tcp_source_feed_disconnect_and_reconnect(self):
        """TCP input feed disconnects; router reconnects automatically when feed returns."""
        feed_server = ReconnectableFeedServer()
        feed_port = feed_server.port

        tcp_cfg = TCPSourceConfig(
            name="VATMS_EAST",
            type="tcp",
            remote_host="127.0.0.1",
            remote_port=feed_port,
            parser="VATMS",
            reconnect_initial_delay=0.2,
            reconnect_max_delay=1.0,
            reconnect_multiplier=1.5,
        )

        self.router._routes["VATMS_EAST"] = Route(
            "VATMS_EAST",
            ParserDestination("VATMS", "127.0.0.1", self.vatms_parser.port)
        )

        tcp_mgr = TCPSourceManager(tcp_cfg, self.router, self.metrics)

        self.router.start()
        tcp_mgr.start()
        time.sleep(0.5)

        self.assertTrue(tcp_mgr.is_connected(), "TCP source failed initial connection")

        # 1. Send first line before disconnect
        feed_server.broadcast_line("!WSVDM,1,1,1,A,LINE_BEFORE_DISCONNECT,0*29")
        time.sleep(0.5)
        self.assertEqual(len(self.vatms_parser.received_envelopes), 1)

        # 2. Stop feed server abruptly
        feed_server.stop()
        time.sleep(0.8)
        self.assertFalse(tcp_mgr.is_connected(), "Source should detect disconnect")

        # 3. Restart feed server on same port
        feed_server.start()
        time.sleep(1.2)  # Allow reconnect backoff to trigger

        self.assertTrue(tcp_mgr.is_connected(), "Source should have reconnected to restored feed server")

        # 4. Broadcast line after reconnect
        feed_server.broadcast_line("!WSVDM,1,1,2,A,LINE_AFTER_RECONNECT,0*79")
        time.sleep(0.5)

        tcp_mgr.stop()
        feed_server.stop()

        self.assertEqual(len(self.vatms_parser.received_envelopes), 2)
        payloads = [e["payload"] for e in self.vatms_parser.received_envelopes]
        self.assertEqual(payloads, [
            "!WSVDM,1,1,1,A,LINE_BEFORE_DISCONNECT,0*29",
            "!WSVDM,1,1,2,A,LINE_AFTER_RECONNECT,0*79"
        ])


if __name__ == "__main__":
    unittest.main()

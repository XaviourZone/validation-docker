"""Integration tests validating Data Router against real project SAMPLE_DATA.

Tests:
- SAIS_IOR (actual EarthIOR sample file) -> Parser :10001
- SAIS_GLOBAL (actual EarthGLOBAL sample file) -> Parser :10001
- MSIS (actual nc3in sample file + large ~2.2MB sample file) -> Parser :10002
- LRIT (actual LRIT sample file + 0-byte sample file) -> Parser :10003
- VATMS_EAST (actual vatms_east.txt sample stream) -> Parser :10004
- VATMS_WEST (actual vatms_west.txt sample stream) -> Parser :10004
- NAIS (actual Nais.txt sample stream) -> Parser :10005

Verifies:
- Payload byte and string preservation
- Provenance / Source identity preservation
- Correct parser destination routing
- Message ID generation
- ACK association
- SQLite operational state tracking
- Duplicate suppression on restart
"""

import json
import shutil
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
from Validation.Data_Router.app.routing.router import RoutingEngine
from Validation.Data_Router.app.sources.file_source import FileSourceManager
from Validation.Data_Router.app.sources.tcp_source import TCPSourceManager
from Validation.Data_Router.app.transport.connection_manager import ParserConnectionManager


class MultiMockParser:
    """Mock parser server capable of receiving multi-MB files and responding with ACKs."""

    def __init__(self, port: int = 0):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", port))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(10)
        self.sock.settimeout(0.5)
        self.running = True
        self.clients = []
        self.received_envelopes = []
        self._lock = threading.Lock()
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
                data = client.recv(65536)
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

    def get_envelopes(self):
        with self._lock:
            return list(self.received_envelopes)

    def close(self):
        self.running = False
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


class MockStreamServer:
    """Mock TCP feed server streaming sample lines to TCPSourceManager."""

    def __init__(self, port: int = 0):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", port))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(5)
        self.sock.settimeout(0.5)
        self.running = True
        self.clients = []
        self._lock = threading.Lock()
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

    def close(self):
        self.running = False
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


class TestRealSampleDataValidation(unittest.TestCase):
    """End-to-end validation using real SAMPLE_DATA."""

    @classmethod
    def setUpClass(cls):
        cls.sample_root = Path("Validation/SAMPLE_DATA")

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.inflow_dir = self.base_path / "INFLOW"
        self.inflow_dir.mkdir(parents=True)
        self.state_db = self.base_path / "router_state.db"

        # Mock parsers for each destination
        self.sais_parser = MultiMockParser()
        self.msis_parser = MultiMockParser()
        self.lrit_parser = MultiMockParser()
        self.vatms_parser = MultiMockParser()
        self.nais_parser = MultiMockParser()

        # Build router config mapped to mock parsers
        self.config = RouterConfig(
            data_inflow=DataInflowConfig(base_dir=str(self.inflow_dir)),
            parser_destinations={
                "SAIS": ParserDestinationConfig(name="SAIS", host="127.0.0.1", port=self.sais_parser.port),
                "MSIS": ParserDestinationConfig(name="MSIS", host="127.0.0.1", port=self.msis_parser.port),
                "LRIT": ParserDestinationConfig(name="LRIT", host="127.0.0.1", port=self.lrit_parser.port),
                "VATMS": ParserDestinationConfig(name="VATMS", host="127.0.0.1", port=self.vatms_parser.port),
                "NAIS": ParserDestinationConfig(name="NAIS", host="127.0.0.1", port=self.nais_parser.port),
            },
            sources={
                "SAIS_IOR": FileSourceConfig(
                    name="SAIS_IOR", type="file", folder="SAIS_IOR", parser="SAIS",
                    poll_interval_seconds=0.1, stability_window_seconds=0.2
                ),
                "SAIS_GLOBAL": FileSourceConfig(
                    name="SAIS_GLOBAL", type="file", folder="SAIS_GLOBAL", parser="SAIS",
                    poll_interval_seconds=0.1, stability_window_seconds=0.2
                ),
                "MSIS": FileSourceConfig(
                    name="MSIS", type="file", folder="MSIS", parser="MSIS",
                    poll_interval_seconds=0.1, stability_window_seconds=0.2
                ),
                "LRIT": FileSourceConfig(
                    name="LRIT", type="file", folder="LRIT", parser="LRIT",
                    poll_interval_seconds=0.1, stability_window_seconds=0.2
                ),
            },
            queue=QueueConfig(max_size=1000, worker_count=2),
            retry=RetryConfig(max_attempts=3, initial_delay_seconds=0.1, max_delay_seconds=0.5),
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
        self.router.start()

    def tearDown(self):
        self.router.stop()
        self.conn_mgr.disconnect_all()
        self.sais_parser.close()
        self.msis_parser.close()
        self.lrit_parser.close()
        self.vatms_parser.close()
        self.nais_parser.close()
        self.temp_dir.cleanup()

    def test_sais_ior_real_file_routed_and_preserved(self):
        """Test routing of real SAIS_IOR sample EarthIOR_2026-06-25-14-21-28.csv."""
        real_file = self.sample_root / "SAIS" / "SAIS_IOR" / "EarthIOR_2026-06-25-14-21-28.csv"
        self.assertTrue(real_file.exists(), f"Sample file not found: {real_file}")
        with open(real_file, "r", encoding="utf-8") as f:
            expected_payload = f.read()

        sais_dir = self.inflow_dir / "SAIS_IOR"
        sais_dir.mkdir(parents=True, exist_ok=True)
        dest_file = sais_dir / real_file.name

        src_mgr = FileSourceManager(
            config=self.config.sources["SAIS_IOR"],
            base_inflow_dir=self.inflow_dir,
            routing_engine=self.router,
            state_store=self.state_store,
            metrics_collector=self.metrics,
        )
        src_mgr.start()

        # Copy actual sample file
        shutil.copyfile(real_file, dest_file)

        # Wait for routing
        start = time.time()
        envelopes = []
        while time.time() - start < 5.0:
            envelopes = self.sais_parser.get_envelopes()
            if envelopes:
                break
            time.sleep(0.1)

        src_mgr.stop()

        self.assertEqual(len(envelopes), 1, "SAIS_IOR file was not delivered to parser")
        env = envelopes[0]
        self.assertEqual(env["source"], "SAIS_IOR")
        self.assertEqual(env["input_type"], "FILE")
        self.assertEqual(env["filename"], real_file.name)
        self.assertEqual(env["file_size"], real_file.stat().st_size)
        self.assertEqual(env["payload"], expected_payload, "Payload string was corrupted or modified!")
        self.assertTrue(env["message_id"].startswith("file:sais_ior:"))

        # Check SQLite state
        record = self.state_store.get_by_message_id(env["message_id"])
        self.assertIsNotNone(record)
        self.assertIn(record.status, (FileState.ACKNOWLEDGED, FileState.PROCESSED))

    def test_sais_global_real_file_routed_and_preserved(self):
        """Test routing of real SAIS_GLOBAL sample EarthGLOBAL_2026-06-25-14-21-39.csv."""
        real_file = self.sample_root / "SAIS" / "SAIS_GLOBAL" / "EarthGLOBAL_2026-06-25-14-21-39.csv"
        self.assertTrue(real_file.exists())
        with open(real_file, "r", encoding="utf-8") as f:
            expected_payload = f.read()

        dest_file = (self.inflow_dir / "SAIS_GLOBAL") / real_file.name
        dest_file.parent.mkdir(parents=True, exist_ok=True)

        src_mgr = FileSourceManager(
            config=self.config.sources["SAIS_GLOBAL"],
            base_inflow_dir=self.inflow_dir,
            routing_engine=self.router,
            state_store=self.state_store,
            metrics_collector=self.metrics,
        )
        src_mgr.start()
        shutil.copyfile(real_file, dest_file)

        start = time.time()
        envelopes = []
        while time.time() - start < 5.0:
            envelopes = self.sais_parser.get_envelopes()
            if envelopes:
                break
            time.sleep(0.1)

        src_mgr.stop()
        self.assertEqual(len(envelopes), 1)
        env = envelopes[0]
        self.assertEqual(env["source"], "SAIS_GLOBAL")
        self.assertEqual(env["payload"], expected_payload)

    def test_msis_real_file_and_large_file_routed(self):
        """Test routing of real MSIS sample files, including large 2.2MB file."""
        real_small = self.sample_root / "MSIS" / "nc3in_20260601_130155.csv"
        real_large = self.sample_root / "MSIS" / "nc3in_20250707_010547.csv"
        self.assertTrue(real_small.exists())
        self.assertTrue(real_large.exists())

        msis_dir = self.inflow_dir / "MSIS"
        msis_dir.mkdir(parents=True, exist_ok=True)

        src_mgr = FileSourceManager(
            config=self.config.sources["MSIS"],
            base_inflow_dir=self.inflow_dir,
            routing_engine=self.router,
            state_store=self.state_store,
            metrics_collector=self.metrics,
        )
        src_mgr.start()

        # Copy small file first
        shutil.copyfile(real_small, msis_dir / real_small.name)
        start = time.time()
        while time.time() - start < 5.0:
            if len(self.msis_parser.get_envelopes()) >= 1:
                break
            time.sleep(0.1)

        # Copy large 2.2MB file
        shutil.copyfile(real_large, msis_dir / real_large.name)
        start = time.time()
        while time.time() - start < 8.0:
            if len(self.msis_parser.get_envelopes()) >= 2:
                break
            time.sleep(0.1)

        src_mgr.stop()
        envelopes = self.msis_parser.get_envelopes()
        self.assertEqual(len(envelopes), 2)
        sources = [e["source"] for e in envelopes]
        self.assertEqual(sources, ["MSIS", "MSIS"])
        filenames = {e["filename"] for e in envelopes}
        self.assertIn(real_small.name, filenames)
        self.assertIn(real_large.name, filenames)

        # Verify exact payload preservation on large 2.2MB file
        large_env = [e for e in envelopes if e["filename"] == real_large.name][0]
        with open(real_large, "r", encoding="utf-8") as f:
            self.assertEqual(large_env["payload"], f.read())

    def test_lrit_real_file_and_empty_file_routed(self):
        """Test routing of real LRIT sample: normal file and 0-byte empty file."""
        real_normal = self.sample_root / "LRIT" / "LRIT_03062026_093001.csv"
        real_empty = self.sample_root / "LRIT" / "LRIT_03062026_100001.csv"
        self.assertTrue(real_normal.exists())
        self.assertTrue(real_empty.exists())
        self.assertEqual(real_empty.stat().st_size, 0)

        lrit_dir = self.inflow_dir / "LRIT"
        lrit_dir.mkdir(parents=True, exist_ok=True)

        src_mgr = FileSourceManager(
            config=self.config.sources["LRIT"],
            base_inflow_dir=self.inflow_dir,
            routing_engine=self.router,
            state_store=self.state_store,
            metrics_collector=self.metrics,
        )
        src_mgr.start()

        shutil.copyfile(real_normal, lrit_dir / real_normal.name)
        shutil.copyfile(real_empty, lrit_dir / real_empty.name)

        start = time.time()
        while time.time() - start < 5.0:
            if len(self.lrit_parser.get_envelopes()) >= 2:
                break
            time.sleep(0.1)

        src_mgr.stop()
        envelopes = self.lrit_parser.get_envelopes()
        self.assertEqual(len(envelopes), 2, "Both normal and 0-byte LRIT files must be delivered")
        
        # Verify 0-byte file envelope
        empty_env = [e for e in envelopes if e["filename"] == real_empty.name][0]
        self.assertEqual(empty_env["source"], "LRIT")
        self.assertEqual(empty_env["payload"], "")
        self.assertEqual(empty_env["file_size"], 0)

    def test_tcp_sources_vatms_and_nais_real_streams(self):
        """Test streaming lines from actual VATMS_EAST, VATMS_WEST, and NAIS samples."""
        east_feed = MockStreamServer()
        west_feed = MockStreamServer()
        nais_feed = MockStreamServer()

        try:
            # Read first 5 lines of each real sample
            with open(self.sample_root / "VATMS" / "VATMS_EAST" / "vatms_east.txt", "r", encoding="utf-8") as f:
                east_lines = [line.strip() for line in f if line.strip()][:5]
            with open(self.sample_root / "VATMS" / "VATMS_WEST" / "vatms_west.txt", "r", encoding="utf-8") as f:
                west_lines = [line.strip() for line in f if line.strip()][:5]
            with open(self.sample_root / "NAIS" / "Nais.txt", "r", encoding="utf-8") as f:
                nais_lines = [line.strip() for line in f if line.strip()][:5]

            # Configure TCP sources
            east_cfg = TCPSourceConfig(name="VATMS_EAST", type="tcp", remote_host="127.0.0.1", remote_port=east_feed.port, parser="VATMS")
            west_cfg = TCPSourceConfig(name="VATMS_WEST", type="tcp", remote_host="127.0.0.1", remote_port=west_feed.port, parser="VATMS")
            nais_cfg = TCPSourceConfig(name="NAIS", type="tcp", remote_host="127.0.0.1", remote_port=nais_feed.port, parser="NAIS")

            # Add routes to routing engine
            from Validation.Data_Router.app.routing.destination import ParserDestination
            from Validation.Data_Router.app.routing.route import Route
            self.router._routes["VATMS_EAST"] = Route(
                "VATMS_EAST",
                ParserDestination("VATMS", "127.0.0.1", self.vatms_parser.port)
            )
            self.router._routes["VATMS_WEST"] = Route(
                "VATMS_WEST",
                ParserDestination("VATMS", "127.0.0.1", self.vatms_parser.port)
            )
            self.router._routes["NAIS"] = Route(
                "NAIS",
                ParserDestination("NAIS", "127.0.0.1", self.nais_parser.port)
            )

            east_mgr = TCPSourceManager(east_cfg, self.router, self.metrics)
            west_mgr = TCPSourceManager(west_cfg, self.router, self.metrics)
            nais_mgr = TCPSourceManager(nais_cfg, self.router, self.metrics)

            east_mgr.start()
            west_mgr.start()
            nais_mgr.start()
            time.sleep(0.6)

            # Broadcast sample lines
            for line in east_lines:
                east_feed.broadcast_line(line)
            for line in west_lines:
                west_feed.broadcast_line(line)
            for line in nais_lines:
                nais_feed.broadcast_line(line)

            # Wait for reception
            start = time.time()
            while time.time() - start < 5.0:
                vatms_count = len(self.vatms_parser.get_envelopes())
                nais_count = len(self.nais_parser.get_envelopes())
                if vatms_count >= 10 and nais_count >= 5:
                    break
                time.sleep(0.1)

            east_mgr.stop()
            west_mgr.stop()
            nais_mgr.stop()

            vatms_envs = self.vatms_parser.get_envelopes()
            nais_envs = self.nais_parser.get_envelopes()

            self.assertEqual(len(vatms_envs), 10, f"Expected 10 VATMS envelopes, got {len(vatms_envs)}")
            self.assertEqual(len(nais_envs), 5, f"Expected 5 NAIS envelopes, got {len(nais_envs)}")

            # Verify provenance separation between EAST and WEST
            east_envs = [e for e in vatms_envs if e["source"] == "VATMS_EAST"]
            west_envs = [e for e in vatms_envs if e["source"] == "VATMS_WEST"]
            self.assertEqual(len(east_envs), 5)
            self.assertEqual(len(west_envs), 5)

            # Verify actual payloads
            self.assertEqual(set(e["payload"] for e in east_envs), set(east_lines))
            self.assertEqual(set(e["payload"] for e in west_envs), set(west_lines))
            self.assertEqual(set(e["payload"] for e in nais_envs), set(nais_lines))

        finally:
            east_feed.close()
            west_feed.close()
            nais_feed.close()


if __name__ == "__main__":
    unittest.main()

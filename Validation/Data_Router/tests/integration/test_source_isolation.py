"""Integration test: Fault isolation ensuring a failing/dead source does not stop other sources."""

import tempfile
import time
import unittest
from pathlib import Path

from Validation.Data_Router.app.config.models import (
    DataInflowConfig,
    FileSourceConfig,
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
from Validation.Data_Router.app.reliability.state import FileState, FileStateStore
from Validation.Data_Router.app.routing.router import RoutingEngine
from Validation.Data_Router.app.sources.file_source import FileSourceManager
from Validation.Data_Router.app.sources.tcp_source import TCPSourceManager
from Validation.Data_Router.app.transport.connection_manager import ParserConnectionManager
from .test_file_routing import MockSingleParser


class TestSourceIsolationIntegration(unittest.TestCase):
    """Verify that an unresponsive or disconnected network source does not impact other sources."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.inflow_dir = self.base_path / "INFLOW"
        self.sais_dir = self.inflow_dir / "SAIS_IOR"
        self.sais_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.base_path / "router_state.db"

        # Mock parser for SAIS
        self.sais_parser = MockSingleParser()

        # Dead port for broken TCP feed (port where nothing is listening)
        dead_p = MockSingleParser()
        self.dead_port = dead_p.port
        dead_p.close()

        self.config = RouterConfig(
            data_inflow=DataInflowConfig(base_dir=str(self.inflow_dir)),
            parser_destinations={
                "SAIS": ParserDestinationConfig(
                    name="SAIS",
                    host="127.0.0.1",
                    port=self.sais_parser.port,
                    framing="ndjson",
                ),
                "VATMS": ParserDestinationConfig(
                    name="VATMS",
                    host="127.0.0.1",
                    port=19999,
                ),
            },
            sources={
                "SAIS_IOR": FileSourceConfig(
                    name="SAIS_IOR",
                    type="file",
                    folder="SAIS_IOR",
                    parser="SAIS",
                    enabled=True,
                    poll_interval_seconds=0.2,
                    stability_window_seconds=0.2,
                ),
                "VATMS_BROKEN": TCPSourceConfig(
                    name="VATMS_BROKEN",
                    type="tcp",
                    remote_host="127.0.0.1",
                    remote_port=self.dead_port,
                    parser="VATMS",
                    enabled=True,
                    reconnect_initial_delay=0.2,
                ),
            },
            retry=RetryConfig(max_attempts=2),
            queue=QueueConfig(max_size=50, worker_count=2),
            monitoring=MonitoringConfig(enabled=False),
            state=StateConfig(db_path=str(self.db_path)),
        )

        self.state_store = FileStateStore(self.db_path)
        self.metrics = MetricsCollector()
        self.metrics.register_source("SAIS_IOR")
        self.metrics.register_source("VATMS_BROKEN")
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
        self.broken_tcp_source = TCPSourceManager(
            config=self.config.sources["VATMS_BROKEN"],
            routing_engine=self.router,
            metrics_collector=self.metrics,
        )

    def tearDown(self):
        self.broken_tcp_source.stop()
        self.file_source.stop()
        self.router.stop()
        self.sais_parser.close()
        self.temp_dir.cleanup()

    def test_failing_tcp_source_does_not_halt_file_source(self):
        # Start all components, including broken TCP feed
        self.router.start()
        self.broken_tcp_source.start()
        self.file_source.start()

        # Let broken TCP feed fail connection attempts
        time.sleep(0.5)
        self.assertFalse(self.broken_tcp_source.is_connected())

        # Drop a file into SAIS_IOR
        test_file = self.sais_dir / "sais_isolated_test.csv"
        test_file.write_text("mmsi,lat,lon\n111222333,10.0,75.0\n")

        # Wait for file to be routed despite TCP errors
        delivered = False
        start = time.time()
        while time.time() - start < 5.0:
            if len(self.sais_parser.received_envelopes) > 0:
                delivered = True
                break
            time.sleep(0.2)

        self.assertTrue(delivered, "SAIS_IOR processing was blocked by broken TCP source!")
        self.assertEqual(self.sais_parser.received_envelopes[0]["source"], "SAIS_IOR")


if __name__ == "__main__":
    unittest.main()

"""Integration test: Fault recovery, retry on parser downtime, and delayed delivery."""

import tempfile
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
from .test_file_routing import MockSingleParser


class TestFaultRecoveryIntegration(unittest.TestCase):
    """Verify router retries on parser downtime and recovers once parser starts."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.inflow_dir = self.base_path / "INFLOW"
        self.lrit_dir = self.inflow_dir / "LRIT"
        self.lrit_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.base_path / "router_state.db"

        # Temporary parser to get a free port, then close it immediately so it starts in DOWN state
        temp_p = MockSingleParser()
        self.parser_port = temp_p.port
        temp_p.close()
        time.sleep(0.2)

        self.config = RouterConfig(
            data_inflow=DataInflowConfig(base_dir=str(self.inflow_dir)),
            parser_destinations={
                "LRIT": ParserDestinationConfig(
                    name="LRIT",
                    host="127.0.0.1",
                    port=self.parser_port,
                    framing="ndjson",
                    timeout_seconds=1.0,
                )
            },
            sources={
                "LRIT": FileSourceConfig(
                    name="LRIT",
                    type="file",
                    folder="LRIT",
                    parser="LRIT",
                    enabled=True,
                    poll_interval_seconds=0.2,
                    stability_window_seconds=0.2,
                )
            },
            retry=RetryConfig(max_attempts=4, initial_delay_seconds=0.5, backoff_multiplier=1.5),
            queue=QueueConfig(max_size=50, worker_count=1),
            monitoring=MonitoringConfig(enabled=False),
            state=StateConfig(db_path=str(self.db_path)),
        )

        self.state_store = FileStateStore(self.db_path)
        self.metrics = MetricsCollector()
        self.metrics.register_source("LRIT")
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
            config=self.config.sources["LRIT"],
            base_inflow_dir=self.inflow_dir,
            routing_engine=self.router,
            state_store=self.state_store,
            metrics_collector=self.metrics,
        )
        self.mock_parser = None

    def tearDown(self):
        self.file_source.stop()
        self.router.stop()
        if self.mock_parser:
            self.mock_parser.close()
        self.temp_dir.cleanup()

    def test_retry_on_parser_downtime_and_recover_when_parser_starts(self):
        self.router.start()
        self.file_source.start()

        # Drop file while parser is offline
        test_file = self.lrit_dir / "lrit_file.csv"
        test_file.write_text("419000122,13.107,80.302,2026-06-03,lrit,VESSEL\n")

        # Allow stability detection and first delivery attempt to fail
        time.sleep(1.5)

        # Verify retry count in metrics and RETRYING state in SQLite
        incomplete = self.state_store.get_incomplete_records()
        self.assertEqual(len(incomplete), 1)
        self.assertIn(incomplete[0].status, (FileState.RETRYING, FileState.SENDING, FileState.QUEUED))

        # Now bring mock parser UP on the designated port
        self.mock_parser = MockSingleParser(port=self.parser_port)

        # Wait for subsequent retry to succeed
        delivered = False
        start_wait = time.time()
        while time.time() - start_wait < 6.0:
            if len(self.mock_parser.received_envelopes) > 0:
                delivered = True
                break
            time.sleep(0.3)

        self.assertTrue(delivered, "File was not recovered and delivered after parser came online")
        self.assertEqual(self.mock_parser.received_envelopes[0]["source"], "LRIT")


if __name__ == "__main__":
    unittest.main()

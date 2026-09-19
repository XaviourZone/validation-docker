"""Full pipeline acceptance test: inflow -> Router -> Parser -> XML -> Forwarder.

This test intentionally exercises the real service classes rather than mocks for the
transport boundary. It uses temporary directories/databases so the test is safe to
run from a clean repository without operational reference databases.
"""

import socket
import tempfile
import time
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

from Validation.Data_Forwarder.app.config import (
    DestinationConfig,
    ForwarderConfig,
    RetryConfig as ForwarderRetryConfig,
    SpoolConfig,
)
from Validation.Data_Forwarder.app.service import ForwarderService
from Validation.Data_Parser.app.metrics.collector import ParserMetricsCollector
from Validation.Data_Parser.app.parsers.sais import SAISParser
from Validation.Data_Parser.app.pipeline.ais_state import AISStateDB
from Validation.Data_Parser.app.pipeline.processor import PipelineProcessor
from Validation.Data_Parser.app.pipeline.reference_db import ReferenceDB
from Validation.Data_Parser.app.pipeline.track_state import TrackStateDB
from Validation.Data_Parser.app.server.endpoint import ParserEndpointServer
from Validation.Data_Router.app.config.models import (
    DataInflowConfig,
    FileSourceConfig,
    MonitoringConfig,
    ParserDestinationConfig,
    QueueConfig,
    RetryConfig as RouterRetryConfig,
    RouterConfig,
    StateConfig,
)
from Validation.Data_Router.app.monitoring.metrics import MetricsCollector
from Validation.Data_Router.app.queue.manager import BoundedQueueManager
from Validation.Data_Router.app.reliability.state import FileStateStore
from Validation.Data_Router.app.routing.router import RoutingEngine
from Validation.Data_Router.app.sources.file_source import FileSourceManager
from Validation.Data_Router.app.transport.connection_manager import ParserConnectionManager


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class TestFullPipelineAcceptance(unittest.TestCase):
    """Verify one real source file traverses the complete operational pipeline."""

    AIS_SAMPLE = "!AIVDM,1,1,,A,13aEO:001m000000000000000000,0*29"

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="validation_e2e_")
        self.root = Path(self.temp_dir.name)

        self.inflow = self.root / "DATA_INFLOW" / "SAIS_IOR"
        self.inflow.mkdir(parents=True)

        self.pending = self.root / "spool" / "pending"
        self.forwarder_archive = self.root / "spool" / "delivered"
        self.forwarder_failed = self.root / "spool" / "failed"
        self.destination = self.root / "downstream"
        for path in (
            self.pending,
            self.forwarder_archive,
            self.forwarder_failed,
            self.destination,
        ):
            path.mkdir(parents=True, exist_ok=True)

        self.router_state = self.root / "router_state.db"
        self.forwarder_state = self.root / "forwarder_state.db"
        self.track_state = TrackStateDB(self.root / "track_state.db")
        self.ais_state = AISStateDB(self.root / "ais_state.db")

        self.reference_db = ReferenceDB(
            wrs_path=self.root / "missing_wrs.db",
            pans_path=self.root / "missing_pans.db",
            nsc_path=self.root / "missing_nsc.db",
        )
        self.processor = PipelineProcessor(
            reference_db=self.reference_db,
            track_state_db=self.track_state,
            ais_state_db=self.ais_state,
            xml_output_dir=self.pending,
        )

        self.parser_port = _free_port()
        self.parser_metrics = ParserMetricsCollector()
        self.parser_server = ParserEndpointServer(
            name="SAIS",
            host="127.0.0.1",
            port=self.parser_port,
            parser=SAISParser(),
            metrics_collector=self.parser_metrics,
            framing="ndjson",
            processor=self.processor,
        )
        self.parser_server.start()

        router_config = RouterConfig(
            data_inflow=DataInflowConfig(base_dir=str(self.root / "DATA_INFLOW")),
            parser_destinations={
                "SAIS": ParserDestinationConfig(
                    name="SAIS",
                    host="127.0.0.1",
                    port=self.parser_port,
                    framing="ndjson",
                    timeout_seconds=5.0,
                    keep_alive=True,
                )
            },
            sources={
                "SAIS_IOR": FileSourceConfig(
                    name="SAIS_IOR",
                    type="file",
                    folder="SAIS_IOR",
                    parser="SAIS",
                    enabled=True,
                    poll_interval_seconds=0.1,
                    stability_window_seconds=0.2,
                    file_patterns=["*.csv"],
                    preserve_file=True,
                )
            },
            retry=RouterRetryConfig(max_attempts=3, initial_delay_seconds=0.1, max_delay_seconds=0.2),
            queue=QueueConfig(max_size=100, worker_count=1),
            monitoring=MonitoringConfig(enabled=False),
            state=StateConfig(db_path=str(self.router_state)),
        )

        self.router_state_store = FileStateStore(self.router_state)
        self.router_metrics = MetricsCollector()
        self.router_metrics.register_source("SAIS_IOR")
        self.queue_manager = BoundedQueueManager(router_config.queue)
        self.connection_manager = ParserConnectionManager(router_config.parser_destinations)
        self.router = RoutingEngine(
            config=router_config,
            queue_manager=self.queue_manager,
            connection_manager=self.connection_manager,
            state_store=self.router_state_store,
            metrics_collector=self.router_metrics,
        )
        self.file_source = FileSourceManager(
            config=router_config.sources["SAIS_IOR"],
            base_inflow_dir=self.root / "DATA_INFLOW",
            routing_engine=self.router,
            state_store=self.router_state_store,
            metrics_collector=self.router_metrics,
        )

        forwarder_config = ForwarderConfig(
            http_host="127.0.0.1",
            http_port=_free_port(),
            config_path=self.root / "forwarder.yaml",
            spool=SpoolConfig(
                input_dir=self.pending,
                archive_dir=self.forwarder_archive,
                failed_dir=self.forwarder_failed,
                state_db=self.forwarder_state,
                secret_file=self.root / "forwarder_secrets.json",
                poll_interval_seconds=0.1,
                claim_timeout_seconds=30,
            ),
            retry=ForwarderRetryConfig(
                max_attempts=3,
                initial_delay_seconds=0.1,
                max_delay_seconds=0.2,
                multiplier=2.0,
            ),
            destinations={
                "LOCAL_TEST": DestinationConfig(
                    name="LOCAL_TEST",
                    enabled=True,
                    protocol="filesystem",
                    remote_path=str(self.destination),
                    verify_remote_size=True,
                )
            },
            log_level="WARNING",
        )
        self.forwarder = ForwarderService(forwarder_config)

    def tearDown(self):
        self.file_source.stop()
        self.router.stop()
        self.forwarder.stop()
        self.parser_server.stop()
        self.track_state.close()
        self.ais_state.close()
        self.temp_dir.cleanup()

    def test_sais_file_reaches_forwarder_destination(self):
        self.router.start()
        self.file_source.start()
        self.forwarder.start()

        source_file = self.inflow / "acceptance.csv"
        source_file.write_text(self.AIS_SAMPLE + "\n", encoding="utf-8")

        deadline = time.time() + 15.0
        while time.time() < deadline:
            delivered = list(self.destination.glob("*.xml"))
            if delivered:
                break
            time.sleep(0.1)

        delivered = list(self.destination.glob("*.xml"))
        self.assertEqual(len(delivered), 1, "Expected exactly one XML document at downstream destination")

        xml_text = delivered[0].read_text(encoding="utf-8")
        self.assertEqual(xml_text.count("<ns2:XTrack "), 1)
        ET.fromstring(xml_text)

        archived = list(self.forwarder_archive.glob("*.xml"))
        self.assertEqual(len(archived), 1, "Forwarder should archive the delivered XML")
        self.assertFalse(list(self.pending.glob("*.xml")), "Forwarder should drain the pending spool")

        # Confirm the Router recorded an acknowledged/processed source message.
        deadline = time.time() + 5.0
        while time.time() < deadline:
            states = self.router_state_store.all_records()
            if states:
                break
            time.sleep(0.1)
        states = self.router_state_store.all_records()
        self.assertEqual(len(states), 1)
        self.assertEqual(states[0].status.value, "PROCESSED")
        self.assertIsNotNone(states[0].acknowledged_at)

        # Confirm the Forwarder persisted successful delivery state.
        counts = self.forwarder.state.counts()
        self.assertEqual(counts.get("DELIVERED"), 1)


if __name__ == "__main__":
    unittest.main()

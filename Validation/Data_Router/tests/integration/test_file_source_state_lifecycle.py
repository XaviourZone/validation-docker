"""Focused file-source lifecycle tests for Task 62.

Covers:
- stable-file observation before routing
- deterministic content hashing / duplicate suppression
- persistent state as the authoritative duplicate record
- release of the in-memory in-flight guard after queue rejection
"""

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
from Validation.Data_Router.app.reliability.state import FileState, FileStateStore
from Validation.Data_Router.app.sources.file_source import FileSourceManager


class RecordingRouter:
    def __init__(self, accepted=True):
        self.accepted = accepted
        self.envelopes = []

    def route(self, envelope):
        self.envelopes.append(envelope)
        return self.accepted


def make_config(base_dir: Path) -> RouterConfig:
    return RouterConfig(
        data_inflow=DataInflowConfig(base_dir=str(base_dir)),
        parser_destinations={
            "SAIS": ParserDestinationConfig(
                name="SAIS", host="127.0.0.1", port=1
            )
        },
        sources={
            "SAIS_IOR": FileSourceConfig(
                name="SAIS_IOR",
                type="file",
                folder="SAIS_IOR",
                parser="SAIS",
                enabled=True,
                poll_interval_seconds=0.05,
                stability_window_seconds=0.10,
            )
        },
        retry=RetryConfig(max_attempts=2),
        queue=QueueConfig(max_size=10, worker_count=1),
        monitoring=MonitoringConfig(enabled=False),
        state=StateConfig(db_path=str(base_dir / "router_state.db")),
    )


class TestFileSourceStateLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.inflow = self.base / "INFLOW"
        self.folder = self.inflow / "SAIS_IOR"
        self.folder.mkdir(parents=True)
        self.store = FileStateStore(self.base / "router_state.db")
        self.config = make_config(self.inflow)

    def tearDown(self):
        self.temp_dir.cleanup()

    def make_source(self, router):
        return FileSourceManager(
            self.config.sources["SAIS_IOR"],
            self.inflow,
            router,
            self.store,
        )

    def stabilize(self, source, path):
        source._process_candidate_file(path)
        time.sleep(0.13)
        source._process_candidate_file(path)

    def test_stability_gate_precedes_first_route(self):
        router = RecordingRouter()
        source = self.make_source(router)
        path = self.folder / "stable.csv"
        path.write_text("mmsi,lat,lon\n419000122,13.1,80.3\n", encoding="utf-8")

        source._process_candidate_file(path)
        self.assertEqual(len(router.envelopes), 0)

        time.sleep(0.13)
        source._process_candidate_file(path)
        self.assertEqual(len(router.envelopes), 1)
        self.assertEqual(router.envelopes[0].filename, "stable.csv")

    def test_persistent_hash_state_blocks_duplicate_submission(self):
        router = RecordingRouter(accepted=True)
        source = self.make_source(router)
        path = self.folder / "duplicate.csv"
        path.write_text("same content\n", encoding="utf-8")

        self.stabilize(source, path)
        self.assertEqual(len(router.envelopes), 1)

        time.sleep(0.13)
        source._process_candidate_file(path)
        self.assertEqual(len(router.envelopes), 1)

        state = self.store.get_state(
            "SAIS_IOR", "duplicate.csv", router.envelopes[0].file_hash
        )
        self.assertIsNotNone(state)
        # The real RoutingEngine advances READY -> QUEUED. This focused test
        # supplies only the source boundary, so READY proves the persistent
        # record itself blocks the second submission.
        self.assertEqual(state.status, FileState.READY)

    def test_in_memory_guard_is_released_after_queue_rejection(self):
        router = RecordingRouter(accepted=False)
        source = self.make_source(router)
        path = self.folder / "rejected.csv"
        path.write_text("retry me\n", encoding="utf-8")

        self.stabilize(source, path)
        self.assertEqual(len(router.envelopes), 1)

        state = self.store.get_state(
            "SAIS_IOR", "rejected.csv", router.envelopes[0].file_hash
        )
        self.assertIsNotNone(state)
        self.assertEqual(state.status, FileState.DISCOVERED)

        time.sleep(0.13)
        source._process_candidate_file(path)
        self.assertEqual(len(router.envelopes), 2)


if __name__ == "__main__":
    unittest.main()

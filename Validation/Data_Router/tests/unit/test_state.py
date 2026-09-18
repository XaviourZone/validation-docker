"""Unit tests for SQLite state persistence and duplicate detection."""

import tempfile
import unittest
from pathlib import Path

from Validation.Data_Router.app.reliability.state import FileState, FileStateStore


class TestFileStateStore(unittest.TestCase):
    """Test suite for FileStateStore."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_state.db"
        self.store = FileStateStore(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_record_and_retrieve_discovered_file(self):
        state = self.store.record_discovered(
            source="SAIS_IOR",
            filename="sample.csv",
            file_path="/tmp/sample.csv",
            file_size=1024,
            mtime=1700000000.0,
            file_hash="hash123",
            message_id="file:sais_ior:12345",
            status=FileState.DISCOVERED,
        )
        self.assertEqual(state.status, FileState.DISCOVERED)

        retrieved = self.store.get_state("SAIS_IOR", "sample.csv", "hash123")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.message_id, "file:sais_ior:12345")

    def test_update_status_lifecycle(self):
        self.store.record_discovered(
            source="MSIS",
            filename="msis_test.csv",
            file_path="/tmp/msis_test.csv",
            file_size=2048,
            mtime=1700000000.0,
            file_hash="hash_msis",
            message_id="msg_msis_1",
            status=FileState.READY,
        )

        self.assertFalse(self.store.is_already_processed("MSIS", "msis_test.csv", "hash_msis"))

        self.store.update_status("msg_msis_1", FileState.QUEUED, destination="127.0.0.1:10002")
        self.assertEqual(self.store.get_by_message_id("msg_msis_1").status, FileState.QUEUED)

        self.store.update_status("msg_msis_1", FileState.PROCESSED)
        self.assertTrue(self.store.is_already_processed("MSIS", "msis_test.csv", "hash_msis"))

    def test_attempt_increment(self):
        self.store.record_discovered(
            source="LRIT",
            filename="lrit.csv",
            file_path="/tmp/lrit.csv",
            file_size=500,
            mtime=1700000000.0,
            file_hash="lrit_hash",
            message_id="lrit_msg_1",
            status=FileState.READY,
        )

        c1 = self.store.increment_attempt("lrit_msg_1", error="Socket timeout")
        self.assertEqual(c1, 1)

        c2 = self.store.increment_attempt("lrit_msg_1", error="Connection refused")
        self.assertEqual(c2, 2)

        rec = self.store.get_by_message_id("lrit_msg_1")
        self.assertEqual(rec.attempt_count, 2)
        self.assertEqual(rec.last_error, "Connection refused")

    def test_get_incomplete_records(self):
        self.store.record_discovered(
            source="SAIS_GLOBAL",
            filename="incomplete.csv",
            file_path="/tmp/incomplete.csv",
            file_size=100,
            mtime=1700000000.0,
            file_hash="inc_hash",
            message_id="inc_msg_1",
            status=FileState.RETRYING,
        )

        incomplete = self.store.get_incomplete_records()
        self.assertEqual(len(incomplete), 1)
        self.assertEqual(incomplete[0].message_id, "inc_msg_1")


if __name__ == "__main__":
    unittest.main()

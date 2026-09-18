"""Unit tests for hashing utilities and message ID generation."""

import tempfile
import unittest
from pathlib import Path

from Validation.Data_Router.app.utils.hashing import (
    compute_data_hash,
    compute_file_hash,
    generate_file_message_id,
    generate_tcp_message_id,
)


class TestHashing(unittest.TestCase):
    """Test suite for hashing and identity generation."""

    def test_compute_file_hash(self):
        content = b"sample_ais_sentence_payload_12345"
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(content)
            tf_path = Path(tf.name)

        try:
            expected_hash = compute_data_hash(content)
            actual_hash = compute_file_hash(tf_path)
            self.assertEqual(actual_hash, expected_hash)
        finally:
            if tf_path.exists():
                tf_path.unlink()

    def test_generate_file_message_id_is_deterministic(self):
        id1 = generate_file_message_id("SAIS_IOR", "data.csv", 1024, 1700000000.0, "abc123hash")
        id2 = generate_file_message_id("SAIS_IOR", "data.csv", 1024, 1700000000.0, "abc123hash")
        self.assertEqual(id1, id2)
        self.assertTrue(id1.startswith("file:sais_ior:"))

    def test_generate_file_message_id_differs_on_source(self):
        id_ior = generate_file_message_id("SAIS_IOR", "data.csv", 1024, 1700000000.0, "abc123hash")
        id_global = generate_file_message_id("SAIS_GLOBAL", "data.csv", 1024, 1700000000.0, "abc123hash")
        self.assertNotEqual(id_ior, id_global)

    def test_generate_tcp_message_id_is_unique(self):
        id1 = generate_tcp_message_id("VATMS_EAST")
        id2 = generate_tcp_message_id("VATMS_EAST")
        self.assertNotEqual(id1, id2)
        self.assertTrue(id1.startswith("tcp:vatms_east:"))


if __name__ == "__main__":
    unittest.main()

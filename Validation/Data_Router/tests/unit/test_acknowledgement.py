"""Unit tests for ACK validation protocol."""

import unittest

from Validation.Data_Router.app.reliability.acknowledgement import validate_ack_response


class TestAcknowledgement(unittest.TestCase):
    """Test suite for ACK validation."""

    def test_valid_json_ack(self):
        raw = '{"message_id": "msg123", "status": "ACK", "timestamp": "2026-09-17T00:00:00Z"}'
        res = validate_ack_response(raw, expected_message_id="msg123")
        self.assertTrue(res.success)
        self.assertEqual(res.status, "ACK")

    def test_mismatched_message_id(self):
        raw = '{"message_id": "wrong_id", "status": "ACK"}'
        res = validate_ack_response(raw, expected_message_id="msg123")
        self.assertFalse(res.success)
        self.assertEqual(res.status, "MESSAGE_ID_MISMATCH")

    def test_downstream_nack(self):
        raw = '{"message_id": "msg123", "status": "NACK", "error": "Schema violation"}'
        res = validate_ack_response(raw, expected_message_id="msg123")
        self.assertFalse(res.success)
        self.assertEqual(res.status, "NACK")
        self.assertIn("Schema violation", res.error)

    def test_malformed_json(self):
        raw = 'NOT_JSON'
        res = validate_ack_response(raw, expected_message_id="msg123")
        self.assertFalse(res.success)
        self.assertEqual(res.status, "MALFORMED_JSON")


if __name__ == "__main__":
    unittest.main()

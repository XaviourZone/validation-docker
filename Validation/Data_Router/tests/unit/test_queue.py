"""Unit tests for bounded queue and backpressure handling."""

import unittest

from Validation.Data_Router.app.config.models import QueueConfig
from Validation.Data_Router.app.queue.item import QueueItem, RoutingEnvelope
from Validation.Data_Router.app.queue.manager import BoundedQueueManager


class TestBoundedQueueManager(unittest.TestCase):
    """Test suite for BoundedQueueManager."""

    def setUp(self):
        self.config = QueueConfig(max_size=3, worker_count=1, high_watermark_ratio=0.66)
        self.qm = BoundedQueueManager(self.config)

    def _make_item(self, msg_id: str) -> QueueItem:
        env = RoutingEnvelope(
            message_id=msg_id,
            source="TEST_SRC",
            input_type="FILE",
            received_at="2026-09-17T00:00:00Z",
            payload="test_payload",
        )
        return QueueItem(
            envelope=env,
            parser_destination="SAIS",
            destination_host="127.0.0.1",
            destination_port=10001,
        )

    def test_put_and_get(self):
        item = self._make_item("msg1")
        accepted = self.qm.put(item, timeout=1.0)
        self.assertTrue(accepted)
        self.assertEqual(self.qm.depth, 1)

        retrieved = self.qm.get(timeout=1.0)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.message_id, "msg1")
        self.qm.task_done()
        self.assertEqual(self.qm.depth, 0)

    def test_queue_full_blocks_or_times_out(self):
        self.assertTrue(self.qm.put(self._make_item("msg1")))
        self.assertTrue(self.qm.put(self._make_item("msg2")))
        self.assertTrue(self.qm.put(self._make_item("msg3")))
        self.assertTrue(self.qm.is_full)
        self.assertTrue(self.qm.is_congested)

        # 4th item must time out
        accepted = self.qm.put(self._make_item("msg4"), timeout=0.1)
        self.assertFalse(accepted)


if __name__ == "__main__":
    unittest.main()

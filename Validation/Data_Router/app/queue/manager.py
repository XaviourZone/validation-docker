"""Bounded queue manager with backpressure and priority for retries."""

import queue
import threading
import time
from typing import Optional
from .item import QueueItem
from ..config.models import QueueConfig


class QueueFullError(Exception):
    """Raised when queue is full and non-blocking put is rejected."""
    pass


class BoundedQueueManager:
    """Thread-safe bounded queue providing controlled buffering and backpressure."""

    def __init__(self, config: QueueConfig):
        self.config = config
        self.max_size = config.max_size
        self.high_watermark = int(config.max_size * config.high_watermark_ratio)
        
        # Primary queue for items ready for delivery
        self._primary_queue: queue.Queue[QueueItem] = queue.Queue(maxsize=self.max_size)
        
        # Lock and condition for metrics and coordinated shutdown
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    def put(self, item: QueueItem, timeout: Optional[float] = 5.0) -> bool:
        """Insert an item into the queue with optional timeout.
        
        Returns True if item was accepted, False if rejected/timed out.
        """
        if self._stop_event.is_set():
            return False

        try:
            self._primary_queue.put(item, block=True, timeout=timeout)
            return True
        except queue.Full:
            return False

    def get(self, timeout: Optional[float] = 1.0) -> Optional[QueueItem]:
        """Fetch next item ready for delivery worker, with timeout."""
        try:
            return self._primary_queue.get(block=True, timeout=timeout)
        except queue.Empty:
            return None

    def task_done(self) -> None:
        """Mark task as done for queue synchronization."""
        self._primary_queue.task_done()

    def requeue_for_retry(self, item: QueueItem, delay_seconds: float) -> None:
        """Schedule an item for retry after delay."""
        item.next_attempt_at = time.time() + delay_seconds

        def _delayed_reput():
            time.sleep(delay_seconds)
            if not self._stop_event.is_set():
                try:
                    self._primary_queue.put(item, block=True, timeout=10.0)
                except queue.Full:
                    pass

        threading.Thread(target=_delayed_reput, daemon=True).start()

    @property
    def depth(self) -> int:
        """Current number of items waiting in queue."""
        return self._primary_queue.qsize()

    @property
    def is_full(self) -> bool:
        """Check if queue has reached maximum capacity."""
        return self._primary_queue.full()

    @property
    def is_congested(self) -> bool:
        """Check if queue depth has exceeded high watermark threshold."""
        return self.depth >= self.high_watermark

    def stop(self) -> None:
        """Signal queue manager to shut down and unblock workers."""
        self._stop_event.set()

"""Unit tests for retry policies and exponential backoff."""

import unittest

from Validation.Data_Router.app.config.models import RetryConfig
from Validation.Data_Router.app.reliability.retry import RetryPolicy, calculate_backoff_delay


class TestRetry(unittest.TestCase):
    """Test suite for retry backoff logic."""

    def test_backoff_calculation_without_jitter(self):
        d1 = calculate_backoff_delay(attempt=1, initial_delay=2.0, max_delay=60.0, multiplier=2.0, add_jitter=False)
        d2 = calculate_backoff_delay(attempt=2, initial_delay=2.0, max_delay=60.0, multiplier=2.0, add_jitter=False)
        d3 = calculate_backoff_delay(attempt=3, initial_delay=2.0, max_delay=60.0, multiplier=2.0, add_jitter=False)
        d5 = calculate_backoff_delay(attempt=10, initial_delay=2.0, max_delay=60.0, multiplier=2.0, add_jitter=False)

        self.assertEqual(d1, 2.0)
        self.assertEqual(d2, 4.0)
        self.assertEqual(d3, 8.0)
        self.assertEqual(d5, 60.0)  # Clamped to max_delay

    def test_retry_policy_can_retry(self):
        cfg = RetryConfig(max_attempts=3, initial_delay_seconds=1.0, max_delay_seconds=10.0, backoff_multiplier=2.0)
        policy = RetryPolicy(cfg)

        self.assertTrue(policy.can_retry(1))
        self.assertTrue(policy.can_retry(2))
        self.assertFalse(policy.can_retry(3))


if __name__ == "__main__":
    unittest.main()

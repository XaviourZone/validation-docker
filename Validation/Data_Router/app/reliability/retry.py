"""Retry policy and exponential backoff calculations."""

import math
import random
from typing import Optional
from ..config.models import RetryConfig


def calculate_backoff_delay(
    attempt: int,
    initial_delay: float = 2.0,
    max_delay: float = 60.0,
    multiplier: float = 2.0,
    add_jitter: bool = True,
) -> float:
    """Calculate exponential backoff delay for given attempt (1-based index).
    
    Formula: min(max_delay, initial_delay * (multiplier ** (attempt - 1)))
    """
    if attempt <= 1:
        delay = initial_delay
    else:
        delay = initial_delay * math.pow(multiplier, attempt - 1)
        delay = min(delay, max_delay)

    if add_jitter:
        # Add uniform jitter between 0% and 20% of delay
        jitter = delay * random.uniform(0.0, 0.2)
        delay = min(delay + jitter, max_delay)

    return delay


class RetryPolicy:
    """Evaluates retry rules based on RetryConfig."""

    def __init__(self, config: RetryConfig):
        self.config = config

    def can_retry(self, attempt: int) -> bool:
        """Return True if attempt count has not exceeded max_attempts."""
        return attempt < self.config.max_attempts

    def get_delay(self, attempt: int) -> float:
        """Return backoff delay in seconds for current attempt."""
        return calculate_backoff_delay(
            attempt=attempt,
            initial_delay=self.config.initial_delay_seconds,
            max_delay=self.config.max_delay_seconds,
            multiplier=self.config.backoff_multiplier,
        )

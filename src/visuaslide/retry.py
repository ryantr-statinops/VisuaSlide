"""Bounded retries for explicitly classified transient adapter failures."""

from __future__ import annotations

import time
from collections.abc import Callable

from pydantic import Field, model_validator

from visuaslide.config import StrictModel
from visuaslide.exceptions import TransientAdapterError


class RetryPolicy(StrictModel):
    """Exponential retry limits measured in total attempts and seconds."""

    max_attempts: int = Field(default=3, ge=1, le=10)
    initial_backoff_seconds: float = Field(default=0.25, ge=0, le=60)
    max_backoff_seconds: float = Field(default=2.0, ge=0, le=300)

    @model_validator(mode="after")
    def check_backoff_bounds(self) -> RetryPolicy:
        if self.max_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError("max_backoff_seconds cannot be below initial_backoff_seconds")
        return self

    def delay_after(self, failed_attempt: int) -> float:
        """Return the capped delay after a one-based failed attempt."""
        return min(
            self.initial_backoff_seconds * (2 ** (failed_attempt - 1)),
            self.max_backoff_seconds,
        )


def call_with_retries[T](
    operation: Callable[[], T],
    *,
    policy: RetryPolicy | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Retry only explicitly transient failures, with a bounded attempt count."""
    selected_policy = policy or RetryPolicy()
    for attempt in range(1, selected_policy.max_attempts + 1):
        try:
            return operation()
        except (TransientAdapterError, TimeoutError, ConnectionError):
            if attempt >= selected_policy.max_attempts:
                raise
            sleep(selected_policy.delay_after(attempt))
    raise RuntimeError("retry loop exited without a result")

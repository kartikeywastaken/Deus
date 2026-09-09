"""Circuit breaker and retry policies for Email OSINT sources."""

from __future__ import annotations

import time
from typing import Callable


class CircuitBreakerOpenException(Exception):
    """Raised when a request is blocked because the source circuit is open."""


class CircuitBreaker:
    """Per-source state tracking to prevent cascade failure when a service is down."""

    def __init__(self, name: str, max_failures: int = 3, reset_timeout_seconds: float = 60.0) -> None:
        self.name = name
        self.max_failures = max_failures
        self.reset_timeout_seconds = reset_timeout_seconds
        self.failure_count = 0
        self.last_failure_time: float | None = None
        self.is_open = False

    def check_allowed(self) -> bool:
        if not self.is_open:
            return True
        if self.last_failure_time and (time.monotonic() - self.last_failure_time) > self.reset_timeout_seconds:
            # Half-open: attempt recovery
            self.is_open = False
            self.failure_count = 0
            return True
        return False

    def record_success(self) -> None:
        self.failure_count = 0
        self.is_open = False

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.failure_count >= self.max_failures:
            self.is_open = True

"""
MAVERICK rate limiter (Phase 1).

Prevents API spam by allowing at most `max_calls` requests per `window_seconds`.
Uses a sliding window of timestamps (monotonic clock).

Typical use before each Groq/Claude call:
    if not limiter.allow():
        return offline_or_message()
    # proceed with API
"""

from __future__ import annotations

from collections import deque
import time
from typing import Deque, Optional

from logger import MaverickLogger, create_logger


class RateLimiter:
    """
    Sliding-window rate limiter for outbound API calls.

    Thread-safe enough for single-threaded CLI; for multi-threaded use,
    protect `allow()` with a lock in the caller if needed.
    """

    def __init__(
        self,
        max_calls: int = 30,
        window_seconds: float = 60.0,
        logger: Optional[MaverickLogger] = None,
    ) -> None:
        if max_calls < 1:
            raise ValueError("max_calls must be >= 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")

        self.max_calls = max_calls
        self.window_seconds = float(window_seconds)
        self._times: Deque[float] = deque()
        self.logger = logger or create_logger()

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._times and self._times[0] < cutoff:
            self._times.popleft()

    def allow(self) -> bool:
        """
        Return True if this request is allowed; record the request timestamp.
        Return False if the limit would be exceeded (does not record).
        """
        now = time.monotonic()
        self._prune(now)
        if len(self._times) >= self.max_calls:
            self.logger.security(
                f"Rate limit hit: {self.max_calls} calls per {self.window_seconds:.0f}s window."
            )
            return False
        self._times.append(now)
        return True

    def remaining(self) -> int:
        """How many more calls are allowed in the current window (estimate)."""
        now = time.monotonic()
        self._prune(now)
        return max(0, self.max_calls - len(self._times))

    def reset(self) -> None:
        """Clear history (e.g. for tests)."""
        self._times.clear()


def create_rate_limiter(
    max_calls: int = 30,
    window_seconds: float = 60.0,
    logger: Optional[MaverickLogger] = None,
) -> RateLimiter:
    return RateLimiter(max_calls=max_calls, window_seconds=window_seconds, logger=logger)

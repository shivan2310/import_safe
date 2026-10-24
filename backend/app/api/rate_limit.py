"""Simple in-memory per-IP rate limiter for investigation creation (docs/prd-backend.md B11).

Uses a sliding-window counter. No external dependency. Thread-safe for a single-process
deployment; use Redis for multi-process (not needed for the demo).

``check_rate_limit(key)`` raises ``RateLimitError`` when the caller exceeds the limit,
and is a no-op otherwise. The key is typically the client IP address.
"""
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from app.errors import ImportSafeError

# Configurable defaults — override in tests by passing them explicitly.
DEFAULT_MAX_REQUESTS = 10       # requests per window
DEFAULT_WINDOW_S = 3600.0       # 1 hour


class RateLimitError(ImportSafeError):
    status_code = 429
    code = "rate_limit_exceeded"

    def __init__(self) -> None:
        super().__init__("Too many investigations. Please wait before trying again.")


class RateLimiter:
    """Sliding-window rate limiter. Call ``check(key)`` to enforce the limit."""

    def __init__(self, max_requests: int = DEFAULT_MAX_REQUESTS,
                 window_s: float = DEFAULT_WINDOW_S) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be >= 1")
        if window_s <= 0:
            raise ValueError("window_s must be > 0")
        self._max = max_requests
        self._window = window_s
        self._windows: Dict[str, Deque[float]] = defaultdict(deque)

    def check(self, key: str, now: float = 0.0) -> None:
        """Raise ``RateLimitError`` when ``key`` has exceeded the limit in the current window."""
        t = now or time.monotonic()
        cutoff = t - self._window
        dq = self._windows[key]
        # Remove timestamps outside the window.
        while dq and dq[0] <= cutoff:
            dq.popleft()
        if len(dq) >= self._max:
            raise RateLimitError()
        dq.append(t)

    def reset(self, key: str) -> None:
        """Clear the window for a key (used in tests)."""
        self._windows.pop(key, None)

    def count(self, key: str) -> int:
        """Current request count for a key (for testing and monitoring)."""
        return len(self._windows.get(key, []))


# Application-wide singleton — replaced in tests via dependency override.
_limiter = RateLimiter()


def get_limiter() -> RateLimiter:
    return _limiter

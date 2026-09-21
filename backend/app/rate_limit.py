"""Single-process in-memory rate limiter with bounded keys and failure counts."""

from collections import deque
from threading import Lock
import time

from app.config import settings


class MemoryRateLimiter:
    """Bounded in-memory rate limiter.

    Tracks two time-series per key:
    * successful requests (``is_allowed``)
    * failed attempts such as invalid credentials (``record_failure``)

    Both series share a global key cap; old keys are evicted by earliest
    activity. Timestamps use ``time.monotonic`` to avoid wall-clock jumps.
    """

    def __init__(
        self,
        window_seconds: int,
        max_requests: int,
        max_failures: int,
        max_keys: int,
    ):
        self.window_seconds = window_seconds
        self.max_requests = max_requests
        self.max_failures = max_failures
        self.max_keys = max_keys
        self._requests: dict[str, deque[float]] = {}
        self._failures: dict[str, deque[float]] = {}
        self._lock = Lock()
        self._monotonic = time.monotonic

    def is_allowed(self, key: str) -> tuple[bool, int | None]:
        now = self._monotonic()
        with self._lock:
            self._cleanup(now)
            if len(self._requests) >= self.max_keys and key not in self._requests:
                return False, self.window_seconds
            bucket = self._requests.setdefault(key, deque())
            while bucket and bucket[0] < now - self.window_seconds:
                bucket.popleft()
            if len(bucket) >= self.max_requests:
                retry_after = int(bucket[0] + self.window_seconds - now) + 1
                return False, retry_after
            bucket.append(now)
            return True, None

    def record_failure(self, key: str) -> tuple[bool, int | None]:
        now = self._monotonic()
        with self._lock:
            self._cleanup(now)
            if len(self._failures) >= self.max_keys and key not in self._failures:
                return False, self.window_seconds
            bucket = self._failures.setdefault(key, deque())
            while bucket and bucket[0] < now - self.window_seconds:
                bucket.popleft()
            if len(bucket) >= self.max_failures:
                retry_after = int(bucket[0] + self.window_seconds - now) + 1
                return False, retry_after
            bucket.append(now)
            return True, None

    def reset(self) -> None:
        with self._lock:
            self._requests.clear()
            self._failures.clear()

    def _cleanup(self, now: float) -> None:
        cutoff = now - self.window_seconds
        for series in (self._requests, self._failures):
            for key in list(series.keys()):
                bucket = series[key]
                while bucket and bucket[0] < cutoff:
                    bucket.popleft()
                if not bucket:
                    del series[key]
            # Evict oldest keys if still over capacity so new keys cannot
            # simply flush out existing state.
            while len(series) > self.max_keys:
                oldest = min(series, key=lambda k: series[k][0])
                del series[oldest]


limiter = MemoryRateLimiter(
    window_seconds=settings.rate_limit_window_seconds,
    max_requests=settings.rate_limit_max_requests,
    max_failures=settings.rate_limit_max_failures,
    max_keys=settings.rate_limit_max_keys,
)

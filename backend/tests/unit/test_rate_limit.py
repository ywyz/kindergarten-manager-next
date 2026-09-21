import time
import unittest

from app.rate_limit import MemoryRateLimiter


class RateLimiterTests(unittest.TestCase):
    def test_allows_under_limit(self):
        limiter = MemoryRateLimiter(
            window_seconds=60, max_requests=3, max_failures=3, max_keys=10
        )
        self.assertTrue(limiter.is_allowed("ip1")[0])
        self.assertTrue(limiter.is_allowed("ip1")[0])
        self.assertTrue(limiter.is_allowed("ip1")[0])

    def test_blocks_at_limit(self):
        limiter = MemoryRateLimiter(
            window_seconds=60, max_requests=2, max_failures=3, max_keys=10
        )
        self.assertTrue(limiter.is_allowed("ip1")[0])
        self.assertTrue(limiter.is_allowed("ip1")[0])
        allowed, retry = limiter.is_allowed("ip1")
        self.assertFalse(allowed)
        self.assertIsInstance(retry, int)
        self.assertGreater(retry, 0)

    def test_keys_are_independent(self):
        limiter = MemoryRateLimiter(
            window_seconds=60, max_requests=1, max_failures=3, max_keys=10
        )
        self.assertTrue(limiter.is_allowed("ip1")[0])
        self.assertTrue(limiter.is_allowed("ip2")[0])

    def test_window_slides(self):
        limiter = MemoryRateLimiter(
            window_seconds=1, max_requests=1, max_failures=3, max_keys=10
        )
        self.assertTrue(limiter.is_allowed("ip1")[0])
        self.assertFalse(limiter.is_allowed("ip1")[0])
        time.sleep(1.1)
        self.assertTrue(limiter.is_allowed("ip1")[0])

    def test_failure_counter_separate_from_success(self):
        limiter = MemoryRateLimiter(
            window_seconds=60, max_requests=10, max_failures=2, max_keys=10
        )
        self.assertTrue(limiter.record_failure("ip1")[0])
        self.assertTrue(limiter.record_failure("ip1")[0])
        allowed, _ = limiter.record_failure("ip1")
        self.assertFalse(allowed)
        # Success counter is unaffected by failures.
        self.assertTrue(limiter.is_allowed("ip1")[0])

    def test_global_key_capacity_blocks_new_keys_when_full(self):
        limiter = MemoryRateLimiter(
            window_seconds=60, max_requests=1, max_failures=3, max_keys=2
        )
        self.assertTrue(limiter.is_allowed("a")[0])
        time.sleep(0.01)
        self.assertTrue(limiter.is_allowed("b")[0])
        # A third distinct key must be blocked while the bucket is at capacity.
        allowed, _ = limiter.is_allowed("c")
        self.assertFalse(allowed)
        self.assertTrue("a" in limiter._requests)
        self.assertTrue("b" in limiter._requests)

    def test_cleanup_removes_expired_keys(self):
        limiter = MemoryRateLimiter(
            window_seconds=1, max_requests=10, max_failures=10, max_keys=10
        )
        self.assertTrue(limiter.is_allowed("ip1")[0])
        time.sleep(1.1)
        # Any new call triggers cleanup.
        self.assertTrue(limiter.is_allowed("ip2")[0])
        self.assertFalse("ip1" in limiter._requests)

    def test_uses_monotonic_time(self):
        # Ensure time.monotonic is used so wall-clock changes do not reset limits.
        class FrozenTime:
            def __init__(self):
                self._value = 1000.0

            def __call__(self):
                return self._value

        frozen = FrozenTime()
        limiter = MemoryRateLimiter(
            window_seconds=60, max_requests=1, max_failures=3, max_keys=10
        )
        limiter.is_allowed("ip1")
        # Patch the time source after one request.
        limiter._monotonic = frozen  # type: ignore[method-assign]
        allowed, _ = limiter.is_allowed("ip1")
        self.assertFalse(allowed)


if __name__ == "__main__":
    unittest.main()

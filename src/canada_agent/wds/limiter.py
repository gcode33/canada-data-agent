"""A token-bucket rate limiter with a bucket of one token.

WDS allows 25 requests/second per IP; we stay at or under 10. A bucket that holds a single
token means grants are always at least 1/rate seconds apart, so any one-second window holds
at most `rate` requests. A bigger bucket would allow bursts that break that guarantee.
The clock and sleep are injectable so tests run on a fake clock: exact and instant.
"""

import time
from collections.abc import Callable


class TokenBucket:
    def __init__(
        self,
        rate: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if rate <= 0:
            raise ValueError("rate must be positive")
        self.interval = 1.0 / rate
        self._clock = clock
        self._sleep = sleep
        self._tokens = 1.0
        self._last = clock()

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(1.0, self._tokens + (now - self._last) / self.interval)
        self._last = now

    def acquire(self) -> None:
        """Block until a request may be sent, then spend the token."""
        self._refill()
        if self._tokens < 1.0:
            self._sleep((1.0 - self._tokens) * self.interval)
            self._refill()
        self._tokens = max(0.0, self._tokens - 1.0)

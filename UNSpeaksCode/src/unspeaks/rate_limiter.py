"""A rate limiter that keeps UNSpeaks within the UN Library's guidance.

The Library asked us to make at most 100 requests per 5 minutes and to respect
HTTP 429 ("Too Many Requests"). Before every HTTP request, `acquire()` waits
until all three of these are true:

1. fewer than `max_requests` requests were sent in the last `window_seconds`;
2. at least `min_interval` seconds have passed since the previous request;
3. any pause the server asked for (via `block_for`, e.g. from Retry-After) is over.

It is thread-safe: requests from tool calls running in parallel are sent one
at a time.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable


class RateLimiter:
    def __init__(
        self,
        max_requests: int,
        window_seconds: float,
        min_interval: float = 0.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_requests < 1 or window_seconds <= 0 or min_interval < 0:
            raise ValueError("invalid rate limit settings")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._sent: deque[float] = deque()
        self._blocked_until = 0.0

    def acquire(self) -> float:
        """Wait until a request may be sent, then record it. Returns seconds waited."""
        waited = 0.0
        with self._lock:
            while True:
                now = self._clock()
                delay = self._delay(now)
                if delay <= 0:
                    self._sent.append(now)
                    return waited
                self._sleep(delay)
                waited += delay

    def block_for(self, seconds: float) -> None:
        """Send no requests for `seconds` (e.g. because the server returned 429)."""
        with self._lock:
            self._blocked_until = max(self._blocked_until, self._clock() + max(0.0, seconds))

    def _delay(self, now: float) -> float:
        while self._sent and now - self._sent[0] >= self.window_seconds:
            self._sent.popleft()
        delays = [self._blocked_until - now]
        if self._sent:
            delays.append(self._sent[-1] + self.min_interval - now)
        if len(self._sent) >= self.max_requests:
            delays.append(self._sent[0] + self.window_seconds - now)
        return max(delays)

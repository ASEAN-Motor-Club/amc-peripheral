"""In-process rate limiting for the workshop's write endpoints.

One process, human-scale writes: a dict of timestamps is enough. The point is
not to be a security control — CSRF and session checks are — but to stop a
double-submit or a stuck retry loop from turning one click into twenty rows.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable


class RateLimiter:
    """At most ``limit`` calls per ``window`` seconds for a given key."""

    def __init__(
        self,
        *,
        limit: int = 1,
        window: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 10_000,
    ):
        self.limit = max(1, int(limit))
        self.window = float(window)
        self.clock = clock
        self.max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        now = self.clock()
        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= self.max_keys:
                self._prune(now)
            hits = self._hits[key] = deque()
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True

    def _prune(self, now: float) -> None:
        stale = [
            key
            for key, hits in self._hits.items()
            if not hits or now - hits[-1] > self.window
        ]
        for key in stale:
            del self._hits[key]

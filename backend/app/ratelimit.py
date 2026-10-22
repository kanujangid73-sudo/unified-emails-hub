"""In-memory sliding-window rate limiter (per process; resets on restart)."""

import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float = 3600) -> None:
        self.limit = limit
        self.window = window_seconds
        self.hits: dict[object, deque[float]] = defaultdict(deque)

    @property
    def enabled(self) -> bool:
        return self.limit > 0

    def _prune(self, key: object, now: float) -> deque[float]:
        hits = self.hits[key]
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        return hits

    def status(self, key: object) -> dict:
        """Remaining requests and seconds until the oldest one expires."""
        if not self.enabled:
            return {"enabled": False, "limit": 0, "remaining": None, "reset_seconds": 0}
        now = time.monotonic()
        hits = self._prune(key, now)
        reset = int(self.window - (now - hits[0])) + 1 if hits else 0
        return {"enabled": True, "limit": self.limit, "remaining": max(0, self.limit - len(hits)), "reset_seconds": reset}

    def hit(self, key: object) -> bool:
        """Record a request if allowed. Returns False when the limit is reached."""
        if not self.enabled:
            return True
        now = time.monotonic()
        hits = self._prune(key, now)
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True

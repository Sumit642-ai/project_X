"""Sliding-window rate limit for sign-in, per client address.

Uses a monotonic timer (a rate limit measures elapsed time, not business time), so the frozen
demo Clock does not disable it. State lives on the app, one window per process.
"""

import time
from collections import deque
from collections.abc import Callable

from fastapi import HTTPException, Request, status


class SlidingWindowLimiter:
    def __init__(
        self, limit: int, window_seconds: float, now: Callable[[], float] = time.monotonic
    ) -> None:
        self.limit, self.window, self.now = limit, window_seconds, now
        self.hits: dict[str, deque[float]] = {}

    def check(self, key: str) -> None:
        """Record an attempt; raise 429 if this key has used up its window."""
        now = self.now()
        hits = self.hits.setdefault(key, deque())
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            retry = max(1, int(self.window - (now - hits[0])) + 1)
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "too many sign-in attempts; try again shortly",
                headers={"Retry-After": str(retry)},
            )
        hits.append(now)


def client_key(request: Request, trust_proxy_headers: bool = False) -> str:
    """The caller's address. Behind a trusted proxy every request arrives from the proxy, so
    the first X-Forwarded-For entry (set by the proxy) identifies the client instead."""
    if trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return request.client.host if request.client else "unknown"

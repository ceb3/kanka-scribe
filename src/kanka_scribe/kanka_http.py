"""Shared Kanka API HTTP helpers: client-side rate limit + 429 retry."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from email.utils import parsedate_to_datetime
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)

# Stay under CE default API_THROTTLE_LIMIT=30/min.
_DEFAULT_MAX_PER_MINUTE = 24


def _env_max_per_minute() -> int:
    raw = os.environ.get("KANKA_MAX_REQUESTS_PER_MINUTE", "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    return _DEFAULT_MAX_PER_MINUTE


class SlidingWindowRateLimiter:
    """Allow at most `max_per_minute` calls in any rolling 60s window."""

    def __init__(self, max_per_minute: int | None = None) -> None:
        self.max_per_minute = (
            max_per_minute if max_per_minute is not None else _env_max_per_minute()
        )
        self._times: deque[float] = deque()
        self._lock = threading.Lock()

    def wait(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                while self._times and now - self._times[0] >= 60.0:
                    self._times.popleft()
                if len(self._times) < self.max_per_minute:
                    self._times.append(now)
                    return
                sleep_for = 60.0 - (now - self._times[0]) + 0.05
            time.sleep(max(sleep_for, 0.05))

    def penalize(self, seconds: float) -> None:
        """After a 429, pause the whole process for `seconds` before next call."""
        seconds = max(0.0, float(seconds))
        if seconds <= 0:
            return
        logger.warning("Kanka rate limit: sleeping %.1fs after 429", seconds)
        time.sleep(seconds)
        with self._lock:
            # Drop history so we don't immediately re-burst after the wait.
            self._times.clear()


_GLOBAL_LIMITER = SlidingWindowRateLimiter()


def get_rate_limiter() -> SlidingWindowRateLimiter:
    return _GLOBAL_LIMITER


def reset_rate_limiter(max_per_minute: int | None = None) -> SlidingWindowRateLimiter:
    """Test helper: replace the process-wide limiter."""
    global _GLOBAL_LIMITER
    _GLOBAL_LIMITER = SlidingWindowRateLimiter(max_per_minute=max_per_minute)
    return _GLOBAL_LIMITER


def _retry_after_seconds(response: httpx.Response) -> float:
    raw = response.headers.get("Retry-After") or ""
    if raw.isdigit():
        return float(raw)
    if raw:
        try:
            dt = parsedate_to_datetime(raw)
            return max(0.0, dt.timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            pass
    # Prefer remaining=0 style windows when header present.
    remaining = response.headers.get("x-ratelimit-remaining")
    if remaining == "0":
        return 60.0
    return 0.0


def kanka_request(
    method: Callable[..., httpx.Response],
    url: str,
    *,
    retries: int = 8,
    limiter: SlidingWindowRateLimiter | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """Issue a Kanka API call with pacing and 429/backoff retries."""
    lim = limiter or _GLOBAL_LIMITER
    last_exc: Exception | None = None
    for attempt in range(retries):
        lim.wait()
        try:
            response = method(url, **kwargs)
        except httpx.HTTPError as exc:
            last_exc = exc
            time.sleep(min(2.0 * (attempt + 1), 15.0))
            continue

        if response.status_code != 429:
            return response

        if attempt + 1 >= retries:
            return response

        hinted = _retry_after_seconds(response)
        # Exponential floor so we don't tight-loop if headers are missing.
        delay = max(hinted, min(2.0 ** attempt, 45.0), 2.0)
        lim.penalize(delay)

    if last_exc:
        raise last_exc
    raise RuntimeError("kanka_request failed without response")

import time
from unittest.mock import MagicMock

import httpx

from kanka_scribe.kanka_http import (
    SlidingWindowRateLimiter,
    kanka_request,
    reset_rate_limiter,
)


def test_sliding_window_caps_burst():
    lim = SlidingWindowRateLimiter(max_per_minute=3)
    t0 = time.monotonic()
    for _ in range(3):
        lim.wait()
    # Fourth call must wait ~60s; stub by checking queue length instead of sleeping
    # Use a tiny window via monkeypatching: force times to look full.
    with lim._lock:
        assert len(lim._times) == 3
    # Simulate aged entries so wait returns immediately
    with lim._lock:
        lim._times.clear()
        lim._times.append(time.monotonic() - 61)
    lim.wait()
    elapsed = time.monotonic() - t0
    assert elapsed < 2.0


def test_kanka_request_retries_429_then_succeeds():
    reset_rate_limiter(max_per_minute=100)
    calls = {"n": 0}

    def fake_get(url, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "0"}, request=httpx.Request("GET", url))
        return httpx.Response(200, json={"ok": True}, request=httpx.Request("GET", url))

    # Avoid real multi-second sleeps from penalize
    lim = SlidingWindowRateLimiter(max_per_minute=100)
    lim.penalize = MagicMock()  # type: ignore[method-assign]

    resp = kanka_request(fake_get, "https://example.test/x", retries=5, limiter=lim)
    assert resp.status_code == 200
    assert calls["n"] == 3
    assert lim.penalize.call_count == 2


def test_kanka_request_respects_retry_after_header():
    reset_rate_limiter(max_per_minute=100)
    lim = SlidingWindowRateLimiter(max_per_minute=100)
    sleeps: list[float] = []
    lim.penalize = lambda s: sleeps.append(s)  # type: ignore[method-assign]

    def fake_get(url, **kwargs):
        return httpx.Response(
            429, headers={"Retry-After": "7"}, request=httpx.Request("GET", url)
        )

    resp = kanka_request(fake_get, "https://example.test/x", retries=2, limiter=lim)
    assert resp.status_code == 429
    assert sleeps and sleeps[0] >= 7.0

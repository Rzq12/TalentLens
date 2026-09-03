from __future__ import annotations

import time

from app.services.rate_limiter import RateLimitScheduler, TokenBucket


def test_reserve_does_not_consume_tpm_when_request_limit_is_full() -> None:
    scheduler = RateLimitScheduler()
    scheduler.register_key("provider", "model", "key", tpm=10, rpm=1, rpd=10)

    assert scheduler.reserve("provider", "model", "key", estimated_tokens=1)
    assert not scheduler.reserve("provider", "model", "key", estimated_tokens=5)

    tpm_bucket, _, _ = scheduler._buckets[scheduler._key("provider", "model", "key")]
    assert sum(cost for _, cost in tpm_bucket._events) == 1


def test_huge_token_budget_stores_one_event_not_one_entry_per_token() -> None:
    """Regression: the old implementation appended one timestamp per token,
    so a 1M-token reservation created a million list entries."""
    bucket = TokenBucket(capacity=1_000_000, window_seconds=60.0)

    assert bucket.has_capacity(1_000_000)
    bucket.consume(1_000_000)

    assert len(bucket._events) == 1
    assert not bucket.has_capacity(1)
    assert bucket.estimated_wait(1) > 0.0


def test_window_expiry_frees_capacity() -> None:
    bucket = TokenBucket(capacity=100, window_seconds=60.0)
    now = time.monotonic()
    bucket._events.append((now, 100))

    assert not bucket.has_capacity(1)
    assert bucket.estimated_wait(1) > 0.0
    # After the window the single entry has aged out entirely.
    assert bucket._used(now + 61.0) == 0

from __future__ import annotations

from app.services.rate_limiter import RateLimitScheduler


def test_reserve_does_not_consume_tpm_when_request_limit_is_full() -> None:
    scheduler = RateLimitScheduler()
    scheduler.register_key("provider", "model", "key", tpm=10, rpm=1, rpd=10)

    assert scheduler.reserve("provider", "model", "key", estimated_tokens=1)
    assert not scheduler.reserve("provider", "model", "key", estimated_tokens=5)

    tpm_bucket, _, _ = scheduler._buckets[scheduler._key("provider", "model", "key")]
    assert len(tpm_bucket._timestamps) == 1

"""Token-bucket rate-limit scheduler with key pooling.

Manages per-(provider, model, api_key) buckets for TPM, RPM, and RPD.
Calls reserve(estimated_tokens) before LLM dispatch — returns True if
budget available, False if needs reschedule.

Free-tier TPM/RPM vary by provider. Buckets are in-memory with an
optional Postgres UNLOGGED table backing for cross-process sharing.
Rate-limit reschedule is NOT a retry — the task's not_before timestamp
is set and the task is re-queued without consuming retry attempts.

ARCHITECTURE-AGENTS.md §2.4, §10.3 — key pooling + provider failover.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import ClassVar


@dataclass
class TokenBucket:
    """Sliding-window budget for one (provider, model, key, window).

    Memory is O(requests), not O(tokens): each entry is (timestamp, cost).
    The previous implementation appended one timestamp PER TOKEN, so a
    1,000,000-token TPM budget produced a list of up to a million floats per
    bucket and an O(n) filter over all of them on every capacity check.
    """

    capacity: int
    window_seconds: float = 60.0
    _events: list[tuple[float, int]] = field(default_factory=list)

    def _prune(self, now: float) -> None:
        """Drop entries that have left the window (in-place, front is oldest)."""
        cutoff = now - self.window_seconds
        events = self._events
        keep_from = 0
        while keep_from < len(events) and events[keep_from][0] <= cutoff:
            keep_from += 1
        if keep_from:
            del events[:keep_from]

    def _used(self, now: float) -> int:
        self._prune(now)
        return sum(cost for _, cost in self._events)

    def has_capacity(self, tokens: int) -> bool:
        """Return whether the bucket can accept tokens without consuming them."""
        return self._used(time.monotonic()) + tokens <= self.capacity

    def consume(self, tokens: int) -> None:
        """Consume tokens after a scheduler-wide capacity check."""
        self._events.append((time.monotonic(), tokens))

    def try_consume(self, tokens: int) -> bool:
        """Return True if tokens were consumed within budget."""
        if not self.has_capacity(tokens):
            return False
        self.consume(tokens)
        return True

    def estimated_wait(self, tokens: int) -> float:
        """Seconds until budget likely available."""
        now = time.monotonic()
        used = self._used(now)
        if used + tokens <= self.capacity:
            return 0.0
        # Wait until enough token weight has left the window. Each entry
        # expires window_seconds after its arrival, so releasing ``needed``
        # tokens requires the entry that carried the (used - needed + 1)-th
        # token of weight to age out — the earliest such moment is that
        # entry's arrival time plus the window.
        needed = used + tokens - self.capacity
        remaining_to_free = needed
        for timestamp, cost in self._events:  # oldest first after _prune
            remaining_to_free -= cost
            if remaining_to_free <= 0:
                wait = (timestamp + self.window_seconds) - now
                return max(wait, 1.0)
        return self.window_seconds


@dataclass
class RateLimitScheduler:
    """Per-provider token-bucket scheduler with key pooling.

    Tracks TPM, RPM, and RPD independently. reserve() checks all three
    — a call waits on whichever is scarcest. Key pooling round-robins
    across available API keys for the same (provider, model) pair.
    """

    # Default free-tier limits (per-key, per-minute)
    DEFAULT_TPM: ClassVar[int] = 1_000_000  # tokens per minute
    DEFAULT_RPM: ClassVar[int] = 1_500  # requests per minute
    DEFAULT_RPD: ClassVar[int] = 1_500  # requests per day

    def __init__(self) -> None:
        self._buckets: dict[tuple, tuple[TokenBucket, TokenBucket, TokenBucket]] = {}

    def _key(self, provider: str, model: str, api_key: str) -> tuple:
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]
        return (provider, model, key_hash)

    def register_key(
        self,
        provider: str,
        model: str,
        api_key: str,
        tpm: int = 0,
        rpm: int = 0,
        rpd: int = 0,
    ) -> None:
        k = self._key(provider, model, api_key)
        self._buckets[k] = (
            TokenBucket(capacity=tpm or self.DEFAULT_TPM, window_seconds=60.0),
            TokenBucket(capacity=rpm or self.DEFAULT_RPM, window_seconds=60.0),
            TokenBucket(capacity=rpd or self.DEFAULT_RPD, window_seconds=86400.0),
        )

    def reserve(
        self,
        provider: str,
        model: str,
        api_key: str,
        estimated_tokens: int = 1000,
    ) -> bool:
        """Try to reserve budget. Returns True if all buckets have headroom."""
        k = self._key(provider, model, api_key)
        if k not in self._buckets:
            self.register_key(provider, model, api_key)
        tpm_bucket, rpm_bucket, rpd_bucket = self._buckets[k]
        if not (
            tpm_bucket.has_capacity(estimated_tokens)
            and rpm_bucket.has_capacity(1)
            and rpd_bucket.has_capacity(1)
        ):
            return False
        tpm_bucket.consume(estimated_tokens)
        rpm_bucket.consume(1)
        rpd_bucket.consume(1)
        return True

    def estimated_wait(
        self,
        provider: str,
        model: str,
        api_key: str,
        estimated_tokens: int = 1000,
    ) -> float:
        """Estimate seconds until budget available."""
        k = self._key(provider, model, api_key)
        if k not in self._buckets:
            return 0.0
        tpm_bucket, rpm_bucket, rpd_bucket = self._buckets[k]
        return max(
            tpm_bucket.estimated_wait(estimated_tokens),
            rpm_bucket.estimated_wait(1),
            rpd_bucket.estimated_wait(1),
        )

    def try_reserve_round_robin(
        self,
        provider: str,
        model: str,
        api_keys: list[str],
        estimated_tokens: int = 1000,
    ) -> tuple[str, bool]:
        """Try each key in round-robin order. Returns (key, True) on success,
        or ('', False) if all keys are exhausted.
        """
        for key in api_keys:
            if self.reserve(provider, model, key, estimated_tokens):
                return key, True
        return "", False

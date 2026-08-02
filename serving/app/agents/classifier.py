"""Map a transport-level exception onto a normalized failure kind.

Providers disagree about how to report the same condition: one returns 429 with
a JSON body, another 503 with prose, a third a 400 that only a substring
reveals to be a context overflow. The failover policy must not read any of
that. It reads the vocabulary produced here.

The function never raises. An unrecognized exception classifies as ``unknown``,
which is retryable — the alternative would be a classifier bug turning a
survivable blip into a failed screening run.
"""

from __future__ import annotations

from typing import Final

import httpx

from app.exceptions import ProviderErrorKind

#: HTTP status to failure kind.
#:
#: ``401``/``403`` are ``auth`` rather than fatal because a chain may hold
#: several keys: one being revoked says nothing about the next. ``404`` and
#: ``503`` both mean "not this model, not now" — a free-tier model id can be
#: retired without notice, which reads as 404.
_STATUS_KINDS: Final[dict[int, ProviderErrorKind]] = {
    401: "auth",
    403: "auth",
    404: "model_unavailable",
    408: "network",
    413: "context",
    429: "rate_limit",
    500: "unknown",
    502: "network",
    503: "model_unavailable",
    504: "network",
}

#: Substrings that identify a context overflow inside an otherwise generic 400.
#: Matched case-insensitively against the response body. Kept narrow: a false
#: positive here would stop the chain on a failure another provider could have
#: served.
_CONTEXT_HINTS: Final[tuple[str, ...]] = (
    "context length",
    "context window",
    "maximum context",
    "token count exceeds",
    "too many tokens",
    "reduce the length",
    "input is too long",
)


def _looks_like_context_overflow(response: httpx.Response) -> bool:
    """Report whether a response body complains about prompt length.

    Args:
        response: The provider's error response.

    Returns:
        ``True`` if any known overflow phrasing appears in the body.
    """
    try:
        body = response.text
    except (UnicodeDecodeError, httpx.ResponseNotRead):
        return False

    lowered = body.lower()
    return any(hint in lowered for hint in _CONTEXT_HINTS)


def classify_provider_error(exc: BaseException) -> ProviderErrorKind:
    """Normalize a provider failure into a single vocabulary.

    Args:
        exc: The exception raised while calling a provider.

    Returns:
        One of the :data:`app.exceptions.ProviderErrorKind` values. Anything
        unrecognized becomes ``"unknown"`` rather than raising, so a gap in
        this mapping degrades to "try the next provider" instead of crashing
        the run.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 400 and _looks_like_context_overflow(exc.response):
            return "context"
        mapped = _STATUS_KINDS.get(status)
        if mapped is not None:
            return mapped
        if 500 <= status < 600:
            return "model_unavailable"
        return "unknown"

    if isinstance(exc, httpx.TimeoutException | httpx.NetworkError):
        return "network"

    if isinstance(exc, httpx.TransportError):
        # Protocol and proxy errors that are neither a timeout nor a plain
        # connect failure. Still transport, so still worth another provider.
        return "network"

    return "unknown"

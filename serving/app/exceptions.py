"""Domain exception hierarchy.

Every domain error carries a stable machine-readable `error_code` and the HTTP
`status_code` it maps to, so the global handlers in `app.main` can build the
uniform error envelope without a translation table. Errors are never swallowed:
full detail goes to the logs, and the caller sees a safe message plus the code.
"""

from __future__ import annotations

from typing import ClassVar, Literal


class TalentLensError(Exception):
    """Base class for every domain error raised by this application.

    Attributes:
        error_code: Stable identifier clients may branch on. Never localized,
            never renamed without an API version bump.
        status_code: HTTP status this error maps to.
        default_message: Safe, caller-facing description. Must not leak internals.
    """

    error_code: ClassVar[str] = "INTERNAL_ERROR"
    status_code: ClassVar[int] = 500
    default_message: ClassVar[str] = "An unexpected error occurred."

    def __init__(self, message: str | None = None) -> None:
        """Initialize the error.

        Args:
            message: Optional override for the class-level default message.
        """
        self.message = message or self.default_message
        super().__init__(self.message)


# --------------------------------------------------------------------------- #
# Ingestion / documents                                                        #
# --------------------------------------------------------------------------- #


class DocumentParseError(TalentLensError):
    """Raised when a document cannot be parsed into text."""

    error_code: ClassVar[str] = "DOCUMENT_PARSE_FAILED"
    status_code: ClassVar[int] = 422
    default_message: ClassVar[str] = "The document could not be parsed."


class UnsupportedMediaTypeError(TalentLensError):
    """Raised when an upload's real content type is not on the allowlist."""

    error_code: ClassVar[str] = "UNSUPPORTED_MEDIA_TYPE"
    status_code: ClassVar[int] = 415
    default_message: ClassVar[str] = "File must be a PDF or DOCX document."


class PayloadTooLargeError(TalentLensError):
    """Raised when an upload exceeds the configured size ceiling."""

    error_code: ClassVar[str] = "PAYLOAD_TOO_LARGE"
    status_code: ClassVar[int] = 413
    default_message: ClassVar[str] = "File exceeds the maximum allowed size."


class EmptyDocumentError(TalentLensError):
    """Raised when an upload contains no bytes."""

    error_code: ClassVar[str] = "EMPTY_DOCUMENT"
    status_code: ClassVar[int] = 422
    default_message: ClassVar[str] = "Uploaded file is empty."


# --------------------------------------------------------------------------- #
# Identity                                                                     #
# --------------------------------------------------------------------------- #


class AuthenticationError(TalentLensError):
    """Raised when a caller's credentials are absent, malformed, or invalid."""

    error_code: ClassVar[str] = "UNAUTHENTICATED"
    status_code: ClassVar[int] = 401
    default_message: ClassVar[str] = "Authentication credentials are missing or invalid."


class AuthorizationError(TalentLensError):
    """Raised when an authenticated caller lacks the required role."""

    error_code: ClassVar[str] = "FORBIDDEN"
    status_code: ClassVar[int] = 403
    default_message: ClassVar[str] = "You do not have permission to perform this action."


# --------------------------------------------------------------------------- #
# Resources                                                                    #
# --------------------------------------------------------------------------- #


class ResourceNotFoundError(TalentLensError):
    """Raised when a resource does not exist, or is not visible to this tenant."""

    error_code: ClassVar[str] = "NOT_FOUND"
    status_code: ClassVar[int] = 404
    default_message: ClassVar[str] = "The requested resource was not found."


class ResourceConflictError(TalentLensError):
    """Raised when a mutation conflicts with existing state."""

    error_code: ClassVar[str] = "CONFLICT"
    status_code: ClassVar[int] = 409
    default_message: ClassVar[str] = "The request conflicts with the current state."


class ValidationFailedError(TalentLensError):
    """Raised when input fails a service-layer invariant."""

    error_code: ClassVar[str] = "VALIDATION_FAILED"
    status_code: ClassVar[int] = 422
    default_message: ClassVar[str] = "The request payload failed validation."


class StorageError(TalentLensError):
    """Raised when the object store cannot satisfy a read or write."""

    error_code: ClassVar[str] = "STORAGE_UNAVAILABLE"
    status_code: ClassVar[int] = 503
    default_message: ClassVar[str] = "Document storage is temporarily unavailable."


# --------------------------------------------------------------------------- #
# Search / Embeddings (Phase 2)                                                #
# --------------------------------------------------------------------------- #


class EmbeddingServiceUnavailableError(TalentLensError):
    """Raised when the embedding service cannot be reached."""

    error_code: ClassVar[str] = "EMBEDDING_SERVICE_UNAVAILABLE"
    status_code: ClassVar[int] = 503
    default_message: ClassVar[str] = "The embedding service is temporarily unavailable."


class SearchError(TalentLensError):
    """Raised when a search operation fails unexpectedly."""

    error_code: ClassVar[str] = "SEARCH_FAILED"
    status_code: ClassVar[int] = 500
    default_message: ClassVar[str] = "The search operation failed."


# --------------------------------------------------------------------------- #
# Scoring (Phase 4)                                                            #
# --------------------------------------------------------------------------- #


class CoreStageFailedError(TalentLensError):
    """Raised when a stage that scoring depends on could not complete.

    Scoring has no safe fallback. A stage that fails must abort the run rather
    than substitute a default verdict, which would bias the score silently and
    leave a number nobody can account for.
    """

    error_code: ClassVar[str] = "CORE_STAGE_FAILED"
    status_code: ClassVar[int] = 500
    default_message: ClassVar[str] = "A required scoring stage failed."


class EvidenceSpanMismatchError(CoreStageFailedError):
    """Raised when a cited span is not present verbatim at its claimed offset.

    Evidence is the audit trail behind a verdict. A quote that does not sit at
    the offset it claims cannot be reviewed, so the verdict citing it is not
    admissible.
    """

    error_code: ClassVar[str] = "EVIDENCE_SPAN_MISMATCH"
    status_code: ClassVar[int] = 500
    default_message: ClassVar[str] = "Cited evidence does not match the source document."


# --------------------------------------------------------------------------- #
# LLM providers (Phase 4)                                                      #
# --------------------------------------------------------------------------- #

#: Normalized failure kinds. Provider APIs disagree on how they report the same
#: condition, so every adapter maps its own errors onto this vocabulary and the
#: failover policy reads only from here.
ProviderErrorKind = Literal[
    "rate_limit", "auth", "context", "model_unavailable", "network", "unknown"
]


class LLMProviderError(TalentLensError):
    """Raised when a provider call fails for a reason worth classifying.

    Carries the normalized ``kind`` so the failover chain can decide whether
    another provider could plausibly do better. A rate limit or a network blip
    is worth retrying elsewhere; a context overflow is not, because the same
    oversized prompt would overflow the next provider too.

    Attributes:
        kind: Normalized failure category.
        provider: Which adapter raised this, for logs and metrics.
    """

    error_code: ClassVar[str] = "LLM_PROVIDER_ERROR"
    status_code: ClassVar[int] = 502
    default_message: ClassVar[str] = "The language model provider failed."

    def __init__(
        self,
        message: str | None = None,
        *,
        kind: ProviderErrorKind = "unknown",
        provider: str = "",
    ) -> None:
        """Initialize the error.

        Args:
            message: Safe, caller-facing description. Must never contain an
                API key or prompt content.
            kind: Normalized failure category.
            provider: Name of the adapter that failed.
        """
        super().__init__(message)
        self.kind = kind
        self.provider = provider


class LLMRefusalError(TalentLensError):
    """Raised when a model declines to answer.

    A refusal is not a transport failure and must not be retried against
    another provider: the second model would most likely refuse too, and a
    refusal can be policy-correct. It is surfaced to the caller instead.
    """

    error_code: ClassVar[str] = "LLM_REFUSAL"
    status_code: ClassVar[int] = 422
    default_message: ClassVar[str] = "The language model declined to answer this request."


class NoEligibleProviderError(TalentLensError):
    """Raised when no configured provider may serve a request.

    Two distinct causes, deliberately sharing one code: every provider in the
    chain failed, or none is permitted to see data at the request's PII tier.
    In both cases the run cannot proceed, and in neither may a default answer
    be substituted.
    """

    error_code: ClassVar[str] = "NO_ELIGIBLE_PROVIDER"
    status_code: ClassVar[int] = 503
    default_message: ClassVar[str] = "No language model provider is available for this request."


class BudgetExceededError(TalentLensError):
    """Raised when a token or spend ceiling would be crossed by this call.

    Maps to 429 rather than 402: the caller should retry later or degrade,
    which is the same remedy as a rate limit.
    """

    error_code: ClassVar[str] = "BUDGET_EXCEEDED"
    status_code: ClassVar[int] = 429
    default_message: ClassVar[str] = "The configured token budget has been exhausted."


"""Domain exception hierarchy.

Every domain error carries a stable machine-readable `error_code` and the HTTP
`status_code` it maps to, so the global handlers in `app.main` can build the
uniform error envelope without a translation table. Errors are never swallowed:
full detail goes to the logs, and the caller sees a safe message plus the code.
"""

from __future__ import annotations

from typing import ClassVar


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

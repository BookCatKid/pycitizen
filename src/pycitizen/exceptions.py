"""Exception hierarchy for pycitizen."""

from __future__ import annotations


class CitizenError(Exception):
    """Base class for all pycitizen errors."""


class CitizenConnectionError(CitizenError):
    """Raised when the API cannot be reached (DNS, TLS, refused, ...)."""


class CitizenTimeoutError(CitizenConnectionError):
    """Raised when a request times out."""


class CitizenResponseError(CitizenError):
    """Raised for non-2xx HTTP responses after retries are exhausted."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class CitizenAuthError(CitizenResponseError):
    """Raised for 401/403 responses (endpoint requires authentication)."""


class CitizenNotFoundError(CitizenResponseError):
    """Raised for 404 responses."""


class CitizenRateLimitError(CitizenResponseError):
    """Raised when the server keeps returning 429 after all retries."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = 429,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, status=status)
        self.retry_after = retry_after


class CitizenParseError(CitizenError):
    """Raised when a response body cannot be decoded as expected."""


class CitizenTileError(CitizenParseError):
    """Raised when a vector tile cannot be decoded."""

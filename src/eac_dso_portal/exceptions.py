"""Exceptions raised by :mod:`eac_dso_portal`."""

from __future__ import annotations


class EacError(Exception):
    """Base class for all errors raised by this package."""


class EacAuthError(EacError):
    """Login was rejected, or the JWT could not be refreshed."""


class EacApiError(EacError):
    """Non-2xx response from the API that is not an auth failure."""

    def __init__(self, status: int, message: str = "", path: str = "") -> None:
        super().__init__(f"HTTP {status} on {path}: {message[:200]}")
        self.status = status
        self.message = message
        self.path = path


class EacRateLimitError(EacApiError):
    """HTTP 429 from the API."""

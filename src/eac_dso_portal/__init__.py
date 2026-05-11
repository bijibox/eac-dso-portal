"""Async client for the EAC (Electricity Authority of Cyprus) Distribution Web Portal."""

from .client import DEFAULT_BASE_URL, EacClient
from .exceptions import EacApiError, EacAuthError, EacError, EacRateLimitError
from .models import (
    ChannelReadings,
    MeasurementChannel,
    MeterConfig,
    Reading,
    ServicePoint,
    UserDetails,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "ChannelReadings",
    "EacApiError",
    "EacAuthError",
    "EacClient",
    "EacError",
    "EacRateLimitError",
    "MeasurementChannel",
    "MeterConfig",
    "Reading",
    "ServicePoint",
    "UserDetails",
]

__version__ = "0.2.0"

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
from .time import CYPRUS, as_utc

__all__ = [
    "CYPRUS",
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
    "as_utc",
]

__version__ = "0.3.0"

"""Data classes returned by :class:`eac_dso_portal.EacClient`."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class UserDetails:
    name: str
    admin: bool
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ServicePoint:
    id: str
    address: str
    active: bool
    device_exists: bool
    serial_number: str | None
    phases: str | None
    load_entitlement: str | None
    load_entitlement_uom: str | None
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class MeasurementChannel:
    id: str
    type: str
    uom: str
    tou: str
    interval: bool
    digits_left: int
    digits_right: int
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class MeterConfig:
    serial_number: str | None
    manufacturer: str | None
    model: str | None
    install_date: datetime | None
    removal_date: datetime | None
    channels: tuple[MeasurementChannel, ...]
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Reading:
    dt: datetime
    value: float
    # Cumulative meter total in kWh. None for interval channels (e.g. KWH-30MIN-LP-*),
    # which only report the value consumed in the slot.
    reading: float | None


@dataclass(frozen=True, slots=True)
class ChannelReadings:
    channel_id: str
    readings: tuple[Reading, ...]

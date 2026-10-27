"""Async client for the EAC Distribution Web Portal REST API."""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp

from .exceptions import EacApiError, EacAuthError, EacRateLimitError
from .models import (
    ChannelReadings,
    MeasurementChannel,
    MeterConfig,
    Reading,
    ServicePoint,
    UserDetails,
)
from .time import CYPRUS, normalize_readings

_LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://meterreading-dso.eac.com.cy"


class EacClient:
    """Async client for the EAC DSO portal.

    The portal exposes an undocumented JSON API guarded by a short-lived JWT
    (~24h). The client transparently re-logs in on 401.

    Example::

        async with aiohttp.ClientSession() as session:
            client = EacClient("you@example.com", "password", session=session)
            await client.login()
            for sp in await client.list_service_points():
                if sp.active:
                    print(sp.address)
    """

    def __init__(
        self,
        email: str,
        password: str,
        *,
        session: aiohttp.ClientSession,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self._email = email
        self._password = password
        self._session = session
        self._base = base_url.rstrip("/")
        self._jwt: str | None = None

    @property
    def jwt(self) -> str | None:
        return self._jwt

    # ----- auth -----

    async def login(self) -> None:
        """POST /api/portal/login and store the returned JWT."""
        url = f"{self._base}/api/portal/login"
        payload = {"email": self._email, "password": self._password}
        async with self._session.post(url, json=payload) as resp:
            if resp.status == 200:
                data = await resp.json()
                jwt = data.get("jwt")
                if not jwt:
                    raise EacAuthError("Login response missing 'jwt' field")
                self._jwt = jwt
                return
            text = await resp.text()
            if resp.status in (401, 403):
                raise EacAuthError(f"Login rejected (HTTP {resp.status}): {text[:200]}")
            raise EacApiError(resp.status, text, "/api/portal/login")

    # ----- internal -----

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        params: dict[str, str] | None = None,
        _retried: bool = False,
    ) -> Any:
        if self._jwt is None:
            await self.login()
        headers = {"Authorization": f"Bearer {self._jwt}"}
        url = f"{self._base}{path}"
        async with self._session.request(
            method, url, headers=headers, json=json_body, params=params
        ) as resp:
            if resp.status == 401 and not _retried:
                _LOGGER.debug("JWT rejected, refreshing and retrying %s %s", method, path)
                self._jwt = None
                await self.login()
                return await self._request(
                    method, path, json_body=json_body, params=params, _retried=True
                )
            if resp.status == 429:
                raise EacRateLimitError(resp.status, await resp.text(), path)
            if resp.status != 200:
                # Anything other than 200 is unexpected: the portal returns
                # 200 for success and 4xx/5xx for errors, never 201/204/3xx.
                # Raising explicitly produces a useful message rather than
                # a confusing JSON decode failure on a 204 No Content.
                raise EacApiError(resp.status, await resp.text(), path)
            return await resp.json()

    # ----- endpoints -----

    async def get_user_details(self) -> UserDetails:
        d = await self._request("GET", "/api/portal/userDetails")
        return UserDetails(name=d.get("name", ""), admin=bool(d.get("admin")), raw=d)

    async def list_service_points(self) -> list[ServicePoint]:
        data = await self._request("GET", "/api/portal/servicePoints")
        return [_parse_service_point(d) for d in data]

    async def get_meter_configs(self, sp_id: str) -> list[MeterConfig]:
        """Return all meters that have ever been installed on this service point.

        The portal returns a list of meter records (old plus any replacements).
        Each record contains one or more configurations, and each configuration
        has a list of measurement channels (mcList).
        """
        data = await self._request("GET", f"/api/portal/servicePoints/{sp_id}")
        return [_parse_meter_config(d) for d in data]

    async def get_readings(
        self,
        sp_id: str,
        start: datetime,
        end: datetime,
        mc_id: str | None = None,
        chunk_days: int = 14,
    ) -> list[ChannelReadings]:
        """Fetch readings for a service point.

        Without ``mc_id`` the API returns the default summary channels only
        (typically ``S-KWH-24H``). Pass an ``mc_id`` from
        :meth:`get_meter_configs` to fetch a specific channel, including
        30-minute load profile channels (``KWH-30MIN-LP-*``).

        The portal caps each ``/readings/list`` response at 1000 rows. For a
        30-minute channel that is roughly 1000 / 48 = 20 days of data, so a
        wider request will silently lose the tail. When the requested range
        is longer than ``chunk_days``, the call is transparently split into
        back-to-back requests and the results merged, with duplicates on the
        chunk boundaries dropped. ``chunk_days`` defaults to 14 which fits
        the 1000-row cap for every channel type the portal exposes today.
        """
        if not 1 <= chunk_days <= 14:
            raise ValueError("chunk_days must be between 1 and 14 (1000-row limit)")
        # Public query arguments retain the original naive-as-UTC contract.
        start = start.replace(tzinfo=UTC) if start.tzinfo is None else start.astimezone(UTC)
        end = end.replace(tzinfo=UTC) if end.tzinfo is None else end.astimezone(UTC)
        if start > end:
            raise ValueError("start must not be after end")

        # Fetch complete local days, including both folds even when the caller's
        # boundary falls inside the repeated autumn hour. Requests overlap at
        # midnight; deduplication is by UTC instant, never by wall-clock label.
        chunk_start = start.astimezone(CYPRUS).replace(hour=0, minute=0, second=0, microsecond=0)
        stop = end.astimezone(CYPRUS).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        by_dt: dict[str, dict[datetime, Reading]] = {}
        while chunk_start < stop:
            chunk_end = min(chunk_start + timedelta(days=chunk_days), stop)
            chunk_data = await self._readings_request(
                sp_id, chunk_start - timedelta(days=1), chunk_end + timedelta(days=1), mc_id
            )
            for cr in chunk_data:
                bucket = by_dt.setdefault(cr.channel_id, {})
                for r in cr.readings:
                    if start <= r.dt <= end:
                        bucket[r.dt] = r
            chunk_start = chunk_end

        return [
            ChannelReadings(channel_id=cid, readings=tuple(rs[dt] for dt in sorted(rs)))
            for cid, rs in by_dt.items()
        ]

    async def _readings_request(
        self,
        sp_id: str,
        start: datetime,
        end: datetime,
        mc_id: str | None,
    ) -> list[ChannelReadings]:
        body: dict[str, Any] = {
            "spId": sp_id,
            "startDate": _to_iso_z(start),
            "endDate": _to_iso_z(end),
        }
        if mc_id is not None:
            body["mcId"] = mc_id
        data = await self._request("POST", "/api/portal/readings/list", json_body=body)
        if any(len(item.get("readings") or []) >= 1000 for item in data):
            # Fail instead of silently accepting a truncated page.
            raise EacApiError(
                200, "Readings response reached the 1000-row cap", "/api/portal/readings/list"
            )
        return [_parse_channel_readings(item) for item in data]


def _parse_service_point(d: dict[str, Any]) -> ServicePoint:
    return ServicePoint(
        id=str(d["id"]),
        address=d.get("address", ""),
        active=bool(d.get("active")),
        device_exists=bool(d.get("deviceExists")),
        serial_number=d.get("serialNumber"),
        phases=d.get("phases"),
        load_entitlement=d.get("loadEntitlement"),
        load_entitlement_uom=d.get("loadEntitlementUOM"),
        raw=d,
    )


def _parse_meter_config(d: dict[str, Any]) -> MeterConfig:
    channels: list[MeasurementChannel] = []
    for cfg in d.get("configurationsList", []) or []:
        for mc in cfg.get("mcList", []) or []:
            channels.append(
                MeasurementChannel(
                    id=str(mc["id"]),
                    type=mc.get("type", ""),
                    uom=mc.get("uom", ""),
                    tou=mc.get("tou", "") or "",
                    interval=bool(mc.get("interval")),
                    digits_left=int(mc.get("digitsLeft", 0) or 0),
                    digits_right=int(mc.get("digitsRight", 0) or 0),
                    raw=mc,
                )
            )
    return MeterConfig(
        serial_number=d.get("serialNumber"),
        manufacturer=d.get("manufacturer"),
        model=d.get("model"),
        install_date=_parse_dt(d.get("installDate")),
        removal_date=_parse_dt(d.get("removalDate")),
        channels=tuple(channels),
        raw=d,
    )


def _parse_channel_readings(item: dict[str, Any]) -> ChannelReadings:
    points = []
    for r in item.get("readings", []) or []:
        try:
            dt = datetime.fromisoformat(r["dt"])
            value = float(r["value"])
            reading = float(r["reading"]) if r.get("reading") is not None else None
            if not math.isfinite(value) or (reading is not None and not math.isfinite(reading)):
                raise ValueError("non-finite energy")
        except (KeyError, TypeError, ValueError) as err:
            raise EacApiError(
                200, "Invalid reading timestamp or energy", "/api/portal/readings/list"
            ) from err
        points.append(Reading(dt=dt, value=value, reading=reading))
    return ChannelReadings(channel_id=str(item["id"]), readings=normalize_readings(tuple(points)))


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s)


def _to_iso_z(dt: datetime) -> str:
    """Format a datetime as an ISO-8601 UTC string with milliseconds and Z suffix.

    The API rejects offsets like ``+00:00`` and demands the literal ``Z``.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt_utc = dt.astimezone(UTC).replace(tzinfo=None)
    return dt_utc.isoformat(timespec="milliseconds") + "Z"

"""Async client for the EAC Distribution Web Portal REST API."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
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
                raise EacAuthError(
                    f"Login rejected (HTTP {resp.status}): {text[:200]}"
                )
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
            if resp.status >= 400:
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
        """Return *all* meters that have ever been installed on this service point.

        The portal returns a list of meter records (old + replacement). Each
        record contains one or more configurations, and each configuration has
        a list of measurement channels (mcList).
        """
        data = await self._request("GET", f"/api/portal/servicePoints/{sp_id}")
        return [_parse_meter_config(d) for d in data]

    async def get_readings(
        self,
        sp_id: str,
        start: datetime,
        end: datetime,
        mc_id: str | None = None,
    ) -> list[ChannelReadings]:
        """Fetch readings for a service point.

        Without ``mc_id`` the API returns the default summary channels only
        (typically ``S-KWH-24H``). Pass an ``mc_id`` from
        :meth:`get_meter_configs` to fetch a specific channel — including
        30-minute load profile channels (``KWH-30MIN-LP-*``).
        """
        body: dict[str, Any] = {
            "spId": sp_id,
            "startDate": _to_iso_z(start),
            "endDate": _to_iso_z(end),
        }
        if mc_id is not None:
            body["mcId"] = mc_id
        data = await self._request("POST", "/api/portal/readings/list", json_body=body)
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
            channels.append(MeasurementChannel(
                id=str(mc["id"]),
                type=mc.get("type", ""),
                uom=mc.get("uom", ""),
                tou=mc.get("tou", "") or "",
                interval=bool(mc.get("interval")),
                digits_left=int(mc.get("digitsLeft", 0) or 0),
                digits_right=int(mc.get("digitsRight", 0) or 0),
                raw=mc,
            ))
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
    return ChannelReadings(
        channel_id=str(item["id"]),
        readings=tuple(
            Reading(
                dt=_parse_dt(r["dt"]) or datetime.fromtimestamp(0, tz=timezone.utc),
                value=float(r.get("value", 0.0)),
                reading=float(r["reading"]) if r.get("reading") is not None else None,
            )
            for r in item.get("readings", []) or []
        ),
    )


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s)


def _to_iso_z(dt: datetime) -> str:
    """Format a datetime as an ISO-8601 UTC string with milliseconds and Z suffix.

    The API rejects offsets like ``+00:00`` and demands the literal ``Z``.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_utc = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt_utc.isoformat(timespec="milliseconds") + "Z"

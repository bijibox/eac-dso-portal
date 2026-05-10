"""Shared pytest fixtures and synthetic API payloads.

Real responses (with the user's real address and meter serials) were used to
shape these payloads but the values here are synthetic.
"""

from __future__ import annotations

from typing import Any

import aiohttp
import pytest
from aioresponses import aioresponses

from eac_dso_portal import EacClient

BASE_URL = "https://meterreading-dso.eac.com.cy"
URL_LOGIN = f"{BASE_URL}/api/portal/login"
URL_USER_DETAILS = f"{BASE_URL}/api/portal/userDetails"
URL_SERVICE_POINTS = f"{BASE_URL}/api/portal/servicePoints"
URL_READINGS = f"{BASE_URL}/api/portal/readings/list"


def url_service_point(sp_id: str) -> str:
    return f"{BASE_URL}/api/portal/servicePoints/{sp_id}"


# ---------------- session / mock fixtures ----------------


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as s:
        yield s


@pytest.fixture
def mock_http():
    with aioresponses() as m:
        yield m


@pytest.fixture
async def logged_in_client(session, mock_http):
    """Client whose login() has already been mocked + called."""
    mock_http.post(URL_LOGIN, payload={"jwt": "fake-jwt-token"})
    client = EacClient("test@example.com", "pw", session=session, base_url=BASE_URL)
    await client.login()
    return client


# ---------------- synthetic payloads ----------------


@pytest.fixture
def payload_user_details() -> dict[str, Any]:
    return {"admin": False, "ids": [], "name": "Test User", "phones": []}


@pytest.fixture
def payload_service_points_one_active() -> list[dict[str, Any]]:
    """Account with one active and one historical service point."""
    return [
        {
            "id": "111111111111",
            "address": "1 Test St, City",
            "active": True,
            "deviceExists": True,
            "loadEntitlement": "30",
            "loadEntitlementUOM": "AMP",
            "phases": "3",
            "serialNumber": "S111",
            "servicePeriodList": [],
            "unmetered": False,
        },
        {
            "id": "222222222222",
            "address": "2 Old Rd, City",
            "active": False,
            "deviceExists": True,
            "serialNumber": "S222",
            "servicePeriodList": [],
            "unmetered": False,
        },
    ]


@pytest.fixture
def payload_meter_configs_swap() -> list[dict[str, Any]]:
    """Two meters: an old non-smart one (removed) and an active smart one."""
    return [
        {
            "manufacturer": "ITRON",
            "model": "ACE3000",
            "serialNumber": "OLD123",
            "installDate": "2018-01-01T00:00:00",
            "removalDate": "2026-02-02T00:00:00",
            "configurationsList": [
                {
                    "configurationId": "cfg-old",
                    "startDate": "2018-01-01T00:00:00",
                    "endDate": "2026-02-02T00:00:00",
                    "mcList": [
                        {
                            "id": "mc-old-total",
                            "type": "S-KWH",
                            "uom": "KWH",
                            "tou": "",
                            "interval": False,
                            "digitsLeft": 6,
                            "digitsRight": 0,
                        },
                    ],
                },
            ],
        },
        {
            "manufacturer": "LANDIS & GYR",
            "model": "E450",
            "serialNumber": "NEW123",
            "installDate": "2026-02-02T00:00:00",
            "removalDate": None,
            "configurationsList": [
                {
                    "configurationId": "cfg-new",
                    "startDate": "2026-02-02T00:00:00",
                    "mcList": [
                        {
                            "id": "mc-total-24h",
                            "type": "S-KWH-24H",
                            "uom": "KWH",
                            "tou": "24H",
                            "interval": False,
                            "digitsLeft": 8,
                            "digitsRight": 0,
                        },
                        {
                            "id": "mc-30min-imp",
                            "type": "KWH-30MIN-LP-IMP",
                            "uom": "KWH",
                            "tou": "30MIN",
                            "interval": True,
                            "digitsLeft": 4,
                            "digitsRight": 3,
                        },
                    ],
                },
            ],
        },
    ]


@pytest.fixture
def payload_readings_summary() -> list[dict[str, Any]]:
    """Cumulative daily readings — `reading` field present."""
    return [
        {
            "id": "mc-total-24h",
            "readings": [
                {"dt": "2026-05-01T00:00:00", "reading": 2900.0, "value": 23.0},
                {"dt": "2026-05-02T00:00:00", "reading": 2924.0, "value": 24.0},
            ],
        },
    ]


@pytest.fixture
def payload_readings_interval() -> list[dict[str, Any]]:
    """30-min profile — only `value`, no `reading`."""
    return [
        {
            "id": "mc-30min-imp",
            "readings": [
                {"dt": "2026-05-01T01:00:00", "value": 0.495},
                {"dt": "2026-05-01T01:30:00", "value": 0.520},
                {"dt": "2026-05-01T02:00:00", "value": 0.310},
            ],
        },
    ]

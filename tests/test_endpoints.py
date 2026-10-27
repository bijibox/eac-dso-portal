"""Endpoint methods + payload parsing into dataclasses."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from aioresponses.core import CallbackResult

from eac_dso_portal import Reading

from .conftest import (
    URL_READINGS,
    URL_SERVICE_POINTS,
    URL_USER_DETAILS,
    url_service_point,
)

# ---------- get_user_details ----------


async def test_get_user_details(mock_http, logged_in_client, payload_user_details) -> None:
    mock_http.get(URL_USER_DETAILS, payload=payload_user_details)
    user = await logged_in_client.get_user_details()
    assert user.name == "Test User"
    assert user.admin is False
    assert user.raw == payload_user_details


async def test_get_user_details_admin_flag(mock_http, logged_in_client) -> None:
    mock_http.get(
        URL_USER_DETAILS,
        payload={"name": "Admin", "admin": True, "ids": ["x"], "phones": []},
    )
    user = await logged_in_client.get_user_details()
    assert user.admin is True


# ---------- list_service_points ----------


async def test_list_service_points_parses_active_and_inactive(
    mock_http, logged_in_client, payload_service_points_one_active
) -> None:
    mock_http.get(URL_SERVICE_POINTS, payload=payload_service_points_one_active)
    sps = await logged_in_client.list_service_points()
    assert len(sps) == 2
    active = next(s for s in sps if s.active)
    inactive = next(s for s in sps if not s.active)
    assert active.id == "111111111111"
    assert active.address == "1 Test St, City"
    assert active.phases == "3"
    assert active.load_entitlement == "30"
    assert active.load_entitlement_uom == "AMP"
    assert active.serial_number == "S111"
    assert inactive.id == "222222222222"
    assert inactive.phases is None  # missing in synthetic payload


async def test_list_service_points_empty_account(mock_http, logged_in_client) -> None:
    mock_http.get(URL_SERVICE_POINTS, payload=[])
    assert await logged_in_client.list_service_points() == []


# ---------- get_meter_configs ----------


async def test_get_meter_configs_old_and_new_meter(
    mock_http, logged_in_client, payload_meter_configs_swap
) -> None:
    sp_id = "111111111111"
    mock_http.get(url_service_point(sp_id), payload=payload_meter_configs_swap)

    configs = await logged_in_client.get_meter_configs(sp_id)
    assert len(configs) == 2

    old, new = configs
    assert old.manufacturer == "ITRON"
    assert old.removal_date == datetime(2026, 2, 2, 0, 0)
    assert len(old.channels) == 1
    assert old.channels[0].type == "S-KWH"
    assert old.channels[0].interval is False

    assert new.manufacturer == "LANDIS & GYR"
    assert new.removal_date is None
    assert {c.type for c in new.channels} == {"S-KWH-24H", "KWH-30MIN-LP-IMP"}
    interval_ch = next(c for c in new.channels if c.interval)
    assert interval_ch.type == "KWH-30MIN-LP-IMP"


async def test_get_meter_configs_handles_missing_optional_fields(
    mock_http, logged_in_client
) -> None:
    """API sometimes omits optional fields like tou or digits."""
    sp_id = "333"
    mock_http.get(
        url_service_point(sp_id),
        payload=[
            {
                "manufacturer": "X",
                "model": "Y",
                "serialNumber": "Z",
                "installDate": "2026-01-01T00:00:00",
                "configurationsList": [
                    {
                        "configurationId": "c1",
                        "mcList": [
                            {"id": "1", "type": "S-KWH", "uom": "KWH"},
                        ],
                    }
                ],
            }
        ],
    )
    configs = await logged_in_client.get_meter_configs(sp_id)
    ch = configs[0].channels[0]
    assert ch.tou == ""
    assert ch.digits_left == 0
    assert ch.digits_right == 0
    assert ch.interval is False


# ---------- get_readings ----------


async def test_get_readings_summary_no_mc_id(
    mock_http, logged_in_client, payload_readings_summary
) -> None:
    """Calling without mc_id returns the default summary channels."""
    mock_http.post(URL_READINGS, payload=payload_readings_summary)

    start = datetime(2026, 4, 20, tzinfo=UTC)
    end = datetime(2026, 5, 3, tzinfo=UTC)
    channels = await logged_in_client.get_readings("111", start, end)

    assert len(channels) == 1
    cr = channels[0]
    assert cr.channel_id == "mc-total-24h"
    assert len(cr.readings) == 2
    assert cr.readings[0].reading == 2900.0
    assert cr.readings[0].value == 23.0
    # All cumulative readings have non-None .reading
    assert all(r.reading is not None for r in cr.readings)


async def test_get_readings_with_mc_id_includes_in_body(
    mock_http, logged_in_client, payload_readings_interval
) -> None:
    """Calling with mc_id must add it to the request body."""
    captured_bodies: list[dict] = []

    def handler(url, **kwargs):
        captured_bodies.append(kwargs.get("json"))
        from aioresponses.core import CallbackResult

        return CallbackResult(status=200, payload=payload_readings_interval)

    mock_http.post(URL_READINGS, callback=handler)

    start = datetime(2026, 4, 30, tzinfo=UTC)
    end = datetime(2026, 5, 2, tzinfo=UTC)
    await logged_in_client.get_readings("111", start, end, mc_id="mc-30min-imp")

    body = captured_bodies[0]
    assert body["spId"] == "111"
    assert body["mcId"] == "mc-30min-imp"
    # ISO-8601 with Z suffix and milliseconds (the portal rejects +00:00)
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", body["startDate"])


async def test_get_readings_interval_channel_has_no_cumulative(
    mock_http, logged_in_client, payload_readings_interval
) -> None:
    """30-min profile readings have value but no cumulative `reading`."""
    mock_http.post(URL_READINGS, payload=payload_readings_interval)

    start = datetime(2026, 4, 30, tzinfo=UTC)
    end = datetime(2026, 5, 2, tzinfo=UTC)
    channels = await logged_in_client.get_readings("111", start, end, mc_id="mc-30min-imp")
    cr = channels[0]
    assert cr.channel_id == "mc-30min-imp"
    assert len(cr.readings) == 3
    for r in cr.readings:
        assert isinstance(r, Reading)
        assert r.reading is None
        assert r.value > 0


async def test_get_readings_naive_datetime_treated_as_utc(
    mock_http, logged_in_client, payload_readings_summary
) -> None:
    """Datetimes without tzinfo must be serialised as UTC, not local time."""
    captured: list[dict] = []

    def handler(url, **kwargs):
        captured.append(kwargs.get("json"))
        from aioresponses.core import CallbackResult

        return CallbackResult(status=200, payload=payload_readings_summary)

    mock_http.post(URL_READINGS, callback=handler)

    naive = datetime(2026, 5, 1, 12, 0, 0)
    await logged_in_client.get_readings("111", naive, naive)
    # Padded whole Cyprus days are serialized in UTC.
    assert captured[0]["startDate"] == "2026-04-29T21:00:00.000Z"


async def test_get_readings_empty_channel(mock_http, logged_in_client) -> None:
    """Empty `readings` list is fine."""
    mock_http.post(URL_READINGS, payload=[{"id": "x", "readings": []}])
    channels = await logged_in_client.get_readings("111", datetime.now(UTC), datetime.now(UTC))
    assert channels[0].readings == ()


async def test_get_readings_chunks_long_ranges(mock_http, logged_in_client) -> None:
    """Inclusive date-rounded pages overlap; each physical slot survives once."""
    from datetime import timedelta

    from eac_dso_portal import CYPRUS

    captured = []

    def handler(url, **kwargs):
        body = kwargs["json"]
        captured.append(body)
        start = datetime.fromisoformat(body["startDate"]).astimezone(CYPRUS)
        end = datetime.fromisoformat(body["endDate"]).astimezone(CYPRUS)
        # Observed summer portal boundaries: 01:00 through next day 00:30.
        dt = start.replace(hour=1)
        end = end.replace(hour=1) + timedelta(days=1)
        rows = []
        while dt < end:
            rows.append({"dt": dt.replace(tzinfo=None).isoformat(), "value": 0.001})
            dt += timedelta(minutes=30)
        return CallbackResult(status=200, payload=[{"id": "x", "readings": rows}])

    mock_http.post(URL_READINGS, callback=handler, repeat=True)
    start = datetime(2026, 4, 1, tzinfo=CYPRUS)
    end = datetime(2026, 5, 1, tzinfo=CYPRUS)
    channels = await logged_in_client.get_readings("111", start, end, mc_id="x")
    assert len(captured) == 3
    assert len(channels[0].readings) == 30 * 48 + 1
    assert channels[0].readings[0].dt == start.astimezone(UTC)
    assert channels[0].readings[-1].dt == end.astimezone(UTC)


async def test_get_readings_chunk_days_override(mock_http, logged_in_client) -> None:
    captured = []

    def handler(url, **kwargs):
        captured.append(kwargs["json"])
        return CallbackResult(status=200, payload=[{"id": "x", "readings": []}])

    mock_http.post(URL_READINGS, callback=handler, repeat=True)
    await logged_in_client.get_readings(
        "111", datetime(2026, 4, 1, tzinfo=UTC), datetime(2026, 5, 1, tzinfo=UTC), chunk_days=7
    )
    assert len(captured) == 5

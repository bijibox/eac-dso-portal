"""DST, validation and pagination regressions."""

from datetime import UTC, datetime

import pytest

from eac_dso_portal import EacApiError, Reading, as_utc
from eac_dso_portal.client import _parse_channel_readings
from eac_dso_portal.time import normalize_readings

from .conftest import URL_READINGS


def test_repeated_labels_equal_values_are_distinct_intervals():
    times = [
        "2026-10-25T02:30:00",
        "2026-10-25T03:00:00",
        "2026-10-25T03:00:00",
        "2026-10-25T03:30:00",
        "2026-10-25T03:30:00",
        "2026-10-25T04:00:00",
    ]
    values = [0.1, 0.028, 0.028, 0.03, 0.032, 0.2]
    rows = tuple(
        Reading(datetime.fromisoformat(t), v, None) for t, v in zip(times, values, strict=True)
    )
    actual = normalize_readings(rows)
    assert len(actual) == 6
    assert [r.dt.isoformat() for r in actual] == [
        "2026-10-24T23:30:00+00:00",
        "2026-10-25T00:00:00+00:00",
        "2026-10-25T00:30:00+00:00",
        "2026-10-25T01:00:00+00:00",
        "2026-10-25T01:30:00+00:00",
        "2026-10-25T02:00:00+00:00",
    ]
    assert normalize_readings(tuple(reversed(rows))) == actual


@pytest.mark.parametrize("dt", ["2026-03-29T03:30:00", "2026-10-25T03:30:00"])
def test_impossible_or_incomplete_ambiguous_time_is_rejected(dt):
    with pytest.raises(EacApiError):
        normalize_readings((Reading(datetime.fromisoformat(dt), 0.1, None),))


def test_explicit_offsets_and_naive_cyprus_time():
    assert as_utc(datetime(2026, 5, 1)) == datetime(2026, 4, 30, 21, tzinfo=UTC)
    rows = tuple(
        Reading(datetime.fromisoformat(t), 0.1, None)
        for t in ["2026-10-25T03:00:00+03:00", "2026-10-25T03:00:00+02:00"]
    )
    assert len(normalize_readings(rows)) == 2


@pytest.mark.parametrize(
    "row",
    [
        {"value": 0.1},
        {"dt": "2026-01-01T00:00:00"},
        {"dt": "2026-01-01T00:00:00", "value": float("nan")},
    ],
)
def test_bad_readings_never_become_zero_energy(row):
    with pytest.raises(EacApiError):
        _parse_channel_readings({"id": "x", "readings": [row]})


@pytest.mark.parametrize("days", [0, -1, 15, 100])
async def test_invalid_chunk_sizes(logged_in_client, days):
    with pytest.raises(ValueError):
        await logged_in_client.get_readings(
            "x", datetime(2026, 1, 1), datetime(2026, 2, 1), chunk_days=days
        )


async def test_truncated_response_rejected(mock_http, logged_in_client):
    mock_http.post(
        URL_READINGS,
        payload=[{"id": "x", "readings": [{"dt": "2026-01-01T00:00:00", "value": 0.1}] * 1000}],
    )
    with pytest.raises(EacApiError, match="1000-row"):
        await logged_in_client.get_readings("x", datetime(2026, 1, 1), datetime(2026, 1, 2))


async def test_reversed_window(logged_in_client):
    with pytest.raises(ValueError):
        await logged_in_client.get_readings("x", datetime(2026, 1, 2), datetime(2026, 1, 1))


async def test_pagination_preserves_both_folds_and_clips_to_requested_window(
    mock_http, logged_in_client
):
    from datetime import timedelta

    from eac_dso_portal import CYPRUS

    start = datetime(2026, 10, 25, tzinfo=CYPRUS).astimezone(UTC)
    end = datetime(2026, 10, 26, tzinfo=CYPRUS).astimezone(UTC)
    rows = [
        {
            "dt": (start + timedelta(minutes=30 * i))
            .astimezone(CYPRUS)
            .replace(tzinfo=None)
            .isoformat(),
            "value": 0.028,
        }
        for i in range(51)
    ]
    rows.sort(key=lambda r: r["dt"])
    mock_http.post(URL_READINGS, payload=[{"id": "x", "readings": rows}], repeat=True)
    result = await logged_in_client.get_readings(
        "x", start + timedelta(minutes=30), end, chunk_days=1
    )
    assert len(result[0].readings) == 50
    assert len({r.dt for r in result[0].readings}) == 50

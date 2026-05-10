"""End-to-end smoke test against the real EAC DSO portal.

Skipped unless the project root contains a ``.env`` file with valid credentials.
Set ``EAC_USERNAME`` / ``EAC_PASSWORD`` (and optionally ``EAC_BASE_URL``).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp
import pytest

from eac_dso_portal import DEFAULT_BASE_URL, EacClient

_ROOT = Path(__file__).resolve().parent.parent
_DOTENV = _ROOT / ".env"


def _load_dotenv() -> None:
    if not _DOTENV.exists():
        return
    for line in _DOTENV.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()
_USER = os.environ.get("EAC_USERNAME")
_PASS = os.environ.get("EAC_PASSWORD")
_BASE = os.environ.get("EAC_BASE_URL", DEFAULT_BASE_URL)

pytestmark = pytest.mark.skipif(
    not (_USER and _PASS),
    reason="EAC_USERNAME / EAC_PASSWORD not configured (see .env.example)",
)


async def test_full_walk() -> None:
    """Login, list service points, fetch detail and recent readings for the active one."""
    async with aiohttp.ClientSession() as session:
        client = EacClient(_USER, _PASS, session=session, base_url=_BASE)
        await client.login()
        assert client.jwt and client.jwt.count(".") == 2

        user = await client.get_user_details()
        assert user.name

        sps = await client.list_service_points()
        assert sps, "expected at least one service point"
        active = next((s for s in sps if s.active), None)
        assert active, "expected one active service point"

        configs = await client.get_meter_configs(active.id)
        assert configs
        # The latest meter (no removal_date) should expose at least one channel.
        latest = next((c for c in configs if c.removal_date is None), None)
        assert latest and latest.channels

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=14)

        # Default (no mc_id) returns the summary channels only.
        default = await client.get_readings(active.id, start, end)
        assert default

        # Per-channel fetch works for an interval channel too.
        interval_ch = next((ch for ch in latest.channels if ch.interval), None)
        if interval_ch is not None:
            per_channel = await client.get_readings(
                active.id, start, end, mc_id=interval_ch.id
            )
            assert per_channel
            # Interval channels report only `value`, no cumulative `reading`.
            for cr in per_channel:
                for r in cr.readings:
                    assert r.reading is None

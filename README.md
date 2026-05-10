# eac-dso-portal

Async Python client for the **EAC** (Electricity Authority of Cyprus) Distribution Web Portal at `meterreading-dso.eac.com.cy`.

The portal exposes an undocumented JSON API behind a JWT-authenticated session. This package wraps it in a small `aiohttp`-based client with typed dataclasses.

## Install

```bash
pip install eac-dso-portal
```

Requires Python 3.11+.

## Usage

```python
import asyncio
from datetime import datetime, timedelta, timezone
import aiohttp
from eac_dso_portal import EacClient

async def main() -> None:
    async with aiohttp.ClientSession() as session:
        client = EacClient("you@example.com", "password", session=session)
        await client.login()

        for sp in await client.list_service_points():
            if not sp.active:
                continue
            print(sp.id, sp.address)

            # Default channel(s) — typically the daily total kWh.
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=14)
            for cr in await client.get_readings(sp.id, start, end):
                for r in cr.readings:
                    print(f"  {r.dt.isoformat()}  {r.reading} kWh (Δ {r.value})")

asyncio.run(main())
```

## What's in the API

| Method | What it does |
|---|---|
| `login()` | POST `/api/portal/login` → JWT, refreshed automatically on 401 |
| `get_user_details()` | Account holder name and admin flag |
| `list_service_points()` | All service points on the account (active and historical) |
| `get_meter_configs(sp_id)` | All meters ever installed at a service point, with their measurement-channel lists |
| `get_readings(sp_id, start, end, mc_id=None)` | Readings in a date range; `mc_id=None` returns the default summary channels, an explicit `mc_id` returns one channel including 30-minute load-profile data |

All return values are immutable dataclasses with `.raw` fallbacks for fields the wrapper does not yet model.

## Errors

- `EacAuthError` — login was rejected, or token refresh failed
- `EacRateLimitError` — HTTP 429
- `EacApiError` — any other non-2xx (with `.status`, `.message`, `.path`)
- `EacError` — base class for all of the above

## Status & scope

This is a thin wrapper around an undocumented portal API, primarily built to drive a Home Assistant integration ([`ha-eac` on GitHub](https://github.com/santafox/ha-eac)). The endpoint set and field names follow what the portal's React frontend uses today and are subject to change without notice on EAC's side. The package exposes a `.raw` payload on each model so consumers can read fields the wrapper has not yet promoted into typed attributes.

## License

MIT

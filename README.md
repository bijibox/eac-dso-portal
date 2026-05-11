# eac-dso-portal

Async Python client for the EAC (Electricity Authority of Cyprus) Distribution Web Portal at `meterreading-dso.eac.com.cy`.

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

            # Default channels are the daily totals.
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=14)
            for cr in await client.get_readings(sp.id, start, end):
                for r in cr.readings:
                    print(f"  {r.dt.isoformat()}  {r.reading} kWh (delta {r.value})")

asyncio.run(main())
```

## What's in the API

| Method | What it does |
|---|---|
| `login()` | POST `/api/portal/login` and store the JWT. Auto-refreshed on 401. |
| `get_user_details()` | Account holder name and admin flag. |
| `list_service_points()` | All service points on the account, active and historical. |
| `get_meter_configs(sp_id)` | All meters ever installed at a service point, with their measurement-channel lists. |
| `get_readings(sp_id, start, end, mc_id=None, chunk_days=14)` | Readings in a date range. Without `mc_id` you get the default summary channels; pass an explicit `mc_id` for one channel including the 30-minute load profile. Wide ranges are split into back-to-back requests because the portal caps each response at 1000 rows. |

All return values are immutable dataclasses. Each model also carries a `.raw` dict so callers can read fields the wrapper has not yet promoted into typed attributes.

## The 1000-row response cap

The portal silently truncates any `/readings/list` response that would exceed 1000 rows. For a 30-minute load profile that hits the limit after about 21 days. `get_readings` works around this by splitting wide requests into 14-day chunks (configurable via `chunk_days`) and merging the results, dropping duplicates that appear on chunk boundaries. The public signature is unchanged from earlier versions, so callers do not have to do anything special.

## Errors

- `EacAuthError`: login was rejected, or token refresh failed.
- `EacRateLimitError`: HTTP 429 from the portal.
- `EacApiError`: any other non-2xx response. Carries `.status`, `.message`, `.path`.
- `EacError`: base class for all of the above.

## Status and scope

A thin wrapper around an undocumented portal API, built primarily to drive the [`ha-eac`](https://github.com/SantaFox/ha-eac) Home Assistant integration. The endpoint set and field names follow what the portal's React frontend uses today, and the API may change without notice on EAC's side. Every model carries a `.raw` payload so consumers can read fields the wrapper has not yet typed.

## License

MIT

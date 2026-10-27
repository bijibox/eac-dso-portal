# eac-dso-portal

Async Python client for the EAC (Electricity Authority of Cyprus) Distribution Web Portal at `meterreading-dso.eac.com.cy`.

The portal exposes an undocumented JSON API behind a JWT-authenticated session. This package wraps it in a small `aiohttp`-based client with typed dataclasses.

## Install

```bash
pip install "eac-dso-portal @ https://github.com/bijibox/eac-dso-portal/archive/refs/heads/main.zip"
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

All return values are immutable dataclasses. Configuration/account models carry a `.raw` dict. Reading timestamps are timezone-aware UTC; naive meter installation/removal dates can be converted with `as_utc`.

## The 1000-row response cap

The portal silently truncates responses at 1000 rows. `get_readings` splits into at most 14-day chunks and rejects responses reaching that cap rather than accepting truncated history. `chunk_days` must be 1–14.

Requests are padded with whole Cyprus days on both sides. Live testing found that the portal rounds request bounds to dates and returns summer pages starting at 01:00; merely adjoining timestamp windows is unsafe. Overlapping results are merged by UTC instant and finally clipped to the caller's inclusive `[start, end]` timestamp range.

## Timestamp contract (0.3.0)

- `Reading.dt` is aware UTC. Naive response timestamps mean **Asia/Nicosia**, not the host timezone or UTC. Explicit offsets take precedence.
- Profile `dt` denotes the **end** of its half-hour. Verified against the official `/api/portal/report/scalarinterval/xlsx` one-day report: 00:30 through next-day 00:00 (48 rows on a normal winter day). Subtract 30 minutes **in UTC** to obtain interval starts.
- Both occurrences of autumn 03:00/03:30 are retained, including equal values. Occurrence order in ascending/descending responses selects folds before UTC sorting/deduplication. A single ambiguous wall time, an impossible spring time, conflicting records at an explicit instant, or an invalid/missing value raises `EacApiError`; it is never silently converted to zero or dropped.
- Query arguments without timezone retain the earlier **naive-as-UTC** API contract. Prefer aware dates. Meter configuration dates remain naive portal wall times for compatibility; use the exported `as_utc` helper.
- `value` is interval energy in **kWh**, not kW. Use decimal arithmetic when aggregating. `reading` is the optional cumulative register and must not be added as the first interval's consumption.
- Portal gaps are preserved; no interpolation is performed. Full and overlapping queries can be repeated safely. Consumers must replace corrected values and recompute subsequent cumulative sums.

## Errors

- `EacAuthError`: login was rejected, or token refresh failed.
- `EacRateLimitError`: HTTP 429 from the portal.
- `EacApiError`: any other non-2xx response. Carries `.status`, `.message`, `.path`.
- `EacError`: base class for all of the above.

## Status and scope

A thin wrapper around an undocumented portal API, built primarily to drive the [`ha-eac`](https://github.com/bijibox/ha-eac) Home Assistant integration. The endpoint set and field names follow what the portal's React frontend uses today, and the API may change without notice on EAC's side. Every model carries a `.raw` payload so consumers can read fields the wrapper has not yet typed.

## License

MIT

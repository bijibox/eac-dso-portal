"""Portal wall-clock handling, independent of the host's timezone."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from .exceptions import EacApiError
from .models import Reading

CYPRUS = ZoneInfo("Asia/Nicosia")


def utc_candidates(dt: datetime) -> list[datetime]:
    """Return real instants for a local time (zero in a spring DST gap)."""
    if dt.tzinfo is not None:
        return [dt.astimezone(UTC)]
    return sorted(
        {
            candidate
            for fold in (0, 1)
            if (candidate := dt.replace(tzinfo=CYPRUS, fold=fold).astimezone(UTC))
            .astimezone(CYPRUS)
            .replace(tzinfo=None)
            == dt
        }
    )


def as_utc(dt: datetime) -> datetime:
    """Interpret naive portal dates in Cyprus; reject ambiguous dates."""
    candidates = utc_candidates(dt)
    if len(candidates) != 1:
        raise EacApiError(200, f"Ambiguous or nonexistent Cyprus time: {dt}", "readings/time")
    return candidates[0]


def normalize_readings(readings: tuple[Reading, ...]) -> tuple[Reading, ...]:
    """Resolve repeated autumn labels before sorting or deduplicating.

    Two occurrences of an ambiguous label are distinct physical intervals,
    even with equal values. The API sequence must be chronological (either
    direction); a lone ambiguous label cannot be safely disambiguated.
    Explicit offsets always take precedence.
    """
    candidates = [utc_candidates(r.dt) for r in readings]
    ordinary = [cs[0] for cs in candidates if len(cs) == 1]
    descending = len(ordinary) > 1 and ordinary[0] > ordinary[-1]
    counts = Counter(r.dt for r, cs in zip(readings, candidates, strict=True) if len(cs) == 2)
    seen: dict[datetime, int] = defaultdict(int)
    result: dict[datetime, Reading] = {}
    for r, cs in zip(readings, candidates, strict=True):
        if not cs or (len(cs) == 2 and counts[r.dt] != 2):
            raise EacApiError(200, f"Unresolvable Cyprus timestamp: {r.dt}", "readings/time")
        if len(cs) == 2:
            occurrence = seen[r.dt]
            dt = cs[1 - occurrence if descending else occurrence]
            seen[r.dt] += 1
        else:
            dt = cs[0]
        if dt in result and result[dt] != replace(r, dt=dt):
            raise EacApiError(200, f"Conflicting readings at {dt}", "readings/time")
        result[dt] = replace(r, dt=dt)
    return tuple(result[dt] for dt in sorted(result))

"""In-process TTL cache for weather windows.

Two tiers, and the second one is the point:

* the *fresh* tier is a normal TTL map keyed by geohash + rounded hour. It exists
  so that six requests for the same city in the same minute cost one upstream call.
* the *last-known-good* tier never expires. When Open-Meteo is down we would rather
  serve a two-hour-old window flagged ``stale=True`` than serve nothing. A playlist
  built from slightly old air is still a better answer than an error page, and the
  derivative dimensions (which is all BAROGROOVE actually cares about) decay slowly.

Deliberately in-process: the weather window for one geohash-5 cell is a few kB and
the whole product is single-node. Swapping this for Redis later means reimplementing
``get``/``set``/``last_known_good`` and nothing else.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Final

from ..contracts import Coordinates, WeatherWindow

__all__ = ["CacheStats", "WeatherWindowCache", "cache_key"]

_DEFAULT_TTL_S: Final[int] = 900
_GEOHASH_PRECISION: Final[int] = 5


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """Naive datetimes are assumed UTC; everything else is converted."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def cache_key(coords: Coordinates, at: datetime | None = None) -> str:
    """``<geohash5>@<UTC hour>``.

    Geohash precision 5 is ~4.9 km, which is well inside the resolution of any
    forecast model we consume — two users on opposite sides of Brussels genuinely
    share weather. Hour rounding matches Open-Meteo's own hourly grid, so a finer
    key would only ever cause misses that return identical data.
    """
    moment = _as_utc(at or _utcnow()).replace(minute=0, second=0, microsecond=0)
    return f"{coords.geohash(_GEOHASH_PRECISION)}@{moment.isoformat()}"


@dataclass(frozen=True)
class CacheStats:
    hits: int = 0
    misses: int = 0
    stale_hits: int = 0
    expiries: int = 0
    entries: int = 0
    last_known_good_entries: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0

    def as_dict(self) -> dict[str, float | int]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "stale_hits": self.stale_hits,
            "expiries": self.expiries,
            "entries": self.entries,
            "last_known_good_entries": self.last_known_good_entries,
            "hit_rate": round(self.hit_rate, 4),
        }


@dataclass
class _Entry:
    window: WeatherWindow
    stored_at: datetime
    key: str

    def age_s(self, now: datetime) -> float:
        return (now - self.stored_at).total_seconds()


@dataclass
class _Counters:
    hits: int = 0
    misses: int = 0
    stale_hits: int = 0
    expiries: int = 0


class WeatherWindowCache:
    """Asyncio-safe two-tier cache.

    All public methods are coroutines guarded by a single lock. Contention is
    irrelevant at our scale and a single lock removes every check-then-act race
    between the TTL tier and the last-known-good tier.
    """

    def __init__(self, ttl_s: int = _DEFAULT_TTL_S, *, max_entries: int = 256) -> None:
        self._ttl = timedelta(seconds=max(1, int(ttl_s)))
        self._max_entries = max(1, int(max_entries))
        self._fresh: dict[str, _Entry] = {}
        self._last_good: dict[str, _Entry] = {}
        self._counters = _Counters()
        self._lock = asyncio.Lock()

    # -- reads ---------------------------------------------------------------

    async def get(self, coords: Coordinates, at: datetime | None = None) -> WeatherWindow | None:
        """Return a window only if it is inside the TTL. Never returns stale data."""
        key = cache_key(coords, at)
        now = _utcnow()
        async with self._lock:
            entry = self._fresh.get(key)
            if entry is None:
                self._counters.misses += 1
                return None
            if entry.age_s(now) > self._ttl.total_seconds():
                # Expired from the fresh tier, but it stays in the LKG tier — an
                # expired window is worthless as "current" and priceless as "fallback".
                del self._fresh[key]
                self._counters.expiries += 1
                self._counters.misses += 1
                return None
            self._counters.hits += 1
            return entry.window

    async def last_known_good(self, coords: Coordinates) -> WeatherWindow | None:
        """The most recent successfully fetched window for this cell, at any age.

        Keyed by geohash alone: when upstream is down we do not care which hour the
        data was cut for, only that it is real observed air from roughly here.
        """
        key = coords.geohash(_GEOHASH_PRECISION)
        async with self._lock:
            entry = self._last_good.get(key)
            if entry is None:
                return None
            self._counters.stale_hits += 1
            return entry.window

    # -- writes --------------------------------------------------------------

    async def set(
        self,
        coords: Coordinates,
        window: WeatherWindow,
        at: datetime | None = None,
    ) -> None:
        key = cache_key(coords, at)
        geo = coords.geohash(_GEOHASH_PRECISION)
        now = _utcnow()
        entry = _Entry(window=window, stored_at=now, key=key)
        async with self._lock:
            self._fresh[key] = entry
            # Only genuinely fresh upstream data is promoted to last-known-good;
            # re-storing an already-stale window would let a degraded answer
            # calcify into the permanent fallback.
            if not window.stale:
                self._last_good[geo] = entry
            self._evict_locked()

    async def invalidate(self, coords: Coordinates, at: datetime | None = None) -> None:
        key = cache_key(coords, at)
        async with self._lock:
            self._fresh.pop(key, None)

    async def clear(self, *, include_last_known_good: bool = False) -> None:
        async with self._lock:
            self._fresh.clear()
            if include_last_known_good:
                self._last_good.clear()
            self._counters = _Counters()

    # -- introspection -------------------------------------------------------

    def stats(self) -> CacheStats:
        """Synchronous by design: metrics scraping should never await a lock."""
        return CacheStats(
            hits=self._counters.hits,
            misses=self._counters.misses,
            stale_hits=self._counters.stale_hits,
            expiries=self._counters.expiries,
            entries=len(self._fresh),
            last_known_good_entries=len(self._last_good),
        )

    # -- internals -----------------------------------------------------------

    def _evict_locked(self) -> None:
        """Drop the oldest fresh entries once the map grows past the bound.

        The LKG tier is bounded by the same limit but evicted separately, because
        losing a fallback is a worse failure than losing a fresh entry.
        """
        if len(self._fresh) > self._max_entries:
            for key in sorted(self._fresh, key=lambda k: self._fresh[k].stored_at)[
                : len(self._fresh) - self._max_entries
            ]:
                del self._fresh[key]
        if len(self._last_good) > self._max_entries:
            for key in sorted(self._last_good, key=lambda k: self._last_good[k].stored_at)[
                : len(self._last_good) - self._max_entries
            ]:
                del self._last_good[key]


_shared_cache: WeatherWindowCache | None = None
_shared_cache_lock = asyncio.Lock()


async def get_shared_cache(ttl_s: int = _DEFAULT_TTL_S) -> WeatherWindowCache:
    """Process-wide cache, for callers that are not wired through the container."""
    global _shared_cache
    if _shared_cache is None:
        async with _shared_cache_lock:
            if _shared_cache is None:
                _shared_cache = WeatherWindowCache(ttl_s=ttl_s)
    return _shared_cache

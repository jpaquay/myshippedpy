"""Lazy service container.

This is the integration seam. Each subsystem (weather, oracle, sinks, forge,
almanac) is resolved on first use through a function that imports the concrete
implementation *inside* the call. Two reasons:

1. Import cost stays off the cold-start path for anything a request never uses.
2. The app boots even when an optional subsystem is missing or broken — you
   get a degraded capability instead of a stack trace at import time. This is
   what lets ``uvicorn app:app`` come up with a completely empty environment.

Nothing here holds credentials; it holds *factories*.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, TypeVar

from .config import Settings, get_settings
from .contracts import AcousticOracle, AlmanacStore, PlaylistSink, WeatherSource

log = logging.getLogger("barogroove.container")

T = TypeVar("T")


class Container:
    """Holds one instance of each subsystem, built on demand."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._cache: dict[str, Any] = {}
        self._failed: dict[str, str] = {}

    # -- generic memoised resolution ---------------------------------------

    def _resolve(self, key: str, factory: Callable[[], T], fallback: Callable[[], T]) -> T:
        if key in self._cache:
            return self._cache[key]
        try:
            value = factory()
        except Exception as exc:
            log.warning("subsystem %r unavailable (%s); using fallback", key, exc)
            self._failed[key] = str(exc)
            value = fallback()
        self._cache[key] = value
        return value

    @property
    def failures(self) -> dict[str, str]:
        """Which subsystems fell back, and why. Shown at ``/api/health``."""
        return dict(self._failed)

    # -- weather ------------------------------------------------------------

    def weather(self) -> WeatherSource:
        def real() -> WeatherSource:
            if self.settings.weather_offline:
                from .sky.fixtures import FixtureWeatherSource

                return FixtureWeatherSource()
            from .sky.google_weather import GoogleWeatherSource
            from .sky.open_meteo import OpenMeteoSource

            om = OpenMeteoSource(settings=self.settings)
            return GoogleWeatherSource(settings=self.settings, fallback=om)

        def stub() -> WeatherSource:
            from .sky.fixtures import FixtureWeatherSource

            return FixtureWeatherSource()

        return self._resolve("weather", real, stub)

    # -- acoustic oracle ----------------------------------------------------

    def oracle(self) -> AcousticOracle:
        def real() -> AcousticOracle:
            if not self.settings.has_lastfm:
                from .lastfm.offline import OfflineOracle

                return OfflineOracle()
            from .lastfm.oracle import LastfmOracle

            return LastfmOracle(self.settings)

        def stub() -> AcousticOracle:
            from .lastfm.offline import OfflineOracle

            return OfflineOracle()

        return self._resolve("oracle", real, stub)

    # -- playlist sinks -----------------------------------------------------

    def sinks(self) -> list[PlaylistSink]:
        """Ordered by preference. The forge walks this list until one works."""

        def real() -> list[PlaylistSink]:
            from .sinks.m3u import M3USink

            out: list[PlaylistSink] = []
            if self.settings.has_spotify:
                from .routes.pairing import get_token_vault
                from .sinks.spotify import SpotifySink

                out.append(SpotifySink(settings=self.settings, vault=get_token_vault()))
            out.append(M3USink())
            return out

        def stub() -> list[PlaylistSink]:
            from .sinks.m3u import M3USink

            return [M3USink()]

        return self._resolve("sinks", real, stub)

    # -- almanac ------------------------------------------------------------

    def almanac(self) -> AlmanacStore:
        def real() -> AlmanacStore:
            if not self.settings.has_firestore:
                raise RuntimeError("no Firestore project configured")
            from .almanac.firestore_store import FirestoreAlmanac

            return FirestoreAlmanac(self.settings)

        def stub() -> AlmanacStore:
            from .almanac.memory_store import MemoryAlmanac

            return MemoryAlmanac()

        return self._resolve("almanac", real, stub)

    # -- forge --------------------------------------------------------------

    def forge(self) -> Any:
        from .forge.engine import PlaylistForge

        if "forge" not in self._cache:
            self._cache["forge"] = PlaylistForge(
                settings=self.settings,
                weather=self.weather(),
                oracle=self.oracle(),
                sinks=self.sinks(),
                almanac=self.almanac(),
            )
        return self._cache["forge"]

    # -- telemetry ----------------------------------------------------------

    def telemetry(self) -> Any:
        from .telemetry.store import get_telemetry_store

        if "telemetry" not in self._cache:
            self._cache["telemetry"] = get_telemetry_store(self.settings)
        return self._cache["telemetry"]


_CONTAINER: Container | None = None


def get_container() -> Container:
    global _CONTAINER
    if _CONTAINER is None:
        _CONTAINER = Container()
    return _CONTAINER


def reset_container() -> None:
    """Tests call this between cases."""
    global _CONTAINER
    _CONTAINER = None
    try:
        from .telemetry.store import reset_telemetry_store

        reset_telemetry_store()
    except Exception:
        pass

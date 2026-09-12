"""Domain errors and the degradation ledger.

BAROGROOVE's operating principle: *something* always comes back. If the sky is
unreachable we serve the last known good one; if Last.fm is down we run
theme-only; if Spotify is unpaired we hand you an M3U. What we must never do
is silently pretend everything was fine — every fallback appends a line to a
:class:`DegradationLedger`, and those lines surface in the rationale card.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class BarogrooveError(Exception):
    """Base class for anything we raise on purpose."""


class ConfigurationError(BarogrooveError):
    """A required setting is missing and there is no sane default."""


class WeatherUnavailable(BarogrooveError):
    """Open-Meteo failed and we have no cached window to fall back to."""


class OracleUnavailable(BarogrooveError):
    """The acoustic oracle (Last.fm) is unusable for this request."""


class PairingError(BarogrooveError):
    """OAuth / web-auth pairing failed. Message is safe to show a user."""


class SinkError(BarogrooveError):
    """A playlist sink failed in a way the caller cannot route around."""


class ThemeNotFound(BarogrooveError):
    """Unknown theme id."""


@dataclass(slots=True)
class DegradationLedger:
    """Collects 'we had to improvise' notes during a single forge."""

    entries: list[str] = field(default_factory=list)

    def note(self, subsystem: str, detail: str) -> None:
        line = f"{subsystem}: {detail}"
        if line not in self.entries:
            self.entries.append(line)

    def extend(self, other: "DegradationLedger | list[str]") -> None:
        items = other.entries if isinstance(other, DegradationLedger) else other
        for item in items:
            if item not in self.entries:
                self.entries.append(item)

    @property
    def clean(self) -> bool:
        return not self.entries

    def as_list(self) -> list[str]:
        return list(self.entries)

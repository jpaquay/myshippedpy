"""A thin, typed async wrapper over the Last.fm 2.0 REST API.

Design notes, all of them consequences of how Last.fm actually behaves rather
than how it documents itself:

1.  **HTTP 200 is not success.** Last.fm answers malformed, unauthorised and
    rate-limited requests with ``200 OK`` and a body of the shape
    ``{"error": 6, "message": "..."}``. Every response therefore goes through
    :func:`_raise_for_lastfm_error` before anything else touches it.
2.  **The JSON shape is unstable.** A container that holds many items is a
    list; the same container holding exactly one item is a bare object; and
    holding zero items it is either absent, an empty string, or an empty
    dict. :func:`as_list` collapses all four cases.
3.  **Numbers are strings.** ``playcount``, ``listeners``, ``duration``,
    ``match`` and friends arrive as strings, occasionally as ``""``,
    occasionally as ``"FIXME"``. :func:`as_int` / :func:`as_float` coerce or
    return ``None``; they never raise.
4.  **Metadata hides under ``@attr``.** Paging info, the resolved username and
    the ``nowplaying`` flag all live there.

All network I/O goes through ``backend/app/http.py`` so that timeouts, bounded
exponential retry with jitter and ``Retry-After`` handling are applied
uniformly. This module never constructs an ``httpx`` client of its own.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Final, Iterable, Literal, Sequence, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings, get_settings
from ..errors import OracleUnavailable
from ..http import UpstreamError, get_json

__all__ = [
    "LastfmClient",
    "LastfmPeriod",
    "LASTFM_PERIODS",
    "as_list",
    "as_int",
    "as_float",
    "as_str",
    "first_image",
    "LastfmArtist",
    "LastfmTrack",
    "LastfmTag",
    "gather_bounded",
]

SERVICE: Final[str] = "lastfm"

#: The ``period`` values ``user.getTopArtists`` / ``user.getTopTracks`` accept.
LastfmPeriod = Literal["overall", "7day", "1month", "3month", "6month", "12month"]
LASTFM_PERIODS: Final[tuple[str, ...]] = (
    "overall",
    "7day",
    "1month",
    "3month",
    "6month",
    "12month",
)

#: Error codes worth retrying at the application layer. 8 is "operation
#: failed", 11 is "service offline", 16 is "temporary error", 29 is the rate
#: limiter. The rest are our fault and retrying is just rudeness.
RETRYABLE_ERROR_CODES: Final[frozenset[int]] = frozenset({8, 11, 16, 29})

#: Codes that mean "this key/session is finished"; surfacing them as
#: retryable would loop forever.
FATAL_ERROR_CODES: Final[frozenset[int]] = frozenset({4, 9, 10, 26})

_T = TypeVar("_T")


# --------------------------------------------------------------------------
# normalisers
# --------------------------------------------------------------------------
def as_list(value: Any) -> list[Any]:
    """Always give me a list.

    Last.fm returns a list for N>1, a bare object for N==1, and for N==0 any
    of ``None``, ``""``, ``[]`` or ``{}``. Callers should not have to care.

    >>> as_list({"name": "Neu!"})
    [{'name': 'Neu!'}]
    >>> as_list(None)
    []
    >>> as_list("")
    []
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [v for v in value if v is not None and v != ""]
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        # The empty string is Last.fm's other way of spelling "no results".
        return [] if not value.strip() else [value]
    if isinstance(value, dict):
        return [] if not value else [value]
    return [value]


def as_int(value: Any) -> int | None:
    """Coerce to ``int`` or ``None``. Never raises.

    Handles ``"1346"``, ``1346``, ``1346.0``, ``""``, ``None`` and the
    occasional ``{"#text": "1346"}``.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, dict):
        return as_int(value.get("#text"))
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            try:
                return int(float(text))
            except ValueError:
                return None
    return None


def as_float(value: Any) -> float | None:
    """Coerce to ``float`` or ``None``. Never raises.

    ``match`` on ``artist.getSimilar`` is documented as 0..1 but has been
    observed as ``"1"``, ``"0.892"`` and, historically, as a 0..100 integer.
    Scaling is the caller's problem; parsing is ours.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        return as_float(value.get("#text"))
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def as_str(value: Any) -> str | None:
    """Coerce to a non-empty ``str`` or ``None``.

    Last.fm uses ``""`` for "no mbid" rather than omitting the key, and wraps
    some scalars as ``{"#text": ...}``.
    """
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, dict):
        return as_str(value.get("#text"))
    if isinstance(value, (int, float)):
        return str(value)
    return None


def first_image(value: Any, *, prefer: str = "extralarge") -> str | None:
    """Pull a usable URL out of Last.fm's ``image`` array.

    The array is ``[{"#text": url, "size": "small"|...}]`` and the URLs are
    frequently the empty string or the notorious star placeholder, which we
    treat as absent.
    """
    entries = as_list(value)
    by_size: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        url = as_str(entry.get("#text"))
        if not url or "2a96cbd8b46e442fc41c2b86b821562f" in url:
            continue  # Last.fm's grey placeholder star.
        by_size[str(entry.get("size") or "")] = url
    if not by_size:
        return None
    for size in (prefer, "extralarge", "large", "medium", "small", ""):
        if size in by_size:
            return by_size[size]
    return next(iter(by_size.values()))


def _raise_for_lastfm_error(payload: Any, *, method: str) -> dict[str, Any]:
    """Turn a 200-with-error-body into :class:`OracleUnavailable`.

    This is the single most important function in the client. Without it a
    quota breach looks exactly like an empty result set and the oracle
    silently degrades to "this user has no taste".
    """
    if payload is None:
        raise OracleUnavailable(f"last.fm {method}: empty response body")
    if isinstance(payload, list):
        # Never observed in the wild, but a list cannot carry an error and
        # cannot be indexed by key either, so normalise it away here.
        raise OracleUnavailable(f"last.fm {method}: unexpected list payload")
    if not isinstance(payload, dict):
        raise OracleUnavailable(f"last.fm {method}: unexpected payload type {type(payload).__name__}")

    if "error" in payload:
        code = as_int(payload.get("error")) or 0
        message = as_str(payload.get("message")) or "unknown error"
        retryable = code in RETRYABLE_ERROR_CODES
        detail = f"last.fm {method} failed (error {code}): {message}"
        if code in FATAL_ERROR_CODES:
            detail += " [credentials or key state — not retryable]"
        raise OracleUnavailable(detail) from UpstreamError(
            SERVICE,
            message,
            status=200,
            retryable=retryable,
        )
    return payload


async def gather_bounded(
    factories: Sequence[Callable[[], Awaitable[_T]]],
    *,
    limit: int = 6,
) -> list[_T | BaseException]:
    """Run coroutine factories with bounded parallelism.

    Graph traversal fans out fast: two hops off twenty seed artists is a few
    hundred calls. Last.fm's documented answer to that is error 29. Six in
    flight is comfortably polite and still an order of magnitude faster than
    serial.

    Takes *factories* rather than coroutines so nothing is scheduled — and so
    nothing warns about a never-awaited coroutine — if the caller bails early.
    Returns results positionally, with exceptions in place rather than raised,
    because partial traversal is still a useful traversal.
    """
    if not factories:
        return []
    semaphore = asyncio.Semaphore(max(1, limit))

    async def _run(factory: Callable[[], Awaitable[_T]]) -> _T:
        async with semaphore:
            return await factory()

    return list(await asyncio.gather(*(_run(f) for f in factories), return_exceptions=True))


# --------------------------------------------------------------------------
# lightweight response models
# --------------------------------------------------------------------------
class LastfmArtist(BaseModel):
    """An artist as Last.fm describes it, already coerced."""

    model_config = ConfigDict(frozen=True)

    name: str
    mbid: str | None = None
    url: str | None = None
    playcount: int | None = None
    listeners: int | None = None
    #: 0..1 similarity, only present on ``artist.getSimilar`` responses.
    match: float | None = None
    image: str | None = None

    @classmethod
    def parse(cls, raw: Any) -> "LastfmArtist | None":
        if not isinstance(raw, dict):
            return None
        # ``user.getRecentTracks`` nests the artist as {"#text": name, "mbid": ...}.
        name = as_str(raw.get("name")) or as_str(raw.get("#text"))
        if not name:
            return None
        match = as_float(raw.get("match"))
        if match is not None and match > 1.0:
            match = match / 100.0  # older responses used 0..100
        return cls(
            name=name,
            mbid=as_str(raw.get("mbid")),
            url=as_str(raw.get("url")),
            playcount=as_int(raw.get("playcount")),
            listeners=as_int(raw.get("listeners")),
            match=match,
            image=first_image(raw.get("image")),
        )


class LastfmTrack(BaseModel):
    """A track as Last.fm describes it, already coerced."""

    model_config = ConfigDict(frozen=True)

    name: str
    artist: str
    mbid: str | None = None
    url: str | None = None
    album: str | None = None
    duration_ms: int | None = None
    playcount: int | None = None
    listeners: int | None = None
    match: float | None = None
    image: str | None = None
    now_playing: bool = False

    @classmethod
    def parse(cls, raw: Any) -> "LastfmTrack | None":
        if not isinstance(raw, dict):
            return None
        name = as_str(raw.get("name"))
        artist_raw = raw.get("artist")
        artist = (
            as_str(artist_raw)
            if isinstance(artist_raw, str)
            else (as_str((artist_raw or {}).get("name")) or as_str((artist_raw or {}).get("#text")))
            if isinstance(artist_raw, dict)
            else None
        )
        if not name or not artist:
            return None

        # ``duration`` is seconds on user.* and tag.*, but milliseconds on
        # track.getInfo. Anything over 10^4 is already milliseconds; a
        # ten-thousand-second track does not exist outside of drone comps, and
        # if it does we will merely mis-scale one obscure record.
        duration = as_int(raw.get("duration"))
        duration_ms: int | None = None
        if duration is not None and duration > 0:
            duration_ms = duration if duration > 10_000 else duration * 1000

        match = as_float(raw.get("match"))
        if match is not None and match > 1.0:
            match = match / 100.0

        attr = raw.get("@attr") if isinstance(raw.get("@attr"), dict) else {}
        album_raw = raw.get("album")
        album = as_str(album_raw.get("#text")) if isinstance(album_raw, dict) else as_str(album_raw)

        return cls(
            name=name,
            artist=artist,
            mbid=as_str(raw.get("mbid")),
            url=as_str(raw.get("url")),
            album=album,
            duration_ms=duration_ms,
            playcount=as_int(raw.get("playcount")),
            listeners=as_int(raw.get("listeners")),
            match=match,
            image=first_image(raw.get("image")),
            now_playing=str((attr or {}).get("nowplaying", "")).lower() == "true",
        )


class LastfmTag(BaseModel):
    """A community tag plus its raw weight.

    ``artist.getTopTags`` / ``track.getTopTags`` return ``count`` on a 0..100
    scale where 100 means "the top tag on this item", not "everybody agrees".
    ``tag.getTopTracks`` and ``user.getTopTags`` use raw counts instead. We
    keep the number as given and let the lexicon normalise.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    count: float = 0.0
    url: str | None = None

    @classmethod
    def parse(cls, raw: Any) -> "LastfmTag | None":
        if isinstance(raw, str):
            name = as_str(raw)
            return cls(name=name) if name else None
        if not isinstance(raw, dict):
            return None
        name = as_str(raw.get("name"))
        if not name:
            return None
        return cls(
            name=name,
            count=as_float(raw.get("count")) or 0.0,
            url=as_str(raw.get("url")),
        )


class LastfmPage(BaseModel):
    """Paging metadata lifted out of ``@attr``."""

    model_config = ConfigDict(frozen=True)

    page: int = 1
    per_page: int = 0
    total: int = 0
    total_pages: int = 1
    user: str | None = None

    @classmethod
    def parse(cls, container: Any) -> "LastfmPage":
        attr = container.get("@attr") if isinstance(container, dict) else None
        if not isinstance(attr, dict):
            return cls()
        return cls(
            page=as_int(attr.get("page")) or 1,
            per_page=as_int(attr.get("perPage")) or 0,
            total=as_int(attr.get("total")) or 0,
            total_pages=as_int(attr.get("totalPages")) or 1,
            user=as_str(attr.get("user")),
        )


class LastfmArtistPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    artists: list[LastfmArtist] = Field(default_factory=list)
    page: LastfmPage = Field(default_factory=LastfmPage)


class LastfmTrackPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    tracks: list[LastfmTrack] = Field(default_factory=list)
    page: LastfmPage = Field(default_factory=LastfmPage)


# --------------------------------------------------------------------------
# client
# --------------------------------------------------------------------------
class LastfmClient:
    """Typed async access to the handful of Last.fm methods we actually use.

    Stateless apart from the settings object and a semaphore, so a single
    instance can be shared across requests.
    """

    service: Final[str] = SERVICE

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        concurrency: int = 6,
    ) -> None:
        self._settings = settings or get_settings()
        self._concurrency = max(1, concurrency)
        self._semaphore = asyncio.Semaphore(self._concurrency)

    # -- plumbing ---------------------------------------------------------
    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def enabled(self) -> bool:
        return bool(getattr(self._settings, "has_lastfm", False))

    @property
    def concurrency(self) -> int:
        return self._concurrency

    def _params(self, method: str, **kwargs: Any) -> dict[str, str]:
        """Build a query string. ``format=json`` and ``api_key`` always ride along."""
        params: dict[str, str] = {
            "method": method,
            "api_key": self._settings.lastfm_api_key,
            "format": "json",
        }
        for key, value in kwargs.items():
            if value is None:
                continue
            if isinstance(value, bool):
                params[key] = "1" if value else "0"
            else:
                params[key] = str(value)
        return params

    async def call(self, method: str, **kwargs: Any) -> dict[str, Any]:
        """Issue one Last.fm call and hand back a validated dict payload.

        Wraps :func:`get_json` so transport failures become
        :class:`OracleUnavailable` too — callers of this module should only
        ever have to catch one exception type.
        """
        if not self._settings.lastfm_api_key:
            raise OracleUnavailable("last.fm: no API key configured")

        params = self._params(method, **kwargs)
        try:
            async with self._semaphore:
                payload = await get_json(
                    self._settings.lastfm_base,
                    service=SERVICE,
                    params=params,
                    settings=self._settings,
                )
        except UpstreamError as exc:
            raise OracleUnavailable(f"last.fm {method}: {exc}") from exc
        return _raise_for_lastfm_error(payload, method=method)

    @staticmethod
    def _period(period: str | None) -> str | None:
        """Reject nonsense periods loudly rather than letting Last.fm guess."""
        if period is None:
            return None
        value = period.strip()
        if value not in LASTFM_PERIODS:
            raise ValueError(f"invalid Last.fm period {period!r}; expected one of {LASTFM_PERIODS}")
        return value

    @staticmethod
    def _artists(container: Any, key: str) -> LastfmArtistPage:
        body = container.get(key) if isinstance(container, dict) else None
        raw = as_list((body or {}).get("artist") if isinstance(body, dict) else body)
        parsed = [LastfmArtist.parse(item) for item in raw]
        return LastfmArtistPage(
            artists=[a for a in parsed if a is not None],
            page=LastfmPage.parse(body),
        )

    @staticmethod
    def _tracks(container: Any, key: str, *, item_key: str = "track") -> LastfmTrackPage:
        body = container.get(key) if isinstance(container, dict) else None
        raw = as_list((body or {}).get(item_key) if isinstance(body, dict) else body)
        parsed = [LastfmTrack.parse(item) for item in raw]
        return LastfmTrackPage(
            tracks=[t for t in parsed if t is not None],
            page=LastfmPage.parse(body),
        )

    @staticmethod
    def _tags(container: Any, key: str) -> list[LastfmTag]:
        body = container.get(key) if isinstance(container, dict) else None
        raw = as_list((body or {}).get("tag") if isinstance(body, dict) else body)
        parsed = [LastfmTag.parse(item) for item in raw]
        return [t for t in parsed if t is not None]

    # -- user.* -----------------------------------------------------------
    async def user_get_top_artists(
        self,
        user: str,
        *,
        period: LastfmPeriod | str = "overall",
        limit: int = 50,
        page: int = 1,
    ) -> LastfmArtistPage:
        """``user.getTopArtists`` -> ``{"topartists": {"artist": [...]}}``."""
        payload = await self.call(
            "user.getTopArtists",
            user=user,
            period=self._period(period),
            limit=limit,
            page=page,
        )
        return self._artists(payload, "topartists")

    async def user_get_top_tracks(
        self,
        user: str,
        *,
        period: LastfmPeriod | str = "overall",
        limit: int = 50,
        page: int = 1,
    ) -> LastfmTrackPage:
        """``user.getTopTracks`` -> ``{"toptracks": {"track": [...]}}``."""
        payload = await self.call(
            "user.getTopTracks",
            user=user,
            period=self._period(period),
            limit=limit,
            page=page,
        )
        return self._tracks(payload, "toptracks")

    async def user_get_recent_tracks(
        self,
        user: str,
        *,
        limit: int = 50,
        page: int = 1,
        from_ts: int | None = None,
        to_ts: int | None = None,
        extended: bool = False,
    ) -> LastfmTrackPage:
        """``user.getRecentTracks`` -> ``{"recenttracks": {"track": [...]}}``.

        The first item may be the currently-playing track, flagged via
        ``@attr.nowplaying``; it has no ``date`` and should not be counted as
        a scrobble. We surface the flag and leave the policy to callers.
        """
        payload = await self.call(
            "user.getRecentTracks",
            user=user,
            limit=limit,
            page=page,
            **{"from": from_ts, "to": to_ts},
            extended=extended,
        )
        return self._tracks(payload, "recenttracks")

    async def user_get_loved_tracks(
        self,
        user: str,
        *,
        limit: int = 50,
        page: int = 1,
    ) -> LastfmTrackPage:
        """``user.getLovedTracks`` -> ``{"lovedtracks": {"track": [...]}}``.

        Loved tracks are the highest-signal thing a Last.fm account exposes:
        an explicit, deliberate act rather than an accident of what was on in
        the background.
        """
        payload = await self.call("user.getLovedTracks", user=user, limit=limit, page=page)
        return self._tracks(payload, "lovedtracks")

    async def user_get_top_tags(self, user: str, *, limit: int = 50) -> list[LastfmTag]:
        """``user.getTopTags`` -> ``{"toptags": {"tag": [...]}}``. Usually sparse."""
        payload = await self.call("user.getTopTags", user=user, limit=limit)
        return self._tags(payload, "toptags")

    # -- artist.* ---------------------------------------------------------
    async def artist_get_similar(
        self,
        artist: str,
        *,
        limit: int = 30,
        mbid: str | None = None,
        autocorrect: bool = True,
    ) -> list[LastfmArtist]:
        """``artist.getSimilar`` -> ``{"similarartists": {"artist": [...]}}``.

        Each entry carries ``match`` in 0..1. This is the edge set of the
        taste graph and the direct replacement for
        ``/artists/{id}/related-artists``.
        """
        payload = await self.call(
            "artist.getSimilar",
            artist=artist,
            mbid=mbid,
            limit=limit,
            autocorrect=autocorrect,
        )
        return self._artists(payload, "similarartists").artists

    async def artist_get_top_tags(
        self,
        artist: str,
        *,
        mbid: str | None = None,
        autocorrect: bool = True,
    ) -> list[LastfmTag]:
        """``artist.getTopTags`` -> ``{"toptags": {"tag": [...]}}``, ``count`` 0..100."""
        payload = await self.call(
            "artist.getTopTags",
            artist=artist,
            mbid=mbid,
            autocorrect=autocorrect,
        )
        return self._tags(payload, "toptags")

    async def artist_get_top_tracks(
        self,
        artist: str,
        *,
        limit: int = 20,
        mbid: str | None = None,
        autocorrect: bool = True,
    ) -> list[LastfmTrack]:
        """``artist.getTopTracks`` -> ``{"toptracks": {"track": [...]}}``."""
        payload = await self.call(
            "artist.getTopTracks",
            artist=artist,
            mbid=mbid,
            limit=limit,
            autocorrect=autocorrect,
        )
        return self._tracks(payload, "toptracks").tracks

    # -- track.* ----------------------------------------------------------
    async def track_get_similar(
        self,
        artist: str,
        track: str,
        *,
        limit: int = 30,
        mbid: str | None = None,
        autocorrect: bool = True,
    ) -> list[LastfmTrack]:
        """``track.getSimilar`` -> ``{"similartracks": {"track": [...]}}``.

        Track-level edges are noisier than artist-level ones but far better at
        crossing genre lines, which is exactly what a weather theme needs.
        """
        payload = await self.call(
            "track.getSimilar",
            artist=artist,
            track=track,
            mbid=mbid,
            limit=limit,
            autocorrect=autocorrect,
        )
        return self._tracks(payload, "similartracks").tracks

    async def track_get_top_tags(
        self,
        artist: str,
        track: str,
        *,
        mbid: str | None = None,
        autocorrect: bool = True,
    ) -> list[LastfmTag]:
        """``track.getTopTags`` -> ``{"toptags": {"tag": [...]}}``.

        This is the closest thing that exists to a free replacement for
        ``/audio-features``: the crowd has already told us what the record
        sounds like, in words. The lexicon turns the words into numbers.
        """
        payload = await self.call(
            "track.getTopTags",
            artist=artist,
            track=track,
            mbid=mbid,
            autocorrect=autocorrect,
        )
        return self._tags(payload, "toptags")

    async def track_search(
        self,
        track: str,
        *,
        artist: str | None = None,
        limit: int = 10,
        page: int = 1,
    ) -> list[LastfmTrack]:
        """``track.search`` -> ``{"results": {"trackmatches": {"track": [...]}}}``.

        Note the extra nesting level; ``results`` is not a container the other
        methods use, so it gets its own unwrap.
        """
        payload = await self.call(
            "track.search",
            track=track,
            artist=artist,
            limit=limit,
            page=page,
        )
        results = payload.get("results") if isinstance(payload, dict) else None
        return self._tracks(results or {}, "trackmatches").tracks

    # -- tag.* ------------------------------------------------------------
    async def tag_get_top_tracks(
        self,
        tag: str,
        *,
        limit: int = 50,
        page: int = 1,
    ) -> list[LastfmTrack]:
        """``tag.getTopTracks`` -> ``{"tracks": {"track": [...]}}``.

        The theme engine's workhorse. "rainy day", "krautrock" and "dub
        techno" are all first-class queries here, which is precisely the
        vocabulary Spotify never had.
        """
        payload = await self.call("tag.getTopTracks", tag=tag, limit=limit, page=page)
        return self._tracks(payload, "tracks").tracks

    async def tag_get_top_artists(self, tag: str, *, limit: int = 50, page: int = 1) -> list[LastfmArtist]:
        """``tag.getTopArtists`` -> ``{"topartists": {"artist": [...]}}``."""
        payload = await self.call("tag.getTopArtists", tag=tag, limit=limit, page=page)
        return self._artists(payload, "topartists").artists

    async def tag_get_similar(self, tag: str) -> list[LastfmTag]:
        """``tag.getSimilar`` -> ``{"similartags": {"tag": [...]}}``.

        Frequently returns nothing at all these days; treat an empty list as
        normal rather than as a fault.
        """
        payload = await self.call("tag.getSimilar", tag=tag)
        return self._tags(payload, "similartags")

    # -- fan-out ----------------------------------------------------------
    async def map_bounded(
        self,
        factories: Sequence[Callable[[], Awaitable[_T]]],
        *,
        limit: int | None = None,
    ) -> list[_T | BaseException]:
        """Bounded fan-out that reuses this client's concurrency budget."""
        return await gather_bounded(factories, limit=limit or self._concurrency)

    @staticmethod
    def successes(results: Iterable[Any]) -> list[Any]:
        """Drop the exceptions out of a :func:`gather_bounded` result.

        Partial graph traversal is still traversal; one dead artist page must
        not sink a playlist.
        """
        return [r for r in results if not isinstance(r, BaseException)]

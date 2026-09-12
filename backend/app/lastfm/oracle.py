"""``LastfmOracle`` — taste-graph traversal in place of ``/recommendations``.

Spotify's ``/recommendations`` took up to five seeds and returned a black box.
It has been 403 for every new application since 27 Nov 2024. What replaces it
here is not a black box, and that is an improvement rather than a compromise:
every candidate arrives with a recorded provenance, so the playlist can be
explained to the person listening to it.

Three streams feed the pool:

``artist-similar``
    ``artist.getSimilar`` from the listener's own top artists, one or two
    hops out, with the similarity score decayed by hop distance. This is the
    direct replacement for ``/artists/{id}/related-artists``.

``track-similar``
    ``track.getSimilar`` from their top tracks. Noisier per edge than the
    artist graph but far better at crossing genre boundaries, which is what a
    weather theme needs — nobody wants eight straight tracks by neighbours of
    the same band.

``tag-theme``
    ``tag.getTopTracks`` over the theme's seed tags crossed with the
    corridor's tags. This is the stream that makes "Petrichor x krautrock"
    a different playlist from "Petrichor x ambient" rather than the same
    playlist with a different title. It is also the only stream that works
    for a listener with no Last.fm history at all.

Everything degrades. A dead stream is a smaller pool, never an exception; a
dead API is an empty pool and a note in the ledger, and the caller falls back
to theme-only mode.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Final, Iterable, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings, get_settings
from ..contracts import (
    SONIC_DIMS,
    GenreCorridor,
    SonicVector,
    TasteVector,
    Track,
    clamp,
)
from ..errors import DegradationLedger, OracleUnavailable
from ..http import UpstreamError
from .client import LastfmArtist, LastfmClient, LastfmTag, LastfmTrack
from .lexicon import canonical_tags, estimate_with_confidence, tag_affinity

__all__ = [
    "LastfmOracle",
    "Provenance",
    "CandidateNote",
    "TASTE_CACHE_TTL_SECONDS",
]

#: Taste changes on the scale of weeks. Twenty minutes is generous to the API
#: and invisible to the listener.
TASTE_CACHE_TTL_SECONDS: Final[float] = 20 * 60.0

#: How much of the long-run identity to keep versus what they are on right
#: now. Both matter: a purely "overall" read makes the playlist a museum, a
#: purely "1month" read makes it a mood ring.
_PERIOD_WEIGHTS: Final[tuple[tuple[str, float], ...]] = (
    ("overall", 0.62),
    ("1month", 0.38),
)

#: Tags fetched for at most this many of the listener's leading artists.
#: Beyond a dozen the centroid stops moving and the API bill keeps rising.
_TAG_FETCH_ARTISTS: Final[int] = 14
_SEED_ARTISTS_HOP1: Final[int] = 12
_SEED_ARTISTS_HOP2: Final[int] = 5
_SEED_TRACKS: Final[int] = 12
_HOP2_DECAY: Final[float] = 0.45
_DEFAULT_PER_ARTIST_CAP: Final[int] = 2


class Provenance:
    """Provenance labels. Strings rather than an enum so they survive JSON."""

    USER_TOP = "user-top"
    ARTIST_SIMILAR_H1 = "artist-similar-h1"
    ARTIST_SIMILAR_H2 = "artist-similar-h2"
    TRACK_SIMILAR = "track-similar"
    TAG_THEME = "tag-theme"
    TAG_CORRIDOR = "tag-corridor"

    #: How much each stream is trusted before per-edge scores are applied.
    BASE_WEIGHT: Final[dict[str, float]] = {
        USER_TOP: 1.00,
        ARTIST_SIMILAR_H1: 0.85,
        ARTIST_SIMILAR_H2: 0.85 * _HOP2_DECAY,
        TRACK_SIMILAR: 0.80,
        TAG_THEME: 0.70,
        TAG_CORRIDOR: 0.62,
    }


#: Provenance is not a field on the frozen ``Track`` contract, so it travels
#: two ways: as a namespaced pseudo-tag appended to ``Track.tags`` (survives
#: serialisation, ignored by the lexicon because it is not a known tag), and
#: as a structured :class:`CandidateNote` retrievable from the oracle.
PROVENANCE_TAG_PREFIX: Final[str] = "via:"


class CandidateNote(BaseModel):
    """Why a candidate is in the pool. Feeds the "explained playlist" copy."""

    model_config = ConfigDict(frozen=True)

    key: str
    provenance: str
    #: The user artist / track / tag this candidate was reached from.
    seed: str
    #: Hops from the listener's own library. 0 = their own top track.
    hops: int = 1
    #: Last.fm's own edge score where one exists, 0..1.
    edge: float = 0.0
    #: How well the candidate sits in the requested corridor, 0..1.
    corridor_fit: float = 0.0
    #: Final ranking score.
    score: float = 0.0

    @property
    def sentence(self) -> str:
        """One line of plain English, for the UI."""
        if self.provenance == Provenance.USER_TOP:
            return "One of your own most-played tracks."
        if self.provenance == Provenance.ARTIST_SIMILAR_H1:
            return f"Last.fm places this artist next to {self.seed}, who you play a lot."
        if self.provenance == Provenance.ARTIST_SIMILAR_H2:
            return f"Two steps out from {self.seed} through the artist similarity graph."
        if self.provenance == Provenance.TRACK_SIMILAR:
            return f"Listeners who play “{self.seed}” play this."
        if self.provenance == Provenance.TAG_CORRIDOR:
            return f"Top of the “{self.seed}” tag, which is the corridor you asked for."
        return f"Top of the “{self.seed}” tag, which is what this weather sounds like."


class _CacheEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    taste: TasteVector
    expires_at: float


def _to_track(
    raw: LastfmTrack,
    *,
    tags: Sequence[str] = (),
    estimated: SonicVector | None = None,
    provenance: str | None = None,
) -> Track:
    """Convert a client-level track into the frozen public contract."""
    tag_list = list(tags)
    if provenance:
        tag_list.append(f"{PROVENANCE_TAG_PREFIX}{provenance}")
    return Track(
        title=raw.name,
        artist=raw.artist,
        mbid=raw.mbid,
        lastfm_url=raw.url,
        album=raw.album,
        duration_ms=raw.duration_ms,
        tags=tag_list,
        estimated=estimated,
        listeners=raw.listeners,
        playcount=raw.playcount,
    )


def _tag_weights(tags: Iterable[LastfmTag]) -> dict[str, float]:
    """Last.fm tag objects -> ``name -> count`` for the lexicon."""
    return {tag.name: tag.count if tag.count > 0 else 1.0 for tag in tags}


def _spread(vectors: Sequence[SonicVector]) -> SonicVector:
    """Per-dimension dispersion of a set of vectors, mapped into 0..1.

    A listener whose artists all measure the same is a listener you can be
    confident about; one whose artists are scattered needs a wider corridor.
    Population standard deviation over a 0..1 axis tops out at 0.5, so it is
    doubled to use the full range. A single vector has no spread, which we
    report as 0.0 rather than as "unknown" — with one data point the honest
    dispersion really is zero and the *confidence* number carries the doubt.
    """
    if not vectors:
        return SonicVector.neutral()
    if len(vectors) == 1:
        return SonicVector.from_array([0.0] * len(SONIC_DIMS))
    arrays = [v.as_array() for v in vectors]
    n = float(len(arrays))
    out: list[float] = []
    for i in range(len(SONIC_DIMS)):
        column = [a[i] for a in arrays]
        mean = sum(column) / n
        variance = sum((x - mean) ** 2 for x in column) / n
        out.append(clamp(2.0 * variance**0.5))
    return SonicVector.from_array(out)


class LastfmOracle:
    """The live acoustic oracle. Satisfies ``contracts.AcousticOracle``."""

    name: str = "lastfm"

    def __init__(
        self,
        *,
        client: LastfmClient | None = None,
        settings: Settings | None = None,
        ledger: DegradationLedger | None = None,
        cache_ttl: float = TASTE_CACHE_TTL_SECONDS,
        per_artist_cap: int = _DEFAULT_PER_ARTIST_CAP,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client or LastfmClient(settings=self._settings)
        self._ledger = ledger or DegradationLedger()
        self._cache_ttl = max(0.0, cache_ttl)
        self._per_artist_cap = max(1, per_artist_cap)
        self._taste_cache: dict[str, _CacheEntry] = {}
        self._cache_lock = asyncio.Lock()
        #: Provenance for the most recent :meth:`candidates` call, by track key.
        self._notes: dict[str, CandidateNote] = {}

    # -- introspection ----------------------------------------------------
    @property
    def ledger(self) -> DegradationLedger:
        return self._ledger

    @property
    def notes(self) -> dict[str, CandidateNote]:
        """Provenance records from the most recent traversal."""
        return dict(self._notes)

    def note_for(self, track: Track) -> CandidateNote | None:
        return self._notes.get(track.key)

    def _degrade(self, detail: str) -> None:
        """Record a partial failure. Never raises; that is the whole point."""
        self._ledger.note(self.name, detail)

    # -- the /audio-features replacement ----------------------------------
    def estimate_from_tags(self, tags: Sequence[str] | Mapping[str, float]) -> SonicVector:
        """Delegate to the lexicon. Pure, synchronous, always available."""
        from .lexicon import estimate_from_tags as _estimate

        return _estimate(tags)

    # -- taste ------------------------------------------------------------
    async def taste_vector(self, handle: str) -> TasteVector:
        """Build a :class:`TasteVector` for a Last.fm handle.

        Blends two listening periods so the result reflects both the long-run
        identity and the current obsession, fetches artist tags with bounded
        concurrency, and reports a confidence that is honest about thin data:
        a forty-scrobble account is a hint, not a verdict.
        """
        key = handle.strip().casefold()
        if not key:
            return TasteVector.empty()

        now = time.monotonic()
        async with self._cache_lock:
            cached = self._taste_cache.get(key)
            if cached is not None and cached.expires_at > now:
                return cached.taste

        taste = await self._build_taste(handle)

        async with self._cache_lock:
            self._taste_cache[key] = _CacheEntry(
                taste=taste, expires_at=time.monotonic() + self._cache_ttl
            )
        return taste

    async def _build_taste(self, handle: str) -> TasteVector:
        artist_weights: dict[str, float] = {}
        artist_meta: dict[str, LastfmArtist] = {}
        track_names: list[tuple[str, str]] = []
        scrobbles = 0
        fetched_any = False

        async def _artists(period: str) -> Any:
            return await self._client.user_get_top_artists(handle, period=period, limit=40)

        async def _tracks(period: str) -> Any:
            return await self._client.user_get_top_tracks(handle, period=period, limit=40)

        factories = [
            *[(lambda p=p: _artists(p)) for p, _ in _PERIOD_WEIGHTS],
            *[(lambda p=p: _tracks(p)) for p, _ in _PERIOD_WEIGHTS],
        ]
        results = await self._client.map_bounded(factories)

        period_count = len(_PERIOD_WEIGHTS)
        for index, result in enumerate(results):
            period, period_weight = _PERIOD_WEIGHTS[index % period_count]
            if isinstance(result, BaseException):
                self._degrade(f"taste: {period} slice unavailable ({result})")
                continue
            fetched_any = True
            if index < period_count:
                page = result
                total = len(page.artists) or 1
                for rank, artist in enumerate(page.artists):
                    # Rank decay: the top of a Last.fm chart is where the
                    # identity lives; the tail is noise and one-off albums.
                    rank_weight = 1.0 - (rank / (total * 1.6))
                    artist_weights[artist.name] = artist_weights.get(artist.name, 0.0) + (
                        period_weight * rank_weight
                    )
                    artist_meta.setdefault(artist.name, artist)
                    if period == "overall" and artist.playcount:
                        scrobbles += artist.playcount
            else:
                for track in result.tracks[:_SEED_TRACKS]:
                    track_names.append((track.artist, track.name))

        if not fetched_any:
            self._degrade("taste: every period failed; returning empty taste")
            return TasteVector.empty()

        ranked = sorted(artist_weights.items(), key=lambda kv: kv[1], reverse=True)
        if not ranked:
            self._degrade(f"taste: no top artists for {handle!r}")
            return TasteVector.empty()

        leaders = ranked[:_TAG_FETCH_ARTISTS]
        tag_results = await self._client.map_bounded(
            [(lambda n=name: self._client.artist_get_top_tags(n)) for name, _ in leaders]
        )

        aggregate: dict[str, float] = {}
        per_artist_vectors: list[SonicVector] = []
        recognised_artists = 0

        for (name, weight), result in zip(leaders, tag_results):
            if isinstance(result, BaseException):
                self._degrade(f"taste: tags for {name!r} unavailable ({result})")
                continue
            weights = _tag_weights(result[:12])
            if not weights:
                continue
            recognised_artists += 1
            vector, _ = estimate_with_confidence(weights)
            per_artist_vectors.append(vector)
            peak = max(weights.values()) or 1.0
            for tag, count in weights.items():
                aggregate[tag] = aggregate.get(tag, 0.0) + weight * (count / peak)

        centroid, lexicon_confidence = estimate_with_confidence(aggregate)
        spread = _spread(per_artist_vectors)

        # Normalise the tag affinities to 0..1 as the contract requires, and
        # keep only what is worth showing.
        top_tags: dict[str, float] = {}
        if aggregate:
            peak = max(aggregate.values()) or 1.0
            canonicalised: dict[str, float] = {}
            for tag, value in aggregate.items():
                canonicalised[tag.strip().casefold()] = max(
                    canonicalised.get(tag.strip().casefold(), 0.0), value / peak
                )
            top_tags = dict(
                sorted(canonicalised.items(), key=lambda kv: kv[1], reverse=True)[:30]
            )

        # Confidence has three independent brakes: how much of the tag
        # vocabulary we understood, how many artists we actually got tags for,
        # and the raw scrobble volume. A thin account fails at least one.
        breadth = min(1.0, recognised_artists / 8.0)
        volume = min(1.0, scrobbles / 2000.0) if scrobbles else min(1.0, len(ranked) / 25.0)
        confidence = clamp(lexicon_confidence * (0.45 + 0.35 * breadth + 0.20 * volume))

        return TasteVector(
            centroid=centroid,
            spread=spread,
            top_tags=top_tags,
            top_artists=[name for name, _ in ranked[:25]],
            scrobble_count=scrobbles,
            confidence=confidence,
            source=self.name,
        )

    # -- the /recommendations replacement ---------------------------------
    async def candidates(
        self,
        *,
        taste: TasteVector,
        seed_tags: Sequence[str],
        corridor: GenreCorridor,
        limit: int = 400,
    ) -> list[Track]:
        """Traverse the taste graph and return a scored, deduplicated pool."""
        self._notes = {}
        pool: dict[str, Track] = {}
        notes: dict[str, CandidateNote] = {}
        corridor_tags = list(corridor.tags)

        streams = await asyncio.gather(
            self._artist_stream(taste, corridor_tags),
            self._track_stream(taste, corridor_tags),
            self._tag_stream(seed_tags, corridor_tags),
            return_exceptions=True,
        )

        for stream in streams:
            if isinstance(stream, BaseException):
                # _artist_stream and friends already swallow their own
                # per-call failures, so reaching here means something
                # structural. Note it and carry on with what we have.
                self._degrade(f"candidates: stream failed wholesale ({stream})")
                continue
            for track, note in stream:
                existing = notes.get(track.key)
                if existing is not None:
                    # Arriving by two routes is corroboration, not duplication.
                    if note.score > existing.score:
                        merged = note.model_copy(
                            update={"score": min(1.0, note.score + 0.10 * existing.score)}
                        )
                        notes[track.key] = merged
                        pool[track.key] = _merge_tracks(pool[track.key], track)
                    else:
                        notes[track.key] = existing.model_copy(
                            update={"score": min(1.0, existing.score + 0.10 * note.score)}
                        )
                        pool[track.key] = _merge_tracks(pool[track.key], track)
                    continue
                pool[track.key] = track
                notes[track.key] = note

        if not pool:
            self._degrade("candidates: no stream produced anything; theme-only fallback")
            return []

        ordered = sorted(pool.values(), key=lambda t: notes[t.key].score, reverse=True)
        capped = _cap_per_artist(ordered, self._per_artist_cap)
        selected = capped[: max(0, limit)]
        self._notes = {t.key: notes[t.key] for t in selected}
        return selected

    async def _artist_stream(
        self,
        taste: TasteVector,
        corridor_tags: Sequence[str],
    ) -> list[tuple[Track, CandidateNote]]:
        """``artist.getSimilar``, one hop then a narrow second hop."""
        seeds = list(taste.top_artists[:_SEED_ARTISTS_HOP1])
        if not seeds:
            return []

        out: list[tuple[Track, CandidateNote]] = []
        hop1 = await self._client.map_bounded(
            [(lambda n=name: self._client.artist_get_similar(n, limit=18)) for name in seeds]
        )

        hop1_pairs: list[tuple[str, LastfmArtist]] = []
        for seed, result in zip(seeds, hop1):
            if isinstance(result, BaseException):
                self._degrade(f"artist stream: similar({seed!r}) failed ({result})")
                continue
            for artist in result:
                hop1_pairs.append((seed, artist))

        # Second hop only from the strongest first-hop neighbours. Two hops of
        # unbounded fan-out is thousands of calls and a rate limit.
        strongest = sorted(hop1_pairs, key=lambda p: p[1].match or 0.0, reverse=True)
        hop2_seeds = []
        seen_hop2: set[str] = set()
        for seed, artist in strongest:
            folded = artist.name.casefold()
            if folded in seen_hop2:
                continue
            seen_hop2.add(folded)
            hop2_seeds.append((seed, artist))
            if len(hop2_seeds) >= _SEED_ARTISTS_HOP2:
                break

        hop2 = await self._client.map_bounded(
            [
                (lambda n=artist.name: self._client.artist_get_similar(n, limit=10))
                for _, artist in hop2_seeds
            ]
        )
        hop2_pairs: list[tuple[str, LastfmArtist, float]] = []
        for (origin, mid), result in zip(hop2_seeds, hop2):
            if isinstance(result, BaseException):
                self._degrade(f"artist stream: hop-2 similar({mid.name!r}) failed ({result})")
                continue
            for artist in result:
                hop2_pairs.append((f"{origin} → {mid.name}", artist, (mid.match or 0.5)))

        # Turn artists into tracks. One request per artist; the per-artist cap
        # in the merge stage stops any one of them dominating.
        targets: list[tuple[str, LastfmArtist, str, float]] = [
            *[(seed, a, Provenance.ARTIST_SIMILAR_H1, 1.0) for seed, a in hop1_pairs[:60]],
            *[
                (seed, a, Provenance.ARTIST_SIMILAR_H2, _HOP2_DECAY * carry)
                for seed, a, carry in hop2_pairs[:30]
            ],
        ]
        track_results = await self._client.map_bounded(
            [
                (lambda n=artist.name: self._client.artist_get_top_tracks(n, limit=4))
                for _, artist, _, _ in targets
            ]
        )

        for (seed, artist, provenance, decay), result in zip(targets, track_results):
            if isinstance(result, BaseException):
                self._degrade(f"artist stream: top tracks for {artist.name!r} failed ({result})")
                continue
            edge = artist.match if artist.match is not None else 0.5
            for raw in result:
                fit = tag_affinity([artist.name], corridor_tags) if corridor_tags else 1.0
                score = _score(
                    base=Provenance.BASE_WEIGHT[provenance],
                    edge=edge,
                    decay=decay,
                    corridor_fit=fit,
                )
                track = _to_track(raw, provenance=provenance)
                out.append(
                    (
                        track,
                        CandidateNote(
                            key=track.key,
                            provenance=provenance,
                            seed=seed,
                            hops=1 if provenance == Provenance.ARTIST_SIMILAR_H1 else 2,
                            edge=edge,
                            corridor_fit=fit,
                            score=score,
                        ),
                    )
                )
        return out

    async def _track_stream(
        self,
        taste: TasteVector,
        corridor_tags: Sequence[str],
    ) -> list[tuple[Track, CandidateNote]]:
        """``track.getSimilar`` from the listener's own top tracks.

        The taste vector does not carry track identities, so this stream is
        driven by the leading artists' own top tracks — a stable, cheap proxy
        that stays inside the protocol.
        """
        seeds = list(taste.top_artists[:_SEED_TRACKS])
        if not seeds:
            return []

        anchors = await self._client.map_bounded(
            [(lambda n=name: self._client.artist_get_top_tracks(n, limit=2)) for name in seeds]
        )
        pairs: list[LastfmTrack] = []
        for name, result in zip(seeds, anchors):
            if isinstance(result, BaseException):
                self._degrade(f"track stream: anchor for {name!r} failed ({result})")
                continue
            pairs.extend(result[:2])

        similar = await self._client.map_bounded(
            [
                (lambda a=p.artist, t=p.name: self._client.track_get_similar(a, t, limit=12))
                for p in pairs
            ]
        )

        out: list[tuple[Track, CandidateNote]] = []
        for anchor, result in zip(pairs, similar):
            if isinstance(result, BaseException):
                self._degrade(f"track stream: similar to {anchor.name!r} failed ({result})")
                continue
            for raw in result:
                edge = raw.match if raw.match is not None else 0.4
                fit = tag_affinity([raw.artist], corridor_tags) if corridor_tags else 1.0
                score = _score(
                    base=Provenance.BASE_WEIGHT[Provenance.TRACK_SIMILAR],
                    edge=edge,
                    decay=1.0,
                    corridor_fit=fit,
                )
                track = _to_track(raw, provenance=Provenance.TRACK_SIMILAR)
                out.append(
                    (
                        track,
                        CandidateNote(
                            key=track.key,
                            provenance=Provenance.TRACK_SIMILAR,
                            seed=f"{anchor.artist} – {anchor.name}",
                            hops=1,
                            edge=edge,
                            corridor_fit=fit,
                            score=score,
                        ),
                    )
                )
        return out

    async def _tag_stream(
        self,
        seed_tags: Sequence[str],
        corridor_tags: Sequence[str],
    ) -> list[tuple[Track, CandidateNote]]:
        """``tag.getTopTracks`` over theme tags and corridor tags.

        The theme tags describe the weather; the corridor tags describe the
        genre the listener asked to stay inside. Both are queried, and both
        are labelled distinctly, because "this is what rain sounds like" and
        "this is the krautrock you asked for" are different sentences.
        """
        themes = [t for t in dict.fromkeys(seed_tags) if t]
        corridors = [t for t in dict.fromkeys(corridor_tags) if t and t not in set(themes)]
        queries: list[tuple[str, str]] = [
            *[(tag, Provenance.TAG_THEME) for tag in themes[:8]],
            *[(tag, Provenance.TAG_CORRIDOR) for tag in corridors[:8]],
        ]
        if not queries:
            return []

        results = await self._client.map_bounded(
            [(lambda t=tag: self._client.tag_get_top_tracks(t, limit=50)) for tag, _ in queries]
        )

        out: list[tuple[Track, CandidateNote]] = []
        for (tag, provenance), result in zip(queries, results):
            if isinstance(result, BaseException):
                self._degrade(f"tag stream: tag.getTopTracks({tag!r}) failed ({result})")
                continue
            canon = canonical_tags([tag]) or [tag]
            estimated, _ = estimate_with_confidence(canon)
            total = len(result) or 1
            for rank, raw in enumerate(result):
                # Chart position is the only edge score tag.getTopTracks
                # offers, so use it: the head of a tag chart really is more
                # representative of that tag than the tail.
                edge = 1.0 - (rank / (total * 1.25))
                fit = tag_affinity(canon, corridor_tags) if corridor_tags else 1.0
                score = _score(
                    base=Provenance.BASE_WEIGHT[provenance],
                    edge=edge,
                    decay=1.0,
                    corridor_fit=fit,
                )
                track = _to_track(raw, tags=canon, estimated=estimated, provenance=provenance)
                out.append(
                    (
                        track,
                        CandidateNote(
                            key=track.key,
                            provenance=provenance,
                            seed=tag,
                            hops=1,
                            edge=edge,
                            corridor_fit=fit,
                            score=score,
                        ),
                    )
                )
        return out

    # -- per-track refinement --------------------------------------------
    async def estimate(self, track: Track) -> Track:
        """Attach tags and a sonic estimate to a single track.

        Order of preference: the track's own community tags, then the
        artist's, then whatever the track already carried. The lexicon does
        the arithmetic in all three cases, so this method never fails — the
        worst outcome is a neutral vector.
        """
        weights: dict[str, float] = {}
        try:
            tags = await self._client.track_get_top_tags(track.artist, track.title)
            weights = _tag_weights(tags[:15])
        except (OracleUnavailable, UpstreamError) as exc:
            self._degrade(f"estimate: track tags for {track.display!r} unavailable ({exc})")

        if not weights:
            try:
                tags = await self._client.artist_get_top_tags(track.artist)
                weights = _tag_weights(tags[:15])
            except (OracleUnavailable, UpstreamError) as exc:
                self._degrade(f"estimate: artist tags for {track.artist!r} unavailable ({exc})")

        existing = [t for t in track.tags if not t.startswith(PROVENANCE_TAG_PREFIX)]
        if not weights:
            if not existing:
                return track.model_copy(update={"estimated": SonicVector.neutral()})
            weights = {tag: 1.0 for tag in existing}

        vector, _ = estimate_with_confidence(weights)
        merged = list(dict.fromkeys([*existing, *weights.keys()]))
        provenance_tags = [t for t in track.tags if t.startswith(PROVENANCE_TAG_PREFIX)]
        return track.model_copy(update={"tags": [*merged, *provenance_tags], "estimated": vector})


# --------------------------------------------------------------------------
# scoring and merge helpers
# --------------------------------------------------------------------------
def _score(*, base: float, edge: float, decay: float, corridor_fit: float) -> float:
    """Combine stream trust, edge strength, hop decay and corridor fit.

    Corridor fit enters as ``0.35 + 0.65 * fit`` rather than as a plain
    multiplier: a corridor should strongly reorder the pool without deleting
    everything outside it, since a playlist made only of the corridor's
    obvious centre is a boring playlist.
    """
    return clamp(base * clamp(edge) * clamp(decay) * (0.35 + 0.65 * clamp(corridor_fit)))


def _merge_tracks(first: Track, second: Track) -> Track:
    """Union of what two sightings of the same track knew."""
    tags = list(dict.fromkeys([*first.tags, *second.tags]))
    return first.model_copy(
        update={
            "tags": tags,
            "estimated": first.estimated or second.estimated,
            "mbid": first.mbid or second.mbid,
            "lastfm_url": first.lastfm_url or second.lastfm_url,
            "album": first.album or second.album,
            "duration_ms": first.duration_ms or second.duration_ms,
            "listeners": first.listeners or second.listeners,
            "playcount": first.playcount or second.playcount,
        }
    )


def _cap_per_artist(tracks: Sequence[Track], cap: int) -> list[Track]:
    """At most *cap* tracks per artist, preserving the incoming order.

    Without this the artist-similarity stream reliably returns four tracks
    each by the six nearest neighbours and calls it a playlist.
    """
    counts: dict[str, int] = {}
    out: list[Track] = []
    for track in tracks:
        artist = track.artist.casefold()
        if counts.get(artist, 0) >= cap:
            continue
        counts[artist] = counts.get(artist, 0) + 1
        out.append(track)
    return out

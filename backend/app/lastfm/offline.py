"""``OfflineOracle`` — the same protocol, zero network, zero credentials.

This is the demo path and an explicit acceptance criterion: ``forge_playlist``
must return a genuinely good, genuinely explained playlist on a laptop with no
API key and no internet. It is also the fallback when Last.fm is down, when a
listener has not paired an account, and when the test suite runs.

It is backed by ``fixtures/seed_corpus.py`` — 170-odd real records, curated by
hand and tagged the way Last.fm's community would tag them. The scoring here
is the same shape as the live oracle's: theme fit, corridor fit and taste
proximity, combined and labelled. The only thing missing is the graph.

Determinism is a feature. The same handle, theme and corridor produce the same
pool every time, so screenshots stay valid and tests do not flake.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Final, Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from ..contracts import (
    GenreCorridor,
    SonicVector,
    TasteVector,
    Track,
    clamp,
)
from .lexicon import canonical_tags, estimate_from_tags, estimate_with_confidence, tag_affinity
from .oracle import CandidateNote, Provenance, PROVENANCE_TAG_PREFIX, _cap_per_artist

__all__ = ["OfflineOracle", "OFFLINE_TRACKS", "seed_tracks", "load_seed_corpus"]


# --------------------------------------------------------------------------
# fixture loading
# --------------------------------------------------------------------------
# The corpus lives at ``fixtures/seed_corpus.py``, a sibling of ``backend/``
# rather than a submodule of it, precisely so that worker 12's tests can
# import it without pulling in the application package. That puts it outside
# this module's relative-import reach, so: try the normal import first, and
# fall back to locating the file by walking up from here.
_FIXTURE_MODULE: Final[str] = "fixtures.seed_corpus"


def load_seed_corpus() -> ModuleType:
    """Import the seed corpus, by package path or by walking up the tree."""
    try:
        return importlib.import_module(_FIXTURE_MODULE)
    except ImportError:
        pass

    cached = sys.modules.get(_FIXTURE_MODULE)
    if cached is not None:
        return cached

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "fixtures" / "seed_corpus.py"
        if not candidate.is_file():
            continue
        spec = importlib.util.spec_from_file_location(_FIXTURE_MODULE, candidate)
        if spec is None or spec.loader is None:  # pragma: no cover - defensive
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[_FIXTURE_MODULE] = module
        spec.loader.exec_module(module)
        return module

    raise ImportError(
        "could not locate fixtures/seed_corpus.py; the offline oracle cannot "
        "run without it"
    )


_corpus = load_seed_corpus()
SEED_CORPUS = _corpus.SEED_CORPUS
THEMES: tuple[str, ...] = _corpus.THEMES
THEME_TAGS: dict[str, tuple[str, ...]] = _corpus.THEME_TAGS
CORRIDOR_TAGS: dict[str, tuple[str, ...]] = _corpus.CORRIDOR_TAGS


class SeedEntry(BaseModel):
    """A corpus row promoted into contract types, with its estimate cached."""

    model_config = ConfigDict(frozen=True)

    track: Track
    themes: tuple[str, ...]
    tags: tuple[str, ...]
    vector: SonicVector


def _build_entries() -> tuple[SeedEntry, ...]:
    """Convert the fixture dataclasses into contract ``Track`` objects once.

    Estimating every vector at import time costs a few milliseconds and buys
    a scoring loop with no arithmetic in it.
    """
    entries: list[SeedEntry] = []
    for seed in SEED_CORPUS:
        tags = tuple(seed.tags)
        entries.append(
            SeedEntry(
                track=Track(
                    title=seed.title,
                    artist=seed.artist,
                    album=seed.album,
                    duration_ms=seed.duration_ms,
                    tags=list(tags),
                    estimated=estimate_from_tags(tags),
                ),
                themes=tuple(seed.themes),
                tags=tags,
                vector=estimate_from_tags(tags),
            )
        )
    return tuple(entries)


_ENTRIES: Final[tuple[SeedEntry, ...]] = _build_entries()

#: The corpus as plain contract tracks, for callers that want the raw pool.
OFFLINE_TRACKS: Final[tuple[Track, ...]] = tuple(e.track for e in _ENTRIES)


def seed_tracks(theme: str | None = None) -> tuple[Track, ...]:
    """Corpus tracks, optionally filtered to one theme."""
    if theme is None:
        return OFFLINE_TRACKS
    needle = theme.strip().casefold()
    return tuple(e.track for e in _ENTRIES if needle in (t.casefold() for t in e.themes))


# --------------------------------------------------------------------------
# the oracle
# --------------------------------------------------------------------------
#: Below this corridor fit a track is not in the corridor, it is merely
#: nearby. Without a floor, "Petrichor x krautrock" and "Petrichor x ambient"
#: return the same eighty tracks in a slightly different order, which is the
#: exact failure the corridor concept exists to prevent.
_CORRIDOR_FLOOR: Final[float] = 0.30

#: Weight of the listener's own taste against the requested weather. The
#: weather wins: they asked for a sky, not a mirror.
_TASTE_WEIGHT: Final[float] = 0.30


class OfflineOracle:
    """Offline implementation of ``contracts.AcousticOracle``."""

    name: str = "offline"

    def __init__(
        self,
        *,
        entries: Sequence[SeedEntry] | None = None,
        per_artist_cap: int = 2,
        corridor_floor: float = _CORRIDOR_FLOOR,
    ) -> None:
        self._entries: tuple[SeedEntry, ...] = tuple(entries) if entries else _ENTRIES
        self._per_artist_cap = max(1, per_artist_cap)
        self._corridor_floor = clamp(corridor_floor)
        self._notes: dict[str, CandidateNote] = {}

    # -- introspection ----------------------------------------------------
    @property
    def entries(self) -> tuple[SeedEntry, ...]:
        return self._entries

    @property
    def notes(self) -> dict[str, CandidateNote]:
        return dict(self._notes)

    def note_for(self, track: Track) -> CandidateNote | None:
        return self._notes.get(track.key)

    # -- protocol ---------------------------------------------------------
    def estimate_from_tags(self, tags: Sequence[str] | Mapping[str, float]) -> SonicVector:
        return estimate_from_tags(tags)

    async def taste_vector(self, handle: str) -> TasteVector:
        """A stable, plausible taste profile derived from the handle alone.

        There is no listening history offline, so inventing one would be a
        lie. What this does instead is deterministic and declared: hash the
        handle, use it to pick a coherent slice of the corpus, and report a
        deliberately modest confidence with ``source="offline"`` so that
        downstream code — and the UI — can tell this apart from a real read.
        """
        cleaned = handle.strip().casefold()
        if not cleaned:
            # No handle at all is a coherent state: pure theme mode.
            return TasteVector.empty().model_copy(update={"source": self.name})

        digest = hashlib.sha256(cleaned.encode("utf-8")).digest()
        # Two themes, deterministically chosen, give a listener with a
        # believable centre of gravity rather than a uniform average of
        # everything in the corpus.
        primary = THEMES[digest[0] % len(THEMES)]
        secondary = THEMES[digest[1] % len(THEMES)]
        chosen = [
            e
            for e in self._entries
            if primary in e.themes or (secondary != primary and secondary in e.themes)
        ]
        if not chosen:  # pragma: no cover - the corpus validator forbids this
            chosen = list(self._entries)

        # Rotate the slice by the hash so two handles that land on the same
        # themes still differ.
        offset = digest[2] % max(1, len(chosen))
        rotated = chosen[offset:] + chosen[:offset]
        sample = rotated[:24]

        aggregate: dict[str, float] = {}
        for rank, entry in enumerate(sample):
            weight = 1.0 - rank / (len(sample) * 1.5)
            for tag in entry.tags:
                aggregate[tag] = aggregate.get(tag, 0.0) + weight

        centroid, lexicon_confidence = estimate_with_confidence(aggregate)
        spread = _dispersion([e.vector for e in sample])
        peak = max(aggregate.values()) or 1.0
        top_tags = dict(
            sorted(
                ((t.casefold(), v / peak) for t, v in aggregate.items()),
                key=lambda kv: kv[1],
                reverse=True,
            )[:25]
        )
        artists: list[str] = []
        for entry in sample:
            if entry.track.artist not in artists:
                artists.append(entry.track.artist)

        return TasteVector(
            centroid=centroid,
            spread=spread,
            top_tags=top_tags,
            top_artists=artists[:20],
            scrobble_count=0,
            # Capped hard. This is a synthetic profile; treating it as
            # gospel would let it out-vote the weather.
            confidence=clamp(min(0.45, lexicon_confidence)),
            source=self.name,
        )

    async def candidates(
        self,
        *,
        taste: TasteVector,
        seed_tags: Sequence[str],
        corridor: GenreCorridor,
        limit: int = 400,
    ) -> list[Track]:
        """Score the corpus against theme, corridor and taste; return a pool."""
        self._notes = {}
        theme_tags = canonical_tags(seed_tags)
        corridor_tags = list(corridor.tags)
        has_corridor = bool(canonical_tags(corridor_tags))
        theme_vector = estimate_from_tags(theme_tags) if theme_tags else None

        scored: list[tuple[float, Track, CandidateNote]] = []
        for entry in self._entries:
            corridor_fit = tag_affinity(entry.tags, corridor_tags) if has_corridor else 1.0
            if has_corridor and corridor_fit < self._corridor_floor:
                continue

            theme_fit = tag_affinity(entry.tags, theme_tags) if theme_tags else 0.6
            if theme_vector is not None:
                # Vocabulary overlap is the primary signal, but a record can
                # be right for the weather without sharing a single word with
                # it. Sonic proximity catches those.
                theme_fit = max(theme_fit, clamp(1.0 - entry.vector.distance(theme_vector)))

            taste_fit = (
                clamp(1.0 - entry.vector.distance(taste.centroid))
                if taste.confidence > 0.0
                else 0.5
            )
            taste_pull = _TASTE_WEIGHT * taste.confidence

            score = clamp(
                (1.0 - taste_pull) * (0.55 * theme_fit + 0.45 * corridor_fit)
                + taste_pull * taste_fit
            )

            provenance = Provenance.TAG_CORRIDOR if has_corridor else Provenance.TAG_THEME
            seed_label = (corridor.name or corridor.id) if has_corridor else _first(theme_tags)
            track = entry.track.model_copy(
                update={"tags": [*entry.tags, f"{PROVENANCE_TAG_PREFIX}offline-corpus"]}
            )
            note = CandidateNote(
                key=track.key,
                provenance=provenance,
                seed=seed_label,
                hops=0,
                edge=theme_fit,
                corridor_fit=corridor_fit,
                score=score,
            )
            scored.append((score, track, note))

        scored.sort(key=lambda row: (-row[0], row[1].key))
        ordered = [row[1] for row in scored]
        capped = _cap_per_artist(ordered, self._per_artist_cap)
        selected = capped[: max(0, limit)]
        notes = {note.key: note for _, _, note in scored}
        self._notes = {t.key: notes[t.key] for t in selected}
        return selected

    async def estimate(self, track: Track) -> Track:
        """Fill in ``estimated`` from whatever tags the track already carries.

        If the track is in the corpus, its curated tags are used even when the
        caller handed over a bare title — the corpus is the better source.
        """
        match = self._by_key.get(track.key)
        if match is not None:
            provenance = [t for t in track.tags if t.startswith(PROVENANCE_TAG_PREFIX)]
            merged = list(dict.fromkeys([*match.tags, *(
                t for t in track.tags if not t.startswith(PROVENANCE_TAG_PREFIX)
            )]))
            return track.model_copy(
                update={"tags": [*merged, *provenance], "estimated": match.vector}
            )

        usable = [t for t in track.tags if not t.startswith(PROVENANCE_TAG_PREFIX)]
        return track.model_copy(update={"estimated": estimate_from_tags(usable)})

    # -- internals --------------------------------------------------------
    @property
    def _by_key(self) -> dict[str, SeedEntry]:
        cached: dict[str, SeedEntry] | None = getattr(self, "_key_index", None)
        if cached is None:
            cached = {e.track.key: e for e in self._entries}
            object.__setattr__(self, "_key_index", cached)
        return cached


def _first(items: Sequence[str]) -> str:
    return items[0] if items else "the weather"


def _dispersion(vectors: Sequence[SonicVector]) -> SonicVector:
    """Per-dimension standard deviation, doubled into 0..1. See oracle._spread."""
    if len(vectors) < 2:
        return SonicVector.from_array([0.0] * 7)
    arrays = [v.as_array() for v in vectors]
    n = float(len(arrays))
    out: list[float] = []
    for i in range(len(arrays[0])):
        column = [a[i] for a in arrays]
        mean = sum(column) / n
        variance = sum((x - mean) ** 2 for x in column) / n
        out.append(clamp(2.0 * variance**0.5))
    return SonicVector.from_array(out)


def offline_corridor(corridor_id: str) -> GenreCorridor:
    """Build a :class:`GenreCorridor` from the fixture's corridor vocabulary.

    Convenience for demos and tests; the real corridor definitions belong to
    whichever module owns the theme catalogue.
    """
    tags = list(CORRIDOR_TAGS.get(corridor_id, ()))
    if not tags:
        return GenreCorridor.any()
    return GenreCorridor(
        id=corridor_id,
        name=corridor_id.replace("_", " ").title(),
        tags=tags,
        anchor=estimate_from_tags(tags),
        width=0.55,
        description=f"Offline corridor seeded from {', '.join(tags)}.",
    )


def offline_theme_tags(theme: str) -> list[str]:
    """The seed tag vocabulary for a BAROGROOVE theme."""
    return list(THEME_TAGS.get(theme, ()))

"""Firestore-backed Scrobble Collection, Search & Sonic DNA Analytics for Almanac.

Stores and indexes user scrobbles in the Firestore `scrobbles` collection
(`scrobbles/{doc_id}`), supporting:
1. Live search across track titles, artists, albums, and micro-genre tags.
2. Sonic DNA analytics (Top Artists, Top Micro-Genres, Barometric Weather Theme
   Affinity, Average Tempo/BPM & Energy profile).
3. One-click selection of scrobbles to seed new Weather-Inspired Daylists in
   the Forge engine (`seed_scrobbles`).
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("barogroove.almanac.scrobbles")


class ScrobbleEntry(BaseModel):
    """A single scrobbled track indexed in the Almanac."""

    id: str
    user_id: str = "demo"
    title: str
    artist: str
    album: str | None = None
    tags: list[str] = Field(default_factory=list)
    weather_theme: str = "petrichor"
    bpm_estimate: int = 112
    energy_estimate: float = 0.62
    play_count: int = 1
    last_played_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    lastfm_url: str | None = None
    spotify_uri: str | None = None

    @property
    def track_key(self) -> str:
        return f"{self.artist} - {self.title}"


class ScrobbleAnalytics(BaseModel):
    """Aggregated Sonic DNA analytics across the user's scrobble history."""

    total_scrobbles: int = 0
    unique_tracks: int = 0
    avg_bpm: float = 114.0
    avg_energy: float = 0.64
    top_artists: list[dict[str, Any]] = Field(default_factory=list)
    top_genres: list[dict[str, Any]] = Field(default_factory=list)
    weather_affinity: list[dict[str, Any]] = Field(default_factory=list)


class ScrobbleSearchResponse(BaseModel):
    count: int
    scrobbles: list[ScrobbleEntry]
    analytics: ScrobbleAnalytics
    synced_from_firestore: bool = False


# Curated initial scrobble catalog representing jpaquay's barometric taste DNA
_CURATED_SEED_SCROBBLES: list[dict[str, Any]] = [
    {
        "title": "Tezeta",
        "artist": "Hailu Mergia",
        "album": "Wede Harer Guzo",
        "tags": ["ethio-jazz", "analog-organ", "nostalgic", "warm"],
        "weather_theme": "petrichor",
        "bpm_estimate": 96,
        "energy_estimate": 0.52,
        "play_count": 19,
    },
    {
        "title": "Yègellé Tezeta",
        "artist": "Mulatu Astatke",
        "album": "Ethiopiques Vol. 4",
        "tags": ["ethio-jazz", "vibraphone", "hypnotic", "twilight"],
        "weather_theme": "petrichor",
        "bpm_estimate": 104,
        "energy_estimate": 0.58,
        "play_count": 24,
    },
    {
        "title": "Everything In Its Right Place",
        "artist": "Radiohead",
        "album": "Kid A",
        "tags": ["art-rock", "ambient-electronic", "prophet-5", "mist"],
        "weather_theme": "low_pressure_front",
        "bpm_estimate": 124,
        "energy_estimate": 0.66,
        "play_count": 31,
    },
    {
        "title": "Archangel",
        "artist": "Burial",
        "album": "Untrue",
        "tags": ["uk-garage", "dubstep", "rain-vinyl", "nocturnal"],
        "weather_theme": "steady_drizzle",
        "bpm_estimate": 135,
        "energy_estimate": 0.64,
        "play_count": 28,
    },
    {
        "title": "Avril 14th",
        "artist": "Aphex Twin",
        "album": "Drukqs",
        "tags": ["neo-classical", "prepared-piano", "minimal", "frost"],
        "weather_theme": "high_pressure_glass",
        "bpm_estimate": 79,
        "energy_estimate": 0.28,
        "play_count": 22,
    },
    {
        "title": "Roygbiv",
        "artist": "Boards of Canada",
        "album": "Music Has the Right to Children",
        "tags": ["idm", "analog-synth", "downtempo", "haze"],
        "weather_theme": "warm_front_haze",
        "bpm_estimate": 84,
        "energy_estimate": 0.55,
        "play_count": 35,
    },
    {
        "title": "Starálfur",
        "artist": "Sigur Rós",
        "album": "Ágætis byrjun",
        "tags": ["post-rock", "icelandic", "cinematic-strings", "aurora"],
        "weather_theme": "clearing_isobar",
        "bpm_estimate": 88,
        "energy_estimate": 0.61,
        "play_count": 17,
    },
    {
        "title": "Midnight City",
        "artist": "M83",
        "album": "Hurry Up, We're Dreaming",
        "tags": ["synthwave", "dream-pop", "neon-drive", "euphoric"],
        "weather_theme": "golden_hour_ridge",
        "bpm_estimate": 105,
        "energy_estimate": 0.84,
        "play_count": 26,
    },
    {
        "title": "La Femme d'Argent",
        "artist": "Air",
        "album": "Moon Safari",
        "tags": ["french-touch", "downtempo", "rhodes-bass", "breeze"],
        "weather_theme": "clearing_isobar",
        "bpm_estimate": 92,
        "energy_estimate": 0.54,
        "play_count": 29,
    },
    {
        "title": "Plastic Beach",
        "artist": "Gorillaz",
        "album": "Plastic Beach",
        "tags": ["synth-pop", "electro-dub", "coastal", "barometric"],
        "weather_theme": "warm_front_haze",
        "bpm_estimate": 110,
        "energy_estimate": 0.71,
        "play_count": 21,
    },
    {
        "title": "Space Song",
        "artist": "Beach House",
        "album": "Depression Cherry",
        "tags": ["dream-pop", "shoegaze", "slide-guitar", "velvet-sky"],
        "weather_theme": "steady_drizzle",
        "bpm_estimate": 147,
        "energy_estimate": 0.60,
        "play_count": 33,
    },
    {
        "title": "Breathe",
        "artist": "Télépopmusik",
        "album": "Genetic World",
        "tags": ["chillout", "trip-hop", "french-electro", "clouds"],
        "weather_theme": "warm_front_haze",
        "bpm_estimate": 90,
        "energy_estimate": 0.49,
        "play_count": 18,
    },
    {
        "title": "So What",
        "artist": "Miles Davis",
        "album": "Kind of Blue",
        "tags": ["modal-jazz", "cool-jazz", "double-bass", "nocturne"],
        "weather_theme": "high_pressure_glass",
        "bpm_estimate": 136,
        "energy_estimate": 0.48,
        "play_count": 27,
    },
    {
        "title": "Halcyon and On and On",
        "artist": "Orbital",
        "album": "Orbital 2",
        "tags": ["ambient-house", "progressive-electronic", "sunrise", "cumulus"],
        "weather_theme": "golden_hour_ridge",
        "bpm_estimate": 127,
        "energy_estimate": 0.74,
        "play_count": 20,
    },
    {
        "title": "Teardrop",
        "artist": "Massive Attack",
        "album": "Mezzanine",
        "tags": ["trip-hop", "bristol-sound", "harpsichord-beat", "storm-front"],
        "weather_theme": "low_pressure_front",
        "bpm_estimate": 77,
        "energy_estimate": 0.56,
        "play_count": 40,
    },
    {
        "title": "Rêverie",
        "artist": "Claude Debussy",
        "album": "Images & Solo Piano",
        "tags": ["impressionist", "solo-piano", "misty-morning", "glass"],
        "weather_theme": "high_pressure_glass",
        "bpm_estimate": 68,
        "energy_estimate": 0.25,
        "play_count": 15,
    },
]

_MEMORY_SCROBBLES: dict[str, list[ScrobbleEntry]] = {}


def _get_firestore_db() -> Any | None:
    try:
        from google.cloud import firestore  # type: ignore[import-untyped]

        return firestore.Client()
    except Exception:  # noqa: BLE001
        return None


def _ensure_seeded(user_id: str) -> list[ScrobbleEntry]:
    uid = user_id or "demo"
    if uid in _MEMORY_SCROBBLES and _MEMORY_SCROBBLES[uid]:
        return _MEMORY_SCROBBLES[uid]

    now = datetime.now(timezone.utc)
    entries: list[ScrobbleEntry] = []

    # First check Firestore `scrobbles` collection
    db = _get_firestore_db()
    if db is not None:
        try:
            docs = (
                db.collection("scrobbles")
                .where("user_id", "==", uid)
                .limit(100)
                .stream()
            )
            for doc in docs:
                data = doc.to_dict() or {}
                entries.append(ScrobbleEntry.model_validate(data))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Firestore scrobbles query fallback: %s", exc)

    if not entries:
        for idx, item in enumerate(_CURATED_SEED_SCROBBLES):
            entry = ScrobbleEntry(
                id=f"scrobble_{uid}_{idx:02d}",
                user_id=uid,
                title=item["title"],
                artist=item["artist"],
                album=item.get("album"),
                tags=list(item.get("tags", [])),
                weather_theme=item.get("weather_theme", "petrichor"),
                bpm_estimate=int(item.get("bpm_estimate", 112)),
                energy_estimate=float(item.get("energy_estimate", 0.60)),
                play_count=int(item.get("play_count", 10)),
                last_played_at=now - timedelta(hours=idx * 3 + 1),
            )
            entries.append(entry)

        # Persist initial seed into Firestore `scrobbles` collection asynchronously/best-effort
        if db is not None:
            try:
                batch = db.batch()
                col = db.collection("scrobbles")
                for e in entries:
                    doc_ref = col.document(e.id)
                    batch.set(doc_ref, e.model_dump(mode="json"), merge=True)
                batch.commit()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Could not write initial scrobbles batch to Firestore: %s", exc)

    _MEMORY_SCROBBLES[uid] = entries
    return entries


def compute_analytics(entries: list[ScrobbleEntry]) -> ScrobbleAnalytics:
    if not entries:
        return ScrobbleAnalytics()

    total_plays = sum(e.play_count for e in entries)
    unique_tracks = len(entries)
    avg_bpm = round(
        sum(e.bpm_estimate * e.play_count for e in entries) / max(1, total_plays), 1
    )
    avg_energy = round(
        sum(e.energy_estimate * e.play_count for e in entries) / max(1, total_plays), 2
    )

    artist_counts: Counter[str] = Counter()
    tag_counts: Counter[str] = Counter()
    theme_counts: Counter[str] = Counter()

    for e in entries:
        artist_counts[e.artist] += e.play_count
        theme_counts[e.weather_theme] += e.play_count
        for t in e.tags:
            tag_counts[t] += e.play_count

    top_artists = [
        {"artist": artist, "plays": count}
        for artist, count in artist_counts.most_common(6)
    ]
    top_genres = [
        {"tag": tag, "count": count} for tag, count in tag_counts.most_common(8)
    ]

    theme_labels = {
        "petrichor": "Petrichor & Rain Front",
        "low_pressure_front": "Low-Pressure Storm Front",
        "steady_drizzle": "Steady Drizzle & Velvet Mist",
        "high_pressure_glass": "High-Pressure Glass & Nocturne",
        "warm_front_haze": "Warm Front Haze & Analog Drift",
        "clearing_isobar": "Clearing Isobar & Horizon Breeze",
        "golden_hour_ridge": "Golden Hour Ridge & Twilight",
    }

    weather_affinity = [
        {
            "theme_id": tid,
            "label": theme_labels.get(tid, tid.replace("_", " ").title()),
            "percentage": round((cnt / max(1, total_plays)) * 100.0, 1),
            "plays": cnt,
        }
        for tid, cnt in theme_counts.most_common(5)
    ]

    return ScrobbleAnalytics(
        total_scrobbles=total_plays,
        unique_tracks=unique_tracks,
        avg_bpm=avg_bpm,
        avg_energy=avg_energy,
        top_artists=top_artists,
        top_genres=top_genres,
        weather_affinity=weather_affinity,
    )


def search_scrobbles(
    user_id: str,
    *,
    query: str | None = None,
    tag: str | None = None,
    theme: str | None = None,
    limit: int = 50,
) -> ScrobbleSearchResponse:
    all_entries = _ensure_seeded(user_id)
    analytics = compute_analytics(all_entries)

    filtered = list(all_entries)
    if query and query.strip():
        q = query.strip().lower()
        filtered = [
            e
            for e in filtered
            if q in e.title.lower()
            or q in e.artist.lower()
            or (e.album and q in e.album.lower())
            or any(q in t.lower() for t in e.tags)
        ]

    if tag and tag.strip():
        t_clean = tag.strip().lower().lstrip("#")
        filtered = [
            e for e in filtered if any(t_clean == t.lower() for t in e.tags)
        ]

    if theme and theme.strip():
        th_clean = theme.strip().lower()
        filtered = [e for e in filtered if e.weather_theme.lower() == th_clean]

    filtered.sort(key=lambda e: (e.play_count, e.last_played_at), reverse=True)
    return ScrobbleSearchResponse(
        count=len(filtered[:limit]),
        scrobbles=filtered[:limit],
        analytics=analytics,
        synced_from_firestore=_get_firestore_db() is not None,
    )


async def sync_scrobbles_from_lastfm(
    user_id: str, lastfm_username: str = "jpaquay"
) -> ScrobbleSearchResponse:
    """Sync recent/top tracks from Last.fm into Firestore `scrobbles` collection."""
    entries = _ensure_seeded(user_id)
    try:
        from ..container import get_container

        oracle = get_container().oracle()
        if oracle is not None and hasattr(oracle, "recent_tracks"):
            recent = await oracle.recent_tracks(lastfm_username, limit=25)
            existing_keys = {e.track_key.lower() for e in entries}
            now = datetime.now(timezone.utc)
            for idx, tr in enumerate(recent or []):
                title = getattr(tr, "title", None) or getattr(tr, "name", "")
                artist = getattr(tr, "artist", "")
                key = f"{artist} - {title}".lower()
                if title and artist and key not in existing_keys:
                    existing_keys.add(key)
                    new_entry = ScrobbleEntry(
                        id=f"scrobble_{user_id}_lfm_{idx:02d}",
                        user_id=user_id,
                        title=title,
                        artist=artist,
                        album=getattr(tr, "album", None),
                        tags=list(getattr(tr, "tags", None) or ["lastfm-live", "atmospheric"]),
                        weather_theme="petrichor",
                        bpm_estimate=115,
                        energy_estimate=0.65,
                        play_count=5,
                        last_played_at=now - timedelta(minutes=idx * 15),
                    )
                    entries.insert(0, new_entry)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Last.fm live scrobble sync note: %s", exc)

    # Write back to Firestore `scrobbles` collection
    db = _get_firestore_db()
    if db is not None:
        try:
            batch = db.batch()
            col = db.collection("scrobbles")
            for e in entries[:40]:
                doc_ref = col.document(e.id)
                batch.set(doc_ref, e.model_dump(mode="json"), merge=True)
            batch.commit()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Firestore scrobbles sync write note: %s", exc)

    _MEMORY_SCROBBLES[user_id] = entries
    return search_scrobbles(user_id)

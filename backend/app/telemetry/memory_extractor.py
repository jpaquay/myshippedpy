"""Semantic memory extraction and prompt formatting for BaroGroove AI surfaces."""

from __future__ import annotations

import re
import uuid
from typing import Any, Sequence

from .models import ConversationTurn, MemoryRecord
from .store import get_telemetry_store

_KNOWN_ARTISTS = [
    "Massive Attack",
    "Portishead",
    "Burial",
    "Serge Gainsbourg",
    "Chinese Man",
    "Stromae",
    "Khruangbin",
    "Georges Brassens",
    "Bonobo",
    "Air",
    "Neu!",
    "Biga*Ranx",
    "Boards of Canada",
    "Aphex Twin",
    "Four Tet",
    "Brian Eno",
    "Radiohead",
    "Björk",
]

_KNOWN_GENRES = [
    "trip-hop",
    "dub-techno",
    "ambient",
    "post-rock",
    "shoegaze",
    "jazz",
    "krautrock",
    "idm",
    "electronic",
    "downtempo",
    "chanson",
    "dub",
    "techno",
    "lo-fi",
]

_LANDMARK_KEYWORDS = {
    "tokyo": ("shimokitazawa_tokyo", "Shimokitazawa (Tokyo)"),
    "shimokitazawa": ("shimokitazawa_tokyo", "Shimokitazawa (Tokyo)"),
    "sao paulo": ("beco_do_batman_sao_paulo", "Beco do Batman (São Paulo)"),
    "batman": ("beco_do_batman_sao_paulo", "Beco do Batman (São Paulo)"),
    "reykjavik": ("wall_poetry_reykjavik", "Wall Poetry Grandi (Reykjavík)"),
    "berlin": ("east_side_gallery_berlin", "East Side Gallery (Berlin)"),
    "london": ("brick_lane_shoreditch", "Brick Lane & Redchurch St (London)"),
    "shoreditch": ("brick_lane_shoreditch", "Brick Lane & Redchurch St (London)"),
    "brussels": ("parcours_bd_brussels", "Parcours BD (Brussels)"),
    "melbourne": ("hosier_lane_melbourne", "Hosier Lane (Melbourne)"),
}

_POSITIVE_CUES = ("love", "favorite", "always play", "obsessed", "craving", "prefer", "more of", "like", "enjoy")
_NEGATIVE_CUES = ("dislike", "hate", "skip", "avoid", "too fast", "too harsh", "no more", "less of", "never")


def extract_memories_from_turn(
    user_id: str,
    prompt: str,
    selected_geocache: Any = None,
    selected_theme_id: str | None = None,
    selected_genre_id: str | None = None,
    seeded_scrobbles: Sequence[Any] | None = None,
    conversation_id: str | None = None,
    trajectory_id: str | None = None,
) -> list[MemoryRecord]:
    """Extract and persist semantic memories across 7 categories from an AI turn."""
    uid = user_id or "demo"
    text = (prompt or "").strip()
    text_lower = text.lower()
    store = get_telemetry_store()
    extracted: list[MemoryRecord] = []

    def _add(
        category: str,
        subject: str,
        content: str,
        sentiment: str = "positive",
        confidence: float = 0.88,
        tags: list[str] | None = None,
    ) -> None:
        mem = MemoryRecord(
            memory_id=f"mem_{uuid.uuid4().hex[:12]}",
            user_id=uid,
            conversation_id=conversation_id,
            trajectory_id=trajectory_id,
            source_type="conversation_turn",
            category=category,
            subject=subject,
            content=content,
            sentiment=sentiment,
            confidence=confidence,
            tags=sorted(set((tags or []) + [category])),
        )
        stored = store.upsert_memory_sync(mem)
        extracted.append(stored)

    # 1. Landmark affinity (street_art_landmark)
    geo_id = None
    geo_label = None
    if isinstance(selected_geocache, dict):
        geo_id = selected_geocache.get("id") or selected_geocache.get("geocache_id")
        geo_label = selected_geocache.get("label") or selected_geocache.get("name") or geo_id
    elif isinstance(selected_geocache, str) and selected_geocache:
        geo_id = selected_geocache
        geo_label = selected_geocache

    if geo_id:
        from backend.app.sky.geocaches import get_geocache

        resolved = get_geocache(str(geo_id))
        if resolved:
            geo_id = resolved.id
            geo_label = resolved.label

    if not geo_id:
        for kw, (lid, llabel) in _LANDMARK_KEYWORDS.items():
            if kw in text_lower:
                geo_id = lid
                geo_label = llabel
                break

    if geo_id:
        _add(
            category="street_art_landmark",
            subject=f"landmark:{geo_id}",
            content=f"Affinity for street-art landmark {geo_label} ({geo_id}) and its atmospheric soundscape",
            sentiment="positive",
            confidence=0.90,
            tags=["landmark", str(geo_id)],
        )

    # 2. Genre affinity (genre_affinity)
    matched_genres: set[str] = set()
    if selected_genre_id and selected_genre_id != "any":
        matched_genres.add(selected_genre_id.lower())
    for g in _KNOWN_GENRES:
        if re.search(rf"\b{re.escape(g)}\b", text_lower):
            matched_genres.add(g)

    for g in sorted(matched_genres):
        _add(
            category="genre_affinity",
            subject=f"genre:{g}",
            content=f"Prefers {g} sonic corridor and textures",
            sentiment="positive",
            confidence=0.89,
            tags=["genre", g],
        )

    # 3. Artist affinity (artist_affinity)
    matched_artists: set[str] = set()
    for a in _KNOWN_ARTISTS:
        if a.lower() in text_lower:
            matched_artists.add(a)
    if seeded_scrobbles:
        for item in seeded_scrobbles[:3]:
            if isinstance(item, dict):
                art = item.get("artist")
                if art:
                    matched_artists.add(str(art))
            elif isinstance(item, str) and " - " in item:
                matched_artists.add(item.split(" - ")[0].strip())

    for art in sorted(matched_artists):
        slug = re.sub(r"[^a-z0-9]+", "_", art.lower()).strip("_")
        _add(
            category="artist_affinity",
            subject=f"artist:{slug}",
            content=f"High affinity for artist {art}",
            sentiment="positive",
            confidence=0.91,
            tags=["artist", slug],
        )

    # 4. Weather-mood association (weather_mood_association)
    theme = selected_theme_id or ""
    if not theme:
        for t_kw in ("low_pressure", "petrichor", "blue_hour", "storm", "fog", "rain", "golden_hour", "frost"):
            if t_kw in text_lower:
                theme = t_kw
                break
    if theme and (matched_genres or "pressure" in text_lower or "rain" in text_lower or "weather" in text_lower):
        genre_label = next(iter(sorted(matched_genres)), "atmospheric")
        _add(
            category="weather_mood_association",
            subject=f"weather_mood:{theme}:{genre_label}",
            content=f"Associates '{theme}' barometric/weather conditions with {genre_label} soundscapes",
            sentiment="positive",
            confidence=0.87,
            tags=["weather", str(theme), genre_label],
        )

    # 5. Explicit likes (sentiment_like)
    if any(re.search(rf"\b{re.escape(cue)}\b", text_lower) for cue in _POSITIVE_CUES):
        _add(
            category="sentiment_like",
            subject=f"like:{re.sub(r'[^a-z0-9]+', '_', text_lower[:28]).strip('_')}",
            content=f"Explicitly likes: {text[:120]}",
            sentiment="positive",
            confidence=0.93,
            tags=["like", "preference"],
        )

    # 6. Explicit dislikes (sentiment_dislike)
    if any(re.search(rf"\b{re.escape(cue)}\b", text_lower) for cue in _NEGATIVE_CUES):
        _add(
            category="sentiment_dislike",
            subject=f"dislike:{re.sub(r'[^a-z0-9]+', '_', text_lower[:28]).strip('_')}",
            content=f"Explicitly dislikes/avoids: {text[:120]}",
            sentiment="negative",
            confidence=0.95,
            tags=["dislike", "avoid"],
        )

    # 7. General musical preference fallback (musical_preference)
    if text and not extracted:
        _add(
            category="musical_preference",
            subject=f"pref:{re.sub(r'[^a-z0-9]+', '_', text_lower[:28]).strip('_')}",
            content=f"Conversational sonic intent: {text[:120]}",
            sentiment="positive",
            confidence=0.84,
            tags=["preference", "intent"],
        )

    return extracted


def extract_memory_from_feedback(
    user_id: str,
    playlist_id: str,
    track_key: str,
    signal: str,
    artist: str = "",
    title: str = "",
    theme_id: str = "",
    genre_id: str = "",
) -> MemoryRecord:
    """Synthesize and persist a semantic MemoryRecord from Almanac loved/skipped feedback."""
    uid = user_id or "demo"
    sig = (signal or "loved").lower()
    track_label = f"{artist} — {title}".strip(" —") if (artist or title) else track_key
    theme_label = theme_id or "atmospheric"
    genre_label = genre_id or "any"

    if sig == "skipped":
        category = "sentiment_dislike"
        sentiment = "negative"
        confidence = 0.78
        content = f"Skipped track '{track_label}' under '{theme_label}' sky"
        tags = ["almanac", "skipped", track_key, theme_label]
    else:
        category = "sentiment_like"
        sentiment = "positive"
        confidence = 0.95
        content = f"Loved track '{track_label}' under '{theme_label}' sky ({genre_label})"
        tags = ["almanac", "loved", track_key, theme_label, genre_label]

    mem = MemoryRecord(
        memory_id=f"mem_{uuid.uuid4().hex[:12]}",
        user_id=uid,
        source_type="almanac_feedback",
        category=category,
        subject=f"track:{track_key}",
        content=content,
        sentiment=sentiment,
        confidence=confidence,
        tags=sorted(set(tags)),
    )
    return get_telemetry_store().upsert_memory_sync(mem)


def format_memories_for_prompt(memories: Sequence[MemoryRecord]) -> str:
    """Format user semantic memories into a system instruction block."""
    if not memories:
        return ""
    lines = [
        "KNOWN USER PREFERENCES & SEMANTIC MEMORIES (learned across sessions & Almanac feedback):"
    ]
    for m in memories[:10]:
        tag = m.category.upper().replace("_", " ")
        lines.append(
            f"- [{tag} | sentiment: {m.sentiment} | conf: {m.confidence:.2f} | reinforced: {m.reinforcement_count}x] {m.content}"
        )
    return "\n".join(lines)


def format_recent_turns_for_prompt(turns: Sequence[ConversationTurn]) -> str:
    """Format recent conversation turns into a system instruction block for multi-turn continuity."""
    if not turns:
        return ""
    lines = [
        "RECENT CONVERSATION HISTORY (maintain multi-turn conversational continuity with these prior turns):"
    ]
    for t in turns[-6:]:
        role_label = t.role.upper()
        lines.append(f"- [{role_label}]: {t.content}")
    return "\n".join(lines)

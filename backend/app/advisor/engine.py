"""Gemini Live Forge Advisor & Executor Engine.

Bridges natural spoken voice/text prompts to BaroGroove's Weathercaster,
World Street-Art Geo-Caches, Firestore Sonic Almanac Scrobbles, and the
18-track Weather-Inspired Daylist Forge Engine.

Uses Vertex AI Gemini 2.5 Flash (`gemini-2.5-flash`) via Google Cloud ADC
with multimodal audio/text support and structured JSON action generation,
plus a deterministic Semantic Forge Agent fallback for offline/unit testing.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx
from pydantic import BaseModel, Field

from backend.app.almanac.scrobbles import ScrobbleEntry, search_scrobbles
from backend.app.container import get_container
from backend.app.contracts import Coordinates, ForgeRequest, ForgeResult
from backend.app.routes.surfaces import record_recent_playlist
from backend.app.sky.geocaches import (
    STREET_ART_GEOCACHES,
    StreetArtGeoCache,
    get_geocache,
    pick_random_geocache,
)

logger = logging.getLogger(__name__)


class AdvisorActionBadge(BaseModel):
    """Telemetry badge describing an autonomous action executed by Gemini Live."""

    tool: str = Field(..., description="Tool identifier executed")
    label: str = Field(..., description="Short human-readable headline")
    detail: str = Field(default="", description="Additional context or parameters")


class AdvisorLiveRequest(BaseModel):
    """Request payload for a conversational or voice turn with the Gemini Live Advisor."""

    prompt: str | None = Field(
        default=None,
        description="Spoken transcript or typed natural-language prompt from the user.",
    )
    audio_base64: str | None = Field(
        default=None,
        description="Optional raw microphone audio encoded as base64 (e.g. audio/webm or audio/wav).",
    )
    audio_mime_type: str | None = Field(
        default="audio/webm",
        description="MIME type of the uploaded audio_base64.",
    )
    current_geocache_id: str | None = Field(
        default=None,
        description="Currently selected world street-art landmark ID, if any.",
    )
    current_theme_id: str | None = Field(
        default=None,
        description="Currently active atmospheric theme ID.",
    )
    current_genre_id: str | None = Field(
        default=None,
        description="Currently active genre corridor ID.",
    )
    auto_forge: bool = Field(
        default=True,
        description="Whether to automatically execute a full 18-track Daylist forge when parameters change.",
    )


class AdvisorLiveResponse(BaseModel):
    """Complete advisor response + executed Forge state update."""

    reply_text: str = Field(..., description="Full atmospheric advisor commentary.")
    spoken_summary: str = Field(
        ...,
        description="Concise, natural voice script optimized for Web Speech / Audio synthesis.",
    )
    transcript: str = Field(
        default="",
        description="Recognized speech transcript or user prompt.",
    )
    actions_executed: list[AdvisorActionBadge] = Field(
        default_factory=list,
        description="Ordered list of autonomous actions executed during this turn.",
    )
    selected_geocache: dict[str, Any] | None = Field(
        default=None,
        description="World Street-Art Geo-Cache selected or teleported to.",
    )
    selected_theme_id: str | None = Field(
        default=None,
        description="Selected atmospheric theme ID.",
    )
    selected_genre_id: str | None = Field(
        default=None,
        description="Selected sonic genre corridor ID.",
    )
    seeded_scrobbles: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Scrobbles selected from the user's Firestore Almanac to seed the forge.",
    )
    forge_result: ForgeResult | None = Field(
        default=None,
        description="The newly forged 18-track Weather-Inspired Daylist, ready for playback.",
    )
    model_used: str = Field(
        default="gemini-2.5-flash (vertex-ai)",
        description="Model that processed the advisor turn.",
    )


class AdvisorSuggestionItem(BaseModel):
    """Quick voice/tap prompt suggestion for desktop & mobile UI."""

    id: str
    title: str
    prompt: str
    geocache_id: str
    badge: str


from backend.app.sonic.corridors import get_corridor

_VALID_THEMES: dict[str, str] = {
    "low_pressure_front": "Storm Front (brooding low-pressure drop, deep bass & sub-heavy tension)",
    "blue_hour": "Blue Hour Drift (twilight transition, atmospheric ambient & nocturnal dub)",
    "clear_high": "High Pressure Clarity (crisp ridge, soaring anticyclonic energy & motorik drive)",
    "petrichor": "Petrichor & Rain (steady rainfall, warm Rhodes, vinyl crackle & lo-fi textures)",
    "midnight_thermal": "Midnight Thermal (late-night urban heat island, deep club & hypnotic techno)",
    "solar_zenith": "Solar Zenith (bright high-altitude sun, upbeat groove, funk & tropicalia)",
}

_VALID_GENRES: dict[str, str] = {
    "any": "All Corridors (balanced atmospheric curation)",
    "trip-hop": "Trip-Hop & Bristol Sound",
    "dub-techno": "Dub Techno & Deep Chords",
    "ambient": "Ambient & Drone Landscapes",
    "post-rock": "Post-Rock & Cinematic Crescendos",
    "shoegaze": "Shoegaze & Dream Pop",
    "jazz": "Spiritual Jazz & Late-Night Horns",
    "krautrock": "Krautrock & Motorik Pulse",
    "idm": "IDM & Glitch Electronica",
}


def _get_vertex_token() -> tuple[str | None, str]:
    """Retrieve a Google Cloud bearer token and project ID via Application Default Credentials."""
    project_id = os.environ.get("BG_GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "netdev-firebase"
    try:
        import google.auth
        import google.auth.transport.requests

        creds, detected_project = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        creds.refresh(google.auth.transport.requests.Request())
        return creds.token, detected_project or project_id
    except Exception as exc:
        logger.debug("Vertex AI ADC token unavailable (%s); using semantic fallback", exc)
        return None, project_id


def _build_system_instruction(
    geocaches: list[StreetArtGeoCache],
    scrobbles: list[ScrobbleEntry],
    current_geocache_id: str | None,
    current_theme_id: str | None,
    current_genre_id: str | None,
) -> str:
    """Build the grounded system prompt for Gemini 2.5 Flash."""
    geo_lines = [
        f"- id: '{g.id}' | {g.name} ({g.city}, {g.country}) | local_time: {g.local_time_label()} ({g.day_period()}) | vibe_tags: {', '.join(g.vibe_tags)}"
        for g in geocaches
    ]
    scrobble_lines = [
        f"- id: '{s.id}' | {s.artist} — {s.title} | tags: {', '.join(s.tags)} | theme: {s.weather_theme} ({s.bpm_estimate} BPM)"
        for s in scrobbles[:25]
    ]
    theme_lines = [f"- '{k}': {v}" for k, v in _VALID_THEMES.items()]
    genre_lines = [f"- '{k}': {v}" for k, v in _VALID_GENRES.items()]

    return f"""You are the **BaroGroove Gemini Live Forge Advisor & Executor**, an atmospheric sonic meteorologist and expert DJ.
The user speaks or writes to you from desktop or mobile to explore weather-inspired music, teleport across iconic World Street-Art Landmarks, seed tracks from their Firestore Sonic Almanac (Last.fm scrobble history), and immediately forge an 18-track Weather-Inspired Daylist.

Current UI State:
- Current Geo-Cache ID: {current_geocache_id or 'Brussels default'}
- Current Theme ID: {current_theme_id or 'auto'}
- Current Genre ID: {current_genre_id or 'any'}

Available World Street-Art Geo-Caches (choose `geocache_id` from this list when teleporting or matching a city/vibe/timezone):
{chr(10).join(geo_lines)}

Available Atmospheric Themes (`theme_id`):
{chr(10).join(theme_lines)}

Available Genre Corridors (`genre_id`):
{chr(10).join(genre_lines)}

User's Firestore Sonic Almanac Scrobbles (choose up to 4 `scrobble_ids` that match the user's artist/mood/weather request):
{chr(10).join(scrobble_lines)}

INSTRUCTIONS:
1. Analyze the user's spoken/written request (or audio recording).
2. Choose the best matching `geocache_id` (or pick an exciting street-art landmark whose local time of day or regional vibe matches the user's request).
3. Choose the best matching `theme_id` and `genre_id`.
4. Select 1 to 4 relevant `scrobble_ids` from the user's Almanac that anchor the sonic mood.
5. Set `should_forge` to true whenever the user wants music, a set, a playlist, a daylist, a teleport, or a vibe shift.
6. Write a warm, charismatic, concise `spoken_summary` (2 sentences max, written for voice synthesis) that sounds like an intelligent late-night radio host announcing the teleport destination, local time/weather, and the newly forged Daylist.
7. Write a rich `reply_text` with atmospheric details.

Return ONLY valid JSON matching this schema:
{{
  "transcript": "what the user said or asked for",
  "geocache_id": "string (one of the valid geocache IDs above)",
  "theme_id": "string (one of the valid theme IDs above)",
  "genre_id": "string (one of the valid genre IDs above)",
  "scrobble_ids": ["list of 1-4 matching scrobble IDs from above"],
  "should_forge": true,
  "spoken_summary": "concise 2-sentence voice script for speech synthesis",
  "reply_text": "detailed atmospheric commentary explaining the street-art landmark, local solar hour, barometric pressure trend, and scrobble DNA seeds"
}}"""


def _semantic_fallback_plan(
    prompt: str,
    geocaches: list[StreetArtGeoCache],
    scrobbles: list[ScrobbleEntry],
    current_geocache_id: str | None,
    current_theme_id: str | None,
    current_genre_id: str | None,
) -> dict[str, Any]:
    """Deterministic Semantic Forge Agent fallback when Vertex AI is offline or in unit tests."""
    p_lower = (prompt or "surprise me with a global street-art daylist").lower()

    # 1. Match Geo-Cache by city, name, country, or vibe tag
    chosen_geo: StreetArtGeoCache | None = None
    for g in geocaches:
        if (
            g.city.lower() in p_lower
            or g.name.lower() in p_lower
            or g.country.lower() in p_lower
            or any(tag.lower() in p_lower for tag in g.vibe_tags)
        ):
            chosen_geo = g
            break

    if chosen_geo is None:
        if "night" in p_lower or "tokyo" in p_lower or "japan" in p_lower or "dub" in p_lower:
            chosen_geo = get_geocache("shimokitazawa_tokyo")
        elif "latin" in p_lower or "brazil" in p_lower or "bossa" in p_lower or "morning" in p_lower:
            chosen_geo = get_geocache("beco_do_batman_sao_paulo")
        elif "storm" in p_lower or "rain" in p_lower or "iceland" in p_lower or "cold" in p_lower:
            chosen_geo = get_geocache("reykjavik_wall_poetry")
        elif "london" in p_lower or "uk" in p_lower or "garage" in p_lower or "bristol" in p_lower:
            chosen_geo = get_geocache("shoreditch_brick_lane_london")
        elif "berlin" in p_lower or "techno" in p_lower or "club" in p_lower:
            chosen_geo = get_geocache("east_side_gallery_berlin")
        else:
            chosen_geo = pick_random_geocache()

    # 2. Match Theme
    chosen_theme = current_theme_id or "blue_hour"
    if any(w in p_lower for w in ["storm", "thunder", "drop", "heavy", "dark", "low pressure"]):
        chosen_theme = "low_pressure_front"
    elif any(w in p_lower for w in ["rain", "petrichor", "drizzle", "wet", "lofi", "lo-fi"]):
        chosen_theme = "petrichor"
    elif any(w in p_lower for w in ["clear", "high", "crisp", "focus", "motorik"]):
        chosen_theme = "clear_high"
    elif any(w in p_lower for w in ["midnight", "club", "heat", "late night", "techno"]):
        chosen_theme = "midnight_thermal"
    elif any(w in p_lower for w in ["sun", "solar", "bright", "morning", "warm", "bossa"]):
        chosen_theme = "solar_zenith"
    elif any(w in p_lower for w in ["twilight", "blue hour", "dusk", "sunset", "drift"]):
        chosen_theme = "blue_hour"

    # 3. Match Genre
    chosen_genre = current_genre_id or "any"
    if any(w in p_lower for w in ["trip-hop", "trip hop", "bristol", "massive attack", "portishead"]):
        chosen_genre = "trip-hop"
    elif any(w in p_lower for w in ["dub techno", "dub", "basic channel", "chord"]):
        chosen_genre = "dub-techno"
    elif any(w in p_lower for w in ["ambient", "drone", "eno", "sleep", "calm"]):
        chosen_genre = "ambient"
    elif any(w in p_lower for w in ["post-rock", "post rock", "mogwai", "crescendo"]):
        chosen_genre = "post-rock"
    elif any(w in p_lower for w in ["shoegaze", "dream pop", "mbv", "slowdive"]):
        chosen_genre = "shoegaze"
    elif any(w in p_lower for w in ["jazz", "noir", "saxophone", "miles"]):
        chosen_genre = "jazz"
    elif any(w in p_lower for w in ["krautrock", "motorik", "neu", "synth"]):
        chosen_genre = "krautrock"
    elif any(w in p_lower for w in ["idm", "glitch", "aphex", "boards of canada", "autechre"]):
        chosen_genre = "idm"
    chosen_genre = get_corridor(chosen_genre).id

    # 4. Match Scrobbles from Almanac
    matched_scrobble_ids: list[str] = []
    words = [w for w in re.split(r"\W+", p_lower) if len(w) >= 3]
    for s in scrobbles:
        haystack = f"{s.artist} {s.title} {' '.join(s.tags)} {s.weather_theme}".lower()
        if any(w in haystack for w in words):
            matched_scrobble_ids.append(s.id)
            if len(matched_scrobble_ids) >= 3:
                break

    if not matched_scrobble_ids and scrobbles:
        theme_matches = [s.id for s in scrobbles if s.weather_theme == chosen_theme]
        matched_scrobble_ids = (theme_matches or [s.id for s in scrobbles])[:2]

    scrobble_names = [
        f"{s.artist} ('{s.title}')"
        for s in scrobbles
        if s.id in matched_scrobble_ids
    ]
    seed_desc = f"anchored by {', '.join(scrobble_names)}" if scrobble_names else "curated from your Sonic Almanac"

    spoken = (
        f"Teleporting your Weathercaster to {chosen_geo.name} in {chosen_geo.city}, where it is currently {chosen_geo.day_period()} ({chosen_geo.local_time_label()}). "
        f"I've seeded your Almanac history and forged an 18-track {_VALID_THEMES.get(chosen_theme, chosen_theme).split('(')[0].strip()} Daylist. Starting playback now!"
    )
    reply = (
        f"**Gemini Live Forge Executed** • Teleported to **{chosen_geo.name}** ({chosen_geo.city}, {chosen_geo.country} • `{chosen_geo.local_time_label()}`).\n\n"
        f"- **Atmospheric Theme**: `{chosen_theme}` ({_VALID_THEMES.get(chosen_theme, '')})\n"
        f"- **Genre Corridor**: `{chosen_genre}` ({_VALID_GENRES.get(chosen_genre, '')})\n"
        f"- **Almanac DNA Seeds**: {seed_desc}\n\n"
        f"Your 18-track Weather-Inspired Daylist is now loaded in the Player Deck."
    )

    return {
        "transcript": prompt or "Voice teleport & forge request",
        "geocache_id": chosen_geo.id,
        "theme_id": chosen_theme,
        "genre_id": chosen_genre,
        "scrobble_ids": matched_scrobble_ids,
        "should_forge": True,
        "spoken_summary": spoken,
        "reply_text": reply,
        "model_used": "gemini-2.5-flash (semantic-agent)",
    }


def _call_vertex_gemini(
    req: AdvisorLiveRequest,
    system_instruction: str,
    token: str,
    project_id: str,
) -> dict[str, Any] | None:
    """Call Vertex AI Gemini 2.5 Flash with multimodal parts and structured JSON schema."""
    region = os.environ.get("BG_GCP_REGION", "europe-west1")
    url = (
        f"https://{region}-aiplatform.googleapis.com/v1/projects/{project_id}"
        f"/locations/{region}/publishers/google/models/gemini-2.5-flash:generateContent"
    )

    parts: list[dict[str, Any]] = []
    if req.audio_base64:
        parts.append(
            {
                "inlineData": {
                    "mimeType": req.audio_mime_type or "audio/webm",
                    "data": req.audio_base64,
                }
            }
        )
    user_text = req.prompt or (
        "Listen to my voice request and forge the ideal Weather-Inspired Daylist "
        "by choosing a world street-art landmark, atmospheric theme, genre, and Almanac scrobbles."
    )
    parts.append({"text": user_text})

    payload = {
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0.4,
            "responseMimeType": "application/json",
        },
    }

    try:
        with httpx.Client(timeout=25.0) as client:
            resp = client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
            )
            if resp.status_code != 200:
                logger.warning(
                    "Vertex AI Gemini returned status %s: %s",
                    resp.status_code,
                    resp.text[:300],
                )
                return None
            data = resp.json()
            candidates = data.get("candidates") or []
            if not candidates:
                return None
            content_parts = candidates[0].get("content", {}).get("parts", [])
            if not content_parts:
                return None
            raw_text = content_parts[0].get("text", "")
            parsed = json.loads(raw_text)
            parsed["model_used"] = "gemini-2.5-flash (vertex-ai)"
            return parsed
    except Exception as exc:
        logger.warning("Vertex AI Gemini call failed (%s); falling back to semantic agent", exc)
        return None


def get_advisor_suggestions(user_id: str = "demo") -> list[AdvisorSuggestionItem]:
    """Return 4 dynamic voice/tap prompts grounded in world timezones and Almanac DNA."""
    tokyo = get_geocache("shimokitazawa_tokyo")
    sao_paulo = get_geocache("beco_do_batman_sao_paulo")
    reykjavik = get_geocache("reykjavik_wall_poetry")
    berlin = get_geocache("east_side_gallery_berlin")

    return [
        AdvisorSuggestionItem(
            id="tokyo_night_triphop",
            title=f"Tokyo • {tokyo.local_time_label() if tokyo else 'UTC+9'}",
            prompt="Teleport to Shimokitazawa in Tokyo and forge a late-night Blue Hour Trip-Hop set seeded with my Massive Attack and Burial scrobbles.",
            geocache_id="shimokitazawa_tokyo",
            badge="🎙️ Late Night Dub & Trip-Hop",
        ),
        AdvisorSuggestionItem(
            id="saopaulo_bossa_drift",
            title=f"São Paulo • {sao_paulo.local_time_label() if sao_paulo else 'UTC-3'}",
            prompt="Take me to Beco do Batman in São Paulo and forge a warm tropicalia & bossa-nova daylist matching local solar time.",
            geocache_id="beco_do_batman_sao_paulo",
            badge="🎙️ Tropicalia & Solar Groove",
        ),
        AdvisorSuggestionItem(
            id="reykjavik_storm_ambient",
            title=f"Reykjavík • {reykjavik.local_time_label() if reykjavik else 'UTC+0'}",
            prompt="Teleport to Reykjavík Wall Poetry and forge a brooding Low Pressure Storm Front ambient & post-rock set from my Almanac.",
            geocache_id="reykjavik_wall_poetry",
            badge="🎙️ Sub-Arctic Storm Front",
        ),
        AdvisorSuggestionItem(
            id="berlin_dub_techno",
            title=f"Berlin • {berlin.local_time_label() if berlin else 'UTC+1'}",
            prompt="Teleport to East Side Gallery in Berlin and forge a hypnotic Midnight Thermal Dub Techno daylist.",
            geocache_id="east_side_gallery_berlin",
            badge="🎙️ Spree River Dub Techno",
        ),
    ]


class AdvisorEngine:
    """Orchestrates Gemini Live conversational advice and autonomous Forge execution."""

    async def execute_turn(
        self,
        req: AdvisorLiveRequest,
        user_id: str = "demo",
    ) -> AdvisorLiveResponse:
        """Process a voice/text turn, execute tools, and return the forged Daylist."""
        geocaches = list(STREET_ART_GEOCACHES)
        scrobble_data = search_scrobbles(user_id, limit=60)
        scrobbles = scrobble_data.scrobbles

        token, project_id = _get_vertex_token()
        plan: dict[str, Any] | None = None

        if token:
            sys_prompt = _build_system_instruction(
                geocaches=geocaches,
                scrobbles=scrobbles,
                current_geocache_id=req.current_geocache_id,
                current_theme_id=req.current_theme_id,
                current_genre_id=req.current_genre_id,
            )
            plan = _call_vertex_gemini(req, sys_prompt, token, project_id)

        if not plan:
            plan = _semantic_fallback_plan(
                prompt=req.prompt or "",
                geocaches=geocaches,
                scrobbles=scrobbles,
                current_geocache_id=req.current_geocache_id,
                current_theme_id=req.current_theme_id,
                current_genre_id=req.current_genre_id,
            )

        # Resolve parameters
        geo_id = plan.get("geocache_id") or req.current_geocache_id
        selected_geo = get_geocache(geo_id) if geo_id else pick_random_geocache()
        if selected_geo is None:
            selected_geo = pick_random_geocache()

        theme_id = plan.get("theme_id") or req.current_theme_id or "blue_hour"
        if theme_id not in _VALID_THEMES:
            theme_id = "blue_hour"

        raw_genre = plan.get("genre_id") or req.current_genre_id or "any"
        genre_id = get_corridor(raw_genre).id

        scrobble_ids: list[str] = plan.get("scrobble_ids") or []
        scrobble_map = {s.id: s for s in scrobbles}
        seeded_entries = [scrobble_map[sid] for sid in scrobble_ids if sid in scrobble_map]

        actions: list[AdvisorActionBadge] = []

        # Action 1: Teleport Geo-Cache
        actions.append(
            AdvisorActionBadge(
                tool="teleport_geocache",
                label=f"Teleported to {selected_geo.name} ({selected_geo.city})",
                detail=f"Local solar time: {selected_geo.local_time_label()} ({selected_geo.day_period()}) • Vibes: {', '.join(selected_geo.vibe_tags[:3])}",
            )
        )

        # Action 2: Select Sonic Parameters
        actions.append(
            AdvisorActionBadge(
                tool="select_sonic_parameters",
                label=f"Theme: {theme_id.replace('_', ' ').title()} • Genre: {genre_id.replace('-', ' ').title()}",
                detail=_VALID_THEMES.get(theme_id, ""),
            )
        )

        # Action 3: Almanac Seed Scrobbles
        if seeded_entries:
            seed_titles = ", ".join(f"{s.artist} - {s.title}" for s in seeded_entries[:3])
            actions.append(
                AdvisorActionBadge(
                    tool="seed_from_almanac",
                    label=f"Seeded {len(seeded_entries)} Almanac Scrobble(s)",
                    detail=seed_titles,
                )
            )

        # Action 4: Execute 18-Track Weather-Inspired Daylist Forge
        forge_res: ForgeResult | None = None
        should_forge = bool(plan.get("should_forge", True)) and req.auto_forge
        if should_forge:
            forge_req = ForgeRequest(
                coords=Coordinates(
                    latitude=selected_geo.lat,
                    longitude=selected_geo.lon,
                    label=selected_geo.label,
                ),
                user_id=user_id,
                lastfm_user="jpaquay",
                theme_id=theme_id,
                genre_id=genre_id,
                geocache_id=selected_geo.id,
                seed_scrobbles=[s.id for s in seeded_entries],
            )
            forge_res = await get_container().forge().forge(forge_req)
            record_recent_playlist(forge_res.playlist)

            actions.append(
                AdvisorActionBadge(
                    tool="execute_forge",
                    label=f"Forged 18-Track Daylist: {forge_res.playlist.title}",
                    detail=f"Barometric trend: {forge_res.playlist.sky.pressure_trend_6h:+.2f} hPa/6h • Saved to Almanac",
                )
            )

        return AdvisorLiveResponse(
            reply_text=plan.get("reply_text") or plan.get("spoken_summary") or "Forged your Weather-Inspired Daylist.",
            spoken_summary=plan.get("spoken_summary") or "I've teleported your Weathercaster and forged a fresh 18-track Daylist.",
            transcript=plan.get("transcript") or req.prompt or "Voice command processed",
            actions_executed=actions,
            selected_geocache=selected_geo.to_dict(),
            selected_theme_id=theme_id,
            selected_genre_id=genre_id,
            seeded_scrobbles=[s.model_dump() for s in seeded_entries],
            forge_result=forge_res,
            model_used=plan.get("model_used", "gemini-2.5-flash (vertex-ai)"),
        )

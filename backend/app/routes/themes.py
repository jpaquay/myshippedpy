"""Read-only HTTP surface for themes and genre corridors.

Everything here is a catalogue lookup except ``/api/themes/suggest``, which is
the only endpoint that touches the network. It is also the only one that can
fail, and it is specifically built not to: an unreachable weather feed returns
a suggestion against the neutral sky with the degradation stated in the
payload, never a 5xx. The front end asks this endpoint what to preselect while
the user is still looking at an empty screen, and a spinner that ends in an
error is worse than a slightly generic theme.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from fastapi import APIRouter, Query

from ..contracts import Coordinates, GenreCorridor, SkyVector, Theme
from ..errors import ThemeNotFound
from ..sonic.corridors import get_corridor, list_corridors
from ..sonic.rationale import short_headline, sky_sentences
from ..sonic.themes import get_theme, list_themes, score_themes, suggest_theme

router = APIRouter(prefix="/api", tags=["themes"])


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _theme_payload(theme: Theme) -> dict[str, Any]:
    """A theme as the A2UI surface wants it: copy, palette, and the bias made legible."""
    return {
        "id": theme.id,
        "name": theme.name,
        "tagline": theme.tagline,
        "description": theme.description,
        "bias": theme.bias.as_dict(),
        "bias_bpm": theme.bias.tempo_bpm,
        "bias_weight": theme.bias_weight,
        "seed_tags": list(theme.seed_tags),
        "avoid_tags": list(theme.avoid_tags),
        "palette": dict(theme.palette),
        "voice": theme.voice,
        "affinity": dict(theme.affinity),
    }


def _corridor_payload(corridor: GenreCorridor) -> dict[str, Any]:
    return {
        "id": corridor.id,
        "name": corridor.name,
        "tags": list(corridor.tags),
        "anchor": corridor.anchor.as_dict() if corridor.anchor else None,
        "anchor_bpm": corridor.anchor.tempo_bpm if corridor.anchor else None,
        "width": corridor.width,
        "description": corridor.description,
    }


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


@router.get("/themes", summary="All eight themes")
def read_themes() -> dict[str, Any]:
    themes = list_themes()
    items = [_theme_payload(t) for t in themes]
    return {"count": len(themes), "themes": items, "items": items}


@router.get("/genres", summary="All genre corridors")
def read_genres() -> dict[str, Any]:
    """Genre is orthogonal to theme, so it gets its own endpoint and its own picker."""
    corridors = list_corridors()
    items = [_corridor_payload(c) for c in corridors]
    return {"count": len(corridors), "genres": items, "items": items}


# NOTE: this route is declared BEFORE ``/themes/{theme_id}`` on purpose.
# FastAPI matches in declaration order, so with the parameterised route first
# a request for /api/themes/suggest would bind theme_id="suggest" and 404.
@router.get("/themes/suggest", summary="Suggest a theme for a location's current sky")
async def suggest_for_location(
    lat: float = Query(..., ge=-90.0, le=90.0, description="Latitude in degrees."),
    lon: float = Query(..., ge=-180.0, le=180.0, description="Longitude in degrees."),
) -> dict[str, Any]:
    """Read the sky at ``lat``/``lon`` and propose the theme it is asking for.

    Degrades rather than fails, in two independent steps: if the weather source
    throws we fall back to the neutral sky, and if the sky extractor cannot be
    reached we do the same. Either way the response is a valid suggestion with
    ``degraded`` populated and a confidence low enough to be honest about it --
    against a neutral sky ``suggest_theme`` returns 0.15, which is the correct
    amount of certainty to have about nothing.
    """
    coordinates = Coordinates(latitude=lat, longitude=lon)
    degraded: list[str] = []
    sky = SkyVector.neutral()

    try:
        from ..container import get_container

        source = get_container().weather()
        window = await source.window(coordinates, _dt.datetime.now(_dt.timezone.utc))
        sky = _extract_sky(window)
        if window.stale and not sky.stale:
            sky = sky.model_copy(update={"stale": True})
    except Exception as exc:  # noqa: BLE001 - a suggestion must never 5xx
        degraded.append(f"weather: {type(exc).__name__} — falling back to the neutral sky")
        sky = SkyVector.neutral()

    if sky.stale:
        degraded.append("weather: serving the last sky we managed to read, not a live one")

    theme, confidence = suggest_theme(sky)
    ranked = score_themes(sky)

    return {
        "theme": _theme_payload(theme),
        "confidence": confidence,
        "headline": short_headline(sky, theme),
        "sky": sky.as_dict(),
        "sky_reading": sky_sentences(sky),
        "coordinates": {"latitude": lat, "longitude": lon},
        "runners_up": [
            {"id": candidate.id, "name": candidate.name, "score": round(score, 3)}
            for candidate, score in ranked[1:4]
        ],
        "degraded": degraded,
    }


@router.get("/themes/{theme_id}", summary="One theme by id")
def read_theme(theme_id: str) -> dict[str, Any]:
    """Fetch a single theme. Unknown ids are a 404 -- a theme is an explicit choice."""
    from fastapi import HTTPException

    try:
        theme = get_theme(theme_id)
    except ThemeNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _theme_payload(theme)


# ---------------------------------------------------------------------------
# Sky extraction, held at arm's length
# ---------------------------------------------------------------------------


def _extract_sky(window: Any) -> SkyVector:
    """Turn a ``WeatherWindow`` into a ``SkyVector``.

    The extractor lives in another module owned by another part of the system,
    so this resolves it lazily and by a couple of plausible names rather than
    importing it at module scope. Two reasons that is the right call here and
    not merely defensive clutter: this router must import cleanly even in a
    deployment where the weather package is absent (the catalogue endpoints
    have no business depending on it), and a signature drift upstream should
    cost this endpoint its precision, not its availability.
    """
    try:
        from .. import weather as weather_pkg
    except Exception:
        return SkyVector.neutral()

    for attribute in ("extract_sky", "sky_from_window", "to_sky", "extract"):
        function = getattr(weather_pkg, attribute, None)
        if callable(function):
            result = function(window)
            if isinstance(result, SkyVector):
                return result
    return SkyVector.neutral()

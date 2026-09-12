"""BAROGROOVE's A2UI v1.0 layer: one UI definition, two surfaces.

  * :mod:`.protocol`  -- typed pydantic models for the A2UI v1.0 envelope.
  * :mod:`.palette`   -- design tokens and the eight theme tints.
  * :mod:`.catalog`   -- the component catalog, declared once, as data.
  * :mod:`.surfaces`  -- the builders. THE SINGLE SOURCE OF UI TRUTH.

The Flutter app is a renderer pointed at ``frontend/a2ui/catalog.json``; the MCP
server emits the identical JSON that :mod:`.surfaces` produces. Nobody builds
this UI twice.
"""

from __future__ import annotations

from .catalog import CATALOG, CATALOG_ID, catalog_json
from .protocol import A2UI_MIME_TYPE, A2UI_VERSION, envelope, stream, validate_stream
from .surfaces import (
    build_almanac_surface,
    build_error_surface,
    build_playlist_surface,
    build_rationale_surface,
    build_sky_surface,
    build_themes_surface,
    single_message,
)

__all__ = [
    "A2UI_VERSION",
    "A2UI_MIME_TYPE",
    "CATALOG",
    "CATALOG_ID",
    "catalog_json",
    "envelope",
    "stream",
    "validate_stream",
    "single_message",
    "build_sky_surface",
    "build_themes_surface",
    "build_playlist_surface",
    "build_rationale_surface",
    "build_almanac_surface",
    "build_error_surface",
]

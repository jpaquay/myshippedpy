"""Configuration and secret loading.

Precedence, highest first:

1. Real environment variables.
2. ``.env`` in the repo root (local dev only, never committed).
3. Google Secret Manager, when ``BG_USE_SECRET_MANAGER=1`` and we can reach it.
4. The declared default.

Nothing in this file, and nothing in ``.env.example``, may contain a real
secret. Secret Manager references are strings like
``projects/<proj>/secrets/<name>/versions/latest`` and are resolved lazily so
that importing this module never blocks on network.
"""

from __future__ import annotations

import functools
import logging
import os
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("barogroove.config")

REPO_ROOT = Path(__file__).resolve().parents[2]

Environment = Literal["local", "dev", "prod"]


class Settings(BaseSettings):
    """Every knob BAROGROOVE has. Stub-friendly by design.

    With an empty environment this yields a fully bootable app in
    ``local`` mode: fixture weather, no Last.fm, M3U sink only. That is the
    contract that makes ``uvicorn app:app`` work with zero credentials.
    """

    model_config = SettingsConfigDict(
        env_prefix="BG_",
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- identity ----------------------------------------------------------
    app_name: str = "barogroove"
    environment: Environment = "local"
    public_host: str = "bg.netdev.be"
    log_level: str = "INFO"

    # --- google cloud ------------------------------------------------------
    gcp_project: str = ""
    gcp_region: str = "europe-west1"  # user standard, non-negotiable
    use_secret_manager: bool = False

    # --- firebase ----------------------------------------------------------
    firebase_project_id: str = ""
    firebase_web_api_key: str = ""
    firestore_database: str = "(default)"
    #: When true we accept unverified bearer tokens as {"sub": token}. Local only.
    auth_allow_insecure_dev_tokens: bool = True

    # --- mcp ---------------------------------------------------------------
    #: Serve the MCP endpoint at all.
    #:
    #: OFF for now, by decision, not by accident. The agent surface is built
    #: and tested but not yet exposed: /mcp is simply not mounted, so the
    #: endpoint 404s rather than existing-and-refusing. Nothing else about the
    #: app changes -- the REST API, the A2UI surfaces and the Flutter client
    #: are unaffected, and `backend/app/mcp/` keeps its full test coverage.
    #:
    #: Flip to True (or set BG_MCP_ENABLED=1) to turn it back on. Before you
    #: do, re-read backend/app/mcp/principal.py: the tools behind this endpoint
    #: spend real listeners' credentials, and the guard is the only thing
    #: standing between an anonymous caller and someone's Spotify account.
    mcp_enabled: bool = False

    #: Require a verified bearer token on /mcp, including the initialize and
    #: tools/list handshake. Defaults on: the MCP tools can spend a listener's
    #: third-party quota and write to their Spotify account, so an anonymous
    #: caller has no business reaching them. Turning this off is honoured only
    #: in the local environment (see `anonymous_mcp_allowed`), and even then no
    #: principal is bound, so user-scoped tools keep refusing.
    #:
    #: Independent of `mcp_enabled`: this governs how the endpoint behaves when
    #: it is served, not whether it is served.
    mcp_require_auth: bool = True

    # --- open-meteo --------------------------------------------------------
    open_meteo_base: str = "https://api.open-meteo.com/v1/forecast"
    open_meteo_past_days: int = 7
    weather_cache_ttl_s: int = 900
    weather_offline: bool = Field(
        False, description="Force fixture weather. Set by tests and the offline demo path."
    )

    # --- last.fm -----------------------------------------------------------
    lastfm_base: str = "https://ws.audioscrobbler.com/2.0/"
    lastfm_api_key: str = ""
    lastfm_api_secret: str = ""
    lastfm_enabled: bool = True

    # --- spotify -----------------------------------------------------------
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    spotify_redirect_uri: str = "https://bg.netdev.be/api/pair/spotify/callback"
    spotify_api_base: str = "https://api.spotify.com/v1"
    spotify_accounts_base: str = "https://accounts.spotify.com"

    # --- crypto ------------------------------------------------------------
    #: Fernet key used to encrypt per-user provider tokens at rest in Firestore.
    #: Empty in local mode => tokens are stored with a loud "INSECURE-DEV" marker.
    token_encryption_key: str = ""

    # --- http behaviour ----------------------------------------------------
    http_timeout_s: float = 8.0
    http_connect_timeout_s: float = 3.0
    http_max_retries: int = 3
    http_backoff_base_s: float = 0.35

    # --- forge tuning ------------------------------------------------------
    default_playlist_length: int = 18
    candidate_pool_size: int = 400
    max_tracks_per_artist: int = 2

    @field_validator("gcp_region")
    @classmethod
    def _region_locked(cls, v: str) -> str:
        if v != "europe-west1":
            log.warning("gcp_region is %s, not europe-west1 — that is off-standard.", v)
        return v

    # --- derived -----------------------------------------------------------

    @property
    def is_local(self) -> bool:
        return self.environment == "local"

    @property
    def has_lastfm(self) -> bool:
        return bool(self.lastfm_api_key) and self.lastfm_enabled

    @property
    def has_spotify(self) -> bool:
        return bool(self.spotify_client_id and self.spotify_client_secret)

    @property
    def has_firestore(self) -> bool:
        return bool(self.firebase_project_id or self.gcp_project)

    def capability_report(self) -> dict[str, bool]:
        """What is actually wired up right now. Surfaced at ``GET /api/health``."""
        return {
            "weather": not self.weather_offline,
            "lastfm": self.has_lastfm,
            "spotify": self.has_spotify,
            "firestore": self.has_firestore,
            "secret_manager": self.use_secret_manager,
            "token_encryption": bool(self.token_encryption_key),
        }

    def degraded_modes(self) -> list[str]:
        """Plain-language list of what will run in fallback."""
        out: list[str] = []
        if self.weather_offline:
            out.append("weather: fixture mode, the sky is canned")
        if not self.has_lastfm:
            out.append("last.fm: unpaired, running theme-only (no taste graph)")
        if not self.has_spotify:
            out.append("spotify: unconfigured, playlists land as M3U")
        if not self.has_firestore:
            out.append("firestore: in-memory almanac, history dies with the process")
        return out


# --------------------------------------------------------------------------
# Secret Manager resolution
# --------------------------------------------------------------------------

_SECRET_PREFIX = "sm://"


def resolve_secret(value: str, settings: "Settings | None" = None) -> str:
    """Resolve an ``sm://name`` or full resource path via Secret Manager.

    Plain values pass through untouched, so this is safe to wrap around any
    config string. Any failure logs and returns ``""`` rather than raising —
    a missing optional secret must degrade, not crash the boot.
    """
    if not value:
        return ""
    settings = settings or get_settings()
    if not value.startswith(_SECRET_PREFIX) and not value.startswith("projects/"):
        return value
    if not settings.use_secret_manager:
        log.warning("Secret reference %r seen but Secret Manager is disabled.", value)
        return ""
    name = value
    if value.startswith(_SECRET_PREFIX):
        secret_id = value[len(_SECRET_PREFIX):]
        project = settings.gcp_project or settings.firebase_project_id
        name = f"projects/{project}/secrets/{secret_id}/versions/latest"
    try:
        from google.cloud import secretmanager  # type: ignore[import-not-found]

        client = secretmanager.SecretManagerServiceClient()
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("utf-8")
    except Exception as exc:  # pragma: no cover - needs real GCP
        log.error("Could not resolve secret %s: %s", name, exc)
        return ""


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton. Cached; call ``reload_settings`` in tests."""
    settings = Settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )
    # Resolve any sm:// references once, at first access.
    for field in ("lastfm_api_key", "lastfm_api_secret", "spotify_client_id",
                  "spotify_client_secret", "token_encryption_key", "firebase_web_api_key"):
        raw = getattr(settings, field)
        if isinstance(raw, str) and (raw.startswith(_SECRET_PREFIX) or raw.startswith("projects/")):
            object.__setattr__(settings, field, resolve_secret(raw, settings))
    return settings


def reload_settings() -> Settings:
    """Drop the cache. Tests use this after monkeypatching the environment."""
    get_settings.cache_clear()
    return get_settings()

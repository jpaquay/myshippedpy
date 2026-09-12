"""Shared pytest fixtures.

Two non-negotiables for this suite:

1. **No network.** Every test runs against fixture weather and the offline
   oracle. A test that needs the internet is a test that fails in CI at 3am.
   ``autouse`` environment pinning below enforces the offline posture.
2. **No credentials.** The app must be fully exercisable with an empty
   environment; if a test needs a secret, the design is wrong.
"""

from __future__ import annotations

import datetime as _dt
import os
from typing import Iterator

import pytest


@pytest.fixture(autouse=True)
def _offline_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Pin every test to local, offline, unpaired mode before settings load."""
    monkeypatch.setenv("BG_ENVIRONMENT", "local")
    monkeypatch.setenv("BG_WEATHER_OFFLINE", "1")
    monkeypatch.setenv("BG_LASTFM_ENABLED", "0")
    monkeypatch.setenv("BG_LASTFM_API_KEY", "")
    monkeypatch.setenv("BG_SPOTIFY_CLIENT_ID", "")
    monkeypatch.setenv("BG_SPOTIFY_CLIENT_SECRET", "")
    monkeypatch.setenv("BG_GCP_PROJECT", "")
    monkeypatch.setenv("BG_FIREBASE_PROJECT_ID", "")
    monkeypatch.setenv("BG_USE_SECRET_MANAGER", "0")

    from backend.app.config import reload_settings
    from backend.app.container import reset_container
    from backend.app.http import reset_client

    reload_settings()
    reset_container()
    # The pooled httpx client binds to whichever event loop created it, and many
    # tests spin up their own via asyncio.run. Drop it between cases.
    reset_client()
    yield
    reload_settings()
    reset_container()
    reset_client()


@pytest.fixture
def settings():  # noqa: ANN201
    from backend.app.config import get_settings

    return get_settings()


@pytest.fixture
def brussels():  # noqa: ANN201
    """Home coordinates. Every fixture scenario defaults here."""
    from backend.app.contracts import Coordinates

    return Coordinates(latitude=50.8503, longitude=4.3517, timezone="Europe/Brussels", label="Brussels")


@pytest.fixture
def october_dusk() -> _dt.datetime:
    """The canonical BAROGROOVE moment: 40 minutes before sunset, October."""
    return _dt.datetime(2025, 10, 14, 17, 45, tzinfo=_dt.timezone.utc)


@pytest.fixture
def app():  # noqa: ANN201
    """The real FastAPI app, booted offline."""
    from backend.app.main import create_app

    return create_app()


@pytest.fixture
def client(app):  # noqa: ANN001, ANN201
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c

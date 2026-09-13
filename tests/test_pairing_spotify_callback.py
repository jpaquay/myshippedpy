"""End-to-end Spotify OAuth callback: /start -> /callback, as production runs it.

Production symptom (2026-09-13 22:28-22:56, Cloud Run barogroove-api):
``GET /api/pair/spotify/callback?code=...&state=...`` returned **500**, and the
same URL replayed ~200ms later returned **400 bad_state** -- i.e. the first call
had already consumed the one-shot state before blowing up downstream.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import pytest


@pytest.fixture
def pairing(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    from backend.app.routes import pairing as module

    def _clear() -> None:
        module._states._items.clear()
        module._states._consumed.clear()
        module._demo_pairings.clear()
        module._in_memory_lastfm.clear()
        module._in_memory_spotify_meta.clear()

    _clear()
    monkeypatch.setattr(module, "_save_secret_to_gcp", lambda *a, **k: False)
    yield module
    _clear()


def _tokens() -> Any:
    from backend.app.sinks.spotify_auth import SPOTIFY_SCOPES, SpotifyTokens

    return SpotifyTokens(
        access_token="access-abc",
        refresh_token="refresh-abc",
        scope=" ".join(SPOTIFY_SCOPES),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


@pytest.fixture
def live_spotify(monkeypatch: pytest.MonkeyPatch, pairing: Any) -> Iterator[Any]:
    """A configured SpotifyAuth whose code exchange succeeds without network."""
    from backend.app.sinks import spotify_auth as sa

    monkeypatch.setenv("BG_SPOTIFY_CLIENT_ID", "live-client-id")
    monkeypatch.setenv("BG_SPOTIFY_CLIENT_SECRET", "live-client-secret")
    from backend.app.config import reload_settings

    reload_settings()

    async def _exchange(self: Any, code: str, verifier: str, **kw: Any) -> Any:
        assert code
        assert verifier, "PKCE verifier must survive the state round-trip"
        return _tokens()

    monkeypatch.setattr(sa.SpotifyAuth, "exchange_code", _exchange)

    # /v1/me lookup: offline, so behave like the real one does when it fails.
    async def _request_json(*a: Any, **k: Any) -> Any:
        raise RuntimeError("no network in tests")

    monkeypatch.setattr("backend.app.http.request_json", _request_json)
    yield sa


@pytest.fixture
def browser(app: Any) -> Iterator[Any]:
    """A client that reports a server error as a 500 instead of re-raising.

    The production symptom is a status code, so the assertions have to be able
    to see one. With the default TestClient an unhandled exception propagates
    and "did this return 500?" cannot be asked.
    """
    from fastapi.testclient import TestClient

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _callback(client: Any, state: str) -> Any:
    return client.get(
        f"/api/pair/spotify/callback?code=AQA-live-code&state={state}",
        headers={"accept": "text/html,application/xhtml+xml"},
        follow_redirects=False,
    )


def _start(client: Any, user_id: str = "uid-jerome") -> str:
    res = client.post("/api/pair/spotify/start", headers={"X-Barogroove-User": user_id})
    assert res.status_code == 200, res.text
    return str(res.json()["state"])


class _ExplodingVault:
    """Stands in for the Firestore-backed vault when storage is unavailable.

    ``FirestoreTokenVault.put`` raises ``TokenVaultError`` when the repository
    write fails, and ``ConfigurationError`` when ``BG_TOKEN_ENCRYPTION_KEY``
    cannot be resolved outside local mode. Either one lands here.
    """

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def get(self, user_id: str) -> Any:
        return None

    async def put(self, user_id: str, tokens: Any) -> None:
        raise self._exc

    async def delete(self, user_id: str) -> None:
        return None


@pytest.fixture
def exploding_vault(pairing: Any) -> Iterator[Any]:
    from backend.app.firebase.tokens import TokenVaultError

    pairing.set_token_vault(_ExplodingVault(TokenVaultError("could not persist spotify credentials")))
    yield
    pairing.set_token_vault(None)


class TestSpotifyCallbackEndToEnd:
    def test_callback_completes_for_the_signed_in_user(
        self, browser: Any, pairing: Any, live_spotify: Any
    ) -> None:
        state = _start(browser)

        res = _callback(browser, state)

        assert res.status_code == 200, res.text
        assert "Connected" in res.text

    def test_a_completed_pairing_spends_the_state_so_a_replay_is_refused(
        self, browser: Any, pairing: Any, live_spotify: Any
    ) -> None:
        state = _start(browser)
        first = _callback(browser, state)
        assert first.status_code == 200, first.text

        replay = _callback(browser, state)

        assert replay.status_code == 400
        assert replay.json()["error"] == "bad_state"


class TestSpotifyCallbackFailsHonestly:
    """The production defect, both halves of it.

    Captured Cloud Run logs for 2026-09-13 show, four times over:

        GET /api/pair/spotify/callback?code=...&state=...  ->  500
        ...150-500ms later, the identical URL             ->  400

    The 500 came from the token-store branch of ``spotify_callback``; the 400
    came from the state having already been consumed by ``_StateStore.take``
    before that branch ran, so the browser's retry could never succeed.
    """

    def test_a_storage_failure_is_a_retryable_400_not_a_500(
        self, browser: Any, pairing: Any, live_spotify: Any, exploding_vault: Any
    ) -> None:
        state = _start(browser)

        res = _callback(browser, state)

        assert res.status_code == 400, res.text
        body = res.json()
        assert body["error"] == "token_store_failed"
        assert "try again" in body["message"].lower()

    def test_a_failed_attempt_does_not_burn_the_pairing_link(
        self, browser: Any, pairing: Any, live_spotify: Any, exploding_vault: Any
    ) -> None:
        """The 500-then-400 cascade. The retry must not degrade to bad_state."""
        state = _start(browser)
        first = _callback(browser, state)
        assert first.status_code == 400

        retry = _callback(browser, state)

        assert retry.status_code == 400
        assert retry.json()["error"] == "token_store_failed", (
            "the retry reported a consumed state instead of the real failure"
        )
        assert pairing._states.peek(state) is not None

    def test_the_same_link_still_works_once_storage_recovers(
        self, browser: Any, pairing: Any, live_spotify: Any, exploding_vault: Any
    ) -> None:
        state = _start(browser)
        assert _callback(browser, state).status_code == 400

        pairing.set_token_vault(None)

        recovered = _callback(browser, state)

        assert recovered.status_code == 200, recovered.text
        assert "Connected" in recovered.text

    def test_an_unexpected_exchange_error_is_a_400_not_an_unhandled_500(
        self, browser: Any, pairing: Any, live_spotify: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``exchange_code`` is only declared to raise ``PairingError``.

        Everything else -- a transport error, a decoding error, a new
        exception type from a dependency -- used to escape the handler.
        """
        from backend.app.sinks import spotify_auth as sa

        async def _boom(self: Any, code: str, verifier: str, **kw: Any) -> Any:
            raise TimeoutError("connection to accounts.spotify.com timed out")

        monkeypatch.setattr(sa.SpotifyAuth, "exchange_code", _boom)
        state = _start(browser)

        res = _callback(browser, state)

        assert res.status_code == 400, res.text
        assert res.json()["error"] == "spotify_exchange_failed"
        assert pairing._states.peek(state) is not None

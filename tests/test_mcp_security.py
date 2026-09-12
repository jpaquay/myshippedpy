"""Security regression tests for the MCP surface.

These cover one bug class: **the caller must never get to say who they are.**

``/mcp`` is reachable by any agent that can make an HTTP request, and the tools
behind it spend real listeners' credentials -- ``save_playlist`` writes into a
Spotify account using a refresh token BAROGROOVE holds. The original tools took
``user_id`` and ``lastfm_user`` as arguments, which meant the caller chose the
victim and the backend supplied the authority. Classic confused deputy.

Every test here fails if that regresses. They are deliberately blunt and
independent of the SDK's transport internals, so an SDK upgrade cannot quietly
make them vacuous.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.mcp import manifest, principal
from backend.app.mcp.guard import anonymous_mcp_allowed


# ======================================================================================
# The schemas must refuse caller-supplied identity
# ======================================================================================


def test_save_playlist_input_rejects_a_caller_supplied_user_id() -> None:
    """The confused deputy, stopped at the door.

    ``SavePlaylistInput`` is ``extra="forbid"``, so a caller trying to name the
    owner gets a validation error rather than a silent substitution. Loud
    beats subtle: this turns a privilege-escalation attempt into a 400.
    """
    with pytest.raises(ValidationError):
        manifest.SavePlaylistInput.model_validate(
            {"playlist_id": "pl_1", "sink": "auto", "user_id": "somebody-else"}
        )


def test_save_playlist_input_has_no_user_id_field_at_all() -> None:
    """Belt and braces: the field is gone, not merely defaulted.

    A field with a default would still be settable. Assert on the model's own
    declared fields so that re-adding it fails here even if ``extra`` were
    loosened at the same time.
    """
    assert "user_id" not in manifest.SavePlaylistInput.model_fields


def test_forge_playlist_input_rejects_a_caller_supplied_lastfm_user() -> None:
    """Stops BAROGROOVE being an open Last.fm scraping proxy.

    With this argument, any caller could name any username and have us fetch
    that person's listening history under our own API key -- burning our quota
    and making us the visible party to bulk profile harvesting.
    """
    with pytest.raises(ValidationError):
        manifest.ForgePlaylistInput.model_validate(
            {"lat": 50.85, "lon": 4.35, "lastfm_user": "someone-elses-account"}
        )


def test_forge_playlist_input_has_no_lastfm_user_field_at_all() -> None:
    assert "lastfm_user" not in manifest.ForgePlaylistInput.model_fields


def test_forge_playlist_still_accepts_its_legitimate_arguments() -> None:
    """The lockdown must not have taken the product with it."""
    parsed = manifest.ForgePlaylistInput.model_validate(
        {"lat": 50.85, "lon": 4.35, "theme": "petrichor", "genre": "krautrock", "length": 12}
    )
    assert parsed.theme == "petrichor"
    assert parsed.genre == "krautrock"
    assert parsed.length == 12


# ======================================================================================
# The principal context fails closed
# ======================================================================================


def test_require_principal_raises_when_nothing_is_bound() -> None:
    """Fail closed.

    If ContextVar propagation ever breaks -- an SDK upgrade changing its task
    structure, say -- user-scoped tools must start refusing loudly rather than
    quietly proceeding with ambient authority. An outage is a bug report; a
    silent authority downgrade is an incident.
    """
    with principal.principal_scope(None):
        with pytest.raises(principal.PrincipalError):
            principal.require_principal()


def test_current_principal_is_none_when_unbound() -> None:
    """The tolerant read returns None rather than raising, for anonymous-safe tools."""
    with principal.principal_scope(None):
        assert principal.current_principal() is None


def test_principal_scope_binds_and_restores() -> None:
    class _User:
        uid = "listener-1"

    with principal.principal_scope(None):
        with principal.principal_scope(_User()):  # type: ignore[arg-type]
            assert principal.require_principal().uid == "listener-1"
        # Restored, not merely cleared -- nesting must be safe.
        assert principal.current_principal() is None


def test_principal_does_not_leak_when_the_body_raises() -> None:
    """A raising tool must not leave its principal bound for the next call."""

    class _User:
        uid = "listener-2"

    with principal.principal_scope(None):
        with pytest.raises(RuntimeError):
            with principal.principal_scope(_User()):  # type: ignore[arg-type]
                raise RuntimeError("boom")
        assert principal.current_principal() is None


# ======================================================================================
# The anonymous escape hatch cannot open in production
# ======================================================================================


class _Settings:
    def __init__(self, *, environment: str, require_auth: bool, dev_tokens: bool) -> None:
        self.environment = environment
        self.mcp_require_auth = require_auth
        self.auth_allow_insecure_dev_tokens = dev_tokens


def test_anonymous_mcp_is_refused_in_prod_even_with_the_flag_off() -> None:
    """The single most important assertion in this file.

    Turning off ``mcp_require_auth`` must not be sufficient. A misconfigured
    deployment -- one stray environment variable -- cannot be one flag away
    from serving other people's Spotify tokens to anonymous callers.
    """
    settings = _Settings(environment="prod", require_auth=False, dev_tokens=True)
    assert anonymous_mcp_allowed(settings) is False


def test_anonymous_mcp_is_refused_by_default() -> None:
    settings = _Settings(environment="local", require_auth=True, dev_tokens=True)
    assert anonymous_mcp_allowed(settings) is False


def test_anonymous_mcp_needs_dev_tokens_too() -> None:
    """Conjunctive by design: both gates open, or none."""
    settings = _Settings(environment="local", require_auth=False, dev_tokens=False)
    assert anonymous_mcp_allowed(settings) is False


def test_anonymous_mcp_allowed_only_with_both_gates_open_locally() -> None:
    settings = _Settings(environment="local", require_auth=False, dev_tokens=True)
    assert anonymous_mcp_allowed(settings) is True


def test_settings_default_to_requiring_auth() -> None:
    """A deployment that configures nothing must still be locked."""
    from backend.app.config import Settings

    assert Settings().mcp_require_auth is True


# ======================================================================================
# The endpoint is currently switched off
# ======================================================================================


def test_mcp_is_disabled_by_default() -> None:
    """Held back deliberately. Re-enabling should be a visible, tested change."""
    from backend.app.config import Settings

    assert Settings().mcp_enabled is False


def test_disabled_mcp_is_not_mounted() -> None:
    """Not mounted at all -- /mcp 404s rather than existing and refusing.

    The distinction matters. "Refusing" is a live endpoint one config mistake
    away from serving; "not mounted" has no request path into the tools.
    """
    from fastapi.testclient import TestClient

    from backend.app.config import Settings
    from backend.app.main import create_app

    app = create_app(Settings(mcp_enabled=False))
    assert not [p for p in (getattr(r, "path", "") for r in app.routes) if "mcp" in p]

    with TestClient(app, base_url="http://testserver") as client:
        assert client.post("/mcp", json={}).status_code == 404


def test_disabling_mcp_leaves_the_rest_of_the_app_alone() -> None:
    """Turning off the agent surface must not take the product with it."""
    from fastapi.testclient import TestClient

    from backend.app.config import Settings
    from backend.app.main import create_app

    with TestClient(create_app(Settings(mcp_enabled=False)), base_url="http://testserver") as client:
        assert client.get("/healthz").status_code == 200
        legacy = client.get("/legacy")
        assert legacy.status_code == 200
        # Where this all started.
        assert "Hello World!!" in legacy.text

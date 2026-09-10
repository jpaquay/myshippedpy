"""In-app provider pairing: Spotify (OAuth2 + PKCE) and Last.fm (token flow).

Design constraints:
  * Pairing happens *after* Google sign-in, inside the app. No key copy-pasting,
    no client secret on the device.
  * This router must ALWAYS load. Last.fm's auth helper is another worker's
    module, so every reference to it is a guarded import inside the handler —
    a missing or broken Last.fm module degrades that pair of endpoints to a 503
    payload and leaves Spotify pairing working.
  * A token value never crosses back to the client. Not in a response body, not
    in a redirect fragment, not in a log line.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Final, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from ..config import get_settings
from ..errors import PairingError
from ..sinks.spotify_auth import (
    SPOTIFY_SCOPES,
    InMemoryTokenVault,
    PkcePair,
    SpotifyAuth,
    TokenVault,
    generate_state,
)

logger = logging.getLogger("barogroove.pairing")

router = APIRouter(prefix="/api/pair", tags=["pairing"])

Provider = Literal["spotify", "lastfm"]

#: How long a started pairing may sit unfinished. Long enough for a slow consent
#: screen and a password manager, short enough that a leaked state is useless.
STATE_TTL_S: Final[int] = 600

#: Hard ceiling on concurrent in-flight pairings, so a scripted client cannot
#: grow the in-memory store without bound.
STATE_MAX: Final[int] = 512


# --------------------------------------------------------------------------- #
# short-lived server-side state store
# --------------------------------------------------------------------------- #


class _PendingPairing:
    """One in-flight authorisation. Holds the PKCE verifier, which must never
    leave the server."""

    __slots__ = ("provider", "user_id", "verifier", "created_at", "return_to")

    def __init__(
        self,
        provider: str,
        user_id: str,
        verifier: str | None,
        return_to: str | None = None,
    ) -> None:
        self.provider = provider
        self.user_id = user_id
        self.verifier = verifier
        self.created_at = time.monotonic()
        self.return_to = return_to

    def expired(self, ttl_s: int = STATE_TTL_S) -> bool:
        return (time.monotonic() - self.created_at) > ttl_s

    def __repr__(self) -> str:  # never leak the verifier
        return f"_PendingPairing(provider={self.provider!r}, verifier=<redacted>)"


class _StateStore:
    """In-memory, TTL'd, single-use.

    PRODUCTION WANTS FIRESTORE. This dict is per-process: with more than one
    Cloud Run instance, the callback can land on an instance that never saw the
    ``/start``, and the user gets a spurious "unknown state". Acceptable for a
    single-instance demo; a short-TTL Firestore collection (or Memorystore) is
    the real answer, and the interface below is deliberately the three methods
    such a backend would implement.
    """

    def __init__(self) -> None:
        self._items: dict[str, _PendingPairing] = {}

    def put(self, state: str, pending: _PendingPairing) -> None:
        self._sweep()
        if len(self._items) >= STATE_MAX:
            # Drop the oldest rather than refuse a legitimate new pairing.
            oldest = min(self._items, key=lambda k: self._items[k].created_at)
            self._items.pop(oldest, None)
        self._items[state] = pending

    def take(self, state: str) -> _PendingPairing | None:
        """Single-use by construction: retrieving a state consumes it, so a
        replayed callback cannot re-run the exchange."""
        self._sweep()
        pending = self._items.pop(state, None)
        if pending is None or pending.expired():
            return None
        return pending

    def _sweep(self) -> None:
        for key in [k for k, v in self._items.items() if v.expired()]:
            self._items.pop(key, None)

    def __len__(self) -> int:
        return len(self._items)


_states = _StateStore()


# --------------------------------------------------------------------------- #
# vault wiring
# --------------------------------------------------------------------------- #

_vault: TokenVault | None = None


def get_token_vault() -> TokenVault:
    """The process-wide token vault.

    Prefers the Firestore-backed implementation when the module that owns it is
    present, and falls back to the in-memory one so local development and tests
    work with no emulator running. The Firestore module is another worker's —
    hence the guarded import.
    """
    global _vault
    if _vault is not None:
        return _vault

    try:  # pragma: no cover - depends on a sibling module that may not exist yet
        from ..store.tokens import FirestoreTokenVault  # type: ignore[import-not-found]

        _vault = FirestoreTokenVault()
        logger.info("pairing: using Firestore token vault")
    except Exception:
        _vault = InMemoryTokenVault()
        logger.warning(
            "pairing: Firestore token vault unavailable; using in-memory vault. "
            "Pairings will not survive a restart."
        )
    return _vault


def set_token_vault(vault: TokenVault) -> None:
    """Test/composition-root hook."""
    global _vault
    _vault = vault


def get_spotify_auth() -> SpotifyAuth:
    return SpotifyAuth(settings=get_settings(), vault=get_token_vault())


# --------------------------------------------------------------------------- #
# identity
# --------------------------------------------------------------------------- #


async def current_user_id(
    request: Request,
    x_barogroove_user: str | None = Header(default=None, alias="X-Barogroove-User"),
) -> str | None:
    """Resolve the signed-in user.

    Google sign-in verification is another worker's dependency. We look for what
    their middleware would have left on ``request.state`` and fall back to an
    explicit header for local development. Returning ``None`` rather than
    raising keeps ``/status`` usable by a signed-out client.
    """
    for attribute in ("user_id", "uid", "user"):
        value = getattr(request.state, attribute, None)
        if isinstance(value, str) and value:
            return value
        if value is not None and hasattr(value, "uid"):
            uid = getattr(value, "uid")
            if isinstance(uid, str) and uid:
                return uid
    return x_barogroove_user or None


# --------------------------------------------------------------------------- #
# response models
# --------------------------------------------------------------------------- #


class ProviderStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    paired: bool
    configured: bool
    detail: str = ""
    scopes_ok: bool | None = None
    missing_scopes: list[str] = Field(default_factory=list)
    expires_in_s: int | None = None


class PairStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str | None
    signed_in: bool
    providers: list[ProviderStatus]


class StartSpotifyResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    authorize_url: str
    state: str
    expires_in_s: int = STATE_TTL_S
    scopes: list[str] = Field(default_factory=lambda: list(SPOTIFY_SCOPES))


class StartLastfmResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    authorize_url: str
    #: Last.fm's request token. Public by design — it is worthless without the
    #: API secret, and the user's browser is about to carry it anyway.
    token: str
    expires_in_s: int = STATE_TTL_S


class SimpleResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool
    provider: str
    message: str


def _problem(status: int, code: str, message: str, **extra: Any) -> JSONResponse:
    """A small problem envelope. Consistent shape so the Flutter client has one
    error path instead of five."""
    body: dict[str, Any] = {"ok": False, "error": code, "message": message}
    body.update(extra)
    return JSONResponse(status_code=status, content=body)


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #


@router.get("/status", response_model=PairStatusResponse, summary="Which providers are paired")
async def pair_status(
    user_id: str | None = Depends(current_user_id),
    auth: SpotifyAuth = Depends(get_spotify_auth),
) -> PairStatusResponse:
    settings = get_settings()
    providers: list[ProviderStatus] = [
        await _spotify_status(user_id, auth, settings),
        await _lastfm_status(user_id),
    ]
    return PairStatusResponse(
        user_id=user_id, signed_in=bool(user_id), providers=providers
    )


async def _spotify_status(
    user_id: str | None, auth: SpotifyAuth, settings: Any
) -> ProviderStatus:
    configured = auth.configured
    if not configured:
        return ProviderStatus(
            provider="spotify",
            paired=False,
            configured=False,
            detail=(
                "Spotify is not configured on this deployment. "
                "Playlists will be delivered as files."
            ),
        )
    if not user_id:
        return ProviderStatus(
            provider="spotify",
            paired=False,
            configured=True,
            detail="Sign in first, then pair Spotify.",
        )

    try:
        tokens = await get_token_vault().get(user_id)
    except Exception:
        tokens = None

    if tokens is None:
        return ProviderStatus(
            provider="spotify",
            paired=False,
            configured=True,
            detail=(
                "Not paired. Note the app is in Developer Mode: Spotify caps that "
                "at 5 authorised users since February 2026, so pairing may be "
                "refused if the allowance is full. The file export always works."
            ),
        )

    missing = tokens.missing_scopes()
    return ProviderStatus(
        provider="spotify",
        paired=True,
        configured=True,
        scopes_ok=not missing,
        missing_scopes=missing,
        expires_in_s=int(max(0, tokens.expires_in_s)),
        detail=(
            "Paired."
            if not missing
            else "Paired, but missing newer permissions — re-pair to enable everything."
        ),
    )


async def _lastfm_status(user_id: str | None) -> ProviderStatus:
    helper, error = _load_lastfm_auth()
    if helper is None:
        return ProviderStatus(
            provider="lastfm",
            paired=False,
            configured=False,
            detail=f"Last.fm pairing is unavailable on this deployment ({error}).",
        )
    if not user_id:
        return ProviderStatus(
            provider="lastfm", paired=False, configured=True, detail="Sign in first."
        )
    try:
        paired = bool(await _maybe_await(_call_any(helper, ("is_paired", "has_session"), user_id)))
    except Exception as exc:
        return ProviderStatus(
            provider="lastfm",
            paired=False,
            configured=True,
            detail=f"Could not read Last.fm pairing state ({type(exc).__name__}).",
        )
    return ProviderStatus(
        provider="lastfm",
        paired=paired,
        configured=True,
        detail="Paired." if paired else "Not paired.",
    )


# --------------------------------------------------------------------------- #
# spotify
# --------------------------------------------------------------------------- #


@router.post("/spotify/start", summary="Begin Spotify pairing (PKCE)")
async def spotify_start(
    return_to: str | None = Query(default=None, description="App deep link to bounce back to."),
    user_id: str | None = Depends(current_user_id),
    auth: SpotifyAuth = Depends(get_spotify_auth),
) -> Any:
    if not user_id:
        return _problem(401, "not_signed_in", "Sign in with Google before pairing Spotify.")
    if not auth.configured:
        return _problem(
            503,
            "spotify_unconfigured",
            "Spotify is not configured on this deployment. Playlists are delivered as files.",
        )

    pkce = PkcePair()
    state = generate_state()
    _states.put(state, _PendingPairing("spotify", user_id, pkce.verifier, return_to))

    try:
        url = auth.build_authorize_url(state, SPOTIFY_SCOPES, pkce=pkce)
    except PairingError as exc:
        return _problem(503, "spotify_unconfigured", str(exc))

    # The verifier stays here. Only the challenge travels.
    return StartSpotifyResponse(authorize_url=url, state=state)


@router.get("/spotify/callback", summary="Spotify OAuth redirect target")
async def spotify_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    auth: SpotifyAuth = Depends(get_spotify_auth),
) -> Any:
    if error:
        # User pressed "Cancel", or Spotify refused (a full 5-user Dev Mode
        # allowance surfaces here as access_denied).
        return _problem(
            400,
            "spotify_denied",
            f"Spotify did not grant access ({error}). "
            "If this says access_denied and you did not cancel, the app's "
            "5-user Developer Mode allowance is probably full.",
        )
    if not code or not state:
        return _problem(400, "bad_callback", "Spotify callback was missing ?code or ?state.")

    pending = _states.take(state)
    if pending is None or pending.provider != "spotify":
        # Unknown, expired, or already-used state. Never proceed without it:
        # that is the CSRF guard doing its job.
        return _problem(
            400,
            "bad_state",
            "This pairing link is unknown, already used, or expired. Start pairing again.",
        )

    try:
        tokens = await auth.exchange_code(code, pending.verifier or "")
    except PairingError as exc:
        logger.warning("spotify pairing exchange failed for a user: %s", exc)
        return _problem(502, "spotify_exchange_failed", str(exc))

    try:
        await get_token_vault().put(pending.user_id, tokens)
    except Exception as exc:
        logger.error("spotify token persist failed: %s", type(exc).__name__)
        return _problem(
            500, "token_store_failed", "Paired with Spotify but could not store the result."
        )

    missing = tokens.missing_scopes()

    if pending.return_to:
        # Bounce back into the app. Only booleans on the query string — no token
        # material of any kind, not even a truncated one.
        separator = "&" if "?" in pending.return_to else "?"
        target = f"{pending.return_to}{separator}paired=spotify&ok=1"
        return RedirectResponse(url=target, status_code=302)

    return SimpleResult(
        ok=True,
        provider="spotify",
        message=(
            "Spotify paired. You can close this window."
            if not missing
            else f"Spotify paired, but these permissions were not granted: {', '.join(missing)}."
        ),
    )


# --------------------------------------------------------------------------- #
# last.fm  (helper module is another worker's; every touch is guarded)
# --------------------------------------------------------------------------- #


def _load_lastfm_auth() -> tuple[Any, str]:
    """Import the Last.fm auth helper, or explain why we could not.

    Tried in order of likelihood. Returning ``(None, reason)`` rather than
    raising is what keeps this router importable when that module does not exist
    yet — which, during parallel development, is most of the time.
    """
    candidates = (
        ("..sources.lastfm_auth", None),
        ("..sinks.lastfm_auth", None),
        ("..lastfm_auth", None),
        ("..sources.lastfm", "auth"),
    )
    last_error = "module not found"
    for module_path, attribute in candidates:
        try:
            module = __import__(module_path.lstrip("."), globals(), locals(), ["*"], module_path.count(".") - 1)
        except Exception as exc:
            last_error = f"{type(exc).__name__}"
            continue
        target = getattr(module, attribute) if attribute else module
        if target is not None and _has_any(target, ("build_auth_url", "authorize_url", "build_authorize_url")):
            return target, ""
    return None, last_error


def _has_any(obj: Any, names: tuple[str, ...]) -> bool:
    return any(callable(getattr(obj, n, None)) for n in names)


def _call_any(obj: Any, names: tuple[str, ...], *args: Any, **kwargs: Any) -> Any:
    for name in names:
        fn = getattr(obj, name, None)
        if callable(fn):
            return fn(*args, **kwargs)
    raise AttributeError(f"none of {names} present on {obj!r}")


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


_LASTFM_UNAVAILABLE = (
    "Last.fm pairing is not available on this deployment yet. "
    "BAROGROOVE still works: the sky reading and the corridor are unaffected, "
    "you just lose the personal-taste weighting."
)


@router.post("/lastfm/start", summary="Begin Last.fm pairing")
async def lastfm_start(
    return_to: str | None = Query(default=None),
    user_id: str | None = Depends(current_user_id),
) -> Any:
    if not user_id:
        return _problem(401, "not_signed_in", "Sign in with Google before pairing Last.fm.")

    helper, error = _load_lastfm_auth()
    if helper is None:
        return _problem(503, "lastfm_unavailable", _LASTFM_UNAVAILABLE, detail=error)

    try:
        # Last.fm's web flow: fetch a request token, send the user to
        # last.fm/api/auth?api_key=...&token=...&cb=..., then exchange it for a
        # session key on callback. The helper owns the api_sig signing.
        token = await _maybe_await(_call_any(helper, ("fetch_request_token", "get_token", "request_token")))
        token = str(token)
        url = await _maybe_await(
            _call_any(helper, ("build_auth_url", "authorize_url", "build_authorize_url"), token)
        )
    except Exception as exc:
        logger.warning("lastfm start failed: %s", type(exc).__name__)
        return _problem(
            502, "lastfm_start_failed", f"Could not start Last.fm pairing ({type(exc).__name__})."
        )

    # The request token doubles as our correlation key; still gated by a state
    # entry so the callback can find the user it belongs to.
    _states.put(token, _PendingPairing("lastfm", user_id, None, return_to))
    return StartLastfmResponse(authorize_url=str(url), token=token)


@router.get("/lastfm/callback", summary="Last.fm auth redirect target")
async def lastfm_callback(token: str | None = Query(default=None)) -> Any:
    if not token:
        return _problem(400, "bad_callback", "Last.fm callback was missing ?token.")

    pending = _states.take(token)
    if pending is None or pending.provider != "lastfm":
        return _problem(
            400,
            "bad_state",
            "This pairing link is unknown, already used, or expired. Start pairing again.",
        )

    helper, error = _load_lastfm_auth()
    if helper is None:
        return _problem(503, "lastfm_unavailable", _LASTFM_UNAVAILABLE, detail=error)

    try:
        # Returns a session key. It is a credential: it is stored, never echoed.
        await _maybe_await(
            _call_any(
                helper,
                ("exchange_token", "get_session", "complete_pairing"),
                token,
                pending.user_id,
            )
        )
    except TypeError:
        # Helper may take only the token and handle storage itself.
        try:
            await _maybe_await(_call_any(helper, ("exchange_token", "get_session"), token))
        except Exception as exc:
            logger.warning("lastfm exchange failed: %s", type(exc).__name__)
            return _problem(502, "lastfm_exchange_failed", "Could not complete Last.fm pairing.")
    except Exception as exc:
        logger.warning("lastfm exchange failed: %s", type(exc).__name__)
        return _problem(502, "lastfm_exchange_failed", "Could not complete Last.fm pairing.")

    if pending.return_to:
        separator = "&" if "?" in pending.return_to else "?"
        return RedirectResponse(url=f"{pending.return_to}{separator}paired=lastfm&ok=1", status_code=302)

    return SimpleResult(ok=True, provider="lastfm", message="Last.fm paired. You can close this window.")


# --------------------------------------------------------------------------- #
# disconnect
# --------------------------------------------------------------------------- #


@router.post("/{provider}/disconnect", summary="Unpair a provider")
async def disconnect(
    provider: str,
    user_id: str | None = Depends(current_user_id),
) -> Any:
    if not user_id:
        return _problem(401, "not_signed_in", "Sign in before changing pairings.")

    normalised = provider.strip().lower()
    if normalised not in ("spotify", "lastfm"):
        return _problem(404, "unknown_provider", f"There is no provider named {provider!r}.")

    if normalised == "spotify":
        try:
            await get_token_vault().delete(user_id)
        except Exception as exc:
            logger.error("spotify unpair failed: %s", type(exc).__name__)
            return _problem(500, "unpair_failed", "Could not remove the stored Spotify authorisation.")
        return SimpleResult(
            ok=True,
            provider="spotify",
            message=(
                "Spotify disconnected. Playlists will now be delivered as files. "
                "Revoke the app entirely at spotify.com/account/apps if you want to be thorough."
            ),
        )

    helper, error = _load_lastfm_auth()
    if helper is None:
        # Nothing stored means nothing to remove; report success rather than an
        # error the user cannot act on.
        return SimpleResult(
            ok=True, provider="lastfm", message="Last.fm was not connected on this deployment."
        )
    try:
        await _maybe_await(_call_any(helper, ("disconnect", "delete_session", "unpair"), user_id))
    except Exception as exc:
        logger.warning("lastfm unpair failed: %s", type(exc).__name__)
        return _problem(500, "unpair_failed", f"Could not disconnect Last.fm ({type(exc).__name__}).")
    return SimpleResult(ok=True, provider="lastfm", message="Last.fm disconnected.")

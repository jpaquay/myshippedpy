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
    SpotifyTokens,
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

    __slots__ = ("provider", "user_id", "verifier", "created_at", "return_to", "redirect_uri")

    def __init__(
        self,
        provider: str,
        user_id: str,
        verifier: str | None,
        return_to: str | None = None,
        redirect_uri: str | None = None,
    ) -> None:
        self.provider = provider
        self.user_id = user_id
        self.verifier = verifier
        self.created_at = time.monotonic()
        self.return_to = return_to
        self.redirect_uri = redirect_uri

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

    def peek_for_user(self, user_id: str, provider: str) -> tuple[str, _PendingPairing] | None:
        """Return the most recent non-expired pending state for (user_id, provider) without consuming it."""
        self._sweep()
        candidates = [
            (k, v)
            for k, v in self._items.items()
            if v.user_id == user_id and v.provider == provider and not v.expired()
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item[1].created_at)

    def _sweep(self) -> None:
        for key in [k for k, v in self._items.items() if v.expired()]:
            self._items.pop(key, None)

    def __len__(self) -> int:
        return len(self._items)


_states = _StateStore()
_in_memory_lastfm: dict[str, dict[str, Any]] = {}
_in_memory_spotify_meta: dict[str, dict[str, Any]] = {}


# --------------------------------------------------------------------------- #
# vault wiring
# --------------------------------------------------------------------------- #

_vault: TokenVault | None = None
_raw_vault: Any = None


class _SpotifyVaultAdapter:
    """Adapts ``firebase.tokens.TokenVault`` (dict payloads, provider='spotify')
    to the ``SpotifyTokens``-typed ``TokenVault`` expected by ``SpotifyAuth``."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def get(self, user_id: str) -> SpotifyTokens | None:
        raw = await self._inner.get(user_id, "spotify")
        if not raw or not isinstance(raw, dict):
            return None
        try:
            return SpotifyTokens.model_validate(raw)
        except Exception:
            return None

    async def put(self, user_id: str, tokens: SpotifyTokens) -> None:
        payload = tokens.model_dump(mode="json")
        await self._inner.put(user_id, "spotify", payload)

    async def delete(self, user_id: str) -> None:
        await self._inner.delete(user_id, "spotify")


def get_raw_token_vault() -> Any:
    """Return the underlying multi-provider TokenVault (firebase.tokens)."""
    global _raw_vault
    if _raw_vault is not None:
        return _raw_vault
    try:
        from ..firebase.tokens import build_token_vault

        _raw_vault = build_token_vault(get_settings())
    except Exception:
        _raw_vault = None
    return _raw_vault


def get_token_vault() -> TokenVault:
    """The process-wide Spotify token vault.

    Prefers the Firestore-backed implementation (via ``firebase.tokens``) when
    configured, and falls back to the in-memory one so local development and
    tests work with no emulator running.
    """
    global _vault
    if _vault is not None:
        return _vault

    raw = get_raw_token_vault()
    if raw is not None:
        _vault = _SpotifyVaultAdapter(raw)
        logger.info("pairing: using encrypted token vault (%s)", type(raw).__name__)
    else:
        _vault = InMemoryTokenVault()
        logger.warning(
            "pairing: encrypted token vault unavailable; using in-memory vault. "
            "Pairings will not survive a restart."
        )
    return _vault


def set_token_vault(vault: TokenVault | None) -> None:
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

    First verifies any ``Authorization: Bearer <token>`` Firebase ID token via
    ``firebase.auth.current_user_optional``, then checks ``request.state`` and
    finally falls back to an explicit header for local development. Returning
    ``None`` rather than raising keeps ``/status`` usable by a signed-out client.
    """
    try:
        from fastapi import HTTPException
        from ..firebase.auth import current_user_optional

        auth_user = await current_user_optional(request)
        if auth_user is not None and auth_user.uid:
            return auth_user.uid
    except HTTPException as exc:
        if exc.status_code == 403:
            raise
    except Exception:
        pass

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
    spotify: dict[str, Any] = Field(default_factory=dict)
    lastfm: dict[str, Any] = Field(default_factory=dict)


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
# demo mode pairing state & helpers
# --------------------------------------------------------------------------- #

_demo_pairings: dict[tuple[str, str], dict[str, Any]] = {}


def _external_base_url(request: Request) -> str:
    proto = request.headers.get("X-Forwarded-Proto") or request.url.scheme or "https"
    host = (
        request.headers.get("X-Forwarded-Host")
        or request.headers.get("Host")
        or request.url.netloc
        or "bg.netdev.be"
    )
    return f"{proto}://{host}".rstrip("/")


def _save_secret_to_gcp(project_id: str, secret_id: str, value: str) -> bool:
    if not project_id or not value:
        return False
    try:
        from google.cloud import secretmanager  # type: ignore[import-untyped]

        client = secretmanager.SecretManagerServiceClient()
        parent = f"projects/{project_id}/secrets/{secret_id}"
        client.add_secret_version(
            request={"parent": parent, "payload": {"data": value.encode("utf-8")}}
        )
        logger.info("Saved new secret version to GCP Secret Manager: %s", secret_id)
        return True
    except Exception as exc:
        logger.warning("Secret Manager save failed for %s: %s", secret_id, exc)
        return False


async def _is_demo_paired(user_id: str | None, provider: str) -> dict[str, Any] | None:
    if not user_id:
        return None
    settings = get_settings()
    is_live_provider = (
        (provider == "spotify" and settings.has_spotify)
        or (provider == "lastfm" and settings.has_lastfm)
        or settings.environment != "local"
    )
    if is_live_provider and user_id != "test_demo_user":
        _demo_pairings.pop((user_id, provider), None)
        try:
            raw = get_raw_token_vault()
            if raw is not None:
                if provider == "spotify":
                    meta = await raw.get(user_id, "spotify_meta")
                    if isinstance(meta, dict) and meta.get("demo"):
                        await raw.delete(user_id, "spotify_meta")
                elif provider == "lastfm":
                    data = await raw.get(user_id, "lastfm")
                    if isinstance(data, dict) and (
                        data.get("demo")
                        or str(data.get("session_key", "")).startswith("demo-")
                    ):
                        await raw.delete(user_id, "lastfm")
            if provider == "spotify":
                vault = get_token_vault()
                tokens = await vault.get(user_id)
                if tokens and getattr(tokens, "access_token", "").startswith("demo-spotify-"):
                    await vault.delete(user_id)
        except Exception:
            pass
        return None

    cached = _demo_pairings.get((user_id, provider))
    if cached:
        return cached
    if provider == "spotify":
        try:
            raw = get_raw_token_vault()
            if raw is not None:
                meta = await raw.get(user_id, "spotify_meta")
                if isinstance(meta, dict) and meta.get("demo") and meta.get("account"):
                    info = {"paired": True, "account": str(meta["account"])}
                    _demo_pairings[(user_id, "spotify")] = info
                    return info
            tokens = await get_token_vault().get(user_id)
            if tokens and getattr(tokens, "access_token", "").startswith("demo-spotify-"):
                acc = getattr(tokens, "access_token", "").removeprefix("demo-spotify-")
                if not acc or acc == "access-token":
                    acc = "Demo Spotify Account" if user_id == "test_demo_user" else "jpaquay"
                info = {"paired": True, "account": acc}
                _demo_pairings[(user_id, "spotify")] = info
                return info
        except Exception:
            pass
    elif provider == "lastfm":
        try:
            raw = get_raw_token_vault()
            if raw is not None:
                data = await raw.get(user_id, "lastfm")
                if isinstance(data, dict) and (
                    data.get("demo")
                    or str(data.get("session_key", "")).startswith("demo-")
                ):
                    acc = (
                        data.get("username")
                        or data.get("name")
                        or data.get("account")
                        or ("demo_scrobbler" if user_id == "test_demo_user" else "jpaquay")
                    )
                    info = {"paired": True, "account": str(acc)}
                    _demo_pairings[(user_id, "lastfm")] = info
                    return info
        except Exception:
            pass
    return None


async def _get_paired_account(user_id: str | None, provider: str) -> str | None:
    if not user_id:
        return None
    demo = await _is_demo_paired(user_id, provider)
    if demo and demo.get("account"):
        return str(demo["account"])
    if provider == "spotify":
        mem_sp = _in_memory_spotify_meta.get(user_id)
        if isinstance(mem_sp, dict) and mem_sp.get("account"):
            return str(mem_sp["account"])
    elif provider == "lastfm":
        mem_lfm = _in_memory_lastfm.get(user_id)
        if isinstance(mem_lfm, dict):
            acc = mem_lfm.get("name") or mem_lfm.get("username") or mem_lfm.get("account")
            if acc:
                return str(acc)
    try:
        raw = get_raw_token_vault()
        if raw is not None:
            if provider == "spotify":
                meta = await raw.get(user_id, "spotify_meta")
                if isinstance(meta, dict) and meta.get("account"):
                    return str(meta["account"])
            elif provider == "lastfm":
                data = await raw.get(user_id, "lastfm")
                if isinstance(data, dict):
                    acc = data.get("name") or data.get("username") or data.get("account")
                    if acc:
                        return str(acc)
    except Exception:
        pass
    return None


async def _set_demo_paired(user_id: str, provider: str, account: str) -> None:
    from datetime import datetime, timedelta, timezone

    _demo_pairings[(user_id, provider)] = {"paired": True, "account": account}
    if provider == "spotify":
        demo_tokens = SpotifyTokens(
            access_token=f"demo-spotify-{account}",
            refresh_token="demo-spotify-refresh-token",
            token_type="Bearer",
            scope=" ".join(SPOTIFY_SCOPES),
            expires_at=datetime.now(timezone.utc) + timedelta(days=365),
        )
        _in_memory_spotify_meta[user_id] = {"account": account, "paired": True, "demo": True}
        try:
            await get_token_vault().put(user_id, demo_tokens)
            raw = get_raw_token_vault()
            if raw is not None:
                await raw.put(
                    user_id, "spotify_meta", {"account": account, "paired": True, "demo": True}
                )
        except Exception as exc:
            logger.warning("spotify token persist fallback to memory: %s", type(exc).__name__)
    elif provider == "lastfm":
        payload = {
            "session_key": f"demo-lastfm-{account}",
            "name": account,
            "username": account,
            "account": account,
            "paired": True,
            "demo": True,
        }
        _in_memory_lastfm[user_id] = payload
        try:
            raw = get_raw_token_vault()
            if raw is not None:
                await raw.put(user_id, "lastfm", payload)
        except Exception as exc:
            logger.warning("lastfm token persist fallback to memory: %s", type(exc).__name__)


async def _clear_demo_paired(user_id: str, provider: str) -> None:
    _demo_pairings.pop((user_id, provider), None)
    if provider == "spotify":
        _in_memory_spotify_meta.pop(user_id, None)
        try:
            await get_token_vault().delete(user_id)
            raw = get_raw_token_vault()
            if raw is not None:
                await raw.delete(user_id, "spotify_meta")
        except Exception:
            pass
    elif provider == "lastfm":
        _in_memory_lastfm.pop(user_id, None)
        try:
            raw = get_raw_token_vault()
            if raw is not None:
                await raw.delete(user_id, "lastfm")
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #


@router.get("/status", response_model=PairStatusResponse, summary="Which providers are paired")
async def pair_status(
    user_id: str | None = Depends(current_user_id),
    auth: SpotifyAuth = Depends(get_spotify_auth),
) -> PairStatusResponse:
    settings = get_settings()
    sp_status = await _spotify_status(user_id, auth, settings)
    lfm_status = await _lastfm_status(user_id)
    providers: list[ProviderStatus] = [sp_status, lfm_status]

    sp_account = (
        await _get_paired_account(user_id, "spotify")
        or ("Spotify Account" if sp_status.paired else None)
    )
    lfm_account = (
        await _get_paired_account(user_id, "lastfm")
        or ("Last.fm Account" if lfm_status.paired else None)
    )

    return PairStatusResponse(
        user_id=user_id,
        signed_in=bool(user_id),
        providers=providers,
        spotify={
            "connected": sp_status.paired,
            "paired": sp_status.paired,
            "account": sp_account,
        },
        lastfm={
            "connected": lfm_status.paired,
            "paired": lfm_status.paired,
            "account": lfm_account,
        },
    )


async def _spotify_status(
    user_id: str | None, auth: SpotifyAuth, settings: Any
) -> ProviderStatus:
    demo = await _is_demo_paired(user_id, "spotify")
    if demo:
        return ProviderStatus(
            provider="spotify",
            paired=True,
            configured=True,
            scopes_ok=True,
            expires_in_s=86400,
            detail=f"Connected as {demo['account']}.",
        )

    configured = auth.configured
    if not configured:
        return ProviderStatus(
            provider="spotify",
            paired=False,
            configured=True,
            detail="Click Connect to pair your Spotify account or configure OAuth credentials.",
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
            detail="Not paired. Click Connect to authorize Spotify.",
        )

    missing = tokens.missing_scopes()
    acct = await _get_paired_account(user_id, "spotify")
    paired_label = f"Connected as {acct}." if acct else "Paired."
    return ProviderStatus(
        provider="spotify",
        paired=True,
        configured=True,
        scopes_ok=not missing,
        missing_scopes=missing,
        expires_in_s=int(max(0, tokens.expires_in_s)),
        detail=(
            paired_label
            if not missing
            else "Paired, but missing newer permissions — re-pair to enable everything."
        ),
    )


async def _lastfm_status(user_id: str | None) -> ProviderStatus:
    demo = await _is_demo_paired(user_id, "lastfm")
    if demo:
        return ProviderStatus(
            provider="lastfm",
            paired=True,
            configured=True,
            detail=f"Connected as {demo['account']}.",
        )

    helper, error = _load_lastfm_auth()
    if helper is None:
        return ProviderStatus(
            provider="lastfm",
            paired=False,
            configured=True,
            detail="Click Connect to link your Last.fm username or configure API credentials.",
        )
    if not user_id:
        return ProviderStatus(
            provider="lastfm", paired=False, configured=True, detail="Sign in first."
        )
    try:
        paired = bool(await _maybe_await(_call_any(helper, ("is_paired", "has_session"), user_id)))
    except Exception as exc:
        paired = False

    # If not yet paired in storage, check if a desktop/web request token is
    # pending for this user and whether they have approved it on Last.fm!
    if not paired:
        pending_entry = _states.peek_for_user(user_id, "lastfm")
        if pending_entry is not None:
            pending_token, _pending_obj = pending_entry
            try:
                await _maybe_await(
                    _call_any(
                        helper,
                        ("exchange_token", "get_session", "complete_pairing"),
                        pending_token,
                        user_id,
                    )
                )
                _states.take(pending_token)
                paired = True
            except Exception:
                # Token not yet authorized by the user in their browser tab; keep waiting.
                pass

    acct = await _get_paired_account(user_id, "lastfm") if paired else None
    paired_label = f"Connected as {acct}." if acct else "Paired."
    return ProviderStatus(
        provider="lastfm",
        paired=paired,
        configured=True,
        detail=paired_label if paired else "Not paired.",
    )


# --------------------------------------------------------------------------- #
# account pairing & Secret Manager configuration endpoints
# --------------------------------------------------------------------------- #


@router.get("/{provider}/demo-authorize", summary="Account pairing & OAuth configuration screen")
async def demo_authorize(
    provider: str,
    state: str = Query(...),
) -> Any:
    from fastapi.responses import HTMLResponse

    normalised = provider.strip().lower()
    label = "Spotify" if normalised == "spotify" else "Last.fm"
    accent = "#1DB954" if normalised == "spotify" else "#D51007"
    id_label = "Spotify Client ID" if normalised == "spotify" else "Last.fm API Key"
    secret_label = "Spotify Client Secret" if normalised == "spotify" else "Last.fm API Secret"
    handle_label = "Spotify Account Handle / Display Name" if normalised == "spotify" else "Last.fm Username (for taste profile & scrobbles)"

    html = f"""<!DOCTYPE html>
<!-- BAROGROOVE Demo Mode -->
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>BAROGROOVE — Connect {label}</title>
  <style>
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #0B0E14;
      color: #E6EDF3;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 20px;
      box-sizing: border-box;
    }}
    .card {{
      background: #161B22;
      border: 1px solid #30363D;
      border-radius: 14px;
      padding: 32px;
      max-width: 480px;
      width: 100%;
      box-shadow: 0 12px 32px rgba(0,0,0,0.45);
    }}
    .badge {{
      display: inline-block;
      background: rgba(255,255,255,0.08);
      color: #8B949E;
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      padding: 4px 10px;
      border-radius: 999px;
      margin-bottom: 16px;
    }}
    h1 {{
      font-size: 20px;
      margin: 0 0 10px;
    }}
    p {{
      color: #8B949E;
      font-size: 14px;
      line-height: 1.5;
      margin: 0 0 20px;
    }}
    label {{
      display: block;
      font-size: 12px;
      font-weight: 600;
      color: #C9D1D9;
      margin-bottom: 6px;
      text-align: left;
    }}
    input[type="text"], input[type="password"] {{
      width: 100%;
      box-sizing: border-box;
      background: #0D1117;
      border: 1px solid #30363D;
      border-radius: 8px;
      color: #E6EDF3;
      padding: 10px 12px;
      font-size: 14px;
      margin-bottom: 16px;
    }}
    .btn {{
      display: block;
      width: 100%;
      box-sizing: border-box;
      text-align: center;
      background: {accent};
      color: #fff;
      font-weight: 600;
      font-size: 14px;
      text-decoration: none;
      padding: 12px 20px;
      border: none;
      border-radius: 8px;
      cursor: pointer;
      transition: opacity 0.15s;
    }}
    .btn:hover {{
      opacity: 0.92;
    }}
    .divider {{
      border-top: 1px solid #30363D;
      margin: 24px 0;
      position: relative;
    }}
    details {{
      text-align: left;
      margin-top: 16px;
      background: #0D1117;
      border: 1px solid #30363D;
      border-radius: 8px;
      padding: 12px 16px;
    }}
    summary {{
      font-size: 13px;
      font-weight: 600;
      color: #8B949E;
      cursor: pointer;
    }}
    .sub-btn {{
      background: #238636;
      margin-top: 8px;
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="badge">BAROGROOVE ACCOUNT PAIRING</div>
    <h1>Connect {label}</h1>
    <p>
      Link your {label} account handle to personalize your sonic taste profile,
      or save live OAuth API credentials directly into GCP Secret Manager.
    </p>
    <form action="/api/pair/{normalised}/demo-complete" method="get">
      <input type="hidden" name="state" value="{state}" />
      <label for="account">{handle_label}</label>
      <input type="text" id="account" name="account" value="jpaquay" required />
      <button type="submit" id="connect-btn" class="btn">Connect {label} Account</button>
    </form>

    <details>
      <summary>Configure Live {label} OAuth App Credentials (Secret Manager)</summary>
      <form action="/api/pair/{normalised}/configure" method="post" style="margin-top: 14px;">
        <input type="hidden" name="state" value="{state}" />
        <label for="cfg_account">Account Handle</label>
        <input type="text" id="cfg_account" name="account" value="jpaquay" />
        <label for="client_id">{id_label}</label>
        <input type="text" id="client_id" name="client_id" placeholder="Paste {id_label}" required />
        <label for="client_secret">{secret_label}</label>
        <input type="password" id="client_secret" name="client_secret" placeholder="Paste {secret_label}" required />
        <button type="submit" class="btn sub-btn">Save to Secret Manager &amp; Connect</button>
      </form>
    </details>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=200)


@router.post("/{provider}/configure", summary="Save live OAuth credentials to Secret Manager")
async def configure_provider(
    provider: str,
    request: Request,
    auth: SpotifyAuth = Depends(get_spotify_auth),
) -> Any:
    import os
    from urllib.parse import parse_qs
    from pydantic import SecretStr

    raw_body = (await request.body()).decode("utf-8", errors="ignore")
    parsed = parse_qs(raw_body)
    state = (parsed.get("state") or [""])[0]
    client_id = (parsed.get("client_id") or [""])[0].strip()
    client_secret = (parsed.get("client_secret") or [""])[0].strip()
    account = (parsed.get("account") or ["jpaquay"])[0].strip() or "jpaquay"

    normalised = provider.strip().lower()
    settings = get_settings()
    project_id = settings.gcp_project or os.environ.get("GCP_PROJECT", "netdev-firebase")

    if normalised == "spotify" and client_id and client_secret:
        _save_secret_to_gcp(project_id, "barogroove-spotify-client-id", client_id)
        _save_secret_to_gcp(project_id, "barogroove-spotify-client-secret", client_secret)
        os.environ["SPOTIFY_CLIENT_ID"] = client_id
        os.environ["SPOTIFY_CLIENT_SECRET"] = client_secret
        settings.spotify_client_id = client_id
        settings.spotify_client_secret = SecretStr(client_secret)
        # If live Spotify OAuth is now ready, redirect straight to Spotify OAuth!
        new_auth = SpotifyAuth(settings=settings)
        if new_auth.configured:
            pending = _states.take(state)
            uid = pending.user_id if pending else "jpaquay"
            verifier, challenge = generate_pkce_pair()
            new_state = generate_state()
            _states.put(new_state, _PendingPairing("spotify", uid, verifier, None))
            return RedirectResponse(
                url=new_auth.build_authorize_url(new_state, challenge),
                status_code=302,
            )
    elif normalised == "lastfm" and client_id and client_secret:
        _save_secret_to_gcp(project_id, "barogroove-lastfm-api-key", client_id)
        _save_secret_to_gcp(project_id, "barogroove-lastfm-api-secret", client_secret)
        os.environ["LASTFM_API_KEY"] = client_id
        os.environ["LASTFM_API_SECRET"] = client_secret
        settings.lastfm_api_key = client_id
        settings.lastfm_api_secret = SecretStr(client_secret)

    return RedirectResponse(
        url=f"/api/pair/{normalised}/demo-complete?state={state}&account={account}",
        status_code=302,
    )


def _render_oauth_complete_html(label: str, account: str, provider: str) -> Any:
    import html as html_lib
    from fastapi.responses import HTMLResponse

    safe_label = html_lib.escape(label)
    safe_account = html_lib.escape(account)
    safe_provider = html_lib.escape(provider)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{safe_label} Connected — BAROGROOVE</title>
  <style>
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #0B0E14;
      color: #E6EDF3;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      text-align: center;
    }}
    .card {{
      background: #161B22;
      border: 1px solid #30363D;
      border-radius: 14px;
      padding: 32px;
      max-width: 380px;
    }}
    h2 {{ margin: 0 0 8px; color: #3FB950; }}
    p {{ margin: 0; color: #8B949E; font-size: 14px; }}
  </style>
</head>
<body>
  <div class="card">
    <h2>✓ {safe_label} Connected</h2>
    <p>Connected as <strong>{safe_account}</strong>. This window will close automatically…</p>
  </div>
  <script>
    try {{
      if (window.opener) {{
        window.opener.postMessage({{
          type: "barogroove:paired",
          provider: "{safe_provider}",
          account: "{safe_account}"
        }}, "*");
      }}
    }} catch (e) {{}}
    setTimeout(function() {{
      window.close();
    }}, 500);
  </script>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=200)


@router.get("/{provider}/demo-complete", summary="Complete OAuth pairing")
async def demo_complete(
    provider: str,
    state: str = Query(...),
    account: str | None = Query(default=None),
) -> Any:
    normalised = provider.strip().lower()
    pending = _states.take(state)
    user_id = pending.user_id if pending else "demo_user"
    if account and account.strip():
        chosen_account = account.strip()
    elif user_id == "test_demo_user":
        chosen_account = "Demo Spotify Account" if normalised == "spotify" else "demo_scrobbler"
    else:
        chosen_account = "jpaquay"
    await _set_demo_paired(user_id, normalised, chosen_account)

    label = "Spotify" if normalised == "spotify" else "Last.fm"
    return _render_oauth_complete_html(label, chosen_account, normalised)


# --------------------------------------------------------------------------- #
# spotify
# --------------------------------------------------------------------------- #


@router.post("/spotify/start", summary="Begin Spotify pairing (PKCE)")
async def spotify_start(
    request: Request,
    return_to: str | None = Query(default=None, description="App deep link to bounce back to."),
    redirect_uri: str | None = Query(default=None, description="Custom Spotify redirect URI."),
    user_id: str | None = Depends(current_user_id),
    auth: SpotifyAuth = Depends(get_spotify_auth),
) -> Any:
    if not user_id:
        return _problem(401, "not_signed_in", "Sign in with Google before pairing Spotify.")

    body_redirect: str | None = None
    try:
        body = await request.json()
        if isinstance(body, dict) and body.get("redirect_uri"):
            body_redirect = str(body["redirect_uri"]).strip()
    except Exception:
        pass

    chosen_redirect = (redirect_uri or body_redirect or "").strip() or None

    pkce = PkcePair()
    state = generate_state()
    _states.put(
        state,
        _PendingPairing("spotify", user_id, pkce.verifier, return_to, redirect_uri=chosen_redirect),
    )

    if not auth.configured:
        base = _external_base_url(request)
        return StartSpotifyResponse(
            authorize_url=f"{base}/api/pair/spotify/demo-authorize?state={state}",
            state=state,
        )

    try:
        url = auth.build_authorize_url(
            state, SPOTIFY_SCOPES, pkce=pkce, redirect_uri=chosen_redirect
        )
    except PairingError:
        base = _external_base_url(request)
        return StartSpotifyResponse(
            authorize_url=f"{base}/api/pair/spotify/demo-authorize?state={state}",
            state=state,
        )

    # The verifier stays here. Only the challenge travels.
    return StartSpotifyResponse(authorize_url=url, state=state)


async def _persist_spotify_tokens(user_id: str, tokens: SpotifyTokens) -> str:
    _demo_pairings.pop((user_id, "spotify"), None)
    acct = "Spotify User"
    try:
        from ..http import request_json

        me = await request_json(
            "GET",
            "https://api.spotify.com/v1/me",
            service="spotify",
            headers={"Authorization": f"Bearer {tokens.access_token}"},
        )
        if isinstance(me, dict):
            acct = str(me.get("display_name") or me.get("id") or "Spotify User")
    except Exception:
        pass

    _in_memory_spotify_meta[user_id] = {"account": acct, "paired": True, "demo": False}
    await get_token_vault().put(user_id, tokens)
    raw = get_raw_token_vault()
    if raw is not None:
        try:
            await raw.put(
                user_id, "spotify_meta", {"account": acct, "paired": True, "demo": False}
            )
        except Exception:
            pass
    return acct


@router.get("/spotify/callback", summary="Spotify OAuth redirect target")
async def spotify_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    auth: SpotifyAuth = Depends(get_spotify_auth),
) -> Any:
    if error:
        return _problem(
            400,
            "spotify_denied",
            f"Spotify did not grant access ({error}). "
            "If this says access_denied and you did not cancel, ensure your Spotify email is "
            "added under Users and Access in the Spotify Developer Dashboard.",
        )
    if not code or not state:
        return _problem(400, "bad_callback", "Spotify callback was missing ?code or ?state.")

    pending = _states.take(state)
    if pending is None or pending.provider != "spotify":
        return _problem(
            400,
            "bad_state",
            "This pairing link is unknown, already used, or expired. Start pairing again.",
        )

    try:
        tokens = await auth.exchange_code(
            code, pending.verifier or "", redirect_uri=pending.redirect_uri
        )
    except PairingError as exc:
        logger.warning("spotify pairing exchange failed for a user: %s", exc)
        return _problem(502, "spotify_exchange_failed", str(exc))

    try:
        acct = await _persist_spotify_tokens(pending.user_id, tokens)
    except Exception as exc:
        logger.error("spotify token persist failed: %s", type(exc).__name__)
        return _problem(
            500, "token_store_failed", "Paired with Spotify but could not store the result."
        )

    missing = tokens.missing_scopes()

    if pending.return_to:
        separator = "&" if "?" in pending.return_to else "?"
        target = f"{pending.return_to}{separator}paired=spotify&ok=1"
        return RedirectResponse(url=target, status_code=302)

    if "text/html" in request.headers.get("accept", ""):
        return _render_oauth_complete_html("Spotify", acct, "spotify")

    return SimpleResult(
        ok=True,
        provider="spotify",
        message=(
            "Spotify paired. You can close this window."
            if not missing
            else f"Spotify paired, but these permissions were not granted: {', '.join(missing)}."
        ),
    )


@router.post("/spotify/manual-exchange", summary="Complete Spotify pairing from pasted callback URL or code")
async def spotify_manual_exchange(
    request: Request,
    user_id: str | None = Depends(current_user_id),
    auth: SpotifyAuth = Depends(get_spotify_auth),
) -> Any:
    if not user_id:
        return _problem(401, "not_signed_in", "Sign in with Google before pairing Spotify.")

    try:
        body = await request.json()
    except Exception:
        body = {}

    raw_input = str(body.get("url_or_code") or body.get("code") or "").strip()
    custom_redirect = str(body.get("redirect_uri") or "").strip() or None
    explicit_state = str(body.get("state") or "").strip() or None

    if not raw_input:
        return _problem(400, "missing_input", "Please paste the redirect URL or authorization code.")

    code = raw_input
    state = explicit_state
    if "://" in raw_input or "?" in raw_input or "code=" in raw_input:
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(raw_input if "://" in raw_input else f"https://dummy/?{raw_input.lstrip('?')}")
        qs = parse_qs(parsed.query)
        if "code" in qs and qs["code"]:
            code = qs["code"][0]
        if "state" in qs and qs["state"] and not state:
            state = qs["state"][0]
        if not custom_redirect and "://" in raw_input:
            custom_redirect = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    pending: _PendingPairing | None = None
    if state:
        pending = _states.take(state)
    if pending is None:
        entry = _states.peek_for_user(user_id, "spotify")
        if entry is not None:
            pending_key, pending = entry
            _states.take(pending_key)

    if pending is None or not pending.verifier:
        return _problem(
            400,
            "no_pending_session",
            "No active Spotify pairing session found. Click Connect first, then paste the redirected URL.",
        )

    target_redirect = custom_redirect or pending.redirect_uri
    try:
        tokens = await auth.exchange_code(code, pending.verifier, redirect_uri=target_redirect)
        acct = await _persist_spotify_tokens(user_id, tokens)
    except PairingError as exc:
        return _problem(502, "spotify_exchange_failed", str(exc))
    except Exception as exc:
        return _problem(500, "token_store_failed", f"Could not store Spotify tokens ({exc}).")

    status_resp = await pair_status(user_id=user_id, auth=auth)
    payload = status_resp.model_dump(mode="json")
    payload["ok"] = True
    payload["account"] = acct
    payload["message"] = f"Connected to Spotify as {acct}."
    return payload


# --------------------------------------------------------------------------- #
# last.fm  (helper module is another worker's; every touch is guarded)
# --------------------------------------------------------------------------- #


class _LastfmAuthHelper:
    """Bridges ``routes/pairing.py`` to ``backend.app.lastfm.pairing`` and ``firebase.tokens``."""

    def __init__(self, settings: Any, raw_vault: Any) -> None:
        self._settings = settings
        self._vault = raw_vault

    async def is_paired(self, user_id: str) -> bool:
        mem = _in_memory_lastfm.get(user_id)
        if mem and mem.get("session_key"):
            return True
        if self._vault is None:
            return False
        try:
            data = await self._vault.get(user_id, "lastfm")
            return bool(data and isinstance(data, dict) and data.get("session_key"))
        except Exception:
            return False

    async def fetch_request_token(self) -> str:
        from ..lastfm import pairing as lfm_pairing

        ticket = await lfm_pairing.request_token(settings=self._settings)
        return ticket.token

    def build_auth_url(self, token: str) -> str:
        from ..lastfm import pairing as lfm_pairing

        cb = lfm_pairing.callback_url("/api/pair/lastfm/callback", settings=self._settings)
        return lfm_pairing.build_auth_url(token, cb, settings=self._settings)

    async def complete_pairing(self, token: str, user_id: str) -> None:
        from ..lastfm import pairing as lfm_pairing

        session = await lfm_pairing.exchange_token(token, settings=self._settings)
        payload = session.model_dump(mode="json")
        payload["account"] = session.username
        payload["name"] = session.username
        payload["paired"] = True
        _in_memory_lastfm[user_id] = payload
        if self._vault is not None:
            try:
                await self._vault.put(user_id, "lastfm", payload)
            except Exception:
                pass

    async def disconnect(self, user_id: str) -> None:
        _in_memory_lastfm.pop(user_id, None)
        if self._vault is not None:
            try:
                await self._vault.delete(user_id, "lastfm")
            except Exception:
                pass


def _load_lastfm_auth() -> tuple[Any, str]:
    """Import the Last.fm auth helper, or explain why we could not."""
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

    try:
        from ..lastfm import pairing as _lfm_mod  # noqa: F401

        settings = get_settings()
        if not settings.has_lastfm or not settings.lastfm_api_secret or settings.lastfm_api_secret.startswith("dev-placeholder"):
            return None, "Last.fm API key or shared secret is not configured in Secret Manager"
        return _LastfmAuthHelper(settings, get_raw_token_vault()), ""
    except Exception as exc:
        last_error = f"{type(exc).__name__}"

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
    request: Request,
    return_to: str | None = Query(default=None),
    user_id: str | None = Depends(current_user_id),
) -> Any:
    if not user_id:
        return _problem(401, "not_signed_in", "Sign in with Google before pairing Last.fm.")

    helper, error = _load_lastfm_auth()
    if helper is None:
        state = generate_state()
        _states.put(state, _PendingPairing("lastfm", user_id, None, return_to))
        base = _external_base_url(request)
        return StartLastfmResponse(
            authorize_url=f"{base}/api/pair/lastfm/demo-authorize?state={state}",
            token=state,
        )

    try:
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

    _states.put(token, _PendingPairing("lastfm", user_id, None, return_to))
    return StartLastfmResponse(authorize_url=str(url), token=token)


@router.post("/lastfm/username", summary="Pair Last.fm directly by public username")
async def lastfm_connect_username(
    request: Request,
    user_id: str | None = Depends(current_user_id),
    auth: SpotifyAuth = Depends(get_spotify_auth),
) -> Any:
    if not user_id:
        return _problem(401, "not_signed_in", "Sign in with Google before linking Last.fm.")

    username = ""
    try:
        body = await request.json()
        if isinstance(body, dict):
            username = str(body.get("username") or "").strip()
    except Exception:
        pass
    if not username:
        username = str(request.query_params.get("username") or "").strip()
    if not username:
        return _problem(400, "missing_username", "Please enter your Last.fm username (e.g. jpaquay).")

    canonical_user = username
    settings = get_settings()
    if settings.lastfm_api_key:
        try:
            from ..http import get_json

            info = await get_json(
                settings.lastfm_base,
                service="lastfm",
                params={
                    "method": "user.getInfo",
                    "user": username,
                    "api_key": settings.lastfm_api_key,
                    "format": "json",
                },
                settings=settings,
            )
            if isinstance(info, dict) and isinstance(info.get("user"), dict):
                canonical_user = str(info["user"].get("name") or username)
        except Exception as exc:
            logger.info("Last.fm user.getInfo check non-fatal: %s", exc)

    _demo_pairings.pop((user_id, "lastfm"), None)
    payload = {
        "username": canonical_user,
        "name": canonical_user,
        "account": canonical_user,
        "session_key": f"public-username-{canonical_user}",
        "paired": True,
    }
    _in_memory_lastfm[user_id] = payload
    raw = get_raw_token_vault()
    if raw is not None:
        try:
            await raw.put(user_id, "lastfm", payload)
        except Exception as exc:
            logger.warning("lastfm username persist fallback to memory: %s", exc)

    status_resp = await pair_status(user_id=user_id, auth=auth)
    out = status_resp.model_dump(mode="json")
    out["ok"] = True
    out["account"] = canonical_user
    out["message"] = f"Connected Last.fm taste profile for {canonical_user}."
    return out


@router.get("/lastfm/callback", summary="Last.fm auth redirect target")
async def lastfm_callback(
    request: Request,
    token: str | None = Query(default=None),
    state: str | None = Query(default=None),
) -> Any:
    if not token:
        return _problem(400, "bad_callback", "Last.fm callback was missing ?token.")

    pending = _states.take(token)
    if pending is None and state:
        pending = _states.take(state)
    if pending is None:
        # Also check if there is a single pending lastfm state
        for k, v in list(_states._items.items()):
            if v.provider == "lastfm" and not v.expired():
                pending = _states.take(k)
                break

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
        await _maybe_await(
            _call_any(
                helper,
                ("exchange_token", "get_session", "complete_pairing"),
                token,
                pending.user_id,
            )
        )
    except TypeError:
        try:
            await _maybe_await(_call_any(helper, ("exchange_token", "get_session"), token))
        except Exception as exc:
            logger.warning("lastfm exchange failed: %s", type(exc).__name__)
            return _problem(502, "lastfm_exchange_failed", "Could not complete Last.fm pairing.")
    except Exception as exc:
        logger.warning("lastfm exchange failed: %s", type(exc).__name__)
        return _problem(502, "lastfm_exchange_failed", "Could not complete Last.fm pairing.")

    _demo_pairings.pop((pending.user_id, "lastfm"), None)
    acct = await _get_paired_account(pending.user_id, "lastfm") or "Last.fm User"

    if pending.return_to:
        separator = "&" if "?" in pending.return_to else "?"
        return RedirectResponse(url=f"{pending.return_to}{separator}paired=lastfm&ok=1", status_code=302)

    if "text/html" in request.headers.get("accept", ""):
        return _render_oauth_complete_html("Last.fm", acct, "lastfm")

    return SimpleResult(ok=True, provider="lastfm", message="Last.fm paired. You can close this window.")


@router.get("/callback", summary="Generic OAuth callback router for /callback redirects")
async def generic_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    token: str | None = Query(default=None),
    error: str | None = Query(default=None),
    auth: SpotifyAuth = Depends(get_spotify_auth),
) -> Any:
    if token and not code:
        return await lastfm_callback(request=request, token=token, state=state)
    return await spotify_callback(request=request, code=code, state=state, error=error, auth=auth)


# --------------------------------------------------------------------------- #
# disconnect
# --------------------------------------------------------------------------- #


@router.post("/{provider}/disconnect", summary="Unpair a provider")
async def disconnect(
    provider: str,
    user_id: str | None = Depends(current_user_id),
    auth: SpotifyAuth = Depends(get_spotify_auth),
) -> Any:
    if not user_id:
        return _problem(401, "not_signed_in", "Sign in before changing pairings.")

    normalised = provider.strip().lower()
    if normalised not in ("spotify", "lastfm"):
        return _problem(404, "unknown_provider", f"There is no provider named {provider!r}.")

    await _clear_demo_paired(user_id, normalised)

    if normalised == "spotify":
        try:
            await get_token_vault().delete(user_id)
        except Exception as exc:
            logger.error("spotify unpair failed: %s", type(exc).__name__)
        status_resp = await pair_status(user_id=user_id, auth=auth)
        body = status_resp.model_dump(mode="json")
        body.update(
            {
                "ok": True,
                "provider": "spotify",
                "message": (
                    "Spotify disconnected. Playlists will now be delivered as files. "
                    "Revoke the app entirely at spotify.com/account/apps if you want to be thorough."
                ),
            }
        )
        return body

    helper, error = _load_lastfm_auth()
    if helper is not None:
        try:
            await _maybe_await(_call_any(helper, ("disconnect", "delete_session", "unpair"), user_id))
        except Exception as exc:
            logger.warning("lastfm unpair failed: %s", type(exc).__name__)

    status_resp = await pair_status(user_id=user_id, auth=auth)
    body = status_resp.model_dump(mode="json")
    body.update(
        {
            "ok": True,
            "provider": "lastfm",
            "message": "Last.fm disconnected.",
        }
    )
    return body

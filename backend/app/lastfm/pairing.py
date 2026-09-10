"""Last.fm web authentication, so listeners pair in-app.

The point of this module is that nobody copy-pastes an API key. After Google
sign-in, BAROGROOVE sends the listener to Last.fm, Last.fm sends them back,
and we hold a session key on their behalf.

The flow, per Last.fm's Authentication API, sections 3 and 4:

1. ``auth.getToken`` returns a short-lived request token.
2. Send the listener to
   ``https://www.last.fm/api/auth/?api_key=…&token=…&cb=…``.
   They log in (if needed) and grant access.
3. Last.fm redirects to ``cb`` with ``?token=…`` — the same token, now
   authorised.
4. ``auth.getSession`` exchanges it for a **permanent** session key.

Signing (their section 8), verified against the current documentation:

    Take every request parameter *except* ``format`` and ``callback``, sort
    them by parameter name, concatenate ``name`` immediately followed by
    ``value`` for each, append the shared secret, UTF-8 encode, and MD5. The
    lowercase hex digest is ``api_sig``.

    So ``{"method": "auth.getSession", "api_key": "K", "token": "T"}`` signs
    the string ``api_keyKmethodauth.getSessiontokenT`` + secret.

Secrets discipline
------------------
No session key, request token or shared secret is ever logged, put in an
exception message, or included in a ``repr``. :class:`LastfmSession` prints
its key as ``***``. Where a value must appear in a diagnostic it goes through
:func:`redact`, which shows at most the first four characters. Session keys
are sent by POST body rather than query string so they do not land in
intermediary access logs.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Final, Mapping, Protocol, runtime_checkable
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..config import Settings, get_settings
from ..errors import PairingError
from ..http import UpstreamError, get_json, post_json

__all__ = [
    "LASTFM_AUTH_URL",
    "LastfmSession",
    "PairingTicket",
    "TokenVault",
    "InMemoryTokenVault",
    "sign_params",
    "signature_base_string",
    "build_auth_url",
    "request_token",
    "exchange_token",
    "callback_url",
    "redact",
]

SERVICE: Final[str] = "lastfm"
LASTFM_AUTH_URL: Final[str] = "https://www.last.fm/api/auth/"

#: Parameters excluded from the signature. ``format`` is a transport concern
#: and ``callback`` is JSONP; including either produces error 13.
_UNSIGNED: Final[frozenset[str]] = frozenset({"format", "callback", "api_sig"})

#: Last.fm does not document the request-token lifetime; 60 minutes is the
#: commonly observed ceiling. We expire our own ticket well inside that so a
#: stale ticket fails locally instead of as a confusing upstream error 4.
TOKEN_TTL_SECONDS: Final[float] = 15 * 60.0


def redact(value: str | None, *, keep: int = 4) -> str:
    """Render a secret safe to print. Never returns more than *keep* chars."""
    if not value:
        return "<unset>"
    if len(value) <= keep:
        return "*" * len(value)
    return f"{value[:keep]}…({len(value)} chars)"


# --------------------------------------------------------------------------
# signing
# --------------------------------------------------------------------------
def signature_base_string(params: Mapping[str, Any]) -> str:
    """The pre-secret half of the signature. Exposed so tests can assert it.

    Sorted by parameter name, ``name`` then ``value``, no separators.
    """
    items = sorted(
        (str(k), "" if v is None else str(v))
        for k, v in params.items()
        if k not in _UNSIGNED and v is not None
    )
    return "".join(f"{name}{value}" for name, value in items)


def sign_params(params: Mapping[str, Any], *, secret: str) -> str:
    """Compute ``api_sig`` for a Last.fm authenticated call.

    MD5 is not a choice, it is the protocol. It is used here purely as the
    message-authentication scheme Last.fm mandates; nothing in BAROGROOVE
    relies on MD5's collision resistance.
    """
    if not secret:
        raise PairingError("last.fm shared secret is not configured")
    base = signature_base_string(params) + secret
    return hashlib.md5(base.encode("utf-8")).hexdigest()  # noqa: S324 - protocol-mandated


# --------------------------------------------------------------------------
# models
# --------------------------------------------------------------------------
class LastfmSession(BaseModel):
    """A permanent Last.fm session key bound to a username.

    The key does not expire, which is precisely why it must be encrypted at
    rest and never logged. ``repr`` and ``str`` are both safe.
    """

    model_config = ConfigDict(frozen=True)

    username: str
    session_key: str = Field(repr=False)
    subscriber: bool = False

    @field_validator("username", "session_key")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"LastfmSession(username={self.username!r}, session_key='***')"

    __str__ = __repr__


class PairingTicket(BaseModel):
    """A request token plus the state needed to finish the handshake.

    Held by the caller (typically in a signed cookie or short-lived server
    session) between steps 1 and 4. The token is not a credential on its own —
    it is useless without the shared secret — but it is still treated as one.
    """

    model_config = ConfigDict(frozen=True)

    token: str = Field(repr=False)
    callback: str
    issued_at: float = Field(default_factory=time.time)
    #: Opaque CSRF value the caller round-trips through the redirect.
    state: str | None = None

    @property
    def expires_at(self) -> float:
        return self.issued_at + TOKEN_TTL_SECONDS

    def expired(self, *, now: float | None = None) -> bool:
        return (now if now is not None else time.time()) >= self.expires_at

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"PairingTicket(token={redact(self.token)!r}, callback={self.callback!r})"

    __str__ = __repr__


# --------------------------------------------------------------------------
# storage seam
# --------------------------------------------------------------------------
@runtime_checkable
class TokenVault(Protocol):
    """Where a listener's Last.fm session key lives, encrypted at rest.

    This is a **seam, not an implementation**. The Firestore-backed vault
    belongs to another worker; defining the protocol here keeps the pairing
    flow testable and keeps persistence out of it. Implementations are
    expected to encrypt ``session.session_key`` before it touches disk, and to
    key everything on the BAROGROOVE user id from Google sign-in — never on
    the Last.fm username, which the listener can change.
    """

    async def get(self, user_id: str) -> LastfmSession | None:
        """Return the stored session, or ``None`` if the user has not paired."""
        ...

    async def put(self, user_id: str, session: LastfmSession) -> None:
        """Store (and encrypt) a session key for *user_id*."""
        ...

    async def delete(self, user_id: str) -> None:
        """Forget a user's pairing. Must be idempotent."""
        ...


class InMemoryTokenVault:
    """A ``TokenVault`` that keeps everything in a dict.

    For tests, local development and the offline demo. It is not durable and
    it is not encrypted, which is fine because it never leaves the process —
    and it is stated plainly here so nobody deploys it by accident.
    """

    def __init__(self) -> None:
        self._store: dict[str, LastfmSession] = {}

    async def get(self, user_id: str) -> LastfmSession | None:
        return self._store.get(user_id)

    async def put(self, user_id: str, session: LastfmSession) -> None:
        self._store[user_id] = session

    async def delete(self, user_id: str) -> None:
        self._store.pop(user_id, None)

    def __len__(self) -> int:
        return len(self._store)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"InMemoryTokenVault(users={len(self._store)})"


# --------------------------------------------------------------------------
# the flow
# --------------------------------------------------------------------------
def callback_url(path: str = "/auth/lastfm/callback", *, settings: Settings | None = None) -> str:
    """Absolute callback URL on the configured public host.

    Last.fm matches the callback against the one registered on the API
    account, so this must be stable and must be HTTPS.
    """
    cfg = settings or get_settings()
    host = cfg.public_host.strip().rstrip("/")
    if not host:
        raise PairingError("public_host is not configured; cannot build a callback URL")
    if "://" in host:
        base = host
    else:
        base = f"https://{host}"
    return f"{base}/{path.lstrip('/')}"


def build_auth_url(
    token: str,
    callback: str,
    *,
    settings: Settings | None = None,
    state: str | None = None,
) -> str:
    """The URL to send the listener to.

    ``cb`` is passed explicitly rather than relying on the callback registered
    on the API account, so that staging and production can share one account.
    Any ``state`` is appended to the callback rather than to this URL, because
    Last.fm only echoes back ``token``.
    """
    cfg = settings or get_settings()
    if not cfg.lastfm_api_key:
        raise PairingError("last.fm API key is not configured; cannot start pairing")
    if not token.strip():
        raise PairingError("cannot build an auth URL without a request token")

    target = callback
    if state:
        joiner = "&" if "?" in callback else "?"
        target = f"{callback}{joiner}{urlencode({'state': state})}"

    query = urlencode(
        {
            "api_key": cfg.lastfm_api_key,
            "token": token,
            "cb": target,
        }
    )
    return f"{LASTFM_AUTH_URL}?{query}"


async def request_token(
    *,
    settings: Settings | None = None,
    callback: str | None = None,
    state: str | None = None,
) -> PairingTicket:
    """Step 1: ``auth.getToken``.

    Signed, because ``auth.*`` methods always are. Returns a ticket the caller
    should stash for the duration of the redirect.
    """
    cfg = settings or get_settings()
    if not cfg.lastfm_api_key or not cfg.lastfm_api_secret:
        raise PairingError("last.fm API key and secret must both be configured to pair")

    params: dict[str, str] = {"method": "auth.getToken", "api_key": cfg.lastfm_api_key}
    params["api_sig"] = sign_params(params, secret=cfg.lastfm_api_secret)
    params["format"] = "json"

    try:
        payload = await get_json(cfg.lastfm_base, service=SERVICE, params=params, settings=cfg)
    except UpstreamError as exc:
        raise PairingError(f"could not reach Last.fm to request a token: {exc}") from exc

    _raise_for_error(payload, step="auth.getToken")
    token = str((payload or {}).get("token") or "").strip()
    if not token:
        raise PairingError("Last.fm returned no request token")

    return PairingTicket(
        token=token,
        callback=callback or callback_url(settings=cfg),
        state=state,
    )


async def exchange_token(
    token: str,
    *,
    settings: Settings | None = None,
) -> LastfmSession:
    """Step 4: ``auth.getSession``. Returns a permanent session key.

    Sent as a POST body. The session key comes back in the response either
    way, but keeping the signed request out of the query string keeps the
    request token out of proxy and CDN logs.
    """
    cfg = settings or get_settings()
    if not cfg.lastfm_api_key or not cfg.lastfm_api_secret:
        raise PairingError("last.fm API key and secret must both be configured to pair")
    cleaned = token.strip()
    if not cleaned:
        raise PairingError("no request token supplied")

    params: dict[str, str] = {
        "method": "auth.getSession",
        "api_key": cfg.lastfm_api_key,
        "token": cleaned,
    }
    params["api_sig"] = sign_params(params, secret=cfg.lastfm_api_secret)
    body = dict(params)
    body["format"] = "json"

    try:
        payload = await post_json(cfg.lastfm_base, service=SERVICE, data=body, settings=cfg)
    except UpstreamError as exc:
        # The token is redacted; the exception text is user-visible.
        raise PairingError(
            f"could not exchange Last.fm token {redact(cleaned)}: {exc}"
        ) from exc

    _raise_for_error(payload, step="auth.getSession")

    session = (payload or {}).get("session")
    if not isinstance(session, dict):
        raise PairingError("Last.fm returned no session object")

    username = str(session.get("name") or "").strip()
    key = str(session.get("key") or "").strip()
    if not username or not key:
        raise PairingError("Last.fm session response was missing a username or key")

    subscriber = str(session.get("subscriber", "0")).strip() in {"1", "true", "True"}
    return LastfmSession(username=username, session_key=key, subscriber=subscriber)


async def complete_pairing(
    ticket: PairingTicket,
    returned_token: str,
    *,
    user_id: str,
    vault: TokenVault,
    settings: Settings | None = None,
) -> LastfmSession:
    """Steps 3-4 end to end: validate the callback, exchange, persist.

    Rejects a mismatched or stale token before spending an API call on it. The
    comparison is a plain equality check rather than a constant-time one on
    purpose — the token is single-use, short-lived, and already public to the
    listener's own browser.
    """
    if ticket.expired():
        raise PairingError("this pairing link has expired; start again")
    if returned_token.strip() != ticket.token:
        raise PairingError("the token Last.fm returned does not match the one we issued")

    session = await exchange_token(returned_token, settings=settings)
    await vault.put(user_id, session)
    return session


def _raise_for_error(payload: Any, *, step: str) -> None:
    """Last.fm answers auth failures with HTTP 200 and an error body too."""
    if not isinstance(payload, dict):
        raise PairingError(f"{step}: unexpected response from Last.fm")
    if "error" in payload:
        code = payload.get("error")
        message = str(payload.get("message") or "unknown error")
        if str(code) == "13":
            message += " (invalid method signature — check parameter sorting and the secret)"
        elif str(code) == "4":
            message += " (the request token was never authorised, or has already been used)"
        raise PairingError(f"{step} failed (error {code}): {message}")

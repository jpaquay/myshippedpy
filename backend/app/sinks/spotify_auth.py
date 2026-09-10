"""Spotify OAuth 2.0 — Authorization Code with PKCE.

Why PKCE and not the classic confidential-client flow: pairing happens *in the
BAROGROOVE app*, after Google sign-in. The user must never see a client secret,
never copy-paste a key, and never leave the app for longer than one browser
round trip. PKCE (RFC 7636) is precisely the flow for a client that cannot keep
a secret.

VERIFIED against Spotify's current "Authorization Code with PKCE Flow" docs
(checked 2026-09):

  Authorize  GET  https://accounts.spotify.com/authorize
             response_type=code, client_id, scope, code_challenge_method=S256,
             code_challenge, redirect_uri, state

  Token      POST https://accounts.spotify.com/api/token
             Content-Type: application/x-www-form-urlencoded
             grant_type=authorization_code, code, redirect_uri, client_id,
             code_verifier
             -> NO Basic auth header, NO client_secret. That is the whole point.

  Refresh    POST https://accounts.spotify.com/api/token
             grant_type=refresh_token, refresh_token, client_id
             Spotify rotates refresh tokens: the response MAY contain a new
             refresh_token and, when it does, the old one stops working. Always
             persist the new one. When it does NOT, keep the old one — see
             ``SpotifyTokens.rolled_from``.

Nothing in this module logs, reprs, or stringifies a token value. ``SpotifyTokens``
overrides ``__repr__``/``__str__`` so an accidental f-string in someone else's
exception handler cannot leak credentials into a log aggregator.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Final, Mapping, Protocol, Sequence, runtime_checkable
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field

from ..config import get_settings
from ..errors import PairingError
from ..http import UpstreamError, request_json

__all__ = [
    "SPOTIFY_SCOPES",
    "SpotifyTokens",
    "PkcePair",
    "TokenVault",
    "InMemoryTokenVault",
    "SpotifyAuth",
    "generate_code_verifier",
    "code_challenge_for",
    "new_pkce_pair",
    "generate_state",
]

#: Everything BAROGROOVE needs and nothing it does not. Requesting a scope you
#: never exercise is a consent-screen tax the user pays for no reason.
SPOTIFY_SCOPES: Final[tuple[str, ...]] = (
    "playlist-modify-private",   # create + fill the private playlist
    "playlist-modify-public",    # only if the user opts into a public one
    "user-top-read",             # /me/top/{tracks,artists} — the taste signal
    "user-read-private",         # /me, for the user id and product tier
    "user-library-modify",       # PUT /me/library  (Feb-2026 generic shape)
    "user-library-read",         # GET /me/library/contains
)

#: RFC 7636 §4.1: the verifier is 43–128 chars from the unreserved set
#: [A-Za-z0-9-._~]. 64 bytes of entropy base64url-encodes to 86 chars, which is
#: comfortably inside the range and well past the security floor.
_VERIFIER_BYTES: Final[int] = 64
_VERIFIER_MIN: Final[int] = 43
_VERIFIER_MAX: Final[int] = 128

#: Treat a token as expired this far before it actually is. Covers clock skew
#: plus the round trip of the request we are about to make.
_EXPIRY_MARGIN_S: Final[int] = 60


def _b64url(raw: bytes) -> str:
    """base64url with padding stripped, per RFC 7636 Appendix A."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def generate_code_verifier(n_bytes: int = _VERIFIER_BYTES) -> str:
    """A cryptographically random PKCE code verifier.

    ``secrets.token_bytes`` -> base64url yields only characters from the
    unreserved set, so the result is RFC-legal by construction.
    """
    verifier = _b64url(secrets.token_bytes(n_bytes))
    if not _VERIFIER_MIN <= len(verifier) <= _VERIFIER_MAX:  # pragma: no cover
        raise PairingError(
            f"generated PKCE verifier of illegal length {len(verifier)}; "
            f"RFC 7636 requires {_VERIFIER_MIN}..{_VERIFIER_MAX}"
        )
    return verifier


def code_challenge_for(verifier: str) -> str:
    """S256 challenge: BASE64URL(SHA256(ASCII(verifier))).

    Note the hash is over the *ASCII bytes of the verifier string*, not over the
    random bytes it was derived from. Getting this wrong produces an
    ``invalid_grant`` at token exchange that is genuinely miserable to debug.
    """
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return _b64url(digest)


def generate_state(n_bytes: int = 24) -> str:
    """Opaque CSRF state. Must be validated on callback; see routes/pairing.py."""
    return _b64url(secrets.token_bytes(n_bytes))


class PkcePair:
    """Verifier + its S256 challenge, generated together so they cannot drift."""

    __slots__ = ("verifier", "challenge", "method")

    def __init__(self, verifier: str | None = None) -> None:
        self.verifier: str = verifier or generate_code_verifier()
        self.challenge: str = code_challenge_for(self.verifier)
        self.method: str = "S256"

    def __repr__(self) -> str:  # never leak the verifier
        return f"PkcePair(method={self.method!r}, challenge={self.challenge!r}, verifier=<redacted>)"


class SpotifyTokens(BaseModel):
    """A user's Spotify credentials. Treat every field as a secret."""

    model_config = ConfigDict(frozen=True)

    access_token: str
    refresh_token: str | None = None
    token_type: str = "Bearer"
    scope: str = ""
    expires_at: datetime
    obtained_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    #: True when a refresh reused the previous refresh token because Spotify did
    #: not issue a new one. Purely diagnostic.
    rolled_from: bool = False

    # -- secret hygiene ------------------------------------------------------ #

    def __repr__(self) -> str:
        return (
            f"SpotifyTokens(expires_at={self.expires_at.isoformat()}, "
            f"scope={self.scope!r}, access_token=<redacted>, refresh_token=<redacted>)"
        )

    __str__ = __repr__

    # -- expiry -------------------------------------------------------------- #

    @property
    def expires_in_s(self) -> float:
        return (self.expires_at - datetime.now(timezone.utc)).total_seconds()

    def is_expired(self, *, margin_s: int = _EXPIRY_MARGIN_S) -> bool:
        """Expired, or close enough that using it would be a race."""
        return self.expires_in_s <= margin_s

    @property
    def can_refresh(self) -> bool:
        return bool(self.refresh_token)

    @property
    def scopes(self) -> tuple[str, ...]:
        return tuple(s for s in self.scope.split() if s)

    def has_scopes(self, required: Sequence[str] = SPOTIFY_SCOPES) -> bool:
        """Spotify grants exactly what it lists in ``scope``; a user who paired
        before we added a scope will be missing it and must re-consent."""
        granted = set(self.scopes)
        return all(s in granted for s in required)

    def missing_scopes(self, required: Sequence[str] = SPOTIFY_SCOPES) -> list[str]:
        granted = set(self.scopes)
        return [s for s in required if s not in granted]

    @property
    def authorization_header(self) -> dict[str, str]:
        return {"Authorization": f"{self.token_type or 'Bearer'} {self.access_token}"}

    @classmethod
    def from_response(
        cls,
        payload: Mapping[str, Any],
        *,
        fallback_refresh: str | None = None,
    ) -> SpotifyTokens:
        """Build from an ``/api/token`` response body."""
        access = payload.get("access_token")
        if not access:
            raise PairingError("Spotify token response contained no access_token.")

        try:
            expires_in = int(payload.get("expires_in", 3600))
        except (TypeError, ValueError):
            expires_in = 3600

        new_refresh = payload.get("refresh_token")
        return cls(
            access_token=str(access),
            # Refresh-token rotation: keep the old one when Spotify omits a new
            # one, otherwise the user silently loses the ability to refresh.
            refresh_token=str(new_refresh) if new_refresh else fallback_refresh,
            token_type=str(payload.get("token_type") or "Bearer"),
            scope=str(payload.get("scope") or ""),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
            rolled_from=bool(fallback_refresh and not new_refresh),
        )


# --------------------------------------------------------------------------- #
# token storage
# --------------------------------------------------------------------------- #


@runtime_checkable
class TokenVault(Protocol):
    """Encrypted per-user token storage.

    The Firestore-backed implementation is another worker's module. This
    protocol is the seam. Implementations are expected to encrypt at rest
    (Cloud KMS envelope encryption or Firestore CMEK) — the in-memory one below
    obviously does not, which is why it is process-local and test-only.
    """

    async def get(self, user_id: str) -> SpotifyTokens | None: ...

    async def put(self, user_id: str, tokens: SpotifyTokens) -> None: ...

    async def delete(self, user_id: str) -> None: ...


class InMemoryTokenVault:
    """Process-local ``TokenVault``. Dies with the process, by design.

    Fine for local development and tests. In production it would also silently
    un-pair every user on each Cloud Run cold start, so: do not.
    """

    def __init__(self) -> None:
        self._store: dict[str, SpotifyTokens] = {}

    async def get(self, user_id: str) -> SpotifyTokens | None:
        return self._store.get(user_id)

    async def put(self, user_id: str, tokens: SpotifyTokens) -> None:
        self._store[user_id] = tokens

    async def delete(self, user_id: str) -> None:
        self._store.pop(user_id, None)

    # -- test/introspection helpers (never expose over HTTP) ----------------- #

    def user_ids(self) -> list[str]:
        return list(self._store)

    def __len__(self) -> int:
        return len(self._store)

    def __repr__(self) -> str:
        return f"InMemoryTokenVault(users={len(self._store)})"


# --------------------------------------------------------------------------- #
# the flow
# --------------------------------------------------------------------------- #


class SpotifyAuth:
    """Builds authorize URLs and exchanges/refreshes tokens."""

    def __init__(self, *, settings: Any | None = None, vault: TokenVault | None = None) -> None:
        self._settings = settings or get_settings()
        self._vault: TokenVault = vault or InMemoryTokenVault()

    # -- configuration ------------------------------------------------------- #

    @property
    def vault(self) -> TokenVault:
        return self._vault

    @property
    def configured(self) -> bool:
        """PKCE needs only a client id. A missing secret is not a problem here —
        it is the intended state for a public client."""
        return bool(getattr(self._settings, "spotify_client_id", None))

    @property
    def client_id(self) -> str:
        client_id = getattr(self._settings, "spotify_client_id", None)
        if not client_id:
            raise PairingError("Spotify is not configured: spotify_client_id is unset.")
        return str(client_id)

    @property
    def redirect_uri(self) -> str:
        return str(
            getattr(
                self._settings,
                "spotify_redirect_uri",
                "https://bg.netdev.be/api/pair/spotify/callback",
            )
        )

    @property
    def _accounts_base(self) -> str:
        return str(
            getattr(self._settings, "spotify_accounts_base", "https://accounts.spotify.com")
        ).rstrip("/")

    # -- step 1: authorize --------------------------------------------------- #

    def new_pkce(self) -> PkcePair:
        return PkcePair()

    def build_authorize_url(
        self,
        state: str,
        scopes: Sequence[str] = SPOTIFY_SCOPES,
        *,
        challenge: str | None = None,
        pkce: PkcePair | None = None,
        show_dialog: bool = False,
    ) -> str:
        """The URL to send the user to.

        Pass either ``pkce`` (preferred — keeps the pair together) or a
        precomputed ``challenge``. The verifier stays server-side; it is never
        part of this URL.
        """
        if pkce is not None:
            challenge = pkce.challenge
        if not challenge:
            raise PairingError("build_authorize_url requires a PKCE challenge.")
        if not state:
            raise PairingError("build_authorize_url requires a state value (CSRF guard).")

        params: dict[str, str] = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "state": state,
            "scope": " ".join(scopes),
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        }
        if show_dialog:
            # Forces the consent screen even for an already-authorized user.
            # Useful when re-pairing to widen scopes.
            params["show_dialog"] = "true"
        return f"{self._accounts_base}/authorize?{urlencode(params)}"

    # -- step 2: exchange ---------------------------------------------------- #

    async def exchange_code(self, code: str, verifier: str) -> SpotifyTokens:
        """Swap ``code`` + ``verifier`` for tokens.

        ``redirect_uri`` is sent for validation only — Spotify compares it to the
        one used at /authorize and rejects a mismatch. There is no redirect.
        """
        if not code:
            raise PairingError("Spotify returned no authorization code.")
        if not verifier:
            raise PairingError("Missing PKCE verifier; the pairing state has expired.")

        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "code_verifier": verifier,
        }
        payload = await self._token_request(form, what="authorization code exchange")
        return SpotifyTokens.from_response(payload)

    # -- step 3: refresh ----------------------------------------------------- #

    async def refresh(self, refresh_token: str) -> SpotifyTokens:
        """Mint a fresh access token.

        PKCE clients send ``client_id`` in the body instead of Basic-authing with
        a secret. Spotify may rotate the refresh token here; ``from_response``
        carries the old one forward when it does not.
        """
        if not refresh_token:
            raise PairingError("No refresh token stored for this user.")

        form = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
        }
        payload = await self._token_request(form, what="token refresh")
        return SpotifyTokens.from_response(payload, fallback_refresh=refresh_token)

    async def _token_request(self, form: Mapping[str, str], *, what: str) -> Mapping[str, Any]:
        try:
            payload = await request_json(
                "POST",
                f"{self._accounts_base}/api/token",
                service="spotify-accounts",
                data=dict(form),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                settings=self._settings,
            )
        except UpstreamError as exc:
            # Deliberately does not include the form body in the message: it
            # contains the code verifier and possibly a refresh token.
            raise PairingError(
                f"Spotify {what} failed with HTTP {exc.status or '?'}. "
                "Common causes: the pairing link was reused, the redirect URI in "
                "the Spotify dashboard does not match "
                f"'{self.redirect_uri}' exactly, or the app's 5-user Developer "
                "Mode allowance is full."
            ) from exc

        if not isinstance(payload, Mapping):
            raise PairingError(f"Spotify {what} returned an unreadable response.")
        if payload.get("error"):
            raise PairingError(
                f"Spotify {what} rejected: {payload.get('error')} — "
                f"{payload.get('error_description') or 'no detail given'}."
            )
        return payload

    # -- convenience: always-valid access token ------------------------------ #

    async def access_token_for(self, user_id: str) -> str | None:
        """Return a usable access token for ``user_id``, refreshing if needed.

        ``None`` means "not paired, or paired with credentials that can no longer
        be revived" — the caller degrades, it does not raise. That contract is
        what lets ``SpotifySink.write`` promise never to blow up.
        """
        if not user_id:
            return None
        tokens = await self._vault.get(user_id)
        if tokens is None:
            return None

        if not tokens.is_expired():
            return tokens.access_token

        if not tokens.can_refresh:
            return None

        try:
            refreshed = await self.refresh(tokens.refresh_token or "")
        except PairingError:
            # A dead refresh token is a normal end-of-life event, not an outage.
            # Drop it so the UI shows "not paired" rather than retrying forever.
            await self._vault.delete(user_id)
            return None

        await self._vault.put(user_id, refreshed)
        return refreshed.access_token

    async def is_paired(self, user_id: str | None) -> bool:
        if not user_id:
            return False
        return await self._vault.get(user_id) is not None


def new_pkce_pair() -> PkcePair:
    """Module-level convenience mirroring ``SpotifyAuth.new_pkce``."""
    return PkcePair()


def _now_s() -> float:  # pragma: no cover - trivial, exists for monkeypatching
    return time.time()

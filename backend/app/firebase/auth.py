"""Firebase Authentication (Google sign-in) for Barogroove.

The public surface is two FastAPI dependencies and one pure function:

* :func:`current_user`          -- 401s unless a valid Firebase ID token is present.
* :func:`current_user_optional` -- returns ``None`` instead of raising.
* :func:`verify_bearer_token`   -- the actual verification, framework-free and
  therefore testable without spinning up an app.

Verification strategy, in order of preference
---------------------------------------------
1. ``firebase_admin.auth.verify_id_token``. Imported *lazily*, because the SDK
   is a heavy dependency that wants credentials the moment you initialise it,
   and this module has to import in a bare venv.
2. A hand-rolled RS256 verification against Google's public x.509 certs for
   ``securetoken@system.gserviceaccount.com``. This is the documented fallback
   path for "verify ID tokens using a third-party JWT library" and checks
   signature, ``iss``, ``aud``, ``exp``, ``iat``, ``auth_time`` and a non-empty
   ``sub``. Certs are cached in-process and honour the endpoint's
   ``Cache-Control: max-age``.
3. Dev tokens (``dev:<uid>``) -- local only, see below.

The dev-token escape hatch
--------------------------
A bearer token of the literal form ``dev:<uid>`` is accepted **only** when both
of the following hold:

* ``settings.auth_allow_insecure_dev_tokens`` is true, and
* ``settings.environment == "local"``.

Two independent conditions, checked in one place (:func:`dev_tokens_enabled`),
so there is exactly one thing to audit. Flipping ``BG_ENVIRONMENT`` to ``dev``
or ``prod`` disables it even if somebody leaves the flag on in a config map,
and clearing the flag disables it even on a laptop. Every use logs a warning at
WARNING level with the uid, because a dev token that silently works in a shared
environment is how you end up impersonating a stranger.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Final

from pydantic import BaseModel, Field

# `Request` must be imported at RUNTIME, not just for typing. Combined with
# `from __future__ import annotations`, a TYPE_CHECKING-only import leaves the
# annotation as an unresolvable string, and FastAPI — which evaluates dependency
# annotations to decide what each parameter *is* — then classifies `request` as a
# required query parameter. Every authenticated endpoint answers 422 instead of
# running. FastAPI is a hard dependency of this application; import it plainly.
from fastapi import Request  # noqa: E402

logger = logging.getLogger("barogroove.firebase.auth")

# Google's public x.509 certificates for Firebase ID tokens. Documented and
# stable; the JSON body maps `kid` -> PEM certificate.
GOOGLE_SECURETOKEN_CERTS_URL: Final[str] = (
    "https://www.googleapis.com/robots/v1/metadata/x509/"
    "securetoken@system.gserviceaccount.com"
)
FIREBASE_ISSUER_PREFIX: Final[str] = "https://securetoken.google.com/"

# Bounded everything: we never let an auth check hang a request.
_CERT_FETCH_TIMEOUT_S: Final[float] = 5.0
_CERT_FETCH_ATTEMPTS: Final[int] = 3
_CERT_MIN_TTL_S: Final[float] = 60.0
_CERT_MAX_TTL_S: Final[float] = 24 * 3600.0
_CERT_FALLBACK_TTL_S: Final[float] = 3600.0

# Small tolerance for clock drift between Google and this container.
_CLOCK_SKEW_S: Final[int] = 60

DEV_TOKEN_PREFIX: Final[str] = "dev:"

ALLOWED_IAM_USERS: Final[frozenset[str]] = frozenset({
    "jpaquay@gmail.com",
    "jerome@netdev.be",
    "jpaquay@gcp.altostrat.com",
    "jpaquay@google.com",
    "elena.ruizroman@gmail.com",
    "arthurpaquay@gmail.com",
})


class AuthUser(BaseModel):
    """An authenticated Barogroove listener.

    ``is_dev`` is deliberately part of the model rather than a side channel:
    downstream code (the almanac, the token vault) can refuse to persist
    anything against a synthetic identity if it wants to.
    """

    uid: str = Field(min_length=1, max_length=128)
    email: str | None = None
    name: str | None = None
    picture: str | None = None
    provider: str = "unknown"
    is_dev: bool = False

    @property
    def display_name(self) -> str:
        """Best-effort human label. Never raises, never returns empty."""
        return self.name or self.email or self.uid


class AuthError(Exception):
    """Token was absent, malformed, expired or not ours.

    Carries an HTTP status so the FastAPI layer does not have to guess, but is
    a plain exception so :func:`verify_bearer_token` stays framework-free.
    """

    def __init__(self, detail: str, *, status_code: int = 401) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


# --------------------------------------------------------------------------
# Settings access
# --------------------------------------------------------------------------


def _settings() -> Any:
    """Fetch app settings, tolerating a partially-wired app.

    Returns a permissive stand-in if ``app.config`` is unavailable. The
    stand-in denies dev tokens, which is the safe direction to fail.
    """
    try:
        from ..config import get_settings  # local import: avoids import cycles
    except Exception:  # pragma: no cover - only when config is missing entirely
        logger.warning("app.config unavailable; auth falling back to strict defaults")
        return _StrictDefaults()
    try:
        return get_settings()
    except Exception:  # pragma: no cover - misconfigured env
        logger.exception("get_settings() failed; auth falling back to strict defaults")
        return _StrictDefaults()


class _StrictDefaults:
    """Fail-closed settings stand-in. Dev tokens off, no project id."""

    environment = "prod"
    auth_allow_insecure_dev_tokens = False
    firebase_project_id = ""


def dev_tokens_enabled(settings: Any) -> bool:
    """True only when insecure dev tokens are permitted.

    Both conditions are required. This is the single audit point for the
    escape hatch; do not inline this check anywhere else.
    """
    flag = bool(getattr(settings, "auth_allow_insecure_dev_tokens", False))
    env = str(getattr(settings, "environment", "prod"))
    return flag and env == "local"


def _project_id(settings: Any) -> str:
    """Firebase project id, falling back to the GCP project id."""
    return str(
        getattr(settings, "firebase_project_id", "")
        or getattr(settings, "gcp_project", "")
        or ""
    )


# --------------------------------------------------------------------------
# Header parsing
# --------------------------------------------------------------------------


def extract_bearer_token(authorization: str | None) -> str | None:
    """Pull the token out of an ``Authorization`` header.

    Case-insensitive on the scheme, because clients are creative. Returns
    ``None`` rather than raising so optional-auth paths stay cheap.
    """
    if not authorization:
        return None
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


# --------------------------------------------------------------------------
# Certificate cache
# --------------------------------------------------------------------------


class _CertCache:
    """In-process cache of Google's signing certificates.

    One lock, so a burst of cold requests triggers one fetch rather than N.
    On refresh failure we keep serving the stale set if we have one -- an
    expired cache plus a flaky network should degrade to "tokens still verify"
    rather than "nobody can log in".
    """

    def __init__(self) -> None:
        self._certs: dict[str, str] = {}
        self._expires_at: float = 0.0
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        # Created lazily: an asyncio.Lock built at import time can bind to the
        # wrong event loop under some test runners.
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def clear(self) -> None:
        self._certs = {}
        self._expires_at = 0.0

    async def get(self, *, force: bool = False) -> dict[str, str]:
        now = time.monotonic()
        if not force and self._certs and now < self._expires_at:
            return self._certs
        async with self._get_lock():
            now = time.monotonic()
            if not force and self._certs and now < self._expires_at:
                return self._certs
            try:
                certs, ttl = await _fetch_certs()
            except Exception as exc:
                if self._certs:
                    logger.warning(
                        "cert refresh failed (%s); serving %d stale certs",
                        exc,
                        len(self._certs),
                    )
                    # Back off briefly so we do not hammer a broken endpoint.
                    self._expires_at = time.monotonic() + _CERT_MIN_TTL_S
                    return self._certs
                raise AuthError("cannot reach Google signing certificates") from exc
            self._certs = certs
            self._expires_at = time.monotonic() + ttl
            return self._certs


_cert_cache = _CertCache()


async def _fetch_certs() -> tuple[dict[str, str], float]:
    """Fetch the x.509 cert map, with retry and timeout.

    Prefers the shared ``app.http`` helper (retry + timeout already wired). If
    that module is unavailable or has a different signature, falls back to
    ``urllib`` on a worker thread so we never block the event loop.
    """
    try:
        from ..http import get_json  # type: ignore[attr-defined]
    except Exception:
        get_json = None  # type: ignore[assignment]

    if get_json is not None:
        try:
            payload = await get_json(
                GOOGLE_SECURETOKEN_CERTS_URL, timeout=_CERT_FETCH_TIMEOUT_S
            )
        except TypeError:
            # Shared helper does not take a timeout kwarg. Still bounded below.
            payload = await asyncio.wait_for(
                get_json(GOOGLE_SECURETOKEN_CERTS_URL),
                timeout=_CERT_FETCH_TIMEOUT_S * _CERT_FETCH_ATTEMPTS,
            )
        if isinstance(payload, dict):
            certs = {str(k): str(v) for k, v in payload.items()}
            if certs:
                return certs, _CERT_FALLBACK_TTL_S
        raise AuthError("signing certificate endpoint returned an unusable body")

    return await asyncio.to_thread(_fetch_certs_blocking)


def _fetch_certs_blocking() -> tuple[dict[str, str], float]:
    """Blocking cert fetch. Runs on a worker thread, bounded retry."""
    import json
    import urllib.request

    last: Exception | None = None
    for attempt in range(_CERT_FETCH_ATTEMPTS):
        try:
            req = urllib.request.Request(  # noqa: S310 - constant https URL
                GOOGLE_SECURETOKEN_CERTS_URL,
                headers={"User-Agent": "barogroove/1.0"},
            )
            with urllib.request.urlopen(  # noqa: S310 - constant https URL
                req, timeout=_CERT_FETCH_TIMEOUT_S
            ) as resp:
                body = resp.read()
                ttl = _parse_max_age(resp.headers.get("Cache-Control"))
            certs = json.loads(body)
            if not isinstance(certs, dict) or not certs:
                raise AuthError("signing certificate endpoint returned an empty map")
            return {str(k): str(v) for k, v in certs.items()}, ttl
        except Exception as exc:  # noqa: BLE001 - retried below
            last = exc
            if attempt + 1 < _CERT_FETCH_ATTEMPTS:
                time.sleep(0.25 * (2**attempt))
    raise AuthError(f"cannot fetch signing certificates: {last}")


def _parse_max_age(cache_control: str | None) -> float:
    """Extract ``max-age`` seconds, clamped to something sane."""
    if not cache_control:
        return _CERT_FALLBACK_TTL_S
    for part in cache_control.split(","):
        part = part.strip()
        if part.startswith("max-age="):
            try:
                return max(_CERT_MIN_TTL_S, min(_CERT_MAX_TTL_S, float(part[8:])))
            except ValueError:
                break
    return _CERT_FALLBACK_TTL_S


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------


async def verify_bearer_token(token: str, settings: Any | None = None) -> AuthUser:
    """Verify a Firebase ID token and return the caller's identity.

    Raises :class:`AuthError` on anything short of a fully valid token. The
    only non-cryptographic path is the dev token, and it is gated on two
    settings that both have to be wrong for it to leak into a deployment.
    """
    settings = settings if settings is not None else _settings()
    token = (token or "").strip()
    if not token:
        raise AuthError("missing bearer token")

    if token.startswith(DEV_TOKEN_PREFIX):
        return _accept_dev_token(token, settings)

    project_id = _project_id(settings)
    if not project_id:
        # Without a project id we cannot check the audience, and a token with
        # an unchecked audience is a token from any Firebase project on earth.
        raise AuthError("firebase_project_id is not configured", status_code=503)

    claims = await _verify_with_admin_sdk(token, project_id)
    if claims is None:
        claims = await _verify_with_jwt_library(token, project_id)
    user = _user_from_claims(claims)
    env = str(getattr(settings, "environment", "local") or "local").strip().lower()
    if not user.is_dev and env != "local":
        email = (user.email or "").strip().lower()
        if email not in ALLOWED_IAM_USERS:
            logger.warning("IAM allowlist rejected unauthorized email=%r", user.email)
            raise AuthError(
                f"Access denied: {user.email or 'unknown account'} is not authorized.",
                status_code=403,
            )
    return user


def _accept_dev_token(token: str, settings: Any) -> AuthUser:
    """Handle ``dev:<uid>``. Refuses loudly unless both gates are open."""
    if not dev_tokens_enabled(settings):
        # Do not explain which gate is shut. An attacker probing prod learns
        # nothing beyond "no".
        logger.warning(
            "rejected dev token (environment=%s, flag=%s)",
            getattr(settings, "environment", "?"),
            getattr(settings, "auth_allow_insecure_dev_tokens", "?"),
        )
        raise AuthError("invalid authentication credentials")

    uid = token[len(DEV_TOKEN_PREFIX) :].strip()
    if not uid or len(uid) > 128:
        raise AuthError("malformed dev token")

    logger.warning(
        "INSECURE DEV TOKEN ACCEPTED for uid=%r -- signature was NOT verified. "
        "This path exists only because BG_ENVIRONMENT=local and "
        "BG_AUTH_ALLOW_INSECURE_DEV_TOKENS is set.",
        uid,
    )
    return AuthUser(
        uid=uid,
        email=f"{uid}@dev.invalid",
        name=f"dev:{uid}",
        picture=None,
        provider="dev",
        is_dev=True,
    )


async def _verify_with_admin_sdk(token: str, project_id: str) -> dict[str, Any] | None:
    """Verify via ``firebase_admin`` if it is installed and initialisable.

    Returns ``None`` (not an error) when the SDK is simply unavailable, so the
    caller can fall through to the JWT path. Returns claims on success and
    raises :class:`AuthError` when the SDK is present and says the token is
    bad -- that is a real verdict, not a missing dependency.
    """
    try:
        import firebase_admin  # noqa: PLC0415 - deliberately lazy
        from firebase_admin import auth as fb_auth  # noqa: PLC0415
    except Exception:
        logger.debug("firebase-admin not importable; using JWT verification path")
        return None

    try:
        _ensure_admin_app(firebase_admin, project_id)
    except Exception as exc:  # credentials missing, ADC unavailable, ...
        logger.debug("firebase-admin not initialisable (%s); using JWT path", exc)
        return None

    def _verify() -> dict[str, Any]:
        # check_revoked=False keeps this to a local signature check: enabling it
        # costs a network round trip to the Firebase Auth backend on every
        # request. Revocation is handled by short token lifetimes (1h) instead.
        return dict(fb_auth.verify_id_token(token, check_revoked=False))

    try:
        return await asyncio.wait_for(asyncio.to_thread(_verify), timeout=10.0)
    except asyncio.TimeoutError as exc:
        raise AuthError("token verification timed out", status_code=503) from exc
    except Exception as exc:
        # The SDK raises a family of ExpiredIdTokenError / InvalidIdTokenError /
        # RevokedIdTokenError. All of them mean the same thing to a caller.
        raise AuthError(f"invalid ID token: {type(exc).__name__}") from exc


def _ensure_admin_app(firebase_admin: Any, project_id: str) -> Any:
    """Idempotently initialise the default firebase-admin app.

    Uses Application Default Credentials, which is what Cloud Run hands us.
    ``projectId`` is passed explicitly so audience checking does not depend on
    credential introspection.
    """
    try:
        return firebase_admin.get_app()
    except ValueError:
        return firebase_admin.initialize_app(options={"projectId": project_id})


async def _verify_with_jwt_library(token: str, project_id: str) -> dict[str, Any]:
    """Verify the ID token manually against Google's x.509 certificates.

    Checks, in order: header is RS256 with a known ``kid``; signature; ``aud``
    equals the project id; ``iss`` is ``https://securetoken.google.com/<pid>``;
    ``exp``/``iat`` within tolerance; ``sub`` present and non-empty. Anything
    less is not verification, it is decoding.
    """
    try:
        import jwt  # noqa: PLC0415 - lazy: pyjwt is optional at import time
        from jwt import algorithms as _jwt_algorithms  # noqa: F401,PLC0415
    except Exception as exc:  # pragma: no cover - dependency missing
        raise AuthError(
            "no ID-token verifier available (install firebase-admin or pyjwt)",
            status_code=503,
        ) from exc

    try:
        header = jwt.get_unverified_header(token)
    except Exception as exc:
        raise AuthError("malformed ID token") from exc

    if header.get("alg") != "RS256":
        # Blocks alg=none and HS256 key-confusion outright.
        raise AuthError("unexpected token algorithm")
    kid = header.get("kid")
    if not kid:
        raise AuthError("ID token has no key id")

    certs = await _cert_cache.get()
    pem = certs.get(kid)
    if pem is None:
        # Key rotation: refetch once before giving up.
        certs = await _cert_cache.get(force=True)
        pem = certs.get(kid)
    if pem is None:
        raise AuthError("ID token signed by an unknown key")

    public_key = _public_key_from_cert(pem)
    issuer = f"{FIREBASE_ISSUER_PREFIX}{project_id}"
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            key=public_key,
            algorithms=["RS256"],
            audience=project_id,
            issuer=issuer,
            leeway=_CLOCK_SKEW_S,
            options={
                "require": ["exp", "iat", "aud", "iss", "sub"],
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_aud": True,
                "verify_iss": True,
            },
        )
    except Exception as exc:
        raise AuthError(f"invalid ID token: {type(exc).__name__}") from exc

    sub = str(claims.get("sub") or "")
    if not sub or len(sub) > 128:
        raise AuthError("ID token has no usable subject")
    # `auth_time` must be in the past; a future auth_time is nonsense and the
    # Firebase spec calls for rejecting it.
    auth_time = claims.get("auth_time")
    if isinstance(auth_time, (int, float)) and auth_time > time.time() + _CLOCK_SKEW_S:
        raise AuthError("ID token auth_time is in the future")
    return claims


def _public_key_from_cert(pem: str) -> Any:
    """Extract an RSA public key from a PEM x.509 certificate."""
    from cryptography.hazmat.primitives.serialization import (  # noqa: PLC0415
        load_pem_public_key,
    )
    from cryptography.x509 import load_pem_x509_certificate  # noqa: PLC0415

    data = pem.encode("utf-8") if isinstance(pem, str) else pem
    try:
        return load_pem_x509_certificate(data).public_key()
    except Exception:
        # Google serves certificates here, but tolerate a bare public key so a
        # JWKS-style override does not break the path.
        return load_pem_public_key(data)


def _user_from_claims(claims: dict[str, Any]) -> AuthUser:
    """Map verified Firebase claims onto :class:`AuthUser`.

    ``firebase.sign_in_provider`` is the useful one (``google.com`` for the
    Google sign-in we ship); ``provider_id`` is the legacy spelling.
    """
    firebase_block = claims.get("firebase")
    provider = "unknown"
    if isinstance(firebase_block, dict):
        provider = str(
            firebase_block.get("sign_in_provider")
            or firebase_block.get("provider_id")
            or "unknown"
        )
    uid = str(claims.get("user_id") or claims.get("sub") or "")
    return AuthUser(
        uid=uid,
        email=(str(claims["email"]) if claims.get("email") else None),
        name=(str(claims["name"]) if claims.get("name") else None),
        picture=(str(claims["picture"]) if claims.get("picture") else None),
        provider=provider,
        is_dev=False,
    )


# --------------------------------------------------------------------------
# FastAPI dependencies
# --------------------------------------------------------------------------


def _http_exception(err: AuthError) -> Exception:
    """Translate an AuthError into an HTTPException, if FastAPI is present."""
    try:
        from fastapi import HTTPException  # noqa: PLC0415
    except Exception:  # pragma: no cover - non-FastAPI host
        return err
    return HTTPException(
        status_code=err.status_code,
        detail=err.detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def current_user(request: Request) -> AuthUser:
    """FastAPI dependency: the signed-in user, or HTTP 401.

    Usage::

        @router.get("/thing")
        async def thing(user: AuthUser = Depends(current_user)) -> ...:
            ...
    """
    token = extract_bearer_token(request.headers.get("authorization"))
    if token is None:
        raise _http_exception(AuthError("missing or malformed Authorization header"))
    try:
        user = await verify_bearer_token(token)
    except AuthError as err:
        raise _http_exception(err) from None
    except Exception as exc:  # unexpected: still a 401, but log it properly
        logger.exception("unexpected auth failure")
        raise _http_exception(AuthError("authentication failed")) from exc
    # Stash on request.state so downstream middleware/handlers can read the
    # identity without re-verifying the token.
    try:
        request.state.user = user
    except Exception:  # pragma: no cover - exotic ASGI shims
        pass
    return user


async def current_user_optional(request: Request) -> AuthUser | None:
    """FastAPI dependency: the signed-in user, or ``None``.

    For endpoints that personalise when they can and still work when they
    cannot. Never raises on a bad token -- an anonymous caller and a caller
    with a stale token get the same anonymous experience.
    """
    token = extract_bearer_token(request.headers.get("authorization"))
    if token is None:
        return None
    try:
        user = await verify_bearer_token(token)
    except AuthError as err:
        if err.status_code == 403:
            raise _http_exception(err) from None
        logger.debug("optional auth: rejecting token (%s)", err.detail)
        return None
    except Exception:
        logger.exception("optional auth: unexpected failure; continuing anonymously")
        return None
    try:
        request.state.user = user
    except Exception:  # pragma: no cover
        pass
    return user


__all__ = [
    "DEV_TOKEN_PREFIX",
    "GOOGLE_SECURETOKEN_CERTS_URL",
    "AuthError",
    "AuthUser",
    "current_user",
    "current_user_optional",
    "dev_tokens_enabled",
    "extract_bearer_token",
    "verify_bearer_token",
]

"""Encrypted per-user provider-token storage: the Barogroove ``TokenVault``.

Spotify refresh tokens and Last.fm session keys are the most dangerous bytes in
this system. A leaked weather reading is a shrug; a leaked refresh token is
somebody else's music library. So:

* **Encrypted at rest with Fernet** (AES-128-CBC + HMAC-SHA256, from
  ``cryptography``), keyed by ``settings.token_encryption_key``, which comes
  from Secret Manager in prod.
* **Never logged.** Not the payload, not the ciphertext, not the key, not a
  prefix of any of them. The only thing that ever reaches a log line is the
  uid and the provider name.
* **Never client-readable.** ``firestore.rules`` denies all client access to
  ``users/{uid}/tokens/{provider}``. Only the backend service account -- via the
  Admin SDK, which bypasses rules -- can touch these documents.

The insecure-dev fallback
-------------------------
If no key is configured and we are in ``local``, the vault still works, but it
stores the payload with ``encryption: "INSECURE-DEV-PLAINTEXT"`` and screams
into the log on every read and write. It does **not** quietly write plaintext
under a field named ``ciphertext`` and let you believe it is encrypted -- that
is how a laptop-shaped decision becomes a production incident.

Outside ``local``, a missing key is a :class:`ConfigurationError` at first use.
Refusing to start is the correct behaviour when the alternative is storing
credentials in the clear.

Envelope shape (stable; the Spotify/Last.fm workers bind to this)::

    {
      "user_id":     "<uid>",
      "provider":    "spotify",
      "encryption":  "fernet" | "INSECURE-DEV-PLAINTEXT",
      "key_id":      "<8-hex fingerprint of the key, or 'none'>",
      "ciphertext":  "<urlsafe-b64 Fernet token>",   # fernet only
      "insecure_payload": { ... },                    # dev marker only
      "created_at":  <timestamp>,
      "updated_at":  <timestamp>,
      "schema":      1
    }

Exactly one of ``ciphertext`` / ``insecure_payload`` is present. A reader that
finds ``insecure_payload`` in a non-local environment must refuse it, and
:class:`FirestoreTokenVault` does.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Final, Protocol, runtime_checkable

logger = logging.getLogger("barogroove.firebase.tokens")

ENC_FERNET: Final[str] = "fernet"
ENC_INSECURE: Final[str] = "INSECURE-DEV-PLAINTEXT"
ENVELOPE_SCHEMA: Final[int] = 1

# A single payload should be a handful of short strings. Anything larger is a
# bug or an attack; Firestore's own ceiling is 1 MiB per document.
MAX_PAYLOAD_BYTES: Final[int] = 64 * 1024

_LOUD_DEV_WARNING: Final[str] = (
    "TOKEN VAULT IS RUNNING WITHOUT ENCRYPTION. Provider credentials for "
    "uid=%s provider=%s are stored in CLEARTEXT under the %r marker. This is "
    "permitted only because BG_ENVIRONMENT=local and BG_TOKEN_ENCRYPTION_KEY "
    "is unset. Set BG_TOKEN_ENCRYPTION_KEY (or sm://barogroove-token-encryption-key) "
    "before pointing this at anything real."
)


class TokenVaultError(RuntimeError):
    """Something went wrong that the caller genuinely needs to know about."""


def _configuration_error(message: str) -> Exception:
    """Prefer the app's ConfigurationError; fall back if it is not importable."""
    try:
        from ..errors import ConfigurationError  # noqa: PLC0415
    except Exception:
        return TokenVaultError(message)
    return ConfigurationError(message)


@runtime_checkable
class TokenVault(Protocol):
    """The contract the Spotify and Last.fm pairing modules bind to.

    Both implementations below satisfy it. Neither raises on a missing token;
    :meth:`get` returns ``None`` and the caller re-runs the OAuth dance.
    """

    async def put(self, user_id: str, provider: str, payload: dict[str, Any]) -> None:
        """Store (encrypting) a provider payload, replacing any previous one."""
        ...

    async def get(self, user_id: str, provider: str) -> dict[str, Any] | None:
        """Return the decrypted payload, or ``None`` if absent/undecryptable."""
        ...

    async def delete(self, user_id: str, provider: str) -> None:
        """Remove a stored payload. Idempotent."""
        ...

    async def providers(self, user_id: str) -> list[str]:
        """Provider ids this user has paired. Empty list on failure."""
        ...


# ==========================================================================
# Crypto
# ==========================================================================


class _Cipher:
    """Fernet wrapper that knows whether it actually has a key.

    Constructed per vault instance. Key resolution happens once, lazily, on
    first use -- the module must import with an empty environment.
    """

    def __init__(self, settings: Any) -> None:
        self._settings = settings
        self._fernet: Any = None
        self._key_id: str = "none"
        self._resolved = False

    @property
    def key_id(self) -> str:
        """Short, non-reversible fingerprint of the key. Safe to log."""
        return self._key_id

    def _is_local(self) -> bool:
        return str(getattr(self._settings, "environment", "prod")) == "local"

    def _resolve_key(self) -> str:
        """Pull the key out of settings, resolving ``sm://`` references."""
        raw = str(getattr(self._settings, "token_encryption_key", "") or "")
        if not raw:
            return ""
        try:
            from ..config import resolve_secret  # noqa: PLC0415
        except Exception:
            # No resolver available: treat the value as a literal key.
            return raw
        try:
            resolved = resolve_secret(raw, self._settings)
        except Exception:
            # resolve_secret is documented to return "" on failure, but a
            # Secret Manager client can still blow up in novel ways.
            logger.exception("token encryption key could not be resolved")
            return ""
        return str(resolved or "")

    def _ensure(self) -> None:
        if self._resolved:
            return
        self._resolved = True
        key = self._resolve_key()
        if not key:
            if self._is_local():
                self._fernet = None
                self._key_id = "none"
                return
            raise _configuration_error(
                "BG_TOKEN_ENCRYPTION_KEY is required outside local mode: "
                "refusing to store provider credentials without encryption"
            )
        try:
            from cryptography.fernet import Fernet  # noqa: PLC0415
        except Exception as exc:  # pragma: no cover - dependency missing
            raise _configuration_error(
                "cryptography is not installed; the token vault cannot encrypt"
            ) from exc
        try:
            self._fernet = Fernet(key.encode("utf-8") if isinstance(key, str) else key)
        except Exception as exc:
            # Wrong length or not urlsafe-b64. Do NOT fall back to plaintext.
            raise _configuration_error(
                "BG_TOKEN_ENCRYPTION_KEY is not a valid Fernet key "
                "(expected 32 url-safe base64-encoded bytes)"
            ) from exc
        # Fingerprint the key so envelopes record which key sealed them, which
        # makes rotation debuggable. A SHA-256 prefix reveals nothing useful.
        self._key_id = hashlib.sha256(str(key).encode("utf-8")).hexdigest()[:8]

    @property
    def available(self) -> bool:
        """True when real encryption is in play."""
        self._ensure()
        return self._fernet is not None

    def encrypt(self, payload: dict[str, Any]) -> str:
        """Serialise and seal. Raises if no key -- callers check :attr:`available`."""
        self._ensure()
        if self._fernet is None:
            raise TokenVaultError("no encryption key available")
        blob = _dump_payload(payload)
        return self._fernet.encrypt(blob).decode("ascii")

    def decrypt(self, ciphertext: str) -> dict[str, Any] | None:
        """Open a sealed payload. ``None`` on any failure -- wrong key, tampering,
        corruption. Deliberately does not distinguish between them in the log."""
        self._ensure()
        if self._fernet is None:
            logger.error("cannot decrypt: no encryption key configured")
            return None
        try:
            raw = self._fernet.decrypt(ciphertext.encode("ascii"))
        except Exception:
            # InvalidToken covers wrong key AND tampering. Same response.
            logger.error("token decryption failed (wrong key or tampered envelope)")
            return None
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            logger.error("decrypted token payload is not valid JSON")
            return None
        return data if isinstance(data, dict) else None


def _dump_payload(payload: dict[str, Any]) -> bytes:
    """JSON-encode a payload, with a size ceiling. Never logs the content."""
    try:
        blob = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TokenVaultError("token payload is not JSON-serialisable") from exc
    if len(blob) > MAX_PAYLOAD_BYTES:
        raise TokenVaultError(
            f"token payload is {len(blob)} bytes, over the {MAX_PAYLOAD_BYTES} limit"
        )
    return blob


def generate_key() -> str:
    """Mint a fresh Fernet key. Used by ``deploy.sh`` and by tests.

    Print it once, put it in Secret Manager, forget it.
    """
    from cryptography.fernet import Fernet  # noqa: PLC0415

    return Fernet.generate_key().decode("ascii")


def _clean(value: str, *, what: str) -> str:
    """Validate a uid or provider id before it becomes a document path."""
    cleaned = (value or "").strip()
    if not cleaned or "/" in cleaned or len(cleaned) > 128:
        raise TokenVaultError(f"invalid {what}")
    return cleaned


# ==========================================================================
# Implementations
# ==========================================================================


class MemoryTokenVault:
    """In-process vault. Used by tests, by ``local`` without Firestore, and as
    the container's fallback when ``settings.has_firestore`` is false.

    Still encrypts when a key is present -- an in-memory store is not an excuse
    for a different security posture, and it means the round-trip that tests
    exercise is the same code path production uses.
    """

    def __init__(self, settings: Any) -> None:
        self._settings = settings
        self._cipher = _Cipher(settings)
        self._store: dict[tuple[str, str], dict[str, Any]] = {}

    async def put(self, user_id: str, provider: str, payload: dict[str, Any]) -> None:
        uid = _clean(user_id, what="user_id")
        prov = _clean(provider, what="provider")
        envelope = _seal(self._cipher, self._settings, uid, prov, payload)
        self._store[(uid, prov)] = envelope

    async def get(self, user_id: str, provider: str) -> dict[str, Any] | None:
        uid = _clean(user_id, what="user_id")
        prov = _clean(provider, what="provider")
        envelope = self._store.get((uid, prov))
        if envelope is None:
            return None
        return _open(self._cipher, self._settings, uid, prov, envelope)

    async def delete(self, user_id: str, provider: str) -> None:
        self._store.pop(
            (_clean(user_id, what="user_id"), _clean(provider, what="provider")), None
        )

    async def providers(self, user_id: str) -> list[str]:
        uid = _clean(user_id, what="user_id")
        return sorted(p for (u, p) in self._store if u == uid)

    def clear(self) -> None:
        """Drop everything. Tests only."""
        self._store.clear()


class FirestoreTokenVault:
    """Firestore-backed vault at ``users/{uid}/tokens/{provider}``.

    Degrades on infrastructure failure: :meth:`get` returns ``None``,
    :meth:`put` logs and gives up. It does **not** degrade on a *crypto*
    failure -- a missing key outside local mode raises, because silently not
    storing a token is better than silently storing it in the clear, and both
    are better than pretending.
    """

    def __init__(self, settings: Any, repo: Any | None = None) -> None:
        self._settings = settings
        self._cipher = _Cipher(settings)
        if repo is None:
            from .firestore import TokenRepository  # noqa: PLC0415 - avoids cycle

            repo = TokenRepository(settings)
        self._repo = repo

    async def put(self, user_id: str, provider: str, payload: dict[str, Any]) -> None:
        uid = _clean(user_id, what="user_id")
        prov = _clean(provider, what="provider")
        envelope = _seal(self._cipher, self._settings, uid, prov, payload)
        ok = await self._repo.put(uid, prov, envelope)
        if not ok:
            # The repository already logged the cause. Surfacing it lets the
            # OAuth callback tell the user "pairing failed, try again" rather
            # than claiming success and failing on the next forge.
            raise TokenVaultError(f"could not persist {prov} credentials")

    async def get(self, user_id: str, provider: str) -> dict[str, Any] | None:
        uid = _clean(user_id, what="user_id")
        prov = _clean(provider, what="provider")
        envelope = await self._repo.get(uid, prov)
        if not envelope:
            return None
        return _open(self._cipher, self._settings, uid, prov, envelope)

    async def delete(self, user_id: str, provider: str) -> None:
        await self._repo.delete(
            _clean(user_id, what="user_id"), _clean(provider, what="provider")
        )

    async def providers(self, user_id: str) -> list[str]:
        return await self._repo.list_providers(_clean(user_id, what="user_id"))


# ==========================================================================
# Envelope seal / open -- shared by both implementations
# ==========================================================================


def _seal(
    cipher: _Cipher,
    settings: Any,
    uid: str,
    provider: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Build a storage envelope. Never logs ``payload``."""
    from datetime import datetime, timezone  # noqa: PLC0415 - cheap, keeps top clean

    now = datetime.now(timezone.utc)
    base: dict[str, Any] = {
        "user_id": uid,
        "provider": provider,
        "created_at": now,
        "updated_at": now,
        "schema": ENVELOPE_SCHEMA,
    }

    if cipher.available:
        base["encryption"] = ENC_FERNET
        base["key_id"] = cipher.key_id
        base["ciphertext"] = cipher.encrypt(payload)
        logger.info("stored %s credentials for uid=%s (fernet/%s)", provider, uid, cipher.key_id)
        return base

    # No key. `cipher.available` already raised outside local mode, so reaching
    # here means environment == "local".
    logger.warning(_LOUD_DEV_WARNING, uid, provider, ENC_INSECURE)
    _dump_payload(payload)  # enforce the same size ceiling as the sealed path
    base["encryption"] = ENC_INSECURE
    base["key_id"] = "none"
    base["insecure_payload"] = dict(payload)
    return base


def _open(
    cipher: _Cipher,
    settings: Any,
    uid: str,
    provider: str,
    envelope: dict[str, Any],
) -> dict[str, Any] | None:
    """Read a storage envelope back. ``None`` on anything suspicious."""
    encryption = str(envelope.get("encryption") or "")

    if encryption == ENC_FERNET:
        ciphertext = envelope.get("ciphertext")
        if not isinstance(ciphertext, str) or not ciphertext:
            logger.error("envelope for uid=%s provider=%s has no ciphertext", uid, provider)
            return None
        return cipher.decrypt(ciphertext)

    if encryption == ENC_INSECURE:
        if str(getattr(settings, "environment", "prod")) != "local":
            # An insecure envelope that has travelled into a real environment.
            # Refuse it and make the operator delete it deliberately.
            logger.error(
                "REFUSING an %s envelope for uid=%s provider=%s outside local mode. "
                "Delete the document and re-pair the provider.",
                ENC_INSECURE,
                uid,
                provider,
            )
            return None
        logger.warning(_LOUD_DEV_WARNING, uid, provider, ENC_INSECURE)
        payload = envelope.get("insecure_payload")
        return dict(payload) if isinstance(payload, dict) else None

    logger.error(
        "unknown encryption marker %r on uid=%s provider=%s; refusing to read",
        encryption,
        uid,
        provider,
    )
    return None


def build_token_vault(settings: Any) -> TokenVault:
    """Pick an implementation. Firestore when configured, memory otherwise.

    Mirrors how the container chooses the almanac store, so a developer with no
    GCP project gets a working pairing flow that forgets everything on restart.
    """
    if getattr(settings, "has_firestore", False):
        return FirestoreTokenVault(settings)
    logger.info("no Firestore configured; provider tokens live in memory only")
    return MemoryTokenVault(settings)


__all__ = [
    "ENC_FERNET",
    "ENC_INSECURE",
    "ENVELOPE_SCHEMA",
    "MAX_PAYLOAD_BYTES",
    "FirestoreTokenVault",
    "MemoryTokenVault",
    "TokenVault",
    "TokenVaultError",
    "build_token_vault",
    "generate_key",
]

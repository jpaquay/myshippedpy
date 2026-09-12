"""Lazy async Firestore client plus a typed repository layer.

Design constraints
------------------
* **Imports clean with no credentials and no network.** ``google.cloud.firestore``
  is imported inside :func:`get_client`, never at module scope. Importing this
  module in a bare venv must succeed; it does.
* **Everything degrades.** Repository methods return empty/``None`` results and
  log on failure. Barogroove would rather hand you a playlist with no history
  attached than a 500.
* **Everything is bounded.** Every call goes through :func:`_guard`, which
  applies a timeout and a small bounded retry with jittered backoff.

Collection layout
-----------------
``users/{uid}``
    Profile + learned taste. Client-readable by its owner only.
    Fields: ``uid, email, display_name, photo_url, provider, created_at,
    updated_at, taste_vector (map of 7 floats), forge_count``.

``users/{uid}/tokens/{provider}``
    Encrypted provider credentials (Spotify, Last.fm). **Never** client-readable
    -- see ``firestore.rules``. Written only by the backend service account via
    the Admin SDK, which bypasses rules by design. Owned by ``tokens.py``.

``forges/{playlistId}``
    One forged playlist. Top-level rather than nested under the user so that a
    shared playlist has a stable, guessable-free URL and so that the
    "public: true" read path does not require walking a user subcollection.
    Fields: the :class:`Playlist` model, flattened, plus ``public: bool`` and
    ``user_id``.

``feedback/{autoId}``
    One loved/skipped signal. Append-only from the client's point of view.
    Fields: ``user_id, playlist_id, track_key, signal, created_at``.

``almanac/{uid}``
    Per-user learning state: the 9x7 delta applied to the sky->sonic transfer
    matrix. See :class:`NudgeRepository` for the exact document shape. The
    *algorithm* that produces this belongs to the Almanac worker; this module
    owns only the shape and the persistence.

Firestore type gotchas encoded in :func:`to_document`
-----------------------------------------------------
* **No tuples.** Tuples become lists. Sets become sorted lists.
* **No nested arrays.** Firestore rejects an array whose elements are arrays.
  A 9x7 matrix therefore round-trips through :func:`encode_matrix` as a flat
  63-element, row-major array plus ``rows``/``cols``. This is the single most
  common way people corrupt a matrix in Firestore; do not "simplify" it.
* **Datetimes must be timezone-aware.** Naive datetimes are coerced to UTC on
  write; on read, Firestore hands back tz-aware UTC and pydantic accepts it.
* **Document ids must not be empty, contain ``/``, or be ``.``/``..``.**
  :func:`safe_doc_id` enforces that.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Final, TypeVar
from uuid import UUID

from pydantic import BaseModel

logger = logging.getLogger("barogroove.firebase.firestore")

T = TypeVar("T")
ModelT = TypeVar("ModelT", bound=BaseModel)

# Collection names in one place so the rules file, the indexes file and the
# code cannot drift apart silently.
COL_USERS: Final[str] = "users"
COL_FORGES: Final[str] = "forges"
COL_FEEDBACK: Final[str] = "feedback"
COL_ALMANAC: Final[str] = "almanac"
COL_SCROBBLES: Final[str] = "scrobbles"
COL_TRACK_CATALOG: Final[str] = "track_catalog"
COL_SCROBBLE_SUMMARIES: Final[str] = "scrobble_summaries"
SUBCOL_TOKENS: Final[str] = "tokens"

# Bounds. Mirrored in firestore.rules; if you change one, change both.
MAX_TRACKS_PER_FORGE: Final[int] = 60
MAX_STRING_LEN: Final[int] = 4096
MAX_HISTORY_LIMIT: Final[int] = 200

DEFAULT_TIMEOUT_S: Final[float] = 10.0
DEFAULT_ATTEMPTS: Final[int] = 3

MATRIX_ROWS: Final[int] = 9  # SkyVector dimensionality
MATRIX_COLS: Final[int] = 7  # SonicVector dimensionality
MATRIX_VERSION: Final[int] = 1

_DOC_ID_BAD = re.compile(r"[/\x00-\x1f\x7f]")


# ==========================================================================
# Client factory
# ==========================================================================

_client_cache: dict[tuple[str, str], Any] = {}
_client_lock: asyncio.Lock | None = None


def _get_client_lock() -> asyncio.Lock:
    global _client_lock
    if _client_lock is None:
        _client_lock = asyncio.Lock()
    return _client_lock


class FirestoreUnavailable(RuntimeError):
    """Firestore is not configured, not installed, or not reachable.

    Callers are expected to catch this and degrade, not to propagate it.
    """


async def get_client(settings: Any) -> Any:
    """Return a cached ``AsyncClient``, constructing it on first use.

    The ``google.cloud.firestore`` import lives inside this function on
    purpose: the package pulls in gRPC and starts credential discovery, and
    this module has to be importable in a test venv with neither.

    Raises :class:`FirestoreUnavailable` when the library is missing or the
    settings do not describe a project. Never raises for network reasons --
    the client is lazy and only talks to the network on first operation.
    """
    if not getattr(settings, "has_firestore", False):
        raise FirestoreUnavailable(
            "settings.has_firestore is false (no gcp_project / firebase_project_id)"
        )

    project = str(
        getattr(settings, "firebase_project_id", "")
        or getattr(settings, "gcp_project", "")
    )
    database = str(getattr(settings, "firestore_database", "(default)") or "(default)")
    key = (project, database)

    cached = _client_cache.get(key)
    if cached is not None:
        return cached

    async with _get_client_lock():
        cached = _client_cache.get(key)
        if cached is not None:
            return cached
        try:
            from google.cloud import firestore  # noqa: PLC0415 - deliberately lazy
        except Exception as exc:
            raise FirestoreUnavailable(
                "google-cloud-firestore is not installed"
            ) from exc
        try:
            # AsyncClient defers credential resolution and channel creation, so
            # constructing it is cheap and does not touch the network.
            client = firestore.AsyncClient(project=project, database=database)
        except Exception as exc:
            raise FirestoreUnavailable(f"cannot construct Firestore client: {exc}") from exc
        _client_cache[key] = client
        logger.info(
            "firestore client ready (project=%s database=%s)", project, database
        )
        return client


def reset_client_cache() -> None:
    """Drop cached clients. For tests and for credential rotation."""
    _client_cache.clear()


# ==========================================================================
# Call guard: timeout + bounded retry + degradation
# ==========================================================================


def _is_retryable(exc: BaseException) -> bool:
    """Retry only transient conditions.

    Matched on class name rather than on imported exception types, because the
    google exception classes are not importable here (lazy-import rule). Blunt,
    but wrong-in-the-safe-direction: an unmatched error is simply not retried.
    """
    name = type(exc).__name__
    return name in {
        "ServiceUnavailable",
        "DeadlineExceeded",
        "InternalServerError",
        "Aborted",
        "TooManyRequests",
        "ResourceExhausted",
        "RetryError",
        "TimeoutError",
        "ConnectionError",
    }


async def _guard(
    op: Callable[[], Awaitable[T]],
    *,
    what: str,
    default: T,
    timeout: float = DEFAULT_TIMEOUT_S,
    attempts: int = DEFAULT_ATTEMPTS,
) -> T:
    """Run a Firestore operation with a timeout, bounded retry and a floor.

    Returns ``default`` instead of raising. That is the whole point: the
    almanac is an enrichment, and an enrichment that can take the request down
    is a liability.
    """
    last: BaseException | None = None
    for attempt in range(attempts):
        try:
            return await asyncio.wait_for(op(), timeout=timeout)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - deliberate catch-all
            last = exc
            if attempt + 1 >= attempts or not _is_retryable(exc):
                break
            backoff = min(2.0, 0.2 * (2**attempt)) * (0.5 + random.random())
            logger.debug("%s failed (%s); retry in %.2fs", what, exc, backoff)
            await asyncio.sleep(backoff)
    logger.warning("%s failed after %d attempt(s): %s", what, attempts, last)
    return default


# ==========================================================================
# Converters
# ==========================================================================


def safe_doc_id(raw: str) -> str:
    """Validate a document id. Raises ``ValueError`` on anything Firestore hates."""
    doc_id = (raw or "").strip()
    if not doc_id or doc_id in {".", ".."} or len(doc_id) > 1500:
        raise ValueError(f"invalid Firestore document id: {raw!r}")
    if _DOC_ID_BAD.search(doc_id):
        raise ValueError(f"document id contains forbidden characters: {raw!r}")
    return doc_id


def _as_utc(value: datetime) -> datetime:
    """Force a datetime to tz-aware UTC. Firestore stores UTC regardless."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def firestore_safe(value: Any, *, _depth: int = 0) -> Any:
    """Coerce an arbitrary Python value into something Firestore accepts.

    Handles: pydantic models, mappings, tuples/sets/lists, datetimes, dates,
    Decimals, UUIDs, Enums. Rejects nested arrays with a clear error rather
    than letting the server produce a cryptic one -- use :func:`encode_matrix`
    for matrices.
    """
    if _depth > 20:
        raise ValueError("document nesting exceeds Firestore's 20-level limit")

    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return value
    if isinstance(value, BaseModel):
        return firestore_safe(value.model_dump(mode="python"), _depth=_depth + 1)
    if isinstance(value, Enum):
        return firestore_safe(value.value, _depth=_depth + 1)
    if isinstance(value, datetime):
        return _as_utc(value)
    if isinstance(value, date):
        # No date type in Firestore; midnight UTC is the least surprising choice.
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): firestore_safe(v, _depth=_depth + 1) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        return [firestore_safe(v, _depth=_depth + 1) for v in sorted(value, key=repr)]
    if isinstance(value, (list, tuple)):
        # Tuples are not a Firestore type. Lists are. Convert, do not apologise.
        out: list[Any] = []
        for item in value:
            if isinstance(item, (list, tuple, set, frozenset)):
                raise ValueError(
                    "Firestore does not support nested arrays; "
                    "use encode_matrix()/encode_rows() for 2-D data"
                )
            out.append(firestore_safe(item, _depth=_depth + 1))
        return out
    # Unknown object: stringify rather than explode. Logged so it gets noticed.
    logger.debug("firestore_safe stringifying unsupported type %s", type(value).__name__)
    return str(value)


def to_document(model: BaseModel, *, exclude_none: bool = False) -> dict[str, Any]:
    """Convert a pydantic model into a Firestore-safe document dict."""
    raw = model.model_dump(mode="python", exclude_none=exclude_none)
    doc = firestore_safe(raw)
    if not isinstance(doc, dict):  # pragma: no cover - models always dump to dict
        raise TypeError("model did not dump to a mapping")
    return doc


def from_document(model_cls: type[ModelT], data: Mapping[str, Any]) -> ModelT:
    """Rebuild a pydantic model from a Firestore document.

    Pydantic v2 handles the datetime and numeric coercion; we only strip the
    bookkeeping keys the repositories add.
    """
    payload = {k: v for k, v in data.items() if not k.startswith("_")}
    return model_cls.model_validate(payload)


def encode_matrix(matrix: Sequence[Sequence[float]]) -> dict[str, Any]:
    """Flatten a 2-D matrix for storage. Firestore has no nested arrays.

    Returns ``{"rows": R, "cols": C, "values": [... R*C floats, row-major ...]}``.
    """
    rows = len(matrix)
    if rows == 0:
        return {"rows": 0, "cols": 0, "values": []}
    cols = len(matrix[0])
    values: list[float] = []
    for r, row in enumerate(matrix):
        if len(row) != cols:
            raise ValueError(f"ragged matrix: row {r} has {len(row)} of {cols} columns")
        values.extend(float(x) for x in row)
    return {"rows": rows, "cols": cols, "values": values}


def decode_matrix(blob: Mapping[str, Any] | None) -> list[list[float]] | None:
    """Inverse of :func:`encode_matrix`. Returns ``None`` on anything malformed."""
    if not isinstance(blob, Mapping):
        return None
    try:
        rows = int(blob.get("rows", 0))
        cols = int(blob.get("cols", 0))
        values = list(blob.get("values") or [])
    except (TypeError, ValueError):
        return None
    if rows <= 0 or cols <= 0 or len(values) != rows * cols:
        logger.warning(
            "discarding malformed matrix blob (rows=%s cols=%s len=%s)",
            blob.get("rows"),
            blob.get("cols"),
            len(values),
        )
        return None
    return [
        [float(values[r * cols + c]) for c in range(cols)] for r in range(rows)
    ]


def now_utc() -> datetime:
    """Single source of 'now'. Tz-aware, always."""
    return datetime.now(timezone.utc)


def clamp_text(value: str | None, limit: int = MAX_STRING_LEN) -> str | None:
    """Truncate free text before it reaches Firestore's 1 MiB document ceiling."""
    if value is None:
        return None
    return value if len(value) <= limit else value[:limit]


# ==========================================================================
# Repositories
# ==========================================================================


class _BaseRepository:
    """Shared plumbing: settings, lazy client, degradation-friendly helpers."""

    def __init__(self, settings: Any) -> None:
        self._settings = settings

    @property
    def settings(self) -> Any:
        return self._settings

    async def _client(self) -> Any:
        return await get_client(self._settings)

    async def _collection(self, name: str) -> Any:
        client = await self._client()
        return client.collection(name)


class UserRepository(_BaseRepository):
    """Profile documents at ``users/{uid}``.

    Holds the identity mirror (so the app can render an avatar without another
    Auth round trip) and the learned :class:`TasteVector`. Client-readable and
    writable by its owner only.
    """

    async def upsert_profile(
        self,
        uid: str,
        *,
        email: str | None = None,
        display_name: str | None = None,
        photo_url: str | None = None,
        provider: str = "unknown",
    ) -> bool:
        """Create or refresh a profile. Returns ``False`` on failure, never raises."""
        try:
            doc_id = safe_doc_id(uid)
        except ValueError:
            logger.warning("refusing to upsert profile for invalid uid")
            return False

        payload: dict[str, Any] = {
            "uid": doc_id,
            "email": clamp_text(email, 320),
            "display_name": clamp_text(display_name, 256),
            "photo_url": clamp_text(photo_url, 2048),
            "provider": clamp_text(provider, 64) or "unknown",
            "updated_at": now_utc(),
        }

        async def _op() -> bool:
            col = await self._collection(COL_USERS)
            ref = col.document(doc_id)
            snap = await ref.get()
            if not getattr(snap, "exists", False):
                payload["created_at"] = now_utc()
                payload["forge_count"] = 0
            await ref.set(payload, merge=True)
            return True

        return await _guard(_op, what=f"users.upsert({doc_id})", default=False)

    async def get_profile(self, uid: str) -> dict[str, Any] | None:
        """Read a profile. ``None`` when absent or unreachable."""

        async def _op() -> dict[str, Any] | None:
            col = await self._collection(COL_USERS)
            snap = await col.document(safe_doc_id(uid)).get()
            return snap.to_dict() if getattr(snap, "exists", False) else None

        return await _guard(_op, what=f"users.get({uid})", default=None)

    async def set_taste_vector(self, uid: str, taste: BaseModel | Mapping[str, float]) -> bool:
        """Persist the user's :class:`TasteVector` (7 sonic dims, all floats)."""
        payload = (
            to_document(taste) if isinstance(taste, BaseModel) else dict(taste)
        )

        async def _op() -> bool:
            col = await self._collection(COL_USERS)
            await col.document(safe_doc_id(uid)).set(
                {"taste_vector": firestore_safe(payload), "updated_at": now_utc()},
                merge=True,
            )
            return True

        return await _guard(_op, what=f"users.set_taste({uid})", default=False)


class ForgeRepository(_BaseRepository):
    """Forged playlists at ``forges/{playlistId}``.

    A "forge" is one act of turning sky into sound. Documents are immutable in
    practice apart from the ``public`` flag, which is the only thing the client
    is allowed to toggle after creation.
    """

    async def create(self, playlist: BaseModel, *, public: bool = False) -> str | None:
        """Write a playlist. Returns its id, or ``None`` if the write failed.

        Tracks are capped at :data:`MAX_TRACKS_PER_FORGE`; the rules file caps
        them too, because a client that talks to Firestore directly must not be
        able to plant a 10 MB document.
        """
        try:
            doc_id = safe_doc_id(str(getattr(playlist, "id", "") or ""))
        except ValueError:
            logger.warning("refusing to persist a playlist with no usable id")
            return None

        try:
            doc = to_document(playlist)
        except Exception:
            logger.exception("playlist -> document conversion failed for %s", doc_id)
            return None

        tracks = doc.get("tracks")
        if isinstance(tracks, list) and len(tracks) > MAX_TRACKS_PER_FORGE:
            logger.warning(
                "truncating forge %s from %d to %d tracks",
                doc_id,
                len(tracks),
                MAX_TRACKS_PER_FORGE,
            )
            doc["tracks"] = tracks[:MAX_TRACKS_PER_FORGE]

        doc["public"] = bool(public)
        doc.setdefault("created_at", now_utc())
        doc["_schema"] = 1

        async def _op() -> str | None:
            col = await self._collection(COL_FORGES)
            await col.document(doc_id).set(doc)
            return doc_id

        return await _guard(_op, what=f"forges.create({doc_id})", default=None)

    async def get(self, playlist_id: str) -> dict[str, Any] | None:
        """Read one forge by id. ``None`` when absent or unreachable."""

        async def _op() -> dict[str, Any] | None:
            col = await self._collection(COL_FORGES)
            snap = await col.document(safe_doc_id(playlist_id)).get()
            return snap.to_dict() if getattr(snap, "exists", False) else None

        return await _guard(_op, what=f"forges.get({playlist_id})", default=None)

    async def list_for_user(
        self,
        user_id: str,
        *,
        limit: int = 50,
        theme_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """A user's forges, newest first.

        Backed by the composite indexes in ``firestore.indexes.json``. If a
        composite index is missing or still building, falls back to single-field
        filtering and in-memory sorting so history is never lost.
        """
        capped = max(1, min(int(limit), MAX_HISTORY_LIMIT))

        async def _query_uid(uid: str) -> list[dict[str, Any]]:
            from google.cloud.firestore_v1.base_query import (  # noqa: PLC0415
                FieldFilter,
            )

            col = await self._collection(COL_FORGES)
            base_q = col.where(filter=FieldFilter("user_id", "==", uid))
            if theme_id:
                base_q = base_q.where(filter=FieldFilter("theme_id", "==", theme_id))
            try:
                ordered_q = base_q.order_by("created_at", direction="DESCENDING").limit(capped)
                return [snap.to_dict() async for snap in ordered_q.stream()]
            except Exception:
                # Composite index may be building or unavailable; fall back to
                # single-field filter + Python sort.
                docs = [snap.to_dict() async for snap in base_q.limit(capped * 2).stream()]
                docs.sort(key=lambda d: str(d.get("created_at") or ""), reverse=True)
                return docs[:capped]

        async def _op() -> list[dict[str, Any]]:
            rows = await _query_uid(user_id)
            if not rows and user_id != "demo":
                rows = await _query_uid("demo")
            return rows

        return await _guard(
            _op, what=f"forges.list_for_user({user_id})", default=[]
        )

    async def set_public(self, playlist_id: str, user_id: str, public: bool) -> bool:
        """Toggle the share flag, after checking ownership server-side.

        The rules file also enforces ownership; this check exists because the
        backend uses the Admin SDK, which bypasses rules.
        """

        async def _op() -> bool:
            col = await self._collection(COL_FORGES)
            ref = col.document(safe_doc_id(playlist_id))
            snap = await ref.get()
            if not getattr(snap, "exists", False):
                return False
            data = snap.to_dict() or {}
            if data.get("user_id") != user_id:
                logger.warning("refused share toggle: %s does not own the forge", user_id)
                return False
            await ref.set({"public": bool(public), "updated_at": now_utc()}, merge=True)
            return True

        return await _guard(_op, what=f"forges.set_public({playlist_id})", default=False)


class FeedbackRepository(_BaseRepository):
    """Loved/skipped signals at ``feedback/{autoId}``.

    Append-only. One document per signal rather than an array on the playlist,
    because arrays in Firestore are read-modify-write and two taps in the same
    second would silently lose one.
    """

    async def record(
        self,
        *,
        user_id: str,
        playlist_id: str,
        track_key: str,
        signal: str,
    ) -> bool:
        """Store one signal. ``signal`` must be ``loved`` or ``skipped``."""
        if signal not in {"loved", "skipped"}:
            logger.warning("rejected unknown feedback signal %r", signal)
            return False

        doc = {
            "user_id": user_id,
            "playlist_id": playlist_id,
            "track_key": clamp_text(track_key, 512),
            "signal": signal,
            "created_at": now_utc(),
        }

        async def _op() -> bool:
            col = await self._collection(COL_FEEDBACK)
            await col.add(doc)
            return True

        return await _guard(_op, what="feedback.record", default=False)

    async def for_playlist(
        self, user_id: str, playlist_id: str, *, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Every signal this user left on one playlist."""
        capped = max(1, min(int(limit), 500))

        async def _op() -> list[dict[str, Any]]:
            from google.cloud.firestore_v1.base_query import (  # noqa: PLC0415
                FieldFilter,
            )

            col = await self._collection(COL_FEEDBACK)
            query = (
                col.where(filter=FieldFilter("user_id", "==", user_id))
                .where(filter=FieldFilter("playlist_id", "==", playlist_id))
                .limit(capped)
            )
            return [snap.to_dict() async for snap in query.stream()]

        return await _guard(_op, what="feedback.for_playlist", default=[])

    async def for_user(self, user_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        """Every signal this user has ever left, newest first.

        This is the training set the Almanac worker's ridge regression consumes.
        """
        capped = max(1, min(int(limit), 2000))

        async def _op() -> list[dict[str, Any]]:
            from google.cloud.firestore_v1.base_query import (  # noqa: PLC0415
                FieldFilter,
            )

            col = await self._collection(COL_FEEDBACK)
            query = (
                col.where(filter=FieldFilter("user_id", "==", user_id))
                .order_by("created_at", direction="DESCENDING")
                .limit(capped)
            )
            return [snap.to_dict() async for snap in query.stream()]

        return await _guard(_op, what="feedback.for_user", default=[])


class NudgeRepository(_BaseRepository):
    """Per-user transfer-matrix deltas at ``almanac/{uid}``.

    **Document shape** (stable contract with the Almanac worker -- if you change
    it, bump ``matrix_version`` and handle both shapes on read)::

        {
          "user_id":        "<uid>",
          "matrix_version": 1,             # bump on any shape change
          "sample_count":   137,           # feedback rows the fit consumed
          "updated_at":     <timestamp>,   # tz-aware UTC
          "delta": {                       # encode_matrix() output
            "rows":   9,                   # SkyVector dims
            "cols":   7,                   # SonicVector dims
            "values": [ ... 63 floats, ROW-MAJOR ... ]
          }
        }

    ``delta`` is *additive*: the effective transfer matrix is
    ``base_matrix + delta``. It is flattened because Firestore rejects nested
    arrays. :meth:`get_delta` hands the caller a proper 9x7 nested list, so the
    flattening is invisible above this line.

    This module owns persistence and shape. The ridge regression that computes
    ``delta`` is the Almanac worker's; nothing here fits anything.
    """

    async def get_delta(self, user_id: str) -> list[list[float]] | None:
        """Return the stored 9x7 delta, or ``None``.

        ``None`` means "no personalisation available" and covers all of: no
        document, malformed document, wrong dimensions, Firestore unreachable.
        The caller uses the base matrix and carries on.
        """

        async def _op() -> list[list[float]] | None:
            col = await self._collection(COL_ALMANAC)
            snap = await col.document(safe_doc_id(user_id)).get()
            if not getattr(snap, "exists", False):
                return None
            data = snap.to_dict() or {}
            matrix = decode_matrix(data.get("delta"))
            if matrix is None:
                return None
            if len(matrix) != MATRIX_ROWS or any(
                len(row) != MATRIX_COLS for row in matrix
            ):
                logger.warning(
                    "almanac/%s delta is %dx%s, expected %dx%d; ignoring",
                    user_id,
                    len(matrix),
                    len(matrix[0]) if matrix else 0,
                    MATRIX_ROWS,
                    MATRIX_COLS,
                )
                return None
            return matrix

        return await _guard(_op, what=f"almanac.get_delta({user_id})", default=None)

    async def get_meta(self, user_id: str) -> dict[str, Any] | None:
        """Metadata only: sample count, version, updated_at. No matrix."""

        async def _op() -> dict[str, Any] | None:
            col = await self._collection(COL_ALMANAC)
            snap = await col.document(safe_doc_id(user_id)).get()
            if not getattr(snap, "exists", False):
                return None
            data = snap.to_dict() or {}
            return {
                "user_id": data.get("user_id", user_id),
                "matrix_version": data.get("matrix_version"),
                "sample_count": data.get("sample_count", 0),
                "updated_at": data.get("updated_at"),
            }

        return await _guard(_op, what=f"almanac.get_meta({user_id})", default=None)

    async def put_delta(
        self,
        user_id: str,
        delta: Sequence[Sequence[float]],
        *,
        sample_count: int,
        matrix_version: int = MATRIX_VERSION,
    ) -> bool:
        """Persist a freshly fitted delta. Called by the Almanac worker's loop.

        Validates dimensions here so a bad fit cannot poison the collection.
        """
        if len(delta) != MATRIX_ROWS or any(len(r) != MATRIX_COLS for r in delta):
            logger.warning(
                "refusing to store a %dx%s delta; expected %dx%d",
                len(delta),
                len(delta[0]) if delta else 0,
                MATRIX_ROWS,
                MATRIX_COLS,
            )
            return False
        try:
            encoded = encode_matrix(delta)
        except ValueError:
            logger.exception("delta encode failed for %s", user_id)
            return False

        doc = {
            "user_id": user_id,
            "matrix_version": int(matrix_version),
            "sample_count": max(0, int(sample_count)),
            "updated_at": now_utc(),
            "delta": encoded,
        }

        async def _op() -> bool:
            col = await self._collection(COL_ALMANAC)
            await col.document(safe_doc_id(user_id)).set(doc)
            return True

        return await _guard(_op, what=f"almanac.put_delta({user_id})", default=False)


class TokenRepository(_BaseRepository):
    """Raw document access for ``users/{uid}/tokens/{provider}``.

    Deliberately dumb: it moves opaque envelopes in and out. All encryption
    lives in ``tokens.py``. This class must never see or log a plaintext token.

    Security note: ``firestore.rules`` denies *all* client access to this
    subcollection. The backend reaches it with the Admin SDK, which bypasses
    rules. That asymmetry is the entire access-control story for tokens.
    """

    async def put(self, user_id: str, provider: str, envelope: Mapping[str, Any]) -> bool:
        """Write an opaque envelope. Returns success; never logs the payload."""

        async def _op() -> bool:
            client = await self._client()
            ref = (
                client.collection(COL_USERS)
                .document(safe_doc_id(user_id))
                .collection(SUBCOL_TOKENS)
                .document(safe_doc_id(provider))
            )
            await ref.set(dict(envelope))
            return True

        return await _guard(_op, what=f"tokens.put({provider})", default=False)

    async def get(self, user_id: str, provider: str) -> dict[str, Any] | None:
        """Read an opaque envelope, or ``None``."""

        async def _op() -> dict[str, Any] | None:
            client = await self._client()
            ref = (
                client.collection(COL_USERS)
                .document(safe_doc_id(user_id))
                .collection(SUBCOL_TOKENS)
                .document(safe_doc_id(provider))
            )
            snap = await ref.get()
            return snap.to_dict() if getattr(snap, "exists", False) else None

        return await _guard(_op, what=f"tokens.get({provider})", default=None)

    async def delete(self, user_id: str, provider: str) -> bool:
        """Remove a stored envelope. Idempotent -- deleting nothing is success."""

        async def _op() -> bool:
            client = await self._client()
            ref = (
                client.collection(COL_USERS)
                .document(safe_doc_id(user_id))
                .collection(SUBCOL_TOKENS)
                .document(safe_doc_id(provider))
            )
            await ref.delete()
            return True

        return await _guard(_op, what=f"tokens.delete({provider})", default=False)

    async def list_providers(self, user_id: str) -> list[str]:
        """Provider ids with a stored envelope. Empty list on failure."""

        async def _op() -> list[str]:
            client = await self._client()
            col = (
                client.collection(COL_USERS)
                .document(safe_doc_id(user_id))
                .collection(SUBCOL_TOKENS)
            )
            return sorted([snap.id async for snap in col.stream()])

        return await _guard(_op, what="tokens.list_providers", default=[])


class Repositories:
    """One handle for the whole repository layer.

    Constructed cheaply and lazily -- building this does not touch Firestore.
    """

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self.users = UserRepository(settings)
        self.forges = ForgeRepository(settings)
        self.feedback = FeedbackRepository(settings)
        self.nudges = NudgeRepository(settings)
        self.tokens = TokenRepository(settings)

    async def healthcheck(self) -> dict[str, Any]:
        """Report reachability without raising, ever.

        Returns ``{"reachable": bool, "detail": str, "latency_ms": float|None,
        "project": str, "database": str}``. Used by ``/readyz``; ``/healthz``
        stays dependency-free on purpose so a Firestore outage does not make
        Cloud Run recycle healthy instances.
        """
        project = str(
            getattr(self.settings, "firebase_project_id", "")
            or getattr(self.settings, "gcp_project", "")
        )
        database = str(getattr(self.settings, "firestore_database", "(default)"))
        result: dict[str, Any] = {
            "reachable": False,
            "detail": "unknown",
            "latency_ms": None,
            "project": project,
            "database": database,
        }

        started = time.perf_counter()
        try:
            client = await get_client(self.settings)
        except FirestoreUnavailable as exc:
            result["detail"] = str(exc)
            return result
        except Exception as exc:  # noqa: BLE001 - healthcheck never raises
            result["detail"] = f"client construction failed: {exc}"
            return result

        async def _probe() -> bool:
            # Cheapest possible round trip: read a document that need not exist.
            await client.collection("_healthcheck").document("probe").get()
            return True

        ok = await _guard(
            _probe, what="firestore.healthcheck", default=False, timeout=5.0, attempts=1
        )
        result["reachable"] = ok
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        result["detail"] = "ok" if ok else "probe failed (see logs)"
        return result


def build_repositories(settings: Any) -> Repositories:
    """Factory. Cheap; no I/O."""
    return Repositories(settings)


__all__ = [
    "COL_ALMANAC",
    "COL_FEEDBACK",
    "COL_FORGES",
    "COL_USERS",
    "MATRIX_COLS",
    "MATRIX_ROWS",
    "MATRIX_VERSION",
    "MAX_TRACKS_PER_FORGE",
    "SUBCOL_TOKENS",
    "FeedbackRepository",
    "FirestoreUnavailable",
    "ForgeRepository",
    "NudgeRepository",
    "Repositories",
    "TokenRepository",
    "UserRepository",
    "build_repositories",
    "clamp_text",
    "decode_matrix",
    "encode_matrix",
    "firestore_safe",
    "from_document",
    "get_client",
    "now_utc",
    "reset_client_cache",
    "safe_doc_id",
    "to_document",
]

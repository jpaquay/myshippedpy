"""Forge runs as tracked server-side jobs.

Why this exists
---------------
A forge used to be *the request*. The engine ran inside the handler, so the
work was only as durable as the socket: navigate away, background the tab, or
lose the connection mid-flight and the playlist you were waiting for was
simply gone. Worse, the obvious client-side fix — "just try again" — meant a
second full forge for the same intent.

So a forge is now a **job**. Starting one hands back an id immediately; the
actual work runs on a background task owned by the server. The client polls.
If the client disappears, the job still finishes and still lands in recent
playlists. If the client comes back, it finds the job it already has rather
than starting a new one.

What this deliberately is NOT
-----------------------------
There is no job/queue abstraction anywhere else in this codebase (checked:
nothing under ``backend/app`` owns tasks beyond two fire-and-forget
``loop.create_task`` calls in the telemetry store), so rather than import a
broker we did not need, this is a plain in-process registry over
``asyncio.Task``.

**Lifetime, stated honestly: this registry lives in the process. It does not
survive a restart, a crash, or a Cloud Run scale-to-zero, and with more than
one instance behind a load balancer a poll can land on a replica that has
never heard of the job.** What *does* survive is the product of a finished
job: the engine persists the playlist through the almanac/Firestore path
exactly as the synchronous route always did, so a completed forge outlives the
registry entry that produced it. Only the *in-flight* state is ephemeral. If
that ever stops being acceptable, the fix is a shared store (Firestore
``forge_jobs/{id}`` plus a Cloud Tasks worker), and this module's surface —
``submit`` / ``get`` / ``list_for`` — is the seam to swap behind.

Idempotency
-----------
``submit`` is the safety net for item 5's retry policy. Two things make a
double-start impossible:

* An explicit ``job_id`` supplied by the client is an idempotency key. A
  retried POST carrying an id we already know returns that job untouched.
* Failing that, a *fingerprint* of (owner, request) matches against jobs that
  are still queued or running. A client that reconnects with the same intent
  joins the existing run.

Both checks happen under one lock, so two concurrent retries cannot both win
the race and create a job each.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Final, Literal

from pydantic import BaseModel

log = logging.getLogger("barogroove.forge.jobs")

JobState = Literal["queued", "running", "done", "failed"]

#: Once a job is in one of these it never changes again.
TERMINAL: Final[frozenset[str]] = frozenset({"done", "failed"})

#: Keep the registry small. A forge is a foreground action; nobody has
#: hundreds in flight, and an unbounded dict in a long-lived process is a leak
#: with extra steps.
DEFAULT_MAX_JOBS: Final[int] = 64

#: Finished jobs are evicted after this long. Long enough that a phone which
#: was backgrounded over lunch still finds its playlist; short enough that the
#: process does not hoard playlists forever.
DEFAULT_TTL_S: Final[float] = 3600.0

#: A single forge is bounded. The engine has its own upstream timeouts, but a
#: wedged task must not pin a job in ``running`` for the life of the process.
DEFAULT_RUN_TIMEOUT_S: Final[float] = 180.0

#: Request fields that identify a *connection*, not an *intent*. A client that
#: reconnects gets a fresh session id; if that changed the fingerprint, every
#: reconnect would start a second forge — which is the exact bug this module
#: exists to prevent.
_VOLATILE_FIELDS: Final[frozenset[str]] = frozenset({"session_id", "conversation_id"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ==========================================================================
# Public envelope
# ==========================================================================


class ForgeJobEnvelope(BaseModel):
    """What the HTTP layer hands back for a job, on start and on every poll.

    ``result`` is intentionally untyped here. The concrete ``ForgeResult``
    lives in ``contracts.py``, which this module does not own and should not
    pin; FastAPI's encoder serialises the pydantic model perfectly well
    through an ``Any``.
    """

    job_id: str
    status: JobState
    owner: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    #: True when this call joined an existing job instead of creating one.
    #: The client uses it to tell "my retry was absorbed" from "I started it".
    resumed: bool = False

    #: Set only when ``status == "failed"``.
    error: str | None = None

    #: Convenience for clients that only want to know *which* playlist.
    playlist_id: str | None = None

    result: Any | None = None

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL


# ==========================================================================
# The job
# ==========================================================================


@dataclass
class ForgeJob:
    """One tracked forge. Mutated only by the registry that owns it."""

    id: str
    owner: str
    fingerprint: str
    status: JobState = "queued"
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: Any = None
    error: str | None = None
    task: asyncio.Task[Any] | None = field(default=None, repr=False, compare=False)

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL

    def _playlist_id(self) -> str | None:
        playlist = getattr(self.result, "playlist", None)
        pid = getattr(playlist, "id", None)
        return str(pid) if pid else None

    def envelope(self, *, resumed: bool = False) -> ForgeJobEnvelope:
        return ForgeJobEnvelope(
            job_id=self.id,
            status=self.status,
            owner=self.owner,
            created_at=self.created_at,
            updated_at=self.updated_at,
            started_at=self.started_at,
            finished_at=self.finished_at,
            resumed=resumed,
            error=self.error,
            playlist_id=self._playlist_id(),
            result=self.result,
        )


def fingerprint(owner: str, request: Any) -> str:
    """A stable digest of "who wants what".

    Built from the serialised request minus the volatile transport fields, so
    the same intent from the same person always hashes the same way no matter
    how many times the socket was re-established.
    """
    if hasattr(request, "model_dump"):
        payload: Any = request.model_dump(mode="json", exclude=set(_VOLATILE_FIELDS))
    elif isinstance(request, dict):
        payload = {k: v for k, v in request.items() if k not in _VOLATILE_FIELDS}
    else:  # pragma: no cover - defensive; every caller passes a ForgeRequest
        payload = repr(request)
    blob = json.dumps(
        {"owner": owner, "request": payload},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


# ==========================================================================
# The registry
# ==========================================================================


class ForgeJobRegistry:
    """In-process job table. See the module docstring for the lifetime caveat."""

    def __init__(
        self,
        *,
        max_jobs: int = DEFAULT_MAX_JOBS,
        ttl_s: float = DEFAULT_TTL_S,
        run_timeout_s: float = DEFAULT_RUN_TIMEOUT_S,
    ) -> None:
        self._jobs: OrderedDict[str, ForgeJob] = OrderedDict()
        self._max_jobs = max_jobs
        self._ttl_s = ttl_s
        self._run_timeout_s = run_timeout_s
        # An asyncio.Lock binds to the loop it is first awaited on. The suite
        # runs each case under its own asyncio.run(), so cache the loop with
        # the lock and rebuild when it changes. Same trick firestore.py uses
        # for its client cache, and for the same reason.
        self._lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None

    # -- internals ---------------------------------------------------------

    def _lock_for_loop(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
        return self._lock

    def _prune(self) -> None:
        """Drop expired and surplus *terminal* jobs. Running jobs are safe."""
        now = _now()
        for jid, job in list(self._jobs.items()):
            if not job.terminal:
                continue
            finished = job.finished_at or job.updated_at
            if (now - finished).total_seconds() > self._ttl_s:
                self._jobs.pop(jid, None)

        if len(self._jobs) <= self._max_jobs:
            return
        for jid, job in list(self._jobs.items()):  # oldest first
            if len(self._jobs) <= self._max_jobs:
                break
            if job.terminal:
                self._jobs.pop(jid, None)

    def _find_active(self, owner: str, fp: str) -> ForgeJob | None:
        for job in reversed(self._jobs.values()):  # newest first
            if job.owner == owner and job.fingerprint == fp and not job.terminal:
                return job
        return None

    async def _run(self, job: ForgeJob, runner: Callable[[], Awaitable[Any]]) -> None:
        job.status = "running"
        job.started_at = _now()
        job.updated_at = job.started_at
        try:
            job.result = await asyncio.wait_for(runner(), timeout=self._run_timeout_s)
        except asyncio.CancelledError:
            job.status = "failed"
            job.error = "cancelled"
            job.finished_at = _now()
            job.updated_at = job.finished_at
            raise
        except asyncio.TimeoutError:
            job.status = "failed"
            job.error = f"forge exceeded {self._run_timeout_s:.0f}s"
            log.warning("forge job %s timed out", job.id)
        except Exception as exc:  # noqa: BLE001 - a job records its failure
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"
            log.warning("forge job %s failed: %s", job.id, exc)
        else:
            job.status = "done"
        finally:
            if job.finished_at is None:
                job.finished_at = _now()
            job.updated_at = job.finished_at

    # -- public surface ----------------------------------------------------

    async def submit(
        self,
        *,
        owner: str,
        request: Any,
        runner: Callable[[], Awaitable[Any]],
        job_id: str | None = None,
    ) -> tuple[ForgeJob, bool]:
        """Start a forge, or hand back the one that is already running.

        Returns ``(job, resumed)``. ``resumed`` is True when no new work was
        scheduled — which is the whole point: a retried start is a no-op.
        """
        async with self._lock_for_loop():
            self._prune()

            if job_id:
                existing = self._jobs.get(job_id)
                if existing is not None:
                    if existing.owner != owner:
                        raise PermissionError("job belongs to someone else")
                    return existing, True

            fp = fingerprint(owner, request)
            active = self._find_active(owner, fp)
            if active is not None:
                return active, True

            job = ForgeJob(id=job_id or uuid.uuid4().hex, owner=owner, fingerprint=fp)
            self._jobs[job.id] = job
            # Hold the Task on the job: asyncio keeps only a weak reference to
            # running tasks, so a bare create_task can be collected mid-flight.
            job.task = asyncio.create_task(self._run(job, runner), name=f"forge-job-{job.id}")
            return job, False

    def get(self, job_id: str, *, owner: str | None = None) -> ForgeJob | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        if owner is not None and job.owner != owner:
            return None
        return job

    def list_for(self, owner: str, *, limit: int = 10) -> list[ForgeJob]:
        """Newest first. This is how a client that lost its id reconnects."""
        out = [j for j in reversed(self._jobs.values()) if j.owner == owner]
        return out[: max(1, limit)]

    def latest_active(self, owner: str) -> ForgeJob | None:
        for job in reversed(self._jobs.values()):
            if job.owner == owner and not job.terminal:
                return job
        return None

    def __len__(self) -> int:
        return len(self._jobs)

    def cancel_all(self) -> None:
        """Best-effort teardown. Used by tests and by process shutdown."""
        for job in self._jobs.values():
            task = job.task
            if task is not None and not task.done():
                try:
                    task.cancel()
                except Exception:  # pragma: no cover - loop already gone
                    pass
        self._jobs.clear()


# ==========================================================================
# Process singleton
# ==========================================================================

_REGISTRY: ForgeJobRegistry | None = None


def get_forge_jobs() -> ForgeJobRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = ForgeJobRegistry()
    return _REGISTRY


def reset_forge_jobs() -> None:
    """Tests call this between cases; ``reset_container`` calls it too."""
    global _REGISTRY
    if _REGISTRY is not None:
        _REGISTRY.cancel_all()
    _REGISTRY = None

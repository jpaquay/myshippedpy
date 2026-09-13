"""First-contact profile provisioning.

Item 2 of the multi-tenancy rework. See ``docs/TENANCY_AUDIT.md``.

The problem
-----------
Before this module, ``UserRepository.upsert_profile`` had exactly one caller:
``almanac/firestore_store.py`` inside ``record_forge``. A Barogroove profile was
therefore a *side effect of a user's first forge*. Somebody who signed in and
browsed existed to Firebase and to nothing else. The profile document at
``users/{uid}`` is the anchor that per-user history, collection and taste hang
off, so it has to exist before any of them are written -- not after the first
write that happens to touch it.

What this module does
---------------------
:func:`ensure_profile` is called from every path that successfully resolves a
caller identity (see ``firebase/auth.py`` and ``routes/pairing.py``). It creates
the profile if it is missing and is a no-op afterwards. That covers both cases
the audit asked for:

* a brand-new user gets a profile on their very first authenticated request;
* an **already signed-in user who never forged** -- and therefore never got a
  profile under the old code -- gets one back-filled on their next
  authenticated request, because the process cache starts empty and the first
  call for that uid goes through to the repository.

Idempotency and the cache
-------------------------
``_ENSURED`` is a process-local set of uids for which an ``upsert_profile``
call has already **returned success**. It exists purely to keep the hot path
free of a Firestore round trip on every request.

Three properties make it safe, and they are the whole reason this is not a
repeat of the audit's finding 3 (a render cache that quietly became a data
source):

1. **It is keyed by uid.** There is no global/shared/"last one wins" entry, so
   one user's presence in the set can never answer a question about another.
2. **It holds no data.** It is a set of strings, not of profiles. Nothing reads
   a profile *out* of it; the only thing it can answer is "have we already
   completed this write?". A stale or missing entry costs one redundant
   idempotent write, never a wrong answer.
3. **It only ever records a completed write.** A failed or refused upsert is
   not cached, so the next request for that uid retries. A dead Firestore
   degrades to "we will try again", not to "this user has a profile".

Concurrency: ``upsert_profile`` is itself an idempotent ``set(merge=True)``, so
two in-flight requests for the same brand-new uid racing each other is
harmless -- the loser overwrites identical fields. The lock below guards the
Python set, not the write.

Refusal, never substitution
---------------------------
``ensure_profile(None)`` (or ``""``) returns ``False`` and writes nothing. An
unresolved identity is not provisioned as some other concrete identity; that
substitution *is* the defect class this rework exists to remove.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger("barogroove.identity")

# The scope used by surfaces that must still answer a signed-out caller.
#
# This is NOT a fallback identity in the sense the audit condemns. The bug is
# resolving an unknown caller onto a *real tenant* -- ``"demo"`` and
# ``"jpaquay"`` are both real users with real rows, and mapping a stranger onto
# them discloses those rows. This constant is a reserved scope that owns
# nothing and that no Firebase uid can collide with, so a signed-out caller
# reads an empty world instead of somebody's.
#
# It exists mainly so that sibling surfaces AGREE. Before this, an anonymous
# caller was "demo" to the advisor and "jpaquay" to dataviz, and the two were
# reconciled by an explicit two-way tenant alias in the telemetry store (audit
# finding 7) -- which is to say, by a cross-tenant leak wearing a bugfix's hat.
#
# Giving signed-out visitors a *populated* experience is demo mode, which is a
# separate item of this rework. When it lands it should serve a synthetic
# corpus under its own scope, and must not resurrect a real tenant's uid here.
ANONYMOUS_USER_ID = "anonymous_unauthenticated"

# uid -> we have already completed a successful upsert_profile in this process.
# A cache of a completed write. Never a source of profile data. See module docs.
_ENSURED: set[str] = set()
_ENSURED_LOCK = threading.Lock()


def profile_already_ensured(uid: str) -> bool:
    """Whether this process has already completed a profile write for ``uid``."""
    with _ENSURED_LOCK:
        return uid in _ENSURED


def reset_ensured_profiles() -> None:
    """Forget the process cache. For tests, and for nothing else."""
    with _ENSURED_LOCK:
        _ENSURED.clear()


def _mark_ensured(uid: str) -> None:
    with _ENSURED_LOCK:
        _ENSURED.add(uid)


async def ensure_profile(
    user_id: str | None,
    *,
    email: str | None = None,
    display_name: str | None = None,
    photo_url: str | None = None,
    provider: str = "firebase",
    settings: Any | None = None,
    repositories: Any | None = None,
) -> bool:
    """Make sure ``users/{user_id}`` exists. Idempotent; never raises.

    Returns ``True`` when the profile is known to exist (either we just wrote
    it, or we wrote it earlier in this process), ``False`` otherwise --
    including when there is no identity to provision, which is a refusal and
    not an error.
    """
    uid = user_id if isinstance(user_id, str) else None
    if not uid:
        # No resolvable caller. Refuse. Provisioning "demo" or any other
        # concrete uid here is exactly the bug this rework is removing.
        return False

    if uid == ANONYMOUS_USER_ID:
        # Item 5: demo mode is READ-ONLY. A signed-out visitor browsing the
        # seed taste must leave no trace -- no profile document, and so nothing
        # for a history, a collection or a taste vector to hang off. The
        # anonymous scope owns nothing by construction; giving it a profile
        # would quietly make it a tenant with storage, which is the first step
        # back towards a shared bucket.
        return False

    if profile_already_ensured(uid):
        return True

    try:
        if settings is None:
            from .config import get_settings  # noqa: PLC0415

            settings = get_settings()

        # No Firestore configured (local dev, the whole test suite): there is
        # no profile store to anchor anything in. Say so, do not cache, and let
        # the next request try again if the config changes.
        if not getattr(settings, "has_firestore", False):
            return False

        if repositories is None:
            from .firebase.firestore import build_repositories  # noqa: PLC0415

            repositories = build_repositories(settings)

        ok = await repositories.users.upsert_profile(
            uid,
            email=email,
            display_name=display_name,
            photo_url=photo_url,
            provider=provider,
        )
    except Exception:
        # A profile we could not write is a degraded request, not a failed one.
        # Crucially we do NOT cache, so the back-fill retries next time.
        logger.debug("ensure_profile failed for %s; will retry", uid, exc_info=True)
        return False

    if ok:
        _mark_ensured(uid)
        return True
    return False


__all__ = [
    "ANONYMOUS_USER_ID",
    "ensure_profile",
    "profile_already_ensured",
    "reset_ensured_profiles",
]

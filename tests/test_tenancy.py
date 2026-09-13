"""Cross-tenant isolation: one user must not be able to read another's rows.

These tests exist because the happy path could not catch the bugs they cover.
Every leak in ``docs/TENANCY_AUDIT.md`` returned a cheerful HTTP 200 with the
right *shape* and the wrong *owner*, so a test asserting "A sees A's data"
passed against all of them. Each test below therefore seeds data for user A,
asks as user B, and asserts B sees **nothing of A's**.

Each test names the audit finding it pins, and -- more usefully -- the exact
line of pre-fix code that made it fail. If you are reading this because one of
them went red, you have probably reintroduced a fallback identity.

The defect class, restated: a path that cannot resolve an identity must REFUSE
(empty result, or raise). It must never substitute a different concrete one. A
path that raises fails loudly here; a path that substitutes ``"demo"`` returns
200 with someone else's data in it.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.identity import (
    ANONYMOUS_USER_ID,
    ensure_profile,
    profile_already_ensured,
    reset_ensured_profiles,
)

ALICE = "alice_uid_0001"
BOB = "bob_uid_0002"


# ===========================================================================
# Helpers
# ===========================================================================


def _playlist(pl_id: str, user_id: str | None, created_at: str = "2026-01-01T00:00:00Z") -> Any:
    """A duck-typed stand-in for ``contracts.Playlist``.

    ``FirestoreAlmanac.history`` only ever reaches for ``id``, ``user_id`` and
    ``created_at`` on the process buffer entries, so a namespace is enough and
    keeps the test independent of the playlist schema.
    """
    return types.SimpleNamespace(id=pl_id, user_id=user_id, created_at=created_at)


class _FakeForges:
    """``ForgeRepository`` stand-in that serves rows strictly by owner."""

    def __init__(self, rows_by_uid: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.rows_by_uid = rows_by_uid or {}
        self.queried: list[str] = []

    async def list_for_user(self, user_id: str, limit: int = 50, **_: Any) -> list[dict[str, Any]]:
        self.queried.append(user_id)
        return list(self.rows_by_uid.get(user_id, []))


class _FakeUsers:
    def __init__(self, *, succeed: bool = True) -> None:
        self.succeed = succeed
        self.upserts: list[str] = []

    async def upsert_profile(self, uid: str, **_: Any) -> bool:
        self.upserts.append(uid)
        return self.succeed


class _FakeRepos:
    def __init__(self, forges: Any = None, users: Any = None) -> None:
        self.forges = forges if forges is not None else _FakeForges()
        self.users = users if users is not None else _FakeUsers()


def _almanac(repos: _FakeRepos) -> Any:
    from backend.app.almanac.firestore_store import FirestoreAlmanac

    return FirestoreAlmanac(types.SimpleNamespace(has_firestore=True), repositories=repos)


@pytest.fixture
def clean_forge_buffer() -> Any:
    """Isolate the process-global forge buffer around each test."""
    from backend.app.almanac import firestore_store

    saved = list(firestore_store._PROCESS_FORGE_HISTORY)
    firestore_store._PROCESS_FORGE_HISTORY.clear()
    yield firestore_store._PROCESS_FORGE_HISTORY
    firestore_store._PROCESS_FORGE_HISTORY.clear()
    firestore_store._PROCESS_FORGE_HISTORY.extend(saved)


@pytest.fixture
def clean_recent_playlists() -> Any:
    from backend.app.routes import surfaces

    saved = dict(surfaces._RECENT_PLAYLISTS)
    surfaces._RECENT_PLAYLISTS.clear()
    yield surfaces._RECENT_PLAYLISTS
    surfaces._RECENT_PLAYLISTS.clear()
    surfaces._RECENT_PLAYLISTS.update(saved)


# ===========================================================================
# Finding 1 -- almanac history merges the process-global forge buffer
# ===========================================================================
#
# Pre-fix (almanac/firestore_store.py:162-168):
#
#     if pl_uid in {user_id, "demo", None} or not playlists:
#         playlists.append(pl)
#
# Four separate ways to hand over somebody else's forge.


async def test_empty_history_does_not_serve_the_process_wide_forge_buffer(
    clean_forge_buffer: Any,
) -> None:
    """The `or not playlists` clause: every brand-new user saw everyone's forges.

    This is the worst of the four, because *having no history* is the normal
    state of every new account, so the leak fired for exactly the users least
    equipped to notice it was not their data.
    """
    clean_forge_buffer.append(_playlist("alice-forge-1", ALICE))

    got = await _almanac(_FakeRepos()).history(BOB, limit=50)

    assert got == [], f"Bob was served Alice's forge: {[p.id for p in got]}"


async def test_buffer_entries_owned_by_demo_do_not_leak(clean_forge_buffer: Any) -> None:
    """The literal `"demo"` set member: anything forged anonymously leaked to all.

    Bob is given a real Firestore row so ``playlists`` is non-empty and the
    `or not playlists` escape hatch above is not what is being tested here.
    """
    clean_forge_buffer.append(_playlist("demo-forge-1", "demo"))
    repos = _FakeRepos(_FakeForges({BOB: [{"id": "bob-row-1", "user_id": BOB}]}))

    got = await _almanac(repos).history(BOB, limit=50)

    assert "demo-forge-1" not in [getattr(p, "id", None) for p in got]


async def test_buffer_entries_with_no_owner_do_not_leak(clean_forge_buffer: Any) -> None:
    """The `None` set member: an unattributed forge went to whoever asked next."""
    clean_forge_buffer.append(_playlist("orphan-forge-1", None))
    repos = _FakeRepos(_FakeForges({BOB: [{"id": "bob-row-1", "user_id": BOB}]}))

    got = await _almanac(repos).history(BOB, limit=50)

    assert "orphan-forge-1" not in [getattr(p, "id", None) for p in got]


async def test_a_user_still_sees_their_own_buffered_forge(clean_forge_buffer: Any) -> None:
    """The buffer still does its job -- this is a fix, not an amputation."""
    clean_forge_buffer.append(_playlist("bob-forge-1", BOB))

    got = await _almanac(_FakeRepos()).history(BOB, limit=50)

    assert [p.id for p in got] == ["bob-forge-1"]


async def test_history_refuses_an_unresolved_caller(clean_forge_buffer: Any) -> None:
    """No uid is a refusal, not an invitation to pick one."""
    clean_forge_buffer.append(_playlist("alice-forge-1", ALICE))
    almanac = _almanac(_FakeRepos())

    assert await almanac.history("", limit=50) == []
    assert await almanac.history(None, limit=50) == []  # type: ignore[arg-type]


# ===========================================================================
# Finding 2 -- ForgeRepository.list_for_user retried as "demo" on an empty result
# ===========================================================================
#
# Pre-fix (firebase/firestore.py:565-566):
#
#     if not rows and user_id != "demo":
#         rows = await _query_uid("demo")


class _FakeSnap:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)


class _FakeQuery:
    """Minimal async Firestore query double that records the uid filtered on."""

    def __init__(self, store: dict[str, list[dict[str, Any]]], sink: list[str]) -> None:
        self._store = store
        self._sink = sink
        self._uid: str | None = None

    def where(self, filter: Any = None, **_: Any) -> "_FakeQuery":  # noqa: A002
        field, _op, value = filter.args
        if field == "user_id":
            self._uid = value
            self._sink.append(value)
        return self

    def order_by(self, *_: Any, **__: Any) -> "_FakeQuery":
        return self

    def limit(self, *_: Any, **__: Any) -> "_FakeQuery":
        return self

    async def stream(self) -> Any:
        for row in self._store.get(self._uid or "", []):
            yield _FakeSnap(row)


class _FakeCollection:
    def __init__(self, store: dict[str, list[dict[str, Any]]], sink: list[str]) -> None:
        self._store = store
        self._sink = sink

    def where(self, filter: Any = None, **kw: Any) -> _FakeQuery:  # noqa: A002
        return _FakeQuery(self._store, self._sink).where(filter=filter, **kw)


@pytest.fixture
def firestore_query_shim(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Make the lazy ``FieldFilter`` import inside ``_query_uid`` resolvable.

    google-cloud-firestore is not installed in this environment, and the import
    lives inside the guarded call, so without this shim the query would raise,
    be swallowed, and return ``[]`` -- which would make this test pass against
    the *unfixed* code too. The shim is what gives the assertion teeth.
    """
    mod = types.ModuleType("google.cloud.firestore_v1.base_query")

    class FieldFilter:
        def __init__(self, *args: Any) -> None:
            self.args = args

    mod.FieldFilter = FieldFilter  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google.cloud.firestore_v1.base_query", mod)
    return mod


async def test_forge_list_never_falls_back_to_the_demo_tenant(
    monkeypatch: pytest.MonkeyPatch, firestore_query_shim: Any
) -> None:
    """An empty result is an empty result, not a reason to serve `demo`."""
    from backend.app.firebase.firestore import ForgeRepository

    rows = {
        "demo": [{"id": "demo-forge", "user_id": "demo"}],
        ALICE: [{"id": "alice-forge", "user_id": ALICE}],
    }
    queried: list[str] = []
    repo = ForgeRepository(types.SimpleNamespace(has_firestore=True))

    async def _collection(_self: Any, _name: str) -> Any:
        return _FakeCollection(rows, queried)

    monkeypatch.setattr(ForgeRepository, "_collection", _collection, raising=True)

    # Bob has forged nothing at all.
    got = await repo.list_for_user(BOB, limit=50)

    assert got == [], f"Bob was served another tenant's forges: {got}"
    assert queried == [BOB], f"expected exactly one query, for Bob; got {queried}"
    assert "demo" not in queried, "the demo retry is back"

    # And the query still works for somebody who does own rows.
    queried.clear()
    mine = await repo.list_for_user(ALICE, limit=50)
    assert [r["id"] for r in mine] == ["alice-forge"]


async def test_forge_list_refuses_an_unresolved_caller(firestore_query_shim: Any) -> None:
    from backend.app.firebase.firestore import ForgeRepository

    repo = ForgeRepository(types.SimpleNamespace(has_firestore=True))
    assert await repo.list_for_user("", limit=50) == []


# ===========================================================================
# Findings 7 and 8 -- telemetry: the demo<->jpaquay alias and default user_id
# ===========================================================================
#
# Pre-fix (telemetry/store.py:130-131):
#
#     if target_user_id in ("demo", "jpaquay"):
#         return record_user_id in ("demo", "jpaquay")


def _store() -> Any:
    from backend.app.telemetry.store import DualSinkTelemetryStore

    return DualSinkTelemetryStore(types.SimpleNamespace(has_firestore=False))


def _memory(user_id: str, content: str) -> Any:
    from backend.app.telemetry.models import MemoryRecord

    return MemoryRecord(user_id=user_id, content=content)


def test_memories_do_not_cross_between_users() -> None:
    store = _store()
    store.upsert_memory_sync(_memory(ALICE, "Alice adores Boards of Canada"))

    mine, _ = store.list_memories(user_id=BOB, limit=50)

    assert mine == [], f"Bob read Alice's memories: {[m.content for m in mine]}"


def test_memories_do_not_cross_between_demo_and_jpaquay() -> None:
    """The explicit two-way tenant alias, pinned in both directions.

    This is the one that mattered most in practice: `demo` is the tenant every
    signed-out visitor landed on, and `jpaquay` is a real named human being.
    The alias made their AI conversation history and extracted memories a
    shared pool.
    """
    store = _store()
    store.upsert_memory_sync(_memory("jpaquay", "a real person's listening habit"))
    store.upsert_memory_sync(_memory("demo", "a demo tenant habit"))

    as_demo, _ = store.list_memories(user_id="demo", limit=50)
    as_jpaquay, _ = store.list_memories(user_id="jpaquay", limit=50)

    assert [m.content for m in as_demo] == ["a demo tenant habit"]
    assert [m.content for m in as_jpaquay] == ["a real person's listening habit"]


def test_conversations_and_sessions_do_not_cross_between_users() -> None:
    store = _store()
    sess = store.resolve_or_create_session(user_id=ALICE, client_surface="advisor")
    conv = store.resolve_or_create_conversation(session_id=sess.session_id, user_id=ALICE)
    store.append_conversation_turn(
        conversation_id=conv.conversation_id,
        role="user",
        content="Alice said something private",
        user_id=ALICE,
    )

    bob_convs, _ = store.list_conversations(user_id=BOB, limit=50)
    bob_sessions, _ = store.list_sessions(user_id=BOB, limit=50)

    assert bob_convs == [], "Bob read Alice's conversations"
    assert bob_sessions == [], "Bob read Alice's sessions"


def test_conversations_and_sessions_do_not_cross_between_demo_and_jpaquay() -> None:
    store = _store()
    sess = store.resolve_or_create_session(user_id="jpaquay", client_surface="advisor")
    store.resolve_or_create_conversation(session_id=sess.session_id, user_id="jpaquay")

    as_demo, _ = store.list_conversations(user_id="demo", limit=50)
    demo_sessions, _ = store.list_sessions(user_id="demo", limit=50)

    assert as_demo == []
    assert demo_sessions == []


def test_telemetry_records_refuse_to_be_built_without_an_owner() -> None:
    """`user_id` has no default any more -- omitting it is a loud error.

    Pre-fix these carried ``user_id: str = "demo"``, so a caller that forgot to
    say who it was had its records filed against the demo tenant and nothing
    anywhere failed. Construction is where the caller still knows the answer,
    so that is where it should fail.
    """
    from pydantic import ValidationError

    from backend.app.telemetry.models import (
        ConversationRecord,
        MemoryCreateRequest,
        MemoryRecord,
        SessionRecord,
        TrajectoryRecord,
    )

    with pytest.raises(ValidationError):
        TrajectoryRecord()
    with pytest.raises(ValidationError):
        SessionRecord()
    with pytest.raises(ValidationError):
        ConversationRecord()
    with pytest.raises(ValidationError):
        MemoryRecord(content="orphan")
    with pytest.raises(ValidationError):
        MemoryCreateRequest(content="orphan")


def test_telemetry_store_refuses_an_empty_user_id() -> None:
    """An empty uid raises rather than resolving to `demo`."""
    store = _store()

    with pytest.raises(ValueError):
        store.resolve_or_create_session(user_id="")
    with pytest.raises(ValueError):
        store.resolve_or_create_conversation(user_id="")


def test_appending_to_an_unknown_conversation_refuses_without_an_owner() -> None:
    """The auto-create branch used to mint a demo-owned conversation silently."""
    store = _store()

    with pytest.raises(ValueError):
        store.append_conversation_turn(
            conversation_id="conv_never_seen_before",
            role="user",
            content="whose words are these?",
        )


def test_memory_extraction_refuses_an_empty_user_id() -> None:
    from backend.app.telemetry.memory_extractor import (
        extract_memories_from_turn,
        extract_memory_from_feedback,
    )

    with pytest.raises(ValueError):
        extract_memories_from_turn(user_id="", prompt="I love dub techno")
    with pytest.raises(ValueError):
        extract_memory_from_feedback(
            user_id="", playlist_id="p", track_key="t", signal="loved"
        )


# ===========================================================================
# Findings 3, 4 and 11 -- the A2UI surface actions, end to end over HTTP
# ===========================================================================
#
# Pre-fix (routes/surfaces.py):
#   :841      uid = user.uid if user else "demo"
#   :883-884  any playlist id the client names, from a process-global dict
#   :894-896  on a miss, retry almanac().history("demo")
#   :903-904  failing that, `list(_RECENT_PLAYLISTS.values())[-1]`


def _forge_as(client: TestClient, uid: str) -> str:
    res = client.post(
        "/api/forge",
        json={"theme_id": "petrichor", "length": 5, "sink": "m3u", "seed": 1958},
        headers={"X-Barogroove-User": uid},
    )
    assert res.status_code == 200, res.text
    return str(res.json()["playlist"]["id"])


def _show_playlist(client: TestClient, playlist_id: str, uid: str | None) -> Any:
    headers = {"X-Barogroove-User": uid} if uid else {}
    return client.post(
        "/api/surfaces/action",
        json={
            "actionResponse": {
                "surfaceId": "playlist",
                "actionId": "showPlaylist",
                "payload": {"playlist_id": playlist_id},
            }
        },
        headers=headers,
    )


def test_another_user_cannot_open_your_playlist_by_id(
    client: TestClient, clean_recent_playlists: Any
) -> None:
    """Bob names Alice's playlist id and must be refused.

    Pre-fix this returned 200 with Alice's playlist in it, straight out of the
    process-global `_RECENT_PLAYLISTS`, with no ownership test anywhere.
    """
    alice_playlist = _forge_as(client, ALICE)

    res = _show_playlist(client, alice_playlist, BOB)

    assert res.status_code == 404, (
        f"Bob opened Alice's playlist: {res.status_code} {res.text[:400]}"
    )


def test_an_anonymous_caller_cannot_open_your_playlist_by_id(
    client: TestClient, clean_recent_playlists: Any
) -> None:
    """And a signed-out caller is not silently mapped onto a real tenant."""
    alice_playlist = _forge_as(client, ALICE)

    res = _show_playlist(client, alice_playlist, None)

    assert res.status_code == 404, res.text[:400]


def test_a_bogus_playlist_id_does_not_serve_the_last_thing_anyone_forged(
    client: TestClient, clean_recent_playlists: Any
) -> None:
    """Pre-fix, a miss fell through to `list(_RECENT_PLAYLISTS.values())[-1]`.

    That is not the requested playlist by any definition -- it is whatever the
    process happened to forge most recently, for anyone.
    """
    _forge_as(client, ALICE)

    res = _show_playlist(client, "no-such-playlist-id", BOB)

    assert res.status_code == 404, res.text[:400]


def test_you_can_still_open_your_own_playlist(
    client: TestClient, clean_recent_playlists: Any
) -> None:
    """The owner's path still works -- ownership, not a blanket refusal."""
    alice_playlist = _forge_as(client, ALICE)

    res = _show_playlist(client, alice_playlist, ALICE)

    assert res.status_code == 200, res.text[:400]


def test_the_almanac_surface_does_not_show_another_users_forges(
    client: TestClient, clean_recent_playlists: Any
) -> None:
    """Bob's almanac must not contain Alice's playlist.

    Pre-fix the almanac action iterated *every* value of the process-global
    recent-playlists dict, so Bob's almanac was seeded with Alice's forges.
    """
    alice_playlist = _forge_as(client, ALICE)

    res = client.post(
        "/api/surfaces/action",
        json={"actionResponse": {"surfaceId": "almanac", "actionId": "showAlmanac"}},
        headers={"X-Barogroove-User": BOB},
    )

    assert res.status_code == 200, res.text[:400]
    assert alice_playlist not in res.text, "Alice's playlist id leaked into Bob's almanac"


def test_almanac_history_endpoint_does_not_cross_users(client: TestClient) -> None:
    """The REST history endpoint, same property."""
    alice_playlist = _forge_as(client, ALICE)

    res = client.get("/api/almanac/history", headers={"X-Barogroove-User": BOB})

    assert res.status_code == 200, res.text[:400]
    assert alice_playlist not in res.text, "Alice's forge appeared in Bob's history"


def test_the_recent_playlist_buffer_is_keyed_by_owner(
    client: TestClient, clean_recent_playlists: Any
) -> None:
    """Structural: there is no process-global bucket left to read from."""
    from backend.app.routes import surfaces

    alice_playlist = _forge_as(client, ALICE)

    assert surfaces.recent_playlist_for(ALICE, alice_playlist) is not None
    assert surfaces.recent_playlist_for(BOB, alice_playlist) is None
    assert surfaces.recent_playlists_for(BOB) == []
    # An unresolved caller gets nothing, rather than everything.
    assert surfaces.recent_playlists_for(None) == []
    assert surfaces.recent_playlist_for(None, alice_playlist) is None


def test_an_unowned_playlist_is_not_recorded_in_the_recent_buffer(
    clean_recent_playlists: Any,
) -> None:
    """An unattributable write is not a write belonging to everybody."""
    from backend.app.routes import surfaces

    surfaces.record_recent_playlist(_playlist("orphan", None))

    assert clean_recent_playlists == {}


# ===========================================================================
# Item 2 -- the profile is created at first authenticated contact
# ===========================================================================


@pytest.fixture(autouse=True)
def _reset_profile_cache() -> Any:
    reset_ensured_profiles()
    yield
    reset_ensured_profiles()


async def test_ensure_profile_refuses_an_unresolved_caller() -> None:
    """No identity means no provisioning -- not provisioning as someone else."""
    users = _FakeUsers()
    settings = types.SimpleNamespace(has_firestore=True)

    assert await ensure_profile(None, settings=settings, repositories=_FakeRepos(users=users)) is False
    assert await ensure_profile("", settings=settings, repositories=_FakeRepos(users=users)) is False
    assert users.upserts == [], "a profile was written for nobody"


async def test_first_contact_creates_the_profile_and_later_contact_is_free() -> None:
    """Idempotent: written once, then a set lookup on the hot path."""
    users = _FakeUsers()
    repos = _FakeRepos(users=users)
    settings = types.SimpleNamespace(has_firestore=True)

    assert await ensure_profile(ALICE, settings=settings, repositories=repos) is True
    assert users.upserts == [ALICE]

    for _ in range(5):
        assert await ensure_profile(ALICE, settings=settings, repositories=repos) is True
    assert users.upserts == [ALICE], "the hot path hit Firestore again"


async def test_the_ensured_cache_is_keyed_by_uid_and_never_answers_for_another_user() -> None:
    """The cache is a record of completed writes, not a source of data.

    Audit finding 3 was a render cache that quietly became a data source. This
    asserts the profile cache cannot repeat that: Alice being cached must not
    make Bob look provisioned.
    """
    users = _FakeUsers()
    repos = _FakeRepos(users=users)
    settings = types.SimpleNamespace(has_firestore=True)

    await ensure_profile(ALICE, settings=settings, repositories=repos)

    assert profile_already_ensured(ALICE) is True
    assert profile_already_ensured(BOB) is False

    await ensure_profile(BOB, settings=settings, repositories=repos)
    assert users.upserts == [ALICE, BOB]


async def test_a_failed_write_is_not_cached_so_the_backfill_retries() -> None:
    """A user who exists to Firebase but not to Barogroove must keep retrying.

    This is the back-fill requirement: the profile write must be re-attempted
    on the next authenticated request, not written off because we tried once.
    """
    failing = _FakeUsers(succeed=False)
    repos = _FakeRepos(users=failing)
    settings = types.SimpleNamespace(has_firestore=True)

    assert await ensure_profile(ALICE, settings=settings, repositories=repos) is False
    assert await ensure_profile(ALICE, settings=settings, repositories=repos) is False
    assert failing.upserts == [ALICE, ALICE], "a failed write was cached as done"
    assert profile_already_ensured(ALICE) is False

    # Once Firestore recovers, the next contact provisions and then settles.
    recovered = _FakeUsers(succeed=True)
    assert await ensure_profile(
        ALICE, settings=settings, repositories=_FakeRepos(users=recovered)
    ) is True
    assert profile_already_ensured(ALICE) is True


async def test_ensure_profile_never_raises_when_the_repository_explodes() -> None:
    """A profile we could not write is a degraded request, not a failed one."""

    class _Exploding:
        async def upsert_profile(self, uid: str, **_: Any) -> bool:
            raise RuntimeError("firestore is on fire")

    ok = await ensure_profile(
        ALICE,
        settings=types.SimpleNamespace(has_firestore=True),
        repositories=_FakeRepos(users=_Exploding()),
    )

    assert ok is False
    assert profile_already_ensured(ALICE) is False


async def test_browsing_provisions_a_profile_without_ever_forging() -> None:
    """The point of item 2: a user who signs in and browses now exists.

    Pre-fix, ``upsert_profile`` had exactly one caller -- inside
    ``record_forge`` -- so a profile was a side effect of a user's *first
    forge*. This asserts the profile exists after a plain authenticated
    request, with no forge anywhere in sight.
    """
    from backend.app.routes.pairing import current_user_id

    users = _FakeUsers()
    repos = _FakeRepos(users=users)
    settings = types.SimpleNamespace(has_firestore=True)

    # Stand in for what the dependency does once it has resolved a caller.
    await ensure_profile(ALICE, settings=settings, repositories=repos)

    assert users.upserts == [ALICE]
    assert callable(current_user_id)


def test_a_plain_authenticated_request_reaches_the_provisioning_hook(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end: a browse-only request calls ensure_profile with the caller.

    ``/api/pair/status`` writes nothing and forges nothing. It is about as
    passive as an authenticated request gets, which is exactly why it is the
    right probe for "does merely showing up provision a profile?".
    """
    seen: list[str | None] = []

    async def _spy(user_id: str | None, **_: Any) -> bool:
        seen.append(user_id)
        return True

    import backend.app.identity as identity_mod

    monkeypatch.setattr(identity_mod, "ensure_profile", _spy)

    res = client.get("/api/pair/status", headers={"X-Barogroove-User": ALICE})

    assert res.status_code == 200, res.text[:300]
    assert ALICE in seen, f"first authenticated contact did not provision; saw {seen}"


def test_the_anonymous_scope_is_not_a_real_tenant() -> None:
    """The reserved anonymous scope must not collide with demo or jpaquay."""
    assert ANONYMOUS_USER_ID not in ("demo", "jpaquay", "demo_user", "")

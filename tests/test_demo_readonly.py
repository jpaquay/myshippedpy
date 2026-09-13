"""Demo mode is strictly read-only.

Item 5 of the multi-tenancy rework. See ``docs/TENANCY_AUDIT.md`` finding 10.

Two guarantees, and neither is allowed to rest on a comment:

1. **The seed corpus is read-only.** ``data/scrobbles/`` is the pre-loaded
   Last.fm corpus that gives a signed-out visitor a real-feeling almanac.
   Nothing in demo mode may write into it. The tests below attempt writes
   through the real demo code paths and assert they are refused or diverted --
   they do not merely inspect a constant.

2. **Demo data must never contaminate a signed-in user.** The anonymous scope
   owns nothing: no profile, and so nothing for a history or a taste vector to
   hang off, and its rows are not readable by an authenticated user.

The file-level assertions hash the corpus before and after, so a regression
that writes into it fails here even if it writes a file these tests never
named.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from backend.app.almanac import data_qna, seed_corpus
from backend.app.identity import ANONYMOUS_USER_ID, ensure_profile, reset_ensured_profiles


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _corpus_fingerprint() -> dict[str, str]:
    """sha256 of every file in the seed corpus, keyed by relative path."""
    root = seed_corpus.SEED_CORPUS_DIR
    if not root.is_dir():
        return {}
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


@pytest.fixture()
def corpus_unchanged() -> Any:
    """Fail the test if the seed corpus changed in any way while it ran."""
    before = _corpus_fingerprint()
    yield
    after = _corpus_fingerprint()

    added = set(after) - set(before)
    removed = set(before) - set(after)
    modified = {p for p in set(before) & set(after) if before[p] != after[p]}
    assert not added, f"demo path CREATED files in the read-only seed corpus: {sorted(added)}"
    assert not removed, f"demo path DELETED files from the seed corpus: {sorted(removed)}"
    assert not modified, f"demo path MODIFIED files in the seed corpus: {sorted(modified)}"


# --------------------------------------------------------------------------- #
# the boundary itself
# --------------------------------------------------------------------------- #


def test_seed_and_runtime_directories_are_disjoint() -> None:
    assert not seed_corpus.is_seed_path(seed_corpus.RUNTIME_CACHE_DIR)
    assert seed_corpus.is_seed_path(seed_corpus.SEED_CORPUS_DIR)


def test_a_path_inside_the_corpus_is_recognised() -> None:
    assert seed_corpus.is_seed_path(seed_corpus.SEED_CORPUS_DIR / "summary_cache.json")
    assert seed_corpus.is_seed_path(seed_corpus.SEED_CORPUS_DIR / "qna_cache" / "x.json")


def test_traversal_back_into_the_corpus_is_recognised() -> None:
    """``..`` must not launder a seed path into an allowed one."""
    sneaky = seed_corpus.RUNTIME_CACHE_DIR / ".." / ".." / "data" / "scrobbles" / "x.json"
    assert seed_corpus.is_seed_path(sneaky)


def test_writing_into_the_corpus_is_refused(corpus_unchanged: Any) -> None:
    target = seed_corpus.SEED_CORPUS_DIR / "summary_cache.json"
    with pytest.raises(seed_corpus.SeedCorpusWriteRefused):
        seed_corpus.refuse_if_seed(target)
    with pytest.raises(seed_corpus.SeedCorpusWriteRefused):
        seed_corpus.write_text(target, "clobbered")


def test_the_refusal_names_the_offending_path() -> None:
    """A refusal nobody can diagnose gets suppressed by the next person."""
    with pytest.raises(seed_corpus.SeedCorpusWriteRefused) as exc:
        seed_corpus.refuse_if_seed(seed_corpus.SEED_CORPUS_DIR / "track_catalog.jsonl")
    message = str(exc.value)
    assert "track_catalog.jsonl" in message
    assert "read-only" in message


def test_writable_path_never_lands_in_the_corpus() -> None:
    assert not seed_corpus.is_seed_path(seed_corpus.writable_path("summary_cache.json"))
    assert not seed_corpus.is_seed_path(seed_corpus.writable_path("qna_cache", "abc.json"))


def test_readable_path_prefers_runtime_then_falls_back_to_seed(tmp_path: Path) -> None:
    """A regenerated artifact shadows the shipped one without overwriting it."""
    name = "readable_probe.json"
    seed_file = seed_corpus.SEED_CORPUS_DIR / name
    runtime_file = seed_corpus.RUNTIME_CACHE_DIR / name
    assert seed_corpus.readable_path(name) is None

    runtime_file.parent.mkdir(parents=True, exist_ok=True)
    runtime_file.write_text("runtime", encoding="utf-8")
    try:
        assert seed_corpus.readable_path(name) == runtime_file
        # and the seed was never created to make that happen
        assert not seed_file.exists()
    finally:
        runtime_file.unlink()


# --------------------------------------------------------------------------- #
# the real demo code paths
# --------------------------------------------------------------------------- #


def test_the_qna_cache_writes_outside_the_corpus(corpus_unchanged: Any) -> None:
    """A write through the actual demo Q&A path, asserted to miss the corpus.

    This is the regression that produced stray untracked files under
    ``data/scrobbles/qna_cache/`` during development.
    """
    key = "demo_readonly_probe"
    landed = seed_corpus.RUNTIME_CACHE_DIR / "qna_cache" / f"{key}.json"
    if landed.exists():
        landed.unlink()

    data_qna._save_cached_qna(key, {"answer": "42"})

    assert landed.exists(), "the answer should have been cached in the runtime cache"
    assert json.loads(landed.read_text(encoding="utf-8")) == {"answer": "42"}
    assert not (seed_corpus.SEED_CORPUS_DIR / "qna_cache" / f"{key}.json").exists()
    landed.unlink()


def test_the_qna_cache_refuses_if_repointed_at_the_corpus(
    monkeypatch: pytest.MonkeyPatch, corpus_unchanged: Any
) -> None:
    """If someone re-points the cache at the corpus, the write must refuse.

    Not silently redirect. A redirect would mean the caller believes something
    happened that did not -- the same shape as the identity fallbacks this
    rework removes.
    """
    monkeypatch.setattr(
        seed_corpus, "RUNTIME_CACHE_DIR", seed_corpus.SEED_CORPUS_DIR, raising=True
    )
    with pytest.raises(seed_corpus.SeedCorpusWriteRefused):
        data_qna._save_cached_qna("repointed_probe", {"answer": "nope"})


def test_importing_the_app_creates_nothing_in_the_corpus(corpus_unchanged: Any) -> None:
    """``data_qna`` used to ``mkdir`` inside the corpus at import time."""
    import importlib

    importlib.reload(seed_corpus)
    assert not seed_corpus.is_seed_path(seed_corpus.RUNTIME_CACHE_DIR)


def test_the_shipped_corpus_is_actually_present() -> None:
    """Guard the guard: these tests are vacuous if the corpus is not here."""
    assert (seed_corpus.SEED_CORPUS_DIR / "summary_cache.json").exists()
    assert _corpus_fingerprint(), "seed corpus is empty; the read-only tests prove nothing"


# --------------------------------------------------------------------------- #
# no contamination of a signed-in user
# --------------------------------------------------------------------------- #


class _RecordingUsers:
    """Records every profile write attempted against it."""

    def __init__(self) -> None:
        self.upserts: list[str] = []

    async def upsert_profile(self, uid: str, **_kw: Any) -> bool:
        self.upserts.append(uid)
        return True


class _RecordingRepos:
    def __init__(self) -> None:
        self.users = _RecordingUsers()


class _FirestoreConfigured:
    """Settings that claim a live Firestore, so the refusal is really tested.

    Without this the test is vacuous: ``ensure_profile`` returns False for
    everyone when there is no profile store configured, which is the case for
    the whole suite. Pinning has_firestore=True makes the ANONYMOUS refusal the
    only thing that can produce a False.
    """

    has_firestore = True


async def test_demo_mode_provisions_no_profile() -> None:
    """The anonymous scope owns nothing -- so it gets no profile document.

    A profile is the anchor history, collection and taste hang off. Giving the
    demo scope one would quietly make it a tenant with storage.
    """
    reset_ensured_profiles()
    repos = _RecordingRepos()

    refused = await ensure_profile(
        ANONYMOUS_USER_ID, settings=_FirestoreConfigured(), repositories=repos
    )

    assert refused is False
    assert repos.users.upserts == [], "demo mode attempted a profile write"


async def test_a_real_user_still_gets_a_profile() -> None:
    """The control. Without this, refusing *everything* would pass the test above."""
    reset_ensured_profiles()
    repos = _RecordingRepos()

    created = await ensure_profile(
        "aRealFirebaseUid0000000000ab", settings=_FirestoreConfigured(), repositories=repos
    )

    assert created is True
    assert repos.users.upserts == ["aRealFirebaseUid0000000000ab"]


async def test_an_unresolved_caller_provisions_no_profile() -> None:
    reset_ensured_profiles()
    repos = _RecordingRepos()
    settings = _FirestoreConfigured()

    assert await ensure_profile(None, settings=settings, repositories=repos) is False
    assert await ensure_profile("", settings=settings, repositories=repos) is False
    assert repos.users.upserts == []


def test_the_anonymous_scope_cannot_collide_with_a_firebase_uid() -> None:
    """Demo mode must not be able to *become* a real tenant by name.

    Firebase uids are 28 alphanumeric characters. The reserved scope contains
    an underscore and is longer, so no real account can ever be handed it.
    """
    assert "_" in ANONYMOUS_USER_ID
    assert len(ANONYMOUS_USER_ID) != 28
    assert ANONYMOUS_USER_ID not in ("demo", "jpaquay", "demo_user", "anonymous")


def test_the_seed_handle_is_not_used_as_a_fallback_identity() -> None:
    """The corpus is attributed to a real Last.fm handle.

    That is fine as *data*. It is not fine as an identity default -- findings
    5, 7 and 9 were all this string leaking into uid resolution.
    """
    assert seed_corpus.SEED_CORPUS_HANDLE == "jpaquay"
    assert seed_corpus.SEED_CORPUS_HANDLE != ANONYMOUS_USER_ID

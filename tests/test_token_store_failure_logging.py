"""Regression tests for the 2026-09-14 ``token_store_failed`` outage.

What happened
-------------
Every Firestore call in the project started failing with

    400 The database (default) is disabled for project netdev-firebase.
    The database has an App Engine app and this app is disabled.

``TokenRepository.put`` dutifully returned ``False``, ``FirestoreTokenVault.put``
raised ``TokenVaultError: could not persist spotify credentials``, and the
pairing callback returned an honest ``token_store_failed`` to the user. All
correct -- and all useless, because the *reason* lived in a separate bare
WARNING with no document path and no exception type, 126 ms away from the
traceback in the log.

These tests pin the diagnosis, not the failure. A write that fails must:

* still return falsy (the degradation contract is deliberate),
* put the exception type, the document path and the provider in the log at a
  severity that sits next to the traceback,
* chain the real cause onto ``TokenVaultError`` so the callback's
  ``logger.exception`` prints it, and
* leak neither the payload nor the raw uid while doing so.

No network, no emulator, no credentials: the backend failure is simulated by a
document stub that raises, exactly as the real client did.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.firebase import firestore as fs_mod  # noqa: E402
from app.firebase import tokens as tok_mod  # noqa: E402

FS_LOGGER = "barogroove.firebase.firestore"
TOK_LOGGER = "barogroove.firebase.tokens"

#: A uid shaped like a real Firebase one. It must never reach a log line.
UID = "kQ7mZ2rLbTfXd0aWpN4eS1uJ9gH3"

#: Stand-in for a Spotify refresh token. Must never reach a log line either.
SECRET = "AQD-do-not-log-this-refresh-token-0123456789"


# --------------------------------------------------------------------------- #
# Backend failures, shaped like the ones google.api_core raises.
#
# Matched by class *name* in `_is_retryable`, same as production, so neither of
# these is retried and the tests stay fast.
# --------------------------------------------------------------------------- #


class PermissionDenied(Exception):
    """Shaped like a ``firestore.rules`` / IAM denial."""


class FailedPrecondition(Exception):
    """Shaped like the 400 that actually took Spotify pairing down."""


DATABASE_DISABLED = (
    "400 The database (default) is disabled for project netdev-firebase. "
    "The database has an App Engine app and this app is disabled. Please refer "
    "to https://cloud.google.com/firestore/docs/app-engine-requirement to "
    "unlink your database from App Engine"
)

RULES_DENIAL = "403 Missing or insufficient permissions."

BACKEND_FAILURES = [
    pytest.param(PermissionDenied, RULES_DENIAL, id="rules-or-iam-denial"),
    pytest.param(FailedPrecondition, DATABASE_DISABLED, id="database-disabled"),
]


def make_settings(**overrides: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "environment": "local",
        "gcp_project": "netdev-firebase",
        "firebase_project_id": "netdev-firebase",
        "firestore_database": "(default)",
        "token_encryption_key": "",
        "has_firestore": True,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def run_async(coro: Any) -> Any:
    return asyncio.run(coro)


class _ExplodingClient:
    """Smallest possible async Firestore stand-in: every operation raises.

    Chaining (`collection().document().collection().document()`) returns
    ``self``, so one object covers the whole path the repository walks.
    """

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def collection(self, name: str) -> "_ExplodingClient":
        return self

    def document(self, doc_id: str) -> "_ExplodingClient":
        return self

    async def set(self, data: Any, **kwargs: Any) -> None:
        raise self._exc

    async def get(self) -> Any:
        raise self._exc

    async def delete(self) -> None:
        raise self._exc


def install_failing_backend(monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> None:
    """Point every ``TokenRepository`` at a client that fails like production."""
    client = _ExplodingClient(exc)

    async def _fake_client(self: Any) -> Any:
        return client

    monkeypatch.setattr(fs_mod.TokenRepository, "_client", _fake_client)


class TestRedactedDocumentPath:
    def test_path_names_the_document_without_naming_the_user(self) -> None:
        path = fs_mod.token_doc_path(UID, "spotify")

        assert path.startswith("users/uid-")
        assert path.endswith("/tokens/spotify")
        assert UID not in path

    def test_fingerprint_is_stable_so_two_log_lines_can_be_joined(self) -> None:
        assert fs_mod.redact_uid(UID) == fs_mod.redact_uid(UID)
        assert fs_mod.redact_uid(UID) != fs_mod.redact_uid(UID + "x")


class TestFailedWriteReportsItsCause:
    """The test that would have made the outage a one-minute read."""

    @pytest.mark.parametrize("exc_cls,message", BACKEND_FAILURES)
    def test_put_returns_falsy(
        self, exc_cls: type[Exception], message: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The degradation contract is deliberate; keep it."""
        install_failing_backend(monkeypatch, exc_cls(message))
        repo = fs_mod.TokenRepository(make_settings())

        assert not run_async(repo.put(UID, "spotify", {"ciphertext": SECRET}))

    @pytest.mark.parametrize("exc_cls,message", BACKEND_FAILURES)
    def test_log_carries_type_path_provider_and_backend_message(
        self,
        exc_cls: type[Exception],
        message: str,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        install_failing_backend(monkeypatch, exc_cls(message))
        repo = fs_mod.TokenRepository(make_settings())

        with caplog.at_level(logging.DEBUG, logger=FS_LOGGER):
            run_async(repo.put(UID, "spotify", {"ciphertext": SECRET}))

        records = [r for r in caplog.records if r.name == FS_LOGGER]
        assert records, "a failed token write logged nothing at all"
        record = records[-1]
        rendered = record.getMessage()

        # Severity: this ends a pairing attempt, so it belongs next to the
        # traceback, not in the WARNING stream you scroll past.
        assert record.levelno >= logging.ERROR
        # Exception type -- "is this a denial or an outage?" answered inline.
        assert exc_cls.__name__ in rendered
        # The backend's own sentence, which is where the fix actually lives.
        assert message in rendered
        # Which document, and which provider.
        assert fs_mod.token_doc_path(UID, "spotify") in rendered
        assert "spotify" in rendered
        # Structured, so it can be filtered rather than grepped.
        assert record.firestore_error_type == exc_cls.__name__
        assert record.firestore_doc == fs_mod.token_doc_path(UID, "spotify")
        assert record.firestore_op == "tokens.put(spotify)"

    @pytest.mark.parametrize("exc_cls,message", BACKEND_FAILURES)
    def test_log_leaks_neither_the_payload_nor_the_uid(
        self,
        exc_cls: type[Exception],
        message: str,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """SECURITY ASSERTION.

        The repository docstring promises it never logs the payload. Better
        diagnostics must not quietly buy themselves out of that promise, and
        the extra document path must not smuggle a raw uid in either.
        """
        install_failing_backend(monkeypatch, exc_cls(message))
        repo = fs_mod.TokenRepository(make_settings())

        with caplog.at_level(logging.DEBUG, logger=FS_LOGGER):
            run_async(
                repo.put(
                    UID,
                    "spotify",
                    {"ciphertext": SECRET, "refresh_token": SECRET, "schema": 1},
                )
            )

        # caplog.text includes the rendered exc_info, so this covers the
        # traceback the ERROR now attaches.
        assert SECRET not in caplog.text
        assert UID not in caplog.text

    @pytest.mark.parametrize("exc_cls,message", BACKEND_FAILURES)
    def test_failure_is_recorded_for_the_caller(
        self, exc_cls: type[Exception], message: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install_failing_backend(monkeypatch, exc_cls(message))
        repo = fs_mod.TokenRepository(make_settings())

        async def _put_then_read() -> Any:
            await repo.put(UID, "spotify", {"ciphertext": SECRET})
            return fs_mod.last_failure()

        failure = run_async(_put_then_read())

        assert failure is not None
        assert failure.error_type == exc_cls.__name__
        assert failure.path == fs_mod.token_doc_path(UID, "spotify")
        assert message in failure.summary()
        assert SECRET not in failure.summary()

    def test_a_successful_write_records_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stale cause must not be chained onto the next request's error."""

        class _Ok(_ExplodingClient):
            async def set(self, data: Any, **kwargs: Any) -> None:
                return None

        client = _Ok(RuntimeError("unused"))

        async def _fake_client(self: Any) -> Any:
            return client

        monkeypatch.setattr(fs_mod.TokenRepository, "_client", _fake_client)
        repo = fs_mod.TokenRepository(make_settings())

        async def _put_then_read() -> Any:
            ok = await repo.put(UID, "spotify", {"ciphertext": SECRET})
            return ok, fs_mod.last_failure()

        ok, failure = run_async(_put_then_read())

        assert ok is True
        assert failure is None


class TestVaultSurfacesTheCause:
    """`TokenVaultError` alone said nothing. It should now carry the reason."""

    @pytest.mark.parametrize("exc_cls,message", BACKEND_FAILURES)
    def test_token_vault_error_chains_the_backend_failure(
        self, exc_cls: type[Exception], message: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install_failing_backend(monkeypatch, exc_cls(message))
        settings = make_settings(token_encryption_key=tok_mod.generate_key())
        vault = tok_mod.FirestoreTokenVault(settings)

        with pytest.raises(tok_mod.TokenVaultError) as caught:
            run_async(vault.put(UID, "spotify", {"refresh_token": SECRET}))

        cause = caught.value.__cause__
        assert isinstance(cause, exc_cls)
        assert message in str(cause)
        # The exception the user's request sees stays terse and honest.
        assert str(caught.value) == "could not persist spotify credentials"
        assert SECRET not in str(caught.value)

    @pytest.mark.parametrize("exc_cls,message", BACKEND_FAILURES)
    def test_vault_logs_provider_and_document_without_the_payload(
        self,
        exc_cls: type[Exception],
        message: str,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        install_failing_backend(monkeypatch, exc_cls(message))
        settings = make_settings(token_encryption_key=tok_mod.generate_key())
        vault = tok_mod.FirestoreTokenVault(settings)

        # ERROR, not DEBUG: the vault's own INFO "sealed ... for uid=..." line
        # names the raw uid on purpose -- that is this module's documented
        # convention -- and it is not what this test is about. The *failure*
        # path is, and it must stay fingerprinted.
        with caplog.at_level(logging.ERROR, logger=TOK_LOGGER):
            with pytest.raises(tok_mod.TokenVaultError):
                run_async(vault.put(UID, "spotify", {"refresh_token": SECRET}))

        vault_lines = [
            r.getMessage() for r in caplog.records if r.name == TOK_LOGGER
        ]
        assert any(
            "provider=spotify" in line
            and fs_mod.token_doc_path(UID, "spotify") in line
            and exc_cls.__name__ in line
            for line in vault_lines
        ), vault_lines
        assert SECRET not in caplog.text
        assert UID not in caplog.text

    def test_a_repository_without_diagnostics_still_raises_cleanly(self) -> None:
        """A fake repo that just says ``False`` must not break the error path."""

        class _MuteRepo:
            async def put(self, *args: Any, **kwargs: Any) -> bool:
                return False

        settings = make_settings(token_encryption_key=tok_mod.generate_key())
        vault = tok_mod.FirestoreTokenVault(settings, repo=_MuteRepo())

        with pytest.raises(tok_mod.TokenVaultError) as caught:
            run_async(vault.put(UID, "spotify", {"refresh_token": SECRET}))

        assert str(caught.value) == "could not persist spotify credentials"

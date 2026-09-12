"""Platform-layer tests for Barogroove.

Hard constraints on this file:

* **No network.** Nothing here resolves DNS, opens a socket, or reaches
  Google. The Firestore client is never constructed; the auth module's cert
  fetch is never exercised.
* **No credentials.** Not an ADC file, not an emulator, not a service-account
  key. Everything runs in a bare venv with ``pydantic pytest fastapi
  pydantic-settings cryptography pyjwt``.
* **No Firebase emulator.** The security rules are checked structurally, as
  text. That is weaker than an emulator test and it is stated as such -- but a
  structural check that runs in two seconds on every commit catches the
  regression that matters (somebody writes ``allow read, write: if true``) and
  an emulator test that nobody runs catches nothing.

The security assertions in :class:`TestDevTokenGate` are the reason this file
exists. Read those first.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Path setup: tests/ is a sibling of backend/, and the package root is
# backend/, so `app.firebase.auth` resolves.
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
FIREBASE_CFG = REPO_ROOT / "firebase_cfg"
DEPLOY = REPO_ROOT / "deploy"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.firebase import auth as auth_mod  # noqa: E402
from app.firebase import firestore as fs_mod  # noqa: E402
from app.firebase import tokens as tok_mod  # noqa: E402

MODULES_UNDER_TEST = [
    "app.firebase.auth",
    "app.firebase.firestore",
    "app.firebase.tokens",
    "app.almanac.firestore_store",
    "app.routes.almanac",
]


# ---------------------------------------------------------------------------
# Fake settings. Deliberately a plain namespace rather than the real Settings:
# these modules access settings by `getattr(..., default)` precisely so they
# can be exercised without pydantic-settings and without an environment.
# ---------------------------------------------------------------------------


def make_settings(**overrides: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "environment": "local",
        "public_host": "bg.netdev.be",
        "gcp_project": "",
        "gcp_region": "europe-west1",
        "use_secret_manager": False,
        "firebase_project_id": "",
        "firebase_web_api_key": "",
        "firestore_database": "(default)",
        "auth_allow_insecure_dev_tokens": True,
        "token_encryption_key": "",
        "has_firestore": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def run_async(coro: Any) -> Any:
    return asyncio.run(coro)


# ===========================================================================
# SECURITY: the dev-token escape hatch
#
# `dev:<uid>` bypasses signature verification entirely. It exists so a
# developer can curl the API without a Firebase project. It must be impossible
# anywhere else. Two independent gates; both have to be open.
# ===========================================================================


class TestDevTokenGate:
    def test_accepted_in_local_with_flag_on(self) -> None:
        """The one configuration where it is allowed to work."""
        settings = make_settings(
            environment="local", auth_allow_insecure_dev_tokens=True
        )
        user = run_async(auth_mod.verify_bearer_token("dev:jerome", settings))

        assert user.uid == "jerome"
        assert user.is_dev is True, "synthetic identities must be labelled as such"
        assert user.provider == "dev"

    @pytest.mark.parametrize("environment", ["prod", "dev", "staging", "PROD", ""])
    def test_refused_outside_local_even_with_flag_on(self, environment: str) -> None:
        """SECURITY ASSERTION.

        A stale ``BG_AUTH_ALLOW_INSECURE_DEV_TOKENS=true`` in a config map must
        not open the door. The environment gate alone has to hold. Note that
        ``"PROD"`` is included: the comparison is against the exact literal
        ``"local"``, so any other spelling -- including a case variant of a
        real environment name -- fails closed.
        """
        settings = make_settings(
            environment=environment, auth_allow_insecure_dev_tokens=True
        )

        assert auth_mod.dev_tokens_enabled(settings) is False

        with pytest.raises(auth_mod.AuthError):
            run_async(auth_mod.verify_bearer_token("dev:attacker", settings))

    def test_refused_in_local_with_flag_off(self) -> None:
        """SECURITY ASSERTION.

        The flag gate alone has to hold too. Turning it off on a laptop must
        actually turn it off.
        """
        settings = make_settings(
            environment="local", auth_allow_insecure_dev_tokens=False
        )

        assert auth_mod.dev_tokens_enabled(settings) is False

        with pytest.raises(auth_mod.AuthError):
            run_async(auth_mod.verify_bearer_token("dev:attacker", settings))

    def test_refused_when_both_gates_shut(self) -> None:
        settings = make_settings(
            environment="prod", auth_allow_insecure_dev_tokens=False
        )
        with pytest.raises(auth_mod.AuthError):
            run_async(auth_mod.verify_bearer_token("dev:attacker", settings))

    def test_gate_defaults_closed_on_a_settings_object_with_nothing_set(self) -> None:
        """An object missing both attributes must not be treated as permissive."""
        assert auth_mod.dev_tokens_enabled(SimpleNamespace()) is False

    def test_rejection_message_does_not_reveal_which_gate_is_shut(self) -> None:
        """Probing prod should not tell an attacker how close they are."""
        settings = make_settings(
            environment="prod", auth_allow_insecure_dev_tokens=True
        )
        with pytest.raises(auth_mod.AuthError) as excinfo:
            run_async(auth_mod.verify_bearer_token("dev:x", settings))

        detail = str(excinfo.value).lower()
        for leak in ("environment", "flag", "local", "insecure_dev"):
            assert leak not in detail, f"rejection message leaks {leak!r}"

    def test_malformed_dev_token_refused_even_in_local(self) -> None:
        settings = make_settings()
        with pytest.raises(auth_mod.AuthError):
            run_async(auth_mod.verify_bearer_token("dev:", settings))
        with pytest.raises(auth_mod.AuthError):
            run_async(auth_mod.verify_bearer_token("dev:" + "x" * 200, settings))

    def test_dev_acceptance_logs_a_warning(self, caplog: Any) -> None:
        """A silent bypass is a bypass nobody notices."""
        settings = make_settings()
        with caplog.at_level("WARNING", logger="barogroove.firebase.auth"):
            run_async(auth_mod.verify_bearer_token("dev:noisy", settings))

        assert any(
            "INSECURE DEV TOKEN" in rec.getMessage() for rec in caplog.records
        ), "accepting a dev token must log loudly"

    def test_real_token_without_project_id_is_refused(self) -> None:
        """No project id means no audience check. Refuse rather than guess.

        Also proves the non-dev path never reaches the network in these tests:
        it bails on configuration before any cert fetch.
        """
        settings = make_settings(
            environment="prod", firebase_project_id="", gcp_project=""
        )
        with pytest.raises(auth_mod.AuthError) as excinfo:
            run_async(auth_mod.verify_bearer_token("eyJhbGciOiJSUzI1NiJ9.x.y", settings))
        assert excinfo.value.status_code == 503


class TestBearerParsing:
    @pytest.mark.parametrize(
        "header,expected",
        [
            ("Bearer abc123", "abc123"),
            ("bearer abc123", "abc123"),
            ("BEARER   abc123", "abc123"),
            ("  Bearer abc123  ", "abc123"),
            (None, None),
            ("", None),
            ("abc123", None),
            ("Basic abc123", None),
            ("Bearer", None),
            ("Bearer   ", None),
        ],
    )
    def test_extract(self, header: str | None, expected: str | None) -> None:
        assert auth_mod.extract_bearer_token(header) == expected


class TestAuthUser:
    def test_display_name_prefers_name_then_email_then_uid(self) -> None:
        assert auth_mod.AuthUser(uid="u", name="Jerome").display_name == "Jerome"
        assert auth_mod.AuthUser(uid="u", email="j@x.be").display_name == "j@x.be"
        assert auth_mod.AuthUser(uid="u").display_name == "u"

    def test_claims_mapping_reads_sign_in_provider(self) -> None:
        user = auth_mod._user_from_claims(
            {
                "sub": "abc",
                "email": "j@x.be",
                "name": "Jerome",
                "picture": "https://x/p.png",
                "firebase": {"sign_in_provider": "google.com"},
            }
        )
        assert (user.uid, user.provider, user.is_dev) == ("abc", "google.com", False)


# ===========================================================================
# Token vault
# ===========================================================================


class TestTokenVault:
    PAYLOAD = {
        "access_token": "not-a-real-token-just-a-fixture",
        "refresh_token": "also-fake",
        "expires_at": 1893456000,
        "scope": "playlist-modify-private",
    }

    def test_round_trip_with_a_generated_fernet_key(self) -> None:
        key = tok_mod.generate_key()
        vault = tok_mod.MemoryTokenVault(make_settings(token_encryption_key=key))

        run_async(vault.put("jerome", "spotify", self.PAYLOAD))
        assert run_async(vault.get("jerome", "spotify")) == self.PAYLOAD

    def test_stored_envelope_is_actually_encrypted(self) -> None:
        """The payload must not be recoverable from the stored bytes."""
        key = tok_mod.generate_key()
        settings = make_settings(token_encryption_key=key)
        vault = tok_mod.MemoryTokenVault(settings)
        run_async(vault.put("jerome", "spotify", self.PAYLOAD))

        envelope = vault._store[("jerome", "spotify")]
        assert envelope["encryption"] == tok_mod.ENC_FERNET
        assert "insecure_payload" not in envelope

        blob = json.dumps(envelope, default=str)
        assert "not-a-real-token-just-a-fixture" not in blob
        assert "also-fake" not in blob
        assert envelope["ciphertext"].startswith("gAAAAA")  # Fernet v1 prefix

    def test_key_id_is_a_fingerprint_not_the_key(self) -> None:
        key = tok_mod.generate_key()
        vault = tok_mod.MemoryTokenVault(make_settings(token_encryption_key=key))
        run_async(vault.put("u", "spotify", {"a": 1}))

        key_id = vault._store[("u", "spotify")]["key_id"]
        assert len(key_id) == 8
        assert key_id not in key and key[:8] != key_id

    def test_wrong_key_yields_none_not_garbage(self) -> None:
        """Rotating the key must fail closed, not return corrupt data."""
        vault_a = tok_mod.MemoryTokenVault(
            make_settings(token_encryption_key=tok_mod.generate_key())
        )
        run_async(vault_a.put("u", "spotify", self.PAYLOAD))
        envelope = vault_a._store[("u", "spotify")]

        vault_b = tok_mod.MemoryTokenVault(
            make_settings(token_encryption_key=tok_mod.generate_key())
        )
        vault_b._store[("u", "spotify")] = envelope

        assert run_async(vault_b.get("u", "spotify")) is None

    def test_tampered_ciphertext_yields_none(self) -> None:
        key = tok_mod.generate_key()
        vault = tok_mod.MemoryTokenVault(make_settings(token_encryption_key=key))
        run_async(vault.put("u", "spotify", self.PAYLOAD))

        envelope = vault._store[("u", "spotify")]
        envelope["ciphertext"] = envelope["ciphertext"][:-6] + "AAAAAA"

        assert run_async(vault.get("u", "spotify")) is None

    def test_refuses_to_pretend_plaintext_is_encrypted(self) -> None:
        """SECURITY ASSERTION.

        With no key in local mode the vault still stores, but it must NOT
        write the payload into a field called ``ciphertext`` and claim
        ``encryption: fernet``. The marker has to say what actually happened.
        """
        vault = tok_mod.MemoryTokenVault(
            make_settings(environment="local", token_encryption_key="")
        )
        run_async(vault.put("u", "spotify", self.PAYLOAD))

        envelope = vault._store[("u", "spotify")]
        assert envelope["encryption"] == tok_mod.ENC_INSECURE
        assert envelope["encryption"] != tok_mod.ENC_FERNET
        assert "ciphertext" not in envelope, "unencrypted data must not look encrypted"
        assert envelope["insecure_payload"] == self.PAYLOAD
        assert envelope["key_id"] == "none"

        # It still round-trips, so local development works.
        assert run_async(vault.get("u", "spotify")) == self.PAYLOAD

    def test_insecure_storage_warns_loudly(self, caplog: Any) -> None:
        vault = tok_mod.MemoryTokenVault(
            make_settings(environment="local", token_encryption_key="")
        )
        with caplog.at_level("WARNING", logger="barogroove.firebase.tokens"):
            run_async(vault.put("u", "spotify", self.PAYLOAD))

        messages = " ".join(rec.getMessage() for rec in caplog.records)
        assert "WITHOUT ENCRYPTION" in messages
        assert "CLEARTEXT" in messages

    @pytest.mark.parametrize("environment", ["dev", "prod"])
    def test_missing_key_outside_local_refuses_to_store(self, environment: str) -> None:
        """SECURITY ASSERTION.

        No key and not local: raise. Never quietly write credentials in clear.
        """
        vault = tok_mod.MemoryTokenVault(
            make_settings(environment=environment, token_encryption_key="")
        )
        with pytest.raises(Exception) as excinfo:
            run_async(vault.put("u", "spotify", self.PAYLOAD))

        assert "encryption" in str(excinfo.value).lower()

    def test_insecure_envelope_is_refused_outside_local(self) -> None:
        """SECURITY ASSERTION.

        A plaintext envelope that somehow reaches prod -- restored backup,
        copied database, promoted emulator data -- must not be read.
        """
        local_vault = tok_mod.MemoryTokenVault(
            make_settings(environment="local", token_encryption_key="")
        )
        run_async(local_vault.put("u", "spotify", self.PAYLOAD))
        envelope = local_vault._store[("u", "spotify")]

        prod_vault = tok_mod.MemoryTokenVault(
            make_settings(environment="prod", token_encryption_key="")
        )
        prod_vault._store[("u", "spotify")] = envelope

        assert run_async(prod_vault.get("u", "spotify")) is None

    def test_unknown_encryption_marker_is_refused(self) -> None:
        vault = tok_mod.MemoryTokenVault(
            make_settings(token_encryption_key=tok_mod.generate_key())
        )
        vault._store[("u", "spotify")] = {
            "encryption": "rot13-obviously",
            "ciphertext": "whatever",
        }
        assert run_async(vault.get("u", "spotify")) is None

    def test_full_interface(self) -> None:
        vault = tok_mod.MemoryTokenVault(
            make_settings(token_encryption_key=tok_mod.generate_key())
        )

        assert run_async(vault.get("u", "spotify")) is None
        assert run_async(vault.providers("u")) == []

        run_async(vault.put("u", "spotify", {"a": 1}))
        run_async(vault.put("u", "lastfm", {"b": 2}))
        assert run_async(vault.providers("u")) == ["lastfm", "spotify"]

        run_async(vault.delete("u", "spotify"))
        assert run_async(vault.providers("u")) == ["lastfm"]
        run_async(vault.delete("u", "spotify"))  # idempotent

    def test_users_are_isolated(self) -> None:
        vault = tok_mod.MemoryTokenVault(
            make_settings(token_encryption_key=tok_mod.generate_key())
        )
        run_async(vault.put("alice", "spotify", {"who": "alice"}))
        assert run_async(vault.get("bob", "spotify")) is None
        assert run_async(vault.providers("bob")) == []

    @pytest.mark.parametrize("bad", ["", "   ", "a/b", "x" * 200])
    def test_path_traversal_and_oversize_ids_refused(self, bad: str) -> None:
        vault = tok_mod.MemoryTokenVault(
            make_settings(token_encryption_key=tok_mod.generate_key())
        )
        with pytest.raises(tok_mod.TokenVaultError):
            run_async(vault.put(bad, "spotify", {"a": 1}))
        with pytest.raises(tok_mod.TokenVaultError):
            run_async(vault.put("u", bad, {"a": 1}))

    def test_oversize_payload_refused(self) -> None:
        vault = tok_mod.MemoryTokenVault(
            make_settings(token_encryption_key=tok_mod.generate_key())
        )
        huge = {"blob": "x" * (tok_mod.MAX_PAYLOAD_BYTES + 1)}
        with pytest.raises(tok_mod.TokenVaultError):
            run_async(vault.put("u", "spotify", huge))

    def test_invalid_fernet_key_raises_rather_than_downgrading(self) -> None:
        """A malformed key must not silently fall back to plaintext."""
        vault = tok_mod.MemoryTokenVault(
            make_settings(environment="local", token_encryption_key="not-a-fernet-key")
        )
        with pytest.raises(Exception):
            run_async(vault.put("u", "spotify", {"a": 1}))

    def test_both_implementations_satisfy_the_protocol(self) -> None:
        settings = make_settings(token_encryption_key=tok_mod.generate_key())
        assert isinstance(tok_mod.MemoryTokenVault(settings), tok_mod.TokenVault)
        assert isinstance(tok_mod.FirestoreTokenVault(settings), tok_mod.TokenVault)

    def test_builder_picks_memory_without_firestore(self) -> None:
        vault = tok_mod.build_token_vault(make_settings(has_firestore=False))
        assert isinstance(vault, tok_mod.MemoryTokenVault)


# ===========================================================================
# Firestore converters -- no client, no network
# ===========================================================================


class TestConverters:
    def test_tuples_become_lists(self) -> None:
        out = fs_mod.firestore_safe({"t": (1, 2, 3)})
        assert out == {"t": [1, 2, 3]} and isinstance(out["t"], list)

    def test_sets_become_lists(self) -> None:
        assert sorted(fs_mod.firestore_safe({"s": {"b", "a"}})["s"]) == ["a", "b"]

    def test_nested_arrays_are_rejected_with_a_useful_message(self) -> None:
        with pytest.raises(ValueError, match="nested arrays"):
            fs_mod.firestore_safe({"m": [[1.0, 2.0], [3.0, 4.0]]})

    def test_naive_datetimes_are_coerced_to_utc(self) -> None:
        from datetime import datetime, timezone

        out = fs_mod.firestore_safe({"t": datetime(2026, 1, 1, 12, 0, 0)})
        assert out["t"].tzinfo is not None
        assert out["t"].utcoffset() == timezone.utc.utcoffset(None)

    def test_matrix_round_trip(self) -> None:
        matrix = [
            [float(r * fs_mod.MATRIX_COLS + c) for c in range(fs_mod.MATRIX_COLS)]
            for r in range(fs_mod.MATRIX_ROWS)
        ]
        encoded = fs_mod.encode_matrix(matrix)

        assert encoded["rows"] == 9 and encoded["cols"] == 7
        assert len(encoded["values"]) == 63
        assert all(not isinstance(v, list) for v in encoded["values"])  # flat
        assert fs_mod.decode_matrix(encoded) == matrix

    def test_encoded_matrix_is_firestore_safe(self) -> None:
        """The flat form must survive the very check that rejects nested arrays."""
        matrix = [[0.0] * 7 for _ in range(9)]
        fs_mod.firestore_safe({"delta": fs_mod.encode_matrix(matrix)})

    def test_ragged_matrix_refused(self) -> None:
        with pytest.raises(ValueError, match="ragged"):
            fs_mod.encode_matrix([[1.0, 2.0], [3.0]])

    @pytest.mark.parametrize(
        "blob",
        [None, {}, {"rows": 9, "cols": 7, "values": [1.0]}, {"rows": 0, "cols": 0}],
    )
    def test_malformed_matrix_decodes_to_none(self, blob: Any) -> None:
        assert fs_mod.decode_matrix(blob) is None

    @pytest.mark.parametrize("bad", ["", "   ", ".", "..", "a/b", "x" * 2000])
    def test_bad_document_ids_refused(self, bad: str) -> None:
        with pytest.raises(ValueError):
            fs_mod.safe_doc_id(bad)

    def test_clamp_text(self) -> None:
        assert fs_mod.clamp_text(None) is None
        assert len(fs_mod.clamp_text("x" * 99999) or "") == fs_mod.MAX_STRING_LEN

    def test_matrix_dimensions_match_the_contracts(self) -> None:
        assert fs_mod.MATRIX_ROWS == 9, "SkyVector is 9-dimensional"
        assert fs_mod.MATRIX_COLS == 7, "SonicVector is 7-dimensional"


class TestClientLaziness:
    def test_get_client_refuses_without_firestore_and_never_touches_network(self) -> None:
        with pytest.raises(fs_mod.FirestoreUnavailable):
            run_async(fs_mod.get_client(make_settings(has_firestore=False)))

    def test_repositories_construct_without_credentials(self) -> None:
        repos = fs_mod.build_repositories(make_settings())
        for name in ("users", "forges", "feedback", "nudges", "tokens"):
            assert hasattr(repos, name)

    def test_healthcheck_reports_rather_than_raises(self) -> None:
        result = run_async(fs_mod.build_repositories(make_settings()).healthcheck())
        assert result["reachable"] is False
        assert isinstance(result["detail"], str) and result["detail"]

    def test_google_cloud_is_not_imported_at_module_scope(self) -> None:
        """Importing our modules must not drag in gRPC."""
        source = (BACKEND_ROOT / "app" / "firebase" / "firestore.py").read_text()
        top_level = [
            line
            for line in source.splitlines()
            if re.match(r"^(import|from)\s+(google|firebase_admin)", line)
        ]
        assert not top_level, f"module-scope google import(s): {top_level}"


class TestAlmanacStore:
    def test_constructs_and_degrades_without_firestore(self) -> None:
        from app.almanac.firestore_store import FirestoreAlmanac

        store = FirestoreAlmanac(make_settings(has_firestore=False))

        assert run_async(store.nudge("u")) is None
        assert run_async(store.history("u")) == []
        assert run_async(store.feedback_rows("u")) == []
        run_async(store.record_feedback(
            user_id="u", playlist_id="p", track_key="t", signal="loved"
        ))  # must not raise

    def test_satisfies_the_almanac_store_protocol_shape(self) -> None:
        from app.almanac.firestore_store import FirestoreAlmanac

        store = FirestoreAlmanac(make_settings())
        for method in ("record_forge", "record_feedback", "history", "nudge"):
            assert callable(getattr(store, method))


# ===========================================================================
# firestore.rules -- structural / text checks (no emulator)
# ===========================================================================


class TestFirestoreRules:
    @staticmethod
    @pytest.fixture(scope="class")
    def rules() -> str:
        path = FIREBASE_CFG / "firestore.rules"
        assert path.is_file(), f"missing {path}"
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _strip_comments(text: str) -> str:
        return "\n".join(line.split("//", 1)[0] for line in text.splitlines())

    def test_declares_rules_version_2(self, rules: str) -> None:
        assert re.search(r"^rules_version\s*=\s*'2'\s*;", rules, re.MULTILINE)

    def test_has_a_cloud_firestore_service_block(self, rules: str) -> None:
        assert "service cloud.firestore" in rules
        assert "match /databases/{database}/documents" in rules

    def test_delimiters_balance(self, rules: str) -> None:
        """The cheapest real syntax check available without the emulator."""
        code = self._strip_comments(rules)
        assert code.count("{") == code.count("}"), "unbalanced braces"
        assert code.count("(") == code.count(")"), "unbalanced parentheses"
        assert code.count("[") == code.count("]"), "unbalanced brackets"

    def test_every_allow_statement_is_terminated(self, rules: str) -> None:
        code = self._strip_comments(rules)
        for stmt in re.findall(r"allow\s+[^;{}]*", code):
            assert stmt.strip(), "empty allow statement"
        # Every `allow` keyword must be followed by a `;` before the block ends.
        for match in re.finditer(r"\ballow\b", code):
            tail = code[match.start():]
            semi = tail.find(";")
            brace = tail.find("}")
            assert semi != -1 and (brace == -1 or semi < brace), (
                "an allow statement is not terminated with ';'"
            )

    def test_allow_verbs_are_all_valid(self, rules: str) -> None:
        valid = {"read", "write", "get", "list", "create", "update", "delete"}
        code = self._strip_comments(rules)
        for verbs in re.findall(r"allow\s+([a-z,\s]+?):", code):
            for verb in verbs.split(","):
                assert verb.strip() in valid, f"unknown rule verb {verb.strip()!r}"

    def test_no_unconditional_allow(self, rules: str) -> None:
        """SECURITY ASSERTION. `if true` in a rules file is a data breach."""
        code = self._strip_comments(rules)
        assert not re.search(r"allow[^;]*:\s*if\s+true\s*;", code)
        assert not re.search(r"allow\s+read\s*,\s*write\s*;", code)

    def test_ends_with_a_default_deny(self, rules: str) -> None:
        code = self._strip_comments(rules)
        assert "match /{document=**}" in code
        tail = code[code.index("match /{document=**}"):]
        assert re.search(r"allow\s+read\s*,\s*write:\s*if\s+false\s*;", tail)

    def test_tokens_are_never_client_readable(self, rules: str) -> None:
        """SECURITY ASSERTION. The single most important line in the file."""
        code = self._strip_comments(rules)
        match = re.search(
            r"match\s+/tokens/\{provider\}\s*\{(.*?)\}", code, re.DOTALL
        )
        assert match, "no rule block for users/{uid}/tokens/{provider}"
        body = match.group(1)
        assert re.search(r"allow\s+read\s*,\s*write:\s*if\s+false\s*;", body)
        assert "request.auth" not in body, "tokens must be denied unconditionally"

    def test_no_recursive_wildcard_under_users(self, rules: str) -> None:
        """A `/users/{uid}/{doc=**}` rule would silently re-expose tokens."""
        code = self._strip_comments(rules)
        assert "/users/{userId}/{document=**}" not in code
        assert not re.search(r"match\s+/users/\{[a-zA-Z]+\}/\{[a-zA-Z]+=\*\*\}", code)

    def test_public_sharing_requires_an_explicit_boolean_flag(self, rules: str) -> None:
        code = self._strip_comments(rules)
        assert "resource.data.public == true" in code
        assert "request.resource.data.public == false" in code

    def test_almanac_delta_is_backend_write_only(self, rules: str) -> None:
        """A client-written personalisation matrix is an arbitrary-behaviour bug."""
        code = self._strip_comments(rules)
        match = re.search(r"match\s+/almanac/\{userId\}\s*\{(.*?)\n    \}", code, re.DOTALL)
        assert match, "no rule block for almanac/{userId}"
        assert re.search(r"allow\s+write:\s*if\s+false\s*;", match.group(1))

    def test_feedback_is_append_only(self, rules: str) -> None:
        code = self._strip_comments(rules)
        match = re.search(r"match\s+/feedback/\{feedbackId\}\s*\{(.*?)\n    \}", code, re.DOTALL)
        assert match
        assert re.search(r"allow\s+update\s*,\s*delete:\s*if\s+false\s*;", match.group(1))

    def test_signal_enum_is_constrained(self, rules: str) -> None:
        assert "in ['loved', 'skipped']" in rules

    def test_track_cap_matches_the_python_constant(self, rules: str) -> None:
        """Rules and code must agree, or one of them is decorative."""
        assert f"tracks.size() <= {fs_mod.MAX_TRACKS_PER_FORGE}" in rules

    def test_every_rule_block_is_commented(self, rules: str) -> None:
        """Each collection block must carry a threat comment above it."""
        lines = rules.splitlines()
        for i, line in enumerate(lines):
            if re.match(r"\s*match\s+/(users|forges|feedback|almanac)/", line):
                window = "\n".join(lines[max(0, i - 30):i])
                assert "//" in window, f"uncommented rule block at line {i + 1}"


# ===========================================================================
# JSON configuration
# ===========================================================================


class TestFirebaseJson:
    @staticmethod
    @pytest.fixture(scope="class")
    def cfg() -> dict[str, Any]:
        path = FIREBASE_CFG / "firebase.json"
        assert path.is_file(), f"missing {path}"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_is_valid_json_with_the_expected_top_level_keys(self, cfg: dict) -> None:
        for key in ("hosting", "firestore", "emulators"):
            assert key in cfg

    def test_serves_the_flutter_web_build(self, cfg: dict) -> None:
        assert cfg["hosting"]["public"] == "frontend/build/web"

    def test_api_mcp_and_legacy_rewrite_to_cloud_run_in_europe_west1(
        self, cfg: dict
    ) -> None:
        rewrites = cfg["hosting"]["rewrites"]
        by_source = {r["source"]: r for r in rewrites}

        for source in ("/api/**", "/mcp", "/mcp/**", "/legacy"):
            assert source in by_source, f"no rewrite for {source}"
            run = by_source[source].get("run")
            assert run, f"{source} must rewrite to Cloud Run"
            assert run["serviceId"] == "barogroove-api"
            # Region is not optional for us: Firebase defaults to us-central1
            # when it is omitted, which would point the rewrite at nothing.
            assert run["region"] == "europe-west1", f"{source} must target europe-west1"

    def test_spa_fallback_is_last(self, cfg: dict) -> None:
        """Order matters: `**` before `/api/**` returns index.html for API calls."""
        rewrites = cfg["hosting"]["rewrites"]
        assert rewrites[-1]["source"] == "**"
        assert rewrites[-1]["destination"] == "/index.html"
        assert "run" not in rewrites[-1]

        sources = [r["source"] for r in rewrites]
        for source in ("/api/**", "/mcp", "/mcp/**", "/legacy"):
            assert sources.index(source) < sources.index("**")

    def test_hashed_assets_are_immutable_and_index_is_not_cached(self, cfg: dict) -> None:
        headers = cfg["hosting"]["headers"]

        def value(source: str, key: str) -> str | None:
            for block in headers:
                if block["source"] == source:
                    for header in block["headers"]:
                        if header["key"] == key:
                            return header["value"]
            return None

        immutable = value("/assets/**", "Cache-Control")
        assert immutable and "immutable" in immutable and "31536000" in immutable

        index = value("/index.html", "Cache-Control")
        assert index and "no-cache" in index

    def test_security_headers_present(self, cfg: dict) -> None:
        catch_all = [b for b in cfg["hosting"]["headers"] if b["source"] == "**"]
        assert catch_all, "no catch-all header block"
        keys = {h["key"] for h in catch_all[0]["headers"]}
        for required in (
            "X-Content-Type-Options",
            "X-Frame-Options",
            "Referrer-Policy",
            "Strict-Transport-Security",
            "Content-Security-Policy",
        ):
            assert required in keys, f"missing security header {required}"

    def test_firestore_config_points_at_our_files(self, cfg: dict) -> None:
        assert cfg["firestore"]["rules"] == "firestore.rules"
        assert cfg["firestore"]["indexes"] == "firestore.indexes.json"
        assert (FIREBASE_CFG / cfg["firestore"]["rules"]).is_file()
        assert (FIREBASE_CFG / cfg["firestore"]["indexes"]).is_file()

    def test_emulator_suite_wired_for_auth_firestore_hosting(self, cfg: dict) -> None:
        emulators = cfg["emulators"]
        for name in ("auth", "firestore", "hosting"):
            assert name in emulators, f"no {name} emulator configured"
            assert isinstance(emulators[name]["port"], int)

        ports = [emulators[n]["port"] for n in ("auth", "firestore", "hosting")]
        assert len(set(ports)) == len(ports), "emulator port collision"


class TestFirebaseRc:
    def test_example_is_valid_json_with_project_aliases(self) -> None:
        path = FIREBASE_CFG / ".firebaserc.example"
        assert path.is_file()
        cfg = json.loads(path.read_text(encoding="utf-8"))
        assert "projects" in cfg and "default" in cfg["projects"]

    def test_the_real_firebaserc_is_not_committed(self) -> None:
        assert not (FIREBASE_CFG / ".firebaserc").exists(), (
            ".firebaserc names real infrastructure; only the .example belongs in git"
        )


class TestFirestoreIndexes:
    @staticmethod
    @pytest.fixture(scope="class")
    def cfg() -> dict[str, Any]:
        path = FIREBASE_CFG / "firestore.indexes.json"
        assert path.is_file(), f"missing {path}"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_is_valid_json_with_an_indexes_array(self, cfg: dict) -> None:
        assert isinstance(cfg.get("indexes"), list) and cfg["indexes"]

    def test_every_index_is_well_formed(self, cfg: dict) -> None:
        for index in cfg["indexes"]:
            assert index["queryScope"] in {"COLLECTION", "COLLECTION_GROUP"}
            assert index["collectionGroup"]
            assert len(index["fields"]) >= 2, "single-field indexes are automatic"
            for field in index["fields"]:
                assert field["fieldPath"]
                assert field["order"] in {"ASCENDING", "DESCENDING"}

    def _shapes(self, cfg: dict) -> set[tuple[str, tuple[tuple[str, str], ...]]]:
        return {
            (
                index["collectionGroup"],
                tuple((f["fieldPath"], f["order"]) for f in index["fields"]),
            )
            for index in cfg["indexes"]
        }

    def test_user_forges_by_created_at_desc(self, cfg: dict) -> None:
        assert (
            "forges",
            (("user_id", "ASCENDING"), ("created_at", "DESCENDING")),
        ) in self._shapes(cfg)

    def test_user_theme_forges_by_created_at_desc(self, cfg: dict) -> None:
        assert (
            "forges",
            (
                ("user_id", "ASCENDING"),
                ("theme_id", "ASCENDING"),
                ("created_at", "DESCENDING"),
            ),
        ) in self._shapes(cfg)

    def test_feedback_by_user_and_playlist(self, cfg: dict) -> None:
        shapes = self._shapes(cfg)
        assert any(
            group == "feedback"
            and fields[0] == ("user_id", "ASCENDING")
            and ("playlist_id", "ASCENDING") in fields
            for group, fields in shapes
        )

    def test_collection_names_match_the_code(self, cfg: dict) -> None:
        known = {
            fs_mod.COL_FORGES,
            fs_mod.COL_FEEDBACK,
            fs_mod.COL_ALMANAC,
            fs_mod.COL_USERS,
            fs_mod.COL_SCROBBLES,
            fs_mod.COL_TRACK_CATALOG,
        }
        for index in cfg["indexes"]:
            assert index["collectionGroup"] in known

    def test_indexes_are_documented_in_the_readme(self, cfg: dict) -> None:
        """JSON has no comments, so the justification lives next door."""
        readme = (FIREBASE_CFG / "README.md").read_text(encoding="utf-8")
        for index in cfg["indexes"]:
            assert index["collectionGroup"] in readme
        assert "Why each composite index exists" in readme


# ===========================================================================
# Deployment configuration
# ===========================================================================


class TestCloudRunManifest:
    @staticmethod
    @pytest.fixture(scope="class")
    def manifest() -> str:
        path = DEPLOY / "cloudrun.yaml"
        assert path.is_file(), f"missing {path}"
        return path.read_text(encoding="utf-8")

    def test_is_a_knative_service(self, manifest: str) -> None:
        assert "apiVersion: serving.knative.dev/v1" in manifest
        assert "kind: Service" in manifest

    def test_targets_europe_west1(self, manifest: str) -> None:
        assert "europe-west1" in manifest
        assert "us-central1" not in manifest

    def test_probes_hit_healthz(self, manifest: str) -> None:
        assert "startupProbe" in manifest and "livenessProbe" in manifest
        assert manifest.count("path: /healthz") >= 2

    def test_scales_to_zero_with_the_tradeoff_written_down(self, manifest: str) -> None:
        assert 'autoscaling.knative.dev/minScale: "0"' in manifest
        assert "maxScale" in manifest
        assert "cold start" in manifest.lower(), (
            "min-scale 0 must be accompanied by a note on the cold-start cost"
        )

    def test_secrets_are_references_only(self, manifest: str) -> None:
        """SECURITY ASSERTION. Not one secret value in a checked-in manifest."""
        assert "secretKeyRef" in manifest
        assert "run.googleapis.com/secrets" in manifest
        assert ", bg-" not in manifest and ",\n" not in manifest.split("run.googleapis.com/secrets:")[1].split("\n\n")[0], (
            "run.googleapis.com/secrets annotation must not contain spaces or folded newlines after commas"
        )

        # Fernet keys are 44-char url-safe base64 ending in '='. If one ever
        # lands here, this catches it.
        assert not re.search(r"[A-Za-z0-9_\-]{43}=", manifest), (
            "something that looks like a Fernet key is in the manifest"
        )
        for leak in ("BEGIN PRIVATE KEY", "client_secret", "AIza"):
            assert leak not in manifest

    def test_runs_as_a_dedicated_service_account(self, manifest: str) -> None:
        assert "serviceAccountName: barogroove-api@" in manifest
        assert "compute@developer.gserviceaccount.com" not in manifest

    def test_resources_and_concurrency_are_set(self, manifest: str) -> None:
        assert "containerConcurrency:" in manifest
        assert "cpu:" in manifest and "memory:" in manifest
        assert "timeoutSeconds:" in manifest


class TestCloudBuild:
    def test_pipeline_targets_europe_west1_artifact_registry(self) -> None:
        text = (DEPLOY / "cloudbuild.yaml").read_text(encoding="utf-8")
        assert "_REGION: europe-west1" in text
        assert "docker.pkg.dev" in text
        assert "run" in text and "services" in text and "replace" in text
        assert "us-central1" not in text


class TestDeployScript:
    @staticmethod
    @pytest.fixture(scope="class")
    def script() -> str:
        path = DEPLOY / "deploy.sh"
        assert path.is_file(), f"missing {path}"
        return path.read_text(encoding="utf-8")

    def test_strict_mode(self, script: str) -> None:
        assert "set -euo pipefail" in script

    def test_has_a_dry_run_flag_and_a_preflight(self, script: str) -> None:
        assert "--dry-run" in script
        assert "DRY_RUN" in script
        assert "preflight" in script

    def test_region_is_hard_coded(self, script: str) -> None:
        assert 'readonly REGION="europe-west1"' in script
        assert "us-central1" not in script

    def test_no_hardcoded_secret_values(self, script: str) -> None:
        """SECURITY ASSERTION. The script prompts; it never carries values."""
        assert "--data-file=-" in script, "secrets must be piped over stdin"
        assert "read -rs" in script, "secret prompts must not echo"
        assert not re.search(r"--data=[\"']?\S", script), (
            "--data puts the secret in argv, which is world-readable via ps"
        )
        for leak in ("AIza", "BEGIN PRIVATE KEY", "sk_live_"):
            assert leak not in script

    def test_is_shell_syntax_valid(self, script: str) -> None:
        """Parse-only. `bash -n` never executes a single command."""
        result = subprocess.run(
            ["bash", "-n", str(DEPLOY / "deploy.sh")],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr

    def test_service_account_doc_exists_and_justifies_each_role(self) -> None:
        text = (DEPLOY / "service-account.md").read_text(encoding="utf-8")
        for role in (
            "roles/datastore.user",
            "roles/secretmanager.secretAccessor",
            "roles/logging.logWriter",
            "roles/iam.serviceAccountUser",
        ):
            assert role in text, f"{role} is granted but not documented"
        assert "roles/editor" in text, "must state which roles are forbidden"


# ===========================================================================
# .env.example
# ===========================================================================


class TestEnvExample:
    @staticmethod
    @pytest.fixture(scope="class")
    def text() -> str:
        path = REPO_ROOT / ".env.example"
        assert path.is_file(), f"missing {path}"
        return path.read_text(encoding="utf-8")

    def test_documents_every_setting_from_config(self, text: str) -> None:
        for key in (
            "BG_ENVIRONMENT",
            "BG_PUBLIC_HOST",
            "BG_GCP_PROJECT",
            "BG_GCP_REGION",
            "BG_USE_SECRET_MANAGER",
            "BG_FIREBASE_PROJECT_ID",
            "BG_FIREBASE_WEB_API_KEY",
            "BG_FIRESTORE_DATABASE",
            "BG_AUTH_ALLOW_INSECURE_DEV_TOKENS",
            "BG_TOKEN_ENCRYPTION_KEY",
        ):
            assert f"{key}=" in text, f"{key} is undocumented"

    def test_region_is_europe_west1(self, text: str) -> None:
        assert "BG_GCP_REGION=europe-west1" in text

    def test_says_the_app_boots_with_an_empty_environment(self, text: str) -> None:
        assert "EMPTY ENVIRONMENT" in text.upper()

    def test_secrets_are_placeholders_only(self, text: str) -> None:
        """SECURITY ASSERTION. A committed .env.example with a real key is a leak."""
        assert "sm://barogroove-" in text

        # Toggles that merely *mention* a secret subsystem without carrying a
        # credential. Everything else matching KEY/SECRET/TOKEN must be empty
        # or an sm:// reference.
        not_credentials = {"BG_USE_SECRET_MANAGER", "BG_AUTH_ALLOW_INSECURE_DEV_TOKENS"}

        checked = 0
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if not key.startswith("BG_") or key in not_credentials:
                continue
            if "KEY" in key or "SECRET" in key or "TOKEN" in key:
                checked += 1
                assert value == "" or value.startswith("sm://"), (
                    f"{key} must be empty or an sm:// reference, got {value!r}"
                )
        assert checked >= 4, "the credential-shaped settings are not being checked"

        # Nothing that looks like a real credential, anywhere.
        assert not re.search(r"AIza[0-9A-Za-z_\-]{35}", text)
        assert not re.search(r"[A-Za-z0-9_\-]{43}=\s*$", text, re.MULTILINE)
        assert "BEGIN PRIVATE KEY" not in text

    def test_every_setting_has_an_absent_behaviour_note(self, text: str) -> None:
        """'What happens when it is absent' is the whole point of this file."""
        assert text.count("Absent ->") >= 10


# ===========================================================================
# Import hygiene: empty environment, no credentials, no network
# ===========================================================================


class TestImportHygiene:
    def test_every_module_imports_in_a_pristine_subprocess(self) -> None:
        """Runs with an emptied environment in a fresh interpreter.

        A subprocess is used deliberately: by the time this test file runs, the
        modules are already imported and any environment side effect has
        happened. Only a clean process proves the claim.
        """
        script = (
            "import sys; sys.path.insert(0, %r)\n" % str(BACKEND_ROOT)
            + "".join(f"import {m}\n" for m in MODULES_UNDER_TEST)
            + "print('ok')\n"
        )

        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": "/nonexistent-barogroove-test-home",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        # Preserve the venv so the interpreter can find its own packages.
        for passthrough in ("VIRTUAL_ENV", "PYTHONPATH", "SYSTEMROOT"):
            if passthrough in os.environ:
                env[passthrough] = os.environ[passthrough]

        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"import failed with an empty environment:\n{result.stderr}"
        )
        assert "ok" in result.stdout

    def test_no_bg_environment_variables_are_required(self, monkeypatch) -> None:
        # The property under test is "the app boots with an empty environment",
        # not "this process happens to have a pristine environment" -- the
        # suite-wide conftest deliberately pins BG_* to offline mode. So clear
        # them here and prove Settings still constructs with working defaults.
        for key in [k for k in os.environ if k.startswith("BG_")]:
            monkeypatch.delenv(key, raising=False)

        from app.config import Settings

        settings = Settings()
        assert settings.environment == "local"
        assert settings.gcp_region == "europe-west1"
        assert settings.public_host == "bg.netdev.be"
        # With nothing configured, every optional subsystem must report absent
        # rather than raise.
        assert settings.capability_report()["lastfm"] is False
        assert settings.degraded_modes()

    def test_modules_use_future_annotations(self) -> None:
        for rel in (
            "app/firebase/auth.py",
            "app/firebase/firestore.py",
            "app/firebase/tokens.py",
            "app/almanac/firestore_store.py",
            "app/routes/almanac.py",
        ):
            source = (BACKEND_ROOT / rel).read_text(encoding="utf-8")
            assert "from __future__ import annotations" in source, rel

    def test_router_is_mounted_at_the_documented_prefix(self) -> None:
        from app.routes.almanac import router

        assert router.prefix == "/api/almanac"
        assert "almanac" in router.tags

        paths = {route.path for route in router.routes}
        for expected in (
            "/api/almanac/history",
            "/api/almanac/retrospective",
            "/api/almanac/feedback",
        ):
            assert expected in paths, f"missing route {expected}"

    def test_router_survives_a_missing_retrospective_module(self) -> None:
        """The Almanac worker's module is optional by contract."""
        from app.routes import almanac as almanac_routes

        assert almanac_routes._load_retrospective_builder() is None or callable(
            almanac_routes._load_retrospective_builder()
        )

    def test_fallback_retrospective_needs_no_dependencies(self) -> None:
        from datetime import datetime, timezone

        from app.routes.almanac import _fallback_retrospective

        assert _fallback_retrospective([]) == []

        rows = [
            SimpleNamespace(
                id="a",
                title="Grey Over Ghent",
                theme_id="drizzle",
                genre_id="ambient",
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            SimpleNamespace(
                id="b",
                title="Second Front",
                theme_id="drizzle",
                genre_id="dub",
                created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            ),
        ]
        keys = {h.key for h in _fallback_retrospective(rows)}
        assert {"first_forge", "signature_theme", "signature_genre"} <= keys


class TestPairingIntegration:
    def test_spotify_vault_adapter_encrypts_and_round_trips_tokens(self) -> None:
        from datetime import datetime, timedelta, timezone
        from app.routes.pairing import _SpotifyVaultAdapter
        from app.sinks.spotify_auth import SpotifyTokens

        key = tok_mod.generate_key()
        inner = tok_mod.MemoryTokenVault(make_settings(token_encryption_key=key))
        adapter = _SpotifyVaultAdapter(inner)

        now = datetime.now(timezone.utc)
        tokens = SpotifyTokens(
            access_token="secret-access-token",
            refresh_token="secret-refresh-token",
            scope="playlist-modify-private",
            expires_at=now + timedelta(hours=1),
        )
        run_async(adapter.put("uid-123", tokens))
        loaded = run_async(adapter.get("uid-123"))
        assert loaded is not None
        assert loaded.access_token == "secret-access-token"
        assert loaded.refresh_token == "secret-refresh-token"

        # Verify inner vault stored encrypted ciphertext
        envelope = inner._store[("uid-123", "spotify")]
        assert envelope["encryption"] == tok_mod.ENC_FERNET
        assert "secret-access-token" not in json.dumps(envelope, default=str)

    def test_placeholder_credentials_report_unconfigured(self) -> None:
        from app.config import Settings
        from app.sinks.spotify_auth import SpotifyAuth

        s = Settings(
            spotify_client_id="dev-placeholder-unconfigured",
            spotify_client_secret="dev-placeholder-unconfigured",
            lastfm_api_key="dev-placeholder-unconfigured",
        )
        assert not s.has_spotify
        assert not s.has_lastfm
        assert not SpotifyAuth(settings=s).configured


class TestFrontendSurfaceAndForgeIntegration:
    def test_sky_surface_works_without_query_params(self) -> None:
        from fastapi.testclient import TestClient
        from app.main import create_app

        client = TestClient(create_app())
        res = client.get("/api/surfaces/sky")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list) and len(data) == 3
        assert data[0]["createSurface"]["surfaceId"] == "sky"
        dims = data[2]["updateDataModel"]["contents"]["sky"]["dimensions"]
        assert len(dims) == 9

    def test_action_response_envelope_unwraps_and_shapes_forge(self) -> None:
        from fastapi.testclient import TestClient
        from app.main import create_app

        client = TestClient(create_app())
        res = client.post(
            "/api/surfaces/action",
            json={
                "actionResponse": {
                    "surfaceId": "themes-1",
                    "actionId": "barogroove.select_theme",
                    "payload": {"themeId": "petrichor"},
                }
            },
        )
        assert res.status_code == 200
        body = res.json()
        assert body[0]["updateDataModel"]["contents"]["selectedThemeId"] == "petrichor"

        # Forge with empty JSON body (as Flutter sends on default selection)
        forge_res = client.post("/api/forge", json={})
        assert forge_res.status_code == 200
        playlist = forge_res.json()["playlist"]
        assert playlist["theme_id"] == "petrichor"

    def test_show_almanac_action_returns_almanac_surface(self) -> None:
        from fastapi.testclient import TestClient
        from app.main import create_app

        client = TestClient(create_app())
        res = client.post(
            "/api/surfaces/action",
            json={
                "actionResponse": {
                    "surfaceId": "almanac",
                    "actionId": "showAlmanac",
                }
            },
        )
        assert res.status_code == 200
        body = res.json()
        assert body[0]["createSurface"]["surfaceId"] == "almanac"


class TestDemoModePairingFlow:
    def test_spotify_and_lastfm_start_return_200_and_complete_demo_pairing(self) -> None:
        from fastapi.testclient import TestClient
        from app.main import create_app

        client = TestClient(create_app())
        headers = {"X-Barogroove-User": "test_demo_user"}

        # 1. Start Spotify pairing in Demo Mode (unconfigured client_id) -> 200 OK (no 503)
        sp_start = client.post("/api/pair/spotify/start", headers=headers)
        assert sp_start.status_code == 200
        sp_data = sp_start.json()
        assert "/api/pair/spotify/demo-authorize?state=" in sp_data["authorize_url"]
        state_sp = sp_data["state"]

        # 2. Demo authorize screen renders HTML
        auth_page = client.get(f"/api/pair/spotify/demo-authorize?state={state_sp}")
        assert auth_page.status_code == 200
        assert "BAROGROOVE Demo Mode" in auth_page.text

        # 3. Complete demo pairing -> sets paired=True
        comp_page = client.get(f"/api/pair/spotify/demo-complete?state={state_sp}")
        assert comp_page.status_code == 200
        assert "Spotify Connected" in comp_page.text

        # 4. Status reflects connected=True for Spotify
        status_res = client.get("/api/pair/status", headers=headers)
        assert status_res.status_code == 200
        status_json = status_res.json()
        assert status_json["spotify"]["connected"] is True
        assert status_json["spotify"]["account"] == "Demo Spotify Account"

        # 5. Start Last.fm pairing in Demo Mode -> 200 OK (no 503)
        lfm_start = client.post("/api/pair/lastfm/start", headers=headers)
        assert lfm_start.status_code == 200
        lfm_data = lfm_start.json()
        assert "/api/pair/lastfm/demo-authorize?state=" in lfm_data["authorize_url"]
        state_lfm = lfm_data["token"]

        # 6. Complete Last.fm demo pairing
        comp_lfm = client.get(f"/api/pair/lastfm/demo-complete?state={state_lfm}")
        assert comp_lfm.status_code == 200

        status_res2 = client.get("/api/pair/status", headers=headers)
        assert status_res2.json()["lastfm"]["connected"] is True

        # 7. Disconnect returns updated status compatible with Flutter PairingStatus.fromJson
        disc_res = client.post("/api/pair/spotify/disconnect", headers=headers)
        assert disc_res.status_code == 200
        assert disc_res.json()["spotify"]["connected"] is False


class TestFlutterA2uiTransformAndLivePairing:
    def test_flutter_a2ui_surfaces_have_no_unknown_components_and_correct_surface_ids(self) -> None:
        from fastapi.testclient import TestClient
        from app.main import create_app

        client = TestClient(create_app())

        # 1. Sky surface has surfaceId "sky" and no Stack components
        sky_res = client.get("/api/surfaces/sky")
        assert sky_res.status_code == 200
        sky_data = sky_res.json()
        assert sky_data[0]["createSurface"]["surfaceId"] == "sky"
        sky_comps = sky_data[1]["updateComponents"]["components"]
        assert all(c["component"] != "Stack" for c in sky_comps)
        assert any(c["component"] == "Column" and c["id"] == "root" for c in sky_comps)

        # 2. Themes surface has surfaceId "themes" and no ThemeChip/GenreOption template components
        th_res = client.get("/api/surfaces/themes")
        assert th_res.status_code == 200
        th_data = th_res.json()
        assert th_data[0]["createSurface"]["surfaceId"] == "themes"
        th_comps = th_data[1]["updateComponents"]["components"]
        assert all(c["component"] not in ("Stack", "ThemeChip", "GenreOption") for c in th_comps)

        # 3. Forge a playlist and verify showPlaylist and showAlmanac return clean Flutter A2UI
        forge_res = client.post("/api/forge", json={"theme_id": "petrichor"})
        assert forge_res.status_code == 200
        pl_id = forge_res.json()["playlist"]["id"]

        pl_surface_res = client.post(
            "/api/surfaces/action",
            json={"actionResponse": {"surfaceId": "playlist", "actionId": "showPlaylist", "payload": {"playlist_id": pl_id}}},
        )
        assert pl_surface_res.status_code == 200
        pl_data = pl_surface_res.json()
        assert pl_data[0]["createSurface"]["surfaceId"] == "playlist"
        pl_comps = pl_data[1]["updateComponents"]["components"]
        assert all(c["component"] not in ("Stack", "TrackRow") for c in pl_comps)

        alm_surface_res = client.post(
            "/api/surfaces/action",
            json={"actionResponse": {"surfaceId": "almanac", "actionId": "showAlmanac"}},
        )
        assert alm_surface_res.status_code == 200
        alm_data = alm_surface_res.json()
        assert alm_data[0]["createSurface"]["surfaceId"] == "almanac"
        alm_comps = alm_data[1]["updateComponents"]["components"]
        assert all(c["component"] not in ("Stack", "AlmanacEntry") for c in alm_comps)

    def test_custom_account_pairing_and_configure_endpoint(self) -> None:
        from fastapi.testclient import TestClient
        from app.main import create_app

        client = TestClient(create_app())
        headers = {"X-Barogroove-User": "jpaquay"}

        start_res = client.post("/api/pair/lastfm/start", headers=headers)
        assert start_res.status_code == 200
        state = start_res.json()["token"]

        comp_res = client.get(f"/api/pair/lastfm/demo-complete?state={state}&account=jpaquay")
        assert comp_res.status_code == 200

        status_res = client.get("/api/pair/status", headers=headers)
        assert status_res.status_code == 200
        assert status_res.json()["lastfm"]["account"] == "jpaquay"

    def test_iam_allowlist_and_real_oauth_html_popup(self) -> None:
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch
        import pytest
        from app.firebase.auth import ALLOWED_IAM_USERS, AuthError, verify_bearer_token

        assert ALLOWED_IAM_USERS == {
            "jpaquay@gmail.com",
            "jerome@netdev.be",
            "jpaquay@gcp.altostrat.com",
            "jpaquay@google.com",
            "elena.ruizroman@gmail.com",
            "arthurpaquay@gmail.com",
            "esperuiz@gmail.com",
        }

        prod_settings = SimpleNamespace(
            environment="production",
            gcp_project="netdev-firebase",
            firebase_project_id="netdev-firebase",
            auth_allow_insecure_dev_tokens=False,
        )

        # Allowed email passes in production
        with patch(
            "app.firebase.auth._verify_with_admin_sdk",
            new=AsyncMock(
                return_value={
                    "user_id": "u123",
                    "email": "jpaquay@google.com",
                    "name": "Jerome",
                }
            ),
        ):
            user = asyncio.run(verify_bearer_token("fake-jwt", settings=prod_settings))
            assert user.email == "jpaquay@google.com"

        # Disallowed email raises 403 Forbidden in production
        with patch(
            "app.firebase.auth._verify_with_admin_sdk",
            new=AsyncMock(
                return_value={
                    "user_id": "intruder",
                    "email": "intruder@example.com",
                    "name": "Intruder",
                }
            ),
        ):
            with pytest.raises(AuthError) as exc_info:
                asyncio.run(verify_bearer_token("fake-jwt", settings=prod_settings))
            assert exc_info.value.status_code == 403



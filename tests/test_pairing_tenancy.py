"""Tenancy boundaries in the provider-pairing layer (rework item 4).

These are boundary tests. The happy paths already have coverage in
``test_platform.py``; what is asserted here is what must NOT happen, because
every one of these paths touches a **credential store**: Spotify refresh
tokens and Last.fm session keys, per uid.

The defect class is a path that cannot resolve an identity and substitutes a
concrete one instead of refusing. Two of the substitutions fixed here named a
real account (``jpaquay``) and a shared one (``demo_user``), and both were
reachable by an unauthenticated caller hitting a callback URL.

The third is state fixation: the Last.fm callback used to fall back to "any
pending Last.fm state" when the token it was handed matched nothing. That made
one user's in-flight pairing redeemable by anybody.
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest


@pytest.fixture
def pairing(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """The pairing module with its process-local state emptied.

    ``_states``, ``_demo_pairings`` and the two ``_in_memory_*`` mirrors are
    module-level dicts. They are correctly keyed by user id, which is exactly
    what these tests hold them to, but they do outlive a single test.
    """
    from backend.app.routes import pairing as module

    def _clear() -> None:
        module._states._items.clear()
        module._states._consumed.clear()
        module._demo_pairings.clear()
        module._in_memory_lastfm.clear()
        module._in_memory_spotify_meta.clear()

    _clear()
    # Nothing here may reach Secret Manager (or its credential discovery).
    monkeypatch.setattr(module, "_save_secret_to_gcp", lambda *a, **k: False)
    yield module
    _clear()


def _as(user_id: str) -> dict[str, str]:
    return {"X-Barogroove-User": user_id}


def _vault_is_empty_for(pairing: Any, user_id: str) -> bool:
    """No trace of ``user_id`` in any of the stores a pairing writes to."""
    return (
        user_id not in pairing._in_memory_lastfm
        and user_id not in pairing._in_memory_spotify_meta
        and not any(key[0] == user_id for key in pairing._demo_pairings)
    )


# --------------------------------------------------------------------------- #
# an unresolvable pending state must refuse, not pick a user
# --------------------------------------------------------------------------- #


class TestUnknownStateWritesNothing:
    def test_lastfm_demo_complete_refuses_an_unknown_state(self, client, pairing) -> None:  # noqa: ANN001
        """Was: ``user_id = pending.user_id if pending else "demo_user"``.

        An expired or forged state used to complete the pairing anyway, into a
        bucket nobody asked for.
        """
        res = client.get(
            "/api/pair/lastfm/demo-complete?state=never-issued&account=attacker"
        )

        assert res.status_code == 400
        assert res.json()["error"] == "bad_state"
        for victim in ("jpaquay", "demo_user", "demo", "attacker"):
            assert _vault_is_empty_for(pairing, victim), victim

    def test_spotify_demo_complete_refuses_an_unknown_state(self, client, pairing) -> None:  # noqa: ANN001
        res = client.get("/api/pair/spotify/demo-complete?state=never-issued")

        assert res.status_code == 400
        assert res.json()["error"] == "bad_state"
        for victim in ("jpaquay", "demo_user", "demo"):
            assert _vault_is_empty_for(pairing, victim), victim

    async def test_no_spotify_token_lands_in_a_named_vault(self, client, pairing) -> None:  # noqa: ANN001
        """The severe version of the above: the write is a *token* write."""
        client.get("/api/pair/spotify/demo-complete?state=never-issued")

        vault = pairing.get_token_vault()
        for victim in ("jpaquay", "demo_user", "demo"):
            assert await vault.get(victim) is None, victim

    def test_configure_refuses_to_mint_a_pairing_for_a_literal_user(
        self, client, pairing, monkeypatch: pytest.MonkeyPatch
    ) -> None:  # noqa: ANN001
        """Was: ``uid = pending.user_id if pending else "jpaquay"``.

        Saving OAuth credentials is a deployment-level act; starting the OAuth
        flow that follows is a per-user one. With no resolvable state there is
        no user to bind it to, and the old code bound it to a real person: the
        tokens that came back would have landed in their vault.
        """
        # Record the pre-state so the route's direct os.environ writes are undone.
        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "")
        monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "")

        res = client.post(
            "/api/pair/spotify/configure",
            data={
                "state": "never-issued",
                "client_id": "live-client-id",
                "client_secret": "live-client-secret",
                "account": "jpaquay",
            },
            follow_redirects=False,
        )

        assert res.status_code == 400, "an unresolvable state must not start an OAuth flow"
        assert res.json()["error"] == "bad_state"
        assert all(
            pending.user_id != "jpaquay" for pending in pairing._states._items.values()
        ), "no pending pairing may be minted for a literal user id"


# --------------------------------------------------------------------------- #
# state fixation: the state must be the one that was issued
# --------------------------------------------------------------------------- #


class TestLastfmCallbackStateBinding:
    @staticmethod
    def _start_for(client, user_id: str) -> str:  # noqa: ANN001
        res = client.post("/api/pair/lastfm/start", headers=_as(user_id))
        assert res.status_code == 200
        token = res.json()["token"]
        assert token
        return str(token)

    def test_an_unissued_token_cannot_borrow_someone_elses_pending_state(
        self, client, pairing
    ) -> None:  # noqa: ANN001
        """The fixation itself.

        The callback used to scan for *any* pending Last.fm state when the
        token matched nothing, so an unauthenticated caller arriving with their
        own Last.fm request token was matched against whoever happened to be
        pairing, and the exchange wrote their session key into that user's
        vault.
        """
        issued = self._start_for(client, "user_a")

        res = client.get("/api/pair/lastfm/callback?token=attacker-request-token")

        assert res.status_code == 400
        assert res.json()["error"] == "bad_state"
        assert (
            pairing._states.peek(issued) is not None
        ), "a stranger's callback must not consume an in-flight pairing"
        assert _vault_is_empty_for(pairing, "user_a")

    def test_a_state_issued_for_a_cannot_be_redeemed_by_b(self, client, pairing) -> None:  # noqa: ANN001
        issued = self._start_for(client, "user_a")

        res = client.get(
            f"/api/pair/lastfm/callback?token={issued}", headers=_as("user_b")
        )

        assert res.status_code == 403
        assert res.json()["error"] == "state_user_mismatch"
        assert pairing._states.peek(issued) is not None, "and it must not burn A's state"
        assert _vault_is_empty_for(pairing, "user_a")
        assert _vault_is_empty_for(pairing, "user_b")

    def test_a_second_users_pending_state_is_not_a_substitute(
        self, client, pairing
    ) -> None:  # noqa: ANN001
        """Two users mid-pairing at once: neither may be matched by accident."""
        issued_a = self._start_for(client, "user_a")
        issued_b = self._start_for(client, "user_b")

        res = client.get("/api/pair/lastfm/callback?token=unrelated-token")

        assert res.status_code == 400
        assert pairing._states.peek(issued_a) is not None
        assert pairing._states.peek(issued_b) is not None

    def test_manual_exchange_refuses_another_users_state(self, client, pairing) -> None:  # noqa: ANN001
        """Pasting a redirect URL issued to someone else pairs nobody."""
        start = client.post("/api/pair/spotify/start", headers=_as("user_a"))
        assert start.status_code == 200
        state_a = start.json()["state"]

        res = client.post(
            "/api/pair/spotify/manual-exchange",
            json={"url_or_code": "https://x/cb?code=abc", "state": state_a},
            headers=_as("user_b"),
        )

        assert res.status_code == 403
        assert res.json()["error"] == "state_user_mismatch"
        assert pairing._states.peek(state_a) is not None
        assert _vault_is_empty_for(pairing, "user_b")


# --------------------------------------------------------------------------- #
# one user's connection is not another user's connection
# --------------------------------------------------------------------------- #


class TestStatusIsPerUser:
    @staticmethod
    def _pair_demo_spotify(client, user_id: str, account: str) -> None:  # noqa: ANN001
        start = client.post("/api/pair/spotify/start", headers=_as(user_id))
        assert start.status_code == 200
        state = start.json()["state"]
        done = client.get(
            f"/api/pair/spotify/demo-complete?state={state}&account={account}"
        )
        assert done.status_code == 200

    def test_status_for_a_does_not_report_bs_connection(self, client, pairing) -> None:  # noqa: ANN001
        self._pair_demo_spotify(client, "user_a", "a-account")

        mine = client.get("/api/pair/status", headers=_as("user_a")).json()
        theirs = client.get("/api/pair/status", headers=_as("user_b")).json()

        assert mine["spotify"]["connected"] is True
        assert mine["spotify"]["account"] == "a-account"
        assert theirs["spotify"]["connected"] is False
        assert theirs["spotify"]["account"] in (None, "")

    def test_demo_complete_pairs_the_state_owner_not_the_caller(
        self, client, pairing
    ) -> None:  # noqa: ANN001
        start = client.post("/api/pair/spotify/start", headers=_as("user_a"))
        state_a = start.json()["state"]

        # user_b walks in with user_a's link.
        client.get(
            f"/api/pair/spotify/demo-complete?state={state_a}&account=a-account",
            headers=_as("user_b"),
        )

        theirs = client.get("/api/pair/status", headers=_as("user_b")).json()
        assert theirs["spotify"]["connected"] is False

    def test_an_unnamed_demo_pairing_is_not_labelled_with_a_real_handle(
        self, client, pairing
    ) -> None:  # noqa: ANN001
        """The badge text is identity too.

        The account label defaulted to ``jpaquay``, so any user completing a
        demo pairing without a handle was shown "Connected as jpaquay".
        """
        start = client.post("/api/pair/lastfm/start", headers=_as("user_a"))
        state = start.json()["token"]
        client.get(f"/api/pair/lastfm/demo-complete?state={state}")

        mine = client.get("/api/pair/status", headers=_as("user_a")).json()
        assert mine["lastfm"]["account"] != "jpaquay"


class TestCrossInstanceStateStore:
    def test_spotify_state_survives_routing_to_a_different_cloud_run_instance(
        self, client, pairing
    ) -> None:  # noqa: ANN001
        """When /start lands on Cloud Run Instance A and /callback lands on
        Instance B (where in-memory _items is empty), the Fernet-sealed state token
        is decrypted statelessly on Instance B while preventing replay."""
        start = client.post("/api/pair/spotify/start", headers=_as("user_a"))
        assert start.status_code == 200
        state = start.json()["state"]
        assert state.startswith("bg1.")

        # Simulate landing on a brand new Cloud Run instance whose in-memory store is empty
        pairing._states._items.clear()

        # Callback on Instance B must succeed
        done = client.get(
            f"/api/pair/spotify/demo-complete?state={state}&account=cross-instance-spotify"
        )
        assert done.status_code == 200

        status = client.get("/api/pair/status", headers=_as("user_a")).json()
        assert status["spotify"]["connected"] is True
        assert status["spotify"]["account"] == "cross-instance-spotify"

        # Replay on Instance B must fail with bad_state
        replay = client.get(
            f"/api/pair/spotify/demo-complete?state={state}&account=attacker"
        )
        assert replay.status_code == 400
        assert replay.json()["error"] == "bad_state"


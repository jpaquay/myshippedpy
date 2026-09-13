"""The write gate -- plan item 11.

The policy under test, in the user's words: **read and select freely, confirm
before anything that writes.**

What these tests are really checking is that the gate is a *server* property.
A confirmation dialog in Flutter is easy to write and worth nothing against a
buggy build, a second client or an agent runtime speaking MCP directly, so
every assertion here is made against the backend with no UI in the picture at
all. If these pass, a compromised client cannot forge, reforge, rate or save
without asking.

Nothing here touches the network.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from backend.app.mcp import confirm
from backend.app.mcp import functions as fx
from backend.app.mcp import gateway
from backend.app.mcp import manifest as mf

def _run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean_tickets() -> Any:
    confirm.reset_tickets()
    yield
    confirm.reset_tickets()


# =====================================================================
# The classification is declared once, in Python, and agrees with itself
# =====================================================================


def test_the_two_selects_do_not_write_and_the_three_mutators_do() -> None:
    """The exact split the user asked for, read back off the declarations."""
    assert confirm.function_writes("select_theme") is False
    assert confirm.function_writes("select_genre") is False

    assert confirm.function_writes("rate_track") is True
    assert confirm.function_writes("reforge") is True
    assert confirm.function_writes("forge_playlist") is True


def test_the_flag_is_reachable_under_every_spelling() -> None:
    """camelCase, snake_case and the A2UI action id must answer the same."""
    for spelling in ("selectTheme", "select_theme", "barogroove.selectTheme"):
        assert confirm.function_writes(spelling) is False, spelling
    for spelling in ("rateTrack", "rate_track", "barogroove.trackFeedback"):
        assert confirm.function_writes(spelling) is True, spelling


def test_an_unclassified_capability_is_treated_as_a_write() -> None:
    """The safe default. A capability nobody declared is not one we run unasked."""
    assert confirm.function_writes("drop_everything") is True


def test_the_agent_registry_and_the_a2ui_catalog_agree() -> None:
    """Two vocabularies, one classification. They must not drift apart.

    ``functions.py`` declares ``AgentFunction.writes`` next to each handler;
    ``a2ui/catalog.py`` declares ``WRITE_FUNCTION_IDS`` in the action-id
    vocabulary. Both are consumed -- by MCP and by the A2UI action endpoint --
    so a disagreement would mean the same operation is gated on one path and
    open on the other.
    """
    catalog = pytest.importorskip("backend.app.a2ui.catalog")

    for fn in fx.REGISTRY.values():
        catalog_ids = [a for a in fn.aliases if a.startswith("barogroove.")]
        if not catalog_ids:
            continue
        for cid in catalog_ids:
            if cid not in catalog.FUNCTIONS:
                continue
            assert catalog.function_writes(cid) == fn.writes, (
                f"{fn.name} says writes={fn.writes} but the catalog says "
                f"{catalog.function_writes(cid)} for {cid}"
            )


def test_reforge_is_classified_even_though_the_catalog_spells_it_forge() -> None:
    """`reforge` is an agent function; `barogroove.forge` is the catalog id.

    They are not string-equal, which is exactly the kind of gap a hardcoded
    name list falls into. Both must classify as a write.
    """
    assert fx.REGISTRY["reforge"].writes is True
    catalog = pytest.importorskip("backend.app.a2ui.catalog")
    assert catalog.function_writes(catalog.FN_FORGE) is True


# =====================================================================
# The flag travels: catalog, tool manifest, capability list
# =====================================================================


def test_the_catalog_carries_the_flag_so_dart_does_not_have_to() -> None:
    catalog = pytest.importorskip("backend.app.a2ui.catalog")
    ext = catalog.CATALOG["metadata"]["extensions"]["barogroove"]

    assert catalog.FN_TRACK_FEEDBACK in ext["writeFunctions"]
    assert catalog.FN_FORGE in ext["writeFunctions"]
    assert catalog.FN_SELECT_THEME not in ext["writeFunctions"]

    writes = ext["functionWrites"]
    assert writes[catalog.FN_SELECT_THEME] is False
    assert writes[catalog.FN_SELECT_GENRE] is False
    assert writes[catalog.FN_TRACK_FEEDBACK] is True


def test_the_tool_manifest_carries_the_flag() -> None:
    assert mf.tool_spec("forge_playlist").writes is True
    assert mf.tool_spec("save_playlist").writes is True
    assert mf.tool_spec("get_sky_vector").writes is False
    assert mf.tool_spec("list_themes").writes is False

    published = mf.tool_spec("forge_playlist").as_dict()
    meta = published["_meta"][mf.A2UI_TOOL_META_KEY]
    assert meta["writes"] is True
    assert meta["requiresConfirmation"] is True
    # The MCP-native spelling is still there and still correct.
    assert published["annotations"]["readOnlyHint"] is False


def test_the_agent_function_manifest_carries_the_flag() -> None:
    by_name = {s.name: s for s in mf.agent_function_specs()}
    assert by_name["selectTheme"].writes is False
    assert by_name["rateTrack"].writes is True
    assert by_name["reforge"].requires_confirmation is True


def test_the_capability_list_the_client_reads_carries_the_flag() -> None:
    """`GET /api/advisor/tools` is why there is no name list in Dart."""
    caps = {c["name"]: c for c in gateway.capabilities()}

    assert caps["selectTheme"]["writes"] is False
    assert caps["selectGenre"]["writes"] is False
    assert caps["rateTrack"]["writes"] is True
    assert caps["reforge"]["writes"] is True
    assert caps["forge_playlist"]["writes"] is True

    # And the arguments, so the confirmation card can show and edit them.
    assert "properties" in caps["forge_playlist"]["arguments"]


# =====================================================================
# A write cannot execute without confirmation
# =====================================================================


def test_a_write_agent_function_refuses_and_runs_nothing() -> None:
    calls: list[Any] = []
    original = fx.REGISTRY["rateTrack"].handler

    async def spy(args: Any) -> list[dict[str, Any]]:
        calls.append(args)
        return await original(args)

    object.__setattr__(fx.REGISTRY["rateTrack"], "handler", spy)
    try:
        result = _run(
            fx.dispatch("rateTrack", {"playlistId": "p", "trackId": "t", "verdict": "love"})
        )
    finally:
        object.__setattr__(fx.REGISTRY["rateTrack"], "handler", original)

    assert result.ok is False
    assert result.error is not None
    assert result.error["code"] == "confirmation_required"
    assert result.error["confirmation"]["token"]
    # The handler was never entered. This is the whole assertion.
    assert calls == []


def test_a_read_function_is_not_gated_at_all() -> None:
    """Selects pay nothing for the gate -- no ticket, no extra round trip."""
    before = confirm.outstanding()
    result = _run(fx.dispatch("selectTheme", {"themeId": "petrichor", "surfaceId": "s1"}))

    assert result.error is None or result.error["code"] != "confirmation_required"
    assert confirm.outstanding() == before, "a select must not mint a ticket"


def test_select_genre_is_not_gated_either() -> None:
    result = _run(fx.dispatch("selectGenre", {"genreId": "ambient", "surfaceId": "s1"}))
    assert result.error is None or result.error["code"] != "confirmation_required"


def test_the_ticket_lets_it_through_exactly_once() -> None:
    args = {"playlistId": "p", "trackId": "t", "verdict": "love"}

    refused = _run(fx.dispatch("rateTrack", dict(args)))
    token = refused.error["confirmation"]["token"]

    allowed = _run(fx.dispatch("rateTrack", dict(args), confirmation_token=token))
    assert allowed.ok is True

    replayed = _run(fx.dispatch("rateTrack", dict(args), confirmation_token=token))
    assert replayed.ok is False
    assert replayed.error["code"] == "confirmation_invalid"


# =====================================================================
# What a client that tries to skip the gate actually gets
# =====================================================================


def test_a_forged_token_is_refused() -> None:
    """The ticket cannot be constructed client-side -- it is server state."""
    result = _run(
        fx.dispatch(
            "rateTrack",
            {"playlistId": "p", "trackId": "t", "verdict": "love"},
            confirmation_token="definitely-a-real-token",
        )
    )
    assert result.ok is False
    assert result.error["code"] == "confirmation_invalid"
    assert "Nothing was changed" in result.error["message"]


def test_a_ticket_for_one_function_cannot_be_spent_on_another() -> None:
    ticket = confirm.issue("rateTrack", principal="u1", arguments={})
    with pytest.raises(confirm.ConfirmationInvalid) as exc:
        confirm.redeem(ticket.token, function="reforge", principal="u1")
    assert "was for 'rateTrack'" in str(exc.value)


def test_a_ticket_belongs_to_the_principal_it_was_minted_for() -> None:
    """Bound to the identity the guard resolved, not to anything sent in the body."""
    ticket = confirm.issue("reforge", principal="alice", arguments={})
    with pytest.raises(confirm.ConfirmationInvalid):
        confirm.redeem(ticket.token, function="reforge", principal="mallory")
    # And alice cannot use it afterwards either: redemption is single-use even
    # when it fails, so a stolen token cannot be brute-forced against
    # principals.
    with pytest.raises(confirm.ConfirmationInvalid):
        confirm.redeem(ticket.token, function="reforge", principal="alice")


def test_a_ticket_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    ticket = confirm.issue("reforge", principal="u1", arguments={})
    real_monotonic = time.monotonic
    monkeypatch.setattr(
        confirm.time,
        "monotonic",
        lambda: real_monotonic() + confirm.TICKET_TTL_SECONDS + 1,
    )
    with pytest.raises(confirm.ConfirmationInvalid):
        confirm.redeem(ticket.token, function="reforge", principal="u1")


def test_outstanding_tickets_are_capped() -> None:
    """Proposing writes you never confirm cannot grow memory without bound."""
    for _ in range(400):
        confirm.issue("reforge", principal="u1", arguments={})
    assert confirm.outstanding() <= 256


# =====================================================================
# The gateway -- one door for both dispatch paths (item 11's real shape)
# =====================================================================


def test_forge_playlist_is_a_tool_not_an_agent_function_and_is_still_gated() -> None:
    """The finding that shaped this item.

    `forge_playlist` is an MCP tool on a different dispatch path from the four
    camelCase agent functions, so a gate that only knew about the registry
    would have left the single most consequential write wide open.
    """
    assert "forge_playlist" not in fx.FUNCTION_NAMES
    assert "forge_playlist" in mf.TOOL_NAMES

    result = _run(
        gateway.perform(
            "forge_playlist",
            {"lat": 50.85, "lon": 4.35, "length": 6},
            principal="u1",
        )
    )
    assert result.status == "confirmation_required"
    assert result.writes is True
    assert result.confirmation is not None
    assert result.confirmation["token"]
    # Every argument comes back so the card can show and edit them (spec 6.5).
    assert result.confirmation["arguments"]["length"] == 6
    assert "properties" in result.confirmation["argument_schema"]


def test_a_select_through_the_gateway_acts_immediately() -> None:
    result = _run(gateway.perform("select_theme", {"themeId": "petrichor"}, principal="u1"))
    assert result.status == "done"
    assert result.writes is False


def test_an_unknown_capability_is_refused_politely() -> None:
    result = _run(gateway.perform("rm_rf_slash", {}, principal="u1"))
    assert result.status == "error"
    assert result.error["code"] == "unknown_function"


def test_the_gateway_spends_exactly_one_ticket_per_confirmed_write() -> None:
    """No double-minting between the gateway and the shared dispatcher."""
    refused = _run(
        gateway.perform(
            "rate_track",
            {"playlistId": "p", "trackId": "t", "verdict": "love"},
            principal="u1",
        )
    )
    assert refused.status == "confirmation_required"
    assert confirm.outstanding() == 1

    token = refused.confirmation["token"]
    done = _run(
        gateway.perform(
            "rate_track",
            {"playlistId": "p", "trackId": "t", "verdict": "love"},
            principal="u1",
            confirmation_token=token,
        )
    )
    assert done.status == "done"
    assert confirm.outstanding() == 0


def test_arguments_may_be_edited_between_proposal_and_confirmation() -> None:
    """Spec 6.5 makes the card's arguments editable, so the ticket authorises
    the *act*, not a frozen payload."""
    refused = _run(
        gateway.perform(
            "rate_track",
            {"playlistId": "p", "trackId": "t", "verdict": "love"},
            principal="u1",
        )
    )
    token = refused.confirmation["token"]

    done = _run(
        gateway.perform(
            "rate_track",
            {"playlistId": "p", "trackId": "t", "verdict": "skip"},
            principal="u1",
            confirmation_token=token,
        )
    )
    assert done.status == "done"


def test_the_refusal_payload_is_what_the_card_needs() -> None:
    result = _run(
        gateway.perform("forge_playlist", {"lat": 0.0, "lon": 0.0}, principal="u1")
    )
    body = result.as_payload()

    assert body["status"] == "confirmation_required"
    assert body["writes"] is True
    assert body["message"]  # a sentence a person can read
    assert body["confirmation"]["token"]
    assert body["confirmation"]["title"]
    assert body["confirmation"]["expires_in_seconds"] > 0
    assert "receipt" not in body, "nothing ran, so there is nothing to receipt"


# =====================================================================
# The MCP transport is a client too
# =====================================================================


def test_the_mcp_wrapper_refuses_an_unconfirmed_forge() -> None:
    """An agent runtime with a valid token, and no BAROGROOVE UI anywhere.

    `_confirmation_refusal` is what the registered `forge_playlist` wrapper
    calls before it touches the tool body, so this is the refusal that a raw
    `tools/call` receives.
    """
    srv = pytest.importorskip("backend.app.mcp.server")

    refusal = srv._confirmation_refusal(
        "forge_playlist",
        {"lat": 50.85, "lon": 4.35, "length": 6},
        None,
    )
    assert refusal is not None, "an unconfirmed forge must not reach the tool body"

    structured = gateway._structured(refusal)
    assert structured.get("ok") is False
    assert structured["error"]["code"] == "confirmation_required"


def test_the_mcp_wrapper_lets_a_confirmed_forge_through() -> None:
    srv = pytest.importorskip("backend.app.mcp.server")

    args = {"lat": 50.85, "lon": 4.35, "length": 6}
    refusal = srv._confirmation_refusal("forge_playlist", args, None)
    token = gateway._structured(refusal)["error"]["detail"]

    assert srv._confirmation_refusal("forge_playlist", args, token) is None


def test_a_read_only_tool_is_never_gated_on_the_mcp_path() -> None:
    srv = pytest.importorskip("backend.app.mcp.server")
    assert srv._confirmation_refusal("list_themes", {}, None) is None
    assert srv._confirmation_refusal("get_sky_vector", {"lat": 0.0, "lon": 0.0}, None) is None


# =====================================================================
# The HTTP surface the overlay actually calls
# =====================================================================


def _api_client() -> Any:
    from fastapi.testclient import TestClient

    from backend.app.main import create_app

    return TestClient(create_app())


def test_the_tools_endpoint_publishes_the_writes_flag() -> None:
    resp = _api_client().get("/api/advisor/tools")
    assert resp.status_code == 200

    caps = {c["name"]: c for c in resp.json()["capabilities"]}
    assert caps["selectTheme"]["writes"] is False
    assert caps["forge_playlist"]["writes"] is True


def test_posting_a_write_without_a_token_returns_a_ticket_and_writes_nothing() -> None:
    """The exact thing a client that skips the confirmation card gets."""
    resp = _api_client().post(
        "/api/advisor/act",
        json={
            "function": "rate_track",
            "arguments": {"playlistId": "p", "trackId": "t", "verdict": "love"},
        },
    )
    assert resp.status_code == 200

    body = resp.json()
    assert body["status"] == "confirmation_required"
    assert body["writes"] is True
    assert body["confirmation"]["token"]
    assert "receipt" not in body


def test_posting_a_select_acts_immediately() -> None:
    resp = _api_client().post(
        "/api/advisor/act",
        json={"function": "select_theme", "arguments": {"themeId": "petrichor"}},
    )
    assert resp.status_code == 200

    body = resp.json()
    assert body["status"] == "done"
    assert body["writes"] is False
    assert body["receipt"]


def test_the_round_trip_over_http() -> None:
    client = _api_client()
    payload = {
        "function": "rate_track",
        "arguments": {"playlistId": "p", "trackId": "t", "verdict": "love"},
    }

    refused = client.post("/api/advisor/act", json=payload).json()
    token = refused["confirmation"]["token"]

    done = client.post(
        "/api/advisor/act", json={**payload, "confirmationToken": token}
    ).json()
    assert done["status"] == "done"

    replayed = client.post(
        "/api/advisor/act", json={**payload, "confirmationToken": token}
    ).json()
    assert replayed["status"] == "error"
    assert replayed["error"]["code"] == "confirmation_invalid"

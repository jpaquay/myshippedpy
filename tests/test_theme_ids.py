"""One canonical theme list, asserted across every module that names themes.

BAROGROOVE used to keep two: ``app.contracts.THEME_IDS`` (petrichor ... sirocco)
and a second, divergent set inside ``app.a2ui.palette`` (high_pressure_blue,
gale_warning, blanket_grey, heat_shimmer, long_dusk).  The theme-chips surface
was built from one and ``selectTheme`` validated against the other, so tapping a
chip the UI had just offered could come back 422.

Every test in this file exists to make that class of drift impossible rather
than merely unlikely: if any module -- Python or Dart -- grows its own list
again, something here goes red.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_ROOT = _TESTS.parent
sys.path.insert(0, str(_ROOT / "backend"))

from app.a2ui import catalog as cat  # noqa: E402
from app.a2ui import palette as pal  # noqa: E402
from app.contracts import (  # noqa: E402
    RETIRED_THEME_ALIASES,
    RETIRED_THEME_IDS,
    THEME_IDS,
    resolve_theme_id,
)
from app.sonic import themes as sonic_themes  # noqa: E402

MODELS_DART = _ROOT / "frontend" / "lib" / "api" / "models.dart"


# --------------------------------------------------------------------------- #
# The canonical list
# --------------------------------------------------------------------------- #


def test_contracts_owns_exactly_eight_ids() -> None:
    assert len(THEME_IDS) == 8
    assert len(set(THEME_IDS)) == 8, "duplicate theme id in contracts.THEME_IDS"


def test_palette_reexports_the_contract_rather_than_redeclaring_it() -> None:
    """``palette.THEME_IDS`` must BE the contract, not a copy that can drift."""
    assert pal.THEME_IDS is THEME_IDS


@pytest.mark.parametrize("theme_id", THEME_IDS)
def test_every_canonical_id_has_a_palette_and_an_intent(theme_id: str) -> None:
    assert theme_id in pal.THEME_PALETTES, f"{theme_id} has no palette"
    assert theme_id in pal.THEME_INTENT, f"{theme_id} has no intent line"
    assert pal.THEME_INTENT[theme_id].strip(), f"{theme_id} intent line is empty"


def test_palette_and_intent_keysets_cannot_drift_from_contracts() -> None:
    """The regression proper: three keysets, one list, no extras either way."""
    canonical = set(THEME_IDS)
    assert set(pal.THEME_PALETTES) == canonical
    assert set(pal.THEME_INTENT) == canonical
    assert set(sonic_themes.THEMES) == canonical
    # Ordering is part of the contract too -- the chips render in this order.
    assert tuple(pal.THEME_PALETTES) == THEME_IDS
    assert tuple(t.id for t in sonic_themes.list_themes()) == THEME_IDS


def test_the_import_time_guard_actually_fires(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_assert_no_theme_drift`` must reject a divergence, not just document one."""
    monkeypatch.setitem(pal.THEME_PALETTES, "hurricane_beige", {})
    with pytest.raises(RuntimeError, match="drifted"):
        pal._assert_no_theme_drift()


# --------------------------------------------------------------------------- #
# The thing that actually broke: chips offered an id selectTheme rejected
# --------------------------------------------------------------------------- #


def test_select_theme_accepts_every_id_the_chips_can_offer() -> None:
    """The bug, stated as a test. ``sirocco`` was the id that 422-ed."""
    definition = cat.function_definition(cat.FN_SELECT_THEME)
    enum = definition.parameters["properties"]["themeId"]["enum"]
    assert list(enum) == list(THEME_IDS)

    for theme in sonic_themes.list_themes():
        payload = cat.validate_action(cat.FN_SELECT_THEME, {"themeId": theme.id})
        assert payload["themeId"] == theme.id


def test_sirocco_specifically_is_selectable() -> None:
    assert "sirocco" in THEME_IDS
    assert "sirocco" in pal.THEME_PALETTES
    assert cat.validate_action(cat.FN_SELECT_THEME, {"themeId": "sirocco"})["themeId"] == "sirocco"


# --------------------------------------------------------------------------- #
# Retired ids
# --------------------------------------------------------------------------- #


def test_retired_ids_are_not_canonical_and_are_not_styled() -> None:
    retired = set(RETIRED_THEME_ALIASES) | set(RETIRED_THEME_IDS)
    assert retired.isdisjoint(THEME_IDS)
    assert retired.isdisjoint(pal.THEME_PALETTES)
    assert retired.isdisjoint(pal.THEME_INTENT)


def test_the_five_palette_only_ids_are_accounted_for() -> None:
    """Four were renames, one was the untinted chassis. None may reappear."""
    assert {
        "gale_warning": "storm_front",
        "blanket_grey": "nordic_fog",
        "heat_shimmer": "heatwave_cruise",
        "long_dusk": "blue_hour",
    }.items() <= RETIRED_THEME_ALIASES.items()
    assert "high_pressure_blue" in RETIRED_THEME_IDS
    assert set(RETIRED_THEME_ALIASES.values()) <= set(THEME_IDS)


def test_the_router_no_longer_keeps_a_theme_table_of_its_own() -> None:
    """One alias table, in contracts. The router used to carry a second one that
    mapped canonical ids ONTO the retired names, which is how blue_hour became
    long_dusk on the way in."""
    source = (_ROOT / "backend" / "app" / "routes" / "surfaces.py").read_text("utf-8")
    assert "theme_aliases = {" not in source
    assert '"blue_hour": "long_dusk"' not in source
    for legacy in ("low_pressure_front", "midnight_thermal", "solar_zenith"):
        assert RETIRED_THEME_ALIASES[legacy] in THEME_IDS


@pytest.mark.parametrize(
    ("retired", "canonical"),
    sorted(RETIRED_THEME_ALIASES.items()),
)
def test_a_retired_spelling_resolves_instead_of_failing(retired: str, canonical: str) -> None:
    assert resolve_theme_id(retired) == canonical
    # ...and it gets the tint it always had, under its new name.
    assert pal.surface_properties_for(retired)["themeId"] == canonical
    assert pal.surface_properties_for(retired)["palette"] == pal.THEME_PALETTES[canonical]


def test_high_pressure_blue_resolves_to_no_theme_not_to_a_wrong_one() -> None:
    """It was ``{**BASE}`` verbatim, so 'no theme' is the honest answer."""
    assert resolve_theme_id("high_pressure_blue") is None
    assert pal.surface_properties_for("high_pressure_blue")["palette"] == dict(pal.BASE)


def test_an_unknown_id_resolves_to_none_rather_than_raising() -> None:
    assert resolve_theme_id("neon_vaporwave") is None
    assert resolve_theme_id(None) is None
    assert resolve_theme_id("") is None


# --------------------------------------------------------------------------- #
# The Dart side keeps a list too -- pin it from here, where it can be tested
# --------------------------------------------------------------------------- #


def test_flutter_canonical_ids_match_the_contract() -> None:
    source = MODELS_DART.read_text(encoding="utf-8")
    block = re.search(
        r"canonicalIds\s*=\s*<String>\[(?P<body>.*?)\];", source, re.DOTALL
    )
    assert block, f"{MODELS_DART} no longer declares SkyTheme.canonicalIds"
    dart_ids = re.findall(r"'([a-z_]+)'", block.group("body"))
    assert dart_ids == list(THEME_IDS), (
        "frontend/lib/api/models.dart has drifted from contracts.THEME_IDS"
    )


# --------------------------------------------------------------------------- #
# The HTTP edge: fail soft, and say what WOULD have worked
# --------------------------------------------------------------------------- #


def test_selecting_sirocco_over_http_is_not_a_422(client) -> None:  # noqa: ANN001
    """The reported bug, end to end: a chip the surface itself offered."""
    response = client.post(
        "/api/surfaces/action",
        json={"action": "selectTheme", "surfaceId": "themes", "payload": {"themeId": "sirocco"}},
    )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("theme_id", THEME_IDS)
def test_every_canonical_id_is_accepted_over_http(client, theme_id: str) -> None:  # noqa: ANN001
    response = client.post(
        "/api/surfaces/action",
        json={"action": "selectTheme", "surfaceId": "themes", "payload": {"themeId": theme_id}},
    )
    assert response.status_code == 200, response.text


def test_a_retired_spelling_is_translated_over_http(client) -> None:  # noqa: ANN001
    response = client.post(
        "/api/surfaces/action",
        json={"action": "selectTheme", "surfaceId": "themes", "payload": {"themeId": "gale_warning"}},
    )
    assert response.status_code == 200, response.text
    patched = [
        m["updateDataModel"]["contents"]
        for m in response.json()
        if isinstance(m, dict) and "updateDataModel" in m
    ]
    assert {"selectedThemeId": "storm_front"} in patched
    assert "gale_warning" not in response.text


def test_an_unknown_theme_id_comes_back_with_the_valid_set(client) -> None:  # noqa: ANN001
    """A bare 422 is unactionable; the body must carry the eight."""
    response = client.post(
        "/api/surfaces/action",
        json={"action": "selectTheme", "surfaceId": "themes", "payload": {"themeId": "neon_vaporwave"}},
    )
    assert response.status_code == 422
    body = response.json()
    # The envelope app.errors/app.main establish for every other domain error.
    assert body["error"] == "ThemeNotFound"
    assert isinstance(body["detail"], str) and "neon_vaporwave" in body["detail"]
    # ...plus the part that makes it actionable.
    assert body["validThemeIds"] == list(THEME_IDS)
    assert body["retiredThemeIds"] == dict(RETIRED_THEME_ALIASES)
    assert "sirocco" in body["detail"]

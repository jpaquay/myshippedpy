"""One icon vocabulary, owned by Python, asserted across the wire into Dart.

BAROGROOVE is A2UI: the backend *describes* a surface and Flutter renders it
generically.  The theme chips broke that rule.  ``theme_chips.dart`` picked a
glyph by sniffing substrings of the theme id -- ``contains('rain')``,
``contains('fog')``, ``contains('sun')`` -- and fell through to
``Icons.graphic_eq``.  Four of the canonical eight (heatwave_cruise, blue_hour,
first_frost, sirocco) matched no branch at all, so they shared one meaningless
glyph.  Presentation knowledge had leaked into the renderer and then drifted
from the Python that owns the palette and the intent line.

Icon identity now lives beside them, in :data:`app.a2ui.palette.THEME_ICONS`, as
a semantic token that rides on every theme item as ``icon``.  Every test here
exists so the leak cannot come back:

  * the registry covers the contract, exactly, with distinct tokens;
  * the surface builder and the REST adapter both emit the token;
  * the Dart const map and the Dart test's mirror of the table both agree with
    this file -- the same cross-language trick ``test_theme_chips_binding.py``
    uses, because a renderer in another language has no other enforcement.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import pytest

_TESTS = Path(__file__).resolve().parent
_ROOT = _TESTS.parent
sys.path.insert(0, str(_ROOT / "backend"))

from app.a2ui import catalog as cat  # noqa: E402
from app.a2ui import palette as pal  # noqa: E402
from app.a2ui import surfaces as sfc  # noqa: E402
from app.contracts import THEME_IDS  # noqa: E402
from app.sonic.corridors import list_corridors  # noqa: E402
from app.sonic.themes import list_themes  # noqa: E402

THEME_CHIPS_DART = _ROOT / "frontend" / "lib" / "a2ui" / "components" / "theme_chips.dart"
THEME_ICONS_DART_TEST = _ROOT / "frontend" / "test" / "theme_icon_tokens_test.dart"


# --------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("theme_id", THEME_IDS)
def test_every_canonical_id_has_an_icon(theme_id: str) -> None:
    assert theme_id in pal.THEME_ICONS, f"{theme_id} has no icon token"
    assert pal.THEME_ICONS[theme_id].strip(), f"{theme_id} icon token is empty"


def test_the_icon_table_is_exactly_the_contract() -> None:
    """No extras either -- a token for a theme that does not exist is dead code."""
    assert set(pal.THEME_ICONS) == set(THEME_IDS)


def test_icon_tokens_are_distinct() -> None:
    """Two themes wearing one glyph is the symptom this table exists to kill."""
    tokens = list(pal.THEME_ICONS.values())
    assert len(set(tokens)) == len(tokens), f"duplicate icon token: {tokens}"


def test_icon_tokens_are_semantic_names_not_codepoints() -> None:
    """A token must survive Flutter's icon tree-shaking on the other side.

    A codepoint here would become ``IconData(0x...)`` there, which the compiler
    cannot prove is reachable, so the release web build ships a blank box.
    """
    for theme_id, token in pal.THEME_ICONS.items():
        assert re.fullmatch(r"[a-z][a-z0-9_]*", token), (
            f"{theme_id}: {token!r} is not a lowercase semantic icon name"
        )


def test_no_theme_claims_the_fallback_token() -> None:
    assert pal.FALLBACK_THEME_ICON not in set(pal.THEME_ICONS.values())


def test_a_missing_icon_fails_at_import_time_not_in_the_ui(monkeypatch) -> None:  # noqa: ANN001
    """The `_assert_no_theme_drift` guard must cover icons, like it covers tints."""
    incomplete = {k: v for k, v in pal.THEME_ICONS.items() if k != THEME_IDS[0]}
    monkeypatch.setattr(pal, "THEME_ICONS", incomplete)
    with pytest.raises(RuntimeError, match="THEME_ICONS"):
        pal._assert_no_theme_drift()


def test_a_duplicated_icon_fails_at_import_time(monkeypatch) -> None:  # noqa: ANN001
    clashing = dict(pal.THEME_ICONS)
    clashing[THEME_IDS[1]] = clashing[THEME_IDS[0]]
    monkeypatch.setattr(pal, "THEME_ICONS", clashing)
    with pytest.raises(RuntimeError, match="reuses icon tokens"):
        pal._assert_no_theme_drift()


# --------------------------------------------------------------------------- #
# icon_for()
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("theme_id", THEME_IDS)
def test_icon_for_returns_the_registry_entry(theme_id: str) -> None:
    assert pal.icon_for(theme_id) == pal.THEME_ICONS[theme_id]


def test_icon_for_resolves_retired_spellings() -> None:
    for retired, canonical in pal.RETIRED_THEME_ALIASES.items():
        assert pal.icon_for(retired) == pal.THEME_ICONS[canonical]


@pytest.mark.parametrize("unknown", [None, "", "not_a_theme"])
def test_icon_for_falls_back_rather_than_raising(unknown: str | None) -> None:
    """A surface that cannot name its theme should still draw a chip."""
    assert pal.icon_for(unknown) == pal.FALLBACK_THEME_ICON


# --------------------------------------------------------------------------- #
# The surface actually emits it
# --------------------------------------------------------------------------- #


def _data(stream: list[dict[str, Any]]) -> dict[str, Any]:
    for message in stream:
        block = message.get("updateDataModel")
        if isinstance(block, dict) and block.get("path") in ("/", ""):
            return block["contents"]
        block = message.get("createSurface")
        if isinstance(block, dict) and isinstance(block.get("dataModel"), dict):
            return block["dataModel"]
    raise AssertionError("no data model in the stream")


def _theme_items(stream: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _data(stream)["themes"]["items"]


@pytest.fixture
def stream() -> list[dict[str, Any]]:
    return sfc.build_themes_surface(
        list_themes(), list_corridors(), selected_theme="sirocco"
    )


def test_every_theme_item_carries_an_icon_hint(stream) -> None:  # noqa: ANN001
    items = _theme_items(stream)
    assert len(items) == len(THEME_IDS)
    for item in items:
        assert item.get("icon"), f"{item['id']} shipped without an icon hint"


def test_the_emitted_hints_are_the_registry_and_are_distinct(stream) -> None:  # noqa: ANN001
    emitted = {item["id"]: item["icon"] for item in _theme_items(stream)}
    assert emitted == pal.THEME_ICONS
    assert len(set(emitted.values())) == len(emitted)


def test_the_chip_template_binds_the_icon_too() -> None:
    """The other renderer -- the one that expands ThemeChip -- must get it as well."""
    for message in sfc.build_themes_surface(list_themes(), list_corridors()):
        for key in ("updateComponents", "createSurface"):
            block = message.get(key)
            if not isinstance(block, dict):
                continue
            for component in block.get("components") or []:
                if component.get("component") == "ThemeChip":
                    assert component["icon"] == {"path": "/icon"}
                    return
    raise AssertionError("no ThemeChip prototype in the stream")


def test_the_catalog_declares_the_icon_property() -> None:
    """"If a property is not declared here, no surface may use it." -- catalog.py"""
    chip = cat.COMPONENTS["ThemeChip"]
    assert "icon" in chip["properties"]
    assert "icon" in chip["metadata"]["extensions"]["barogroove"]["bindable"]


def test_the_flutter_payload_carries_the_icon(client) -> None:  # noqa: ANN001
    """The REST adapter rebuilds theme items; it must not drop the hint."""
    messages = client.get("/api/surfaces/themes").json()
    items = _data(messages)["themes"]["items"]
    assert len(items) == len(THEME_IDS)
    assert {item["id"]: item["icon"] for item in items} == pal.THEME_ICONS


# --------------------------------------------------------------------------- #
# The Dart side, read out of the Dart source
# --------------------------------------------------------------------------- #


def _dart_token_map(source: str, name: str) -> dict[str, str]:
    """Pull `const Map<String, ...> name = {...}` out of Dart as {key: value}."""
    match = re.search(
        rf"const\s+Map<String,\s*\w+>\s+{re.escape(name)}\s*=\s*<String,\s*\w+>\{{(.*?)\n\}};",
        source,
        re.DOTALL,
    )
    assert match, f"{name} is not a const Map literal any more"
    body = re.sub(r"//[^\n]*", "", match.group(1))
    return dict(re.findall(r"'([a-z0-9_]+)'\s*:\s*([^,\n]+),", body))


def test_the_dart_renderer_reads_the_icon_key_off_the_item() -> None:
    source = THEME_CHIPS_DART.read_text(encoding="utf-8")
    item_keys = set(re.findall(r"theme\['(\w+)'\]", source))
    assert "icon" in item_keys, (
        "theme_chips.dart no longer reads the backend's icon hint"
    )


def test_the_dart_renderer_no_longer_guesses_from_the_theme_id() -> None:
    source = THEME_CHIPS_DART.read_text(encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("//")
    )
    assert "_iconForTheme" not in code, "the substring guesser is back"
    assert ".contains(" not in code, (
        "theme_chips.dart is matching substrings of the theme id again"
    )


def test_the_dart_const_map_covers_the_python_vocabulary() -> None:
    """The two halves of the contract, pinned against each other.

    There is no shared schema between a Python dict and a Dart const map, so
    this reads the map out of the source.  A token added on one side and not the
    other turns this red instead of drawing a grey blob in the UI.
    """
    dart = _dart_token_map(
        THEME_CHIPS_DART.read_text(encoding="utf-8"), "kThemeIconsByToken"
    )
    expected = set(pal.THEME_ICONS.values()) | {pal.FALLBACK_THEME_ICON}
    assert set(dart) == expected, (
        f"icon vocabularies diverged: python-only={sorted(expected - set(dart))} "
        f"dart-only={sorted(set(dart) - expected)}"
    )


def test_the_dart_map_resolves_every_token_to_a_distinct_glyph() -> None:
    dart = _dart_token_map(
        THEME_CHIPS_DART.read_text(encoding="utf-8"), "kThemeIconsByToken"
    )
    glyphs = [dart[token] for token in pal.THEME_ICONS.values()]
    assert len(set(glyphs)) == len(glyphs), f"two themes draw the same glyph: {glyphs}"
    for token, glyph in zip(pal.THEME_ICONS.values(), glyphs, strict=True):
        assert glyph.startswith("Icons."), (
            f"{token} maps to {glyph!r}, which is not a literal Icons.* constant; "
            "Flutter web can only tree-shake statically referenced glyphs"
        )


def test_the_fallback_glyph_is_not_a_theme_glyph() -> None:
    dart = _dart_token_map(
        THEME_CHIPS_DART.read_text(encoding="utf-8"), "kThemeIconsByToken"
    )
    fallback = dart[pal.FALLBACK_THEME_ICON]
    theme_glyphs = {dart[token] for token in pal.THEME_ICONS.values()}
    assert fallback not in theme_glyphs


def test_the_dart_test_mirrors_this_table_exactly() -> None:
    """The Dart suite keeps its own copy of the table; keep the copies honest."""
    mirror = _dart_token_map(
        THEME_ICONS_DART_TEST.read_text(encoding="utf-8"), "_canonicalThemeTokens"
    )
    assert {k: v.strip().strip("'") for k, v in mirror.items()} == dict(pal.THEME_ICONS)

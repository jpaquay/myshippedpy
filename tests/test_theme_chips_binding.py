"""The themeChips data binding, pinned on the side that can be tested here.

The renderer used to log ``Missing data: themeChips no themes bound to items``.
The surface was describing the chips ONLY as a ChildTemplate over
``/themes/items`` with a ``ThemeChip`` prototype, and Flutter's catalog ships
ThemeChips as one self-drawing widget with no ThemeChip builder at all: it never
expands the template, it binds the array under ``items`` with ``selected`` /
``title`` beside it and one node-level ``action``.  So the chips were described
correctly and bound to nothing.

These tests assert the emitted surface JSON carries the keys the Dart widget
actually looks up -- including on the raw stream the MCP server publishes, which
is the copy that never passed through the REST router's Flutter adapter.
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
from app.a2ui import surfaces as sfc  # noqa: E402
from app.sonic.corridors import list_corridors  # noqa: E402
from app.sonic.themes import list_themes  # noqa: E402

THEME_CHIPS_DART = _ROOT / "frontend" / "lib" / "a2ui" / "components" / "theme_chips.dart"


@pytest.fixture
def stream() -> list[dict[str, Any]]:
    """The surface exactly as ``build_themes_surface`` publishes it.

    No Flutter adaptation: this is what the MCP server emits and what
    ``frontend/a2ui/catalog.json`` documents.
    """
    return sfc.build_themes_surface(
        list_themes(), list_corridors(), selected_theme="sirocco"
    )


def _node(stream: list[dict[str, Any]], component_id: str) -> dict[str, Any]:
    for message in stream:
        for key in ("updateComponents", "createSurface"):
            block = message.get(key)
            if isinstance(block, dict):
                for component in block.get("components") or []:
                    if component.get("id") == component_id:
                        return component
    raise AssertionError(f"{component_id} is not in the stream")


def _data(stream: list[dict[str, Any]]) -> dict[str, Any]:
    for message in stream:
        block = message.get("updateDataModel")
        if isinstance(block, dict) and block.get("path") in ("/", ""):
            return block["contents"]
        block = message.get("createSurface")
        if isinstance(block, dict) and isinstance(block.get("dataModel"), dict):
            return block["dataModel"]
    raise AssertionError("no data model in the stream")


# --------------------------------------------------------------------------- #
# The component node
# --------------------------------------------------------------------------- #


def test_theme_chips_bind_the_array_and_not_only_a_template(stream) -> None:
    """The regression proper: ``items`` must point at the theme array."""
    chips = _node(stream, "themeChips")
    assert chips["items"] == {"path": "/themes/items"}, (
        "themeChips does not bind /themes/items -- this is the "
        '"no themes bound to items" defect'
    )
    assert chips["selected"] == {"path": "/themes/selectedThemeId"}
    assert chips["title"] == {"path": "/themes/label"}


def test_theme_chips_still_declare_the_template_for_generic_renderers(stream) -> None:
    """Fixing one renderer must not break the other one."""
    chips = _node(stream, "themeChips")
    assert chips["chips"] == {"componentId": "themeChip", "dataBinding": "/themes/items"}
    assert _node(stream, "themeChip")["component"] == "ThemeChip"


def test_theme_chips_carry_a_node_level_select_action(stream) -> None:
    """The widget fires one action for the whole list, adding the tapped id."""
    action = _node(stream, "themeChips")["action"]
    assert action["action"] == cat.FN_SELECT_THEME


def test_the_array_and_the_template_read_the_same_pointer(stream) -> None:
    chips = _node(stream, "themeChips")
    assert chips["items"]["path"] == chips["chips"]["dataBinding"]


# --------------------------------------------------------------------------- #
# The item shape
# --------------------------------------------------------------------------- #


def test_every_theme_item_carries_what_a_chip_draws(stream) -> None:
    items = _data(stream)["themes"]["items"]
    assert len(items) == 8
    for item in items:
        # `id` is what the list-rendering widget reads; `themeId` is what the
        # ChildTemplate prototype binds. They must never disagree.
        assert item["id"] == item["themeId"]
        assert item["name"] and item["tagline"]
        assert isinstance(item["selected"], bool)
        palette = item["palette"]
        assert {"accent", "primary", "base", "ink"} <= set(palette)
        for value in palette.values():
            assert re.fullmatch(r"#[0-9A-Fa-f]{6}", value), value


def test_the_selected_chip_is_the_selected_theme(stream) -> None:
    data = _data(stream)["themes"]
    assert data["selectedThemeId"] == "sirocco"
    selected = [i["id"] for i in data["items"] if i["selected"]]
    assert selected == ["sirocco"]


# --------------------------------------------------------------------------- #
# Cross-language pin: the Dart widget names these keys, so the surface must too
# --------------------------------------------------------------------------- #


def test_the_keys_the_dart_widget_reads_are_the_keys_we_emit() -> None:
    """Read the renderer's own lookups out of the Dart source and check them.

    A rename on either side turns this red, which is the whole point: the
    binding contract has no other enforcement between the two languages.
    """
    source = THEME_CHIPS_DART.read_text(encoding="utf-8")

    node_keys = set(re.findall(r"node\.(?:list|string|map|number|boolean)\('(\w+)'\)", source))
    assert {"items", "selected", "title"} <= node_keys, (
        f"{THEME_CHIPS_DART.name} no longer reads the keys this test pins: {node_keys}"
    )
    assert "node.action()" in source, "the widget no longer fires a node-level action"

    item_keys = set(re.findall(r"theme\['(\w+)'\]", source))
    assert {"id", "name", "tagline"} <= item_keys

    chips = _node(
        sfc.build_themes_surface(list_themes(), list_corridors()), "themeChips"
    )
    for key in ("items", "selected", "title", "action"):
        assert key in chips, f"surface does not emit {key!r}, which theme_chips.dart reads"


def test_the_catalog_declares_the_properties_the_surface_emits() -> None:
    """"If a property is not declared here, no surface may use it." -- catalog.py"""
    declared = set(cat.COMPONENTS["ThemeChips"]["properties"])
    assert {"chips", "items", "selected", "title", "action"} <= declared


# --------------------------------------------------------------------------- #
# End to end over HTTP, the way the Flutter client actually fetches it
# --------------------------------------------------------------------------- #


def test_the_flutter_payload_binds_items_and_drops_the_dangling_template(client) -> None:  # noqa: ANN001
    messages = client.get("/api/surfaces/themes").json()
    chips = _node(messages, "themeChips")
    assert chips["items"] == {"path": "/themes/items"}
    # The prototype component is filtered out of the Flutter payload, so a
    # template pointing at it would reference a node that never arrives.
    assert "chips" not in chips
    assert all(c.get("component") != "ThemeChip" for c in messages[1]["updateComponents"]["components"])

    items = _data(messages)["themes"]["items"]
    assert len(items) == 8
    assert all(item["id"] and item["palette"] for item in items)

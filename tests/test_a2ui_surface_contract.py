"""The Python half of the cross-language surface contract.

``frontend/test/fixtures/a2ui_surfaces.json`` is the seam between the surface
builders and the Flutter renderer: Python writes it, Dart renders it. This
module keeps it honest from the Python side -- it must be exactly what the
builders emit today -- and asserts the binding invariant that the renderer
depends on and that nothing here used to check.

Why this exists: three separate regressions shipped because a component was
described in a form the Flutter catalog cannot bind. Every one of them passed
the whole Python suite, because the Python suite only ever asked whether the
payload was *well-formed*, never whether anything could *render* it.

The rule, in one line: **a self-drawing feature component must carry its array
under a key the renderer reads, emitted by the surface builder itself** -- not
patched in by the REST adapter on its way to Flutter, which is what made the
app look fine while the MCP stream and the published catalog stayed broken.

See ``frontend/test/a2ui_surface_contract_test.dart`` for the other half, which
drives the real renderer over the same file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

_TESTS = Path(__file__).resolve().parent
_ROOT = _TESTS.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.gen_a2ui_fixtures import (  # noqa: E402
    FIXTURE_PATH,
    build_surface_fixtures,
    surface_fixtures_json,
)

#: Component type -> the property names its Flutter widget will accept the
#: array/object under, in the order the widget tries them.
#:
#: Keep this in step with ``frontend/lib/a2ui/components/*.dart``. If you add a
#: self-drawing feature component, add it here; if you rename the property a
#: widget reads, this table is where the two languages are reconciled.
SELF_DRAWING_BINDINGS: dict[str, tuple[str, ...]] = {
    "ThemeChips": ("items", "themes"),
    "GenreCorridor": ("items", "corridors"),
    "TrackList": ("tracks", "items"),
    "AlmanacTimeline": ("entries", "items"),
    "TelemetryInspector": ("entries", "trajectories", "items"),
}


def _is_path_binding(value: Any) -> bool:
    """True for ``{"path": "/a/b"}`` and nothing else.

    A ``ChildTemplate`` (``{"componentId": ..., "dataBinding": ...}``) is NOT a
    path binding. That distinction is the entire bug: the renderer resolves a
    property through ``DynamicValue.parse``, which turns an unrecognised map
    into a literal object, so a template under a data key silently reads as
    "no data" rather than as a list.
    """
    return isinstance(value, dict) and isinstance(value.get("path"), str)


def _components(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in messages:
        if "createSurface" in message:
            out.extend(message["createSurface"].get("components") or [])
        if "updateComponents" in message:
            out.extend(message["updateComponents"]["components"] or [])
    return out


def _merged_properties(component: dict[str, Any]) -> dict[str, Any]:
    """Every property, however the emitter chose to nest it.

    A2UI serialises properties FLAT, as siblings of ``id``. The REST adapter
    additionally puts some under ``properties``. The renderer merges both, so
    this must too, or the test would disagree with the thing it is testing.
    """
    merged = {
        key: value
        for key, value in component.items()
        if key not in {"id", "component", "type", "componentType", "properties", "componentProperties"}
    }
    merged.update(component.get("componentProperties") or {})
    merged.update(component.get("properties") or {})
    return merged


# --------------------------------------------------------------------------- #
# 1. The fixture is current
# --------------------------------------------------------------------------- #


def test_the_checked_in_fixture_matches_the_builders():
    """Regenerate with ``.venv/bin/python -m scripts.gen_a2ui_fixtures``.

    This failing is not a bug -- it means you changed a surface. Regenerate,
    then read the Dart contract test's verdict on whether the new shape still
    renders.
    """
    assert FIXTURE_PATH.exists(), (
        f"{FIXTURE_PATH} is missing; regenerate it with\n"
        f"  .venv/bin/python -m scripts.gen_a2ui_fixtures"
    )
    assert FIXTURE_PATH.read_text(encoding="utf-8") == surface_fixtures_json(), (
        "The checked-in A2UI surface fixture is stale. A surface builder "
        "changed without the contract being refreshed. Run\n"
        "  .venv/bin/python -m scripts.gen_a2ui_fixtures\n"
        "and then run `flutter test` -- the Dart half will tell you whether "
        "the new shape can still be rendered."
    )


def test_the_fixture_is_deterministic():
    """Two runs, same bytes. A fixture with a clock in it is not a contract."""
    assert surface_fixtures_json() == surface_fixtures_json()


# --------------------------------------------------------------------------- #
# 2. The binding invariant
# --------------------------------------------------------------------------- #


_FIXTURES = build_surface_fixtures()

_SELF_DRAWING_CASES = [
    pytest.param(surface, shape, component, id=f"{surface}-{shape}-{component['id']}")
    for surface, shapes in _FIXTURES.items()
    for shape, messages in shapes.items()
    for component in _components(messages)
    if component.get("component") in SELF_DRAWING_BINDINGS
]


@pytest.mark.parametrize("surface,shape,component", _SELF_DRAWING_CASES)
def test_self_drawing_components_bind_their_array(
    surface: str, shape: str, component: dict[str, Any]
):
    """The invariant the renderer actually depends on.

    ``GenreCorridor`` described its corridors only as a ``ChildTemplate`` over
    ``options``. That is legal A2UI and it validated cleanly -- and Flutter,
    which ships GenreCorridor as one self-drawing widget and registers no
    GenreOption builder, never expanded the template and rendered

        Missing data: "genreCorridor": no corridors bound to "items"

    Both published shapes are checked. ``raw`` is what ``surfaces.py`` emits and
    what the MCP stream serves; ``flutter`` is the same messages after the REST
    adapter. Checking only the adapted shape is how this stayed hidden.
    """
    ctype = component["component"]
    accepted = SELF_DRAWING_BINDINGS[ctype]
    properties = _merged_properties(component)

    bound = [key for key in accepted if _is_path_binding(properties.get(key))]

    assert bound, (
        f'{surface}/{shape}: {ctype} "{component["id"]}" binds none of '
        f"{list(accepted)} to a JSON Pointer.\n"
        f"  present keys: {sorted(properties)}\n"
        f"  values found: "
        f"{ {k: properties.get(k) for k in accepted if k in properties} }\n\n"
        "The Flutter widget draws this list itself, so a ChildTemplate over a "
        "prototype it has no builder for resolves to nothing and the component "
        "degrades to a grey placeholder. Emit the array as a path binding from "
        "the surface builder -- not from the REST adapter, which only fixes one "
        "of the two consumers."
    )


def test_every_self_drawing_component_is_covered():
    """A component that quietly stops being emitted stops being tested."""
    seen = {
        component["component"]
        for _, _, component in (
            (case.values[0], case.values[1], case.values[2])
            for case in _SELF_DRAWING_CASES
        )
    }
    assert seen == set(SELF_DRAWING_BINDINGS), (
        f"not exercised by any fixture surface: {set(SELF_DRAWING_BINDINGS) - seen}"
    )


def test_the_data_the_arrays_point_at_is_actually_populated():
    """A correct pointer into an empty model still renders an empty component."""
    for surface, shapes in _FIXTURES.items():
        for shape, messages in shapes.items():
            model: dict[str, Any] = {}
            for message in messages:
                udm = message.get("updateDataModel")
                if udm and udm.get("path") in ("/", ""):
                    model = udm.get("contents") or {}

            for component in _components(messages):
                ctype = component.get("component")
                if ctype not in SELF_DRAWING_BINDINGS:
                    continue
                properties = _merged_properties(component)
                for key in SELF_DRAWING_BINDINGS[ctype]:
                    value = properties.get(key)
                    if not _is_path_binding(value):
                        continue
                    cursor: Any = model
                    for segment in value["path"].strip("/").split("/"):
                        assert isinstance(cursor, dict) and segment in cursor, (
                            f"{surface}/{shape}: {ctype} binds {key} -> "
                            f'{value["path"]}, which is not in the data model'
                        )
                        cursor = cursor[segment]
                    assert isinstance(cursor, list) and cursor, (
                        f"{surface}/{shape}: {ctype} binds {key} -> "
                        f'{value["path"]}, which is not a non-empty list'
                    )
                    break


# --------------------------------------------------------------------------- #
# 3. The fixture itself
# --------------------------------------------------------------------------- #


def test_the_fixture_publishes_both_shapes_of_every_surface():
    on_disk = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert sorted(on_disk) == [
        "almanac",
        "error",
        "playlist",
        "rationale",
        "sky",
        "telemetry",
        "themes",
    ]
    for surface, shapes in on_disk.items():
        assert sorted(shapes) == ["flutter", "raw"], surface
        for shape, messages in shapes.items():
            assert messages, f"{surface}/{shape} is empty"
            assert "createSurface" in messages[0], f"{surface}/{shape}"

"""Tests for the BAROGROOVE A2UI layer. No network, no services, no I/O beyond
reading the generated catalog file.

These tests are deliberately structural rather than snapshot-based: they encode
the invariants the OTHER two workers depend on (the MCP server and the Flutter
renderer), so a change that would break either of them fails here first.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import pytest

_TESTS = Path(__file__).resolve().parent
_ROOT = _TESTS.parent
sys.path.insert(0, str(_ROOT / "backend"))

from app.a2ui import catalog as cat  # noqa: E402
from app.a2ui import palette as pal  # noqa: E402
from app.a2ui import protocol as proto  # noqa: E402
from app.a2ui import surfaces as sfc  # noqa: E402
from app.contracts import (  # noqa: E402
    SKY_DIMS,
    Coordinates,
    GenreCorridor,
    Playlist,
    Rationale,
    ScoredTrack,
    SkyVector,
    SonicVector,
    Theme,
    Track,
)

CATALOG_JSON_PATH = _ROOT / "frontend" / "a2ui" / "catalog.json"

_MISSING = object()


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def sky() -> SkyVector:
    # SkyVector dims are NORMALISED, not raw physical readings: the signed dims
    # live in [-1, 1] and the unsigned ones in [0, 1]. The raw quantities
    # (-9.2 hPa/6h, 2.5 mm/h) belong in `notes`, which is exactly where the
    # rationale card reads them from.
    return SkyVector(
        pressure_trend_6h=-0.88,        # a steep 6h fall, near the practical extreme
        pressure_norm_deviation=-0.79,  # well below this location's own weekly norm
        temp_norm_deviation=0.42,       # warm sector ahead of the front
        sun_elevation=0.18,             # low, but still above the horizon
        golden_hour_proximity=0.72,
        gust_variance=0.64,             # unsettled, not merely windy
        cloud_depth=0.83,
        precip_intensity=0.55,          # steady rain
        daylight_delta=-0.31,           # the year closing in
        observed_at=datetime(2026, 3, 14, 17, 5, tzinfo=timezone.utc),
        coordinates=Coordinates(latitude=50.8503, longitude=4.3517, label="Brussels"),
        stale=False,
        notes=["pressure fell 9.2 hPa in 6h", "38 min to sunset", "gusts swinging 14-33 km/h"],
    )


@pytest.fixture
def themes() -> list[Theme]:
    return [
        Theme(
            id=theme_id,
            name=theme_id.replace("_", " ").title(),
            tagline=pal.THEME_INTENT[theme_id],
            # `description` and `bias` are required by the frozen contract. The real
            # copy and bias vectors live in backend/app/sonic/themes.py; these
            # surface tests only care that a Theme renders, so a placeholder keeps
            # the fixture honest without duplicating another module's voice.
            description=pal.THEME_INTENT[theme_id],
            bias=SonicVector.neutral(),
            palette=dict(pal.THEME_PALETTES[theme_id]),
        )
        for theme_id in pal.THEME_IDS
    ]


@pytest.fixture
def corridors() -> list[GenreCorridor]:
    return [
        GenreCorridor(
            id="krautrock",
            name="Krautrock",
            description="Motorik pulse, patient repetition.",
            tags=["krautrock", "motorik"],
            width=0.4,
        ),
        GenreCorridor(
            id="ambient",
            name="Ambient",
            description="Space before notes.",
            tags=["ambient", "drone"],
            width=0.7,
        ),
    ]


@pytest.fixture
def rationale() -> Rationale:
    return Rationale(
        headline="Pressure fell nine hectopascals; the music leans in.",
        body="A six-hour collapse of this size usually lands as restlessness.",
        sky_reading=[
            "Pressure trend -9.2 hPa/6h — the steepest fall in a fortnight.",
            "Gust variance 7.4 m/s — the wind is not settled.",
        ],
        sonic_moves=["energy +0.18", "acousticness -0.12", "grit +0.09"],
        taste_note="You reach for motorik when the barometer drops.",
        confidence=0.82,
        degraded=[],
    )


@pytest.fixture
def playlist(sky: SkyVector, rationale: Rationale) -> Playlist:
    roles = ["opener", "build", "peak", "descent", "closer"]
    tracks = [
        ScoredTrack(
            track=Track(
                title=f"Track {i}",
                artist=f"Artist {i}",
                duration_ms=210_000 + i * 1000,
                spotify_uri=f"spotify:track:{i:022d}",
                tags=["krautrock"],
            ),
            score=0.9 - i * 0.05,
            sonic_distance=0.1 + i * 0.02,
            role=roles[i % len(roles)],
            position=i + 1,
            why=f"Sits at {i + 1} because the fall wants momentum here.",
        )
        for i in range(7)
    ]
    return Playlist(
        id="pl-001",
        title="Nine Hectopascals Down",
        subtitle="Petrichor × krautrock",
        tracks=tracks,
        sky=sky,
        # The target the forge actually aimed at: pulled down and inward by a
        # collapsing barometer, with the reverb opened up.
        sonic_target=SonicVector(
            valence=0.31, energy=0.38, tempo=0.28,
            acousticness=0.44, density=0.52, grit=0.47, spatiality=0.78,
        ),
        theme_id="petrichor",
        genre_id="krautrock",
        rationale=rationale,
        created_at=datetime(2026, 3, 14, 17, 6, tzinfo=timezone.utc),
        coordinates=Coordinates(latitude=50.8503, longitude=4.3517, label="Brussels"),
    )


@pytest.fixture
def all_streams(
    sky: SkyVector,
    themes: list[Theme],
    corridors: list[GenreCorridor],
    playlist: Playlist,
    rationale: Rationale,
) -> dict[str, list[dict[str, Any]]]:
    """One stream per builder, keyed by builder name."""
    return {
        "sky": sfc.build_sky_surface(sky),
        "themes": sfc.build_themes_surface(
            themes, corridors, selected_theme="petrichor", selected_genre="krautrock"
        ),
        "playlist": sfc.build_playlist_surface(playlist),
        "rationale": sfc.build_rationale_surface(rationale),
        "almanac": sfc.build_almanac_surface([playlist]),
        "error": sfc.build_error_surface("Boom.", detail="upstream 503"),
    }


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _components(stream: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = list(stream[0]["createSurface"].get("components") or [])
    for message in stream:
        if "updateComponents" in message:
            out.extend(message["updateComponents"]["components"])
    return out


def _data_model(stream: list[dict[str, Any]]) -> dict[str, Any]:
    data: dict[str, Any] = dict(stream[0]["createSurface"].get("dataModel") or {})
    for message in stream:
        if "updateDataModel" in message and message["updateDataModel"]["path"] == "/":
            data.update(message["updateDataModel"]["contents"])
    return data


def _templates(components: list[dict[str, Any]]) -> dict[str, str]:
    """componentId -> bound array pointer, for every ChildList template in use."""
    found: dict[str, str] = {}
    for component in components:
        for value in component.values():
            if isinstance(value, dict) and "componentId" in value and "dataBinding" in value:
                found[value["componentId"]] = value["dataBinding"]
    return found


def _walk(node: Any) -> Iterator[Any]:
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _pointers(node: Any) -> list[str]:
    return [
        n["path"]
        for n in _walk(node)
        if isinstance(n, dict) and set(n) == {"path"} and isinstance(n["path"], str)
    ]


def _keys(node: Any) -> Iterator[str]:
    for n in _walk(node):
        if isinstance(n, dict):
            yield from n.keys()


def _resolve(data: Any, pointer: str) -> Any:
    current = data
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                return _MISSING
            current = current[token]
        elif isinstance(current, list):
            if not token.isdigit() or int(token) >= len(current):
                return _MISSING
            current = current[int(token)]
        else:
            return _MISSING
    return current


def _actions(node: Any) -> list[dict[str, Any]]:
    return [
        n
        for n in _walk(node)
        if isinstance(n, dict) and "action" in n and isinstance(n.get("action"), str)
    ]


def _bindable(component_type: str) -> list[str]:
    definition = cat.COMPONENTS[component_type]
    return definition["metadata"]["extensions"]["barogroove"]["bindable"]


# --------------------------------------------------------------------------- #
# 1. Envelope / stream validity
# --------------------------------------------------------------------------- #


def test_every_builder_emits_a_valid_stream(all_streams):
    for name, stream in all_streams.items():
        proto.validate_stream(stream), name


def test_exactly_one_key_per_message(all_streams):
    for name, stream in all_streams.items():
        for message in stream:
            assert len(message) == 1, f"{name}: envelope carries {sorted(message)}"
            key = proto.validate_envelope(message)
            assert key in proto.AGENT_ENVELOPE_KEYS


def test_stream_order_is_create_components_data(all_streams):
    for name, stream in all_streams.items():
        assert [next(iter(m)) for m in stream] == [
            "createSurface",
            "updateComponents",
            "updateDataModel",
        ], name


def test_every_stream_has_a_root_component(all_streams):
    for name, stream in all_streams.items():
        root = proto.find_root(_components(stream))
        assert root["id"] == proto.ROOT_COMPONENT_ID, name
        assert root["component"] != proto.SURFACE_COMPONENT


def test_surface_id_is_consistent_within_a_stream(all_streams):
    for name, stream in all_streams.items():
        ids = {list(m.values())[0]["surfaceId"] for m in stream}
        assert len(ids) == 1, f"{name}: mixed surfaceIds {ids}"
        assert list(ids)[0].startswith("bg-")


def test_surface_ids_are_unique_across_builds(sky):
    ids = {sfc.build_sky_surface(sky)[0]["createSurface"]["surfaceId"] for _ in range(25)}
    assert len(ids) == 25, "surfaceId must be globally unique for the renderer lifetime"


def test_explicit_surface_id_is_honoured(sky):
    stream = sfc.build_sky_surface(sky, surface_id="fixed-id")
    assert all(list(m.values())[0]["surfaceId"] == "fixed-id" for m in stream)


def test_envelope_wrapper_rejects_zero_or_two_keys():
    with pytest.raises(Exception):
        proto.AgentMessage()
    with pytest.raises(Exception):
        proto.AgentMessage(
            create_surface=proto.CreateSurface(surface_id="s1"),
            delete_surface=proto.DeleteSurface(surface_id="s1"),
        )


def test_validate_envelope_rejects_unknown_and_multi_keys():
    with pytest.raises(proto.A2UIProtocolError):
        proto.validate_envelope({"createSurface": {}, "deleteSurface": {}})
    with pytest.raises(proto.A2UIProtocolError):
        proto.validate_envelope({"nope": {}})


def test_validate_stream_rejects_missing_root():
    bad = proto.stream(
        [
            proto.CreateSurface(surface_id="s1"),
            proto.UpdateComponents(
                surface_id="s1",
                components=[proto.Component(id="notRoot", component="Notice")],
            ),
        ]
    )
    with pytest.raises(proto.A2UIProtocolError, match="root"):
        proto.validate_stream(bad)


def test_reserved_surface_component_cannot_be_built():
    with pytest.raises(Exception):
        proto.Component(id="root", component="Surface")


# --------------------------------------------------------------------------- #
# 2. Spec-shaped camelCase serialisation
# --------------------------------------------------------------------------- #

_CAMEL = re.compile(r"^[a-z$][A-Za-z0-9]*$")


def test_no_snake_case_keys_anywhere_on_the_wire(all_streams):
    for name, stream in all_streams.items():
        for key in _keys(stream):
            assert "_" not in key, f"{name}: non-camelCase key {key!r} on the wire"


def test_all_wire_keys_are_camel_case(all_streams):
    for name, stream in all_streams.items():
        for key in _keys(stream):
            assert _CAMEL.match(key), f"{name}: {key!r} is not camelCase"


def test_create_surface_uses_v1_field_names(all_streams):
    allowed = {
        "surfaceId",
        "catalogId",
        "surfaceProperties",
        "sendDataModel",
        "components",
        "dataModel",
        "metadata",
    }
    for name, stream in all_streams.items():
        create = stream[0]["createSurface"]
        assert set(create) <= allowed, f"{name}: unexpected {set(create) - allowed}"
        assert create["catalogId"] == cat.CATALOG_ID
        # v1.0 renamed `theme` -> `surfaceProperties`.
        assert "theme" not in create
        assert "surfaceProperties" in create
        assert create["surfaceProperties"]["colorScheme"] == "light"


def test_data_bindings_use_the_path_object_form(all_streams):
    for name, stream in all_streams.items():
        for component in _components(stream):
            for key, value in component.items():
                if isinstance(value, dict) and "path" in value:
                    assert set(value) == {"path"}, f"{name}.{component['id']}.{key}"
                    assert value["path"].startswith("/")


def test_helpers_round_trip_to_spec_shape():
    assert proto.envelope(proto.DeleteSurface(surface_id="s1")) == {
        "deleteSurface": {"surfaceId": "s1"}
    }
    assert proto.envelope(
        proto.UpdateDataModel(surface_id="s1", path="/a", contents={"b": 1})
    ) == {"updateDataModel": {"surfaceId": "s1", "path": "/a", "contents": {"b": 1}}}
    assert len(proto.stream([proto.DeleteSurface(surface_id="s1")])) == 1


# --------------------------------------------------------------------------- #
# 3. Data lives in the data model, never inlined in the component tree
# --------------------------------------------------------------------------- #


def test_bindable_properties_are_never_inlined(all_streams):
    """Every property the catalog marks bindable must arrive as a JSON Pointer."""
    for name, stream in all_streams.items():
        for component in _components(stream):
            for key in _bindable(component["component"]):
                if key not in component:
                    continue
                value = component[key]
                assert isinstance(value, dict) and "path" in value, (
                    f"{name}: {component['id']}.{key} is inlined as {value!r}; "
                    "data belongs in the data model"
                )


def test_components_carry_no_literal_prose(all_streams):
    """A component may hold layout tokens and enum-ish literals, never sentences."""
    for name, stream in all_streams.items():
        for component in _components(stream):
            for key, value in component.items():
                if key in {"id", "component", "catalogId"}:
                    continue
                if isinstance(value, str):
                    assert " " not in value, (
                        f"{name}: {component['id']}.{key} = {value!r} looks like copy "
                        "inlined into the component tree"
                    )


def test_surface_scope_pointers_all_resolve(all_streams):
    """Non-template components bind against the surface data model."""
    for name, stream in all_streams.items():
        components = _components(stream)
        data = _data_model(stream)
        template_ids = set(_templates(components))
        for component in components:
            if component["id"] in template_ids:
                continue
            for pointer in _pointers(component):
                assert _resolve(data, pointer) is not _MISSING, (
                    f"{name}: {component['id']} binds {pointer} which is not in the data model"
                )


def test_template_scope_pointers_resolve_against_items(all_streams):
    """Inside a template, pointers resolve relative to the current list item."""
    for name, stream in all_streams.items():
        components = _components(stream)
        data = _data_model(stream)
        templates = _templates(components)
        by_id = {c["id"]: c for c in components}
        for component_id, array_pointer in templates.items():
            items = _resolve(data, array_pointer)
            assert isinstance(items, list), f"{name}: {array_pointer} is not a list"
            assert items, f"{name}: {array_pointer} is empty; nothing to render"
            item = items[0]
            for pointer in _pointers(by_id[component_id]):
                assert _resolve(item, pointer) is not _MISSING, (
                    f"{name}: template {component_id} binds {pointer}, "
                    f"absent from items of {array_pointer}"
                )


def test_data_model_carries_the_actual_values(all_streams, playlist, sky):
    data = _data_model(all_streams["playlist"])
    assert data["playlist"]["title"] == playlist.title
    assert len(data["playlist"]["tracks"]) == len(playlist.tracks)
    assert data["rationale"]["headline"] == playlist.rationale.headline

    sky_data = _data_model(all_streams["sky"])["sky"]
    assert sky_data["heroDimension"] == cat.HERO_SKY_DIM
    assert len(sky_data["dimensions"]) == len(SKY_DIMS)


# --------------------------------------------------------------------------- #
# 4. Lists use the ChildList template form
# --------------------------------------------------------------------------- #


def test_track_list_uses_the_template_child_list_form(all_streams):
    components = {c["id"]: c for c in _components(all_streams["playlist"])}
    rows = components["trackList"]["rows"]
    assert isinstance(rows, dict), "TrackList.rows must be the ChildList object form"
    assert rows == {"componentId": "trackRow", "dataBinding": "/playlist/tracks"}
    assert components["trackRow"]["component"] == "TrackRow"


def test_track_list_emits_one_row_component_not_n(playlist):
    """Seven tracks, four components. That is the point of the template form."""
    stream = sfc.build_playlist_surface(playlist)
    components = _components(stream)
    assert len(playlist.tracks) == 7
    assert len(components) == 4
    assert sum(1 for c in components if c["component"] == "TrackRow") == 1


def test_all_list_bearing_components_use_templates(all_streams):
    expected = {
        "sky": ("skyDial", "spokes", "skySpoke", "/sky/dimensions"),
        "themes": ("themeChips", "chips", "themeChip", "/themes/items"),
        "playlist": ("trackList", "rows", "trackRow", "/playlist/tracks"),
        "almanac": ("almanac", "entries", "almanacEntry", "/almanac/entries"),
    }
    for stream_name, (host, prop, template, pointer) in expected.items():
        components = {c["id"]: c for c in _components(all_streams[stream_name])}
        assert components[host][prop] == {"componentId": template, "dataBinding": pointer}

    genre = {c["id"]: c for c in _components(all_streams["themes"])}["genreCorridor"]
    assert genre["options"] == {"componentId": "genreOption", "dataBinding": "/genres/items"}


def test_root_children_use_the_array_form(all_streams):
    for name, stream in all_streams.items():
        root = proto.find_root(_components(stream))
        assert isinstance(root["children"], list), name
        assert all(isinstance(child, str) for child in root["children"])


def test_child_template_rejects_a_non_pointer():
    with pytest.raises(Exception):
        proto.ChildTemplate(component_id="x", data_binding="tracks")


# --------------------------------------------------------------------------- #
# 5. Palettes
# --------------------------------------------------------------------------- #


def test_there_are_exactly_eight_themes():
    assert len(pal.THEME_IDS) == 8
    assert set(pal.THEME_IDS) == set(pal.THEME_PALETTES)
    assert set(pal.THEME_IDS) == set(pal.THEME_INTENT)


def test_every_palette_is_complete_and_well_formed_hex():
    for theme_id in pal.THEME_IDS:
        palette = pal.THEME_PALETTES[theme_id]
        for key in pal.PALETTE_KEYS:
            assert key in palette, f"{theme_id} is missing {key}"
            assert pal.is_hex(palette[key]), f"{theme_id}.{key} = {palette[key]!r}"
        for value in palette.values():
            assert pal.is_hex(value), f"{theme_id}: {value!r} is not #RRGGBB"


def test_every_palette_clears_its_contrast_floor():
    assert pal.audit_palettes() == []


def test_light_mode_is_the_default_and_the_register_is_kept():
    for theme_id in pal.THEME_IDS:
        properties = pal.surface_properties_for(theme_id)
        assert properties["colorScheme"] == "light"
        assert properties["contrast"] == "high"
        palette = properties["palette"]
        # Canvas stays a near-white wash in every theme: no dark or neon surfaces.
        assert pal.relative_luminance(palette["canvas"]) > 0.8
        # Ink stays a near-black slate.
        assert pal.relative_luminance(palette["ink"]) < 0.05


def test_unknown_theme_falls_back_rather_than_raising():
    assert pal.surface_properties_for("no-such-theme")["palette"] == pal.BASE
    assert pal.surface_properties_for(None)["palette"] == pal.BASE


def test_contrast_ratio_maths():
    assert pal.contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0, abs=0.01)
    assert pal.contrast_ratio("#FFFFFF", "#FFFFFF") == pytest.approx(1.0, abs=0.01)


def test_theme_chip_swatches_come_from_the_palette(all_streams):
    items = _data_model(all_streams["themes"])["themes"]["items"]
    assert len(items) == 8
    for item in items:
        for key in ("swatchAccent", "swatchSoft", "swatchInk"):
            assert pal.is_hex(item[key]), item


# --------------------------------------------------------------------------- #
# 6. Catalog integrity
# --------------------------------------------------------------------------- #


def test_catalog_json_on_disk_matches_the_python_catalog():
    assert CATALOG_JSON_PATH.exists(), (
        f"{CATALOG_JSON_PATH} is missing; regenerate it with catalog_json()"
    )
    on_disk = json.loads(CATALOG_JSON_PATH.read_text(encoding="utf-8"))
    assert on_disk == cat.CATALOG
    # Byte-identical too, so the Flutter worker can diff the file meaningfully.
    assert CATALOG_JSON_PATH.read_text(encoding="utf-8") == cat.catalog_json()


def test_catalog_declares_the_six_feature_components():
    declared = cat.CATALOG["metadata"]["extensions"]["barogroove"]["featureComponents"]
    assert declared == [
        "SkyDial",
        "ThemeChips",
        "GenreCorridor",
        "TrackList",
        "RationaleCard",
        "AlmanacTimeline",
    ]
    for name in declared:
        assert name in cat.COMPONENTS


def test_every_component_obeys_the_discriminator_rule():
    for name, definition in cat.COMPONENTS.items():
        assert definition["properties"]["component"]["const"] == name
        assert "component" in definition["required"]
        assert definition["additionalProperties"] is False


def test_child_bearing_properties_reference_the_child_list_type():
    for name, definition in cat.COMPONENTS.items():
        for prop, schema in definition["properties"].items():
            if prop in {"children", "rows", "chips", "options", "entries", "spokes"}:
                assert schema["$ref"].endswith("ChildList"), f"{name}.{prop}"


def test_sky_dial_weighting_makes_derivatives_dominant():
    """The whole argument of the SkyDial: change beats state."""
    assert cat.HERO_SKY_DIM == "pressure_trend_6h"
    assert cat.SKY_DIM_TIERS[cat.HERO_SKY_DIM] == "hero"
    assert cat.SKY_DIM_WEIGHTS[cat.HERO_SKY_DIM] == max(cat.SKY_DIM_WEIGHTS.values())
    derivative = [d for d, t in cat.SKY_DIM_TIERS.items() if t in {"hero", "derivative"}]
    state = [d for d, t in cat.SKY_DIM_TIERS.items() if t == "state"]
    assert len(derivative) == 6 and len(state) == 3
    assert min(cat.SKY_DIM_WEIGHTS[d] for d in derivative) > max(
        cat.SKY_DIM_WEIGHTS[s] for s in state
    )
    assert set(cat.SKY_DIM_TIERS) == set(SKY_DIMS)


def test_emitted_spokes_are_ordered_by_weight(all_streams):
    dims = _data_model(all_streams["sky"])["sky"]["dimensions"]
    weights = [d["weight"] for d in dims]
    assert weights == sorted(weights, reverse=True)
    assert dims[0]["dimensionId"] == cat.HERO_SKY_DIM
    assert dims[0]["tier"] == "hero"


def test_rationale_card_is_rendered_first_on_the_playlist_surface(all_streams):
    """The explanation is a feature, not a footnote: it leads the surface."""
    root = proto.find_root(_components(all_streams["playlist"]))
    assert root["children"][0] == "rationale"
    assert root["children"] == ["rationale", "trackList"]
    card = {c["id"]: c for c in _components(all_streams["playlist"])}["rationale"]
    assert card["component"] == "RationaleCard"
    assert card["emphasis"] == "hero"


def test_theme_and_genre_are_separate_components(all_streams):
    """Two axes, two panels -- a crossing, not a hierarchy."""
    components = {c["id"]: c for c in _components(all_streams["themes"])}
    assert components["themeChips"]["component"] == "ThemeChips"
    assert components["genreCorridor"]["component"] == "GenreCorridor"
    root = proto.find_root(list(components.values()))
    assert root["children"] == ["themeChips", "genreCorridor"]
    data = _data_model(all_streams["themes"])
    assert "×" in data["genres"]["crossingLabel"]
    assert data["themes"]["axisNote"].startswith("Axis 1")
    assert data["genres"]["axisNote"].startswith("Axis 2")


def test_almanac_entries_carry_their_badge_and_tint(all_streams):
    entries = _data_model(all_streams["almanac"])["almanac"]["entries"]
    assert entries[0]["badge"] == "your rain sound"
    assert pal.is_hex(entries[0]["accent"])


def test_catalog_functions_are_a_map_with_v1_metadata():
    functions = cat.CATALOG["functions"]
    assert isinstance(functions, dict) and functions
    for name, definition in functions.items():
        assert name.startswith("barogroove.")
        assert definition["allowedCallers"] in {
            "rendererOnly",
            "agentOnly",
            "rendererOrAgent",
        }
        assert "requiresUserActivation" in definition
        assert definition["parameters"]["type"] == "object"


# --------------------------------------------------------------------------- #
# 7. Action round trips validate against the declared signatures
# --------------------------------------------------------------------------- #


def test_every_emitted_action_names_a_declared_function(all_streams):
    seen: set[str] = set()
    for name, stream in all_streams.items():
        for action in _actions(_components(stream)):
            assert action["action"] in cat.FUNCTIONS, f"{name}: {action['action']}"
            seen.add(action["action"])
    # The three round trips the brief calls out must actually be wired.
    assert {cat.FN_SELECT_THEME, cat.FN_SELECT_GENRE, cat.FN_TRACK_FEEDBACK} <= seen


def test_every_emitted_action_context_matches_its_signature(all_streams):
    """The keys a component promises to send must be the keys the function declares."""
    for name, stream in all_streams.items():
        for action in _actions(_components(stream)):
            definition = cat.function_definition(action["action"])
            declared = set(definition.parameters.get("properties", {}))
            required = set(definition.parameters.get("required", []))
            context = set(action.get("context") or {})
            assert context <= declared, (
                f"{name}: {action['action']} sends {context - declared}, undeclared"
            )
            assert required <= context, (
                f"{name}: {action['action']} omits required {required - context}"
            )


def test_resolved_action_payloads_validate(all_streams, playlist):
    """Resolve a real action's bindings against real data, then validate it."""
    components = {c["id"]: c for c in _components(all_streams["playlist"])}
    data = _data_model(all_streams["playlist"])
    item = data["playlist"]["tracks"][0]

    for handler in ("onLove", "onSkip"):
        action = components["trackRow"][handler]
        payload = {
            key: (_resolve(item, value["path"]) if isinstance(value, dict) else value)
            for key, value in action["context"].items()
        }
        assert _MISSING not in payload.values()
        assert cat.validate_action(action["action"], payload) == payload

    chip = {c["id"]: c for c in _components(all_streams["themes"])}["themeChip"]
    theme_item = _data_model(all_streams["themes"])["themes"]["items"][0]
    payload = {
        key: _resolve(theme_item, value["path"])
        for key, value in chip["onSelect"]["context"].items()
    }
    assert cat.validate_action(cat.FN_SELECT_THEME, payload) == payload


@pytest.mark.parametrize(
    "name,payload",
    [
        (cat.FN_SELECT_THEME, {"themeId": "petrichor"}),
        (cat.FN_SELECT_GENRE, {"genreId": "krautrock"}),
        (cat.FN_SET_CORRIDOR_WIDTH, {"genreId": "krautrock", "width": 0.4}),
        (cat.FN_TRACK_FEEDBACK, {"trackKey": "a|b", "verdict": "loved", "position": 2}),
        (cat.FN_EXPLAIN_DIMENSION, {"dimension": "pressure_trend_6h"}),
        (cat.FN_OPEN_ALMANAC_ENTRY, {"playlistId": "pl-001"}),
        (cat.FN_REFRESH_SKY, {"lat": 50.85, "lon": 4.35}),
        (cat.FN_FORGE, {"themeId": "petrichor", "genreId": "krautrock"}),
    ],
)
def test_good_action_payloads_validate(name, payload):
    assert cat.validate_action(name, payload) == payload


@pytest.mark.parametrize(
    "name,payload,reason",
    [
        (cat.FN_SELECT_THEME, {}, "missing required"),
        (cat.FN_SELECT_THEME, {"themeId": "neon_rave"}, "not an enum member"),
        (cat.FN_TRACK_FEEDBACK, {"trackKey": "a|b", "verdict": "meh"}, "bad enum"),
        (cat.FN_TRACK_FEEDBACK, {"trackKey": 7, "verdict": "loved"}, "bad type"),
        (cat.FN_EXPLAIN_DIMENSION, {"dimension": "humidity"}, "unknown dimension"),
        (cat.FN_SELECT_GENRE, {"genreId": "x", "surprise": 1}, "undeclared argument"),
    ],
)
def test_bad_action_payloads_are_rejected(name, payload, reason):
    with pytest.raises(proto.A2UIProtocolError):
        cat.validate_action(name, payload)


def test_unknown_action_name_is_rejected():
    with pytest.raises(KeyError):
        cat.validate_action("barogroove.nope", {})


def test_theme_selection_round_trip_is_data_only():
    """The dividend of keeping data out of the tree: no components are resent."""
    messages = sfc.patch_selection("s1", theme_id="petrichor")
    assert [next(iter(m)) for m in messages] == ["updateDataModel"]
    assert messages[0]["updateDataModel"] == {
        "surfaceId": "s1",
        "path": "/themes",
        "contents": {"selectedThemeId": "petrichor"},
    }


def test_genre_and_width_round_trip():
    messages = sfc.patch_selection("s1", genre_id="ambient", width=0.8)
    contents = messages[0]["updateDataModel"]["contents"]
    assert contents["selectedGenreId"] == "ambient"
    assert contents["width"] == 0.8
    assert contents["widthLabel"] == "loose"


def test_track_feedback_round_trip_patches_one_row():
    messages = sfc.patch_track_feedback("s1", index=3, verdict="loved")
    payload = messages[0]["updateDataModel"]
    assert payload["path"] == "/playlist/tracks/3"
    assert payload["contents"] == {"loved": True, "skipped": False}
    for message in messages:
        proto.validate_envelope(message)


def test_agent_function_response_shape():
    message = sfc.agent_function_response("s1", "call-9", result={"ok": True})
    assert proto.validate_envelope(message) == "agentFunctionResponse"
    assert message["agentFunctionResponse"] == {
        "surfaceId": "s1",
        "callId": "call-9",
        "result": {"ok": True},
    }


def test_agent_function_response_needs_result_xor_error():
    with pytest.raises(Exception):
        sfc.agent_function_response("s1", "c1")
    with pytest.raises(Exception):
        sfc.agent_function_response("s1", "c1", result={"a": 1}, error={"b": 2})


# --------------------------------------------------------------------------- #
# 8. v1.0 single-message UI instantiation
# --------------------------------------------------------------------------- #


def test_single_message_collapse_is_equivalent(all_streams):
    for name, stream in all_streams.items():
        folded = sfc.single_message(stream)
        assert len(folded) == 1, name
        create = folded[0]["createSurface"]
        assert create["surfaceId"] == stream[0]["createSurface"]["surfaceId"]
        assert create["components"] == stream[1]["updateComponents"]["components"]
        assert create["dataModel"] == stream[2]["updateDataModel"]["contents"]
        proto.validate_stream(folded)


def test_single_message_stream_still_has_a_root(all_streams):
    for stream in all_streams.values():
        proto.find_root(sfc.single_message(stream)[0]["createSurface"]["components"])


# --------------------------------------------------------------------------- #
# 9. Error surface
# --------------------------------------------------------------------------- #


def test_error_surface_states_the_problem_and_offers_a_retry(all_streams):
    stream = all_streams["error"]
    notice = {c["id"]: c for c in _components(stream)}["notice"]
    assert notice["component"] == "Notice"
    assert notice["tone"] == "critical"
    assert notice["onRetry"]["action"] == cat.FN_RETRY
    data = _data_model(stream)["error"]
    assert data["message"] == "Boom."
    assert data["detail"] == "upstream 503"


def test_empty_almanac_still_renders():
    stream = sfc.build_almanac_surface([])
    proto.validate_stream(stream)
    assert _data_model(stream)["almanac"]["entryCount"] == 0


def test_playlist_with_no_tracks_still_renders(playlist):
    empty = playlist.model_copy(update={"tracks": []})
    stream = sfc.build_playlist_surface(empty)
    proto.validate_stream(stream)
    assert _data_model(stream)["playlist"]["trackCount"] == 0

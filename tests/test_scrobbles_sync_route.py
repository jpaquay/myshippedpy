"""The scrobbles-sync endpoint's contract, as the Flutter client now calls it.

Production logged::

    GET /api/almanac/scrobbles/sync%3Flastfm_user=jpaquay -> 404

The ``?`` was percent-encoded because the client concatenated a query string
onto the *path* argument, and ``BgConfig.resolve`` puts that argument through
``Uri.replace(path: ...)``, which escapes it. These tests pin both halves: the
mangled path really is a 404, and the properly-formed call is not.
"""

from __future__ import annotations

from typing import Any


def test_the_percent_encoded_query_is_not_a_route(client: Any) -> None:
    """Reproduces the logged URL verbatim. It is a path, and no route has it."""
    res = client.post("/api/almanac/scrobbles/sync%3Flastfm_user=jpaquay")

    assert res.status_code == 404


def test_sync_requires_a_lastfm_username(client: Any) -> None:
    """No default. It used to fall back to a real person's handle."""
    res = client.post(
        "/api/almanac/scrobbles/sync", headers={"X-Barogroove-User": "uid-jerome"}
    )

    assert res.status_code == 422


def test_sync_accepts_the_username_as_a_query_parameter(client: Any) -> None:
    """The shape the fixed client sends: query params, not a glued-on string."""
    res = client.post(
        "/api/almanac/scrobbles/sync?lastfm_user=someone",
        headers={"X-Barogroove-User": "uid-jerome"},
    )

    assert res.status_code != 404, "the route must exist at this path"
    assert res.status_code != 422, res.text

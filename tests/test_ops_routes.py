"""The root route, as uptime checks and link unfurlers actually hit it.

Production logged ``GET / -> 405`` on both bg.netdev.be and
barogroove.netdev.be. The requests were HEADs: FastAPI's ``APIRoute`` does not
derive HEAD from GET the way Starlette's plain ``Route`` does, so ``/``
answered 405 to every probe that did not want a body.
"""

from __future__ import annotations

from typing import Any


def test_root_answers_get(client: Any) -> None:
    res = client.get("/")

    assert res.status_code == 200
    assert res.json()["service"] == "BAROGROOVE"


def test_root_answers_head(client: Any) -> None:
    res = client.head("/")

    assert res.status_code == 200
    assert res.content == b"", "HEAD must not carry a body"


def test_root_still_refuses_a_write(client: Any) -> None:
    assert client.post("/").status_code == 405

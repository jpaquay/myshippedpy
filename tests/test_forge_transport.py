"""Upstream transport policy: bounded timeouts, retry, and retry SAFETY.

The load-bearing tests here are the ones asserting what is *not* retried.
Retrying a read is free. Retrying a write is how ``POST /v1/playlists/{id}/
tracks`` puts every track in twice, so the policy keys off the HTTP method and
these tests pin that down.

No network: every case runs against an ``httpx.MockTransport``.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, TypeVar

import httpx
import pytest

from backend.app import http as bghttp

T = TypeVar("T")


def run(coro: Awaitable[T]) -> T:
    return asyncio.run(coro)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _no_real_sleeping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the backoff curve, drop the wall-clock cost of walking it."""
    real_sleep = asyncio.sleep

    async def _instant(_seconds: float) -> None:
        await real_sleep(0)

    monkeypatch.setattr(bghttp.asyncio, "sleep", _instant)


class _Recorder:
    """Counts attempts and replays a scripted sequence of outcomes."""

    def __init__(self, *outcomes: Any) -> None:
        self.calls: list[httpx.Request] = []
        self._outcomes = list(outcomes)

    @property
    def count(self) -> int:
        return len(self.calls)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        idx = min(len(self.calls) - 1, len(self._outcomes) - 1)
        outcome = self._outcomes[idx]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _install(monkeypatch: pytest.MonkeyPatch, rec: _Recorder) -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(rec.handler))

    async def _get_client(_settings: Any = None) -> httpx.AsyncClient:
        return client

    monkeypatch.setattr(bghttp, "get_client", _get_client)


def _ok(payload: Any = None) -> httpx.Response:
    return httpx.Response(200, json=payload if payload is not None else {"ok": True})


def _boom(code: int = 503) -> httpx.Response:
    return httpx.Response(code, json={"error": "upstream sulking"})


# ===========================================================================
# Idempotent methods get the full policy
# ===========================================================================


def test_a_get_retries_a_5xx_and_eventually_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = _Recorder(_boom(), _boom(), _ok({"v": 1}))
    _install(monkeypatch, rec)

    out = run(bghttp.get_json("https://x.test/a", service="t"))
    assert out == {"v": 1}
    assert rec.count == 3


def test_a_get_retries_a_read_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = _Recorder(httpx.ReadTimeout("slow"), _ok({"v": 2}))
    _install(monkeypatch, rec)

    assert run(bghttp.get_json("https://x.test/a", service="t")) == {"v": 2}
    assert rec.count == 2


def test_a_get_gives_up_after_a_bounded_number_of_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = _Recorder(_boom())
    _install(monkeypatch, rec)

    with pytest.raises(bghttp.UpstreamError):
        run(bghttp.get_json("https://x.test/a", service="t", max_retries=2))
    assert rec.count == 3  # 1 initial + 2 retries, then stop


def test_a_put_is_idempotent_and_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    # PUT sets state to a value; doing it twice lands on the same value.
    rec = _Recorder(_boom(), _ok({"v": 3}))
    _install(monkeypatch, rec)

    assert run(bghttp.put_json("https://x.test/lib", service="t")) == {"v": 3}
    assert rec.count == 2


# ===========================================================================
# Writes are NOT retried — the safety rule
# ===========================================================================


def test_a_post_is_not_retried_on_a_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    """The server saw it. Sending it again may create a second playlist."""
    rec = _Recorder(_boom(), _ok())
    _install(monkeypatch, rec)

    with pytest.raises(bghttp.UpstreamError):
        run(bghttp.post_json("https://x.test/playlists", service="t", json_body={"a": 1}))
    assert rec.count == 1


def test_a_post_is_not_retried_on_a_read_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """The subtle one: the request may have been delivered and acted upon."""
    rec = _Recorder(httpx.ReadTimeout("slow"), _ok())
    _install(monkeypatch, rec)

    with pytest.raises(bghttp.UpstreamError):
        run(bghttp.post_json("https://x.test/playlists", service="t", json_body={"a": 1}))
    assert rec.count == 1


def test_a_post_is_not_retried_on_a_429(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = _Recorder(httpx.Response(429, headers={"Retry-After": "1"}, json={}), _ok())
    _install(monkeypatch, rec)

    with pytest.raises(bghttp.UpstreamError):
        run(bghttp.post_json("https://x.test/playlists", service="t"))
    assert rec.count == 1


def test_a_post_IS_retried_on_a_connect_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """The one safe case: no connection, so the server never saw a thing."""
    rec = _Recorder(httpx.ConnectError("refused"), _ok({"v": 4}))
    _install(monkeypatch, rec)

    assert run(bghttp.post_json("https://x.test/playlists", service="t")) == {"v": 4}
    assert rec.count == 2


# ===========================================================================
# Explicit overrides
# ===========================================================================


def test_an_idempotency_key_lets_a_post_opt_back_into_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What the forge job start does: the key makes a repeat provably safe."""
    rec = _Recorder(_boom(), _boom(), _ok({"job": "j1"}))
    _install(monkeypatch, rec)

    out = run(
        bghttp.post_json(
            "https://x.test/forge/jobs",
            service="t",
            params={"job_id": "k1"},
            idempotent=True,
        )
    )
    assert out == {"job": "j1"}
    assert rec.count == 3
    # Every attempt carried the same key, which is the entire safety argument.
    assert {r.url.params.get("job_id") for r in rec.calls} == {"k1"}


def test_idempotent_false_forbids_retrying_even_a_get(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = _Recorder(_boom(), _ok())
    _install(monkeypatch, rec)

    with pytest.raises(bghttp.UpstreamError):
        run(bghttp.get_json("https://x.test/a", service="t", idempotent=False))
    assert rec.count == 1


# ===========================================================================
# Bounds and non-transient answers
# ===========================================================================


def test_a_403_is_never_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Nov 2024 deprecation cliff, not an outage."""
    rec = _Recorder(httpx.Response(403, json={}))
    _install(monkeypatch, rec)

    with pytest.raises(bghttp.UpstreamError) as caught:
        run(bghttp.get_json("https://x.test/audio-features", service="spotify"))
    assert caught.value.is_deprecation
    assert rec.count == 1


def test_a_4xx_is_an_answer_and_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = _Recorder(httpx.Response(422, json={"detail": "nope"}))
    _install(monkeypatch, rec)

    with pytest.raises(bghttp.UpstreamError):
        run(bghttp.get_json("https://x.test/a", service="t"))
    assert rec.count == 1


def test_an_exhausted_budget_stops_the_retry_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """A zero budget means there is no room to back off, so do not."""
    rec = _Recorder(_boom())
    _install(monkeypatch, rec)

    with pytest.raises(bghttp.UpstreamError):
        run(bghttp.get_json("https://x.test/a", service="t", budget_s=0.0))
    assert rec.count == 1


def test_the_method_policy_table_is_what_we_think_it_is() -> None:
    assert "GET" in bghttp.IDEMPOTENT_METHODS
    assert "PUT" in bghttp.IDEMPOTENT_METHODS
    assert "DELETE" in bghttp.IDEMPOTENT_METHODS
    assert "POST" not in bghttp.IDEMPOTENT_METHODS
    assert "PATCH" not in bghttp.IDEMPOTENT_METHODS

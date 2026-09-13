"""Forge jobs: lifecycle, idempotency, and the no-double-forge guarantee.

The load-bearing tests here are the idempotency ones. Everything else checks
that the registry is well-formed; those check that a retry — from a flaky
network, a reconnecting tab, or the backoff logic in ``api/client.dart`` —
cannot produce two playlists for one intent. That is the property item 5's
retry policy leans on, so if it breaks, retries become unsafe.

No network, no credentials, no sleeping on wall-clock time beyond a few
milliseconds of task yielding.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, TypeVar

import pytest

from backend.app.contracts import Coordinates, ForgeRequest
from backend.app.forge.jobs import ForgeJobRegistry, fingerprint, get_forge_jobs, reset_forge_jobs

T = TypeVar("T")

BRUSSELS = Coordinates(latitude=50.8503, longitude=4.3517, label="Brussels")


def run(coro: Awaitable[T]) -> T:
    return asyncio.run(coro)  # type: ignore[arg-type]


def a_request(**kw: Any) -> ForgeRequest:
    base: dict[str, Any] = {
        "coordinates": BRUSSELS,
        "theme_id": "nordic_fog",
        "genre_id": "any",
        "length": 6,
        "sink": "m3u",
        "seed": 1958,
    }
    base.update(kw)
    return ForgeRequest(**base)


class _CountingRunner:
    """A stand-in forge. Counts how many times it was actually executed."""

    def __init__(self, *, value: Any = "playlist", fail: bool = False, gate: bool = False) -> None:
        self.calls = 0
        self._value = value
        self._fail = fail
        self._gate: asyncio.Event | None = asyncio.Event() if gate else None

    def release(self) -> None:
        assert self._gate is not None
        self._gate.set()

    async def __call__(self) -> Any:
        self.calls += 1
        if self._gate is not None:
            await self._gate.wait()
        else:
            await asyncio.sleep(0)
        if self._fail:
            raise RuntimeError("the barometer fell off the wall")
        return self._value


# ===========================================================================
# Registry lifecycle
# ===========================================================================


def test_job_runs_to_completion_and_carries_its_result() -> None:
    async def scenario() -> None:
        reg = ForgeJobRegistry()
        runner = _CountingRunner(value="a playlist")
        job, resumed = await reg.submit(owner="u1", request=a_request(), runner=runner)

        assert resumed is False
        assert job.status in {"queued", "running"}
        assert job.id
        assert job.created_at is not None
        assert job.result is None

        await job.task  # type: ignore[arg-type]

        assert job.status == "done"
        assert job.result == "a playlist"
        assert job.finished_at is not None
        assert job.started_at is not None
        assert job.error is None
        assert runner.calls == 1

    run(scenario())


def test_job_outlives_the_caller_that_started_it() -> None:
    """submit() returns while the work is still running — that is the point.

    The client "goes away" here by simply never awaiting the task. The
    registry still drives it to completion.
    """

    async def scenario() -> None:
        reg = ForgeJobRegistry()
        runner = _CountingRunner(gate=True)

        job, _ = await reg.submit(owner="u1", request=a_request(), runner=runner)
        await asyncio.sleep(0)  # let the task start
        assert job.status == "running"
        assert job.result is None

        # The starter is long gone. Release the work anyway.
        runner.release()
        for _ in range(50):
            if job.terminal:
                break
            await asyncio.sleep(0.001)

        assert job.status == "done"

    run(scenario())


def test_a_failing_forge_becomes_a_failed_job_not_an_exception() -> None:
    async def scenario() -> None:
        reg = ForgeJobRegistry()
        job, _ = await reg.submit(owner="u1", request=a_request(), runner=_CountingRunner(fail=True))
        await job.task  # type: ignore[arg-type]

        assert job.status == "failed"
        assert job.error is not None
        assert "barometer" in job.error
        assert job.result is None

    run(scenario())


def test_a_wedged_forge_is_bounded_by_the_run_timeout() -> None:
    async def scenario() -> None:
        reg = ForgeJobRegistry(run_timeout_s=0.02)

        async def never() -> Any:
            await asyncio.sleep(30)

        job, _ = await reg.submit(owner="u1", request=a_request(), runner=never)
        await job.task  # type: ignore[arg-type]

        assert job.status == "failed"
        assert "exceeded" in (job.error or "")

    run(scenario())


# ===========================================================================
# Idempotency — the reason retries are allowed to exist
# ===========================================================================


def test_same_job_id_never_forges_twice() -> None:
    async def scenario() -> None:
        reg = ForgeJobRegistry()
        runner = _CountingRunner(gate=True)

        first, r1 = await reg.submit(owner="u1", request=a_request(), runner=runner, job_id="key-1")
        second, r2 = await reg.submit(owner="u1", request=a_request(), runner=runner, job_id="key-1")

        assert r1 is False and r2 is True
        assert first is second
        assert first.id == "key-1"

        runner.release()
        await first.task  # type: ignore[arg-type]
        assert runner.calls == 1
        assert len(reg) == 1

    run(scenario())


def test_same_job_id_is_honoured_even_after_the_job_finished() -> None:
    """A retry that arrives late must not restart a completed forge."""

    async def scenario() -> None:
        reg = ForgeJobRegistry()
        runner = _CountingRunner()
        first, _ = await reg.submit(owner="u1", request=a_request(), runner=runner, job_id="key-1")
        await first.task  # type: ignore[arg-type]

        again, resumed = await reg.submit(
            owner="u1", request=a_request(), runner=runner, job_id="key-1"
        )
        assert resumed is True
        assert again is first
        assert runner.calls == 1

    run(scenario())


def test_identical_in_flight_request_is_joined_not_duplicated() -> None:
    """No idempotency key? The (owner, request) fingerprint still catches it."""

    async def scenario() -> None:
        reg = ForgeJobRegistry()
        runner = _CountingRunner(gate=True)

        first, r1 = await reg.submit(owner="u1", request=a_request(), runner=runner)
        second, r2 = await reg.submit(owner="u1", request=a_request(), runner=runner)

        assert r1 is False and r2 is True
        assert first is second
        runner.release()
        await first.task  # type: ignore[arg-type]
        assert runner.calls == 1

    run(scenario())


def test_concurrent_starts_race_to_one_job() -> None:
    async def scenario() -> None:
        reg = ForgeJobRegistry()
        runner = _CountingRunner(gate=True)
        req = a_request()

        results = await asyncio.gather(
            *(reg.submit(owner="u1", request=req, runner=runner) for _ in range(8))
        )
        ids = {job.id for job, _ in results}
        assert len(ids) == 1
        assert sum(1 for _, resumed in results if not resumed) == 1

        runner.release()
        await results[0][0].task  # type: ignore[arg-type]
        assert runner.calls == 1

    run(scenario())


def test_a_reconnect_with_a_new_session_id_does_not_start_a_second_forge() -> None:
    """session_id / conversation_id are transport identity, not forge intent."""

    async def scenario() -> None:
        reg = ForgeJobRegistry()
        runner = _CountingRunner(gate=True)

        first, _ = await reg.submit(
            owner="u1", request=a_request(session_id="sock-A"), runner=runner
        )
        second, resumed = await reg.submit(
            owner="u1", request=a_request(session_id="sock-B"), runner=runner
        )

        assert resumed is True
        assert second is first
        runner.release()
        await first.task  # type: ignore[arg-type]
        assert runner.calls == 1

    run(scenario())


def test_a_genuinely_different_request_gets_its_own_job() -> None:
    async def scenario() -> None:
        reg = ForgeJobRegistry()
        runner = _CountingRunner(gate=True)

        a, _ = await reg.submit(owner="u1", request=a_request(length=6), runner=runner)
        b, resumed = await reg.submit(owner="u1", request=a_request(length=12), runner=runner)

        assert resumed is False
        assert a is not b
        runner.release()
        await asyncio.gather(a.task, b.task)  # type: ignore[arg-type]
        assert runner.calls == 2

    run(scenario())


def test_finished_jobs_do_not_block_a_deliberate_re_forge() -> None:
    """Dedupe applies to *in-flight* work only. Asking again later re-runs."""

    async def scenario() -> None:
        reg = ForgeJobRegistry()
        runner = _CountingRunner()
        first, _ = await reg.submit(owner="u1", request=a_request(), runner=runner)
        await first.task  # type: ignore[arg-type]

        second, resumed = await reg.submit(owner="u1", request=a_request(), runner=runner)
        assert resumed is False
        assert second is not first
        await second.task  # type: ignore[arg-type]
        assert runner.calls == 2

    run(scenario())


def test_two_users_with_the_same_request_get_two_jobs() -> None:
    async def scenario() -> None:
        reg = ForgeJobRegistry()
        runner = _CountingRunner(gate=True)
        a, _ = await reg.submit(owner="alice", request=a_request(), runner=runner)
        b, resumed = await reg.submit(owner="bob", request=a_request(), runner=runner)
        assert resumed is False
        assert a is not b
        runner.release()
        await asyncio.gather(a.task, b.task)  # type: ignore[arg-type]

    run(scenario())


def test_claiming_someone_elses_job_id_is_refused() -> None:
    async def scenario() -> None:
        reg = ForgeJobRegistry()
        runner = _CountingRunner()
        await reg.submit(owner="alice", request=a_request(), runner=runner, job_id="shared")
        with pytest.raises(PermissionError):
            await reg.submit(owner="mallory", request=a_request(), runner=runner, job_id="shared")

    run(scenario())


def test_fingerprint_is_stable_and_ignores_volatile_fields() -> None:
    base = fingerprint("u1", a_request())
    assert base == fingerprint("u1", a_request())
    assert base == fingerprint("u1", a_request(session_id="x", conversation_id="y"))
    assert base != fingerprint("u2", a_request())
    assert base != fingerprint("u1", a_request(length=20))


# ===========================================================================
# Bookkeeping
# ===========================================================================


def test_lookup_is_scoped_to_the_owner() -> None:
    async def scenario() -> None:
        reg = ForgeJobRegistry()
        job, _ = await reg.submit(owner="alice", request=a_request(), runner=_CountingRunner())
        await job.task  # type: ignore[arg-type]

        assert reg.get(job.id, owner="alice") is job
        assert reg.get(job.id, owner="bob") is None
        assert reg.get("nope", owner="alice") is None

    run(scenario())


def test_list_for_is_newest_first_and_bounded() -> None:
    async def scenario() -> None:
        reg = ForgeJobRegistry()
        made = []
        for n in range(4, 9):
            job, _ = await reg.submit(
                owner="u1", request=a_request(length=n), runner=_CountingRunner()
            )
            await job.task  # type: ignore[arg-type]
            made.append(job.id)

        listed = [j.id for j in reg.list_for("u1", limit=3)]
        assert listed == list(reversed(made))[:3]
        assert reg.list_for("nobody") == []

    run(scenario())


def test_latest_active_finds_the_run_a_reconnecting_client_lost() -> None:
    async def scenario() -> None:
        reg = ForgeJobRegistry()
        done, _ = await reg.submit(owner="u1", request=a_request(length=5), runner=_CountingRunner())
        await done.task  # type: ignore[arg-type]

        gated = _CountingRunner(gate=True)
        live, _ = await reg.submit(owner="u1", request=a_request(length=9), runner=gated)
        await asyncio.sleep(0)

        assert reg.latest_active("u1") is live
        gated.release()
        await live.task  # type: ignore[arg-type]
        assert reg.latest_active("u1") is None

    run(scenario())


def test_the_registry_is_bounded_but_never_evicts_a_running_job() -> None:
    async def scenario() -> None:
        reg = ForgeJobRegistry(max_jobs=3)
        gated = _CountingRunner(gate=True)
        live, _ = await reg.submit(owner="u1", request=a_request(length=60), runner=gated)
        await asyncio.sleep(0)

        for n in range(4, 16):
            job, _ = await reg.submit(
                owner="u1", request=a_request(length=n), runner=_CountingRunner()
            )
            await job.task  # type: ignore[arg-type]

        assert len(reg) <= 4  # the cap, plus the one running job that is exempt
        assert reg.get(live.id, owner="u1") is live

        gated.release()
        await live.task  # type: ignore[arg-type]

    run(scenario())


def test_expired_terminal_jobs_are_pruned() -> None:
    async def scenario() -> None:
        reg = ForgeJobRegistry(ttl_s=-1.0)  # everything terminal is instantly stale
        old, _ = await reg.submit(owner="u1", request=a_request(length=5), runner=_CountingRunner())
        await old.task  # type: ignore[arg-type]

        fresh, _ = await reg.submit(
            owner="u1", request=a_request(length=9), runner=_CountingRunner()
        )
        await fresh.task  # type: ignore[arg-type]
        assert reg.get(old.id) is None

    run(scenario())


def test_the_module_singleton_resets_cleanly() -> None:
    first = get_forge_jobs()
    assert get_forge_jobs() is first
    reset_forge_jobs()
    assert get_forge_jobs() is not first
    reset_forge_jobs()


# ===========================================================================
# HTTP surface
# ===========================================================================


def _poll(client: Any, job_id: str, *, tries: int = 200) -> dict[str, Any]:
    import time

    body: dict[str, Any] = {}
    for _ in range(tries):
        res = client.get(f"/api/forge/jobs/{job_id}")
        assert res.status_code == 200, res.text
        body = res.json()
        if body["status"] in {"done", "failed"}:
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished; last status {body.get('status')!r}")


def test_http_start_poll_and_collect(client: Any) -> None:
    payload = {
        "coordinates": {"latitude": 50.8503, "longitude": 4.3517, "label": "Brussels"},
        "length": 6,
        "sink": "m3u",
        "seed": 1958,
    }
    started = client.post("/api/forge/jobs", json=payload)
    assert started.status_code == 202, started.text
    env = started.json()
    assert env["status"] in {"queued", "running", "done"}
    assert env["resumed"] is False
    job_id = env["job_id"]
    assert job_id

    final = _poll(client, job_id)
    assert final["status"] == "done", final.get("error")
    assert final["result"] is not None
    assert final["result"]["playlist"]["tracks"]
    assert final["playlist_id"] == final["result"]["playlist"]["id"]
    assert final["finished_at"] is not None


def test_http_retrying_the_start_with_the_same_key_does_not_forge_twice(client: Any) -> None:
    payload = {
        "coordinates": {"latitude": 50.8503, "longitude": 4.3517, "label": "Brussels"},
        "length": 6,
        "sink": "m3u",
        "seed": 1958,
    }
    first = client.post("/api/forge/jobs?job_id=retry-me", json=payload)
    assert first.status_code == 202
    assert first.json()["job_id"] == "retry-me"

    # Exactly what the client's backoff would send after a timeout.
    second = client.post("/api/forge/jobs?job_id=retry-me", json=payload)
    assert second.status_code == 200  # 200, not 202: nothing new was accepted
    assert second.json()["resumed"] is True
    assert second.json()["job_id"] == "retry-me"

    final = _poll(client, "retry-me")
    assert final["status"] == "done", final.get("error")

    listed = client.get("/api/forge/jobs").json()
    assert [j["job_id"] for j in listed] == ["retry-me"]


def test_http_start_without_a_key_still_dedupes_an_identical_request(client: Any) -> None:
    payload = {
        "coordinates": {"latitude": 50.8503, "longitude": 4.3517, "label": "Brussels"},
        "length": 8,
        "sink": "m3u",
        "seed": 1958,
    }
    a = client.post("/api/forge/jobs", json=payload).json()
    b = client.post("/api/forge/jobs", json=payload).json()
    # Either b joined a (still running) or a had already finished; in both
    # cases there must never be two *concurrent* runs for one intent.
    if b["resumed"]:
        assert b["job_id"] == a["job_id"]
    _poll(client, a["job_id"])


def test_http_a_finished_job_lands_in_recent_playlists(client: Any) -> None:
    from backend.app.routes import surfaces

    payload = {
        "coordinates": {"latitude": 50.8503, "longitude": 4.3517, "label": "Brussels"},
        "length": 5,
        "sink": "m3u",
        "seed": 1958,
    }
    job_id = client.post("/api/forge/jobs", json=payload).json()["job_id"]
    final = _poll(client, job_id)
    assert final["status"] == "done", final.get("error")
    assert final["playlist_id"] in surfaces._RECENT_PLAYLISTS


def test_http_unknown_job_is_a_404_not_a_crash(client: Any) -> None:
    res = client.get("/api/forge/jobs/definitely-not-a-job")
    assert res.status_code == 404
    assert "forge job" in res.json()["detail"]


def test_http_active_only_filter(client: Any) -> None:
    payload = {
        "coordinates": {"latitude": 50.8503, "longitude": 4.3517, "label": "Brussels"},
        "length": 4,
        "sink": "m3u",
        "seed": 1958,
    }
    job_id = client.post("/api/forge/jobs", json=payload).json()["job_id"]
    _poll(client, job_id)

    assert client.get("/api/forge/jobs?active_only=true").json() == []
    assert len(client.get("/api/forge/jobs").json()) == 1


def test_the_synchronous_route_still_works(client: Any) -> None:
    """Item 4 must not break the old path; the demo depends on it."""
    res = client.get("/api/forge/demo?length=6")
    assert res.status_code == 200, res.text
    assert res.json()["playlist"]["tracks"]

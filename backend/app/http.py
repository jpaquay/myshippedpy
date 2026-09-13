"""One resilient HTTP client for every upstream.

House rules, enforced here so no connector has to remember them:

* Every request has a connect timeout **and** a read timeout.
* Retries are bounded, exponential, jittered, and only on transient failures
  (429, 5xx, connect errors). A 403 from Spotify is *not* transient — that is
  the November 2024 deprecation talking, and retrying it is just rudeness.
* ``Retry-After`` is honoured when present. Last.fm and Spotify both send it.
* The *whole* call is bounded, not just each attempt: a total budget caps
  attempts plus backoff, so a wedged upstream cannot hold a request open for
  ``retries × (timeout + 12s)``.
* Failures raise :class:`UpstreamError`, which carries enough context for the
  caller to decide between "degrade" and "give up".

Retry safety — read this before widening anything
-------------------------------------------------
A retry is only free if repeating the call cannot change the world twice.
That is a property of the *operation*, not of the error, so the policy keys
off the HTTP method:

``GET`` / ``HEAD`` / ``OPTIONS`` / ``PUT`` / ``DELETE``
    Idempotent by definition. Full policy: retried on connect errors, read
    timeouts, 429 and 5xx.

``POST`` (and anything else)
    Assumed to change state. Retried **only** on a connect error — the one
    failure mode where we know the request never reached the server, because
    no connection was ever established. A read timeout is explicitly *not*
    retried: the server may well have acted and only the response was lost,
    and "probably fine" is not a standard to duplicate a user's playlist on.
    A 5xx is likewise not retried; the server definitely saw the request.

This is not theoretical. ``POST /v1/users/{id}/playlists`` and
``POST /v1/playlists/{id}/tracks`` in ``sinks/spotify.py`` both used to be
retried on a 5xx, which is how you end up with two playlists, or one playlist
with every track twice. Callers that know better can override with
``idempotent=True`` — the forge job start does exactly that, because its
``job_id`` is an idempotency key the server dedupes on.

Connectors should never construct their own ``httpx.AsyncClient``.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Mapping

import httpx

from .config import Settings, get_settings

log = logging.getLogger("barogroove.http")

#: Statuses worth trying again. 403 is deliberately absent.
RETRYABLE_STATUS: frozenset[int] = frozenset({408, 425, 429, 500, 502, 503, 504})

#: Statuses that mean "this endpoint is gone, stop asking" — the Nov 2024 cliff.
DEPRECATED_STATUS: frozenset[int] = frozenset({403, 404, 410})

#: Methods whose repetition is a no-op on the server, per RFC 9110. These get
#: the full retry policy; everything else is treated as state-changing.
IDEMPOTENT_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})

#: Extra wall-clock slack on top of (attempts x per-request timeout), covering
#: the jittered backoff sleeps. Keeps the worst case finite and predictable.
TOTAL_BUDGET_SLACK_S: float = 15.0


class UpstreamError(RuntimeError):
    """An upstream call failed after exhausting its retry budget."""

    def __init__(
        self,
        service: str,
        message: str,
        *,
        status: int | None = None,
        retryable: bool = False,
        url: str | None = None,
    ) -> None:
        super().__init__(f"[{service}] {message}")
        self.service = service
        self.status = status
        self.retryable = retryable
        self.url = url

    @property
    def is_deprecation(self) -> bool:
        """True when this smells like a retired endpoint rather than an outage."""
        return self.status in DEPRECATED_STATUS


@dataclass(slots=True)
class ClientStats:
    """Cheap observability. Surfaced at ``/api/health`` so demos can be debugged."""

    requests: int = 0
    retries: int = 0
    failures: int = 0
    by_service: dict[str, int] = field(default_factory=dict)


_STATS = ClientStats()
_CLIENT: httpx.AsyncClient | None = None
_LOCK = asyncio.Lock()


def stats() -> ClientStats:
    return _STATS


async def get_client(settings: Settings | None = None) -> httpx.AsyncClient:
    """Lazily create the shared client. One connection pool for the process."""
    global _CLIENT
    if _CLIENT is not None and not _CLIENT.is_closed:
        return _CLIENT
    async with _LOCK:
        if _CLIENT is None or _CLIENT.is_closed:
            s = settings or get_settings()
            _CLIENT = httpx.AsyncClient(
                timeout=httpx.Timeout(s.http_timeout_s, connect=s.http_connect_timeout_s),
                follow_redirects=True,
                headers={"User-Agent": "barogroove/1.0 (+https://bg.netdev.be)"},
                limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
            )
    return _CLIENT


async def close_client() -> None:
    """Shut the pool down on app teardown."""
    global _CLIENT
    if _CLIENT is not None and not _CLIENT.is_closed:
        await _CLIENT.aclose()
    _CLIENT = None


def reset_client() -> None:
    """Drop the pooled client without awaiting it.

    An ``httpx.AsyncClient`` binds to the event loop that created it. Tests that
    each spin up their own loop via ``asyncio.run`` would otherwise inherit a
    client belonging to a loop that has already closed, which surfaces as a
    baffling ``RuntimeError`` from deep inside asyncio rather than as anything
    resembling the actual mistake. The suite calls this between tests.

    Simply dropping the reference is not enough: any socket still in the pool
    then gets closed by the garbage collector long after its loop is gone. So
    close it eagerly and swallow whatever the teardown throws — by this point
    the client is being discarded anyway, and a noisy shutdown is not a failure.
    """
    global _CLIENT
    client, _CLIENT = _CLIENT, None
    if client is None or client.is_closed:
        return
    try:
        asyncio.run(client.aclose())
    except Exception:  # pragma: no cover - best-effort teardown
        pass


def _sleep_for(attempt: int, base: float, retry_after: str | None) -> float:
    if retry_after:
        try:
            return min(float(retry_after), 30.0)
        except ValueError:
            pass
    # Exponential with full jitter — avoids thundering herds on a shared quota.
    return min(base * (2**attempt) * (0.5 + random.random()), 12.0)


async def request_json(
    method: str,
    url: str,
    *,
    service: str,
    params: Mapping[str, Any] | None = None,
    json_body: Any | None = None,
    data: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    settings: Settings | None = None,
    max_retries: int | None = None,
    expect_json: bool = True,
    idempotent: bool | None = None,
    budget_s: float | None = None,
) -> Any:
    """Perform a request with the house retry policy and return parsed JSON.

    Raises :class:`UpstreamError` on definitive failure. Callers are expected
    to catch it and degrade — see each connector's fallback path.

    ``idempotent`` overrides the method-derived default. Pass ``True`` only
    when repeating the call genuinely cannot act twice — either the operation
    is naturally a no-op on repeat, or the upstream dedupes on a key you sent.
    Pass ``False`` to forbid all retries, including the connect-error one.

    ``budget_s`` caps total wall-clock across attempts and backoff. The
    default derives from the per-request timeout, so no call can hang around
    for the full ``retries × (timeout + max backoff)`` worst case.
    """
    s = settings or get_settings()
    retries = s.http_max_retries if max_retries is None else max_retries
    verb = method.upper()
    safe = verb in IDEMPOTENT_METHODS if idempotent is None else bool(idempotent)
    if budget_s is None:
        budget_s = (retries + 1) * s.http_timeout_s + TOTAL_BUDGET_SLACK_S
    started = time.monotonic()

    def _budget_left() -> float:
        return budget_s - (time.monotonic() - started)

    client = await get_client(s)
    clean_params = {k: v for k, v in (params or {}).items() if v is not None}

    last: Exception | None = None
    for attempt in range(retries + 1):
        _STATS.requests += 1
        _STATS.by_service[service] = _STATS.by_service.get(service, 0) + 1
        try:
            resp = await client.request(
                verb, url,
                params=clean_params or None,
                json=json_body,
                data=dict(data) if data else None,
                headers=dict(headers) if headers else None,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # The connection was never established, so the server cannot have
            # seen this request. Safe to repeat even for a POST — this is the
            # single exception to the "no retrying writes" rule.
            last = exc
            if attempt >= retries:
                break
            delay = _sleep_for(attempt, s.http_backoff_base_s, None)
            if delay >= _budget_left():
                log.warning("%s connect error; out of budget, giving up", service)
                break
            _STATS.retries += 1
            log.warning("%s transport error (%s); retry %d in %.2fs", service, type(exc).__name__, attempt + 1, delay)
            await asyncio.sleep(delay)
            continue
        except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as exc:
            # The request may well have been delivered and acted upon; only
            # the answer went missing. Repeating an idempotent call is still
            # free, but repeating a write here is how you get two playlists.
            last = exc
            if not safe:
                log.warning("%s %s timed out; not retrying a non-idempotent call", service, verb)
                break
            if attempt >= retries:
                break
            delay = _sleep_for(attempt, s.http_backoff_base_s, None)
            if delay >= _budget_left():
                log.warning("%s timeout; out of budget, giving up", service)
                break
            _STATS.retries += 1
            log.warning("%s transport error (%s); retry %d in %.2fs", service, type(exc).__name__, attempt + 1, delay)
            await asyncio.sleep(delay)
            continue

        if resp.status_code in DEPRECATED_STATUS:
            _STATS.failures += 1
            raise UpstreamError(
                service,
                f"{resp.status_code} on {resp.request.url.path} — endpoint retired or forbidden; "
                "not retrying",
                status=resp.status_code, retryable=False, url=str(resp.request.url),
            )

        # A 5xx/429 means the server saw the request. Repeating it is only
        # safe when the operation itself is idempotent.
        if resp.status_code in RETRYABLE_STATUS and attempt < retries and safe:
            delay = _sleep_for(attempt, s.http_backoff_base_s, resp.headers.get("Retry-After"))
            if delay < _budget_left():
                _STATS.retries += 1
                log.warning("%s HTTP %d; retry %d in %.2fs", service, resp.status_code, attempt + 1, delay)
                await asyncio.sleep(delay)
                continue
            log.warning("%s HTTP %d; out of budget, giving up", service, resp.status_code)

        if resp.status_code >= 400:
            _STATS.failures += 1
            raise UpstreamError(
                service, f"HTTP {resp.status_code}: {resp.text[:240]}",
                status=resp.status_code,
                retryable=resp.status_code in RETRYABLE_STATUS,
                url=str(resp.request.url),
            )

        if not expect_json:
            return resp.text
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError as exc:
            _STATS.failures += 1
            raise UpstreamError(service, f"non-JSON response: {exc}", url=str(resp.request.url)) from exc

    _STATS.failures += 1
    raise UpstreamError(
        service, f"exhausted {retries} retries: {last}", retryable=True, url=url
    ) from last


async def get_json(url: str, *, service: str, **kwargs: Any) -> Any:
    return await request_json("GET", url, service=service, **kwargs)


async def post_json(url: str, *, service: str, **kwargs: Any) -> Any:
    """POST. Retried only on a connect error unless you pass ``idempotent=True``.

    Say why in a comment when you do pass it. "It seemed flaky" is not why.
    """
    return await request_json("POST", url, service=service, **kwargs)


async def put_json(url: str, *, service: str, **kwargs: Any) -> Any:
    return await request_json("PUT", url, service=service, **kwargs)

# Backend route smoke pass

Every route the app actually exposes, exercised once with a plausible request,
offline. Re-runnable:

```bash
python -m scripts.smoke_routes            # table + exit code
python -m scripts.smoke_routes --json     # machine-readable
python -m scripts.smoke_routes --only-failures
```

Exit status is 0 only when every route answered with a status it is allowed to
answer **and** every route has a case. A new route with no case fails the run
as `gap` — that is deliberate, so a path nobody documented cannot rot quietly.

## How routes are discovered

Not from a hand-written list. The script boots the real app and walks
`app.routes`. One wrinkle worth recording: since FastAPI 0.116 an included
router is **not** flattened into `app.routes` — it is kept as an
`_IncludedRouter` wrapper. A naive `[r.path for r in app.routes]` sees **6**
routes here; recursing through `original_router` and re-applying
`include_context.prefix` finds **82**. Anyone auditing this app with the naive
loop will conclude it has almost no API.

## What "pass" means

There is no network in this environment, so several routes cannot do their
real job. That is expected and is *not* counted as a defect. What is a defect
is a route that answers an unreachable upstream with a stack trace. The script
encodes that distinction:

- **500 is never a pass.** BAROGROOVE's stated premise is that *something*
  always comes back.
- Any other 5xx passes only where a case declares it **and** the body is
  structured JSON. `503 {"error":"lastfm_unavailable"}` is a legitimate
  answer; a framework HTML error page is not.
- Each row is tagged `core` (must work fully offline), `offline-degraded`
  (upstream gone, must degrade gracefully), or `oauth-unconfigured` (no
  credentials, must refuse politely).

## Result

| | Before | After |
| --- | --- | --- |
| Checks | 81 | 85 |
| Pass | 78 | **85** |
| Fail | 3 | **0** |

"Before" is pristine `HEAD`; "after" is `HEAD` + the fixes below. Both columns
come from the same final script, so the comparison is apples-to-apples. The
four extra checks are the `/api/forge/jobs` routes, which another worker added
to the tree *during* this pass — the coverage-gap detector caught them, and
cases were added.

### A note on measurement

Two other workers were editing this same checkout throughout. A mid-pass run
against the live tree showed every `/api/surfaces/*` and `/api/advisor/*` route
404-ing and `/api/forge` raising `KeyError: 'high_pressure_blue'`. Those were
**transient artifacts of another worker's in-flight edits**, not defects, and
they had cleared by the end of the pass. To keep the before/after honest, the
baseline was measured against a `git archive HEAD` export in a scratch
directory with only my own files overlaid. The final 85/85 figure is from the
live tree.

The same caveat applies to the test suite. `pytest -q` on `HEAD` plus **only**
the change described here exits **0** — green. A run against the live tree at
the moment of writing fails one test,
`tests/test_a2ui.py::test_every_emitted_action_context_matches_its_signature`
(`themes: barogroove.selectTheme omits required {'themeId'}`), which is the
A2UI worker's in-flight edit to `a2ui/catalog.py` / `a2ui/surfaces.py` and is
unrelated to anything in this pass.

## Defects found and fixed

### 1. The Almanac could not see your forges — read/write identity disagreed

`GET /api/almanac/forges/{id}` returned 404 for a playlist that `POST
/api/forge` had just created and returned the id of. `GET /api/almanac/history`
reported `count: 0` at the same time. The record was genuinely in the store —
`MemoryAlmanac._playlists` held the id and `_by_user["smoke-user"]` listed it.

**Root cause: the two halves of the compounding loop resolved the caller
differently.**

- The write path (`routes/forge.py`) resolves identity via
  `routes.pairing.current_user_id`, which checks a Firebase bearer token, then
  `request.state`, then falls back to the **`X-Barogroove-User` header**. So a
  forge sent with that header is stamped `playlist.user_id = "smoke-user"`.
- The read path (`routes/almanac.py::_resolve_user`) used only
  `firebase.auth.current_user_optional`, which looks at **`Authorization:
  Bearer` and nothing else**. With no bearer token it returns `None`, and the
  router fell back to a hard-coded `"demo"` uid. It never consulted
  `X-Barogroove-User`.

So any client identifying itself with `X-Barogroove-User` — the local-dev path,
and the Flutter app before Firebase sign-in completes — wrote under its own uid
and read under `demo`. Every forge it made was invisible to `/history`,
`/forges/{id}`, `/nudge` and `/retrospective`. A *fully anonymous* caller landed
on `demo` on both sides and worked fine, which is exactly why the test suite
never caught it: no test sets that header.

**Fix** (`backend/app/routes/almanac.py`): `_resolve_user` now falls back to
`X-Barogroove-User` before defaulting to `demo`, matching the write path's
precedence. Verified three ways — consistent identity now resolves (404 → 200),
the anonymous flow is unchanged (200 → 200), and a *different* caller asking for
the same playlist id still gets 404, so per-user isolation is preserved and this
is not a data leak. That last property is now pinned by its own smoke case.

### 2. `/api/almanac/qna/ask` and `/qna/stream` returned a 500 offline

Both raised `IndexError: list index out of range` and returned a bare 500.

**Root cause:** `backend/app/almanac/data_qna.py`, in
`_local_olap_qna_synthesizer` — the offline fallback that exists *precisely* for
when BigQuery is unreachable. Building its narrative string it writes:

```python
f"**{rows[1]['weather_theme'] if len(rows) > 1 else 'Solar High'}** "
f"({rows[1]['scrobble_count']:,} plays). ..."
```

The guard `if len(rows) > 1` is applied to the first `rows[1]` and then
**forgotten on the very next line**, which indexes `rows[1]` unconditionally.
Offline the in-memory almanac yields a single weather theme, so `len(rows) == 1`
and the fallback path blows up. The degradation ladder had a broken bottom rung:
the code that catches BigQuery being down could not itself survive a small
dataset.

**Fix:** `data_qna.py` is owned by another worker, so this was *not* patched at
source. Instead `routes/almanac.py` now degrades at the route boundary — a
failed QnA turn returns a well-formed, empty `DataQnAResponse` with an honest
message (`engine: "unavailable"`) rather than a 500. The streaming variant is
wrapped so a mid-stream failure still emits a `FINAL_RESPONSE` event followed by
the same literal `data: [DONE]` sentinel the happy path uses — otherwise the
client hangs on a truncated `text/event-stream` with no terminating event.

**Still worth fixing at source:** the one-line guard on `data_qna.py:557`. The
route-level net stops the 500 but the offline synthesizer still cannot answer
this question at all.

## Defects found and left to their owners

- **`data_qna.py:557` unguarded `rows[1]`** — see above. Root cause identified,
  worked around at the route layer, not fixed at source (file not owned).
- **Theme ids disagree between `contracts.py` and `a2ui/palette.py`**, so
  `selectTheme` can 422 on a valid chip. Known, already assigned. Consistent
  with the transient `KeyError: 'high_pressure_blue'` seen from `/api/forge`
  mid-pass.
- **`themeChips` emits a binding the Dart renderer does not resolve**
  ("no themes bound to items"). Known, already assigned.
- **`POST /api/pair/{provider}/configure` answers `200` with an HTML "Spotify
  Connected" success page** even with no Secret Manager and dummy credentials.
  It is graceful (not a crash) so the smoke pass accepts it, but claiming
  success for a configure that cannot have persisted anything is misleading.
  Flagged rather than changed — altering pairing success semantics is a
  behavioural decision, not a smoke fix.
- **`/api/pair/lastfm/callback` matches *any* pending Last.fm state** rather
  than the one keyed by the returned token. Offline it 503s before reaching
  that code so the smoke pass cannot demonstrate impact, but it reads like a
  state-fixation weakness in the OAuth handshake and deserves a look by whoever
  owns the pairing security model.

## Not exercised, and why

- **Real upstream behaviour** — Open-Meteo, Google Weather, Last.fm, Spotify,
  Firestore, BigQuery, Vertex/Gemini. No network. Every route touching these was
  exercised only along its *degraded* branch. The happy paths are unverified
  here.
- **OAuth completion.** `/api/pair/*/callback`, `manual-exchange` and
  `configure` were driven with synthetic codes/tokens, so only their rejection
  and degradation branches ran. No real handshake completes offline.
- **`/mcp`.** Not mounted — `mcp_enabled=False` in this configuration, so it is
  not in the route table at all.
- **SSE payload semantics.** `/api/almanac/qna/stream` is checked for status and
  a well-formed terminating event, not for the correctness of the event
  sequence.
- **Anything authenticated by a real Firebase bearer token.** Identity was
  exercised through the `X-Barogroove-User` fallback only.

## Reproducing

The suite and this script need an offline stand-in for `pydantic-settings`,
which cannot be `pip install`-ed in this environment. It lives **outside the
repo** at `$SHARED/testshim` and is injected on `PYTHONPATH` only:

```bash
PYTHONPATH=$SHARED/testshim python -m pytest -q
PYTHONPATH=$SHARED/testshim python -m scripts.smoke_routes
```

Nothing in the repo depends on it and it must never be committed. Running the
script also emits structured telemetry JSON on stdout; pipe through
`grep -v '^{"severity"'` if you want just the table.

## Full results

Statuses are the raw HTTP codes. `Before` = pristine `HEAD`, `After` = with the
fixes above, both from the live tree's final script.

| Method | Path | What we sent | Before | After | Kind | Note |
| --- | --- | --- | --- | --- | --- | --- |
| `GET` | `/api/health` | no args | 200 PASS | 200 PASS | core |  |
| `GET` | `/api/healthz` | no args | 200 PASS | 200 PASS | core |  |
| `GET` | `/healthz` | no args | 200 PASS | 200 PASS | core |  |
| `GET` | `/` | no args | 200 PASS | 200 PASS | core |  |
| `GET` | `/api/openapi.json` | no args | 200 PASS | 200 PASS | core |  |
| `GET` | `/api/docs` | no args | 200 PASS | 200 PASS | core |  |
| `GET` | `/docs/oauth2-redirect` | no args | 200 PASS | 200 PASS | core |  |
| `GET` | `/legacy` | no args | 200 PASS | 200 PASS | core |  |
| `GET` | `/legacy/about` | no args | 200 PASS | 200 PASS | core |  |
| `GET` | `/api/themes` | no args | 200 PASS | 200 PASS | core |  |
| `GET` | `/api/genres` | no args | 200 PASS | 200 PASS | core |  |
| `GET` | `/api/themes/{theme_id}` | theme_id from /api/themes | 200 PASS | 200 PASS | core |  |
| `GET` | `/api/themes/suggest` | lat/lon = Brussels | 200 PASS | 200 PASS | offline-degraded |  |
| `GET` | `/api/sky/scenarios` | no args | 200 PASS | 200 PASS | core |  |
| `GET` | `/api/sky/geocaches` | no args | 200 PASS | 200 PASS | core |  |
| `GET` | `/api/sky/geocaches` | random=true | 200 PASS | 200 PASS | core |  |
| `GET` | `/api/sky/vector` | lat/lon = Brussels, scenario=front_collapse | 200 PASS | 200 PASS | offline-degraded |  |
| `GET` | `/api/surfaces/catalog` | no args | 200 PASS | 200 PASS | core |  |
| `GET` | `/api/surfaces/catalog.json` | no args | 200 PASS | 200 PASS | core |  |
| `GET` | `/api/surfaces/health` | no args | 200 PASS | 200 PASS | core |  |
| `GET` | `/api/surfaces/sky` | lat/lon = Brussels, single=true | 200 PASS | 200 PASS | offline-degraded |  |
| `GET` | `/api/surfaces/themes` | theme=petrichor, genre=any | 200 PASS | 200 PASS | core |  |
| `GET` | `/api/surfaces/telemetry` | single=false | 200 PASS | 200 PASS | core |  |
| `POST` | `/api/surfaces/action` | selectTheme chip tap (args.themeId=petrichor) | 200 PASS | 200 PASS | core |  |
| `GET` | `/api/forge/demo` | length=6 | 200 PASS | 200 PASS | offline-degraded |  |
| `POST` | `/api/forge` | Brussels, theme=petrichor, length=6, sink=none, seed=7 | 200 PASS | 200 PASS | offline-degraded |  |
| `POST` | `/api/forge/explain` | the playlist just forged, echoed back | 200 PASS | 200 PASS | offline-degraded |  |
| `POST` | `/api/forge/jobs` | same forge body, job_id=smoke-job-1 (idempotency key) | n/a *(route added mid-pass)* | 202 PASS | offline-degraded |  |
| `POST` | `/api/forge/jobs` | the SAME job_id again -- must join, not forge twice | n/a *(route added mid-pass)* | 200 PASS | offline-degraded | Idempotent retry: 200 means it handed back the in-flight run. |
| `GET` | `/api/forge/jobs` | limit=5 | n/a *(route added mid-pass)* | 200 PASS | core |  |
| `GET` | `/api/forge/jobs/{job_id}` | poll the job started above | n/a *(route added mid-pass)* | 200 PASS | core | 404 is legitimate: the job registry is in-process only. |
| `GET` | `/api/almanac/history` | limit=5 | 200 PASS | 200 PASS | offline-degraded |  |
| `GET` | `/api/almanac/nudge` | no args | 200 PASS | 200 PASS | offline-degraded |  |
| `GET` | `/api/almanac/retrospective` | no args | 200 PASS | 200 PASS | offline-degraded |  |
| `GET` | `/api/almanac/scrobbles` | limit=5 | 200 PASS | 200 PASS | offline-degraded |  |
| `GET` | `/api/almanac/scrobbles/analytics` | years 2020-2026, limit=5 | 200 PASS | 200 PASS | offline-degraded |  |
| `GET` | `/api/almanac/scrobbles/cache/stats` | no args | 200 PASS | 200 PASS | core |  |
| `GET` | `/api/almanac/forges/{playlist_id}` | playlist_id from POST /api/forge, same user header | 404 **FAIL** | 200 PASS | offline-degraded |  |
| `GET` | `/api/almanac/forges/{playlist_id}` | same id as a DIFFERENT caller -- must stay private | 404 PASS | 404 PASS | core | Per-user scoping: another caller must not be able to fetch this forge by id. |
| `GET` | `/api/almanac/qna/status` | no args | 200 PASS | 200 PASS | offline-degraded |  |
| `POST` | `/api/almanac/qna/ask` | {"question": "which theme do I forge most?"} | **500** **FAIL** | 200 PASS | offline-degraded |  |
| `POST` | `/api/almanac/qna/stream` | same question, streaming variant | **500** **FAIL** | 200 PASS | offline-degraded |  |
| `POST` | `/api/almanac/qna/graph-on-demand` | bar chart over two literal rows | 200 PASS | 200 PASS | core |  |
| `POST` | `/api/almanac/playlist-cohort-check` | {"input_text": "Petrichor, falling barometer"} | 200 PASS | 200 PASS | offline-degraded |  |
| `POST` | `/api/almanac/feedback` | signal="loved" on the first forged track | 200 PASS | 200 PASS | offline-degraded |  |
| `POST` | `/api/almanac/scrobbles/sync` | lastfm_user=smokeuser (Last.fm disabled offline) | 200 PASS | 200 PASS | offline-degraded |  |
| `POST` | `/api/almanac/scrobbles/cache/clear` | no args | 200 PASS | 200 PASS | core |  |
| `GET` | `/api/advisor/suggestions` | no args | 200 PASS | 200 PASS | offline-degraded |  |
| `POST` | `/api/advisor/live` | {"prompt": "forge me something for this sky", auto_forge: false} | 200 PASS | 200 PASS | offline-degraded |  |
| `GET` | `/api/dataviz/dashboard` | no args | 200 PASS | 200 PASS | offline-degraded |  |
| `POST` | `/api/dataviz/qna` | {"question": "what is my busiest listening hour?"} | 200 PASS | 200 PASS | offline-degraded |  |
| `GET` | `/api/telemetry/summary` | user_id=smoke-user | 200 PASS | 200 PASS | core |  |
| `GET` | `/api/telemetry/sessions` | limit=5 | 200 PASS | 200 PASS | core |  |
| `GET` | `/api/telemetry/sessions/{session_id}` | id from the sessions list (synthetic if empty) | 200 PASS | 200 PASS | core |  |
| `GET` | `/api/telemetry/conversations` | limit=5 | 200 PASS | 200 PASS | core |  |
| `GET` | `/api/telemetry/conversations/{conversation_id}` | id from the conversations list (synthetic if empty) | 404 PASS | 404 PASS | core |  |
| `GET` | `/api/telemetry/trajectories` | limit=5, offset=0 | 200 PASS | 200 PASS | core |  |
| `GET` | `/api/telemetry/trajectories/{trajectory_id}` | id from the trajectories list (synthetic if empty) | 404 PASS | 404 PASS | core |  |
| `GET` | `/api/telemetry/memories` | limit=5 | 200 PASS | 200 PASS | core |  |
| `POST` | `/api/telemetry/memories` | {"content": "prefers slowcore on falling barometers"} | 200 PASS | 200 PASS | core |  |
| `DELETE` | `/api/telemetry/memories/{memory_id}` | the memory just created | 404 PASS | 404 PASS | core |  |
| `GET` | `/api/observability/summary` | user_id=smoke-user | 200 PASS | 200 PASS | core |  |
| `GET` | `/api/observability/sessions` | limit=5 | 200 PASS | 200 PASS | core |  |
| `GET` | `/api/observability/sessions/{session_id}` | id from the sessions list (synthetic if empty) | 200 PASS | 200 PASS | core |  |
| `GET` | `/api/observability/conversations` | limit=5 | 200 PASS | 200 PASS | core |  |
| `GET` | `/api/observability/conversations/{conversation_id}` | id from the conversations list (synthetic if empty) | 404 PASS | 404 PASS | core |  |
| `GET` | `/api/observability/trajectories` | limit=5, offset=0 | 200 PASS | 200 PASS | core |  |
| `GET` | `/api/observability/trajectories/{trajectory_id}` | id from the trajectories list (synthetic if empty) | 404 PASS | 404 PASS | core |  |
| `GET` | `/api/observability/memories` | limit=5 | 200 PASS | 200 PASS | core |  |
| `POST` | `/api/observability/memories` | {"content": "prefers slowcore on falling barometers"} | 200 PASS | 200 PASS | core |  |
| `DELETE` | `/api/observability/memories/{memory_id}` | the memory just created | 404 PASS | 404 PASS | core |  |
| `GET` | `/api/pair/status` | X-Barogroove-User header only | 200 PASS | 200 PASS | core |  |
| `POST` | `/api/pair/spotify/start` | return_to=https://bg.netdev.be/ | 200 PASS | 200 PASS | oauth-unconfigured | 422 = ConfigurationError: no Spotify client id offline. |
| `POST` | `/api/pair/lastfm/start` | return_to=https://bg.netdev.be/ | 200 PASS | 200 PASS | oauth-unconfigured | 422 = ConfigurationError: no Last.fm API key offline. |
| `POST` | `/api/pair/lastfm/username` | {"username": "smokeuser"} | 200 PASS | 200 PASS | oauth-unconfigured |  |
| `POST` | `/api/pair/spotify/manual-exchange` | pasted callback URL with code+state | 400 PASS | 400 PASS | oauth-unconfigured |  |
| `GET` | `/api/pair/spotify/callback` | code=smoke-code&state=smoke-state | 400 PASS | 400 PASS | oauth-unconfigured |  |
| `GET` | `/api/pair/lastfm/callback` | token=smoke-token&state=smoke-state | 503 PASS | 503 PASS | oauth-unconfigured | 503 lastfm_unavailable is the offline answer: no API secret to exchange the token with. |
| `GET` | `/api/pair/callback` | code=smoke-code&state=smoke-state (generic router) | 400 PASS | 400 PASS | oauth-unconfigured |  |
| `GET` | `/callback` | root alias of the generic OAuth callback | 400 PASS | 400 PASS | oauth-unconfigured |  |
| `GET` | `/auth/lastfm/callback` | legacy Last.fm redirect alias | 400 PASS | 400 PASS | oauth-unconfigured |  |
| `GET` | `/api/pair/{provider}/demo-authorize` | provider=spotify, state=smoke-state | 200 PASS | 200 PASS | oauth-unconfigured |  |
| `GET` | `/api/pair/{provider}/demo-complete` | provider=spotify, state=smoke-state, account=smoke@example.com | 200 PASS | 200 PASS | oauth-unconfigured |  |
| `POST` | `/api/pair/{provider}/configure` | provider=spotify, dummy client id/secret | 200 PASS | 200 PASS | oauth-unconfigured | No Secret Manager offline; must refuse politely. |
| `POST` | `/api/pair/{provider}/disconnect` | provider=spotify | 200 PASS | 200 PASS | oauth-unconfigured |  |

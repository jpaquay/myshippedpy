# BAROGROOVE UX rework — decision log

Running record of what was changed during the 14-item rework, and why. This is
the companion to `docs/UX_IA_SPEC.md`: the spec says what the product should
be, this file says what we actually did and which tradeoffs we accepted.

Each item below lands as its own commit. Item numbers match the approved plan.

## Ground rules we worked under

* **A2UI first.** The backend describes surfaces (`backend/app/a2ui/`,
  `backend/app/routes/surfaces.py`) and Flutter renders them generically
  (`frontend/lib/a2ui/`). Where a visual change belongs to the surface
  description, it was made in Python, not in Dart. See `A2UI_HANDOFF.md`.
* **No network during the rework.** No dependency could be added: every fix
  uses what is already in `requirements.txt` / `pubspec.yaml`. Anything that
  genuinely needed a new package was reported as blocked instead of faked.
* **Design register.** Sober, calm, executive — institutional dashboard, not a
  neon music app. Monochrome icons, restrained accent, system theme by default.
* **Almanac and Data Viz stay separate.** Almanac is the static archive; Data
  Viz is the dynamic A2UI analytics surface. The separation is deliberate and
  is what uncluttered the flow, so nothing here merges them.

## Verification environment

The sandbox this ran in has no network, so the usual bootstrap commands are
unavailable. What worked:

* Backend tests: the full suite runs and was **green before any change**. One
  third-party package (`pydantic-settings`) could not be installed offline, so
  it was supplied from outside the repo on `PYTHONPATH` purely to let the suite
  execute. No repo code depends on that stand-in.
* Flutter: `flutter analyze --no-pub` and `flutter test --no-pub` work offline
  once dependencies are resolved from the local pub cache. Plain
  `flutter pub get` / `flutter analyze` try to reach pub.dev and fail.
* Analyzer baseline before the rework: **43 issues, 0 errors**.

## Per-item record

Entries are appended as each item lands.

### Item 2 — Theme-id reconciliation (`670998f`)

**Root cause.** `a2ui/palette.py` declared its *own* `THEME_IDS` tuple of
design-time working names, and `catalog.py` built the `selectTheme` parameter
enum from that list — while the chips, the sonic themes and the Flutter client
all came from `contracts.THEME_IDS`. So `sirocco` was offered by the UI and
rejected by the validator. A **third** hidden table in `routes/surfaces.py`
made it worse: it rewrote canonical ids *onto* the retired names
(`blue_hour` → `long_dusk`) to sneak them past the wrong validator, and mapped
`clear_high` to `clear_cold`, an id that has never existed anywhere.

**Decision on the five orphans.** Four were earlier *names* for canonical
themes and are kept as retired aliases with their tints intact
(`gale_warning`→`storm_front`, `blanket_grey`→`nordic_fog`,
`heat_shimmer`→`heatwave_cruise`, `long_dusk`→`blue_hour`).
`high_pressure_blue` was the untinted house chassis — its palette was `{**BASE}`
verbatim, identical to an unthemed surface — so it is deleted with no successor.
`contracts.py` is now the single authority; the alias map lives there too.
Unknown ids fail soft: the 422 body carries `validThemeIds` / `retiredThemeIds`.
An anti-drift test fails if the two modules ever diverge again.

### Item 3 — themeChips binding (`25fb79a`)

**Root cause.** The surface builder emitted a chip *template* rather than the
theme array the Dart widget binds to, so the renderer found no items. The REST
router happened to paper over it with an adapter; the raw/MCP surface path did
not, which is why the "no themes bound to items" log appeared. Fixed in the
surface description (the layer that owns it) — no Dart change was needed. A
cross-language regression test reads the Dart widget's own lookup keys out of
`theme_chips.dart` and pins them against the emitted JSON.

**Known follow-up:** `GenreCorridor`, `TrackList` and `AlmanacTimeline` have the
identical mismatch, currently masked by the same REST adapter and broken on the
raw/MCP stream. Mechanical to fix now that themeChips shows the pattern.

### Item 4 — Forge statefulness (`17f21d3`)

No job/queue abstraction existed to reuse (the only background work in the app
was two fire-and-forget `create_task` calls in telemetry), so rather than import
a broker the app does not need, this is a plain in-process registry over
`asyncio.Task` in `backend/app/forge/jobs.py`. `POST /api/forge/jobs` starts and
returns immediately, `GET /api/forge/jobs/{id}` polls, `GET /api/forge/jobs`
lists recent runs for the caller. The synchronous `POST /api/forge` still works:
`_prepare_request` / `_execute_forge` were extracted so both paths run identical
code and cannot drift, and publishing into recent playlists moved *into*
`_execute_forge`, which is what makes a job land in recents on its own.

**Accepted tradeoff, stated plainly:** the registry is in-process and dies with
the process. It survives navigation, backgrounding and reconnect — which is what
was asked — but not a deploy or a restart.

### Item 5 — Transport hardening (`3ac3702`)

Retry is now **method-aware** with a bounded total budget. This caught a real
latent bug: `request_json` retried every 5xx, and the Spotify sink posts through
it, so a transient failure on `POST /playlists` or `POST /tracks` could
genuinely have duplicated a user's Spotify playlist. Only idempotent reads
retry; forge starts are keyed by the item-4 job id. On the client, every request
has a bounded timeout, and the job watcher rides out transient poll failures on
a jittered backoff, resets its budget on success, and stops only on a fatal
answer (404/401) or a bounded run of failures.

**Honest gap:** the backend has an SSE endpoint (`/api/almanac/qna` streaming)
that no Dart code currently consumes — there is no `EventSource`/`WebSocket` in
`frontend/lib`. No new SSE transport was added for it, because on Flutter web
`package:http` buffers rather than streams and it could not have been verified
offline. Reconnect work went into the long-lived connection that actually
exists.

### Item 6 — Route smoke pass (`9820091`, `e876151`)

85 routes exercised; results and a re-runnable `scripts/smoke_routes.py` in
`docs/ROUTE_SMOKE.md`. Two real defects fixed:

* **Identity asymmetry (the good one).** The almanac write path honoured
  `X-Barogroove-User` while the read path only looked at `Authorization: Bearer`
  and silently fell back to `"demo"` — so a user could forge a playlist
  successfully and then get a 404 fetching their own. Cross-user access still
  correctly 404s after the fix, so this did not become a data leak.
* **QnA 500.** `qna.py:557` guards `rows[1]` on one line and then uses it
  unguarded on the next; offline there is exactly one theme, so it threw.
  Degraded gracefully at the route layer (the file itself belonged to another
  workstream).

**Worth knowing for anyone auditing this API:** FastAPI ≥0.116 keeps included
routers as `_IncludedRouter` wrappers, so the obvious `[r.path for r in
app.routes]` sees **6** routes while recursing finds **82**.

**Flagged, not changed** (behavioural calls for the owner):
`POST /api/pair/{provider}/configure` returns a 200 "Spotify Connected" page
with dummy credentials and no Secret Manager — graceful, but it claims a success
that cannot have persisted. And `/api/pair/lastfm/callback` matches *any*
pending Last.fm state rather than the token's, which reads like state fixation;
offline it 503s first, so the impact could not be demonstrated.

### Item 7 — Navigation & IA spec (`dbb54e1`)

`docs/UX_IA_SPEC.md`. Mobile header reduces to wordmark + avatar, with a status
dot only when something is wrong. The theme control and install button move to
Settings; the Telemetry Inspector header entry point is deleted (the panel keeps
its other routes); the theme toggle that existed *twice* (AppBar and nav-rail
trailing) loses the duplicate. One three-rung disclosure ladder is defined for
the whole app, with a hard rung-0 budget on a 390px screen.

### Item 8 — Forge console modes (`ad9f072`)

The three pill buttons become one full-width segmented control with a permanent
helper line per mode. Guided renders an outcome headline and one rationale line
and *nothing else* — measured at **105px** against the spec's 120px budget, with
no `Slider` in the tree at all. Easy adds the three cursors that actually travel
plus a collapsed "why these three". Expert promotes the SkyDial to first glance
and adds pressure/trend/BPM, telemetry badges, a coefficients table and a raw
`ForgeRequest` sheet.

**The real point of this item:** `toRequest()` was *already* nulling every
custom field in Guided, so the old UI displayed three cursors and then silently
discarded them. The show/hide table is now declared once on a `ConsoleMode` enum
and matches the masking exactly, asserted by test. The UI was made to tell the
truth about existing behaviour rather than the reverse.

### Item 9 — Data Viz (`137f63e`, `12f01be`)

`dataviz_screen.dart` goes from 2127 lines to **377 lines of composition**, with
the rest split into eight focused files under `lib/screens/dataviz/`.

The notable finding: the backend had supported the full answer card all along.
`POST /api/almanac/qna/ask` has always produced `sql_query`, `chart_spec`,
`rows` and `suggestions`, and the status endpoint publishes starter prompts —
the Dart screen simply consumed none of it. So the fix was mostly *consumption*,
plus carrying `generated_sql` / `chart_spec` / `row_count` / `data_engine` on
the QnA turn so provenance travels with the answer. Empty/loading/error are
first-class states, which matters here because offline they are what renders.
Three genuine 390px overflows in the inherited standing cards were found by a
screen-level test and fixed.

**Deliberate deviation:** the backend hands over a per-point `color_hex`
rainbow. It is ignored — every geometry is a single-hue ramp of the accent, with
magnitude carried by length and position. §7.3 rations colour, and monochrome is
what stays readable at 390px.

**Removed following the spec, flagged in case it was an oversight:** the old
insight card could seed matching scrobbles into Forge. `matching_scrobbles` is
still parsed off the wire, so reinstating it is cheap.

### Items 12 / 13 / 14 — Design system, theme mode, badges (`b74ff57`, `6c5ffb4`, `5b14ca8`)

Tokens are centralised in `app_theme.dart`: `BgSpace`, `BgIcon`, `BgBreak`,
`BgText` and `BgColors`. The load-bearing choice is making **`BgColors` a
`ThemeExtension`** — `BgTheme.tinted` carries the whole role set forward and
moves only `accent` / `accentWash`, so a palette arriving from `/api/themes` can
shift the interaction colour but cannot acquire a private one. That is what
makes the A2UI rule enforceable rather than aspirational.

The theme control is now Dark / Light / **As host**, defaulting to `host`,
persisted via `shared_preferences` (already a dependency of `pairing_service`,
so no new package). Restore is async: the first frame renders on the default and
swaps on the next, so startup never blocks on storage. Connection badges read
from the existing `pairing_service` and render three honest states — linked,
unlinked, unknown.

### Items 10 + 11 — One assistant overlay, and MCP behind a write gate (`ed8e600`, `a0a11e9`)

`gemini_live_advisor.dart` is **gone from the tree** — all 1019 lines removed,
not orphaned — along with its instance in `home_screen.dart`. The Data Viz QnA
banner went with the Data Viz rework. In their place: one 56px monochrome bubble
mounted in the shell's `Stack`, with scroll-hide wired **once at the shell
level** so all five destinations drive it, including the ones the overlay author
did not own.

Conversation state lives on the root `ProviderScope`, strictly above `AppShell`
and above the `IndexedStack`, so tab switches cannot lose it. The Data Viz
question field stays where it is and writes into that same store through a
transport decorator, so there is one conversation, not two.

**The write gate (item 11) is enforced on the server, not in the UI.** A write
is refused and the server mints a single-use ticket bound to the function *and*
to the principal the MCP guard resolved — never to anything in the request body,
since a ticket bound to a caller-supplied identity is a ticket the caller can
forge. Five-minute TTL. The gate sits at every client-reachable entry:
`functions.dispatch()`, the `forge_playlist` / `save_playlist` tool wrappers
(so an agent runtime with a valid bearer token and no BAROGROOVE UI in sight is
still asked), and `POST /api/advisor/act`.

`forge_playlist` being an MCP *tool* rather than an A2UI agent function is what
shaped the design: one gateway over both dispatch paths, with `writes` declared
in Python and published via `GET /api/advisor/tools`. **There is no list of
function names in Dart**, and an unclassified capability is treated as a write.
`select_theme` / `select_genre` execute immediately and mint nothing.

Voice needs an unambiguous affirmative: "yes, but make it 20 tracks" does *not*
confirm — it becomes a new question and the card stays pending.

**Honest limit, documented in the module:** this does not prove a *human*
consented; no server can. What it guarantees is that no single call can both
propose and perform a write.

### Follow-up pass — single-sourcing and honesty (`ebb676f`, `6ac2533`)

Because workers could not edit each other's files, three of them built a local
copy of the disclosure widget and two mirrored the token numbers. That debt is
paid: `frontend/lib/widgets/bg_disclosure.dart` is the one ladder, the local
copies are deleted, and the shim classes no longer contain a single number —
every member forwards to `BgBreak` / `BgSpace`, asserted identical by test.

**The fabricated numbers are gone.** The Almanac KPI strip was inventing
`160717` scrobbles, `2649` unique tracks, and a favourite theme and dominant
mood of `'Petrichor'` whenever data was missing; `playlist_screen.dart`
defaulted the city to `'Brussels'` and the theme to `'petrichor'`. All now
render an em-dash through one `_kNoValue` constant.

**Still outstanding, and it matters:** the same fiction lives one layer down, at
JSON parse time — `dataviz_models.dart` (`?? 160717`, `?? 102.4`, `?? 38572`,
`?? 30000`, `?? 1013.0`, `?? 100`) and `api/models.dart` (`?? 112`, `?? 102`,
`?? 112.0`, `?? 102.0`). The screen-level fix is cosmetic while the model layer
invents 160717 before the screen ever sees it. **This is the single highest-value
follow-up in this list.**

## Verification — what actually ran

Measured on the final tree by the coordinator, not reported second-hand:

| Check | Result |
|---|---|
| `flutter analyze --no-pub` | **19 issues** (from a 43 baseline), 5 errors |
| `flutter test --no-pub` | **182 passing** (from 66) |
| `pytest -q` | **exit 0**, green (from ~896 tests to ~1015) |
| `flutter build web --release --no-pub` | **succeeded**, `✓ Built build/web` |

The 5 remaining analyzer errors are the pre-existing `allowInterop` ones in
`lib/advisor/voice_io_web.dart` (×4) and `lib/pwa/pwa_install_web.dart` (×1).
They predate this rework. Clearing them means migrating to `dart:js_interop`,
which could not be validated without a browser, so they were deliberately left
rather than changed blind.

### What could NOT be verified

* **Screenshots at 390px / desktop.** No browser is reachable from the build
  environment, and a local web server does not outlive a single command, so
  neither a headless capture nor an external browser could reach the built app.
  The 390px claims in this document are backed by **widget tests that measure
  real rendered geometry** at 390×844 — including the Forge Guided body at
  105px against its 120px budget, and screen-level overflow tests that fail on
  a `RenderFlex` — but nobody has looked at a picture of this app.
* **Anything requiring a live upstream.** Open-Meteo / Google Weather, Last.fm,
  Spotify, Firestore, BigQuery and Gemini are all unreachable offline. Only the
  degraded branches were exercised. In particular the Gemini Live session and
  real BigQuery answers have never run against the real services.
* **OAuth completion** (synthetic codes only) and anything behind a real
  Firebase bearer token.
* **`pydantic-settings` could not be installed**, so the backend suite was run
  with an offline stand-in supplied from outside the repo on `PYTHONPATH`. No
  repo code depends on it and it is not committed — but it does mean the suite
  has not been run against the real package in this environment.


---

# Multi-tenancy rework — decision log

A seven-item pass over tenancy, following the discovery of commit `9820091`:
the forge **write** path resolved the caller via `current_user_id` (bearer
token → `request.state` → `X-Barogroove-User`) while the almanac **read** path
checked only the bearer token and otherwise fell back to the literal uid
`"demo"`. Writes and reads landed in different buckets.

That bug was treated as an instance, not an incident. The audit
([TENANCY_AUDIT.md](./TENANCY_AUDIT.md)) went looking for the rest of the class
and found 13 more; a 14th surfaced during the fixing.

## The rule that came out of it

> **A path that cannot resolve an identity must refuse. It must never
> substitute a different concrete identity.**

The substitution is the whole danger. A path that raises on an unresolvable
identity fails loudly in a test. A path that substitutes `"demo"` returns `200`
with somebody else's data in it, and looks healthy from every angle a
monitoring dashboard can see.

## Decisions

**Anonymous callers get a reserved scope, not a real tenant.**
`anonymous_unauthenticated` owns nothing and cannot collide with a Firebase uid
(28 alphanumerics). The alternative — keep mapping signed-out visitors onto
`"demo"` — is what caused the leaks: `demo` and `jpaquay` are *real accounts
with real rows*. A reserved scope also makes sibling surfaces agree; before
this, an anonymous caller was `"demo"` to the advisor and `"jpaquay"` to
dataviz, and the two were reconciled by an explicit two-way alias in the
telemetry store — a cross-tenant leak wearing a bugfix's hat.

**The profile is provisioned at first authenticated contact, not first forge.**
It is the anchor history, collection and taste hang off, so it must exist before
any of them are written. Idempotent, and it back-fills users who predate the
change.

**The `_ENSURED` cache is a cache of a completed write, never a data source.**
Keyed by uid, holds no profile data, and only records writes that already
succeeded. A stale entry costs one redundant idempotent write, never a wrong
answer. This was written against the shape of audit finding 3, where a render
cache (`_RECENT_PLAYLISTS`) quietly became the source of a user's almanac.

**A `user_id` in a request body is not an identity.** Finding 14. The helper
that fills in a default theme and genre was also allowed to supply the forge's
owner, so an unauthenticated caller could name a victim's uid and publish into
their Spotify account. Defaulting is for preferences, never for identity.

**Demo mode reads the seed corpus and writes nothing.** The corpus was also the
runtime cache directory, so the app mutated its own git-tracked seed on every
Q&A cache miss — the stray untracked files under `data/scrobbles/qna_cache/`
were this, observed for a while and misfiled as noise. Reads and writes are now
separate directories.

**A refused write raises; it does not silently redirect.** A redirect would mean
the caller believes something happened that did not — the same shape as the
identity fallbacks this rework removes.

**Fixing state fixation was pulled in, not deferred.** The Last.fm callback
matched *any* pending state rather than the one bound to the token; it had been
flagged earlier and left. It sat directly in item 4's path, and leaving a known
credential-write hole open while rewriting the code around it was not
defensible. Exact-key match, owner-checked, not consumed on refusal.

**Tests assert refusal, not success.** A test that only checks "A sees A's data"
passes against every bug in the audit. Every tenancy test added here was
verified to **fail** against the unfixed code by reverting each fix in turn.
`test_demo_readonly.py` additionally fingerprints every file in the seed corpus
before and after, so a regression that writes somewhere no test named still
fails.

**The Firestore rules were read and left alone.** They are already default-deny
and anchored to `request.auth.uid`, and the token subcollection is unreadable by
every client including the owner. Nothing here added a collection or a
client-read field, so changing them would have been churn on the one layer that
was already correct.

## Deliberately not done

**The scrobble corpus is still single-tenant** (finding 9). One process-global
set of catalog indices, no uid in any key. No leak between two signed-in users
is possible, because no second corpus can exist to leak from — but per-user
collections do not exist either, and a second corpus would land in the same
globals. Making it per-uid is a feature with a data-model decision behind it,
not a bugfix, and doing it half-way under a tenancy pass would have been worse
than leaving it legible. The `"jpaquay"` defaults are now a named constant so
the single-tenancy is stated rather than implied.

**`models.dart` still defaults a missing `user_id` to `'demo'`** on parse
(finding 12). Display-side only, and the server no longer sends a row without an
owner.

**`_states` remains per-process.** A multi-instance deployment will see spurious
"unknown state" on pairing callbacks. That is durability, not tenancy, and
fixing it means moving pending pairings into Firestore.

## What could NOT be verified

* **Anything requiring a live Firestore.** No network and no
  `google-cloud-firestore` in this environment. The repository layer is
  exercised through fakes and an import shim, never against a real backend or
  the emulator. The **Firestore rules in particular have not been executed** —
  there is no emulator here, so the claim that they enforce the same boundary as
  the Python rests on reading them, not on running them.
* **The live Last.fm exchange.** The helper is unconfigured offline, so
  callbacks return `503` *after* the state check. The tests pin the ordering of
  the refusal, not the exchange itself.
* **The Fernet/Firestore token vault** — in-memory in tests.
* **OAuth completion** — synthetic codes only.

One environment note, correcting the previous entry in this file:
`pydantic-settings` *was* available this time, from a local package cache, so
the backend suite ran against the real package rather than an offline stand-in.
No repo code changed to make that work.

## Verification

Baseline held or improved throughout. Final:

| Check | Before | After |
| :--- | :--- | :--- |
| `flutter analyze` | 19 issues | 19 issues |
| `flutter test` | 182 passed | 185 passed |
| `pytest` | 1007 passed, 8 skipped | 1068 passed, 8 skipped |

No pre-existing test was deleted. Three encoded behaviour that this rework makes
wrong — two relied on the shared anonymous bucket, one asserted that an
anonymous forge lands in the `"demo"` tenant. All three were updated to state an
identity explicitly, with the reason commented in place, and the third now also
asserts the playlist is **not** in the demo tenant's bucket.

# BAROGROOVE — Flutter client

> Your sky has a soundtrack.

One codebase, web + mobile. Deploys to **bg.netdev.be** via Firebase Hosting.

---

## THE ONE RULE

**This app is an A2UI renderer. The UI is defined once, in Python, and rendered
here. Do not build a second one.**

BAROGROOVE declares its A2UI v1.0 component catalog exactly once, on the
server, and serves it from `GET /api/surfaces/catalog`. The screens in
`lib/screens/` fetch A2UI message streams and hand them to
`lib/a2ui/renderer.dart`. The MCP server emits the same JSON. There is one
definition of the interface and three consumers of it.

Concretely, this means:

* **Do not hard-code a screen layout the server already describes.** If you
  want the rationale above the tracklist instead of below it, that is a change
  to the Python surface builder, not to Dart.
* **Do not add local selection state to make a chip feel snappier.** A theme
  chip fires an action; the agent decides what that means and sends messages
  back. The moment the client decides what an interaction means, the two
  surfaces start to drift and the mobile app quietly becomes a different
  product from the web app.
* **Hand-built layout is allowed only for shell chrome:** navigation, the app
  bar, sign-in, pairing cards, the boot-failure screen. Those are about the
  client's relationship with the platform, and the agent has no view on them.

There are exactly two places in this client that compose domain content, both
clearly marked `_fallbackEnvelope` (in `playlist_screen.dart` and
`almanac_screen.dart`). They exist so a backend that has not shipped its
playlist/almanac surface yet still produces a usable page. Even they go
*through* the renderer, using the same catalog components — they pick a
component, never a layout. If you extend the playlist page, extend the server
surface; adding to the fallback and stopping there means the real path never
gets it.

---

## Did you use the official A2UI Flutter renderer?

**We found it. We did not take it as a dependency.** Here is the reasoning, so
you can revisit the call rather than rediscover it.

There is a real, published, Google-maintained Flutter implementation of A2UI:

| Package | What it is |
|---|---|
| [`genui`](https://pub.dev/packages/genui) | The core generative-UI framework. Explicitly "implements the A2UI protocol (https://a2ui.org)". Ships `Catalog`, `CatalogItem`, `DataModel`, `SurfaceController`, `A2uiParserTransformer`, `Surface`. |
| [`genui_a2a`](https://pub.dev/packages/genui_a2a) / `genui_a2ui` | Transport integration — connects `genui` to an A2A server over WebSocket. |
| [`genui_catalog`](https://pub.dev/packages/genui_catalog) | ~17 stock components built on `genui`. |

Three reasons we wrote our own instead:

1. **Catalog ownership is backwards for us.** `genui` requires the *client* to
   declare the catalog: one `CatalogItem` per component, each with its JSON
   schema and builder. BAROGROOVE's entire premise is that the catalog is
   declared once in Python. Adopting `genui` would mean re-declaring six
   schemas in Dart — precisely the duplication this project exists to avoid.
2. **Transport shape.** `genui`'s high-level API is a conversational
   `Conversation` / `SurfaceController` over a streaming A2A WebSocket. Our
   backend serves plain HTTP endpoints returning a *batch* (JSON array) of
   envelopes, with `POST /api/surfaces/action` as the return path. We would
   have used a tenth of the package and fought the rest.
3. **Pre-1.0 API, unverifiable here.** `genui` is still moving and this module
   was written without a Flutter SDK available to compile against. Taking a
   hard dependency on symbol names we could not verify would mean shipping
   code that looks right and does not build.

What we wrote instead is small enough to read in one sitting: four core files
plus one widget per catalog component. See `pubspec.yaml` for the commented-out
dependency and the swap notes. **If `genui` reaches 1.0 with a
server-supplied-catalog story, revisit this** — `lib/a2ui/renderer.dart` and
`lib/a2ui/data_model.dart` are the only two files that would go away.

---

## What was verified vs. assumed

Verified against a2ui.org, pub.dev and current package docs:

* The six agent→renderer message types (`createSurface`, `updateComponents`,
  `updateDataModel`, `deleteSurface`, `callRendererFunction`,
  `agentFunctionResponse`) and the three renderer→agent types
  (`callAgentFunction`, `rendererFunctionResponse`, `actionResponse`).
* v1.0 renames `theme` → `surfaceProperties`, adds action IDs, and allows
  single-message UI instantiation.
* `createSurface` implicitly instantiates a Surface whose child is the
  component with `"id": "root"`.
* Dynamic\* binding accepts a literal, a JSON-Pointer path, or a FunctionCall.
* `ChildList` accepts an explicit id array or a template + data-binding path.
* `google_sign_in` 7.x is a breaking redesign: `GoogleSignIn.instance`,
  mandatory `initialize()`, `authenticate()` (which **throws
  `UnsupportedError` on web**), `attemptLightweightAuthentication()` replacing
  `signInSilently()`, and `GoogleSignInAuthentication` exposing `idToken` only
  (the access token moved to `authorizationClient`).

Marked `UNVERIFIED` in the source where it matters:

* Exact JSON key spelling inside Dynamic\* wrappers and `ChildList`. The parser
  is deliberately lenient and accepts every plausible spelling.
* Whether `actionResponse` carries a `timestamp` (we send one; a server that
  ignores it loses nothing).
* Exact patch versions in `pubspec.yaml` — caret ranges will resolve forward.
* Whether `GoogleSignIn.initialize()` needs an explicit `clientId` on Android
  in the current release.
* Which side completes the Spotify PKCE exchange. Both are supported: we
  generate the verifier client-side and the backend can ask for it.

---

## Layout

```
lib/
  main.dart              App bootstrap, Firebase init, the one routing decision
  config.dart            --dart-define configuration
  app_theme.dart         The visual register (slate / sky / gold, light default)
  providers.dart         Riverpod wiring
  firebase_options.dart  PLACEHOLDERS — regenerate with `flutterfire configure`

  a2ui/                  ← THE RENDERER. The heart of the module.
    messages.dart          Typed A2UI v1.0 envelope models. Total parsing.
    data_model.dart        JSON-Pointer document + path-scoped change tracking
    catalog.dart           type name → widget builder; A2uiNode; placeholders
    renderer.dart          Surface controller + the view that builds from "root"
    actions.dart           Renderer → agent dispatch to /api/surfaces/action
    components/            One widget per catalog component
      sky_dial.dart          Derivative-dominant. pressure_trend_6h is the hero.
      theme_chips.dart       No local selection state. On purpose.
      genre_corridor.dart    A genre as an interval, not a label
      track_list.dart        The set's arc made visible; per-track `why`
      rationale_card.dart    THE HERO CARD
      almanac_timeline.dart  A record, not a feed

  api/
    models.dart          Domain models mirroring the Python contracts
    client.dart          Typed client: timeouts, backoff+jitter, honest errors
    auth_interceptor.dart  Firebase ID token on every request, 401 → refresh

  auth/
    auth_service.dart    Google sign-in (web popup / mobile credential split)
    pairing_service.dart Spotify PKCE + Last.fm web auth, in-app, no key paste
    sign_in_screen.dart

  screens/               Thin shell. Fetch a surface, hand it to the renderer.
    shell.dart             Nav rail / bottom bar, account menu, health pip
    home_screen.dart       Forge — renders /api/surfaces/sky + /themes
    playlist_screen.dart   The set
    almanac_screen.dart    History + retrospective
    settings_screen.dart   Account, pairing, backend info, About
    widgets/               Shared chrome (Section, DegradedNotes)

test/
  a2ui_renderer_test.dart  Envelope parsing, pointers, templates, degradation
web/
  index.html, manifest.json
```

### Screens

| Screen | Source of its content |
|---|---|
| Sign-in | Hand-built (no session, no surface) |
| Forge (home) | `GET /api/surfaces/sky` + `GET /api/surfaces/themes` → renderer |
| Set (playlist) | `POST /api/surfaces/action` `showPlaylist` → renderer (fallback shim) |
| Almanac | `POST /api/surfaces/action` `showAlmanac` → renderer (fallback shim) |
| Settings | Hand-built — platform/config concerns only |

---

## Renderer architecture

```
HTTP body ──► A2uiMessage.parseBatch()  ── total, never throws
                        │
                        ▼
            A2uiSurfaceController          implements A2uiHost
              ├── Map<String, A2uiComponent>   components by id
              ├── SurfaceDataModel             JSON-Pointer document
              ├── SurfaceProperties            v1.0 accent tint
              └── List<SurfaceIssue>           what went wrong, shown honestly
                        │
                        ▼
              A2uiSurfaceView  ──► buildById('root')
                        │
                        ▼
                  A2uiCatalog     type name → builder
                        │
                        ▼
                    A2uiNode      resolves bindings in a scope
                        │
                   ┌────┴────┐
              known type   unknown type
                   │            │
              your widget   A2uiPlaceholder
```

**Change granularity.** `SurfaceDataModel` records the revision at which each
pointer was written. `revisionFor('/sky')` returns the latest revision of
anything intersecting `/sky`, so an `updateDataModel` on `/tracks` does not
invalidate the SkyDial. Containment runs both ways: a write to `/sky/gust`
invalidates a binding on `/sky`, and vice versa.

**Template expansion.** A `ChildList` in template form names a prototype
component and a bound array. The renderer builds the prototype once per
element with the data scope rebased onto `<path>/<index>`, so the prototype
writes `title` and gets the right row's title. Absolute pointers (leading `/`)
still reach the surface root, so a row can read `/sky/cloud_depth`.

**Failure policy — nothing in the render path throws.**

| Problem | Result |
|---|---|
| Malformed JSON / unknown envelope | `UnknownA2uiMessage` → issue banner |
| Unknown component type | Inline placeholder naming the type and the known set |
| Referenced but undefined component | Inline placeholder |
| Binding that does not resolve | Inline placeholder naming the missing segment |
| Component graph cycle | Branch cut, placeholder |
| Builder throws | Caught, placeholder, `debugPrint` in debug |
| No component with id `root` | Placeholder listing what *was* defined |

A bad message never white-screens the app. It also is never hidden — an
explanation-first product that silently swallows its own errors would be a
strange thing.

---

## Running it

### Prerequisites

* Flutter 3.24+ (Dart 3.5+)
* A Firebase project with Google sign-in enabled
* The BAROGROOVE backend, locally or deployed

### First run

```bash
cd barogroove/frontend

# 1. Firebase config — this replaces the PLACEHOLDER firebase_options.dart
dart pub global activate flutterfire_cli
flutterfire configure --project=<your-firebase-project>

# 2. Dependencies
flutter pub get
```

### Web, against a local backend

```bash
flutter run -d chrome --dart-define=BG_API_BASE=http://localhost:8000
```

Your backend must allow the Flutter dev-server origin via CORS. If you would
rather not deal with CORS, run Chrome against the Hosting emulator instead
(below), which puts everything on one origin.

### Mobile, against a local backend

```bash
# Android emulator: localhost on the host is 10.0.2.2 from inside the emulator
flutter run -d emulator-5554 --dart-define=BG_API_BASE=http://10.0.2.2:8000

# iOS simulator shares the host's loopback
flutter run -d "iPhone 15" --dart-define=BG_API_BASE=http://localhost:8000

# A physical device needs your machine's LAN address
flutter run -d <device-id> --dart-define=BG_API_BASE=http://192.168.1.42:8000
```

Android also needs cleartext HTTP allowed for local dev, or use an `https`
tunnel. iOS/macOS need the outbound-network entitlement in
`{ios,macos}/Runner/*.entitlements`.

### Against production

```bash
flutter run -d chrome --dart-define=BG_API_BASE=https://bg.netdev.be
```

Leaving `BG_API_BASE` empty means **same origin**, which is what production web
builds want — Hosting rewrites `/api/**` and `/mcp/**` to Cloud Run in
`europe-west1`, so relative paths just work. Do not set it to empty on mobile;
there is no origin to be the same as.

### All dart-defines

| Define | Default | Purpose |
|---|---|---|
| `BG_API_BASE` | `http://localhost:8000` | Backend base URL. Empty = same origin. |
| `BG_STRICT_AUTH` | `false` | Refuse the anonymous demo forge. |
| `BG_GOOGLE_CLIENT_ID` | *(unset)* | Override the platform OAuth client id. |
| `BG_GOOGLE_SERVER_CLIENT_ID` | *(unset)* | Server client id for Android. |

---

## Building for Firebase Hosting

```bash
flutter build web --release --dart-define=BG_API_BASE=
```

Output lands in **`frontend/build/web`**, which is the directory Hosting
serves. The `firebase.json` at the repo root (owned by another module) should
point `hosting.public` at `frontend/build/web` and carry the rewrites:

```jsonc
{
  "hosting": {
    "public": "frontend/build/web",
    "ignore": ["firebase.json", "**/.*", "**/node_modules/**"],
    "rewrites": [
      { "source": "/api/**", "run": { "serviceId": "barogroove", "region": "europe-west1" } },
      { "source": "/mcp/**", "run": { "serviceId": "barogroove", "region": "europe-west1" } },
      { "source": "/legacy",  "run": { "serviceId": "barogroove", "region": "europe-west1" } },
      { "source": "**", "destination": "/index.html" }
    ]
  }
}
```

Then:

```bash
firebase emulators:start --only hosting   # local, same-origin, no CORS
firebase deploy --only hosting
```

**Do not forget:** add `bg.netdev.be` to Firebase Auth → Settings → Authorised
domains, or the Google sign-in popup is rejected in production with
`unauthorized-domain`. The app surfaces that error by name rather than as a
generic failure, so you will know.

### Testing

```bash
flutter analyze
flutter test
```

`test/a2ui_renderer_test.dart` covers envelope parsing, JSON-Pointer
resolution (including `~0`/`~1` escaping and `~01` ordering), revision
scoping, ChildList template expansion, action payload resolution in scope, and
that every degradation path renders a placeholder instead of throwing.

---

## Pairing

The user never sees, types or pastes an API key. Anything that asks a human to
copy a token out of a browser is a broken product, not a security measure.

1. Client generates a PKCE verifier/challenge (Spotify) and POSTs the challenge
   to `/api/pair/spotify/start`; backend returns `authorize_url` + `state`.
2. Client launches that URL — a new tab on web, the system browser on mobile.
3. The provider redirects to the **backend's** callback. The backend holds the
   client secret, completes the exchange, and stores tokens against the
   Firebase uid.
4. Client polls `/api/pair/status` until the provider flips to connected.

Polling rather than deep-linking is deliberate: a deep link needs a custom URL
scheme registered on both mobile platforms plus a web redirect page, and it
fails silently in exactly the situations (in-app browsers, SSO interstitials)
where you most need it. Polling a status endpoint is dull and always works.

Degradation is stated on the pairing cards before the user chooses, not
discovered afterwards:

* **No Spotify** → a forged set comes back as an M3U file you download.
* **No Last.fm** → no taste signal; the forge runs theme-only and the rationale
  says so.

---

## Design register

Executive instrument panel, not a music app. The reference is the EHDS portal:
slate structure, sky blue for interaction, gold rationed to things that have
earned it. **Light mode is the default and the intended register**; the dark
variant exists because a system-wide dark preference is not ours to override.

* **Slate** carries all structure — text, chrome, borders, the tertiary meters.
* **Sky blue** means "you can act on this", and marks falling pressure.
* **Gold** appears on the rationale card's top rule, the peak track, the
  confidence meter and the degraded notice. Nowhere else. If it is everywhere
  it is nothing.
* Typography is confident and quiet: tight tracking on display sizes, generous
  line height on body copy, tabular figures on every number.
* Theme palettes from `/api/themes` **tint**; they never repaint. `storm_front`
  moves the accent. It does not make the app purple.
* Nothing glows, shimmers or bounces. Loading states are a 2px determinate rule.

Two components deserve their reasoning restated, because it is easy to
"simplify" both into something worse:

**SkyDial** does not draw nine equal spokes. `pressure_trend_6h` gets a large
signed arc, a display-size numeral and a plain-language reading — roughly half
the component's visual weight. The two normalised deviations get a secondary
bipolar pair; the remaining six get a quiet magnitude strip. A radar chart
would have been easier and would have asserted that all nine dimensions matter
equally. They do not. The derivative is the product's whole thesis.

**RationaleCard** is the largest thing on the page. A recommender that cannot
explain itself is a slot machine. The confidence figure and the `degraded[]`
list get the same prominence as the good news, because an explanation that
omits its own caveats is marketing.

---

## Security notes

* **No real secrets in this tree.** `lib/firebase_options.dart` and the config
  block in `web/index.html` are marked placeholders. Regenerate with
  `flutterfire configure`, or better, let Hosting serve
  `/__/firebase/init.js` so staging and production stop being a copy-paste
  problem.
* OAuth client secrets live on the backend. The client holds a PKCE verifier
  and nothing else.
* The A2UI catalog is the security boundary: the agent can only name component
  types registered in `buildBarogrooveCatalog()`. An unknown type executes
  nothing and renders a placeholder. Adding a component to that map is the one
  change in this codebase that widens what a server can make the client draw —
  review it accordingly.

---

## The easter egg

There is a `GET /legacy` button in Settings → About. It returns
`Hello World!!`. That is all. Don't explain it to anyone.

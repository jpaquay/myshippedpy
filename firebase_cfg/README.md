# Barogroove — Firebase configuration

Everything Firebase-side for `bg.netdev.be`. Region for every Google Cloud
resource this app touches is **`europe-west1`**. Not negotiable, not a default,
not something to "just try in us-central1 for the demo".

```
firebase_cfg/
├── firebase.json            Hosting, rewrites to Cloud Run, headers, emulators
├── .firebaserc.example      Project aliases — copy to .firebaserc, never commit the real one
├── firestore.rules          Security rules (default deny)
├── firestore.indexes.json   Composite indexes
└── README.md                This file — including the "why" for each index
```

Deploy from this directory:

```bash
firebase deploy --only hosting,firestore:rules,firestore:indexes --project <alias>
```

---

## Why each composite index exists

Firestore auto-indexes every single field. It does **not** auto-create the
composite indexes a `where(...) + order_by(...)` combination needs, and it does
not degrade gracefully when one is missing — the query fails outright with a
`FAILED_PRECONDITION` and a console link. JSON has no comment syntax, so the
justifications live here. Each entry below maps one-to-one onto an entry in
`firestore.indexes.json`, in the same order.

### `forges`

| Fields | Serves | Why it is needed |
|---|---|---|
| `user_id ASC, created_at DESC` | `ForgeRepository.list_for_user()` — the `/api/almanac/history` sidebar | The single hottest query in the app: every history load and every retrospective runs it. An equality filter combined with an order-by on a *different* field always requires a composite index. |
| `user_id ASC, theme_id ASC, created_at DESC` | `list_for_user(theme_id=...)` — "show me every downpour I ever forged" | Two equality filters plus an ordering. The two-field index above cannot serve it: Firestore will not use a prefix of the wrong shape. Field order matters — equality filters first, range/ordering last. |
| `public ASC, created_at DESC` | The shared-playlist gallery: recently shared forges | Reads the world-readable slice of the collection. Small, but without it the gallery cannot be ordered by recency at all. Guarded by the `public: true` clause in `firestore.rules`. |

### `feedback`

| Fields | Serves | Why it is needed |
|---|---|---|
| `user_id ASC, playlist_id ASC, created_at DESC` | `FeedbackRepository.for_playlist()` — replaying which tracks you hearted in one forge | Two equality filters plus recency ordering. Used on every history detail view to re-render the heart states. |
| `user_id ASC, created_at DESC` | `FeedbackRepository.for_user()` — the training set for the Almanac worker's ridge regression | The learning loop reads the most recent N signals per user. Recency ordering matters because the fit is time-weighted; without the index it would have to read the whole collection and sort in memory. |
| `user_id ASC, signal ASC, created_at DESC` | "what have I skipped lately" — negative-signal analysis | Lets the fit pull loved and skipped rows separately rather than reading everything and partitioning client-side. Cheaper at the ten-thousand-row scale where it starts to matter. |

### `fieldOverrides` — indexes we deliberately turn **off**

Single-field indexing is on by default for every field, including large nested
maps and arrays. That costs storage and write latency on fields nobody ever
filters by.

- `forges.tracks` — a 60-element array of nested track maps. Never queried.
  Indexing it means an index entry per array element per document, which is the
  single largest avoidable write cost in this schema.
- `forges.rationale` — a nested explanation blob. Read whole, never filtered.
- `almanac.delta` — the flattened 63-float matrix. Filtering on an individual
  coefficient is meaningless.

---

## Hosting configuration notes

### Rewrite to Cloud Run — verified syntax

```json
{ "source": "/api/**", "run": { "serviceId": "barogroove-api", "region": "europe-west1" } }
```

Verified against the Cloud Run custom-domain docs and the Firebase Hosting
full-config reference:

- The key is **`run`**, and it takes `serviceId` and `region`.
- **`region` is effectively required here.** If omitted, Firebase falls back to
  `us-central1`. Since our service lives in `europe-west1`, leaving it out
  produces a rewrite that points at nothing — a 404 that looks like a routing
  bug and is actually a geography bug.
- `pinTag: true` is available and pins preview channels to the revision tagged
  at deploy time. Not enabled in production: we want the live channel to follow
  the latest revision.

### Ordering of rewrites

Rewrites are evaluated **in array order, first match wins**, and only when no
static file exists at the requested path. `/api/**`, `/mcp/**` and `/legacy`
therefore come before the `**` SPA fallback. Reverse that order and every API
call gets `index.html` with a 200 status, which is a spectacularly confusing
failure mode for a frontend developer.

### Cache headers

- Flutter web emits content-hashed asset filenames, so `*.@(js|css|woff2|...)`
  gets `max-age=31536000, immutable`. A hashed file's content never changes;
  caching it for a year is free correctness.
- `index.html`, `flutter_service_worker.js`, `version.json` and `manifest.json`
  get `no-cache`. These are the files that point at the hashed ones. Cache them
  and users get pinned to a stale build with no way out.

### Security headers

`X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options: DENY`,
`Permissions-Policy` and an HSTS header with a one-year max-age.

`Content-Security-Policy` is set but **UNVERIFIED against a real Flutter web
build**: Flutter's CanvasKit renderer loads WASM from `gstatic.com` and, in
some build configurations, needs `'wasm-unsafe-eval'` or `'unsafe-eval'` in
`script-src`. Deploy to a preview channel and read the browser console before
trusting it in production. If the app renders blank, CSP is the first suspect.

### Emulators

`firebase emulators:start` brings up auth (9099), firestore (8080) and hosting
(5000), with the emulator UI on 4000. Note that **hosting rewrites to Cloud Run
are not emulated** — the emulator has no way to run your container. Point the
frontend at a locally running `uvicorn` on 8000 during development, or deploy
the backend to a Cloud Run revision and hit it directly.

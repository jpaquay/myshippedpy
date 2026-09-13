# BAROGROOVE — tenancy gap audit

Status: **findings, pre-fix**. Produced as item 1 of the multi-tenancy rework;
items 2–5 fix what is listed here. Written against `5ef6df9`.

## Why this audit exists

Commit `9820091` fixed a bug where the forge **write** path resolved the caller
via `routes.pairing.current_user_id` (bearer token → `request.state` →
`X-Barogroove-User` header) while the almanac **read** path only checked the
bearer token and otherwise fell back to the literal user id `"demo"`. Writes and
reads therefore landed in different buckets.

That was not a one-off. It is a *defect class*: **a read or write path that,
when it cannot resolve an identity, silently substitutes a different one**
instead of refusing. This audit enumerates every remaining instance.

The substitution is what makes it dangerous. A path that raises on an
unresolvable identity fails loudly in a test. A path that substitutes `"demo"`
returns a 200 with someone else's data in it.

## How identity is supposed to resolve

`routes.pairing.current_user_id` is the one intended resolver:

1. `Authorization: Bearer <token>` → `firebase.auth.current_user_optional`;
2. `request.state.{user_id,uid,user}`;
3. `X-Barogroove-User` header (local development);
4. otherwise `None`.

Returning `None` rather than raising is deliberate — it keeps `/status` usable
for a signed-out client. That is sound. The bugs are all downstream, in callers
that turn that `None` (or a miss on a query) into a *concrete other user*.

## Findings

Severity: **S1** cross-tenant data disclosure or misattributed write ·
**S2** contamination / incorrect attribution · **S3** smell, no direct leak.

| # | Path | How identity resolves | Verdict |
|---|------|----------------------|---------|
| 1 | `almanac/firestore_store.py:162-168` — `history()` merge of `_PROCESS_FORGE_HISTORY` | `pl_uid in {user_id, "demo", None} **or not playlists**` | **S1 — leak** |
| 2 | `firebase/firestore.py:565-566` — `list_for_user()` | on empty result, re-queries `user_id="demo"` | **S1 — leak** |
| 3 | `routes/surfaces.py:852,883,903` — A2UI almanac/detail actions | reads process-global `_RECENT_PLAYLISTS`, unkeyed by uid | **S1 — leak** |
| 4 | `routes/surfaces.py:894-896` | on miss, retries `almanac().history("demo", limit=50)` | **S1 — leak** |
| 5 | `routes/pairing.py:~890` — Last.fm callback | `uid = pending.user_id if pending else **"jpaquay"**` | **S1 — misattributed write** |
| 6 | `routes/pairing.py:~979` — pairing callback | `user_id = pending.user_id if pending else **"demo_user"**` | **S2** |
| 7 | `telemetry/store.py:130-131` — `_match_user()` | `target in ("demo","jpaquay")` ⇒ matches `("demo","jpaquay")` | **S1 — leak** |
| 8 | `telemetry/{store,memory_extractor,models}.py` | `user_id: str = "demo"` default on 8 signatures/fields | **S2** |
| 9 | `almanac/scrobbles.py` — whole module | `user_id: str = "jpaquay"` default; corpus indices process-global | **S2 — single-tenant by construction** |
| 10 | `almanac/data_qna.py:50-51,227-229` | writes answer cache into `data/scrobbles/qna_cache/` at import time | **S2 — demo corpus is writable** |
| 11 | `routes/surfaces.py:841` | `uid = user.uid if user else "demo"` | **S2** |
| 12 | `frontend/lib/api/models.dart:1815,1892` | `asStringOrNull(json['user_id']) ?? 'demo'` | **S3** |
| 13 | `routes/pairing.py` — Last.fm callback state | matches *any* pending state, not the one bound to the token | **S3 — state fixation** |

### 1. `history()` merges every user's forges into an empty-history user — S1

```python
for pl in _PROCESS_FORGE_HISTORY:
    if pl_id and pl_id not in seen_ids:
        if pl_uid in {user_id, "demo", None} or not playlists:
            playlists.append(pl)
```

`or not playlists` short-circuits the ownership test entirely. **Root cause:** a
"don't show an empty screen" affordance written as a fallback on the ownership
predicate rather than on the empty state. Any user whose Firestore history query
returns nothing — which is *every brand-new user* — is served the process-wide
forge buffer, i.e. the last N playlists forged by anyone sharing that container
instance. The `"demo"` and `None` members of the set leak on top of that,
independent of the `or`.

### 2. `list_for_user()` falls back to the demo tenant — S1

```python
if not rows and user_id != "demo":
    rows = await _query_uid("demo")
```

Same shape, one layer down, in the Firestore repo itself. Root cause identical:
empty result treated as "wrong bucket, try the demo bucket" rather than as a
legitimate empty result.

### 3–4. A2UI surface actions read a process-global playlist cache — S1

`_RECENT_PLAYLISTS: dict[str, Any] = {}` at `surfaces.py:807` is keyed by
*playlist id*, never by uid, and is populated by every forge in the process. The
almanac action iterates all of its values (852); the detail action will serve
any playlist id a client names (883) and, failing that, `list(...)[-1]` — "the
last playlist anyone forged" (903). Line 894 then retries the lookup against the
literal `"demo"` history. Root cause: a render cache doubling as a data source.

### 5. The Last.fm callback attributes an orphan pairing to `jpaquay` — S1

`uid = pending.user_id if pending else "jpaquay"`. If the pending state has
expired or is unknown, the callback does not refuse — it writes the resulting
Last.fm session key into the vault of the literal user `jpaquay`. Combined with
finding 13 (the callback matches *any* pending state rather than the one bound
to the token), this is the most serious item in the table: it is a write, it
targets a real named account, and it is reachable by an unauthenticated caller
hitting the callback URL.

### 7. `demo` and `jpaquay` are hardcoded as the same tenant — S1

```python
if target_user_id in ("demo", "jpaquay"):
    return record_user_id in ("demo", "jpaquay")
```

An explicit two-way alias in the telemetry store's ownership check. AI
conversation history and extracted memories cross freely between the demo tenant
and the real user `jpaquay`. Root cause: a demo convenience promoted into the
ownership predicate instead of into the seeding code.

### 9. The scrobble corpus is single-tenant by construction — S2

`scrobbles.py` defaults `user_id` to `"jpaquay"` in the model, the row parser and
the search entry point, and holds the catalog in five process-global indices
(`_CATALOG_DICTS_CACHE`, `_CATALOG_INDEX_BY_NORM`, `_ARTIST_*_INDEX`) with no uid
in any key. `sync_scrobbles_from_lastfm(user_id, lastfm_username="jpaquay")`
ignores both arguments and returns `search_scrobbles(user_id)`. There is exactly
one corpus in the process and it is Jerome's. This is not a leak between two
signed-in users today — no second corpus can exist to leak *from* — but it means
"per-user collection" does not exist yet, and any future second corpus would
land in the same globals.

### 10. The demo corpus is writable, and is being written — S2

`data_qna.py` does `_QNA_CACHE_DIR.mkdir(parents=True, exist_ok=True)` **at
import time** and `disk_path.write_text(...)` on every cache miss, straight into
`data/scrobbles/qna_cache/`. The four untracked files in that directory in the
working tree are this code writing into the demo corpus during the session. The
read-only requirement for demo mode is currently violated by default.

## What is already sound — do not "fix" these

- **`firebase_cfg/firestore.rules`** is default-deny and anchors every rule to
  `request.auth.uid`. `users/{uid}/tokens/{provider}` is `read, write: if false`
  for all clients including the owner. Forge create requires `public == false`
  explicitly. The client-side boundary is in good shape; the gaps above are all
  on the backend Admin-SDK path, which bypasses rules by design.
- **`firebase/tokens.py`** — Fernet-encrypted, addressed `users/{uid}/tokens/{provider}`.
  No fallback uid anywhere in it.
- **Last.fm sessions keyed on the Barogroove uid, not the Last.fm username** —
  deliberate, because users rename. Preserve it.
- **`routes.pairing._in_memory_lastfm` / `_in_memory_spotify_meta`** — module-level
  dicts, but correctly keyed by `user_id` at every one of their 13 call sites.
  Process-local and lost on restart, which is a durability question, not a
  tenancy one.
- **`sinks/resolver.py:_CACHE`** — keyed on track identity, holds no user data.

## Scope handed to items 2–5

- **Item 2** — finding: `upsert_profile` has exactly one caller,
  `almanac/firestore_store.py:103`, inside `record_forge`. A profile is a side
  effect of a user's *first forge*; a user who signs in and browses exists to
  Firebase but not to Barogroove.
- **Item 3** — findings 1, 2, 3, 4, 7, 8, 9, 11, 12.
- **Item 4** — findings 5, 6, 13.
- **Item 5** — finding 10, plus the read-only guarantee for finding 9's corpus.

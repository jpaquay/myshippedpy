# BAROGROOVE — Navigation & Information-Architecture Spec

**Status:** normative. Plan item 7. This document is the brief for plan items 8–14.
**Audience:** the implementers of items 8, 9, 10, 11, 12, 13, 14.
**Rule of thumb:** if this spec says "must", do exactly that. If you find a case it
does not cover, pick the option that shows *less* on a 390 px screen.

---

## 0. The problem, stated once

BAROGROOVE has five good destinations and a cluttered surface. The bloat is
measurable — `dataviz_screen.dart` 2127 lines, `telemetry_inspector_panel.dart`
2272, `almanac_screen.dart` 1891, `gemini_live_advisor.dart` 1019,
`atmospheric_cursors_console.dart` 825, `shell.dart` 781 — but line count is the
symptom. The cause is that **everything is at rung 0**: every control, every
diagnostic, every affordance is visible at first glance, at every viewport, all
the time. There is no shared convention for "this is secondary", so nothing is.

This spec fixes three things:

1. **The header.** Five competing actions become two, plus status.
2. **A shared disclosure ladder.** Three rungs, named, so six implementers stop
   inventing four different "expand" patterns.
3. **One assistant, not two banners.** Gemini Live stops being page furniture and
   becomes app chrome.

### Which layer does a change belong to?

Per `A2UI_HANDOFF.md` and `docs/A2UI_ARCHITECTURE.md`, the backend *describes*
surfaces (`backend/app/a2ui/{catalog,palette,surfaces,protocol}.py`,
`backend/app/routes/surfaces.py`) and Flutter renders them generically
(`frontend/lib/a2ui/`). Content, ordering and grouping **inside** a surface is a
Python change. Chrome around surfaces is Dart.

| Change | Layer |
|---|---|
| Header, tab bar, nav rail, assistant overlay, theme control, badges | **Dart** — `frontend/lib/screens/shell.dart`, `frontend/lib/app_theme.dart` |
| What a surface contains, in what order, and what its eyebrows say | **Python** — `backend/app/a2ui/surfaces.py` |
| Whether a component exists at all / what it can bind / whether a function writes | **Python** — `backend/app/a2ui/catalog.py` (then regenerate `frontend/a2ui/catalog.json`) |
| Design tokens exposed to A2UI surfaces | **Python** — `backend/app/a2ui/palette.py` (`CATALOG["metadata"]["surfaceProperties"]`) |
| How a catalog component is painted | **Dart** — `frontend/lib/a2ui/` |
| Disclosure rung of a *section inside a surface* | **Python** — the builder emits the group; Dart renders `collapsed: true` generically |

Concretely for the in-flight items: item 8's three console modes are **Dart**
(the console is hand-built, not A2UI-driven) except the SkyDial it embeds, which
is A2UI. Item 9's chart cards are **Dart** today and should stay Dart for now.
Item 11's write/read classification is **Python** (a catalog flag), consumed by
**Dart**.

---

## 1. Header & tab-bar inventory — before and after

### 1.1 What is in the header today

Read from `frontend/lib/screens/shell.dart` (`AppShellState.build`, ~line 87).
The `AppBar` is: one title, five action widgets separated by spacers.

| # | Control (widget) | What it does today | Verdict | Where it goes |
|---|---|---|---|---|
| 1 | `BarogrooveWordmark(compact: true)` — AppBar `title` | App identity | **KEEP** | Header, left. Only always-visible identity element. Stays `compact: true` at every width; do not add a subtitle. |
| 2 | `_PwaInstallButton(bridge:, compact:)` — outlined pill, tooltip, opens a 3-step install bottom sheet | Prompts PWA install, hides itself when `isStandalone` | **MOVE to Settings** | New `Section(eyebrow: 'INSTALL')` in `settings_screen.dart`, above `ABOUT`. Plus **one** dismissible inline `Notice` at the bottom of Forge, shown at most once per browser (localStorage key `bg.install.dismissed`). Delete from the header entirely. Rationale: a one-time action does not earn permanent header space. |
| 3 | `_TelemetryInspectorAppBarButton` — icon + live call-count badge, opens `TelemetryInspectorPanel` in a 1120×780 `Dialog` | Ops diagnostics | **DELETE from header** | The panel already has *three* entry points (this button, the health-pip dialog's "Open Telemetry Inspector" action, and Data Viz segment 1). Keep exactly one: the health-pip sheet. Also see §3.4 — the panel should not be a Data Viz segment either. |
| 4 | `_HealthPip` — coloured dot; green/amber/red; tap opens an `AlertDialog` listing degraded subsystems + a telemetry summary | Backend honesty | **KEEP, demoted** | Header, right of the wordmark. **Silent when healthy:** when `health.ok && health.degraded.isEmpty`, render `SizedBox.shrink()` on viewports < 900 px (a hairline slate dot on desktop). Never green. Amber/red only. Tap target 40×40, visual dot 8 px. Replace the `AlertDialog` with a rung-2 bottom sheet (§2) that keeps the "Open Telemetry Inspector" and "Re-check" actions. |
| 5 | `_ThemeModeSwitchButton` — binary Sun/Moon toggle | Flips `themeModeProvider` | **MOVE to Settings** | Becomes the three-option control of §7.4. Deleted from the header. A read-only "Appearance — As host" row in the account menu deep-links to it. |
| 6 | `_AccountMenu` — avatar + popup | Sign in/out, account | **KEEP** | Header, far right. Becomes the **overflow host**: avatar → menu with `Appearance`, `Connections`, `Install app`, `Sign out`. On mobile the menu is a bottom sheet, not a `PopupMenuButton`. |
| 7 | `_ThemeModeSwitchButton` + a `'THEME'` `labelSmall` caption — `NavigationRail.trailing` (duplicate of #5) | Same toggle, second copy | **DELETE** | The rail's `trailing` becomes `null`. This duplicate is the one everyone forgets; it must go in the same change as #5. |
| 8 | *(new)* Spotify / Last.fm connection badges | — | **ADD, desktop only** | §7.5. Desktop ≥ 900 px: two monochrome badges between wordmark and health pip. Mobile: **not in the header** — they live in Settings → `CONNECTED SERVICES` and in the account sheet. |

**Resulting header.**

```
mobile  (<900px):   [ BAROGROOVE ]                        · (amber only)  (A)
desktop (>=900px):  [ BAROGROOVE ]        [SP] [FM]       · (amber only)  (A)
```

Two controls on mobile — the avatar and, when something is wrong, the status dot.
That is the whole budget.

### 1.2 What is in the navigation today

| Element | Today | Verdict |
|---|---|---|
| `BgDestination` enum — 5 values | forge / playlist / almanac / dataViz / settings | **KEEP all five, keep all five labels verbatim** (`Forge`, `Set`, `Almanac`, `Data Viz`, `Settings`). See §9. |
| `NavigationBar` (< 900 px) | 5 destinations, icon + label | **KEEP.** Labels always shown (`NavigationBar` default). `Data Viz` is the longest label and fits 78 px at `labelSmall` 11. |
| `NavigationRail` (≥ 900 px), `labelType: all` | 5 destinations + theme toggle in `trailing` | **KEEP the rail, DELETE the trailing block.** |
| `_FloatingMiniPlayerBar` — floats above the tab bar on every destination except Set, when `lastForgeProvider != null` | Title, "N-Track Daylist • Active in Player Deck", `OPEN DECK` button | **KEEP, with constraints.** Height 64. It is the *only* thing allowed to float above the tab bar besides the assistant bubble, and the bubble must stack above it (§6.2). Collapse the second line to just `N tracks` on < 390 px. |
| Destination icons | See §7.6 | **REPLACE the set** — monochrome, no sparkles. |

### 1.3 Icon set (item 12)

Current pairs are mixed-metaphor and one is an explicit placeholder.

| Destination | Today | **Use this** | Why |
|---|---|---|---|
| Forge | `explore_outlined` / `explore` | **unchanged** | A compass is an instrument. In register. |
| Set | `queue_music_outlined` / `queue_music` | **unchanged** | Literal, monochrome, unambiguous. |
| Almanac | `auto_stories_outlined` / `auto_stories` | **`menu_book_outlined` / `menu_book`** | `auto_stories` is the "magic book" glyph. The Almanac is a ledger, not a spellbook. |
| Data Viz | `insights_outlined` / `insights` (placeholder — the glyph carries a sparkle) | **`query_stats` (outlined variant unselected, filled-weight selected)** | A magnifier over a line chart = *asking questions of data*, which is precisely the BigQuery QnA agent. No sparkle, no gradient, reads at 24 px. |
| Settings | `tune_outlined` / `tune` | **`settings_outlined` / `settings`** | `tune` is sliders, which collides with the Forge cursor sliders. Reserve the slider metaphor for the console. |

Also replace, in chrome: `Icons.radar` (telemetry) → `Icons.monitor_heart_outlined`;
`Icons.bolt` (the FORGE CTA) → `Icons.play_arrow_rounded` is already used by the
mini-player, so use **`Icons.east`** (an arrow — "produce this") for FORGE;
`Icons.install_desktop_rounded` / `download_for_offline_rounded` →
`Icons.add_to_home_screen`. No icon in header or menu may be filled, coloured,
or larger than 20 px.

---

## 2. The disclosure ladder — one convention, three rungs

Every destination, every card, every implementer uses **these three rungs and no
others**. Build them once as shared widgets in
`frontend/lib/screens/widgets/bg_disclosure.dart` and reuse.

### Rung 0 — At a glance
Always visible. **Budget: the destination's rung-0 content must fit in ≤ 1.25
screen heights at 390 × 844 with the tab bar and header subtracted (≈ 700 px of
content).** If it does not fit, something moves to rung 1. This is a hard
acceptance criterion, not a guideline.

### Rung 1 — `BgDisclosure` (in place)
A styled `ExpansionTile`, **not** raw Material.
- `elevation: 0`, no fill, a 1 px `outlineVariant` rule above the header row.
- Header row: `labelSmall` (11 / w600 / +0.9 tracking), UPPERCASE, `onSurfaceVariant`;
  trailing `Icons.keyboard_arrow_down` 18 px rotating 180° over 180 ms.
- Optional trailing count badge (`(3)`), plain text, no pill.
- `initiallyExpanded: false` **always**, with exactly one exception per
  destination (named in §3–§5).
- Expansion state is held in a session-scoped
  `disclosureStateProvider` keyed `'<destination>/<sectionId>'`. Not persisted to
  disk — a fresh visit is a calm visit.
- **Never nest a `BgDisclosure` inside a `BgDisclosure`.** If you need two levels,
  the inner one is rung 2.

### Rung 2 — `BgDetailSheet` (out of flow)
For raw data, diagnostics, editors, and confirmations.
- `< 900 px`: `showModalBottomSheet`, `isScrollControlled: true`, top radius 16
  (the only radius above 10 in the app; it is the sheet grab-edge and is exempt),
  initial height 60 % of viewport, drag to 92 %, scrim `scrim` token.
- `≥ 900 px`: right-anchored side panel, width 420, full height, 1 px left rule,
  no scrim. (The existing 1120 × 780 `Dialog` used by the telemetry inspector is
  grandfathered — it is a genuine full-screen tool — but nothing new may use a
  `Dialog`.)
- Always has a visible `Close`. Never traps focus without one.

### Rules that bind everyone
1. **A primary CTA never lives behind a rung.** FORGE, Ask, Push to Spotify,
   Confirm — rung 0, always.
2. **Errors are never collapsed.** A `DegradedNotes` / error `Notice` is rung 0
   even if the section it belongs to is collapsed; it renders *above* the
   collapsed tile.
3. **Loading is rung 0 and shaped.** Use `_SurfaceSkeleton`-style block skeletons
   matching the final layout. No bare `CircularProgressIndicator` above rung 2.
4. **Empty states are rung 0 and honest.** They say what is missing and give one
   action. They never show placeholder numbers (see §9 contradiction #7).
5. Label rung-1 headers with a **noun phrase**, not "More" — `WHY THESE THREE`,
   `COEFFICIENTS`, `SOURCE QUERY`. "Advanced" is banned as a label; it is a
   rung, not a word.

---

## 3. Destination specs

Throughout: **M** = mobile 390 px, **D** = desktop ≥ 900 px.

### 3.1 Forge — `frontend/lib/screens/home_screen.dart` (870 lines)

**Purpose, one sentence:** turn *where you are and what the sky is doing right
now* into a playlist.

**Today (rung 0, in order):** `GeminiLiveAdvisorBanner` → `_ForgeHeader`
(location, geocache teleport, city presets, seed-scrobble chips) → `Section(
eyebrow: 'CURRENT BAROMETRIC READING')` with the A2UI `sky` surface → `Section(
eyebrow: 'SONIC CURATION CONSOLE')` with `AtmosphericCursorsConsole` →
`_ForgeActionDeck` (four `_DeckChip`s: OBSERVATORY / THEME / CORRIDOR / TASTE
ENGINE, then the FORGE `FilledButton`) → `DegradedNotes` (health) →
`DegradedNotes` (surface error) → forge-failure notice → `NetdevFooter`.

That is seven stacked blocks plus a banner before the user reaches the button
that is the entire point of the screen.

**Stays at rung 0:** location line (one line: label + coords, tappable) · the sky
reading, reduced to a **3-value strip** (temperature, pressure + trend arrow,
light) · the console's mode segmented control and its current-mode body · the
FORGE button · errors.

**Rung 1:** `OBSERVATORY` (city presets + teleport + geocache list — today's
`_ForgeHeader` body and the OBSERVATORY chip collapse into one tile) ·
`THEME & CORRIDOR` (the THEME and CORRIDOR deck chips become one tile showing
the two current selections as its subtitle) · `TASTE ENGINE` (seed scrobbles,
with a count badge) · `SKY DETAIL` (the full A2UI SkyDial — Expert mode promotes
this to rung 0, see §5.1).

**Rung 2:** raw forge request JSON (Expert only) · the install prompt sheet.

**Moves elsewhere:** `GeminiLiveAdvisorBanner` → **deleted**, folded into the
app-wide assistant overlay (§6). `NetdevFooter` → Settings → `ABOUT`. The
health `DegradedNotes` block → the health-pip sheet; only *forge-specific*
errors stay on Forge.

**Wireframe — M 390 px**

```
┌──────────────────────────────────────┐ 56  AppBar: BAROGROOVE        ·  (A)
├──────────────────────────────────────┤
│ Brussels, BE · 50.85, 4.35        ›  │ 44  _LocationLine (tap → rung1 OBSERVATORY)
│ 11°C   1004 hPa ↓   38% light        │ 40  _SkyStrip  (3 values, labelSmall+titleMedium)
├──────────────────────────────────────┤
│ ┌──────┬──────┬──────┐               │ 40  SegmentedButton<String>
│ │Guided│ Easy │Expert│               │     full width, 3 equal segments
│ └──────┴──────┴──────┘               │
│ Guided — we choose everything.       │ 18  helper line, bodySmall, muted
│                                      │
│ ╭──────────────────────────────────╮ │
│ │ Slower, denser, minor-key.       │ │ 72  _OutcomeCard  (rung 0)
│ │ Falling pressure asks for weight.│ │     title 18/w600 + 1 rationale line
│ ╰──────────────────────────────────╯ │
├──────────────────────────────────────┤
│ OBSERVATORY            Brussels   ⌄  │ 44  BgDisclosure (collapsed)
│ THEME & CORRIDOR   Petrichor·Amb  ⌄  │ 44  BgDisclosure (collapsed)
│ TASTE ENGINE                (0)   ⌄  │ 44  BgDisclosure (collapsed)
│ SKY DETAIL                        ⌄  │ 44  BgDisclosure (collapsed)
├──────────────────────────────────────┤
│ ╭──────────────────────────────────╮ │
│ │  →   FORGE                       │ │ 52  FilledButton, full width
│ ╰──────────────────────────────────╯ │
│                                      │ 96  bottom padding (bubble clearance)
└──────────────────────────────────────┘
        [mini-player 64, if any]        ← floats
        NavigationBar 80                ← fixed
```

Total rung-0 height ≈ 460 px. Comfortably inside budget; Expert mode uses the
slack.

**D adaptation:** content column stays `maxWidth: 1080` (unchanged). The four
`BgDisclosure` tiles become a 2 × 2 grid of **expanded** cards — at ≥ 900 px
there is room, and progressive disclosure is a mobile concession, not a
philosophy. The FORGE button stops being full-width; it is 240 px, right-aligned,
in a sticky footer rule. `SKY DETAIL` is expanded by default on D.

---

### 3.2 Set — `frontend/lib/screens/playlist_screen.dart` (586 lines)

**Purpose:** the playlist you just forged, playable and pushable.

**Today:** `_SetHeader` → fallback notice (`_usedFallback`) → loading state →
`A2uiSurfaceView` (the `playlist` surface: TrackList + RationaleCard) →
`_SinkBar` (push-to-Spotify / export) → `_EmptySet` when nothing forged.

This screen is the closest to right already. Two changes.

**Stays at rung 0:** playlist title + track count + forged-at · the track list ·
`_SinkBar` actions · `_EmptySet`.

**Rung 1:** `WHY THIS SET` — the `RationaleCard`. Today it sits inline under the
tracks and is the single longest block on the screen. It is a *justification*,
read once. Collapse it. **This is the one section allowed `initiallyExpanded:
true` on this destination when `trackCount <= 8`** (short set → the rationale is
the interesting part).

**Rung 2:** per-track detail (audio features, why this track) via long-press on a
`TrackRow` → `BgDetailSheet`. Today there is nowhere to put this; adding it here
keeps it off rung 0.

**Moves:** the mini-player bar is suppressed on this destination already
(`_current != BgDestination.playlist`) — keep that.

**Layer note:** the ordering of TrackList vs RationaleCard, and the collapsed
flag, are emitted by `build_playlist_surface` in
`backend/app/a2ui/surfaces.py`. **This is a Python change.** Dart only needs a
generic "render this group collapsed" capability in `frontend/lib/a2ui/`.

**Wireframe — M 390 px**

```
┌──────────────────────────────────────┐
│ Petrichor Drift                      │ 26  titleLarge
│ 14 tracks · forged 19:04 · Brussels  │ 18  bodySmall muted
├──────────────────────────────────────┤
│ 1  Track name              ·  4:02   │ 52  TrackRow (A2UI)
│    Artist                      ♡  ⤫  │
│ 2  …                                 │ 52
│ …                                    │
├──────────────────────────────────────┤
│ WHY THIS SET                      ⌄  │ 44  BgDisclosure → RationaleCard
├──────────────────────────────────────┤
│ ╭──────────────────────────────────╮ │
│ │  PUSH TO SPOTIFY                 │ │ 52  _SinkBar, sticky bottom
│ ╰──────────────────────────────────╯ │
│  Export .m3u   ·   Reforge           │ 36  text actions (Reforge → confirm, §6.4)
│                                      │ 96  bubble clearance
└──────────────────────────────────────┘
```

**D:** two columns — tracks left (flex 3), rationale right (flex 2) **expanded,
not collapsed**. `_SinkBar` moves to the top-right of the header row.

---

### 3.3 Almanac — `frontend/lib/screens/almanac_screen.dart` (1891 lines)

**Purpose:** the **static archive** — what you have already forged and already
listened to. *Fixed constraint: this does not merge with Data Viz. Almanac is
history you can page through; Data Viz is questions you can ask.*

**Today:** `_buildHeader` (title + a trailing action) → `_buildModeBar` (a
hand-rolled 3-way pill bar: `Forged Daylists (n)` / `Scrobble Catalog` /
`Cohort Matcher`) → `_buildKpiStrip` (KPI pills, always on, for all three modes)
→ one of `_buildForgedSetsView` / `_buildCatalogView` /
`_buildCohortMatcherView` → `_FloatingSeedBar` when scrobbles are selected.

Three problems: the mode bar is a bespoke widget duplicating
`SegmentedButton`; the KPI strip is shown for all three modes but is only
meaningful for two; and `Cohort Matcher` is analysis, not archive.

**Stays at rung 0:** the three-way mode control (**re-implemented as
`SegmentedButton<_AlmanacMode>`**, matching Forge's console control — one
segmented-control idiom in the app) · the list/grid for the active mode · the
`_FloatingSeedBar`.

**Rung 1:** `SUMMARY` — the KPI strip, collapsed by default on M, and **only
rendered for `forged` and `catalog` modes**. Expanded by default on D.

**Rung 2:** a forged set's full detail (today `_ForgedSetCard` expands inline and
makes the list jump) → `BgDetailSheet`. Cohort donut breakdown by segment →
sheet.

**Moves:** **`Cohort Matcher` stays on Almanac** — resist the urge to move it to
Data Viz. It operates on the *archive* (your scrobbles) and its output seeds the
Forge. Moving it would violate the archive/analytics split in the wrong
direction: Data Viz answers questions about data, Cohort Matcher selects rows
from it. The `_FloatingSeedBar` → Forge hand-off is the proof.

Its *charts*, however, belong to the analytics vocabulary. Reuse the Data Viz
chart-card widget rather than `_CohortDonutPainter`'s private copy.

**Wireframe — M 390 px**

```
┌──────────────────────────────────────┐
│ Almanac                              │ 26  titleLarge
│ 428 sets · 160,717 scrobbles         │ 18  bodySmall (real values only, §9 #7)
├──────────────────────────────────────┤
│ ┌───────┬────────┬────────┐          │ 40  SegmentedButton<_AlmanacMode>
│ │Forged │Catalog │Cohorts │          │     scrollable:false, equal widths
│ └───────┴────────┴────────┘          │
├──────────────────────────────────────┤
│ SUMMARY                           ⌄  │ 44  BgDisclosure → _KpiPill wrap
├──────────────────────────────────────┤
│ ╭──────────────────────────────────╮ │
│ │ Petrichor Drift          19:04 › │ │ 76  _ForgedSetCard (tap → rung-2 sheet)
│ │ 14 tracks · 1004 hPa ↓ · 11°C    │ │
│ ╰──────────────────────────────────╯ │
│ ╭──────────────────────────────────╮ │ 76
│ …                                    │
│                                      │ 96  bubble clearance
└──────────────────────────────────────┘
       [_FloatingSeedBar 56, if any]
```

**D:** `SUMMARY` expanded as a horizontal KPI row above the segmented control.
Forged sets become a 2-column grid. The rung-2 sheet becomes the right-side
panel; the list stays visible and highlights the open row.

---

### 3.4 Data Viz — `frontend/lib/screens/dataviz_screen.dart` (2127 lines)

**Purpose:** the **dynamic analytics surface** — ask a question about your
listening data in natural language, get a chart and a sentence back. *Fixed
constraint: this does not merge with Almanac.*

**Today:** a top `SegmentedButton<int>` with two segments —
`Sonic Almanac Analytics` (`Icons.insights_outlined`) and
`Live AI Telemetry & Trace Inspector` (`Icons.radar`) — then, for segment 0:
`_buildGeminiLiveQnaBanner` (a slate900→slate800 **gradient** box with voice
controls — the only gradient in the app) → `_buildSummaryKpiRibbon` → five fixed
dashboard cards (`_buildPressureVsBpmCard`, `_buildWeatherAffinityCard`,
`_buildHourlySolarCard`, `_buildDecadeSonicDnaCard`, …), 2-up on ≥ 920 px, with
an `isHighlighted` flag driven by `_lastQna?.highlightSection`. Segment 1 embeds
`TelemetryInspectorPanel` wholesale.

Segment 1 does not belong here. **Telemetry is ops, not analytics.** Remove the
`SegmentedButton` entirely; Data Viz becomes a single view. Telemetry's one
entry point is the health-pip sheet (§1.1 #3/#4).

**The conversational experience (item 9).** Structure, top to bottom:

1. **Question entry, rung 0, pinned.** A single-line `TextField`,
   `hintText: 'Ask about your listening data'`, leading `Icons.search` 18 px,
   trailing mic `Icons.mic_none` (monochrome; it does **not** pulse, glow, or
   animate at rest). Height 48, `BgSpace.br`, 1 px `outlineVariant`, no fill, no
   gradient. On mobile it is **sticky at the top** of the scroll view.
2. **Suggested questions.** Directly under the field, a single non-scrolling
   `Wrap` of **at most three** chips, `labelSmall`, outlined, monochrome.
   Sourced from the agent's `suggested_followups` when a conversation is live,
   otherwise three static starters. Never more than three; never a horizontal
   carousel.
3. **Answer cards.** Newest first, above the standing dashboard. One card per
   answered question:
   ```
   ╭────────────────────────────────────────╮
   │ “Which decade do I play in the rain?”  │  question, titleMedium, 2-line max
   │ ──────────────────────────────────────  │  1px rule
   │  The 1990s — 31% of wet-weather plays,  │  answer sentence, bodyMedium
   │  against 18% baseline.                  │
   │  ┌──────────────────────────────────┐   │  chart, fixed 180 h on M
   │  │       [donut / bar / line]       │   │  one of the four geometries in
   │  └──────────────────────────────────┘   │  docs/BIGQUERY_DATA_QNA_AGENT.md
   │  SOURCE QUERY                       ⌄   │  rung 1 — the generated SQL
   │  Ask a follow-up  ·  Pin to dashboard   │  text actions
   ╰────────────────────────────────────────╯
   ```
   `SOURCE QUERY` collapsed by default; it is the trust affordance and must
   exist. "Pin to dashboard" promotes the card below the ribbon permanently.
4. **`SUMMARY` KPI ribbon**, rung 1 on M (collapsed), rung 0 on D.
5. **Standing dashboard cards**, rung 0, one column on M, two on D (existing
   `isWide >= 920` breakpoint — align it to 900 to match the rest of the app).
   Keep `isHighlighted`: when an answer references a standing card, the card gets
   a 2 px left accent rule for 4 s. No flashing, no scale animation.

**Real states — all four are mandatory, none may be a spinner alone:**

| State | Rung 0 rendering |
|---|---|
| **Empty** (no question asked yet) | The entry field, the three starter chips, and the standing dashboard. **No hero illustration, no "Welcome to Data Viz" card.** The dashboard *is* the empty state. |
| **Loading** | The answer card appears immediately with the question echoed, a 3-line shimmer for the answer, and a 180 px skeleton block for the chart. A `labelSmall` status line cycles `Understanding question…` → `Querying BigQuery…` → `Drawing…`, driven by real agent events, not a timer. Cancel is available for the whole duration. |
| **Error** | The answer card stays, the chart slot is replaced by a `Notice(tone: error)` with the plain-language failure, a `Retry` button, and `SOURCE QUERY` **auto-expanded** (if a query was generated) so the user can see what was attempted. |
| **No rows** | Distinct from error: `Nothing matched that.` plus the narrowing that caused it (`Rain + 1990s + your library`) and one action, `Widen to all weather`. |

**Moves:** `_buildGeminiLiveQnaBanner` → **deleted** (§6). The voice affordance it
carried becomes the mic in the entry field, which routes to the same overlay.
`TelemetryInspectorPanel` → health-pip sheet only.

**Wireframe — M 390 px**

```
┌──────────────────────────────────────┐
│ ⌕  Ask about your listening data  🎙 │ 48  sticky entry field
│  [Rainy-day decade] [Top 2026] [BPM] │ 30  ≤3 suggestion chips
├──────────────────────────────────────┤
│ ╭──────────────────────────────────╮ │
│ │ answer card (newest)             │ │ var
│ ╰──────────────────────────────────╯ │
├──────────────────────────────────────┤
│ SUMMARY                           ⌄  │ 44  BgDisclosure → KPI ribbon
├──────────────────────────────────────┤
│ ╭ Pressure vs BPM ─────────────────╮ │ 240
│ ╰──────────────────────────────────╯ │
│ ╭ Weather affinity ────────────────╮ │ 240
│ ╰──────────────────────────────────╯ │
│ …                                    │
│                                      │ 96  bubble clearance
└──────────────────────────────────────┘
```

**D:** entry field centred, `maxWidth: 720`. Answer cards full width. Standing
cards 2-up. Suggestion chips move inline to the right of the field.

---

### 3.5 Settings — `frontend/lib/screens/settings_screen.dart` (860 lines)

**Purpose:** account, connections, appearance, and the truth about this build.

**Today:** `Section(ACCOUNT)` → `Section(CONNECTED SERVICES)` (two
`_PairingCard`s wrapping `_SpotifySetupBox` and `_LastfmQuickLinkBox`) →
`Section(BACKEND)` → `Section(ABOUT)` with `_AboutCard`.

**After — section order (this order exactly):**

| # | Section | Rung | Contents |
|---|---|---|---|
| 1 | `ACCOUNT` | 0 | Signed-in identity, sign out. Unchanged. |
| 2 | `APPEARANCE` | 0 | **New.** The three-option theme control (§7.4). One row, nothing else. |
| 3 | `CONNECTED SERVICES` | 0 | The two `ServiceBadge`s as a status row, then the existing `_PairingCard`s. The *setup instructions* inside `_SpotifySetupBox` / `_LastfmQuickLinkBox` move to rung 1 (`HOW TO CONNECT`) — they are long and only needed once. |
| 4 | `INSTALL` | 0 | The relocated `_PwaInstallButton`; hidden when `bridge.isStandalone`. The three-step instructions become rung 1, not a bottom sheet. |
| 5 | `BACKEND` | 1 | Collapsed. Endpoint, environment, re-check. Diagnostics, not settings. |
| 6 | `ABOUT` | 1 | Collapsed. `_AboutCard`, `_KeyValue` rows, version, and the relocated `NetdevFooter`. |

**Wireframe — M 390 px**

```
┌──────────────────────────────────────┐
│ Settings                             │ 26
├──────────────────────────────────────┤
│ ACCOUNT                              │ 20  eyebrow (not a disclosure)
│  jerome@… · Signed in       Sign out │ 56
├──────────────────────────────────────┤
│ APPEARANCE                           │ 20
│ ┌──────┬──────┬─────────┐            │ 40  SegmentedButton<BgThemeChoice>
│ │ Dark │ Light│ As host │            │
│ └──────┴──────┴─────────┘            │
├──────────────────────────────────────┤
│ CONNECTED SERVICES                   │ 20
│  [SP Spotify · Linked ]              │ 36  ServiceBadge rows
│  [FM Last.fm · Not linked   Connect] │ 36
│  HOW TO CONNECT                   ⌄  │ 44  rung 1
├──────────────────────────────────────┤
│ INSTALL                              │ 20
│  Install BAROGROOVE       [Install]  │ 44
├──────────────────────────────────────┤
│ BACKEND                           ⌄  │ 44  rung 1, collapsed
│ ABOUT                             ⌄  │ 44  rung 1, collapsed
└──────────────────────────────────────┘
```

**D:** single column, `maxWidth: 720`, left-aligned. Sections 5 and 6 expanded.

---

## 4. Breakpoints

Three, and only three. `shell.dart` already uses `wide = width >= 900` and
`isMobile = width < 600`; `dataviz_screen.dart` uses 920. **Unify on 600 / 900.**

| Name | Range | Behaviour |
|---|---|---|
| `compact` | `< 600` | Bottom `NavigationBar`. Gutter `BgSpace.md` (12). One column. Rung-1 defaults collapsed. Badges not in header. |
| `medium` | `600 – 899` | Bottom `NavigationBar`. Gutter `BgSpace.xl` (24). One column, `maxWidth: 720`. Rung-1 defaults collapsed. |
| `expanded` | `>= 900` | `NavigationRail`. Gutter `BgSpace.xl`. Two columns where specified, `maxWidth: 1080`. Rung-1 defaults **expanded**. Badges in header. |

Put these in `app_theme.dart` as `BgBreak.compact = 600`, `BgBreak.expanded = 900`
and a `BgBreak.of(context)` helper. No screen may hard-code a pixel breakpoint
again.

---

## 5. Item 8 — the Forge console, three modes

`consoleMode` already exists (`frontend/lib/providers.dart`, `ForgeSelection.
consoleMode`, default `'guided'`) and is rendered by
`frontend/lib/screens/widgets/atmospheric_cursors_console.dart` via
`_ModePillButton` ×3 and two bodies (`_buildGuidedBody`,
`_buildAdjustableBody(isExpert:)`). **This is not new work; it is a rewrite of an
existing three-way that currently reads as two-and-a-half.**

### 5.1 The affordance

Replace the three `_ModePillButton`s with a single full-width
`SegmentedButton<String>`, segments `Guided` / `Easy` / `Expert`, `showSelectedIcon:
false`, no icons, `labelLarge`. Directly beneath it, a permanent one-line
`bodySmall` helper that changes with the mode:

- Guided — *we choose everything.*
- Easy — *nudge three dials.*
- Expert — *the full instrument panel.*

Mode switching animates the body height (`AnimatedSize`, 220 ms,
`Curves.easeOutCubic`) and **must not scroll-jump**: the FORGE button is pinned
in a footer, so growth happens above it. Remove the "switch to Easy" `TextButton`
currently inside `_buildGuidedBody` — the segmented control is the affordance.

### 5.2 Exactly what each mode shows and hides

| Element | Guided | Easy | Expert |
|---|---|---|---|
| Segmented mode control + helper line | ● shown | ● shown | ● shown |
| `_OutcomeCard` — outcome headline + **one** rationale line | ● shown | ● shown | ● shown |
| `_SkyStrip` — 3 values (temp / pressure+trend / light) | ● shown | ● shown | ○ replaced by full dial |
| A2UI **SkyDial** (`sky` surface, all spokes) | ✕ hidden | rung 1 (`SKY DETAIL`, collapsed) | ● **rung 0, expanded** |
| Cursor: **Temperature °C** (`_CursorSliderCard`) | ✕ hidden | ● shown | ● shown |
| Cursor: **Light %** | ✕ hidden | ● shown | ● shown |
| Cursor: **Colour K** | ✕ hidden | ● shown | ● shown |
| Rung 1 `WHY THESE THREE` (what each cursor does) | ✕ hidden | ● present, collapsed | ● present, collapsed |
| Slider: **Pressure hPa** | ✕ | ✕ | ● shown |
| Slider: **Trend hPa/3h** | ✕ | ✕ | ● shown |
| Slider: **Target BPM** | ✕ | ✕ | ● shown |
| `_TelemetryBadge` row (model, latency, tokens) | ✕ | ✕ | ● shown |
| Rung 1 `COEFFICIENTS` — the mapping weight table | ✕ | ✕ | ● present, collapsed |
| Rung 2 `SOURCE REQUEST` — the `ForgeRequest` JSON | ✕ | ✕ | ● sheet, via a text link |
| FORGE button | ● | ● | ● |

Legend: ● visible · ✕ not rendered at all (not merely `Opacity(0)`) · ○ replaced.

This matches what `ForgeSelection.toRequest()` already does — guided nulls all
customs, expert alone sends `customPressureHpa` / `customTrendHpa` /
`customTargetBpm`. **Do not change `toRequest()`.** The UI now tells the truth
about it.

### 5.3 Guided is genuinely minimal

Guided's entire body is the outcome card. Two lines of text and nothing else.
If an implementer's Guided mode is taller than 120 px, it is wrong.

### 5.4 Expert on mobile

Expert at 390 px is long, and that is fine — it is opt-in. Three cursor cards
stack (the existing `expertSliders[0..2]` `Row` only applies above the wide
breakpoint; keep that, aligned to 900). The FORGE footer stays pinned so the
button is never more than a thumb-reach away.

---

## 6. Item 10 + 11 — one assistant overlay

### 6.1 What is deleted

- `GeminiLiveAdvisorBanner` — the instance in
  `frontend/lib/screens/home_screen.dart` (~line 188) **and** the widget in
  `frontend/lib/screens/widgets/gemini_live_advisor.dart` as a *banner*. Its
  machinery (`VoiceIo`, `AdvisorLiveResponse`, `AdvisorSuggestionItem`,
  execution state) is lifted into the overlay. The 1019-line file becomes the
  overlay's controller, not a page widget.
- `_buildGeminiLiveQnaBanner` in `frontend/lib/screens/dataviz_screen.dart`
  (~line 820, invoked ~line 735) — deleted outright, including its
  slate900→slate800 gradient.

### 6.2 Resting state

`BgAssistantBubble`, hosted in `AppShellState.build` as the **last child of a
`Stack`** that wraps the content `Row` — above `IndexedStack` and above
`_FloatingMiniPlayerBar`, but **outside** `Scaffold.bottomNavigationBar`, so it
can never overlap the tab bar.

- Shape: 56 × 56 circle, `surfaceContainerHigh` fill, 1 px `outlineVariant`, no
  shadow beyond the `shadow` token, **no glow, no pulse at rest**.
- Icon: `Icons.forum_outlined`, 22 px, `onSurface`. Not a sparkle, not a robot.
- Position, compact/medium: `right: BgSpace.lg (16)`,
  `bottom: kBottomNavigationBarHeight(80) + viewPadding.bottom + BgSpace.lg (16)`,
  **plus 64 when `_FloatingMiniPlayerBar` is visible**. Expose this as
  `BgAssistantBubble.reservedBottomInset(context)` so screens can pad correctly.
- Position, expanded (≥ 900): `right: 24`, `bottom: 24`. No tab bar to clear.
- Active states: while listening/speaking/executing, a 2 px accent ring fades in
  (200 ms). One ring. No expanding halos.

**Not covering the primary CTA.** Two mechanisms, both required:

1. Every destination's scroll view gets `padding.bottom = 96` (bubble 56 + 16 ×
   2 + 8). The Forge FORGE button sits in a **pinned footer above** the bubble's
   band, not in the scroll flow, so it is structurally un-overlappable.
2. The bubble hides on scroll-down and returns on scroll-up
   (`ScrollDirection.reverse/forward`, fade + scale to 0.8 over 120 ms). Any
   scrollable that is the primary content of a destination drives this via a
   shared `bubbleVisibilityProvider`.

### 6.3 Expanded layout

| | compact / medium | expanded |
|---|---|---|
| Container | `showModalBottomSheet`, `isScrollControlled`, top radius 16 | Anchored panel 380 × 560, bottom-right, radius 10 |
| Initial height | 60 % of viewport | fixed |
| Drag | 30 % ↔ 92 % | not draggable; resize handle out of scope |
| Scrim | `scrim` token at 8 % — the page stays legible behind it | none |
| Header row (48) | `Assistant` `titleMedium` · mic toggle · `Icons.close` | same |
| Body | Message list, newest at the bottom, auto-scroll. User turns right-aligned, no bubble fill, `bodyMedium`. Agent turns left-aligned on `surfaceContainerLow`, radius 10. Action cards (§6.4) full width. | same |
| Footer (56) | `TextField` + mic + send, 1 px top rule | same |

The overlay **never goes full-screen** and never hides the tab bar. On a 390 ×
844 screen at 60 % height it occupies 506 px and leaves the header and top of
the page visible — deliberate, because the assistant's job is to act on what you
are looking at.

### 6.4 Conversation persistence

`assistantConversationProvider` — a root-scope
`StateNotifierProvider<AssistantConversation, List<AssistantTurn>>`. Because it is
Riverpod at app scope, history survives destination changes for free; the
`IndexedStack` already keeps screens mounted, so nothing else is needed.

Each `AssistantTurn` carries `originDestination` (`BgDestination`) so the agent
knows where the user was when they asked, and so the UI can show a
`from Data Viz` eyebrow on turns raised elsewhere.

**Reconciling item 9 and item 10 — read this, both of you.** Data Viz keeps its
own question field (§3.4). It is *not* a second assistant. On submit it appends
to the **same** `assistantConversationProvider` and the answer is rendered
**twice by design**: as a turn in the overlay, and as a pinned answer card on the
Data Viz page. One brain, two entry points, one history. The Data Viz field does
not open the overlay automatically; the mic button does.

### 6.5 Item 11 — confirming writes

**Classification.** `backend/app/mcp/functions.py` declares four A2UI agent
functions — `selectTheme`, `selectGenre`, `rateTrack`, `reforge`. `forge_playlist`
is an MCP *tool* in `backend/app/mcp/server.py` / `manifest.py`, a different
dispatch path. The gate must cover both.

| Function | Path | Gate |
|---|---|---|
| `selectTheme` | A2UI agent function | **Immediate.** No confirmation. It is a selection; it is reversible by selecting again. |
| `selectGenre` | A2UI agent function | **Immediate.** Same. |
| any read / browse / look-up tool | MCP tool | **Immediate.** |
| `rateTrack` | A2UI agent function | **Confirm.** It writes taste state that feeds future forges. |
| `reforge` | A2UI agent function | **Confirm.** It replaces the current set. |
| `forge_playlist` | MCP tool | **Confirm.** It creates an almanac entry and may push to a sink. |

**Do not hard-code that list in Dart.** Add a boolean to the per-function
extension block the catalog already carries —
`CATALOG["functions"][name]["metadata"]["extensions"]["barogroove"]["writes"]` —
in `backend/app/a2ui/catalog.py`, regenerate `frontend/a2ui/catalog.json`, and
have the renderer gate on it. **That is a Python change**, and it means a new
write-capable function is safe by construction. Mirror the same flag on the MCP
tool specs in `backend/app/mcp/manifest.py`.

**The confirmation UI is an inline action card in the conversation, not a
dialog.** A dialog steals focus and destroys a voice flow mid-sentence.

```
╭──────────────────────────────────────────╮
│ CONFIRM ACTION                           │  labelSmall, onSurfaceVariant
│ Forge a new playlist                     │  titleMedium
│ ────────────────────────────────────────  │  1px rule
│ Location     Brussels, BE             ›  │  tap → rung-2 sheet to edit
│ Theme        Petrichor                ›  │
│ Corridor     Ambient → Downtempo      ›  │
│ Seeds        3 tracks                 ›  │
│ ────────────────────────────────────────  │
│ This replaces your current set,          │  bodySmall, only for reforge
│ “Petrichor Drift”.                       │
│                                          │
│                   Cancel      [Confirm]  │  TextButton   FilledButton
╰──────────────────────────────────────────╯
```

Binding rules:

- Every parameter the agent inferred is **visible and editable** before confirm.
  A confirmation that hides its arguments is not a confirmation.
- `Confirm` is **not** autofocused. Enter does not submit. There is no
  keyboard shortcut.
- Voice requires an explicit affirmative — `confirm`, `yes do it`, `go ahead`. A
  bare `ok` or `sure` does **not** pass; re-prompt once, then fall back to touch.
- A destructive-adjacent action names what it replaces, in plain language, in the
  card (as shown for `reforge`).
- No "always allow", no "remember this choice", no batching of multiple writes
  into one confirmation. One write, one card.
- **After confirm** the card collapses in place to a one-line receipt:
  `✓ Forged “Petrichor Drift” · 14 tracks · 19:04  ·  View`. For `rateTrack` the
  receipt carries `Undo` for 10 s. `View` navigates via
  `AppShell.of(context)?.go(...)` and leaves the overlay open.
- **On cancel** the card collapses to `✕ Cancelled.` and stays in history. The
  agent is told, so it does not immediately re-propose.
- While a confirmation card is pending, the agent may not issue another write
  proposal. One at a time.

---

## 7. Items 12 / 13 / 14 — tokens

Everything below lands in `frontend/lib/app_theme.dart` (currently 335 lines).
No screen may declare a colour, a font size, a padding or a radius literal again.

### 7.1 Type scale

Current `TextTheme` is close. Four corrections, then freeze it.

| Role (alias) | Slot | Size | Weight | Tracking | Height | Change |
|---|---|---|---|---|---|---|
| `BgText.hero` | `displaySmall` | 34 | w600 | −0.8 | 1.15 | **Sign-in screen only.** Banned on the five destinations. |
| `BgText.screenTitle` | `headlineMedium` | **24** | w600 | −0.5 | 1.2 | was 26 → 24 |
| `BgText.sectionTitle` | `headlineSmall` | 20 | w600 | −0.3 | 1.25 | was 21 → 20 (whole numbers only) |
| `BgText.cardTitle` | `titleLarge` | 18 | w600 | −0.2 | 1.3 | unchanged |
| `BgText.rowTitle` | `titleMedium` | 15 | w600 | 0 | 1.35 | unchanged |
| `BgText.rowSubtitle` | `titleSmall` | 13 | w600 | 0 | 1.35 | unchanged |
| `BgText.bodyLead` | `bodyLarge` | 16 | w400 | 0 | 1.55 | rationale prose only |
| `BgText.body` | `bodyMedium` | **14** | w400 | 0 | 1.55 | was 14.5 → 14 |
| `BgText.caption` | `bodySmall` | 13 | w400 | 0 | 1.5 | unchanged |
| `BgText.action` | `labelLarge` | 14 | w600 | +0.1 | 1.2 | unchanged |
| `BgText.meta` | `labelMedium` | **12** | w500 | +0.2 | 1.3 | **new** — badges, chips, receipts |
| `BgText.eyebrow` | `labelSmall` | 11 | w600 | +0.9 | 1.2 | UPPERCASE by convention |

Hard rules: **no product text above 24 on any of the five destinations.** No
fractional sizes. Exactly two weights in product chrome — w400 and w600; w500 is
reserved for `meta`; w700 is **banned** (`shell.dart` and `almanac_screen.dart`
use `w700` in several places — replace with w600).

Numerals in KPIs, telemetry and charts use
`fontFeatures: [FontFeature.tabularFigures()]` via a `BgText.numeric` alias so
values stop shifting as they update.

### 7.2 Spacing & radius

Keep `BgSpace` (4 / 8 / 12 / 16 / 24 / 32, radius 10 / 6). Add two, then freeze.

```dart
static const double xxs = 2;    // icon-to-label only
static const double xxxl = 48;  // destination bottom padding, empty-state breathing
static const double bubbleClearance = 96;  // §6.2
static const double radiusSheet = 16;      // the ONLY value above 10; sheets only
```

Applied consistently:

| Where | Value |
|---|---|
| Screen gutter | `md` (12) compact · `xl` (24) medium & expanded |
| Between sections | `xl` (24) compact · `xxl` (32) expanded |
| Card padding | `lg` (16) |
| Between rows in a list | `sm` (8) |
| Icon → label | `xs` (4) … `sm` (8) |
| Scroll-view bottom padding | `bubbleClearance` (96) |
| Card / control radius | `BgSpace.br` (10) / `BgSpace.brSm` (6) |
| Sheet top radius | `radiusSheet` (16) |

`app_theme.dart` says *"nothing rounder than 10"* and `shell.dart` then uses
`circular(20)` (PWA pill, health pip ink-well, telemetry button), `circular(16)`,
`circular(14)`. **Fix all of them.** The only survivors above 10 are sheet tops
and the assistant bubble, which is a true circle.

### 7.3 Colour roles

Name the roles; stop reaching into `BgPalette` from screens.

| Role | Light | Dark | Use |
|---|---|---|---|
| `surfaceBase` | `slate50` | `slate900` | Page background |
| `surfaceRaised` | `white` | `slate800` | Cards, sheets, the bubble |
| `surfaceSunken` | `slate100` | `#0B1220` | Input fields, skeletons, chart plot areas |
| `hairline` | `slate200` | `slate700` | **1 px separators and card borders. The primary structuring device.** |
| `inkPrimary` | `slate900` | `slate100` | Headings, values |
| `inkSecondary` | `slate600` | `slate400` | Body, labels |
| `inkTertiary` | `slate400` | `slate500` | Disabled, unlinked, placeholders |
| `accent` | `sky600` | `sky500` | Interaction only — filled buttons, selected segment, focus ring, the one highlight rule |
| `onAccent` | `white` | `slate900` | Text on accent |
| `accentWash` | `sky50` | `sky700 @ 14 %` | The faintest possible selected-row tint. One per screen. |
| `markGold` | `gold600` | `gold500` | Rationed: confidence mark, hero rationale rule, peak track. **Never more than one gold element per viewport.** |
| `statusOk` | `ok` | `ok` | Only in the health sheet, never as a header dot |
| `statusWarn` | `warn` | `warn` | Degraded |
| `statusDanger` | `danger` | `danger` | Unreachable, failed forge |
| `connected` | `inkPrimary` | `inkPrimary` | Linked badge (monochrome — *not* green) |
| `disconnected` | `inkTertiary` | `inkTertiary` | Unlinked badge |

**De-neoning the dark theme (item 13) — concrete removals:**

1. **No gradients anywhere.** Kill the `LinearGradient(slate900 → slate800)` in
   `dataviz_screen.dart` `_buildGeminiLiveQnaBanner` (deleted anyway) and any
   other. Flat fills only.
2. **No coloured glows / alpha-primary fills as decoration.** `shell.dart` uses
   `colors.primary.withValues(alpha: 0.14 / 0.08 / 0.22)` as button and toggle
   backgrounds. Replace with `surfaceRaised` + a `hairline` border.
3. **Accent budget: one accent-filled element per viewport**, which is the
   primary CTA. Selection is shown with a 2 px accent *rule* or `accentWash`, not
   a filled block. The Almanac mode bar currently fills the active segment with
   `colors.primary` — `SegmentedButton`'s default `accentWash` + accent label is
   correct instead.
4. **Dark mode raises surfaces with `hairline`, not elevation.** Shadows in dark
   are `Colors.transparent`; separation comes from the 1 px border.
5. Charts in dark: plot area `surfaceSunken`, gridlines `hairline`, series in a
   **monochrome ramp** (`slate300 → slate500 → slate700`) with the *single*
   highlighted series in `accent`. No rainbow categoricals. This applies to
   `_CohortDonutPainter` and `_QnAChartPainter` alike.

### 7.4 The theme control (item 14)

```dart
enum BgThemeChoice { dark, light, host }   // host -> ThemeMode.system
```

- **Default is `host`.** `frontend/lib/providers.dart` line ~23 currently reads
  `StateProvider<ThemeMode>((Ref ref) => ThemeMode.dark)` — change it to
  `ThemeMode.system`, and persist the user's explicit choice under
  `bg.theme.choice`. First run must follow the OS.
- **Light must feel native, not like dark-mode-inverted.** Audit every
  `withValues(alpha:)` on a dark palette colour; in light they read as grey mud.
- **Where it lives:** Settings → `APPEARANCE`, section 2, as a
  `SegmentedButton<BgThemeChoice>`, full width on compact, 320 px on expanded.
  Labels `Dark` / `Light` / `As host`, icons `Icons.dark_mode_outlined`,
  `Icons.light_mode_outlined`, `Icons.contrast`, all 18 px, `showSelectedIcon:
  false`.
- **Secondary access:** account menu → a row `Appearance · As host ›` that
  navigates to Settings (compact) or expands inline (expanded). This is the only
  other place it appears.
- **Removed from:** the `AppBar` and the `NavigationRail.trailing`. Delete
  `_ThemeModeSwitchButton` and both of its call sites.

### 7.5 Connection badges (item 14)

`ServiceBadge({required BgService service, required bool linked})`,
`BgService { spotify, lastfm }`.

- 24 px tall pill, `brSm` (6), 1 px border, transparent fill.
- **Monochrome, always.** No Spotify green, no Last.fm red. Linked: border
  `hairline`, text/monogram `connected` (= `inkPrimary`), plus a 4 px
  `statusOk` dot — the *only* colour, and only when linked. Unlinked: border
  `hairline @ 50 %`, text `disconnected`, no dot.
- Content: desktop header → 2-letter monogram `SP` / `FM` at `BgText.meta`, with
  a `Tooltip` giving `Spotify · Linked as jerome`. Settings → full name + status
  word + action (`Connect` / `Disconnect`).
- **No brand logos.** None ship with Material and we are not adding an asset or a
  dependency.

| Viewport | Where the badges live |
|---|---|
| compact `< 600` | **Not in the header.** Settings → `CONNECTED SERVICES` (rung 0) and the account bottom sheet. |
| medium `600–899` | Same as compact. The header budget is still wordmark + status + avatar. |
| expanded `>= 900` | Header, between the wordmark and the health pip, `sm` (8) apart. Also in Settings. |

Tapping a badge anywhere navigates to Settings → `CONNECTED SERVICES` and
expands the relevant `_PairingCard`. It never opens an OAuth flow directly from
the header.

### 7.6 Icon rules

Monochrome, outlined at rest, filled when selected, 20 px in chrome / 18 px
inline / 24 px in the tab bar. Colour is `inkSecondary` unless the element is
selected (`accent`) or destructive (`statusDanger`). No icon is ever the sole
carrier of meaning in the header — every header icon has a tooltip, and the
badges carry text.

---

## 8. What we deliberately did **not** change, and why

- **The Almanac / Data Viz split.** Fixed constraint, and correct: Almanac is an
  archive you browse, Data Viz is a question you ask. Cohort Matcher stays on
  Almanac because it *selects rows from the archive* and seeds the Forge; it is
  not an analytics answer.
- **Five destinations, five labels.** `Forge`, `Set`, `Almanac`, `Data Viz`,
  `Settings` stay exactly as written. Renaming costs six implementers a merge
  conflict and buys nothing; the icons were the actual problem.
- **`IndexedStack` keeping all five screens mounted.** It costs memory and buys
  0 ms tab switches, preserved scroll position, and uninterrupted audio. Keep it
  — and it is what makes the assistant's cross-destination history free.
- **A2UI as the source of UI truth.** Nothing here proposes hand-building a
  surface in Dart. Where content or ordering changes, the change is in
  `backend/app/a2ui/surfaces.py`.
- **`_FloatingMiniPlayerBar`.** It survives. It is the only thing tying the other
  four destinations back to the set you just made.
- **Pull-to-refresh (`RefreshIndicator`) on Forge.** Mobile-native, discoverable,
  costs no chrome.
- **The health pip's honesty.** We demote it to silence-when-healthy; we do not
  remove it. A degraded backend must still be visible without opening a menu.
- **`ForgeSelection.toRequest()`.** Its guided/easy/expert null-masking is
  already correct. Item 8 changes the UI to match it, not the other way round.
- **No new dependencies.** Everything specified here is Material 3 +
  `flutter_riverpod`, both already present. There is no network in this
  environment and none is needed.

---

## 9. Things in the code that contradict the brief (implementers: read)

1. **`themeModeProvider` defaults to `ThemeMode.dark`** (`frontend/lib/providers.dart`
   ~line 23) while `app_theme.dart`'s own doc comment says *"light mode by
   default"* and the brief says "As host" becomes the default. Three sources, three
   answers. **Resolution: default `ThemeMode.system`** (§7.4). Item 14 owns the fix.
2. **`forge_playlist` is not an A2UI agent function.** `backend/app/mcp/functions.py`
   registers exactly four — `selectTheme`, `selectGenre`, `rateTrack`, `reforge`
   (camelCase). `forge_playlist` is an MCP *tool* (`backend/app/mcp/server.py`
   ~line 793, `manifest.py` ~line 464). The item-11 write gate therefore spans two
   dispatch paths and needs the `writes` flag mirrored in both the catalog and the
   tool manifest (§6.5).
3. **`_ThemeModeSwitchButton` is instantiated twice** — `AppBar.actions` and
   `NavigationRail.trailing`. Removing only the first leaves a ghost toggle on
   desktop.
4. **The Telemetry Inspector has three entry points** — the AppBar button, the
   health-pip dialog action, and Data Viz segment 1. Spec keeps one.
5. **Data Viz segment 1 is "Live AI Telemetry & Trace Inspector"**, which is ops
   tooling sitting inside the surface the brief defines as *dynamic A2UI
   analytics*. Removed here; if someone wants it back it belongs in Settings →
   `BACKEND`, not Data Viz.
6. **Radius discipline is already broken.** `app_theme.dart` says nothing rounder
   than 10; `shell.dart` ships `circular(20)`, `circular(16)`, `circular(14)`.
7. **The Almanac KPI strip fabricates data**: `_buildKpiStrip` does
   `stats.totalScrobbles > 0 ? stats.totalScrobbles : 160717`. A hardcoded
   fallback shown when the real value is missing is a lie in an executive
   dashboard. Replace with a real empty state (`—` plus `No scrobbles synced`).
   Not strictly IA, but it is on the critical path of "calm and serious".
8. **Breakpoints disagree**: 900 in `shell.dart`, 920 in `dataviz_screen.dart`,
   600 for `isMobile`. Unified in §4.

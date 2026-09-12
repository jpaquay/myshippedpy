# Playlist & Song Cohort Analysis Cross-Check Engine

The **Playlist Cohort Analysis Engine** (`POST /api/almanac/playlist-cohort-check`) cross-examines any pasted playlist, tracklist, or song link against the user's **15-year `160,717`-scrobble BigQuery/Catalog cohort**, quantifying familiarity, uncovering hidden history, and rendering visual Donut & Timeline charts.

---

## 1. Universal Playlist & Song Input Parser

The engine accepts multi-format input strings via `playlist_input` and automatically extracts canonical `(artist, track)` pairs:

1. **Spotify Playlist & Track URLs / URIs**:
   - e.g., `https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M` or `spotify:track:...`
   - Automatically resolves curated atmospheric/genre showcase presets or metadata.
2. **Last.fm Track & Album URLs**:
   - e.g., `https://www.last.fm/music/Radiohead/_/Weird+Fishes%2FArpeggi`
   - URL-decodes artist and track slugs directly from the path structure.
3. **M3U / Extended M3U Playlists**:
   - Parses `#EXTINF:duration,Artist - Title` directives and strips file paths.
4. **Plaintext Tracklists**:
   - Supports `Artist - Track`, `Artist — Track`, `Artist : Track`, or numbered lines (`01. Boards of Canada - Roygbiv`).
5. **Artist-Only or Single-Song Lookup**:
   - If only an artist or single song title is provided, matches against the user's top tracks by that artist in the `track_catalog.jsonl` index.

---

## 2. Four-Tier Scrobble Cohort Classification

Every track resolved from the input is cross-checked against the `160,717`-scrobble warehouse and classified into one of four **Familiarity Cohorts**:

| Cohort Tier | Play Count Threshold | UI Color | Sonic Meaning & Interpretation |
| :--- | :--- | :--- | :--- |
| **Obsession** | `50+` scrobbles | `#10B981` (Emerald) | Core personal canon — tracks deeply etched into multi-year listening memory. |
| **Heavy Rotation** | `10–49` scrobbles | `#0EA5E9` (Cyan) | Trusted favorites — familiar tracks that anchor seasonal or thematic moods. |
| **Discovery** | `1–9` scrobbles | `#F59E0B` (Amber) | Acquaintances — tracks heard briefly in the past, ripe for re-discovery. |
| **Unheard (Fresh)** | `0` scrobbles | `#A855F7` (Purple) | Brand-new territory — tracks never scrobbled in 15 years of history. |

### Artist Affinity Bonus
Even if a specific track is **Unheard (`0` plays)**, the engine checks whether the **Artist** has historical plays in the user's almanac (`artist_total_plays`). A track with `0` plays by an artist with `1,200` plays is flagged as a **"Deep-Cut Discovery from a Beloved Artist"**, boosting the overall **Cohort Affinity Score (`0–100%`)**.

---

## 3. API Specification (`POST /api/almanac/playlist-cohort-check`)

### Request Payload
```json
{
  "playlist_input": "Radiohead - Weird Fishes/Arpeggi\nBoards of Canada - Roygbiv\nAphex Twin - Xtal\nBurial - Archangel\nBicep - Glue\nUnknown Mortal Orchestra - So Good At Being in Trouble"
}
```

### Response Structure
```json
{
  "status": "ok",
  "playlist_title": "Custom Pasted Tracklist (6 tracks)",
  "total_tracks": 6,
  "matched_tracks_count": 5,
  "unheard_tracks_count": 1,
  "cohort_affinity_score": 84.2,
  "total_historical_plays": 412,
  "pie_chart_cohorts": [
    {"cohort": "Obsession (50+ plays)", "count": 2, "percentage": 33.3, "color": "#10B981"},
    {"cohort": "Heavy Rotation (10-49)", "count": 2, "percentage": 33.3, "color": "#0EA5E9"},
    {"cohort": "Discovery (1-9 plays)", "count": 1, "percentage": 16.7, "color": "#F59E0B"},
    {"cohort": "Unheard (0 plays)", "count": 1, "percentage": 16.7, "color": "#A855F7"}
  ],
  "yearly_timeline_overlap": [
    {"year": 2012, "plays": 18},
    {"year": 2016, "plays": 64},
    {"year": 2021, "plays": 95},
    {"year": 2025, "plays": 42}
  ],
  "tracks": [
    {
      "artist": "Radiohead",
      "track": "Weird Fishes/Arpeggi",
      "play_count": 142,
      "artist_total_plays": 3840,
      "cohort": "Obsession (50+ plays)",
      "first_played_year": 2012,
      "last_played_year": 2026
    }
  ],
  "sonic_recommendation": "High-Resonance Core Anchor (84.2% Affinity): 66.6% of this playlist sits in your Obsession & Heavy Rotation tiers, led by Radiohead and Boards of Canada."
}
```

---

## 4. Visual Rendering in Flutter (`almanac_screen.dart`)

The **PLAYLIST COHORT ANALYSIS** tab (`Tab 3` in the Almanac UI) renders:
1. **Interactive Preset Chips**: One-click test buttons for *Atmospheric Krautrock & IDM*, *Late Night Rain & Slowcore*, *90s Shoegaze & Dream Pop*, and *Spotify URL Simulation*.
2. **`_CohortDonutChartPainter`**: Custom-painted canvas Donut Chart showing proportional slices for `Obsession`, `Heavy Rotation`, `Discovery`, and `Unheard`, complete with center KPI percentage badge and legend.
3. **`_CohortBarGraphPainter`**: 15-Year Timeline Bar Graph (`2012–2026`) illustrating exactly *when* in the user's life the pasted playlist's songs were most heavily played.
4. **Track-by-Track Breakdown Table**: Displays individual track play counts, artist total plays, historical active years (`first_played_year` – `last_played_year`), and color-coded cohort badges.

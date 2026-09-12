"""Tests for the BAROGROOVE playlist sinks.

NO NETWORK. Every Spotify interaction is either short-circuited before transport
(unconfigured / unpaired) or served by a fake ``_search`` override. If any test
in this file ever opens a socket, that is the bug.

Async tests are driven with ``asyncio.run`` through the ``run()`` helper rather
than pytest-asyncio, so the suite has no plugin dependency.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Sequence, TypeVar

import pytest

# The sinks live under backend/app/...; make that importable as the `app`
# namespace package regardless of where pytest was invoked from.
_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.contracts import (  # noqa: E402
    Coordinates,
    Playlist,
    PlaylistSink,
    Rationale,
    ScoredTrack,
    SinkResult,
    SkyVector,
    SonicVector,
    Track,
)
from app.sinks import m3u as m3u_mod  # noqa: E402
from app.sinks import resolver as resolver_mod  # noqa: E402
from app.sinks.m3u import M3USink, build_export, render_csv, render_json, render_m3u  # noqa: E402
from app.sinks.registry import NoopSink, choose_sink, write_playlist  # noqa: E402
from app.sinks.resolver import (  # noqa: E402
    DEFAULT_THRESHOLD,
    MatchCandidate,
    SpotifyResolver,
    normalise_artist,
    normalise_text,
    normalise_title,
    score_candidate,
)
from app.sinks.spotify import (  # noqa: E402
    DEAD_ENDPOINTS,
    DESCRIPTION_LIMIT,
    SpotifySink,
    compress_description,
)
from app.sinks.spotify_auth import (  # noqa: E402
    SPOTIFY_SCOPES,
    InMemoryTokenVault,
    PkcePair,
    SpotifyAuth,
    SpotifyTokens,
    TokenVault,
    code_challenge_for,
    generate_code_verifier,
    generate_state,
)

T = TypeVar("T")


# --- integration backfill --------------------------------------------------
# `sky` and `sonic_target` are required by the frozen Playlist contract. The
# sink layer ignores them, but a playlist without a sky is not a BAROGROOVE
# playlist, so the fixtures carry a real one rather than the contract carrying
# a default.
_SKY = SkyVector(
    pressure_trend_6h=-0.62,
    pressure_norm_deviation=-0.41,
    cloud_depth=0.88,
    precip_intensity=0.34,
    notes=["pressure fell 3.2 hPa in 6h", "near-total cloud"],
)
_TARGET = SonicVector.from_bpm(96.0, energy=0.38, valence=0.42, density=0.55)


def run(coro: Awaitable[T]) -> T:
    return asyncio.run(coro)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #


def make_track(
    artist: str,
    title: str,
    *,
    duration_ms: int | None = 210_000,
    tags: Sequence[str] = (),
    spotify_uri: str | None = None,
) -> Track:
    return Track(
        title=title,
        artist=artist,
        duration_ms=duration_ms,
        tags=list(tags),
        spotify_uri=spotify_uri,
        lastfm_url=f"https://www.last.fm/music/{artist.replace(' ', '+')}",
    )


def make_scored(track: Track, position: int, role: str = "build") -> ScoredTrack:
    return ScoredTrack(
        track=track,
        score=0.8 - position * 0.01,
        sonic_distance=0.2,
        taste_affinity=0.6,
        corridor_fit=0.7,
        novelty=0.4,
        role=role,  # type: ignore[arg-type]
        position=position,
        why=f"Sits {position} steps into the build; matches the falling pressure.",
    )


@pytest.fixture()
def playlist() -> Playlist:
    tracks = [
        make_track("Björk", "Jóga - Remastered 2011", tags=["ethereal", "art pop"]),
        make_track("Boards of Canada", "Roygbiv", duration_ms=151_000, tags=["idm"]),
        make_track("Sufjan Stevens", "Chicago (feat. My Brightest Diamond)", duration_ms=None),
        make_track("Sigur Rós", "Hoppípolla", duration_ms=268_000, tags=["post-rock"]),
    ]
    return Playlist(
        id="pl_test_0001",
        title="Falling Pressure, Rising Warmth",
        subtitle="Brussels, a grey Tuesday that means it",
        tracks=[make_scored(t, i) for i, t in enumerate(tracks)],
        # The real SkyVector is NORMALISED and derivative-first. The raw
        # meteorology (998.4 hPa, -3.2 hPa/6h, 9.5 C, 88% cloud, 1.4 mm) lives in
        # `notes`, which is where the rationale card reads it from.
        sky=SkyVector(
            pressure_trend_6h=-0.62,
            pressure_norm_deviation=-0.41,
            temp_norm_deviation=-0.12,
            cloud_depth=0.88,
            precip_intensity=0.34,
            notes=[
                "pressure fell 3.2 hPa in 6h",
                "near-total cloud, overcast",
                "1.4 mm/h, steady",
            ],
        ),
        # tempo is NORMALISED across [60, 180] BPM, not raw BPM: 96 BPM -> 0.30.
        sonic_target=SonicVector.from_bpm(96.0, energy=0.38, valence=0.42, density=0.55),
        theme_id="low-pressure-drift",
        genre_id="ambient-post-rock",
        rationale=Rationale(
            headline="The barometer is falling and the music should know it.",
            body=(
                "Pressure is down three hectopascals in six hours under near-total "
                "cloud. That reads as weight, not gloom, so the corridor leans warm "
                "and slow rather than dark."
            ),
            sky_reading=[
                "998 hPa and dropping — a front is arriving, not passing.",
                "88% cloud with light precipitation: diffuse, shadowless light.",
            ],
            sonic_moves=[
                "Tempo pulled to 96 BPM to sit under the wind.",
                "Warmth raised to 0.70 to keep the low pressure from reading as cold.",
            ],
            taste_note="Weighted toward your Last.fm affinity for post-rock and IDM.",
            confidence=0.78,
            degraded=[],
        ),
        created_at=datetime(2026, 9, 10, 5, 0, tzinfo=timezone.utc),
        user_id="user_abc",
        coordinates=Coordinates(latitude=50.8503, longitude=4.3517, label="Brussels"),
    )


class FakeSettings:
    """Minimal stand-in for ``config.Settings``."""

    def __init__(self, *, client_id: str | None = "test-client-id") -> None:
        self.spotify_client_id = client_id
        self.spotify_client_secret = None
        self.spotify_redirect_uri = "https://bg.netdev.be/api/pair/spotify/callback"
        self.spotify_api_base = "https://api.spotify.com/v1"
        self.spotify_accounts_base = "https://accounts.spotify.com"
        self.public_host = "bg.netdev.be"

    @property
    def has_spotify(self) -> bool:
        return bool(self.spotify_client_id)


def make_spotify_sink(*, client_id: str | None = "test-client-id", vault: TokenVault | None = None) -> SpotifySink:
    settings = FakeSettings(client_id=client_id)
    return SpotifySink(settings=settings, vault=vault or InMemoryTokenVault())


# --------------------------------------------------------------------------- #
# protocol conformance
# --------------------------------------------------------------------------- #


def test_both_sinks_satisfy_the_playlist_sink_protocol() -> None:
    assert isinstance(M3USink(), PlaylistSink)
    assert isinstance(make_spotify_sink(), PlaylistSink)
    assert isinstance(NoopSink(), PlaylistSink)


def test_sink_kinds_are_the_declared_literals() -> None:
    assert M3USink().kind == "m3u"
    assert make_spotify_sink().kind == "spotify"
    assert NoopSink().kind == "none"


# --------------------------------------------------------------------------- #
# M3U
# --------------------------------------------------------------------------- #


def parse_m3u(body: str) -> tuple[list[str], list[tuple[int, str]]]:
    """Return (comment lines, [(duration_s, label)]) and assert basic sanity."""
    lines = body.splitlines()
    assert lines and lines[0] == "#EXTM3U", "an extended M3U must open with #EXTM3U"

    comments: list[str] = []
    entries: list[tuple[int, str]] = []
    expecting_resource = False

    for line in lines:
        if expecting_resource:
            assert not line.startswith("#EXTINF"), "two #EXTINF lines with no resource between them"
            if not line.startswith("#"):
                expecting_resource = False
                continue
        if line.startswith("#EXTINF:"):
            payload = line[len("#EXTINF:") :]
            duration_text, _, label = payload.partition(",")
            # Duration may carry optional attributes before the comma in some
            # dialects; ours does not, so this must parse cleanly.
            entries.append((int(duration_text.strip()), label))
            expecting_resource = True
        elif line.startswith("#"):
            comments.append(line)

    assert not expecting_resource, "trailing #EXTINF with no resource line"
    return comments, entries


def test_m3u_is_valid_and_has_one_extinf_per_track(playlist: Playlist) -> None:
    result = run(M3USink().write(playlist))
    assert result.ok is True
    assert result.kind == "m3u"
    assert result.payload is not None

    comments, entries = parse_m3u(result.payload)
    assert len(entries) == len(playlist.tracks) == 4
    assert result.matched == result.requested == 4
    assert result.unmatched == []


def test_m3u_extinf_durations_are_seconds_and_unknown_is_minus_one(playlist: Playlist) -> None:
    _, entries = parse_m3u(render_m3u(playlist))
    durations = [d for d, _ in entries]
    assert durations[0] == 210  # 210_000 ms -> 210 s, not 210000
    assert durations[1] == 151
    assert durations[2] == -1  # duration_ms was None
    assert durations[3] == 268


def test_m3u_labels_use_plain_hyphen_not_em_dash(playlist: Playlist) -> None:
    _, entries = parse_m3u(render_m3u(playlist))
    labels = [label for _, label in entries]
    assert "Björk - Jóga - Remastered 2011" in labels
    # Track.display uses an em dash; #EXTINF convention does not.
    assert not any("—" in label for label in labels)


def test_m3u_carries_the_rationale_theme_genre_sky_and_sonic_target(playlist: Playlist) -> None:
    body = render_m3u(playlist)

    # Rationale prose. Wrapping breaks lines, so assert on distinctive fragments.
    assert "barometer is falling" in body
    assert "998 hPa and dropping" in body
    assert "Tempo pulled to 96 BPM" in body
    assert "Weighted toward your Last.fm affinity" in body

    # Corridor.
    assert "low-pressure-drift" in body
    assert "ambient-post-rock" in body

    # Sky vector and sonic target, rendered as key=value summaries.
    # The real SkyVector is normalised and derivative-first; the M3U header
    # reflects the contract's own field names.
    assert "pressure_trend_6h" in body
    assert "overcast" in body  # carried in the sky notes
    assert "tempo=0.30" in body  # 96 BPM normalised across [60, 180]
    assert "valence=0.42" in body

    # Provenance + title directive.
    assert "#PLAYLIST:Falling Pressure, Rising Warmth" in body
    assert "pl_test_0001" in body
    assert "Brussels" in body


def test_m3u_never_lets_a_newline_escape_into_a_comment() -> None:
    """A newline inside a comment would terminate it and the remainder would be
    read as a resource path — a real corruption vector, since rationale body
    text is generated prose."""
    nasty = Playlist(sky=_SKY, sonic_target=_TARGET, theme_id="petrichor", 
        id="pl_nasty",
        title="Line\nBreak",
        subtitle="",
        tracks=[make_scored(make_track("A", "B"), 0)],
        rationale=Rationale(
            headline="head\nline",
            body="body\r\nwith\nbreaks",
            sky_reading=["sky\nreading"],
            sonic_moves=["sonic\tmove"],
            taste_note="taste\nnote",
            confidence=0.5,
        ),
    )
    body = render_m3u(nasty)
    comments, entries = parse_m3u(body)
    assert len(entries) == 1
    # Every comment line is a single line by construction.
    assert all("\n" not in c and "\r" not in c for c in comments)


def test_m3u_resource_line_prefers_spotify_uri_then_lastfm_then_filename() -> None:
    pl = Playlist(sky=_SKY, sonic_target=_TARGET, theme_id="petrichor", 
        id="pl_res",
        title="Resources",
        tracks=[
            make_scored(make_track("A", "One", spotify_uri="spotify:track:abc123"), 0),
            make_scored(Track(title="Two", artist="B", lastfm_url="https://last.fm/x"), 1),
            make_scored(Track(title="Th/ree", artist="C"), 2),
        ],
        rationale=Rationale(headline="h", body="b"),
    )
    lines = render_m3u(pl).splitlines()
    resources = [
        lines[i + 1] for i, line in enumerate(lines) if line.startswith("#EXTINF:")
    ]
    assert resources[0] == "spotify:track:abc123"
    assert resources[1] == "https://last.fm/x"
    assert resources[2] == "C - Th_ree.mp3"  # slash sanitised out of the filename


def test_m3u_degraded_subsystems_are_surfaced() -> None:
    pl = Playlist(sky=_SKY, sonic_target=_TARGET, theme_id="petrichor", 
        id="pl_deg",
        title="Degraded",
        tracks=[make_scored(make_track("A", "B"), 0)],
        rationale=Rationale(
            headline="h", body="b", degraded=["lastfm: tag lexicon unavailable"]
        ),
    )
    body = render_m3u(pl)
    assert "DEGRADED SUBSYSTEMS" in body
    assert "tag lexicon unavailable" in body


def test_m3u_sink_never_raises_on_an_empty_playlist() -> None:
    empty = Playlist(sky=_SKY, sonic_target=_TARGET, theme_id="petrichor", id="pl_empty", title="Nothing", tracks=[], rationale=Rationale(headline="h", body="b"))
    result = run(M3USink().write(empty))
    assert result.ok is True
    assert result.requested == 0
    _, entries = parse_m3u(result.payload or "")
    assert entries == []


def test_m3u_sink_is_always_available() -> None:
    assert run(M3USink().available(None)) is True
    assert run(M3USink().available("anyone")) is True


# --------------------------------------------------------------------------- #
# JSON / CSV export
# --------------------------------------------------------------------------- #


def test_json_export_is_valid_and_complete(playlist: Playlist) -> None:
    import json

    doc = json.loads(render_json(playlist))
    assert doc["format"] == "barogroove.playlist.v1"
    assert doc["track_count"] == 4
    assert len(doc["tracks"]) == 4
    assert doc["rationale"]["headline"].startswith("The barometer")
    assert doc["sky"]["pressure_trend_6h"] == _SKY.pressure_trend_6h
    assert doc["coordinates"]["label"] == "Brussels"
    assert doc["tracks"][0]["artist"] == "Björk"


def test_csv_export_has_a_header_and_one_row_per_track(playlist: Playlist) -> None:
    import csv
    import io

    rows = list(csv.reader(io.StringIO(render_csv(playlist))))
    assert rows[0][0] == "position"
    assert len([r for r in rows if r]) == 5  # header + 4


def test_export_bundle_filenames_are_filesystem_safe(playlist: Playlist) -> None:
    bundle = build_export(playlist)
    assert bundle.m3u_filename.endswith(".m3u8")
    assert re.fullmatch(r"[a-z0-9-]+", bundle.filename_stem)
    assert bundle.track_count == 4
    assert bundle.json_payload and bundle.csv_payload and bundle.m3u


# --------------------------------------------------------------------------- #
# resolver: normalisation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Jóga - Remastered 2011", "Jóga"),
        ("Karma Police - Remastered", "Karma Police"),
        ("Paranoid Android - 2011 Remaster", "Paranoid Android"),
        ("Roygbiv (Remastered 2004)", "Roygbiv"),
        ("Everlong [2011 Remaster]", "Everlong"),
        ("Space Oddity - Mono Version", "Space Oddity"),
        ("Heroes - Single Version", "Heroes"),
        ("Bohemian Rhapsody - Radio Edit", "Bohemian Rhapsody"),
    ],
)
def test_normalise_title_strips_remaster_and_edition_noise(raw: str, expected: str) -> None:
    assert normalise_title(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Chicago (feat. My Brightest Diamond)", "Chicago"),
        ("Chicago [featuring Someone]", "Chicago"),
        ("No Church in the Wild feat. Frank Ocean", "No Church in the Wild"),
        ("Runaway ft. Pusha T", "Runaway"),
    ],
)
def test_normalise_title_strips_featured_credits(raw: str, expected: str) -> None:
    assert normalise_title(raw) == expected


def test_normalise_title_peels_stacked_noise() -> None:
    assert normalise_title("Song (feat. X) - Remastered 2011") == "Song"


def test_normalise_title_never_empties_a_title() -> None:
    # "Remaster" really is a song title. Refusing to normalise it away is the
    # difference between a miss and a crash.
    assert normalise_title("Remaster") == "Remaster"
    assert normalise_title("(Live)") != ""


def test_normalise_title_keeps_meaningful_parentheticals_unless_aggressive() -> None:
    assert normalise_title("Rock Lobster (Live)") == "Rock Lobster (Live)"
    assert normalise_title("Rock Lobster (Live)", aggressive=True) == "Rock Lobster"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Sufjan Stevens & My Brightest Diamond", "Sufjan Stevens"),
        ("Jay-Z feat. Alicia Keys", "Jay-Z"),
        ("Above & Beyond, Zoë Johnston", "Above"),
        ("Beatles, The", "The Beatles"),
    ],
)
def test_normalise_artist_reduces_to_the_primary_credit(raw: str, expected: str) -> None:
    assert normalise_artist(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Björk", "bjork"),
        ("Sigur Rós", "sigur ros"),
        ("Mötley Crüe", "motley crue"),
        ("Beyoncé", "beyonce"),
        ("Sinéad O'Connor", "sinead o connor"),
        ("Mø", "mo"),          # ø has no NFKD decomposition — explicit mapping
        ("Łukasz", "lukasz"),  # ł likewise
        ("Blue Öyster Cult", "blue oyster cult"),
    ],
)
def test_normalise_text_folds_diacritics(raw: str, expected: str) -> None:
    assert normalise_text(raw) == expected


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Don’t Stop", "Don't Stop"),          # curly vs straight apostrophe
        ("Us — Them", "Us - Them"),            # em dash vs hyphen
        ("Us – Them", "Us - Them"),            # en dash
        ("A\u00a0B", "A B"),                   # non-breaking space
        ("“Quoted”", '"Quoted"'),              # smart quotes
        ("Wait\u2026", "Wait..."),             # ellipsis
    ],
)
def test_normalise_text_unifies_unicode_punctuation(a: str, b: str) -> None:
    assert normalise_text(a) == normalise_text(b)


# --------------------------------------------------------------------------- #
# resolver: confidence + rejection
# --------------------------------------------------------------------------- #


def candidate(title: str, artists: Sequence[str], duration_ms: int | None = 210_000) -> MatchCandidate:
    slug = re.sub(r"[^a-z0-9]", "", title.lower())[:22] or "x"
    return MatchCandidate(
        uri=f"spotify:track:{slug}",
        spotify_id=slug,
        title=title,
        artists=list(artists),
        duration_ms=duration_ms,
    )


def test_confidence_is_high_for_a_true_match_despite_remaster_noise() -> None:
    track = make_track("Björk", "Jóga - Remastered 2011")
    scored = score_candidate(track, candidate("Jóga", ["Björk"]))
    assert scored.confidence >= DEFAULT_THRESHOLD
    assert scored.title_similarity > 0.9
    assert scored.artist_similarity == pytest.approx(1.0)


def test_confidence_survives_diacritic_and_featured_artist_differences() -> None:
    track = make_track("Sigur Rós", "Hoppípolla")
    scored = score_candidate(track, candidate("Hoppipolla", ["Sigur Ros"]))
    assert scored.confidence >= DEFAULT_THRESHOLD

    track2 = make_track("Sufjan Stevens", "Chicago (feat. My Brightest Diamond)")
    scored2 = score_candidate(track2, candidate("Chicago", ["Sufjan Stevens", "My Brightest Diamond"]))
    assert scored2.confidence >= DEFAULT_THRESHOLD


def test_right_title_wrong_artist_is_pushed_below_threshold() -> None:
    """A cover version is not the track we asked for."""
    track = make_track("Jeff Buckley", "Hallelujah")
    scored = score_candidate(track, candidate("Hallelujah", ["Pentatonix"]))
    assert scored.artist_similarity < 0.45
    assert scored.confidence < DEFAULT_THRESHOLD


def test_right_artist_wrong_title_is_pushed_below_threshold() -> None:
    track = make_track("Radiohead", "Karma Police")
    scored = score_candidate(track, candidate("Creep", ["Radiohead"]))
    assert scored.title_similarity < 0.55
    assert scored.confidence < DEFAULT_THRESHOLD


def test_a_wildly_different_duration_drags_confidence_down() -> None:
    track = make_track("Boards of Canada", "Roygbiv", duration_ms=151_000)
    tight = score_candidate(track, candidate("Roygbiv", ["Boards of Canada"], 152_000))
    loose = score_candidate(track, candidate("Roygbiv", ["Boards of Canada"], 600_000))
    assert tight.confidence > loose.confidence
    assert tight.duration_similarity == pytest.approx(1.0)
    assert loose.duration_similarity == pytest.approx(0.0)


def test_absent_duration_is_not_penalised() -> None:
    track = make_track("Boards of Canada", "Roygbiv", duration_ms=None)
    scored = score_candidate(track, candidate("Roygbiv", ["Boards of Canada"], None))
    assert scored.duration_similarity is None
    assert scored.confidence >= DEFAULT_THRESHOLD


# --------------------------------------------------------------------------- #
# resolver: end-to-end with a fake search
# --------------------------------------------------------------------------- #


class FakeResolver(SpotifyResolver):
    """``SpotifyResolver`` with the transport replaced. No network, ever."""

    def __init__(self, results: Sequence[MatchCandidate], **kwargs: Any) -> None:
        super().__init__(use_cache=False, **kwargs)
        self._results = list(results)
        self.queries: list[str] = []

    async def _search(self, query: str, *, token: str) -> list[MatchCandidate]:  # type: ignore[override]
        self.queries.append(query)
        return list(self._results)


def test_resolver_rejects_rather_than_substituting_a_different_song() -> None:
    resolver = FakeResolver([candidate("Hallelujah", ["Pentatonix"])])
    track = make_track("Jeff Buckley", "Hallelujah")

    resolution = run(resolver.resolve_track(track, token="fake"))

    assert resolution.ok is False
    assert resolution.uri is None
    assert resolution.confidence == 0.0
    # The near-miss is reported, not silently used.
    assert resolution.rejected_display == "Pentatonix — Hallelujah"
    assert resolution.rejected_confidence is not None
    assert "rejected rather than substituted" in resolution.reason


def test_resolver_accepts_a_good_match_and_returns_a_uri() -> None:
    resolver = FakeResolver([candidate("Jóga", ["Björk"])])
    resolution = run(resolver.resolve_track(make_track("Björk", "Jóga - Remastered 2011"), token="fake"))

    assert resolution.ok is True
    assert resolution.uri is not None and resolution.uri.startswith("spotify:track:")
    assert resolution.confidence >= DEFAULT_THRESHOLD


def test_resolver_picks_the_best_candidate_not_the_first() -> None:
    resolver = FakeResolver(
        [
            candidate("Karma Police - Karaoke Version", ["Karaoke Allstars"]),
            candidate("Karma Police", ["Radiohead"]),
        ]
    )
    resolution = run(resolver.resolve_track(make_track("Radiohead", "Karma Police"), token="fake"))
    assert resolution.ok is True
    assert resolution.matched_display == "Radiohead — Karma Police"


def test_resolver_reports_no_candidates_as_unmatched_not_an_error() -> None:
    resolution = run(FakeResolver([]).resolve_track(make_track("Nobody", "Nothing"), token="fake"))
    assert resolution.ok is False
    assert resolution.uri is None
    assert "no candidate" in resolution.reason.lower()


def test_resolver_short_circuits_when_a_uri_is_already_present() -> None:
    resolver = FakeResolver([])
    track = make_track("A", "B", spotify_uri="spotify:track:preexisting")
    resolution = run(resolver.resolve_track(track, token="fake"))
    assert resolution.ok is True
    assert resolution.uri == "spotify:track:preexisting"
    assert resolution.strategy == "prefilled"
    assert resolver.queries == [], "a prefilled URI must not cost a search call"


def test_resolver_builds_strict_field_filtered_queries_first() -> None:
    resolver = FakeResolver([])
    queries = resolver.build_queries(make_track("Björk", "Jóga - Remastered 2011"))
    strategy, first = queries[0]
    assert strategy == "strict"
    assert 'track:"Jóga"' in first
    assert 'artist:"Björk"' in first
    # A fuzzy fallback must exist for when strict filters return nothing.
    assert any(s.startswith("fuzzy") for s, _ in queries)


def test_resolver_batch_preserves_order_and_reports_both_outcomes() -> None:
    class Mixed(FakeResolver):
        async def _search(self, query: str, *, token: str) -> list[MatchCandidate]:  # type: ignore[override]
            self.queries.append(query)
            if "Roygbiv" in query or "roygbiv" in query:
                return [candidate("Roygbiv", ["Boards of Canada"], 151_000)]
            return [candidate("Something Else Entirely", ["A Different Band"])]

    resolver = Mixed([])
    tracks = [
        make_track("Boards of Canada", "Roygbiv", duration_ms=151_000),
        make_track("Nobody At All", "Untraceable"),
    ]
    result = run(resolver.resolve(tracks, token="fake"))

    assert result.requested_count == 2
    assert result.matched_count == 1
    assert [r.requested for r in result.resolutions] == [t.display for t in tracks]
    assert result.unmatched_labels == ["Nobody At All — Untraceable"]
    assert len(result.uris) == 1
    assert 0.0 < result.mean_confidence <= 1.0
    assert set(result.confidence_map()) == {t.key for t in tracks}


def test_resolver_batch_on_empty_input_is_a_no_op() -> None:
    result = run(FakeResolver([]).resolve([], token="fake"))
    assert result.requested_count == 0
    assert result.uris == []


# --------------------------------------------------------------------------- #
# PKCE
# --------------------------------------------------------------------------- #

_RFC7636_UNRESERVED = re.compile(r"^[A-Za-z0-9\-._~]+$")


def test_code_verifier_matches_rfc7636_length_and_charset() -> None:
    for _ in range(50):
        verifier = generate_code_verifier()
        assert 43 <= len(verifier) <= 128, "RFC 7636 §4.1 requires 43..128 characters"
        assert _RFC7636_UNRESERVED.fullmatch(verifier), "must use only unreserved characters"
        # base64url output must never contain padding or the base64 specials.
        assert "=" not in verifier and "+" not in verifier and "/" not in verifier


def test_code_verifiers_are_unique() -> None:
    assert len({generate_code_verifier() for _ in range(200)}) == 200


def test_code_challenge_is_base64url_sha256_of_the_ascii_verifier() -> None:
    verifier = generate_code_verifier()
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    assert code_challenge_for(verifier) == expected
    assert len(code_challenge_for(verifier)) == 43  # SHA-256 -> 32 bytes -> 43 chars
    assert _RFC7636_UNRESERVED.fullmatch(code_challenge_for(verifier))


def test_code_challenge_matches_the_rfc7636_appendix_b_test_vector() -> None:
    """The one worked example in the RFC. If this passes, the S256 wiring is right."""
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert code_challenge_for(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_pkce_pair_keeps_verifier_and_challenge_consistent() -> None:
    pair = PkcePair()
    assert pair.method == "S256"
    assert pair.challenge == code_challenge_for(pair.verifier)


def test_pkce_pair_repr_does_not_leak_the_verifier() -> None:
    pair = PkcePair()
    assert pair.verifier not in repr(pair)
    assert "redacted" in repr(pair)


def test_state_values_are_random_and_url_safe() -> None:
    states = {generate_state() for _ in range(100)}
    assert len(states) == 100
    assert all(_RFC7636_UNRESERVED.fullmatch(s) for s in states)


# --------------------------------------------------------------------------- #
# authorize URL
# --------------------------------------------------------------------------- #


def test_authorize_url_carries_the_challenge_and_never_the_verifier() -> None:
    from urllib.parse import parse_qs, urlparse

    auth = SpotifyAuth(settings=FakeSettings(), vault=InMemoryTokenVault())
    pair = PkcePair()
    url = auth.build_authorize_url("state-123", SPOTIFY_SCOPES, pkce=pair)

    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    assert parsed.netloc == "accounts.spotify.com"
    assert parsed.path == "/authorize"
    assert params["response_type"] == ["code"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["code_challenge"] == [pair.challenge]
    assert params["state"] == ["state-123"]
    assert params["client_id"] == ["test-client-id"]
    assert set(params["scope"][0].split()) == set(SPOTIFY_SCOPES)
    assert "client_secret" not in params
    assert pair.verifier not in url, "the verifier must never leave the server"


def test_authorize_url_requires_configuration() -> None:
    from app.errors import PairingError

    auth = SpotifyAuth(settings=FakeSettings(client_id=None), vault=InMemoryTokenVault())
    assert auth.configured is False
    with pytest.raises(PairingError):
        auth.build_authorize_url("state", SPOTIFY_SCOPES, pkce=PkcePair())


# --------------------------------------------------------------------------- #
# tokens
# --------------------------------------------------------------------------- #


def make_tokens(*, expires_in: int = 3600, refresh: str | None = "refresh-abc", scope: str | None = None) -> SpotifyTokens:
    from datetime import timedelta

    return SpotifyTokens(
        access_token="access-secret-value",
        refresh_token=refresh,
        scope=scope if scope is not None else " ".join(SPOTIFY_SCOPES),
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
    )


def test_tokens_never_appear_in_repr_or_str() -> None:
    tokens = make_tokens()
    assert "access-secret-value" not in repr(tokens)
    assert "refresh-abc" not in repr(tokens)
    assert "access-secret-value" not in str(tokens)
    assert "access-secret-value" not in f"{tokens}"


def test_token_expiry_uses_a_safety_margin() -> None:
    assert make_tokens(expires_in=3600).is_expired() is False
    # Inside the 60s margin: still technically valid, treated as expired.
    assert make_tokens(expires_in=30).is_expired() is True
    assert make_tokens(expires_in=-10).is_expired() is True


def test_scope_checking_reports_exactly_what_is_missing() -> None:
    full = make_tokens()
    assert full.has_scopes() is True
    assert full.missing_scopes() == []

    partial = make_tokens(scope="user-read-private playlist-modify-private")
    assert partial.has_scopes() is False
    assert "user-library-modify" in partial.missing_scopes()


def test_refresh_token_rotation_keeps_the_old_token_when_none_is_returned() -> None:
    rotated = SpotifyTokens.from_response(
        {"access_token": "new", "expires_in": 3600, "scope": "a b"},
        fallback_refresh="old-refresh",
    )
    assert rotated.refresh_token == "old-refresh"
    assert rotated.rolled_from is True

    replaced = SpotifyTokens.from_response(
        {"access_token": "new", "expires_in": 3600, "refresh_token": "brand-new"},
        fallback_refresh="old-refresh",
    )
    assert replaced.refresh_token == "brand-new"
    assert replaced.rolled_from is False


def test_in_memory_vault_round_trips_and_deletes() -> None:
    vault = InMemoryTokenVault()
    assert isinstance(vault, TokenVault)

    tokens = make_tokens()
    run(vault.put("user_a", tokens))
    assert run(vault.get("user_a")) is tokens
    assert run(vault.get("nobody")) is None

    run(vault.delete("user_a"))
    assert run(vault.get("user_a")) is None
    run(vault.delete("user_a"))  # idempotent


# --------------------------------------------------------------------------- #
# SpotifySink degradation
# --------------------------------------------------------------------------- #


def test_spotify_sink_degrades_when_unconfigured(playlist: Playlist) -> None:
    sink = make_spotify_sink(client_id=None)

    assert run(sink.available("user_abc")) is False

    result = run(sink.write(playlist, user_id="user_abc"))
    assert isinstance(result, SinkResult)
    assert result.ok is False
    assert result.kind == "spotify"
    assert result.matched == 0
    assert result.requested == 4
    assert result.external_url is None
    assert "not configured" in result.message.lower()


def test_spotify_sink_degrades_when_unpaired(playlist: Playlist) -> None:
    sink = make_spotify_sink(vault=InMemoryTokenVault())  # configured, empty vault

    assert run(sink.available("user_abc")) is False

    result = run(sink.write(playlist, user_id="user_abc"))
    assert result.ok is False
    assert result.matched == 0
    assert "pair" in result.message.lower()


def test_spotify_sink_degrades_with_no_user_at_all() -> None:
    pl = Playlist(sky=_SKY, sonic_target=_TARGET, theme_id="petrichor", id="p", title="t", tracks=[], rationale=Rationale(headline="h", body="b"))
    result = run(make_spotify_sink().write(pl, user_id=None))
    assert result.ok is False
    assert "sign in" in result.message.lower() or "no signed-in user" in result.message.lower()


def test_spotify_sink_never_raises_even_when_the_vault_explodes(playlist: Playlist) -> None:
    class ExplodingVault:
        async def get(self, user_id: str) -> Any:
            raise RuntimeError("firestore is on fire")

        async def put(self, user_id: str, tokens: Any) -> None:
            raise RuntimeError("firestore is on fire")

        async def delete(self, user_id: str) -> None:
            raise RuntimeError("firestore is on fire")

    sink = make_spotify_sink(vault=ExplodingVault())  # type: ignore[arg-type]

    # available() swallows it...
    assert run(sink.available("user_abc")) is False
    # ...and so does write().
    result = run(sink.write(playlist, user_id="user_abc"))
    assert result.ok is False
    assert result.kind == "spotify"


def test_spotify_sink_availability_is_false_without_a_user() -> None:
    assert run(make_spotify_sink().available(None)) is False


def test_dead_endpoints_are_documented_and_never_referenced_in_code() -> None:
    """Guard rail: if someone re-adds /audio-features, this fails."""
    assert "/recommendations" in DEAD_ENDPOINTS
    assert "/audio-features" in DEAD_ENDPOINTS
    assert "/artists/{id}/related-artists" in DEAD_ENDPOINTS
    assert "/browse/featured-playlists" in DEAD_ENDPOINTS

    banned = ("/audio-features", "/audio-analysis", "/recommendations", "/related-artists")
    for module in (
        Path(resolver_mod.__file__),
        Path(sys.modules["app.sinks.spotify"].__file__ or ""),
    ):
        source = module.read_text(encoding="utf-8")
        # Strip the graveyard block and comments before checking for live calls:
        # the strings are *supposed* to appear in documentation.
        code_lines = [
            line for line in source.splitlines() if not line.lstrip().startswith("#")
        ]
        code = "\n".join(code_lines)
        for endpoint in banned:
            assert f'f"{{self._api_base}}{endpoint}' not in code, f"{module.name} calls {endpoint}"


def test_description_compression_respects_spotifys_300_char_limit(playlist: Playlist) -> None:
    description = compress_description(playlist)
    assert 0 < len(description) <= DESCRIPTION_LIMIT
    assert "BAROGROOVE" in description
    assert "low-pressure-drift" in description
    # Nothing should be cut mid-word without an explicit ellipsis.
    assert not description.endswith(" ")


def test_description_compression_handles_an_absurdly_long_rationale() -> None:
    pl = Playlist(sky=_SKY, sonic_target=_TARGET, 
        id="p",
        title="t",
        tracks=[],
        theme_id="theme",
        genre_id="genre",
        rationale=Rationale(headline="word " * 400, body="b" * 5000),
    )
    description = compress_description(pl)
    assert len(description) <= DESCRIPTION_LIMIT


def test_description_compression_survives_an_empty_rationale() -> None:
    pl = Playlist(sky=_SKY, sonic_target=_TARGET, theme_id="petrichor", id="p", title="t", tracks=[], rationale=Rationale(headline="", body=""))
    description = compress_description(pl)
    assert description and len(description) <= DESCRIPTION_LIMIT


# --------------------------------------------------------------------------- #
# registry fallthrough
# --------------------------------------------------------------------------- #


class StubSink:
    """A configurable ``PlaylistSink`` for exercising the fallthrough."""

    def __init__(self, kind: str, *, is_available: bool, ok: bool, message: str = "", raises: bool = False) -> None:
        self.kind = kind  # type: ignore[assignment]
        self._available = is_available
        self._ok = ok
        self._message = message
        self._raises = raises
        self.write_calls = 0

    async def available(self, user_id: str | None) -> bool:
        return self._available

    async def write(self, playlist: Playlist, *, user_id: str | None = None) -> SinkResult:
        self.write_calls += 1
        if self._raises:
            raise RuntimeError("this sink is broken")
        return SinkResult(
            kind=self.kind,  # type: ignore[arg-type]
            ok=self._ok,
            external_id="ext-1" if self._ok else None,
            external_url="https://open.spotify.com/playlist/ext-1" if self._ok else None,
            matched=len(playlist.tracks) if self._ok else 0,
            requested=len(playlist.tracks),
            message=self._message,
        )


def test_auto_prefers_spotify_when_it_is_available(playlist: Playlist) -> None:
    spotify = StubSink("spotify", is_available=True, ok=True, message="wrote it")
    sinks = [spotify, M3USink(), NoopSink()]

    chosen = run(choose_sink(sinks, "auto", "user_abc"))
    assert chosen is spotify

    result = run(write_playlist(sinks, playlist, kind="auto", user_id="user_abc"))
    assert result.ok is True
    assert result.kind == "spotify"
    assert result.external_url == "https://open.spotify.com/playlist/ext-1"
    assert result.payload is None


def test_auto_falls_through_to_m3u_when_spotify_is_unavailable(playlist: Playlist) -> None:
    spotify = StubSink("spotify", is_available=False, ok=True)
    sinks = [spotify, M3USink(), NoopSink()]

    chosen = run(choose_sink(sinks, "auto", "user_abc"))
    assert chosen.kind == "m3u"

    result = run(write_playlist(sinks, playlist, kind="auto", user_id="user_abc"))
    assert result.ok is True
    assert result.kind == "m3u"
    assert result.payload is not None and result.payload.startswith("#EXTM3U")
    assert spotify.write_calls == 0, "an unavailable sink must not be written to"


def test_auto_falls_through_and_explains_why_when_spotify_returns_not_ok(playlist: Playlist) -> None:
    reason = "The app's 5-user Developer Mode allowance is full"
    spotify = StubSink("spotify", is_available=True, ok=False, message=reason)
    sinks = [spotify, M3USink()]

    result = run(write_playlist(sinks, playlist, kind="auto", user_id="user_abc"))

    assert result.ok is True
    assert result.kind == "m3u"
    assert spotify.write_calls == 1
    # The user must learn why they got a file instead of a playlist.
    assert reason in result.message
    assert result.message.startswith(reason)
    assert "annotated M3U" in result.message


def test_fallthrough_absorbs_a_sink_that_breaks_its_never_raise_contract(playlist: Playlist) -> None:
    spotify = StubSink("spotify", is_available=True, ok=True, raises=True)
    sinks = [spotify, M3USink()]

    result = run(write_playlist(sinks, playlist, kind="auto", user_id="user_abc"))
    assert result.ok is True
    assert result.kind == "m3u"
    assert "RuntimeError" in result.message


def test_real_unpaired_spotify_sink_falls_through_to_m3u(playlist: Playlist) -> None:
    """The end-to-end version of the policy, with the real SpotifySink."""
    sinks = [make_spotify_sink(), M3USink(), NoopSink()]

    result = run(write_playlist(sinks, playlist, kind="auto", user_id="user_abc"))

    assert result.ok is True
    assert result.kind == "m3u"
    assert result.payload is not None
    _, entries = parse_m3u(result.payload)
    assert len(entries) == 4


def test_explicit_spotify_still_falls_through_rather_than_failing(playlist: Playlist) -> None:
    sinks = [make_spotify_sink(client_id=None), M3USink()]
    result = run(write_playlist(sinks, playlist, kind="spotify", user_id="user_abc"))
    assert result.ok is True
    assert result.kind == "m3u"
    assert "not configured" in result.message.lower()


def test_explicit_m3u_never_touches_spotify(playlist: Playlist) -> None:
    spotify = StubSink("spotify", is_available=True, ok=True)
    result = run(write_playlist([spotify, M3USink()], playlist, kind="m3u", user_id="user_abc"))
    assert result.kind == "m3u"
    assert spotify.write_calls == 0


def test_kind_none_is_a_no_op(playlist: Playlist) -> None:
    sinks = [make_spotify_sink(), M3USink(), NoopSink()]

    chosen = run(choose_sink(sinks, "none", "user_abc"))
    assert chosen.kind == "none"

    result = run(write_playlist(sinks, playlist, kind="none", user_id="user_abc"))
    assert result.ok is True
    assert result.kind == "none"
    assert result.payload is None
    assert result.matched == 0


def test_registry_synthesises_an_m3u_sink_if_none_was_registered(playlist: Playlist) -> None:
    """The fallback floor cannot be removed by a misconfigured composition root."""
    spotify = StubSink("spotify", is_available=False, ok=True)
    result = run(write_playlist([spotify], playlist, kind="auto", user_id="user_abc"))
    assert result.kind == "m3u"
    assert result.payload is not None


def test_choose_sink_honours_an_explicit_kind_even_when_unavailable(playlist: Playlist) -> None:
    spotify = StubSink("spotify", is_available=False, ok=True)
    chosen = run(choose_sink([spotify, M3USink()], "spotify", "user_abc"))
    assert chosen is spotify


def test_availability_probe_that_raises_counts_as_unavailable(playlist: Playlist) -> None:
    class ProbeExplodes(StubSink):
        async def available(self, user_id: str | None) -> bool:
            raise RuntimeError("nope")

    spotify = ProbeExplodes("spotify", is_available=True, ok=True)
    chosen = run(choose_sink([spotify, M3USink()], "auto", "user_abc"))
    assert chosen.kind == "m3u"


# --------------------------------------------------------------------------- #
# pairing router loads without the Last.fm module present
# --------------------------------------------------------------------------- #


def test_pairing_router_imports_and_exposes_every_endpoint() -> None:
    """The router must load even though the Last.fm auth module does not exist."""
    from app.routes.pairing import router

    paths = {route.path for route in router.routes}  # type: ignore[attr-defined]
    assert "/api/pair/status" in paths
    assert "/api/pair/spotify/start" in paths
    assert "/api/pair/spotify/callback" in paths
    assert "/api/pair/lastfm/start" in paths
    assert "/api/pair/lastfm/callback" in paths
    assert "/api/pair/{provider}/disconnect" in paths


def test_pairing_state_store_is_single_use_and_ttl_bounded() -> None:
    from app.routes.pairing import _PendingPairing, _StateStore

    store = _StateStore()
    store.put("state-1", _PendingPairing("spotify", "user_a", "verifier-1"))

    taken = store.take("state-1")
    assert taken is not None and taken.user_id == "user_a"
    # Replaying the same state must fail — that is the CSRF guard.
    assert store.take("state-1") is None
    assert store.take("never-existed") is None


def test_pairing_state_expires() -> None:
    from app.routes.pairing import _PendingPairing, _StateStore

    store = _StateStore()
    pending = _PendingPairing("spotify", "user_a", "verifier-1")
    pending.created_at -= 10_000  # pretend it is very old
    store._items["stale"] = pending
    assert store.take("stale") is None


def test_pending_pairing_repr_does_not_leak_the_verifier() -> None:
    from app.routes.pairing import _PendingPairing

    pending = _PendingPairing("spotify", "user_a", "super-secret-verifier")
    assert "super-secret-verifier" not in repr(pending)


# --------------------------------------------------------------------------- #
# SpotifySink happy path, with the transport faked
# --------------------------------------------------------------------------- #


class FakeTransport:
    """Records every ``request_json`` call and returns canned Spotify responses.

    This exists because every *other* Spotify test degrades before reaching the
    network, which once let a NameError sit undetected on the success path.
    """

    def __init__(self, *, me: dict[str, Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._me = me or {"id": "spotify_user_9", "product": "premium"}

    async def __call__(self, method: str, url: str, **kwargs: Any) -> Any:
        self.calls.append({"method": method, "url": url, **kwargs})

        if url.endswith("/me"):
            return self._me
        if url.endswith("/me/playlists"):
            return {
                "id": "pl_spotify_123",
                "external_urls": {"spotify": "https://open.spotify.com/playlist/pl_spotify_123"},
            }
        if url.endswith("/items") or url.endswith("/tracks"):
            return {"snapshot_id": "snap-1"}
        if url.endswith("/me/library"):
            return None
        if url.endswith("/me/library/contains"):
            return [True] * len(str(kwargs.get("params", {}).get("uris", "")).split(","))
        raise AssertionError(f"unexpected call to {url}")

    def urls(self, method: str | None = None) -> list[str]:
        return [c["url"] for c in self.calls if method is None or c["method"] == method]


class PrefilledResolver(SpotifyResolver):
    """Resolver that matches everything, without any search traffic."""

    async def resolve(self, tracks: Any, *, token: str) -> Any:  # type: ignore[override]
        from app.sinks.resolver import ResolutionResult, TrackResolution

        items = list(tracks)
        return ResolutionResult(
            resolutions=[
                TrackResolution(
                    key=t.key,
                    requested=t.display,
                    uri=f"spotify:track:{i:022d}",
                    spotify_id=f"{i:022d}",
                    confidence=0.95,
                    matched_display=t.display,
                    strategy="strict",
                )
                for i, t in enumerate(items)
            ]
        )


def paired_sink(transport: FakeTransport, resolver: Any | None = None) -> SpotifySink:
    vault = InMemoryTokenVault()
    run(vault.put("user_abc", make_tokens()))
    sink = SpotifySink(
        settings=FakeSettings(),
        vault=vault,
        resolver=resolver or PrefilledResolver(use_cache=False),
    )
    import app.sinks.spotify as spotify_mod

    spotify_mod.request_json = transport  # type: ignore[assignment]
    return sink


@pytest.fixture(autouse=True)
def _restore_request_json():
    """Undo any transport monkeypatching so tests stay independent."""
    import app.sinks.spotify as spotify_mod

    original = spotify_mod.request_json
    yield
    spotify_mod.request_json = original


def test_spotify_sink_writes_a_playlist_end_to_end(playlist: Playlist) -> None:
    transport = FakeTransport()
    result = run(paired_sink(transport).write(playlist, user_id="user_abc"))

    assert result.ok is True
    assert result.kind == "spotify"
    assert result.external_id == "pl_spotify_123"
    assert result.external_url == "https://open.spotify.com/playlist/pl_spotify_123"
    assert result.matched == 4
    assert result.requested == 4
    assert result.payload is None
    assert "Added 4 of 4" in result.message


def test_spotify_sink_uses_the_feb_2026_endpoints(playlist: Playlist) -> None:
    transport = FakeTransport()
    run(paired_sink(transport).write(playlist, user_id="user_abc"))

    urls = transport.urls()
    # Create must target /me/playlists, NOT the removed /users/{id}/playlists.
    assert any(u.endswith("/me/playlists") for u in urls)
    assert not any("/users/" in u for u in urls)
    # Add items must target /items, not the renamed-away /tracks.
    assert any(u.endswith("/items") for u in urls)
    assert not any(u.endswith("/tracks") for u in urls)


def test_spotify_sink_sends_uris_array_and_a_bounded_description(playlist: Playlist) -> None:
    transport = FakeTransport()
    run(paired_sink(transport).write(playlist, user_id="user_abc"))

    create = next(c for c in transport.calls if c["url"].endswith("/me/playlists"))
    body = create["json_body"]
    assert body["public"] is False
    assert len(body["description"]) <= DESCRIPTION_LIMIT
    assert len(body["name"]) <= 100

    add = next(c for c in transport.calls if c["url"].endswith("/items"))
    assert isinstance(add["json_body"]["uris"], list)
    assert all(u.startswith("spotify:track:") for u in add["json_body"]["uris"])


def test_spotify_sink_batches_add_items_at_100() -> None:
    tracks = [make_track(f"Artist {i}", f"Title {i}") for i in range(250)]
    big = Playlist(sky=_SKY, sonic_target=_TARGET, theme_id="petrichor", 
        id="pl_big",
        title="Long One",
        tracks=[make_scored(t, i) for i, t in enumerate(tracks)],
        rationale=Rationale(headline="h", body="b"),
    )
    transport = FakeTransport()
    result = run(paired_sink(transport).write(big, user_id="user_abc"))

    assert result.ok is True
    assert result.matched == 250
    add_calls = [c for c in transport.calls if c["url"].endswith("/items")]
    assert [len(c["json_body"]["uris"]) for c in add_calls] == [100, 100, 50]


def test_spotify_sink_reports_a_free_account(playlist: Playlist) -> None:
    transport = FakeTransport(me={"id": "u", "product": "free"})
    result = run(paired_sink(transport).write(playlist, user_id="user_abc"))
    assert result.ok is True
    assert "not Premium" in result.message


def test_spotify_sink_degrades_when_nothing_resolves(playlist: Playlist) -> None:
    class NoMatchResolver(SpotifyResolver):
        async def resolve(self, tracks: Any, *, token: str) -> Any:  # type: ignore[override]
            from app.sinks.resolver import ResolutionResult, TrackResolution

            return ResolutionResult(
                resolutions=[
                    TrackResolution(
                        key=t.key,
                        requested=t.display,
                        rejected_display="Something Wrong",
                        rejected_confidence=0.5,
                        reason="rejected rather than substituted",
                    )
                    for t in tracks
                ]
            )

    transport = FakeTransport()
    sink = paired_sink(transport, NoMatchResolver(use_cache=False))
    result = run(sink.write(playlist, user_id="user_abc"))

    assert result.ok is False
    assert result.matched == 0
    assert len(result.unmatched) == 4
    assert "rejected rather than substituted" in result.message
    # It must not have created an empty playlist.
    assert not any(c["url"].endswith("/me/playlists") for c in transport.calls)


def test_spotify_sink_degrades_on_403_without_raising(playlist: Playlist) -> None:
    from app.http import UpstreamError

    async def forbidden(method: str, url: str, **kwargs: Any) -> Any:
        raise UpstreamError("spotify", "nope", status=403, url=url)

    vault = InMemoryTokenVault()
    run(vault.put("user_abc", make_tokens()))
    sink = SpotifySink(
        settings=FakeSettings(), vault=vault, resolver=PrefilledResolver(use_cache=False)
    )
    import app.sinks.spotify as spotify_mod

    spotify_mod.request_json = forbidden  # type: ignore[assignment]

    result = run(sink.write(playlist, user_id="user_abc"))
    assert result.ok is False
    assert "5-user" in result.message
    assert "403" in result.message


def test_spotify_403_falls_through_to_m3u_in_the_registry(playlist: Playlist) -> None:
    """The whole policy, exercised against the real sinks and a 403."""
    from app.http import UpstreamError

    async def forbidden(method: str, url: str, **kwargs: Any) -> Any:
        raise UpstreamError("spotify", "nope", status=403, url=url)

    vault = InMemoryTokenVault()
    run(vault.put("user_abc", make_tokens()))
    spotify = SpotifySink(
        settings=FakeSettings(), vault=vault, resolver=PrefilledResolver(use_cache=False)
    )
    import app.sinks.spotify as spotify_mod

    spotify_mod.request_json = forbidden  # type: ignore[assignment]

    result = run(write_playlist([spotify, M3USink()], playlist, kind="auto", user_id="user_abc"))

    assert result.ok is True
    assert result.kind == "m3u"
    assert result.payload is not None and result.payload.startswith("#EXTM3U")
    # The user is told why they got a file.
    assert "403" in result.message
    _, entries = parse_m3u(result.payload)
    assert len(entries) == 4


# --------------------------------------------------------------------------- #
# Feb-2026 library shape
# --------------------------------------------------------------------------- #


def test_save_to_library_sends_uris_as_a_comma_separated_query_param() -> None:
    transport = FakeTransport()
    sink = paired_sink(transport)
    uris = [f"spotify:track:{i:022d}" for i in range(3)]

    result = run(sink.save_to_library(uris, user_id="user_abc"))

    assert result.ok is True
    assert result.matched == 3
    call = next(c for c in transport.calls if c["url"].endswith("/me/library"))
    assert call["method"] == "PUT"
    assert call["params"]["uris"] == ",".join(uris)
    # URIs, never bare IDs — that is the whole point of the Feb-2026 shape.
    assert all(u.startswith("spotify:") for u in call["params"]["uris"].split(","))


def test_save_to_library_batches_at_40() -> None:
    transport = FakeTransport()
    sink = paired_sink(transport)
    uris = [f"spotify:track:{i:022d}" for i in range(95)]

    result = run(sink.save_to_library(uris, user_id="user_abc"))

    assert result.matched == 95
    calls = [c for c in transport.calls if c["url"].endswith("/me/library")]
    assert [len(c["params"]["uris"].split(",")) for c in calls] == [40, 40, 15]


def test_save_to_library_rejects_bare_ids() -> None:
    transport = FakeTransport()
    result = run(paired_sink(transport).save_to_library(["4iV5W9uYEdYUVa79Axb7Rh"], user_id="user_abc"))
    assert result.ok is False
    assert "No valid Spotify URIs" in result.message


def test_library_contains_maps_a_boolean_array_back_onto_the_uris() -> None:
    transport = FakeTransport()
    sink = paired_sink(transport)
    uris = [f"spotify:track:{i:022d}" for i in range(3)]

    contains = run(sink.library_contains(uris, user_id="user_abc"))

    assert contains == {u: True for u in uris}
    call = next(c for c in transport.calls if "contains" in c["url"])
    assert call["method"] == "GET"
    assert call["params"]["uris"] == ",".join(uris)


def test_library_contains_degrades_to_empty_when_unpaired() -> None:
    sink = SpotifySink(settings=FakeSettings(), vault=InMemoryTokenVault())
    assert run(sink.library_contains(["spotify:track:x"], user_id="nobody")) == {}

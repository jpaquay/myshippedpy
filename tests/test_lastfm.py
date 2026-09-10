"""Tests for the Last.fm acoustic oracle. No network, ever.

The lexicon gets the hardest treatment because it is the only part of the
subsystem that is pure: same input, same output, no clock, no sockets. If the
numbers in ``lexicon.py`` drift, these assertions are what notices.

Everything that would touch the network is either exercised against a
hand-written payload or replaced by the offline oracle.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# path bootstrap
# ---------------------------------------------------------------------------
# The application package lives under ``backend/`` and the fixtures live at the
# repository root, so both roots go on ``sys.path``. Doing it here rather than
# in a conftest keeps this file runnable on its own with a bare ``pytest``.
_ROOT = Path(__file__).resolve().parents[1]
for _candidate in (_ROOT, _ROOT / "backend"):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from app.contracts import (  # noqa: E402
    SONIC_DIMS,
    AcousticOracle,
    GenreCorridor,
    SonicVector,
    TasteVector,
    Track,
)
from app.errors import OracleUnavailable, PairingError  # noqa: E402
from app.lastfm import client as client_mod  # noqa: E402
from app.lastfm import lexicon as lex  # noqa: E402
from app.lastfm.client import (  # noqa: E402
    LastfmArtist,
    LastfmClient,
    LastfmTag,
    LastfmTrack,
    as_float,
    as_int,
    as_list,
    as_str,
    first_image,
    gather_bounded,
)
from app.lastfm.offline import (  # noqa: E402
    OFFLINE_TRACKS,
    OfflineOracle,
    offline_corridor,
    offline_theme_tags,
)
from app.lastfm.pairing import (  # noqa: E402
    InMemoryTokenVault,
    LastfmSession,
    PairingTicket,
    build_auth_url,
    complete_pairing,
    redact,
    sign_params,
    signature_base_string,
)
from fixtures.seed_corpus import SEED_CORPUS, THEMES, by_theme  # noqa: E402

NEUTRAL = 0.5


def run(coro):
    """Tiny runner so the suite needs no async plugin."""
    return asyncio.run(coro)


# ===========================================================================
# LEXICON — canonicalisation
# ===========================================================================
class TestCanonicalisation:
    def test_hyphen_space_and_runtogether_are_one_tag(self) -> None:
        forms = ["post rock", "post-rock", "postrock", "Post Rock", "POST-ROCK", "post_rock"]
        canon = {lex.canonical_tag(f) for f in forms}
        assert canon == {"post rock"}

    def test_identical_vectors_for_every_spelling(self) -> None:
        a = lex.estimate_from_tags(["post-rock"])
        b = lex.estimate_from_tags(["postrock"])
        c = lex.estimate_from_tags(["Post Rock"])
        assert a == b == c

    def test_accents_and_punctuation_are_stripped(self) -> None:
        assert lex.canonical_tag("Musique Concrète") == "musique concrete"
        assert lex.canonical_tag("  drum & bass  ") == "drum and bass"

    def test_plurals_fall_back_to_the_singular(self) -> None:
        assert lex.canonical_tag("drones") == "drone"
        assert lex.canonical_tag("soundscapes") == "atmospheric"

    def test_synonyms_resolve_through_the_alias_map(self) -> None:
        assert lex.canonical_tag("melancholic") == "melancholy"
        assert lex.canonical_tag("shoegazing") == "shoegaze"
        assert lex.canonical_tag("lofi") == lex.canonical_tag("lo-fi") == "lo fi"
        assert lex.canonical_tag("dnb") == "drum and bass"

    def test_unknown_tag_is_none(self) -> None:
        assert lex.canonical_tag("definitely not a real genre") is None
        assert lex.canonical_tag("") is None

    def test_exported_tables_are_consistent(self) -> None:
        assert isinstance(lex.KNOWN_TAGS, frozenset)
        assert isinstance(lex.ALIASES, dict)
        # The brief asked for at least 110 curated tags.
        assert len(lex.KNOWN_TAGS) >= 110
        # Every alias points somewhere real and shadows nothing.
        assert all(target in lex.KNOWN_TAGS for target in lex.ALIASES.values())
        assert not (set(lex.ALIASES) & set(lex.KNOWN_TAGS))

    def test_lexicon_covers_the_required_families(self) -> None:
        required = {
            "krautrock", "shoegaze", "dub techno", "slowcore", "post punk",
            "spiritual jazz", "drone", "ambient", "idm", "desert blues",
            "cold wave", "black metal", "bossa nova", "minimal wave", "jungle",
            "gospel", "melancholy", "euphoric", "bittersweet", "menacing",
            "wistful", "hypnotic", "rainy day", "driving", "late night",
            "summer", "sunday morning", "winter", "lo fi", "hi fi", "tape",
            "reverb", "distorted", "acoustic", "orchestral", "minimal",
            "wall of sound",
        }
        assert required <= lex.KNOWN_TAGS


# ===========================================================================
# LEXICON — the judgements that matter
# ===========================================================================
class TestLexiconJudgements:
    def test_shoegaze_raises_spatiality_and_grit(self) -> None:
        v = lex.estimate_from_tags(["shoegaze"])
        assert v.spatiality > NEUTRAL
        assert v.grit > NEUTRAL
        # Not a nudge: these are the defining dimensions.
        assert v.spatiality > 0.65
        assert v.grit > 0.6

    def test_shoegaze_leaves_valence_alone(self) -> None:
        # Loveless and Souvlaki share a texture, not an emotion.
        assert lex.estimate_from_tags(["shoegaze"]).valence == pytest.approx(NEUTRAL)

    def test_slowcore_lowers_tempo_and_density(self) -> None:
        v = lex.estimate_from_tags(["slowcore"])
        assert v.tempo < NEUTRAL
        assert v.density < NEUTRAL
        assert v.tempo < 0.35
        assert v.density < 0.35

    def test_slowcore_is_slower_than_shoegaze_and_krautrock(self) -> None:
        slow = lex.estimate_from_tags(["slowcore"])
        kraut = lex.estimate_from_tags(["krautrock"])
        assert slow.tempo < kraut.tempo
        assert slow.tempo_bpm < kraut.tempo_bpm

    def test_krautrock_raises_density_and_keeps_valence_neutral(self) -> None:
        v = lex.estimate_from_tags(["krautrock"])
        assert v.density > NEUTRAL
        assert v.tempo > NEUTRAL
        assert v.acousticness < NEUTRAL
        # Motorik is not happy, it is relentless.
        assert v.valence == pytest.approx(NEUTRAL)

    def test_krautrock_is_not_mistaken_for_a_happy_genre(self) -> None:
        kraut = lex.estimate_from_tags(["krautrock"])
        disco = lex.estimate_from_tags(["disco"])
        assert disco.valence > kraut.valence
        # ...even though both are fast and busy.
        assert kraut.tempo > NEUTRAL and disco.tempo > NEUTRAL

    def test_dub_techno_is_spacious_but_not_dense(self) -> None:
        v = lex.estimate_from_tags(["dub techno"])
        assert v.spatiality > 0.7
        assert v.density < NEUTRAL
        assert v.acousticness < 0.3

    def test_drone_bottoms_out_density_without_bottoming_out_size(self) -> None:
        v = lex.estimate_from_tags(["drone"])
        assert v.density < 0.3
        assert v.spatiality > 0.65

    def test_ambient_and_black_metal_sit_at_opposite_ends_of_energy(self) -> None:
        assert lex.estimate_from_tags(["ambient"]).energy < 0.35
        assert lex.estimate_from_tags(["black metal"]).energy > 0.7

    def test_acoustic_and_analog_synth_oppose_on_acousticness(self) -> None:
        assert lex.estimate_from_tags(["acoustic"]).acousticness > 0.75
        assert lex.estimate_from_tags(["analog synth"]).acousticness < 0.25

    def test_context_tags_are_weaker_than_genre_tags(self) -> None:
        # "rainy day" should not out-vote "black metal" about energy.
        mixed = lex.estimate_from_tags(["black metal", "rainy day"])
        assert mixed.energy > NEUTRAL

    def test_every_dimension_stays_in_range_for_every_single_tag(self) -> None:
        for tag in sorted(lex.KNOWN_TAGS):
            v = lex.estimate_from_tags([tag])
            for dim in SONIC_DIMS:
                value = getattr(v, dim)
                assert 0.0 <= value <= 1.0, f"{tag}.{dim} = {value}"


# ===========================================================================
# LEXICON — degradation and weighting
# ===========================================================================
class TestLexiconDegradation:
    def test_unknown_tags_degrade_to_neutral(self) -> None:
        v = lex.estimate_from_tags(["blorptronica", "zzzz", ""])
        assert v == SonicVector.neutral()
        assert v.as_dict() == {dim: NEUTRAL for dim in SONIC_DIMS}

    def test_unknown_tags_do_not_raise_any_dimension(self) -> None:
        v = lex.estimate_from_tags(["not a genre", "also not a genre"])
        assert all(getattr(v, dim) == NEUTRAL for dim in SONIC_DIMS)

    def test_empty_input_is_neutral_with_zero_confidence(self) -> None:
        vector, confidence = lex.estimate_with_confidence([])
        assert vector == SonicVector.neutral()
        assert confidence == 0.0

    def test_unknown_tags_dilute_confidence_but_not_the_vector(self) -> None:
        clean_v, clean_c = lex.estimate_with_confidence(["shoegaze"])
        noisy_v, noisy_c = lex.estimate_with_confidence(["shoegaze", "asdf", "qwerty", "zxcv"])
        assert clean_v == noisy_v  # the noise contributes nothing
        assert noisy_c < clean_c  # but it costs us confidence

    def test_confidence_grows_with_recognised_tags(self) -> None:
        one = lex.estimate_with_confidence(["ambient"])[1]
        three = lex.estimate_with_confidence(["ambient", "drone", "minimal"])[1]
        eight = lex.estimate_with_confidence(
            ["ambient", "drone", "minimal", "reverb", "dreamy", "sparse", "tape", "winter"]
        )[1]
        assert 0.0 < one < three < eight <= 1.0

    def test_dimensions_no_tag_mentions_stay_neutral(self) -> None:
        # "reverb" asserts spatiality and nothing else.
        v = lex.estimate_from_tags(["reverb"])
        assert v.spatiality > 0.7
        for dim in ("valence", "energy", "tempo", "acousticness", "density", "grit"):
            assert getattr(v, dim) == pytest.approx(NEUTRAL)


class TestWeightedTags:
    def test_a_weighted_dict_is_accepted(self) -> None:
        v = lex.estimate_from_tags({"shoegaze": 100, "reverb": 40})
        assert v.spatiality > NEUTRAL

    def test_only_the_ratios_matter_not_the_scale(self) -> None:
        # artist.getTopTags uses 0..100; user.getTopTags uses raw counts.
        small = lex.estimate_from_tags({"slowcore": 100, "folk": 50})
        large = lex.estimate_from_tags({"slowcore": 4000, "folk": 2000})
        assert small == large

    def test_a_dominant_tag_pulls_harder_than_a_footnote(self) -> None:
        mostly_kraut = lex.estimate_from_tags({"krautrock": 100, "ambient": 5})
        mostly_ambient = lex.estimate_from_tags({"krautrock": 5, "ambient": 100})
        assert mostly_kraut.tempo > mostly_ambient.tempo
        assert mostly_ambient.spatiality > mostly_kraut.spatiality

    def test_a_uniform_dict_matches_the_equivalent_list(self) -> None:
        as_dict = lex.estimate_from_tags({"dub techno": 10, "reverb": 10})
        as_list_ = lex.estimate_from_tags(["dub techno", "reverb"])
        assert as_dict == as_list_

    def test_duplicate_spellings_are_not_double_counted(self) -> None:
        once = lex.estimate_from_tags(["post rock"])
        thrice = lex.estimate_from_tags(["post rock", "post-rock", "postrock"])
        assert once == thrice

    def test_zero_and_negative_counts_do_not_explode(self) -> None:
        v = lex.estimate_from_tags({"ambient": 0, "drone": 0})
        assert all(0.0 <= getattr(v, d) <= 1.0 for d in SONIC_DIMS)
        assert v.energy < NEUTRAL  # membership still counts

    def test_garbage_counts_are_survived(self) -> None:
        v = lex.estimate_from_tags({"ambient": "not a number", "drone": None})
        assert all(0.0 <= getattr(v, d) <= 1.0 for d in SONIC_DIMS)

    def test_opposed_tags_partially_cancel(self) -> None:
        both = lex.estimate_from_tags(["minimal", "dense"])
        assert abs(both.density - NEUTRAL) < 0.12


class TestTagAffinity:
    def test_an_empty_corridor_admits_everything(self) -> None:
        assert lex.tag_affinity(["krautrock"], []) == 1.0

    def test_direct_overlap_scores_high(self) -> None:
        assert lex.tag_affinity(["krautrock", "motorik"], ["krautrock", "kosmische"]) > 0.7

    def test_a_foreign_tag_set_scores_low(self) -> None:
        assert lex.tag_affinity(["gospel", "soul"], ["black metal", "doom metal"]) < 0.35

    def test_the_right_corridor_beats_the_wrong_one(self) -> None:
        tags = ["krautrock", "motorik", "driving"]
        assert lex.tag_affinity(tags, ["krautrock", "kosmische"]) > lex.tag_affinity(
            tags, ["ambient", "drone"]
        )

    def test_unknown_tags_have_no_affinity(self) -> None:
        assert lex.tag_affinity(["asdfgh"], ["ambient"]) == 0.0

    def test_affinity_is_bounded(self) -> None:
        for corridor in (["ambient"], ["krautrock", "motorik"], ["soul", "gospel", "funk"]):
            for tags in (["ambient"], ["black metal"], ["bossa nova", "summer"]):
                assert 0.0 <= lex.tag_affinity(tags, corridor) <= 1.0


# ===========================================================================
# CLIENT — normalisers and the 200-with-error-body trap
# ===========================================================================
class TestAlwaysAList:
    @pytest.mark.parametrize(
        "raw, expected_len",
        [
            ([{"name": "a"}, {"name": "b"}], 2),  # the many case
            ({"name": "Neu!"}, 1),                # the single-result case
            (None, 0),                            # absent
            ("", 0),                              # Last.fm's empty string
            ({}, 0),                              # empty object
            ([], 0),                              # empty list
        ],
    )
    def test_shapes_collapse_to_a_list(self, raw, expected_len: int) -> None:
        assert len(as_list(raw)) == expected_len

    def test_a_bare_object_is_wrapped_not_iterated(self) -> None:
        # The classic bug: iterating a dict yields its keys.
        assert as_list({"name": "Harmonia", "mbid": "x"}) == [{"name": "Harmonia", "mbid": "x"}]

    def test_empty_strings_inside_a_list_are_dropped(self) -> None:
        assert as_list([{"name": "a"}, "", None]) == [{"name": "a"}]


class TestNumericCoercion:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("1346", 1346),
            (1346, 1346),
            (1346.0, 1346),
            ("1,346", 1346),
            ("1346.7", 1346),
            ({"#text": "42"}, 42),
            ("", None),
            (None, None),
            ("FIXME", None),
            (True, None),  # a bool is not a playcount
        ],
    )
    def test_as_int(self, raw, expected) -> None:
        assert as_int(raw) == expected

    @pytest.mark.parametrize(
        "raw, expected",
        [("0.892", 0.892), (1, 1.0), ("1", 1.0), ("", None), (None, None), ("nope", None)],
    )
    def test_as_float(self, raw, expected) -> None:
        assert as_float(raw) == expected

    def test_as_str_treats_the_empty_string_as_absent(self) -> None:
        assert as_str("") is None
        assert as_str("  ") is None
        assert as_str({"#text": "Neu!"}) == "Neu!"
        assert as_str("Neu!") == "Neu!"

    def test_the_placeholder_star_image_is_not_a_url(self) -> None:
        images = [
            {"#text": "https://lastfm.freetls.fastly.net/i/u/34s/2a96cbd8b46e442fc41c2b86b821562f.png",
             "size": "small"},
            {"#text": "", "size": "large"},
        ]
        assert first_image(images) is None

    def test_a_real_image_is_returned_by_preference(self) -> None:
        images = [
            {"#text": "https://example.test/s.png", "size": "small"},
            {"#text": "https://example.test/xl.png", "size": "extralarge"},
        ]
        assert first_image(images) == "https://example.test/xl.png"


class TestErrorBodyDetection:
    """Last.fm answers failures with HTTP 200 and an error object."""

    def test_a_200_with_an_error_body_raises(self) -> None:
        payload = {"error": 6, "message": "User not found"}
        with pytest.raises(OracleUnavailable) as excinfo:
            client_mod._raise_for_lastfm_error(payload, method="user.getTopArtists")
        assert "User not found" in str(excinfo.value)
        assert "6" in str(excinfo.value)

    def test_rate_limiting_is_reported_as_such(self) -> None:
        payload = {"error": 29, "message": "Rate limit exceeded"}
        with pytest.raises(OracleUnavailable, match="Rate limit exceeded"):
            client_mod._raise_for_lastfm_error(payload, method="tag.getTopTracks")

    def test_a_dead_key_is_flagged_as_not_retryable(self) -> None:
        payload = {"error": 10, "message": "Invalid API key"}
        with pytest.raises(OracleUnavailable, match="not retryable"):
            client_mod._raise_for_lastfm_error(payload, method="artist.getSimilar")

    @pytest.mark.parametrize("payload", [None, "", [], 42])
    def test_non_object_payloads_raise_rather_than_look_empty(self, payload) -> None:
        with pytest.raises(OracleUnavailable):
            client_mod._raise_for_lastfm_error(payload, method="track.getSimilar")

    def test_a_healthy_payload_passes_through_unchanged(self) -> None:
        payload = {"topartists": {"artist": [{"name": "Neu!"}]}}
        assert client_mod._raise_for_lastfm_error(payload, method="user.getTopArtists") is payload

    def test_an_empty_result_set_is_not_an_error(self) -> None:
        payload = {"similarartists": {"artist": [], "@attr": {"artist": "Nobody"}}}
        assert client_mod._raise_for_lastfm_error(payload, method="artist.getSimilar") is payload


class TestResponseParsing:
    """Feed the parsers real response shapes; still no network."""

    def test_top_artists_page_from_a_documented_payload(self) -> None:
        payload = {
            "topartists": {
                "artist": [
                    {
                        "name": "Dream Theater",
                        "playcount": "1346",
                        "mbid": "28503ab7-8bf2-4666-a7bd-2644bfc7cb1d",
                        "url": "https://www.last.fm/music/Dream+Theater",
                        "image": [{"#text": "", "size": "small"}],
                        "@attr": {"rank": "1"},
                    }
                ],
                "@attr": {"user": "RJ", "page": "1", "perPage": "50", "totalPages": "20",
                          "total": "997"},
            }
        }
        page = LastfmClient._artists(payload, "topartists")
        assert [a.name for a in page.artists] == ["Dream Theater"]
        assert page.artists[0].playcount == 1346
        assert page.page.user == "RJ"
        assert page.page.total == 997

    def test_a_single_similar_artist_is_still_a_list(self) -> None:
        payload = {"similarartists": {"artist": {"name": "Sonny & Cher", "match": "1"}}}
        page = LastfmClient._artists(payload, "similarartists")
        assert len(page.artists) == 1
        assert page.artists[0].match == 1.0

    def test_a_0_to_100_match_is_rescaled(self) -> None:
        artist = LastfmArtist.parse({"name": "Harmonia", "match": "87"})
        assert artist is not None and artist.match == pytest.approx(0.87)

    def test_recent_tracks_nowplaying_and_nested_artist(self) -> None:
        payload = {
            "recenttracks": {
                "track": [
                    {
                        "name": "Hallogallo",
                        "artist": {"#text": "Neu!", "mbid": ""},
                        "album": {"#text": "Neu!"},
                        "@attr": {"nowplaying": "true"},
                    }
                ]
            }
        }
        page = LastfmClient._tracks(payload, "recenttracks")
        assert page.tracks[0].artist == "Neu!"
        assert page.tracks[0].album == "Neu!"
        assert page.tracks[0].now_playing is True
        assert page.tracks[0].mbid is None  # "" is absent, not a value

    def test_seconds_are_promoted_to_milliseconds(self) -> None:
        track = LastfmTrack.parse({"name": "Sea", "artist": "Codeine", "duration": "322"})
        assert track is not None and track.duration_ms == 322_000

    def test_millisecond_durations_are_left_alone(self) -> None:
        track = LastfmTrack.parse({"name": "Sea", "artist": "Codeine", "duration": "322000"})
        assert track is not None and track.duration_ms == 322_000

    def test_tags_parse_from_objects_and_bare_strings(self) -> None:
        payload = {"toptags": {"tag": [{"name": "krautrock", "count": "100"}, "motorik"]}}
        tags = LastfmClient._tags(payload, "toptags")
        assert [t.name for t in tags] == ["krautrock", "motorik"]
        assert tags[0].count == 100.0

    def test_malformed_entries_are_skipped_not_fatal(self) -> None:
        payload = {"toptracks": {"track": [{"name": "no artist"}, {"artist": "no title"},
                                           {"name": "Dino", "artist": "Harmonia"}]}}
        page = LastfmClient._tracks(payload, "toptracks")
        assert [t.name for t in page.tracks] == ["Dino"]

    def test_an_invalid_period_is_rejected_locally(self) -> None:
        with pytest.raises(ValueError, match="invalid Last.fm period"):
            LastfmClient._period("last tuesday")
        assert LastfmClient._period("3month") == "3month"
        assert LastfmClient._period(None) is None

    def test_params_always_carry_format_and_key(self) -> None:
        client = LastfmClient(settings=_FakeSettings())
        params = client._params("artist.getSimilar", artist="Neu!", autocorrect=True, mbid=None)
        assert params["format"] == "json"
        assert params["api_key"] == "test-key"
        assert params["autocorrect"] == "1"
        assert "mbid" not in params  # Nones are dropped, not stringified

    def test_a_call_without_a_key_fails_before_any_socket(self) -> None:
        client = LastfmClient(settings=_FakeSettings(key=""))
        with pytest.raises(OracleUnavailable, match="no API key"):
            run(client.call("user.getTopArtists", user="rj"))


class _FakeSettings:
    # backend/app/http.py reads these off Settings on every request.
    http_max_retries = 0
    http_timeout_s = 1.0
    http_connect_timeout_s = 0.5
    http_backoff_base_s = 0.0
    """Minimal settings stand-in. Never used to reach anything."""

    def __init__(self, key: str = "test-key") -> None:
        # Deliberately unroutable. The docstring says this stand-in never
        # reaches anything, but pointing it at the real host meant the
        # degradation tests were quietly making live calls -- and leaving a
        # TLS socket behind to blow up at loop teardown. TEST-NET-1 refuses
        # instantly, which is exactly the "Last.fm is down" path under test.
        self.lastfm_base = "http://192.0.2.1:9/2.0/"
        self.lastfm_api_key = key
        self.lastfm_api_secret = "test-secret"
        self.lastfm_enabled = True
        self.public_host = "bg.netdev.be"

    @property
    def has_lastfm(self) -> bool:
        return bool(self.lastfm_api_key)


class TestBoundedConcurrency:
    def test_parallelism_is_capped(self) -> None:
        state = {"live": 0, "peak": 0}

        async def work(i: int) -> int:
            state["live"] += 1
            state["peak"] = max(state["peak"], state["live"])
            await asyncio.sleep(0.005)
            state["live"] -= 1
            return i

        results = run(gather_bounded([(lambda i=i: work(i)) for i in range(24)], limit=6))
        assert results == list(range(24))
        assert state["peak"] <= 6

    def test_one_failure_does_not_sink_the_batch(self) -> None:
        async def ok() -> str:
            return "fine"

        async def boom() -> str:
            raise OracleUnavailable("upstream sulked")

        results = run(gather_bounded([ok, boom, ok], limit=2))
        assert results[0] == "fine" and results[2] == "fine"
        assert isinstance(results[1], OracleUnavailable)
        assert LastfmClient.successes(results) == ["fine", "fine"]

    def test_an_empty_batch_is_fine(self) -> None:
        assert run(gather_bounded([], limit=6)) == []


# ===========================================================================
# OFFLINE ORACLE
# ===========================================================================
class TestSeedCorpus:
    def test_the_corpus_is_the_promised_size(self) -> None:
        assert 120 <= len(SEED_CORPUS) <= 200

    def test_every_theme_has_a_usable_number_of_tracks(self) -> None:
        for theme in THEMES:
            assert len(by_theme(theme)) >= 12, theme

    def test_no_duplicate_tracks(self) -> None:
        keys = [t.key for t in SEED_CORPUS]
        assert len(keys) == len(set(keys))

    def test_every_corpus_tag_is_understood_by_the_lexicon(self) -> None:
        # If curation adds a tag the lexicon has never heard of, that track
        # silently degrades to neutral. Catch it here instead.
        unknown = sorted(
            {tag for track in SEED_CORPUS for tag in track.tags if lex.canonical_tag(tag) is None}
        )
        assert unknown == []

    def test_tracks_convert_to_the_frozen_contract(self) -> None:
        assert len(OFFLINE_TRACKS) == len(SEED_CORPUS)
        assert all(isinstance(t, Track) for t in OFFLINE_TRACKS)
        assert all(t.estimated is not None for t in OFFLINE_TRACKS)


class TestOfflineOracle:
    def test_it_satisfies_the_protocol(self) -> None:
        assert isinstance(OfflineOracle(), AcousticOracle)
        assert OfflineOracle().name == "offline"

    def test_taste_is_deterministic_per_handle(self) -> None:
        oracle = OfflineOracle()
        first = run(oracle.taste_vector("jpaquay"))
        second = run(oracle.taste_vector("jpaquay"))
        assert first == second

    def test_different_handles_give_different_taste(self) -> None:
        oracle = OfflineOracle()
        a = run(oracle.taste_vector("jpaquay"))
        b = run(oracle.taste_vector("someone-else-entirely"))
        assert a.top_artists != b.top_artists

    def test_taste_declares_itself_as_offline_and_stays_modest(self) -> None:
        taste = run(OfflineOracle().taste_vector("jpaquay"))
        assert taste.source == "offline"
        assert 0.0 < taste.confidence <= 0.45  # synthetic, and says so
        assert taste.scrobble_count == 0

    def test_an_empty_handle_yields_an_empty_taste(self) -> None:
        taste = run(OfflineOracle().taste_vector("   "))
        assert taste.top_artists == []
        assert taste.confidence == 0.0

    @pytest.mark.parametrize("theme", list(THEMES))
    def test_every_theme_yields_a_usable_pool(self, theme: str) -> None:
        oracle = OfflineOracle()
        taste = run(oracle.taste_vector("jpaquay"))
        pool = run(
            oracle.candidates(
                taste=taste,
                seed_tags=offline_theme_tags(theme),
                corridor=GenreCorridor.any(),
                limit=40,
            )
        )
        assert len(pool) >= 20, theme
        assert all(isinstance(t, Track) for t in pool)
        assert len({t.key for t in pool}) == len(pool)  # deduplicated

    def test_no_taste_still_produces_a_pool(self) -> None:
        # The listener has not paired anything. Theme-only mode must work.
        pool = run(
            OfflineOracle().candidates(
                taste=TasteVector.empty(),
                seed_tags=offline_theme_tags("storm_front"),
                corridor=GenreCorridor.any(),
                limit=30,
            )
        )
        assert len(pool) >= 20

    @pytest.mark.parametrize(
        "left, right",
        [("krautrock", "ambient"), ("soul", "heavy"), ("folk", "electronic")],
    )
    def test_different_corridors_produce_genuinely_different_pools(
        self, left: str, right: str
    ) -> None:
        oracle = OfflineOracle()
        taste = run(oracle.taste_vector("jpaquay"))
        seeds = offline_theme_tags("petrichor")

        def pool_for(corridor_id: str) -> set[str]:
            return {
                t.key
                for t in run(
                    oracle.candidates(
                        taste=taste,
                        seed_tags=seeds,
                        corridor=offline_corridor(corridor_id),
                        limit=30,
                    )
                )
            }

        a, b = pool_for(left), pool_for(right)
        assert a and b
        overlap = len(a & b) / len(a | b)
        assert overlap < 0.30, f"{left} vs {right} overlap {overlap:.2f}"

    def test_the_corridor_actually_lands_where_it_should(self) -> None:
        oracle = OfflineOracle()
        taste = run(oracle.taste_vector("jpaquay"))
        pool = run(
            oracle.candidates(
                taste=taste,
                seed_tags=offline_theme_tags("heatwave_cruise"),
                corridor=offline_corridor("krautrock"),
                limit=12,
            )
        )
        artists = {t.artist for t in pool}
        assert artists & {"Neu!", "Harmonia", "Can", "Kraftwerk", "Cluster", "La Dusseldorf",
                          "Popol Vuh"}

    def test_the_per_artist_cap_is_respected(self) -> None:
        oracle = OfflineOracle(per_artist_cap=1)
        taste = run(oracle.taste_vector("jpaquay"))
        pool = run(
            oracle.candidates(
                taste=taste,
                seed_tags=offline_theme_tags("first_frost"),
                corridor=GenreCorridor.any(),
                limit=60,
            )
        )
        artists = [t.artist for t in pool]
        assert len(artists) == len(set(artists))

    def test_the_limit_is_respected(self) -> None:
        oracle = OfflineOracle()
        pool = run(
            oracle.candidates(
                taste=TasteVector.empty(),
                seed_tags=offline_theme_tags("blue_hour"),
                corridor=GenreCorridor.any(),
                limit=7,
            )
        )
        assert len(pool) == 7

    def test_candidates_carry_a_provenance_and_an_explanation(self) -> None:
        oracle = OfflineOracle()
        pool = run(
            oracle.candidates(
                taste=TasteVector.empty(),
                seed_tags=offline_theme_tags("nordic_fog"),
                corridor=offline_corridor("ambient"),
                limit=5,
            )
        )
        for track in pool:
            note = oracle.note_for(track)
            assert note is not None
            assert note.provenance
            assert note.sentence  # a sentence a human can read
            assert any(t.startswith("via:") for t in track.tags)

    def test_estimate_fills_in_a_vector_offline(self) -> None:
        oracle = OfflineOracle()
        bare = Track(title="Hallogallo", artist="Neu!")
        assert bare.estimated is None
        filled = run(oracle.estimate(bare))
        assert filled.estimated is not None
        assert "krautrock" in filled.tags
        assert filled.estimated.density > NEUTRAL  # picked up the corpus tags

    def test_estimate_of_an_unknown_track_is_neutral_not_a_crash(self) -> None:
        filled = run(OfflineOracle().estimate(Track(title="Nothing", artist="Nobody")))
        assert filled.estimated == SonicVector.neutral()

    def test_estimate_from_tags_matches_the_lexicon_exactly(self) -> None:
        oracle = OfflineOracle()
        assert oracle.estimate_from_tags(["shoegaze"]) == lex.estimate_from_tags(["shoegaze"])

    def test_the_pool_is_stable_across_runs(self) -> None:
        oracle = OfflineOracle()
        taste = run(oracle.taste_vector("jpaquay"))
        args = dict(taste=taste, seed_tags=offline_theme_tags("sirocco"),
                    corridor=offline_corridor("global"), limit=15)
        first = [t.key for t in run(oracle.candidates(**args))]
        second = [t.key for t in run(oracle.candidates(**args))]
        assert first == second


# ===========================================================================
# LIVE ORACLE — the parts that need no network
# ===========================================================================
class TestLastfmOracleOffline:
    def test_it_satisfies_the_protocol(self) -> None:
        from app.lastfm.oracle import LastfmOracle

        oracle = LastfmOracle(settings=_FakeSettings())
        assert isinstance(oracle, AcousticOracle)
        assert oracle.name == "lastfm"

    def test_the_lexicon_is_reachable_without_a_socket(self) -> None:
        from app.lastfm.oracle import LastfmOracle

        oracle = LastfmOracle(settings=_FakeSettings())
        assert oracle.estimate_from_tags(["krautrock"]).density > NEUTRAL

    def test_a_dead_api_yields_an_empty_pool_and_a_ledger_note(self) -> None:
        # The local http stand-in cannot reach anything, so every stream fails.
        from app.lastfm.oracle import LastfmOracle

        oracle = LastfmOracle(settings=_FakeSettings())
        pool = run(
            oracle.candidates(
                taste=TasteVector(top_artists=["Neu!", "Harmonia"], confidence=0.5),
                seed_tags=["krautrock"],
                corridor=GenreCorridor.any(),
                limit=20,
            )
        )
        assert pool == []
        assert not oracle.ledger.clean  # it told us why

    def test_a_dead_api_yields_an_empty_taste_rather_than_an_exception(self) -> None:
        from app.lastfm.oracle import LastfmOracle

        oracle = LastfmOracle(settings=_FakeSettings())
        taste = run(oracle.taste_vector("jpaquay"))
        assert taste.top_artists == []
        assert taste.confidence == 0.0
        assert not oracle.ledger.clean

    def test_estimate_degrades_to_the_tags_already_on_the_track(self) -> None:
        from app.lastfm.oracle import LastfmOracle

        oracle = LastfmOracle(settings=_FakeSettings())
        track = Track(title="Hallogallo", artist="Neu!", tags=["krautrock", "motorik"])
        filled = run(oracle.estimate(track))
        assert filled.estimated is not None
        assert filled.estimated.density > NEUTRAL

    def test_the_per_artist_cap_helper(self) -> None:
        from app.lastfm.oracle import _cap_per_artist

        tracks = [Track(title=f"t{i}", artist="Neu!") for i in range(5)]
        assert len(_cap_per_artist(tracks, 2)) == 2


# ===========================================================================
# PAIRING
# ===========================================================================
class TestSignature:
    def test_the_base_string_is_sorted_name_then_value(self) -> None:
        params = {"method": "auth.getSession", "api_key": "K", "token": "T"}
        assert signature_base_string(params) == "api_keyKmethodauth.getSessiontokenT"

    def test_format_and_callback_are_excluded(self) -> None:
        with_extras = {"method": "m", "api_key": "K", "format": "json", "callback": "cb"}
        assert signature_base_string(with_extras) == "api_keyKmethodm"

    def test_the_signature_is_md5_of_base_plus_secret(self) -> None:
        import hashlib

        params = {"method": "auth.getSession", "api_key": "K", "token": "T"}
        expected = hashlib.md5(b"api_keyKmethodauth.getSessiontokenTS").hexdigest()
        assert sign_params(params, secret="S") == expected

    def test_a_missing_secret_is_a_pairing_error_not_a_bad_signature(self) -> None:
        with pytest.raises(PairingError):
            sign_params({"method": "m"}, secret="")


class TestAuthUrl:
    def test_it_points_at_the_right_endpoint_with_key_token_and_cb(self) -> None:
        url = build_auth_url("TOK", "https://bg.netdev.be/auth/lastfm/callback",
                             settings=_FakeSettings())
        assert url.startswith("https://www.last.fm/api/auth/?")
        assert "api_key=test-key" in url
        assert "token=TOK" in url
        assert "cb=https%3A%2F%2Fbg.netdev.be%2Fauth%2Flastfm%2Fcallback" in url

    def test_state_rides_on_the_callback_not_the_auth_url(self) -> None:
        url = build_auth_url("TOK", "https://bg.netdev.be/cb", settings=_FakeSettings(),
                             state="csrf123")
        assert "state%3Dcsrf123" in url  # encoded inside cb=
        assert "&state=" not in url

    def test_no_token_is_refused(self) -> None:
        with pytest.raises(PairingError):
            build_auth_url("  ", "https://bg.netdev.be/cb", settings=_FakeSettings())

    def test_no_api_key_is_refused(self) -> None:
        with pytest.raises(PairingError):
            build_auth_url("TOK", "https://bg.netdev.be/cb", settings=_FakeSettings(key=""))


class TestSecretsDiscipline:
    def test_a_session_never_prints_its_key(self) -> None:
        session = LastfmSession(username="jpaquay", session_key="d41d8cd98f00b204e980")
        assert "d41d8cd98f00b204e980" not in repr(session)
        assert "d41d8cd98f00b204e980" not in str(session)
        assert "***" in repr(session)

    def test_a_ticket_never_prints_its_token(self) -> None:
        ticket = PairingTicket(token="secrettoken12345", callback="https://bg.netdev.be/cb")
        assert "secrettoken12345" not in repr(ticket)

    def test_redact_keeps_almost_nothing(self) -> None:
        assert redact("abcdefghijklmnop").startswith("abcd")
        assert "efghijklmnop" not in redact("abcdefghijklmnop")
        assert redact(None) == "<unset>"
        assert redact("ab") == "**"

    def test_an_empty_session_key_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            LastfmSession(username="jpaquay", session_key="   ")


class TestTokenVault:
    def test_the_in_memory_vault_satisfies_the_protocol(self) -> None:
        from app.lastfm.pairing import TokenVault

        assert isinstance(InMemoryTokenVault(), TokenVault)

    def test_round_trip_and_delete(self) -> None:
        vault = InMemoryTokenVault()
        session = LastfmSession(username="jpaquay", session_key="abc123")

        async def scenario() -> None:
            assert await vault.get("user-1") is None
            await vault.put("user-1", session)
            assert (await vault.get("user-1")) == session
            await vault.delete("user-1")
            await vault.delete("user-1")  # idempotent
            assert await vault.get("user-1") is None

        run(scenario())

    def test_a_stale_ticket_is_refused_before_any_call(self) -> None:
        ticket = PairingTicket(
            token="TOK", callback="https://bg.netdev.be/cb", issued_at=0.0
        )
        assert ticket.expired()
        with pytest.raises(PairingError, match="expired"):
            run(complete_pairing(ticket, "TOK", user_id="u", vault=InMemoryTokenVault()))

    def test_a_mismatched_token_is_refused_before_any_call(self) -> None:
        ticket = PairingTicket(token="TOK", callback="https://bg.netdev.be/cb")
        with pytest.raises(PairingError, match="does not match"):
            run(complete_pairing(ticket, "OTHER", user_id="u", vault=InMemoryTokenVault()))


class TestPairingErrorBodies:
    def test_a_bad_signature_is_explained(self) -> None:
        from app.lastfm.pairing import _raise_for_error

        with pytest.raises(PairingError, match="parameter sorting"):
            _raise_for_error({"error": 13, "message": "Invalid method signature supplied"},
                             step="auth.getSession")

    def test_an_unauthorised_token_is_explained(self) -> None:
        from app.lastfm.pairing import _raise_for_error

        with pytest.raises(PairingError, match="never authorised"):
            _raise_for_error({"error": 4, "message": "Authentication failed"},
                             step="auth.getSession")

    def test_a_healthy_body_passes(self) -> None:
        from app.lastfm.pairing import _raise_for_error

        _raise_for_error({"session": {"name": "jpaquay", "key": "abc"}}, step="auth.getSession")

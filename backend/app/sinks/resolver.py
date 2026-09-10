"""Track -> Spotify URI resolution.

This is the single hardest thing the Spotify sink does, so it lives alone.

Why it is hard: Last.fm's tag lexicon (our recommendation brain since Spotify's
died on 2024-11-27) yields tracks as free text — "Björk – Jóga - Remastered",
"Sufjan Stevens - Chicago (feat. My Brightest Diamond)", "Boards of Canada -
Roygbiv [2004 Reissue]". Spotify's catalogue spells all of those differently and
its ``/search`` relevance ranking will cheerfully hand you a karaoke cover, a
sped-up edit, or a completely unrelated song with a similar name.

The policy here is blunt and deliberate: **a wrong match is worse than no
match.** Every candidate is scored, and anything under the rejection threshold
is reported as unmatched rather than substituted. An M3U line the user can
search by hand beats a playlist quietly containing the wrong song.

Only ``/search`` is used. ``/recommendations``, ``/audio-features`` and friends
have been 403 for non-grandfathered apps since 2024-11-27 — see
``spotify.py::DEAD_ENDPOINTS``.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Final, Iterable, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from ..contracts import Track
from ..http import UpstreamError, get_json

__all__ = [
    "DEFAULT_THRESHOLD",
    "MatchCandidate",
    "TrackResolution",
    "ResolutionResult",
    "SpotifyResolver",
    "normalise_title",
    "normalise_artist",
    "normalise_text",
    "score_candidate",
    "clear_cache",
]

# --------------------------------------------------------------------------- #
# tuning constants
# --------------------------------------------------------------------------- #

#: Overall confidence below which we refuse to match. Tuned deliberately high:
#: the cost of a wrong track in a curated 20-track set is far higher than the
#: cost of one unmatched line in the M3U fallback.
DEFAULT_THRESHOLD: Final[float] = 0.72

#: Even a perfect artist match cannot rescue a title that looks nothing like the
#: request. This is the "never silently substitute a different song" guard.
TITLE_FLOOR: Final[float] = 0.55

#: Likewise: the right title by the wrong artist is a cover, not our track.
ARTIST_FLOOR: Final[float] = 0.45

#: Spotify caps ``/search`` results hard in Developer Mode. Asking for more than
#: this is wasted bandwidth and, in Dev Mode, sometimes a 400.
SEARCH_LIMIT: Final[int] = 10

#: Concurrent in-flight searches. Spotify rate-limits per-app in ~30s windows and
#: Dev Mode apps get a notably thinner allowance, so we stay modest.
DEFAULT_CONCURRENCY: Final[int] = 5

#: Duration agreement within this many ms is treated as a perfect duration match.
_DURATION_TOLERANCE_MS: Final[int] = 4_000

#: Beyond this, duration disagreement is evidence of a different recording
#: (radio edit, extended mix, live version).
_DURATION_MAX_DELTA_MS: Final[int] = 30_000


# --------------------------------------------------------------------------- #
# normalisation
# --------------------------------------------------------------------------- #

# Unicode punctuation that means the same thing as an ASCII character. Spotify
# and Last.fm disagree constantly about which apostrophe is the real one.
_PUNCT_MAP: Final[dict[int, str]] = {
    ord("\u2018"): "'",   # ‘
    ord("\u2019"): "'",   # ’
    ord("\u201a"): "'",
    ord("\u201b"): "'",
    ord("\u02bc"): "'",   # modifier letter apostrophe
    ord("\u201c"): '"',   # “
    ord("\u201d"): '"',   # ”
    ord("\u201e"): '"',
    ord("\u2013"): "-",   # en dash
    ord("\u2014"): "-",   # em dash
    ord("\u2015"): "-",
    ord("\u2212"): "-",   # minus sign
    ord("\u00a0"): " ",   # nbsp
    ord("\u200b"): "",    # zero-width space
    ord("\ufeff"): "",    # bom
    ord("\u2026"): "...",
    ord("\u00b7"): " ",   # middle dot
    ord("\u2027"): " ",
}

# Trailing editorial noise. Matched case-insensitively against a *suffix* after
# a separator (" - ", " / ") or inside brackets. The list is empirical: every
# entry here has burned a real match at some point.
_NOISE_WORDS: Final[tuple[str, ...]] = (
    "remaster",
    "remastered",
    "remastered version",
    "digital remaster",
    "digitally remastered",
    "re-master",
    "reissue",
    "re-issue",
    "deluxe",
    "deluxe edition",
    "expanded edition",
    "anniversary edition",
    "bonus track",
    "bonus",
    "mono",
    "stereo",
    "mono version",
    "stereo version",
    "single version",
    "album version",
    "original version",
    "original mix",
    "radio edit",
    "radio version",
    "explicit",
    "clean",
    "clean version",
    "edit",
    "extended",
    "extended version",
    "instrumental",
    "demo",
    "take 1",
    "alternate take",
    "from the motion picture",
    "original motion picture soundtrack",
    "soundtrack version",
)

# "- Remastered 2011", "- 2011 Remaster", "- Remastered", "/ Mono Version" ...
_SUFFIX_NOISE: Final[re.Pattern[str]] = re.compile(
    r"""
    \s*[-/\u2013\u2014]\s*          # separator
    (?:\d{2,4}\s+)?                 # optional leading year: "2011 Remaster"
    (?P<word>%s)                    # a known noise phrase
    (?:\s+\d{2,4})?                 # optional trailing year: "Remastered 2011"
    \s*$
    """
    % "|".join(re.escape(w) for w in sorted(_NOISE_WORDS, key=len, reverse=True)),
    re.IGNORECASE | re.VERBOSE,
)

# The same noise, but parenthesised/bracketed: "(Remastered 2011)", "[2004 Reissue]"
_BRACKET_NOISE: Final[re.Pattern[str]] = re.compile(
    r"""
    \s*[\(\[\{]\s*
    (?:\d{2,4}\s+)?
    (?:%s)
    (?:\s+\d{2,4})?
    \s*[\)\]\}]
    """
    % "|".join(re.escape(w) for w in sorted(_NOISE_WORDS, key=len, reverse=True)),
    re.IGNORECASE | re.VERBOSE,
)

# "(feat. X)", "[featuring X and Y]", "ft. X" — the featured-artist credit is a
# metadata difference, not a different song.
_FEAT_BRACKETED: Final[re.Pattern[str]] = re.compile(
    r"\s*[\(\[\{]\s*(?:feat|ft|featuring|with|w/)\b[^\)\]\}]*[\)\]\}]",
    re.IGNORECASE,
)
_FEAT_TRAILING: Final[re.Pattern[str]] = re.compile(
    r"\s*[-/,\u2013\u2014]?\s*\b(?:feat|ft|featuring)\.?\s+.*$",
    re.IGNORECASE,
)

# Any remaining parenthetical suffix, stripped only in the *fuzzy* pass — some
# songs genuinely need theirs ("Where Is My Mind?" is fine, but "Rock Lobster
# (Live)" is not the same recording as "Rock Lobster").
_TRAILING_PAREN: Final[re.Pattern[str]] = re.compile(r"\s*[\(\[\{][^\)\]\}]*[\)\]\}]\s*$")

_ARTIST_SPLIT: Final[re.Pattern[str]] = re.compile(
    r"\s*(?:,|&|\+|/|;|\bx\b|\band\b|\bvs\.?\b|\bwith\b|\bfeat\.?\b|\bft\.?\b|\bfeaturing\b)\s*",
    re.IGNORECASE,
)

_WS: Final[re.Pattern[str]] = re.compile(r"\s+")
_NON_ALNUM: Final[re.Pattern[str]] = re.compile(r"[^0-9a-z\s]")

# Leading articles: Spotify has "The Beatles", Last.fm sometimes "Beatles, The".
_TRAILING_ARTICLE: Final[re.Pattern[str]] = re.compile(r"^(.*),\s*(the|a|an)$", re.IGNORECASE)
_LEADING_ARTICLE: Final[re.Pattern[str]] = re.compile(r"^(?:the|a|an)\s+", re.IGNORECASE)


def _strip_diacritics(text: str) -> str:
    """Björk -> Bjork, Sigur Rós -> Sigur Ros, Mötley Crüe -> Motley Crue.

    NFKD then drop combining marks. Note this deliberately does *not* handle
    ø/ð/þ/ł, which have no decomposition; those are mapped explicitly below
    because Scandinavian and Polish acts are not exactly rare in this catalogue.
    """
    special = str.maketrans(
        {
            "ø": "o", "Ø": "O",
            "æ": "ae", "Æ": "AE",
            "œ": "oe", "Œ": "OE",
            "ð": "d", "Ð": "D",
            "þ": "th", "Þ": "Th",
            "ł": "l", "Ł": "L",
            "ß": "ss",
            "đ": "d", "Đ": "D",
            "ı": "i",
        }
    )
    text = text.translate(special)
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalise_text(text: str) -> str:
    """Fold to a comparison-safe form: ASCII-ish, lowercase, alphanumeric+space."""
    if not text:
        return ""
    folded = text.translate(_PUNCT_MAP)
    folded = _strip_diacritics(folded)
    folded = folded.lower()
    folded = _NON_ALNUM.sub(" ", folded)
    return _WS.sub(" ", folded).strip()


def normalise_title(title: str, *, aggressive: bool = False) -> str:
    """Strip editorial noise from a track title.

    ``aggressive`` additionally drops *any* trailing parenthetical, which is
    right for a last-ditch fuzzy query but wrong for scoring (it would make
    "Song (Live)" and "Song" look identical).
    """
    if not title:
        return ""
    text = title.translate(_PUNCT_MAP).strip()

    # Peel repeatedly: "Song - Remastered 2011 - Mono Version" is real.
    for _ in range(4):
        before = text
        text = _BRACKET_NOISE.sub(" ", text)
        text = _SUFFIX_NOISE.sub("", text)
        text = _FEAT_BRACKETED.sub(" ", text)
        if text == before:
            break

    text = _FEAT_TRAILING.sub("", text)
    if aggressive:
        text = _TRAILING_PAREN.sub("", text)
    text = _WS.sub(" ", text).strip(" -–—/·")
    # Never normalise a title out of existence.
    return text or title.strip()


def normalise_artist(artist: str, *, primary_only: bool = True) -> str:
    """Reduce a credit string to its primary artist.

    "Sufjan Stevens & My Brightest Diamond" -> "Sufjan Stevens".
    "Beatles, The" -> "The Beatles" -> "Beatles" once folded.
    """
    if not artist:
        return ""
    text = artist.translate(_PUNCT_MAP).strip()
    text = _FEAT_BRACKETED.sub(" ", text)
    text = _FEAT_TRAILING.sub("", text)

    match = _TRAILING_ARTICLE.match(text.strip())
    if match:
        text = f"{match.group(2)} {match.group(1)}"

    if primary_only:
        parts = [p for p in _ARTIST_SPLIT.split(text) if p and p.strip()]
        if parts:
            text = parts[0]

    return _WS.sub(" ", text).strip(" -–—/·,") or artist.strip()


def _artist_tokens(artist: str) -> set[str]:
    folded = normalise_text(_LEADING_ARTICLE.sub("", normalise_artist(artist)))
    return {t for t in folded.split() if t}


# --------------------------------------------------------------------------- #
# similarity + scoring
# --------------------------------------------------------------------------- #


def _ratio(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _token_overlap(a: str, b: str) -> float:
    """Containment-biased Jaccard. Containment matters because Spotify titles
    are frequently supersets of Last.fm ones, never the reverse."""
    ta = {t for t in a.split() if t}
    tb = {t for t in b.split() if t}
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    if not inter:
        return 0.0
    jaccard = inter / len(ta | tb)
    containment = inter / min(len(ta), len(tb))
    return 0.5 * jaccard + 0.5 * containment


def _text_similarity(a: str, b: str) -> float:
    na, nb = normalise_text(a), normalise_text(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return max(_ratio(na, nb), _token_overlap(na, nb))


def _artist_similarity(wanted: str, candidate_artists: Sequence[str]) -> float:
    """Best score across all credited artists — Spotify lists featured artists
    as separate entries, so the primary may be at any index."""
    wanted_primary = normalise_text(_LEADING_ARTICLE.sub("", normalise_artist(wanted)))
    if not wanted_primary:
        return 0.0

    best = 0.0
    for name in candidate_artists:
        cand = normalise_text(_LEADING_ARTICLE.sub("", normalise_artist(name, primary_only=False)))
        if not cand:
            continue
        if cand == wanted_primary:
            return 1.0
        best = max(best, _ratio(cand, wanted_primary), _token_overlap(cand, wanted_primary))

    # Token-level rescue: "Simon & Garfunkel" vs a Spotify credit list of
    # ["Simon", "Garfunkel"] should not read as a mismatch.
    wanted_tokens = _artist_tokens(wanted)
    cand_tokens: set[str] = set()
    for name in candidate_artists:
        cand_tokens |= _artist_tokens(name)
    if wanted_tokens and cand_tokens:
        inter = len(wanted_tokens & cand_tokens)
        if inter:
            best = max(best, inter / max(len(wanted_tokens), 1) * 0.95)

    return min(best, 1.0)


def _duration_similarity(wanted_ms: int | None, candidate_ms: int | None) -> float | None:
    """``None`` means 'no opinion' — absent duration must not be penalised."""
    if not wanted_ms or not candidate_ms:
        return None
    delta = abs(int(wanted_ms) - int(candidate_ms))
    if delta <= _DURATION_TOLERANCE_MS:
        return 1.0
    if delta >= _DURATION_MAX_DELTA_MS:
        return 0.0
    span = _DURATION_MAX_DELTA_MS - _DURATION_TOLERANCE_MS
    return 1.0 - ((delta - _DURATION_TOLERANCE_MS) / span)


class MatchCandidate(BaseModel):
    """One ``/search`` hit, scored against the requested track."""

    model_config = ConfigDict(frozen=True)

    uri: str
    spotify_id: str
    title: str
    artists: list[str] = Field(default_factory=list)
    album: str | None = None
    duration_ms: int | None = None
    popularity: int | None = None
    explicit: bool = False
    external_url: str | None = None

    title_similarity: float = 0.0
    artist_similarity: float = 0.0
    duration_similarity: float | None = None
    confidence: float = 0.0

    @property
    def display(self) -> str:
        return f"{', '.join(self.artists) or '?'} — {self.title}"


def score_candidate(track: Track, candidate: MatchCandidate) -> MatchCandidate:
    """Return a copy of ``candidate`` with similarity fields populated.

    Weighting: title 0.50 / artist 0.40 / duration 0.10. Duration is only a
    tie-breaker — plenty of legitimate matches differ by a fade-out — but it is
    the single best signal for catching a live version masquerading as a studio
    one, so it is not zero.
    """
    # Compare against both the raw and the de-noised title, keeping the better
    # of the two. Spotify's title may be the noisy one.
    wanted_titles = {track.title, normalise_title(track.title), normalise_title(track.title, aggressive=True)}
    cand_titles = {candidate.title, normalise_title(candidate.title), normalise_title(candidate.title, aggressive=True)}
    title_sim = max(
        _text_similarity(w, c) for w in wanted_titles if w for c in cand_titles if c
    )

    artist_sim = _artist_similarity(track.artist, candidate.artists or [])
    dur_sim = _duration_similarity(track.duration_ms, candidate.duration_ms)

    if dur_sim is None:
        confidence = 0.5556 * title_sim + 0.4444 * artist_sim  # 0.50/0.40 renormalised
    else:
        confidence = 0.50 * title_sim + 0.40 * artist_sim + 0.10 * dur_sim

    # Hard vetoes. These exist so that a very high artist score can never drag a
    # wrong title over the line, and vice versa.
    if title_sim < TITLE_FLOOR or artist_sim < ARTIST_FLOOR:
        confidence = min(confidence, DEFAULT_THRESHOLD - 0.01)

    return candidate.model_copy(
        update={
            "title_similarity": round(title_sim, 4),
            "artist_similarity": round(artist_sim, 4),
            "duration_similarity": None if dur_sim is None else round(dur_sim, 4),
            "confidence": round(max(0.0, min(1.0, confidence)), 4),
        }
    )


# --------------------------------------------------------------------------- #
# result models
# --------------------------------------------------------------------------- #


class TrackResolution(BaseModel):
    """Outcome for exactly one requested track."""

    model_config = ConfigDict(frozen=True)

    key: str
    requested: str
    uri: str | None = None
    spotify_id: str | None = None
    confidence: float = 0.0
    matched_display: str | None = None
    strategy: str = "none"
    rejected_display: str | None = None
    rejected_confidence: float | None = None
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.uri is not None


class ResolutionResult(BaseModel):
    """Aggregate outcome for a batch."""

    model_config = ConfigDict(frozen=True)

    resolutions: list[TrackResolution] = Field(default_factory=list)
    threshold: float = DEFAULT_THRESHOLD
    degraded: list[str] = Field(default_factory=list)

    @property
    def matched(self) -> list[TrackResolution]:
        return [r for r in self.resolutions if r.ok]

    @property
    def unmatched(self) -> list[TrackResolution]:
        return [r for r in self.resolutions if not r.ok]

    @property
    def uris(self) -> list[str]:
        return [r.uri for r in self.resolutions if r.uri]

    @property
    def unmatched_labels(self) -> list[str]:
        return [r.requested for r in self.resolutions if not r.ok]

    @property
    def requested_count(self) -> int:
        return len(self.resolutions)

    @property
    def matched_count(self) -> int:
        return len(self.matched)

    @property
    def mean_confidence(self) -> float:
        scores = [r.confidence for r in self.matched]
        return round(sum(scores) / len(scores), 4) if scores else 0.0

    def confidence_map(self) -> dict[str, float]:
        return {r.key: r.confidence for r in self.resolutions}


# --------------------------------------------------------------------------- #
# per-process cache
# --------------------------------------------------------------------------- #

# Keyed by (track.key, market). Cheap, unbounded-ish, and reset on redeploy —
# which is the correct TTL for "does this song exist on Spotify".
_CACHE: dict[tuple[str, str], TrackResolution] = {}
_CACHE_MAX = 4096


def clear_cache() -> None:
    """Test hook, and a manual escape hatch if the catalogue shifts under us."""
    _CACHE.clear()


# --------------------------------------------------------------------------- #
# the resolver
# --------------------------------------------------------------------------- #


class SpotifyResolver:
    """Resolve ``Track`` -> ``spotify:track:...`` using only ``/search``."""

    def __init__(
        self,
        *,
        api_base: str = "https://api.spotify.com/v1",
        threshold: float = DEFAULT_THRESHOLD,
        concurrency: int = DEFAULT_CONCURRENCY,
        market: str | None = "from_token",
        limit: int = SEARCH_LIMIT,
        use_cache: bool = True,
    ) -> None:
        self._api_base = api_base.rstrip("/")
        self._threshold = float(threshold)
        self._concurrency = max(1, int(concurrency))
        self._market = market
        self._limit = max(1, min(int(limit), 50))
        self._use_cache = use_cache

    # -- query construction -------------------------------------------------- #

    def build_queries(self, track: Track) -> list[tuple[str, str]]:
        """Ordered ``(strategy, query)`` pairs, strictest first.

        Field filters (``track:"..." artist:"..."``) are precise but brittle:
        Spotify's filter matching is closer to exact-phrase than to fuzzy, so a
        single stray "(Remastered)" makes them return nothing at all. Hence the
        cascade.
        """
        raw_title = track.title.strip()
        clean_title = normalise_title(raw_title)
        bare_title = normalise_title(raw_title, aggressive=True)
        raw_artist = track.artist.strip()
        primary_artist = normalise_artist(raw_artist)

        queries: list[tuple[str, str]] = []
        seen: set[str] = set()

        def add(strategy: str, query: str) -> None:
            query = _WS.sub(" ", query).strip()
            if query and query.lower() not in seen:
                seen.add(query.lower())
                queries.append((strategy, query))

        # 1. Strict field filters on the de-noised strings.
        add("strict", f'track:"{_q(clean_title)}" artist:"{_q(primary_artist)}"')
        # 2. Same, but with the title stripped of every parenthetical.
        if bare_title != clean_title:
            add("strict-bare", f'track:"{_q(bare_title)}" artist:"{_q(primary_artist)}"')
        # 3. Field filters on the raw strings — occasionally the "noise" is the
        #    actual title ("Remaster" by Ocean Wisdom is a real song).
        if clean_title != raw_title or primary_artist != raw_artist:
            add("strict-raw", f'track:"{_q(raw_title)}" artist:"{_q(raw_artist)}"')
        # 4. Free text. No filters, let relevance ranking do the work; scoring
        #    still guards the outcome.
        add("fuzzy", f"{clean_title} {primary_artist}")
        # 5. Last ditch: bare title + primary artist, no punctuation at all.
        add("fuzzy-bare", f"{normalise_text(bare_title)} {normalise_text(primary_artist)}")
        return queries

    # -- single track -------------------------------------------------------- #

    async def resolve_track(self, track: Track, *, token: str) -> TrackResolution:
        """Resolve one track. Never raises; failures come back as unmatched."""
        label = track.display
        cache_key = (track.key, self._market or "-")

        # A track that arrived with a URI already attached needs no lookup. This
        # is the common case for anything sourced from /me/top/tracks.
        if track.spotify_uri:
            return TrackResolution(
                key=track.key,
                requested=label,
                uri=track.spotify_uri,
                spotify_id=track.spotify_id,
                confidence=1.0,
                matched_display=label,
                strategy="prefilled",
                reason="URI supplied upstream; no search performed.",
            )
        if track.spotify_id:
            return TrackResolution(
                key=track.key,
                requested=label,
                uri=f"spotify:track:{track.spotify_id}",
                spotify_id=track.spotify_id,
                confidence=1.0,
                matched_display=label,
                strategy="prefilled",
                reason="ID supplied upstream; no search performed.",
            )

        if self._use_cache and cache_key in _CACHE:
            return _CACHE[cache_key]

        best: MatchCandidate | None = None
        best_strategy = "none"
        transport_error: str | None = None

        for strategy, query in self.build_queries(track):
            try:
                candidates = await self._search(query, token=token)
            except UpstreamError as exc:
                # 403 here is either the Dev Mode cap or the deprecation cliff.
                # Either way, further queries for this track are pointless and
                # further queries for *any* track are probably pointless too —
                # re-raise so the caller can abort the batch cleanly.
                if exc.is_deprecation or exc.status in (401, 429):
                    raise
                transport_error = f"{exc.service} {exc.status or '?'}"
                continue
            except Exception as exc:  # pragma: no cover - belt and braces
                transport_error = type(exc).__name__
                continue

            for candidate in candidates:
                scored = score_candidate(track, candidate)
                if best is None or scored.confidence > best.confidence:
                    best, best_strategy = scored, strategy

            # An unambiguous strict hit ends the cascade — no reason to spend
            # rate-limit budget confirming what we already know.
            if best is not None and best.confidence >= 0.93:
                break

        resolution = self._decide(track, best, best_strategy, transport_error)
        if self._use_cache:
            if len(_CACHE) >= _CACHE_MAX:
                _CACHE.clear()
            _CACHE[cache_key] = resolution
        return resolution

    def _decide(
        self,
        track: Track,
        best: MatchCandidate | None,
        strategy: str,
        transport_error: str | None,
    ) -> TrackResolution:
        label = track.display

        if best is None:
            reason = (
                f"No Spotify search result at all ({transport_error})."
                if transport_error
                else "Spotify's catalogue returned no candidate for any query variant."
            )
            return TrackResolution(key=track.key, requested=label, strategy=strategy, reason=reason)

        if best.confidence < self._threshold:
            # The whole point of the module. We *found* something and we are
            # throwing it away, loudly.
            return TrackResolution(
                key=track.key,
                requested=label,
                confidence=0.0,
                strategy=strategy,
                rejected_display=best.display,
                rejected_confidence=best.confidence,
                reason=(
                    f"Best candidate '{best.display}' scored "
                    f"{best.confidence:.2f} < {self._threshold:.2f} "
                    f"(title {best.title_similarity:.2f}, artist {best.artist_similarity:.2f}); "
                    "rejected rather than substituted."
                ),
            )

        return TrackResolution(
            key=track.key,
            requested=label,
            uri=best.uri,
            spotify_id=best.spotify_id,
            confidence=best.confidence,
            matched_display=best.display,
            strategy=strategy,
            reason=(
                f"Matched via {strategy} at {best.confidence:.2f} "
                f"(title {best.title_similarity:.2f}, artist {best.artist_similarity:.2f})."
            ),
        )

    # -- batch --------------------------------------------------------------- #

    async def resolve(self, tracks: Iterable[Track], *, token: str) -> ResolutionResult:
        """Resolve many tracks with bounded concurrency, preserving input order."""
        ordered = list(tracks)
        if not ordered:
            return ResolutionResult(threshold=self._threshold)

        semaphore = asyncio.Semaphore(self._concurrency)
        degraded: list[str] = []

        async def one(track: Track) -> TrackResolution | BaseException:
            async with semaphore:
                try:
                    return await self.resolve_track(track, token=token)
                except BaseException as exc:  # noqa: BLE001 - captured, not swallowed
                    return exc

        results = await asyncio.gather(*(one(t) for t in ordered))

        resolutions: list[TrackResolution] = []
        fatal: UpstreamError | None = None
        for track, outcome in zip(ordered, results, strict=True):
            if isinstance(outcome, TrackResolution):
                resolutions.append(outcome)
                continue
            if isinstance(outcome, UpstreamError):
                fatal = fatal or outcome
                resolutions.append(
                    TrackResolution(
                        key=track.key,
                        requested=track.display,
                        reason=f"Search aborted: {outcome.service} HTTP {outcome.status}.",
                    )
                )
            else:
                resolutions.append(
                    TrackResolution(
                        key=track.key,
                        requested=track.display,
                        reason=f"Search failed: {type(outcome).__name__}.",
                    )
                )

        if fatal is not None:
            if fatal.is_deprecation:
                degraded.append(
                    "Spotify /search returned "
                    f"{fatal.status}: Developer Mode is capped at 5 users since the "
                    "Feb-2026 migration, and the app owner must hold Premium. "
                    "Resolution abandoned."
                )
            elif fatal.status == 429:
                degraded.append("Spotify rate-limited the search batch; resolution incomplete.")
            elif fatal.status == 401:
                degraded.append("Spotify access token rejected during search; re-pair required.")

        return ResolutionResult(
            resolutions=resolutions, threshold=self._threshold, degraded=degraded
        )

    # -- transport ----------------------------------------------------------- #

    async def _search(self, query: str, *, token: str) -> list[MatchCandidate]:
        params: dict[str, Any] = {"q": query, "type": "track", "limit": self._limit}
        if self._market:
            params["market"] = self._market

        payload = await get_json(
            f"{self._api_base}/search",
            service="spotify",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        return _parse_search(payload)


def _q(text: str) -> str:
    """Escape a value for inclusion in a quoted Spotify field filter.

    Spotify's query grammar has no escape sequence for a double quote inside a
    quoted term, so the only safe move is to drop them.
    """
    return text.replace('"', " ").replace("\\", " ").strip()


def _parse_search(payload: Any) -> list[MatchCandidate]:
    """Tolerant parse of ``/search?type=track``. Unknown shape -> no candidates."""
    if not isinstance(payload, Mapping):
        return []
    tracks = payload.get("tracks")
    items = tracks.get("items") if isinstance(tracks, Mapping) else None
    if not isinstance(items, list):
        return []

    out: list[MatchCandidate] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        track_id = item.get("id")
        uri = item.get("uri") or (f"spotify:track:{track_id}" if track_id else None)
        title = item.get("name")
        if not uri or not track_id or not title:
            continue
        artists = [
            str(a.get("name"))
            for a in (item.get("artists") or [])
            if isinstance(a, Mapping) and a.get("name")
        ]
        album_obj = item.get("album")
        album = album_obj.get("name") if isinstance(album_obj, Mapping) else None
        ext = item.get("external_urls")
        external_url = ext.get("spotify") if isinstance(ext, Mapping) else None
        duration = item.get("duration_ms")

        out.append(
            MatchCandidate(
                uri=str(uri),
                spotify_id=str(track_id),
                title=str(title),
                artists=artists,
                album=str(album) if album else None,
                duration_ms=int(duration) if isinstance(duration, (int, float)) else None,
                popularity=item.get("popularity") if isinstance(item.get("popularity"), int) else None,
                explicit=bool(item.get("explicit", False)),
                external_url=str(external_url) if external_url else None,
            )
        )
    return out

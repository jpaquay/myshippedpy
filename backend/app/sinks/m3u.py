"""M3U playlist sink — BAROGROOVE's guaranteed-delivery surface.

This is not a consolation prize. Spotify Dev Mode is capped at 5 users (Feb-2026
migration) and its recommendation brain has been dead since 2024-11-27, so for
the sixth person who ever tries the demo *this file is the product*. It must be
openable in a text editor and explain, in plain language, why these tracks and
why this sky.

Format notes:
  * ``#EXTM3U`` header, then ``#EXTINF:<seconds>,<Artist> - <Title>`` per entry.
    ``#EXTINF`` duration is SECONDS (not ms) and ``-1`` when unknown — players
    treat a bogus positive number far worse than an honest -1.
  * ``#PLAYLIST:<title>`` is the de-facto title directive understood by VLC,
    foobar2000 and friends.
  * Everything else we emit is a ``#`` comment. Unknown comments are ignored by
    every player in the wild, which is exactly what makes them a safe carrier
    for the rationale.

This sink never performs I/O and never raises. ``available()`` is unconditionally
true; that is the whole point of it.
"""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Final, Iterable, Sequence

from pydantic import BaseModel, ConfigDict, Field

from ..contracts import Playlist, ScoredTrack, SinkKind, SinkResult, Track

__all__ = [
    "M3USink",
    "M3UExport",
    "render_m3u",
    "render_json",
    "render_csv",
    "build_export",
]

# Width at which comment prose is hard-wrapped. 78 keeps the file readable in a
# terminal without turning long rationale bodies into a single runaway line.
_WRAP: Final[int] = 78

_BANNER: Final[str] = "BAROGROOVE — your sky has a soundtrack"

# Characters that are illegal or merely obnoxious in filenames across the three
# desktop platforms plus Android.
_FILENAME_BAD: Final[re.Pattern[str]] = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


class M3UExport(BaseModel):
    """Everything the Flutter client needs to offer 'save' / 'share' locally.

    The client gets all three renderings in one round trip; deciding which to
    hand to the OS share sheet is a UI concern, not a backend one.
    """

    model_config = ConfigDict(frozen=True)

    filename_stem: str
    m3u: str
    json_payload: str
    csv_payload: str
    track_count: int
    duration_ms: int

    @property
    def m3u_filename(self) -> str:
        return f"{self.filename_stem}.m3u8"

    @property
    def json_filename(self) -> str:
        return f"{self.filename_stem}.json"

    @property
    def csv_filename(self) -> str:
        return f"{self.filename_stem}.csv"


# --------------------------------------------------------------------------- #
# small text helpers
# --------------------------------------------------------------------------- #


def _wrap(text: str, width: int = _WRAP) -> list[str]:
    """Greedy wrap that never splits a word and never returns an empty list."""
    words = str(text).split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        if len(current) + 1 + len(word) <= width:
            current = f"{current} {word}"
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _comment_block(label: str, text: str) -> list[str]:
    """``# LABEL: first line`` then hanging-indented continuations."""
    lines = _wrap(text, _WRAP - len(label) - 4)
    head = f"#   {label}: {lines[0]}"
    pad = " " * (len(label) + 6)
    return [head] + [f"#{pad}{line}" for line in lines[1:]]


def _bullet_block(text: str) -> list[str]:
    """A dashed list item, hanging-indented. Distinct from ``_comment_block``
    because a bullet takes no ``label:`` prefix."""
    lines = _wrap(text, _WRAP - 6)
    return [f"#   - {lines[0]}"] + [f"#     {line}" for line in lines[1:]]


def _sanitise_comment(text: Any) -> str:
    """A comment may not contain a newline; a newline would end the comment and
    the remainder would be parsed as a resource path. Flatten aggressively."""
    return re.sub(r"\s+", " ", str(text)).strip()


def _slug(text: str, *, fallback: str = "barogroove") -> str:
    folded = unicodedata.normalize("NFKD", text)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    folded = re.sub(r"[^A-Za-z0-9]+", "-", folded).strip("-").lower()
    return folded or fallback


def _safe_filename(text: str) -> str:
    cleaned = _FILENAME_BAD.sub("_", text).strip(" .")
    return cleaned or "track"


def _extinf_seconds(track: Track) -> int:
    """M3U wants whole seconds. -1 is the documented 'unknown' sentinel."""
    ms = track.duration_ms
    if not ms or ms <= 0:
        return -1
    return int(round(ms / 1000.0))


def _resource_line(track: Track) -> str:
    """The locator that follows each ``#EXTINF``.

    Preference order is deliberate:
      1. ``spotify:track:...`` — the desktop client resolves these natively.
      2. the Last.fm URL — at least it opens something authoritative.
      3. ``Artist - Title.mp3`` — a relative filename, which is what a local
         library player (Rhythmbox, foobar2000, Plex) will happily match against
         its own collection. Better than a dead link.
    """
    if track.spotify_uri:
        return track.spotify_uri
    if track.spotify_id:
        return f"spotify:track:{track.spotify_id}"
    if track.lastfm_url:
        return track.lastfm_url
    return f"{_safe_filename(track.artist)} - {_safe_filename(track.title)}.mp3"


def _fmt_duration(ms: int) -> str:
    total = max(0, int(ms // 1000))
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{seconds:02d}s"
    return f"{minutes}m{seconds:02d}s"


def _sonic_summary(playlist: Playlist) -> str:
    target = playlist.sonic_target
    parts: list[str] = []
    for field in target.__class__.model_fields:
        value = getattr(target, field, None)
        if isinstance(value, bool):
            parts.append(f"{field}={'yes' if value else 'no'}")
        elif isinstance(value, (int, float)):
            parts.append(f"{field}={float(value):.2f}")
        elif value is not None:
            parts.append(f"{field}={value}")
    return ", ".join(parts) or "(no sonic target recorded)"


def _sky_summary(playlist: Playlist) -> str:
    sky = playlist.sky
    parts: list[str] = []
    for field in sky.__class__.model_fields:
        value = getattr(sky, field, None)
        if isinstance(value, bool):
            parts.append(f"{field}={'yes' if value else 'no'}")
        elif isinstance(value, float):
            parts.append(f"{field}={value:g}")
        elif value is not None:
            parts.append(f"{field}={value}")
    return ", ".join(parts) or "(no sky vector recorded)"


# --------------------------------------------------------------------------- #
# renderers
# --------------------------------------------------------------------------- #


def render_m3u(playlist: Playlist, *, include_rationale: bool = True) -> str:
    """Render an extended M3U (UTF-8, LF endings) for ``playlist``."""
    out: list[str] = ["#EXTM3U"]
    title = _sanitise_comment(playlist.title) or "BAROGROOVE playlist"
    out.append(f"#PLAYLIST:{title}")

    if include_rationale:
        out.extend(_header_comments(playlist))

    for scored in playlist.tracks:
        out.extend(_track_lines(scored))

    out.append("#")
    out.append("# end of playlist")
    return "\n".join(out) + "\n"


def _header_comments(playlist: Playlist) -> list[str]:
    rationale = playlist.rationale
    created = playlist.created_at
    if isinstance(created, datetime):
        stamp = created.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    else:  # defensive: contracts says datetime, but never trust a render path
        stamp = str(created)

    out: list[str] = [
        "#",
        f"# {_BANNER}",
        "# " + "=" * (_WRAP - 2),
        "#",
    ]

    if playlist.subtitle:
        out.append(f"# {_sanitise_comment(playlist.subtitle)}")
        out.append("#")

    out.append("# WHY THIS PLAYLIST EXISTS")
    out.extend(_comment_block("headline", _sanitise_comment(rationale.headline)))
    out.extend(_comment_block("body", _sanitise_comment(rationale.body)))
    if rationale.taste_note:
        out.extend(_comment_block("taste", _sanitise_comment(rationale.taste_note)))
    out.extend(_comment_block("confidence", f"{rationale.confidence:.2f}"))
    out.append("#")

    out.append("# SKY READING")
    for line in rationale.sky_reading or ["(none recorded)"]:
        out.extend(_bullet_block(_sanitise_comment(line)))
    out.extend(_comment_block("sky vector", _sky_summary(playlist)))
    if playlist.coordinates is not None:
        coords = playlist.coordinates
        label = getattr(coords, "label", None) or "unnamed"
        # The frozen contract spells these `latitude`/`longitude`, not lat/lon.
        lat = float(getattr(coords, "latitude", 0.0) or 0.0)
        lon = float(getattr(coords, "longitude", 0.0) or 0.0)
        out.extend(
            _comment_block(
                "location",
                f"{label} ({lat:.4f}, {lon:.4f})",
            )
        )
    out.append("#")

    out.append("# SONIC MOVES")
    for line in rationale.sonic_moves or ["(none recorded)"]:
        out.extend(_bullet_block(_sanitise_comment(line)))
    out.extend(_comment_block("sonic target", _sonic_summary(playlist)))
    out.append("#")

    out.append("# CORRIDOR")
    out.extend(_comment_block("theme", _sanitise_comment(playlist.theme_id)))
    out.extend(_comment_block("genre", _sanitise_comment(playlist.genre_id)))
    out.append("#")

    if rationale.degraded:
        out.append("# DEGRADED SUBSYSTEMS (this playlist was built with less than full data)")
        for line in rationale.degraded:
            out.extend(_bullet_block("! " + _sanitise_comment(line)))
        out.append("#")

    out.append("# PROVENANCE")
    out.extend(_comment_block("playlist id", _sanitise_comment(playlist.id)))
    out.extend(_comment_block("generated", stamp))
    out.extend(_comment_block("tracks", str(len(playlist.tracks))))
    out.extend(_comment_block("duration", _fmt_duration(playlist.duration_ms)))
    out.append("#")
    out.append("# " + "=" * (_WRAP - 2))
    out.append("#")
    return out


def _track_lines(scored: ScoredTrack) -> list[str]:
    track = scored.track
    lines: list[str] = []

    # Per-track annotation: role, position and the one-line 'why'. A curious
    # listener reading the file learns the shape of the set, not just its
    # contents.
    role = _sanitise_comment(scored.role)
    annotation = f"# [{scored.position:02d}] {role}"
    if scored.score:
        annotation += f" · score {scored.score:.3f}"
    lines.append(annotation)
    if scored.why:
        lines.extend(_comment_block("why", _sanitise_comment(scored.why)))
    if track.tags:
        lines.extend(_comment_block("tags", ", ".join(track.tags[:8])))

    # "Artist - Title" with a plain hyphen: the EXTINF convention predates the
    # em dash Track.display uses, and some parsers split on " - " exactly.
    label = f"{_sanitise_comment(track.artist)} - {_sanitise_comment(track.title)}"
    lines.append(f"#EXTINF:{_extinf_seconds(track)},{label}")
    lines.append(_resource_line(track))
    return lines


def _track_record(scored: ScoredTrack) -> dict[str, Any]:
    track = scored.track
    return {
        "position": scored.position,
        "role": scored.role,
        "artist": track.artist,
        "title": track.title,
        "album": track.album,
        "duration_ms": track.duration_ms,
        "duration_s": None if not track.duration_ms else round(track.duration_ms / 1000),
        "spotify_uri": track.spotify_uri,
        "spotify_id": track.spotify_id,
        "mbid": track.mbid,
        "lastfm_url": track.lastfm_url,
        "tags": list(track.tags),
        "listeners": track.listeners,
        "playcount": track.playcount,
        "score": scored.score,
        "sonic_distance": scored.sonic_distance,
        "taste_affinity": scored.taste_affinity,
        "corridor_fit": scored.corridor_fit,
        "novelty": scored.novelty,
        "why": scored.why,
        "key": track.key,
    }


def render_json(playlist: Playlist, *, indent: int = 2) -> str:
    """A structured export for the Flutter client: the same information as the
    M3U comments, but machine-readable so the app can render its own 'why' UI
    without re-parsing comments."""
    rationale = playlist.rationale
    created = playlist.created_at
    doc: dict[str, Any] = {
        "format": "barogroove.playlist.v1",
        "id": playlist.id,
        "title": playlist.title,
        "subtitle": playlist.subtitle,
        "theme_id": playlist.theme_id,
        "genre_id": playlist.genre_id,
        "created_at": created.isoformat() if isinstance(created, datetime) else str(created),
        "user_id": playlist.user_id,
        "track_count": len(playlist.tracks),
        "duration_ms": playlist.duration_ms,
        "duration_human": _fmt_duration(playlist.duration_ms),
        "sky": playlist.sky.model_dump(mode="json"),
        "sonic_target": playlist.sonic_target.model_dump(mode="json"),
        "coordinates": (
            playlist.coordinates.model_dump(mode="json")
            if playlist.coordinates is not None
            else None
        ),
        "rationale": {
            "headline": rationale.headline,
            "body": rationale.body,
            "sky_reading": list(rationale.sky_reading),
            "sonic_moves": list(rationale.sonic_moves),
            "taste_note": rationale.taste_note,
            "confidence": rationale.confidence,
            "degraded": list(rationale.degraded),
        },
        "tracks": [_track_record(st) for st in playlist.tracks],
    }
    return json.dumps(doc, indent=indent, ensure_ascii=False, sort_keys=False)


_CSV_COLUMNS: Final[tuple[str, ...]] = (
    "position",
    "role",
    "artist",
    "title",
    "album",
    "duration_s",
    "spotify_uri",
    "tags",
    "score",
    "why",
)


def render_csv(playlist: Playlist) -> str:
    """CSV for the spreadsheet-brained. CRLF per RFC 4180."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(_CSV_COLUMNS)
    for scored in playlist.tracks:
        record = _track_record(scored)
        record["tags"] = "; ".join(record["tags"] or [])
        writer.writerow([record.get(col, "") if record.get(col) is not None else "" for col in _CSV_COLUMNS])
    return buffer.getvalue()


def build_export(playlist: Playlist) -> M3UExport:
    """All three renderings plus a filesystem-safe stem, in one shot."""
    stem = _slug(f"barogroove-{playlist.title}") or "barogroove-playlist"
    return M3UExport(
        filename_stem=stem[:96],
        m3u=render_m3u(playlist),
        json_payload=render_json(playlist),
        csv_payload=render_csv(playlist),
        track_count=len(playlist.tracks),
        duration_ms=playlist.duration_ms,
    )


# --------------------------------------------------------------------------- #
# the sink
# --------------------------------------------------------------------------- #


class M3USink:
    """``PlaylistSink`` that renders to a string. Always available, never fails.

    There is no I/O here on purpose: the route hands ``SinkResult.payload`` to
    the client as a download. Nothing about this sink can 403, rate-limit, or
    require a Premium subscription, which is why the fallthrough policy in
    ``registry.py`` can treat it as an unconditional floor.
    """

    kind: SinkKind = "m3u"

    def __init__(self, *, include_rationale: bool = True) -> None:
        self._include_rationale = include_rationale

    async def available(self, user_id: str | None) -> bool:  # noqa: ARG002
        # Unconditionally true. If this ever returns False the demo has no floor
        # left to stand on.
        return True

    async def write(
        self, playlist: Playlist, *, user_id: str | None = None
    ) -> SinkResult:
        requested = len(playlist.tracks)
        try:
            body = render_m3u(playlist, include_rationale=self._include_rationale)
        except Exception as exc:  # pragma: no cover - defensive floor
            # Even here we degrade: a minimal but valid M3U beats an exception
            # bubbling into the request handler.
            body = _minimal_m3u(playlist.plain_tracks())
            return SinkResult(
                kind=self.kind,
                ok=True,
                matched=requested,
                requested=requested,
                payload=body,
                message=(
                    "M3U written in reduced form; the annotated renderer failed "
                    f"({type(exc).__name__}). Track list is intact."
                ),
            )

        return SinkResult(
            kind=self.kind,
            ok=True,
            external_id=playlist.id,
            external_url=None,
            matched=requested,
            requested=requested,
            unmatched=[],
            payload=body,
            message=(
                f"Wrote an annotated M3U with {requested} track"
                f"{'' if requested == 1 else 's'} "
                f"({_fmt_duration(playlist.duration_ms)}). "
                "Open it in any player, or in a text editor to read the reasoning."
            ),
        )

    def export(self, playlist: Playlist) -> M3UExport:
        """Convenience passthrough for the Flutter export endpoint."""
        return build_export(playlist)


def _minimal_m3u(tracks: Iterable[Track] | Sequence[Track]) -> str:
    lines = ["#EXTM3U"]
    for track in tracks:
        lines.append(
            f"#EXTINF:{_extinf_seconds(track)},"
            f"{_sanitise_comment(track.artist)} - {_sanitise_comment(track.title)}"
        )
        lines.append(_resource_line(track))
    return "\n".join(lines) + "\n"

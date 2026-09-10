"""Genre corridors: the second, orthogonal knob.

Theme answers *what today is*. Corridor answers *what shelf we are shopping on*.
Keeping those two separate is the headline feature of the whole app, because it
is what makes the crossing interesting:

    petrichor x krautrock   -> Neu! at half speed, tape hiss, a motorik pulse
                               that never quite arrives at its own downbeat
    petrichor x ambient     -> Eno's "On Land", nothing but room tone and dread
    petrichor x spiritual jazz -> late Alice Coltrane, harp and reverb and a
                               storm somewhere over the next county

Same sky, same theme, same nine numbers going in. Three genuinely different
records coming out. A single "mood" slider cannot produce that, and an app that
only has themes will serve every user the same eight playlists forever.

MECHANICS
=========
A corridor is an ``anchor`` (where this music lives in sonic space) plus a
``width`` (how far it will let you roam). Width is a **radius**, in the same
units as :meth:`SonicVector.distance`:

* ``width = 1.0``  -- no constraint at all. This is what ``any`` is.
* ``width = 0.40`` -- a broad church. Indie rock contains multitudes and most
  of them are fine.
* ``width = 0.26`` -- doctrinaire. Drone is drone. If your sky wants 140 BPM,
  drone is going to lose that argument, and it should.

:func:`~.target.build_target` applies width twice: a soft pull toward the anchor
scaled by ``1 - width``, then a hard projection guaranteeing the final target
sits inside the ball. Narrow corridors therefore dominate; wide ones only
suggest. That asymmetry is deliberate -- picking "drone" is a much stronger
statement of intent than picking "indie rock", and the model should believe you.

The tags are real Last.fm community tags, spelled the way people on Last.fm
actually spell them, because they are going straight into ``tag.getTopTracks``
and a tidy invented taxonomy would return nothing at all.
"""

from __future__ import annotations

from ..contracts import GenreCorridor, SonicVector

__all__ = ["CORRIDORS", "get_corridor", "list_corridors", "corridor_ids"]


def _corridor(
    corridor_id: str,
    name: str,
    *,
    tags: list[str],
    width: float,
    description: str,
    valence: float,
    energy: float,
    tempo: float,
    acousticness: float,
    density: float,
    grit: float,
    spatiality: float,
) -> GenreCorridor:
    """Build a corridor with a keyword-spelled anchor, so a reader can audit it."""
    return GenreCorridor(
        id=corridor_id,
        name=name,
        tags=tags,
        anchor=SonicVector(
            valence=valence,
            energy=energy,
            tempo=tempo,
            acousticness=acousticness,
            density=density,
            grit=grit,
            spatiality=spatiality,
        ),
        width=width,
        description=description,
    )


_ANY = GenreCorridor.any()

_KRAUTROCK = _corridor(
    "krautrock",
    "Krautrock",
    tags=["krautrock", "motorik", "kosmische", "experimental", "psychedelic rock", "german"],
    width=0.38,
    description=(
        "Repetition as a destination rather than a shortcut. A pulse that does not "
        "develop, will not resolve, and is entirely comfortable about it."
    ),
    valence=0.50, energy=0.66, tempo=0.58,  # ~130 BPM: the motorik cruise
    acousticness=0.34, density=0.58, grit=0.52, spatiality=0.50,
)

_AMBIENT = _corridor(
    "ambient",
    "Ambient",
    tags=["ambient", "atmospheric", "drone", "instrumental", "electronic", "chillout"],
    width=0.32,
    description=(
        "Music as weather in its own right -- as ignorable as it is interesting. "
        "Near-zero event density, near-total room."
    ),
    valence=0.48, energy=0.16, tempo=0.22,  # ~86 BPM, and often no pulse at all
    acousticness=0.40, density=0.16, grit=0.22, spatiality=0.88,
)

_SHOEGAZE = _corridor(
    "shoegaze",
    "Shoegaze",
    tags=["shoegaze", "dream pop", "noise pop", "4ad", "ethereal", "alternative"],
    width=0.34,
    description=(
        "Enormous and completely uninterested in you. Melody buried three layers down "
        "under guitars doing something no guitar was designed to do."
    ),
    valence=0.42, energy=0.62, tempo=0.48,
    acousticness=0.22, density=0.70, grit=0.82,  # highest grit in the set, by design
    spatiality=0.86,
)

_POST_PUNK = _corridor(
    "post-punk",
    "Post-punk",
    tags=["post-punk", "new wave", "coldwave", "gothic rock", "80s", "dark"],
    width=0.36,
    description=(
        "Angular, literate, played by people who could not play a year ago and turned "
        "that into a method. High treble, high anxiety, bass carrying the tune."
    ),
    valence=0.36, energy=0.70, tempo=0.58,
    acousticness=0.26, density=0.58, grit=0.62, spatiality=0.48,
)

_DUB_TECHNO = _corridor(
    "dub-techno",
    "Dub techno",
    tags=["dub techno", "minimal techno", "dub", "basic channel", "detroit techno", "techno"],
    width=0.30,
    description=(
        "One chord, a delay line, and forty minutes. The genre that understood before "
        "anyone else that reverb is a compositional element and not a finishing touch."
    ),
    valence=0.44, energy=0.52, tempo=0.52,  # ~122 BPM and it does not move
    acousticness=0.12,  # the most synthetic corridor here
    density=0.40, grit=0.44, spatiality=0.84,
)

_SPIRITUAL_JAZZ = _corridor(
    "spiritual-jazz",
    "Spiritual jazz",
    tags=["spiritual jazz", "jazz", "modal jazz", "free jazz", "soul jazz", "impulse"],
    width=0.34,
    description=(
        "Modal, searching, played like it is going somewhere specific. Harp and horns "
        "and a rhythm section three seconds ahead of everyone in the room."
    ),
    valence=0.62, energy=0.58, tempo=0.52,
    acousticness=0.82, density=0.72,  # busiest corridor: a lot of people playing at once
    grit=0.34, spatiality=0.60,
)

_FOLK = _corridor(
    "folk",
    "Folk",
    tags=["folk", "acoustic", "singer-songwriter", "freak folk", "americana", "traditional"],
    width=0.32,
    description=(
        "One or two people, wooden instruments, a room with a floor you can hear. The "
        "oldest delivery mechanism for bad news there is."
    ),
    valence=0.52, energy=0.32, tempo=0.38,
    acousticness=0.92,  # the acoustic pole of the whole space
    density=0.34, grit=0.24, spatiality=0.40,
)

_SOUL = _corridor(
    "soul",
    "Soul",
    tags=["soul", "northern soul", "funk", "rnb", "motown", "70s soul"],
    width=0.34,
    description=(
        "Written to be sung at somebody. The most reliably high-valence corridor here, "
        "which does not make it a happy one -- read the lyrics."
    ),
    valence=0.70,  # highest valence anchor in the set
    energy=0.60, tempo=0.48, acousticness=0.68, density=0.62, grit=0.40, spatiality=0.42,
)

_INDIE_ROCK = _corridor(
    "indie-rock",
    "Indie rock",
    tags=["indie rock", "indie", "alternative rock", "lo-fi", "90s", "guitar"],
    width=0.44,  # the widest real corridor; the label has meant six things since 1986
    description=(
        "A distribution model that became a sound and then stopped meaning either. "
        "Broad on purpose: this one lets the sky do most of the talking."
    ),
    valence=0.56, energy=0.64, tempo=0.56, acousticness=0.42, density=0.60,
    grit=0.52, spatiality=0.42,
)

_DRONE = _corridor(
    "drone",
    "Drone & minimalism",
    tags=["drone", "minimalism", "experimental", "avant-garde", "modern classical", "instrumental"],
    width=0.26,  # the narrowest. Drone does not negotiate
    description=(
        "One idea, examined at length, until the overtones start doing the work. "
        "Requires either total attention or none whatsoever."
    ),
    valence=0.44, energy=0.14, tempo=0.16,  # ~79 BPM where a tempo exists at all
    acousticness=0.54, density=0.10,  # the sparsest anchor in the set
    grit=0.34, spatiality=0.90,  # and the largest room
)

_HIP_HOP = _corridor(
    "hip-hop",
    "Hip hop",
    tags=["hip hop", "boom bap", "instrumental hip hop", "abstract hip hop", "rap", "trip hop"],
    width=0.40,
    description=(
        "Everything hangs off the drums, and the drums are somebody else's record. "
        "Dense, dry, close, and built for headphones on public transport."
    ),
    valence=0.54, energy=0.66, tempo=0.44,  # ~113 BPM: half-time feel, high energy
    acousticness=0.28, density=0.66, grit=0.56,
    spatiality=0.38,  # driest corridor here; the vocal sits right on your ear
)

_ELECTRONICA = _corridor(
    "electronica",
    "Electronica & IDM",
    tags=["idm", "electronica", "braindance", "warp", "glitch", "electronic"],
    width=0.38,
    description=(
        "Rhythm treated as a research programme. Melodically sentimental, "
        "structurally hostile, and quietly the most emotional shelf in the shop."
    ),
    valence=0.48, energy=0.54, tempo=0.50, acousticness=0.10, density=0.64,
    grit=0.44, spatiality=0.62,
)

_MODERN_COMPOSITION = _corridor(
    "modern-composition",
    "Classical & modern composition",
    tags=["modern classical", "contemporary classical", "neoclassical", "piano", "minimalism", "soundtrack"],
    width=0.30,
    description=(
        "Notated, performed, and recorded in a room chosen on purpose. Spans four "
        "centuries and a lot of silence."
    ),
    valence=0.48, energy=0.30, tempo=0.30, acousticness=0.88, density=0.34,
    grit=0.16,  # the cleanest anchor: no tape, no amp, no hiss
    spatiality=0.74,
)

_DESERT_BLUES = _corridor(
    "desert-blues",
    "Desert blues",
    tags=["desert blues", "tuareg", "african", "blues", "sahel", "psychedelic"],
    width=0.34,
    description=(
        "Pentatonic guitar figures that loop like a road does. Blues geometry with the "
        "resolution taken out and a great deal more patience."
    ),
    valence=0.52, energy=0.58, tempo=0.46, acousticness=0.74, density=0.52,
    grit=0.58, spatiality=0.44,
)

_SLOWCORE = _corridor(
    "slowcore",
    "Slowcore",
    tags=["slowcore", "sadcore", "lo-fi", "melancholy", "indie folk", "quiet"],
    width=0.30,
    description=(
        "Rock music played at the speed of an honest conversation. Every note costs "
        "something, so there are not many of them."
    ),
    valence=0.30,  # the lowest-valence anchor here, and it has earned it
    energy=0.24, tempo=0.24,  # ~89 BPM
    acousticness=0.70, density=0.22, grit=0.32, spatiality=0.62,
)


CORRIDORS: dict[str, GenreCorridor] = {
    corridor.id: corridor
    for corridor in (
        _ANY,
        _AMBIENT,
        _DESERT_BLUES,
        _DRONE,
        _DUB_TECHNO,
        _ELECTRONICA,
        _FOLK,
        _HIP_HOP,
        _INDIE_ROCK,
        _KRAUTROCK,
        _MODERN_COMPOSITION,
        _POST_PUNK,
        _SHOEGAZE,
        _SLOWCORE,
        _SOUL,
        _SPIRITUAL_JAZZ,
    )
}


# Spellings people actually type, and the ids the UI used in earlier builds.
# Cheap to maintain, and it saves a forge from silently collapsing to `any`
# because somebody wrote "post punk" without the hyphen.
_ALIASES: dict[str, str] = {
    "": "any",
    "none": "any",
    "all": "any",
    "postpunk": "post-punk",
    "post punk": "post-punk",
    "post_punk": "post-punk",
    "dub techno": "dub-techno",
    "dubtechno": "dub-techno",
    "dub_techno": "dub-techno",
    "techno": "dub-techno",
    "spiritual jazz": "spiritual-jazz",
    "spiritual_jazz": "spiritual-jazz",
    "jazz": "spiritual-jazz",
    "indie": "indie-rock",
    "indie rock": "indie-rock",
    "indie_rock": "indie-rock",
    "rock": "indie-rock",
    "hip hop": "hip-hop",
    "hiphop": "hip-hop",
    "hip_hop": "hip-hop",
    "rap": "hip-hop",
    "idm": "electronica",
    "electronic": "electronica",
    "minimalism": "drone",
    "drone-minimalism": "drone",
    "classical": "modern-composition",
    "modern classical": "modern-composition",
    "neoclassical": "modern-composition",
    "desert blues": "desert-blues",
    "desert_blues": "desert-blues",
    "tuareg": "desert-blues",
    "sadcore": "slowcore",
    "dream pop": "shoegaze",
    "funk": "soul",
}


def corridor_ids() -> list[str]:
    """Canonical ids, ``any`` first and the rest alphabetical."""
    rest = sorted(cid for cid in CORRIDORS if cid != "any")
    return ["any", *rest]


def get_corridor(corridor_id: str | None) -> GenreCorridor:
    """Resolve a corridor id, forgivingly.

    Unlike :func:`~.themes.get_theme` this never raises. A genre is a *filter*
    on an outcome the user is going to get regardless, and an unrecognised
    filter must never kill a forge -- the correct response to "krautrok" is a
    playlist, not a 404. Falls back to :meth:`GenreCorridor.any`, which imposes
    nothing and lets the sky and the scrobbles have the floor.
    """
    if not corridor_id:
        return _ANY
    key = corridor_id.strip().lower()
    if key in CORRIDORS:
        return CORRIDORS[key]
    if key in _ALIASES:
        return CORRIDORS[_ALIASES[key]]
    # Last try: normalise separators before giving up ("Dub Techno" -> "dub-techno").
    squashed = key.replace("_", "-").replace(" ", "-").replace("&", "-")
    while "--" in squashed:
        squashed = squashed.replace("--", "-")
    return CORRIDORS.get(squashed, _ANY)


def list_corridors() -> list[GenreCorridor]:
    """All corridors, ``any`` first."""
    return [CORRIDORS[cid] for cid in corridor_ids()]

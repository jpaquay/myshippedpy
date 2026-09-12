"""The tag lexicon: BAROGROOVE's replacement for Spotify ``/audio-features``.

Spotify used to hand out eleven numbers per track. As of 27 Nov 2024 it hands
out a 403. What Last.fm hands out instead is *words* — a community tag
vocabulary of a size and specificity Spotify never approached. "krautrock",
"dub techno", "slowcore", "rainy day", "wall of sound", "desert blues". The
crowd has already described how the record sounds. This module is the
dictionary that turns those descriptions back into numbers.

How it works
------------
Each known tag contributes a *partial* set of signed deltas around the neutral
0.5 baseline, plus a confidence weight. A tag only speaks about the dimensions
it actually has an opinion on: ``rainy day`` says nothing about tempo, and
pretending otherwise would drag every rainy-day track toward 120 BPM for no
reason. Dimensions nobody mentions stay at 0.5.

The seven dimensions, as this file reads them:

==============  =========================================================
valence         miserable (0) .. elated (1). Not "good"; just bright.
energy          inert (0) .. violent (1). Arousal, not volume.
tempo           60 BPM (0) .. 180 BPM (1), linear. 0.5 is 120 BPM.
acousticness    fully synthetic (0) .. fully acoustic (1). Electric
                guitars sit near the middle: not a machine, not a cello.
density         one line (0) .. everything at once (1). Event rate and
                layer count.
grit            polished (0) .. abrasive (1). Distortion, noise, tape
                saturation, clipping, hoarseness.
spatiality      dry and close (0) .. cavernous (1). Reverb, width, the
                sense of a room around the sound.
==============  =========================================================

Judgement calls are the point of this file, so they are written down:

* ``shoegaze`` pushes **spatiality** and **grit** hard and leaves valence
  ambiguous. The genre is defined by the guitar texture and the size of the
  room, not by mood — *Loveless* and *Souvlaki* are not the same emotion.
* ``slowcore`` pushes **tempo** and **density** down hard. It is defined by
  subtraction: fewer events, more silence between them.
* ``krautrock`` pushes **density** and **tempo** up while leaving **valence**
  neutral and **acousticness** low. Motorik is not happy, it is relentless.
  A naive "fast + busy => cheerful" model gets Neu! catastrophically wrong,
  and that single distinction is most of the reason this file exists rather
  than a two-line heuristic.
* Weather and time-of-day context tags (``rainy day``, ``late night``) get
  *low* confidence weights and touch few dimensions. They are real signal
  about mood and space but they are not genre, and they are applied by
  listeners far more loosely than "dub techno" is.

Everything here is pure, synchronous and deterministic. No network, no clock,
no randomness. It is the one part of the oracle that always works.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final, Iterable, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..contracts import SONIC_DIMS, SonicVector, clamp

__all__ = [
    "TagProfile",
    "LEXICON",
    "KNOWN_TAGS",
    "ALIASES",
    "canonical_tag",
    "canonical_tags",
    "estimate_from_tags",
    "estimate_with_confidence",
    "recognised_tags",
    "tag_affinity",
    "tag_coverage",
]


# --------------------------------------------------------------------------
# canonicalisation
# --------------------------------------------------------------------------
# Last.fm tags are free text typed by humans over twenty years. The same idea
# arrives as "Post-Rock", "post rock", "postrock", "post_rock" and "POST ROCK".
# Canonical form: casefolded, accent-stripped, punctuation-to-space,
# whitespace-collapsed. Everything after that is handled by the alias map.
_PUNCT = re.compile(r"[^a-z0-9&+]+")
_WS = re.compile(r"\s+")


def _fold(tag: str) -> str:
    text = unicodedata.normalize("NFKD", str(tag)).encode("ascii", "ignore").decode("ascii")
    text = text.casefold()
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip()


class TagProfile(BaseModel):
    """One lexicon entry: what a tag asserts about a record.

    ``deltas`` is deliberately partial. Absent dimensions are *not* asserted to
    be 0.5 — they are simply not asserted at all, and are left to whatever
    other tags in the set have to say.
    """

    model_config = ConfigDict(frozen=True)

    #: Signed offsets from the 0.5 neutral baseline, per sonic dimension.
    deltas: dict[str, float] = Field(default_factory=dict)
    #: How much this tag should be trusted, 0..1. Genre tags are strong,
    #: mood tags moderate, context tags weak.
    weight: float = 1.0
    #: Why the numbers are what they are. Read by humans; ignored by code.
    note: str = ""

    @field_validator("deltas")
    @classmethod
    def _known_dims(cls, value: dict[str, float]) -> dict[str, float]:
        bad = set(value) - set(SONIC_DIMS)
        if bad:
            raise ValueError(f"unknown sonic dimensions: {sorted(bad)}")
        return {k: float(v) for k, v in value.items()}


def _p(weight: float, note: str, **deltas: float) -> TagProfile:
    """Terse constructor so the table below reads as a table."""
    return TagProfile(deltas=deltas, weight=weight, note=note)


# Shorthand for the dimension names, purely so the table stays inside a
# sensible line length and the numbers stay visually aligned.
# val=valence  eng=energy  tmp=tempo  aco=acousticness
# den=density  grt=grit    spa=spatiality
def _e(
    weight: float,
    note: str,
    *,
    val: float | None = None,
    eng: float | None = None,
    tmp: float | None = None,
    aco: float | None = None,
    den: float | None = None,
    grt: float | None = None,
    spa: float | None = None,
) -> TagProfile:
    deltas = {
        "valence": val,
        "energy": eng,
        "tempo": tmp,
        "acousticness": aco,
        "density": den,
        "grit": grt,
        "spatiality": spa,
    }
    return TagProfile(
        deltas={k: v for k, v in deltas.items() if v is not None},
        weight=weight,
        note=note,
    )


# ==========================================================================
# THE LEXICON
# ==========================================================================
# Entry order within a section is roughly by family, not alphabetical, so
# neighbouring entries can be compared against each other while editing.
# Delta magnitudes: 0.05 is a nudge, 0.15 a clear lean, 0.30 a defining
# characteristic, 0.45 the practical ceiling (a single tag should never be
# able to pin a dimension to an extreme on its own).

LEXICON: Final[dict[str, TagProfile]] = {
    # ----------------------------------------------------------------
    # 1. GUITAR MUSIC, SCENES AND POST-EVERYTHING
    # ----------------------------------------------------------------
    # The defining move is the guitar *texture* and the size of the room.
    # Mood is deliberately under-asserted here: these scenes span from
    # euphoric to suicidal without changing their sonic signature.
    "shoegaze": _e(
        1.0,
        "Spatiality and grit are the genre. Valence is left alone on purpose: "
        "'Loveless' and 'Souvlaki' share a texture, not an emotion.",
        eng=0.10, aco=-0.20, den=0.25, grt=0.30, spa=0.38,
    ),
    "dream pop": _e(
        1.0,
        "Shoegaze with the fuzz pedal off. Same room, less abrasion, and a "
        "warmer valence because the melodies are actually pop melodies.",
        val=0.10, eng=-0.10, tmp=-0.08, aco=-0.10, den=0.12, grt=-0.05, spa=0.32,
    ),
    "post rock": _e(
        1.0,
        "Long-form dynamics. Wide, largely instrumental, builds rather than "
        "sustains, so energy sits only slightly above neutral despite the "
        "crescendos.",
        eng=0.08, tmp=-0.08, aco=-0.05, den=0.18, grt=0.08, spa=0.32,
    ),
    "post punk": _e(
        1.0,
        "Angular, dry, treble-forward, driven by the bass. Low spatiality is "
        "the tell versus goth, which shares the harmony but not the room.",
        val=-0.12, eng=0.18, tmp=0.12, aco=-0.12, den=-0.05, grt=0.18, spa=-0.05,
    ),
    "no wave": _e(
        0.9,
        "Post-punk with the melody removed and the atonality left in.",
        val=-0.22, eng=0.28, tmp=0.10, aco=-0.15, den=0.10, grt=0.38, spa=-0.05,
    ),
    "cold wave": _e(
        1.0,
        "Post-punk played on cheap machines in a cold room. Synthetic, "
        "sparse, deliberately affectless.",
        val=-0.22, eng=0.02, tmp=0.05, aco=-0.35, den=-0.15, grt=0.08, spa=0.12,
    ),
    "minimal wave": _e(
        1.0,
        "Cold wave's more austere cousin: fewer elements still, drum machine "
        "and one synth line. Density is the discriminator.",
        val=-0.18, eng=0.00, tmp=0.05, aco=-0.40, den=-0.28, grt=0.05, spa=0.08,
    ),
    "new wave": _e(
        0.9,
        "Post-punk that decided it wanted a chorus and a keyboard hook.",
        val=0.18, eng=0.20, tmp=0.18, aco=-0.22, den=0.05, grt=-0.05,
    ),
    "gothic rock": _e(
        0.9,
        "Post-punk plus reverb plus a much worse mood.",
        val=-0.30, eng=0.10, tmp=0.02, aco=-0.10, den=0.10, grt=0.12, spa=0.25,
    ),
    "slowcore": _e(
        1.0,
        "Defined by subtraction. Tempo and density both drop hard; the "
        "silence between events is the instrument.",
        val=-0.22, eng=-0.32, tmp=-0.38, aco=0.18, den=-0.35, grt=-0.08, spa=0.12,
    ),
    "sadcore": _e(
        0.9,
        "Slowcore with the emotional content made explicit rather than "
        "implied. Slightly less austere, considerably more miserable.",
        val=-0.32, eng=-0.28, tmp=-0.30, aco=0.15, den=-0.25, spa=0.10,
    ),
    "midwest emo": _e(
        0.8,
        "Twinkly arpeggios, unstable time signatures, earnest to a fault.",
        val=-0.10, eng=0.12, tmp=0.05, aco=0.05, den=0.10, grt=0.05, spa=0.05,
    ),
    "emo": _e(
        0.8,
        "Dynamic swing between quiet and loud; the mood is the point.",
        val=-0.18, eng=0.18, tmp=0.08, den=0.08, grt=0.15,
    ),
    "math rock": _e(
        0.9,
        "Metric complexity. Density is high because the event rate is high, "
        "not because the arrangement is thick.",
        eng=0.20, tmp=0.15, den=0.30, grt=0.05, spa=-0.10,
    ),
    "noise rock": _e(
        0.9,
        "Grit is the entire proposition.",
        val=-0.18, eng=0.32, tmp=0.10, aco=-0.15, den=0.20, grt=0.42, spa=0.05,
    ),
    "krautrock": _e(
        1.0,
        "Motorik is not happy, it is relentless. Density and tempo go up, "
        "acousticness goes down, and valence stays exactly where it was — "
        "the repetition is affect-neutral by design. Getting this wrong is "
        "the single most common failure of naive feature models.",
        eng=0.18, tmp=0.20, aco=-0.22, den=0.26, grt=0.08, spa=0.15,
    ),
    "motorik": _e(
        0.9,
        "The 4/4 pulse itself, tagged separately. Pure forward motion.",
        eng=0.20, tmp=0.25, den=0.22, spa=0.08,
    ),
    "berlin school": _e(
        0.9,
        "Sequencer music: long, hypnotic, wholly electronic, patient.",
        eng=-0.05, tmp=0.05, aco=-0.45, den=0.15, spa=0.30,
    ),
    "space rock": _e(
        0.85,
        "Rock that has been given far too much room and a delay pedal.",
        eng=0.10, aco=-0.15, den=0.15, grt=0.12, spa=0.38,
    ),
    "psychedelic rock": _e(
        0.85,
        "Colour and effects over aggression; warmer than its descendants.",
        val=0.08, eng=0.10, aco=0.05, den=0.18, grt=0.10, spa=0.25,
    ),
    "progressive rock": _e(
        0.85,
        "Maximal arrangement, shifting metre, high information rate.",
        eng=0.12, tmp=0.08, den=0.35, spa=0.15,
    ),
    "art rock": _e(
        0.8,
        "Studio as instrument; unusual timbres, restrained aggression.",
        val=-0.05, den=0.15, spa=0.15,
    ),
    "garage rock": _e(
        0.85,
        "Cheap, fast, loud, recorded badly on purpose.",
        val=0.12, eng=0.32, tmp=0.25, aco=0.05, den=-0.05, grt=0.32, spa=-0.08,
    ),
    "surf rock": _e(
        0.8,
        "Spring reverb is non-negotiable; bright and fast.",
        val=0.25, eng=0.25, tmp=0.28, aco=0.05, grt=0.10, spa=0.28,
    ),
    "grunge": _e(
        0.85,
        "Heavy, mid-tempo, deeply unhappy, thickly distorted.",
        val=-0.25, eng=0.30, tmp=0.02, aco=-0.05, den=0.15, grt=0.38, spa=0.08,
    ),
    "jangle pop": _e(
        0.8,
        "Chiming, clean, bright, unbothered.",
        val=0.28, eng=0.12, tmp=0.10, aco=0.15, grt=-0.20, spa=0.10,
    ),
    "power pop": _e(
        0.75,
        "Hooks at speed, compressed, cheerful.",
        val=0.30, eng=0.28, tmp=0.22, den=0.08, grt=0.05,
    ),
    "indie rock": _e(
        0.6,
        "Weak entry by design: the tag spans thirty years and everything in "
        "them. Low confidence keeps it from dominating a tag set.",
        eng=0.10, tmp=0.05, grt=0.05,
    ),
    "indie pop": _e(
        0.6,
        "As above, brighter and cleaner.",
        val=0.20, eng=0.05, aco=0.05, grt=-0.10,
    ),
    "singer songwriter": _e(
        0.85,
        "One person, one instrument, foregrounded voice.",
        val=-0.08, eng=-0.25, tmp=-0.18, aco=0.38, den=-0.30, grt=-0.10,
    ),

    # ----------------------------------------------------------------
    # 2. ELECTRONIC
    # ----------------------------------------------------------------
    # Acousticness is uniformly low; the interesting axes are density,
    # spatiality and tempo. Note the deliberate spread in tempo: dub techno
    # and jungle are both "electronic dance music" and are 60 BPM apart.
    "ambient": _e(
        1.0,
        "The genre is space and duration. Everything else recedes: no beat "
        "to speak of, minimal event rate, no abrasion.",
        eng=-0.35, tmp=-0.30, aco=-0.25, den=-0.32, grt=-0.20, spa=0.40,
    ),
    "dark ambient": _e(
        1.0,
        "Ambient's parameters with the valence floor removed and a little "
        "grit added — the texture is usually decaying, not clean.",
        val=-0.35, eng=-0.25, tmp=-0.30, aco=-0.28, den=-0.20, grt=0.15, spa=0.42,
    ),
    "drone": _e(
        1.0,
        "One event, sustained. Density bottoms out precisely because the "
        "sound may be enormous — density is event rate, not loudness.",
        eng=-0.25, tmp=-0.40, aco=-0.15, den=-0.40, grt=0.12, spa=0.40,
    ),
    "field recording": _e(
        0.9,
        "Literally the sound of a place. Maximally acoustic and spatial, "
        "minimally rhythmic.",
        eng=-0.35, tmp=-0.35, aco=0.45, den=-0.25, spa=0.35,
    ),
    "musique concrete": _e(
        0.85,
        "Edited real-world sound. Unpredictable event rate, harsh edges.",
        val=-0.15, tmp=-0.15, aco=0.20, den=0.10, grt=0.25, spa=0.25,
    ),
    "idm": _e(
        1.0,
        "Programmed complexity. High density from the drum edit alone; "
        "spatiality moderate; mood pointedly ambiguous.",
        eng=0.10, tmp=0.12, aco=-0.40, den=0.32, grt=0.15, spa=0.18,
    ),
    "glitch": _e(
        0.9,
        "Error as material. Grit and density both up; tempo unstable enough "
        "to be left unasserted.",
        aco=-0.42, den=0.30, grt=0.30, spa=0.10,
    ),
    "dub techno": _e(
        1.0,
        "Chord stab, tape delay, and a very long decay. Spatiality is the "
        "genre; density stays LOW despite the four-to-the-floor, because "
        "almost nothing happens per bar. Tempo sits just under house.",
        val=-0.05, eng=-0.05, tmp=0.02, aco=-0.45, den=-0.15, grt=0.05, spa=0.42,
    ),
    "dub": _e(
        0.95,
        "The source of all of the above. Bass, space, and the mixing desk "
        "as an instrument.",
        val=0.05, eng=-0.10, tmp=-0.15, aco=0.05, den=-0.15, grt=0.08, spa=0.40,
    ),
    "techno": _e(
        0.95,
        "Machine music at pace. Repetition without warmth.",
        eng=0.30, tmp=0.28, aco=-0.45, den=0.15, grt=0.15, spa=0.05,
    ),
    "minimal techno": _e(
        0.95,
        "Techno with the arrangement removed. Density drops, pace stays.",
        eng=0.15, tmp=0.25, aco=-0.45, den=-0.22, grt=0.05, spa=0.12,
    ),
    "acid house": _e(
        0.9,
        "The 303 squelch is the grit; relentlessly upbeat.",
        val=0.20, eng=0.32, tmp=0.30, aco=-0.45, den=0.10, grt=0.22,
    ),
    "deep house": _e(
        0.9,
        "Warm chords, soft swing, considerably more human than techno.",
        val=0.18, eng=0.12, tmp=0.18, aco=-0.30, den=0.05, grt=-0.12, spa=0.20,
    ),
    "house": _e(
        0.85,
        "Four to the floor at 120-126. Bright and functional.",
        val=0.25, eng=0.28, tmp=0.22, aco=-0.35, den=0.10,
    ),
    "italo disco": _e(
        0.85,
        "Melodramatic, synthetic, euphoric and slightly cheap.",
        val=0.28, eng=0.28, tmp=0.22, aco=-0.42, den=0.15, spa=0.15,
    ),
    "disco": _e(
        0.85,
        "Live rhythm section, string section, unambiguous joy.",
        val=0.35, eng=0.30, tmp=0.22, aco=0.15, den=0.30,
    ),
    "synthpop": _e(
        0.85,
        "Songs, but every timbre is a keyboard.",
        val=0.18, eng=0.15, tmp=0.15, aco=-0.42, den=0.05, grt=-0.10, spa=0.10,
    ),
    "synthwave": _e(
        0.85,
        "Retro-futurist pastiche: gated reverb, arpeggios, wide stereo.",
        val=0.10, eng=0.18, tmp=0.15, aco=-0.45, den=0.15, spa=0.28,
    ),
    "vaporwave": _e(
        0.85,
        "Slowed, chopped, drenched. Nostalgic and faintly nauseous.",
        val=0.05, eng=-0.25, tmp=-0.30, aco=-0.35, den=-0.10, grt=0.10, spa=0.35,
    ),
    "chillwave": _e(
        0.8,
        "Hazy, mid-tempo, sun-bleached; heavy on the tape wobble.",
        val=0.15, eng=-0.12, tmp=-0.08, aco=-0.25, grt=0.05, spa=0.30,
    ),
    "downtempo": _e(
        0.85,
        "Beat-led but unhurried.",
        eng=-0.20, tmp=-0.25, aco=-0.25, den=-0.05, spa=0.20,
    ),
    "trip hop": _e(
        0.9,
        "Slow breaks, dusty samples, cinematic gloom.",
        val=-0.25, eng=-0.10, tmp=-0.28, aco=-0.15, den=0.10, grt=0.15, spa=0.28,
    ),
    "jungle": _e(
        1.0,
        "Chopped breaks at 160+ over a half-time sub bass. Tempo and density "
        "go to the ceiling; valence stays neutral because the mood ranges "
        "from ecstatic to genuinely menacing within one record.",
        eng=0.38, tmp=0.42, aco=-0.30, den=0.40, grt=0.20, spa=0.15,
    ),
    "drum and bass": _e(
        0.95,
        "Jungle's tidier descendant: same pace, cleaner edit.",
        eng=0.38, tmp=0.42, aco=-0.40, den=0.30, grt=0.15, spa=0.10,
    ),
    "breakbeat": _e(
        0.85,
        "Syncopated sampled drums as the organising principle.",
        eng=0.28, tmp=0.25, aco=-0.30, den=0.25, grt=0.12,
    ),
    "uk garage": _e(
        0.85,
        "Skippy two-step swing, clipped vocals, ~135.",
        val=0.18, eng=0.28, tmp=0.30, aco=-0.35, den=0.20,
    ),
    "footwork": _e(
        0.9,
        "160 BPM, extreme repetition, very high event rate.",
        eng=0.35, tmp=0.40, aco=-0.40, den=0.38, grt=0.15,
    ),
    "dubstep": _e(
        0.85,
        "Half-time at 140, enormous sub, cavernous mix.",
        val=-0.20, eng=0.25, tmp=-0.05, aco=-0.42, den=0.10, grt=0.28, spa=0.30,
    ),
    "electro": _e(
        0.8,
        "808 machine funk; stiff, bright, mechanical.",
        val=0.10, eng=0.28, tmp=0.20, aco=-0.45, den=0.15, grt=0.10,
    ),
    "industrial": _e(
        0.9,
        "Metal-on-metal percussion and deliberate ugliness.",
        val=-0.32, eng=0.35, tmp=0.15, aco=-0.35, den=0.25, grt=0.42, spa=0.15,
    ),
    "ebm": _e(
        0.85,
        "Industrial made danceable: rigid, sequenced, aggressive.",
        val=-0.20, eng=0.35, tmp=0.28, aco=-0.45, den=0.15, grt=0.28,
    ),
    "trance": _e(
        0.8,
        "Long builds, major-key release, wide supersaws.",
        val=0.28, eng=0.32, tmp=0.32, aco=-0.45, den=0.25, spa=0.30,
    ),
    "modular synth": _e(
        0.8,
        "Patch-cable music: evolving, unrepeatable, unmistakably electronic.",
        aco=-0.45, den=0.10, spa=0.25,
    ),
    "new age": _e(
        0.8,
        "Consonant, slow, deliberately frictionless.",
        val=0.25, eng=-0.30, tmp=-0.28, den=-0.20, grt=-0.30, spa=0.35,
    ),
    "kosmische": _e(
        0.85,
        "The cosmic wing of krautrock: slower, wider, less motorik.",
        tmp=-0.05, aco=-0.30, den=0.05, spa=0.38,
    ),
}

# The dict literal is split so that no single statement becomes unreadable.
# Later sections update the same mapping.

LEXICON.update({
    # ----------------------------------------------------------------
    # 3. JAZZ, CLASSICAL AND COMPOSED MUSIC
    # ----------------------------------------------------------------
    "jazz": _e(
        0.7,
        "Deliberately weak: the tag covers Bix Beiderbecke and Peter "
        "Brötzmann. Only acousticness and density are safe to assert.",
        aco=0.32, den=0.15,
    ),
    "spiritual jazz": _e(
        1.0,
        "Modal, incantatory, harp and reeds, recorded in a large room. "
        "Valence is *elevated but not cheerful* — this is devotional music, "
        "which is a different thing from happy music.",
        val=0.18, eng=0.05, tmp=-0.05, aco=0.35, den=0.25, spa=0.35,
    ),
    "modal jazz": _e(
        0.9,
        "Fewer chord changes, more room to sit inside one.",
        val=-0.05, eng=-0.10, tmp=-0.10, aco=0.35, den=0.05, spa=0.20,
    ),
    "free jazz": _e(
        0.95,
        "No metre, no restraint. Density and grit both very high; the "
        "acoustic instruments are being played abrasively on purpose.",
        val=-0.10, eng=0.40, tmp=0.20, aco=0.30, den=0.42, grt=0.35, spa=0.10,
    ),
    "cool jazz": _e(
        0.9,
        "Restraint as the aesthetic. Quiet, unhurried, immaculate.",
        val=0.10, eng=-0.25, tmp=-0.15, aco=0.38, den=-0.10, grt=-0.25, spa=0.10,
    ),
    "jazz fusion": _e(
        0.85,
        "Electric, virtuosic, extremely busy.",
        eng=0.25, tmp=0.20, aco=-0.05, den=0.40, grt=0.10,
    ),
    "bossa nova": _e(
        0.95,
        "Nylon guitar, brushed drums, and the specific melancholy of a very "
        "pretty chord. Bright surface, saudade underneath: valence up only "
        "moderately despite the major sevenths.",
        val=0.20, eng=-0.25, tmp=-0.12, aco=0.42, den=-0.15, grt=-0.30, spa=0.05,
    ),
    "samba": _e(
        0.85,
        "Percussion-led, fast, communal, unambiguously bright.",
        val=0.35, eng=0.32, tmp=0.28, aco=0.35, den=0.35,
    ),
    "contemporary classical": _e(
        0.85,
        "Composed, acoustic, dynamically extreme, often austere.",
        val=-0.10, eng=-0.10, aco=0.35, den=0.05, grt=-0.10, spa=0.30,
    ),
    "neoclassical": _e(
        0.85,
        "Piano and strings, close-miked, melancholic by convention.",
        val=-0.18, eng=-0.30, tmp=-0.25, aco=0.42, den=-0.20, grt=-0.25, spa=0.25,
    ),
    "minimalism": _e(
        0.9,
        "Phase and repetition. High event rate, low harmonic movement — "
        "density up, everything else calm.",
        eng=-0.05, tmp=0.08, aco=0.15, den=0.25, grt=-0.20, spa=0.20,
    ),
    "chamber music": _e(
        0.8,
        "Small ensemble, real room, no amplification.",
        eng=-0.20, aco=0.45, den=-0.10, grt=-0.30, spa=0.20,
    ),
    "baroque": _e(
        0.8,
        "Ornamented, brisk, harpsichord-bright.",
        val=0.15, tmp=0.15, aco=0.45, den=0.25, grt=-0.30, spa=0.15,
    ),
    "choral": _e(
        0.8,
        "Massed voices in a stone building. Spatiality is structural.",
        val=0.10, eng=-0.15, tmp=-0.20, aco=0.45, den=0.15, grt=-0.30, spa=0.45,
    ),
    "soundtrack": _e(
        0.65,
        "Weak: a delivery format, not a sound. Only the tendency toward "
        "instrumental width is reliable.",
        den=0.05, spa=0.22,
    ),
    "library music": _e(
        0.7,
        "Functional instrumental production music; competent and uncanny.",
        den=0.10, spa=0.12,
    ),

    # ----------------------------------------------------------------
    # 4. FOLK, ROOTS AND MUSIC FROM OUTSIDE THE ANGLOPHONE DEFAULT
    # ----------------------------------------------------------------
    "folk": _e(
        0.85,
        "Acoustic, sparse, voice-forward.",
        eng=-0.25, tmp=-0.20, aco=0.42, den=-0.25, grt=-0.10,
    ),
    "freak folk": _e(
        0.85,
        "Folk instrumentation, psychedelic arrangement, home-recorded.",
        eng=-0.10, tmp=-0.12, aco=0.30, den=0.10, grt=0.15, spa=0.20,
    ),
    "americana": _e(
        0.8,
        "Roots instrumentation, mid-tempo, unhurried.",
        val=0.05, eng=-0.12, tmp=-0.12, aco=0.35, den=-0.05,
    ),
    "alt country": _e(
        0.8,
        "Country structure, indie-rock recording, worse mood.",
        val=-0.15, eng=-0.05, tmp=-0.10, aco=0.28, grt=0.10,
    ),
    "country": _e(
        0.75,
        "Pedal steel, plain production, narrative lyrics.",
        val=0.05, aco=0.35, grt=-0.05,
    ),
    "bluegrass": _e(
        0.85,
        "Fast, acoustic, high event rate, relentlessly bright.",
        val=0.28, eng=0.30, tmp=0.32, aco=0.45, den=0.25, grt=-0.10,
    ),
    "delta blues": _e(
        0.9,
        "One voice, one guitar, and a great deal of surface noise. Grit here "
        "is as much the 1930s shellac as the performance.",
        val=-0.28, eng=-0.05, tmp=-0.15, aco=0.45, den=-0.35, grt=0.30, spa=0.05,
    ),
    "blues": _e(
        0.8,
        "Twelve bars, bent notes, mid-tempo.",
        val=-0.20, eng=0.05, aco=0.20, grt=0.18,
    ),
    "desert blues": _e(
        1.0,
        "Tuareg guitar music: circular, hypnotic, electric but recorded "
        "openly. Tempo is moderate, density moderate, the pull is in the "
        "loop. Valence resolutely neutral — it is exile music.",
        val=-0.05, eng=0.10, tmp=0.05, aco=0.15, den=0.05, grt=0.15, spa=0.25,
    ),
    "tuareg": _e(
        0.9,
        "Alias-adjacent to desert blues but tagged separately often enough "
        "to deserve its own entry.",
        val=-0.05, eng=0.10, aco=0.18, grt=0.12, spa=0.22,
    ),
    "afrobeat": _e(
        0.9,
        "Interlocking horns and percussion over a twenty-minute groove. "
        "Density is the defining number.",
        val=0.20, eng=0.30, tmp=0.15, aco=0.30, den=0.42, grt=0.05,
    ),
    "highlife": _e(
        0.8,
        "Bright interlocking guitars, buoyant, warm.",
        val=0.35, eng=0.20, tmp=0.15, aco=0.35, den=0.25,
    ),
    "ethio jazz": _e(
        0.9,
        "Pentatonic modes over a loose jazz rhythm section. The scale reads "
        "as neither major nor minor, so valence stays put.",
        val=-0.05, eng=-0.05, tmp=-0.10, aco=0.32, den=0.10, spa=0.15,
    ),
    "cumbia": _e(
        0.8,
        "Mid-tempo, percussive, communal.",
        val=0.28, eng=0.20, tmp=0.05, aco=0.25, den=0.25,
    ),
    "fado": _e(
        0.85,
        "Portuguese guitar and professional grief.",
        val=-0.35, eng=-0.15, tmp=-0.20, aco=0.45, den=-0.20, grt=-0.10, spa=0.15,
    ),
    "flamenco": _e(
        0.85,
        "Percussive nylon guitar, sudden dynamics, high event rate.",
        val=-0.10, eng=0.30, tmp=0.15, aco=0.45, den=0.20, grt=0.10,
    ),
    "celtic": _e(
        0.75,
        "Modal, acoustic, often airy.",
        aco=0.40, den=0.05, spa=0.20,
    ),
    "gamelan": _e(
        0.85,
        "Tuned metal percussion; extremely dense, extremely resonant, and "
        "tuned outside equal temperament so valence is meaningless.",
        aco=0.42, den=0.35, spa=0.35,
    ),
    "raga": _e(
        0.85,
        "Slow unmetered alap giving way to rhythm; drone underneath.",
        eng=-0.15, tmp=-0.25, aco=0.42, den=-0.10, spa=0.25,
    ),
    "qawwali": _e(
        0.85,
        "Devotional, accelerating, ecstatic, massed handclaps.",
        val=0.25, eng=0.30, tmp=0.15, aco=0.40, den=0.30, spa=0.25,
    ),
    "gospel": _e(
        0.9,
        "Massed voices, organ, hall reverb, and genuine elation. One of the "
        "few tags where a high valence assertion is safe.",
        val=0.40, eng=0.30, tmp=0.05, aco=0.35, den=0.30, grt=0.05, spa=0.35,
    ),
    "spirituals": _e(
        0.8,
        "Older, sparser, graver relative of the above.",
        val=0.05, eng=-0.10, tmp=-0.20, aco=0.45, den=-0.15, spa=0.30,
    ),

    # ----------------------------------------------------------------
    # 5. SOUL, FUNK, HIP HOP, POP
    # ----------------------------------------------------------------
    "soul": _e(
        0.85,
        "Live band, foregrounded voice, warm mix.",
        val=0.22, eng=0.12, aco=0.25, den=0.20, grt=0.05,
    ),
    "neo soul": _e(
        0.85,
        "Soul with a hip-hop rhythmic sensibility; slower, hazier.",
        val=0.15, eng=-0.10, tmp=-0.18, aco=0.10, den=0.15, spa=0.20,
    ),
    "northern soul": _e(
        0.8,
        "Uptempo, four-on-the-floor, built for a dance floor in Wigan.",
        val=0.32, eng=0.35, tmp=0.28, aco=0.25, den=0.25,
    ),
    "funk": _e(
        0.85,
        "Syncopation and space in the rhythm section; hard on the one.",
        val=0.25, eng=0.30, tmp=0.10, aco=0.20, den=0.28, grt=0.08,
    ),
    "hip hop": _e(
        0.7,
        "Weak on purpose: the tag spans forty years and every possible "
        "tempo. Only the sampled, non-acoustic tendency is safe.",
        aco=-0.20, den=0.10, grt=0.05,
    ),
    "boom bap": _e(
        0.85,
        "Dusty breaks at 85-95, hard snare, sample-based.",
        val=-0.05, eng=0.15, tmp=-0.20, aco=-0.15, den=0.15, grt=0.20,
    ),
    "jazz rap": _e(
        0.85,
        "Boom bap with upright bass and horn samples; warmer.",
        val=0.15, eng=0.05, tmp=-0.18, aco=0.05, den=0.20, grt=0.10,
    ),
    "cloud rap": _e(
        0.85,
        "Reverb-drenched, half-time, deliberately weightless.",
        val=-0.10, eng=-0.15, tmp=-0.20, aco=-0.35, den=-0.05, spa=0.38,
    ),
    "r&b": _e(
        0.75,
        "Smooth production, melisma, mid-tempo.",
        val=0.15, eng=-0.05, tmp=-0.10, aco=-0.05, den=0.15, grt=-0.20,
    ),
    "city pop": _e(
        0.85,
        "Japanese 80s AOR: immaculate session playing, chrome production, "
        "unmistakably nocturnal optimism.",
        val=0.32, eng=0.15, tmp=0.10, aco=-0.10, den=0.28, grt=-0.25, spa=0.18,
    ),
    "yacht rock": _e(
        0.75,
        "Session-musician perfection; smooth to the point of frictionless.",
        val=0.30, eng=0.05, tmp=0.00, aco=0.10, den=0.25, grt=-0.30,
    ),
    "dance pop": _e(
        0.75,
        "Compressed, bright, built for a chorus.",
        val=0.32, eng=0.30, tmp=0.22, aco=-0.30, den=0.25, grt=-0.15,
    ),
    "bedroom pop": _e(
        0.85,
        "Home-recorded, small, tape-hissy, intimate.",
        val=0.05, eng=-0.22, tmp=-0.15, aco=0.10, den=-0.20, grt=0.15, spa=0.10,
    ),
    "art pop": _e(
        0.75,
        "Pop songcraft with unusual production choices.",
        val=0.05, den=0.20, spa=0.15,
    ),

    # ----------------------------------------------------------------
    # 6. METAL AND THE HEAVY END
    # ----------------------------------------------------------------
    "black metal": _e(
        1.0,
        "Tremolo guitar, blast beats, and a mix that is deliberately thin "
        "and distant. Grit at the ceiling; spatiality high, which surprises "
        "people until they hear how the cymbals are recorded.",
        val=-0.40, eng=0.42, tmp=0.38, aco=-0.20, den=0.35, grt=0.45, spa=0.30,
    ),
    "atmospheric black metal": _e(
        0.95,
        "The same, slowed and widened until it is nearly shoegaze.",
        val=-0.30, eng=0.25, tmp=0.15, aco=-0.15, den=0.30, grt=0.38, spa=0.42,
    ),
    "doom metal": _e(
        0.95,
        "Very slow, very heavy, very few events per minute.",
        val=-0.35, eng=0.20, tmp=-0.38, aco=-0.10, den=-0.05, grt=0.42, spa=0.25,
    ),
    "funeral doom": _e(
        0.9,
        "Doom taken to its logical, glacial conclusion.",
        val=-0.40, eng=0.05, tmp=-0.45, aco=-0.05, den=-0.15, grt=0.40, spa=0.35,
    ),
    "sludge": _e(
        0.9,
        "Doom with hardcore's abrasion and a worse recording.",
        val=-0.35, eng=0.32, tmp=-0.20, aco=-0.10, den=0.15, grt=0.45, spa=0.10,
    ),
    "stoner rock": _e(
        0.85,
        "Fuzz, riffs, mid-tempo, faintly benign.",
        val=-0.05, eng=0.25, tmp=-0.10, aco=-0.05, den=0.10, grt=0.38, spa=0.15,
    ),
    "post metal": _e(
        0.9,
        "Post-rock structure, metal weight, cathedral reverb.",
        val=-0.22, eng=0.25, tmp=-0.10, aco=-0.15, den=0.30, grt=0.35, spa=0.38,
    ),
    "death metal": _e(
        0.9,
        "Maximum event rate, maximum abrasion, no space at all.",
        val=-0.40, eng=0.45, tmp=0.35, aco=-0.20, den=0.40, grt=0.45, spa=-0.05,
    ),
    "hardcore punk": _e(
        0.85,
        "Fast, short, shouted, dry.",
        val=-0.20, eng=0.45, tmp=0.40, aco=-0.10, den=0.15, grt=0.40, spa=-0.10,
    ),
    "punk": _e(
        0.8,
        "Fast, loud, three chords, no reverb.",
        val=-0.05, eng=0.42, tmp=0.35, aco=-0.05, den=0.05, grt=0.35, spa=-0.10,
    ),
    "noise": _e(
        0.9,
        "Texture as the whole content; the extreme of the grit axis.",
        val=-0.25, eng=0.35, aco=-0.20, den=0.20, grt=0.45, spa=0.15,
    ),
    "power electronics": _e(
        0.85,
        "Noise with a microphone and hostility.",
        val=-0.40, eng=0.42, aco=-0.35, den=0.20, grt=0.45,
    ),
})

LEXICON.update({
    # ----------------------------------------------------------------
    # 7. MOODS
    # ----------------------------------------------------------------
    # Mood tags carry a middling weight. They are honest signal — listeners
    # are describing how the record makes them feel — but they are applied
    # far more loosely than genre tags, and they say almost nothing about
    # production. Most entries here touch valence, energy and tempo only.
    "melancholy": _e(
        0.8,
        "Sad but not agitated; the energy drop matters as much as the "
        "valence drop.",
        val=-0.35, eng=-0.20, tmp=-0.15,
    ),
    "bittersweet": _e(
        0.8,
        "The genuinely useful one. Valence dips only slightly — the whole "
        "point is that it is not simply sad.",
        val=-0.10, eng=-0.10, tmp=-0.08,
    ),
    "wistful": _e(
        0.8,
        "Backward-looking and gentle. Quieter than melancholy, less bleak.",
        val=-0.15, eng=-0.25, tmp=-0.18, spa=0.15,
    ),
    "nostalgic": _e(
        0.7,
        "Often a comment on the listener rather than the record; mild.",
        val=0.05, eng=-0.15, tmp=-0.10, spa=0.15,
    ),
    "euphoric": _e(
        0.85,
        "Bright and fast and large. The one mood tag that justifies moving "
        "four dimensions at once.",
        val=0.40, eng=0.38, tmp=0.25, den=0.20, spa=0.20,
    ),
    "uplifting": _e(
        0.8,
        "Euphoric with the volume down.",
        val=0.35, eng=0.20, tmp=0.10,
    ),
    "triumphant": _e(
        0.75,
        "Major-key, brass-adjacent, large.",
        val=0.35, eng=0.30, den=0.25, spa=0.20,
    ),
    "happy": _e(
        0.7,
        "Blunt instrument, but unambiguous in direction.",
        val=0.40, eng=0.15,
    ),
    "sad": _e(
        0.7,
        "As above, inverted.",
        val=-0.40, eng=-0.15, tmp=-0.12,
    ),
    "dark": _e(
        0.75,
        "Low valence, and in practice also more reverb and more grit — "
        "'dark' is a production adjective as often as an emotional one.",
        val=-0.35, grt=0.12, spa=0.15,
    ),
    "menacing": _e(
        0.85,
        "Low valence, *high* energy. The distinction from 'dark' is that "
        "something is about to happen.",
        val=-0.32, eng=0.28, den=0.10, grt=0.20,
    ),
    "eerie": _e(
        0.8,
        "Unsettling without threat: dissonance and space, not aggression.",
        val=-0.25, eng=-0.20, tmp=-0.18, spa=0.32,
    ),
    "haunting": _e(
        0.8,
        "Eerie plus beauty. Slow, wide, minor.",
        val=-0.25, eng=-0.22, tmp=-0.20, den=-0.10, spa=0.35,
    ),
    "aggressive": _e(
        0.85,
        "Energy and grit; direction of valence left open, since aggression "
        "is as often joyful as it is bitter.",
        eng=0.40, tmp=0.20, den=0.15, grt=0.35,
    ),
    "angry": _e(
        0.75,
        "Aggressive with the valence question settled.",
        val=-0.32, eng=0.38, tmp=0.18, grt=0.32,
    ),
    "hypnotic": _e(
        0.85,
        "Repetition. Tempo unasserted — hypnosis works at 60 and at 160 — "
        "but energy flattens and space opens.",
        eng=-0.12, den=0.10, spa=0.25,
    ),
    "dreamy": _e(
        0.85,
        "Reverb, soft attack, no urgency.",
        val=0.10, eng=-0.25, tmp=-0.18, grt=-0.15, spa=0.38,
    ),
    "ethereal": _e(
        0.85,
        "Dreamy, higher, thinner, more diffuse.",
        val=0.08, eng=-0.28, tmp=-0.20, den=-0.15, grt=-0.25, spa=0.42,
    ),
    "mellow": _e(
        0.8,
        "Low arousal, mildly positive, no edges.",
        val=0.12, eng=-0.32, tmp=-0.22, grt=-0.25,
    ),
    "calm": _e(
        0.8,
        "As mellow, more so, and quieter still.",
        val=0.10, eng=-0.38, tmp=-0.28, den=-0.20, grt=-0.25,
    ),
    "contemplative": _e(
        0.8,
        "Slow, sparse, interior.",
        val=-0.08, eng=-0.30, tmp=-0.25, den=-0.22, spa=0.20,
    ),
    "romantic": _e(
        0.7,
        "Warm, slow, close-miked.",
        val=0.22, eng=-0.18, tmp=-0.15, aco=0.15, spa=0.05,
    ),
    "sensual": _e(
        0.7,
        "Slow, low, intimate rather than spacious.",
        val=0.15, eng=-0.12, tmp=-0.25, den=0.05, spa=-0.05,
    ),
    "epic": _e(
        0.7,
        "A statement about scale, not mood. Density and space.",
        eng=0.25, den=0.35, spa=0.35,
    ),
    "playful": _e(
        0.7,
        "Bright, bouncy, high event rate.",
        val=0.32, eng=0.20, tmp=0.18, den=0.15,
    ),
    "melodramatic": _e(
        0.7,
        "Large gestures, large reverb, unstable valence.",
        eng=0.20, den=0.30, spa=0.30,
    ),
    "meditative": _e(
        0.8,
        "Drone-adjacent stillness.",
        val=0.08, eng=-0.38, tmp=-0.35, den=-0.30, grt=-0.28, spa=0.30,
    ),

    # ----------------------------------------------------------------
    # 8. CONTEXT: WEATHER, SEASON, TIME OF DAY, ACTIVITY
    # ----------------------------------------------------------------
    # These carry the LOWEST weights in the lexicon (0.4-0.6) and touch the
    # fewest dimensions. They are exactly the vocabulary BAROGROOVE exists to
    # exploit — a barometer reading maps to "rainy day" far more naturally
    # than it maps to a danceability float — but a context tag must never
    # out-vote a genre tag about what a record actually sounds like.
    "rainy day": _e(
        0.55,
        "Interior, slow, soft-edged. Says nothing about instrumentation.",
        val=-0.18, eng=-0.28, tmp=-0.22, grt=-0.10, spa=0.20,
    ),
    "petrichor": _e(
        0.5,
        "Rare as a tag, but the theme name; treat as rainy day's cleaner, "
        "more expectant cousin — after the rain, not during it.",
        val=-0.05, eng=-0.25, tmp=-0.22, aco=0.15, den=-0.15, spa=0.28,
    ),
    "driving": _e(
        0.6,
        "Steady forward motion. Tempo and energy up; the tag is about pulse, "
        "not about mood, so valence stays put.",
        eng=0.25, tmp=0.25, den=0.12,
    ),
    "road trip": _e(
        0.55,
        "Driving, plus daylight and a better mood.",
        val=0.22, eng=0.20, tmp=0.18,
    ),
    "night drive": _e(
        0.6,
        "Driving, minus the daylight. Synthetic and wide.",
        val=-0.08, eng=0.15, tmp=0.18, aco=-0.25, spa=0.28,
    ),
    "late night": _e(
        0.55,
        "Low, slow, spacious, and slightly worse-tempered than the evening.",
        val=-0.15, eng=-0.25, tmp=-0.20, spa=0.25,
    ),
    "3am": _e(
        0.5,
        "Late night with the last of the company gone.",
        val=-0.25, eng=-0.30, tmp=-0.25, den=-0.20, spa=0.28,
    ),
    "sunday morning": _e(
        0.55,
        "Warm, acoustic, unhurried, benign. The classic low-stakes tag.",
        val=0.22, eng=-0.28, tmp=-0.22, aco=0.28, den=-0.15, grt=-0.20,
    ),
    "morning": _e(
        0.5,
        "Bright and gentle.",
        val=0.20, eng=-0.12, aco=0.15, grt=-0.15,
    ),
    "summer": _e(
        0.55,
        "Bright, warm, up-tempo, outdoors.",
        val=0.32, eng=0.20, tmp=0.15,
    ),
    "winter": _e(
        0.55,
        "Cold, still, spacious. The reverb here is an empty landscape, not a "
        "cathedral.",
        val=-0.22, eng=-0.25, tmp=-0.25, den=-0.18, spa=0.30,
    ),
    "autumn": _e(
        0.55,
        "Warm-toned decline. Acoustic, mid-slow, gently sad.",
        val=-0.15, eng=-0.20, tmp=-0.18, aco=0.22, spa=0.12,
    ),
    "spring": _e(
        0.5,
        "Bright, light, quick.",
        val=0.28, eng=0.10, tmp=0.12, aco=0.15,
    ),
    "beach": _e(
        0.5,
        "Warm, open, unbothered.",
        val=0.30, eng=0.10, tmp=0.05, aco=0.15, spa=0.20,
    ),
    "desert": _e(
        0.55,
        "Wide, dry, patient. Spatiality without wetness — a big empty place, "
        "not a big reflective one.",
        val=-0.05, eng=-0.10, tmp=-0.12, aco=0.20, den=-0.20, spa=0.28,
    ),
    "chill": _e(
        0.5,
        "Enormously over-applied; kept only for its energy signal.",
        eng=-0.30, tmp=-0.20, grt=-0.15,
    ),
    "party": _e(
        0.55,
        "Loud, fast, bright, dense.",
        val=0.35, eng=0.38, tmp=0.28, den=0.25,
    ),
    "workout": _e(
        0.5,
        "Pace and drive; nothing else is reliable.",
        eng=0.38, tmp=0.32, den=0.20,
    ),
    "study": _e(
        0.5,
        "Must not demand attention: low energy, low density, instrumental.",
        eng=-0.32, tmp=-0.20, den=-0.28, grt=-0.25,
    ),
    "sleep": _e(
        0.6,
        "The most extreme context tag, and the most reliable.",
        eng=-0.42, tmp=-0.40, den=-0.35, grt=-0.35, spa=0.30,
    ),
    "walking": _e(
        0.45,
        "Pedestrian tempo, mild.",
        eng=0.10, tmp=0.10,
    ),
    "headphones": _e(
        0.5,
        "A tag about detail and stereo width rather than mood.",
        den=0.15, spa=0.28,
    ),
    "coffee shop": _e(
        0.45,
        "Acoustic, mid-quiet, inoffensive.",
        val=0.15, eng=-0.25, aco=0.30, den=-0.15, grt=-0.20,
    ),
    "campfire": _e(
        0.45,
        "Acoustic, close, small.",
        val=0.12, eng=-0.25, tmp=-0.18, aco=0.42, den=-0.30, spa=-0.10,
    ),
    "fog": _e(
        0.5,
        "Diffuse and muffled: space up, definition down.",
        val=-0.15, eng=-0.22, tmp=-0.18, den=-0.10, spa=0.35,
    ),
    "storm": _e(
        0.55,
        "Weight and turbulence. Energy, density and grit; valence down.",
        val=-0.25, eng=0.35, den=0.30, grt=0.30, spa=0.25,
    ),

    # ----------------------------------------------------------------
    # 9. PRODUCTION AND RECORDING DESCRIPTORS
    # ----------------------------------------------------------------
    # These are the highest-precision tags in the lexicon. A listener who
    # writes "wall of sound" is making a specific, checkable claim about the
    # mix, so these carry genre-level weight even though they touch few
    # dimensions. Note that most of them say nothing about valence at all,
    # which is exactly right.
    "lo fi": _e(
        0.95,
        "Bandwidth-limited and noisy. Grit up, density down (there is less "
        "there), acousticness slightly up because it usually means fewer "
        "and more literal sound sources.",
        eng=-0.10, aco=0.10, den=-0.20, grt=0.32, spa=-0.05,
    ),
    "hi fi": _e(
        0.85,
        "Full bandwidth, wide image, no artefacts.",
        den=0.10, grt=-0.30, spa=0.20,
    ),
    "tape": _e(
        0.9,
        "Saturation, wow and flutter, compressed transients.",
        aco=0.08, grt=0.25, spa=0.05,
    ),
    "cassette": _e(
        0.85,
        "Tape, worse.",
        den=-0.12, grt=0.30,
    ),
    "reverb": _e(
        0.95,
        "The single most direct claim anyone makes about spatiality.",
        spa=0.42,
    ),
    "wall of sound": _e(
        1.0,
        "Everything at once, everywhere. Density and spatiality both near "
        "the ceiling; grit follows because that much summed signal always "
        "saturates something.",
        eng=0.20, den=0.42, grt=0.25, spa=0.42,
    ),
    "distorted": _e(
        0.95,
        "Unambiguous. Grit, and the energy that usually accompanies it.",
        eng=0.22, aco=-0.15, grt=0.42,
    ),
    "fuzz": _e(
        0.9,
        "A specific distortion: thick, woolly, less brittle than overdrive.",
        eng=0.18, aco=-0.12, den=0.12, grt=0.38,
    ),
    "acoustic": _e(
        1.0,
        "The definitional entry for the acousticness axis.",
        eng=-0.22, aco=0.45, den=-0.20, grt=-0.20,
    ),
    "unplugged": _e(
        0.85,
        "Acoustic, and usually a live room.",
        eng=-0.25, aco=0.42, den=-0.22, spa=0.10,
    ),
    "orchestral": _e(
        0.95,
        "Large acoustic ensemble in a large room.",
        aco=0.40, den=0.40, grt=-0.20, spa=0.35,
    ),
    "strings": _e(
        0.8,
        "A section, not a band. Warm, sustained, wide.",
        aco=0.32, den=0.20, grt=-0.20, spa=0.25,
    ),
    "piano": _e(
        0.8,
        "One acoustic source, wide dynamic range, sparse by default.",
        aco=0.40, den=-0.15, grt=-0.25,
    ),
    "guitar": _e(
        0.5,
        "Nearly contentless as a tag; kept for completeness at low weight.",
        aco=0.12,
    ),
    "saxophone": _e(
        0.7,
        "Acoustic, expressive, mid-forward.",
        aco=0.35, den=0.10,
    ),
    "female vocalists": _e(
        0.35,
        "One of the most-used tags on Last.fm and one of the least "
        "informative. Weight kept near the floor so it cannot distort a "
        "vector; retained only because dropping it would discard a real, if "
        "faint, correlation with cleaner production.",
        grt=-0.10,
    ),
    "instrumental": _e(
        0.8,
        "No voice to anchor attention: reads as more spacious and less "
        "immediately energetic.",
        eng=-0.15, den=0.05, spa=0.18,
    ),
    "spoken word": _e(
        0.8,
        "Speech over accompaniment; sparse and dry.",
        eng=-0.15, tmp=-0.15, aco=0.25, den=-0.25, spa=-0.05,
    ),
    "a cappella": _e(
        0.85,
        "Voices only: fully acoustic, sparse, usually reverberant.",
        aco=0.45, den=-0.20, grt=-0.25, spa=0.30,
    ),
    "live": _e(
        0.75,
        "Room sound, audience, looser playing, more grit.",
        eng=0.15, aco=0.15, grt=0.18, spa=0.28,
    ),
    "home recording": _e(
        0.85,
        "Small room, few tracks, audible noise floor.",
        eng=-0.18, aco=0.20, den=-0.28, grt=0.25, spa=-0.12,
    ),
    "four track": _e(
        0.85,
        "Home recording with a hard ceiling on layer count.",
        aco=0.18, den=-0.32, grt=0.28, spa=-0.10,
    ),
    "minimal": _e(
        0.9,
        "Few elements. This is the density axis stated outright.",
        eng=-0.18, den=-0.38, grt=-0.15, spa=0.12,
    ),
    "maximalist": _e(
        0.85,
        "The inverse, and rarer.",
        eng=0.20, den=0.42, spa=0.15,
    ),
    "sparse": _e(
        0.9,
        "As minimal, with an implication of silence rather than restraint.",
        eng=-0.22, den=-0.40, spa=0.15,
    ),
    "dense": _e(
        0.85,
        "Stated outright, the other way.",
        den=0.40,
    ),
    "sample based": _e(
        0.8,
        "Constructed rather than performed: non-acoustic sources even when "
        "the samples are of acoustic instruments.",
        aco=-0.25, den=0.15, grt=0.12,
    ),
    "analog synth": _e(
        0.85,
        "Warm, drifting, unmistakably electronic.",
        aco=-0.45, grt=0.08, spa=0.12,
    ),
    "polyrhythmic": _e(
        0.8,
        "Multiple simultaneous metres; the event rate is the point.",
        den=0.38, eng=0.15,
    ),
    "repetitive": _e(
        0.75,
        "Loop-based. Flattens energy, opens space, says nothing about pace.",
        eng=-0.10, den=0.05, spa=0.15,
    ),
    "long songs": _e(
        0.7,
        "Duration implies patience: slower and more spacious.",
        eng=-0.15, tmp=-0.18, spa=0.22,
    ),
    "improvisation": _e(
        0.8,
        "Unrepeatable, acoustic more often than not, variable density.",
        aco=0.25, den=0.15,
    ),
    "atmospheric": _e(
        0.85,
        "A direct claim about space, made constantly and usually accurately.",
        eng=-0.20, tmp=-0.15, spa=0.38,
    ),
    "cinematic": _e(
        0.8,
        "Wide, scored, dynamically staged.",
        den=0.25, spa=0.35,
    ),
    "dry": _e(
        0.9,
        "The explicit negation of reverb; close-miked and unflattering.",
        spa=-0.40,
    ),
    "warm": _e(
        0.75,
        "A claim about the low mids and the tape, not about the mood — but "
        "in practice it correlates with acoustic sources and less abrasion.",
        val=0.15, aco=0.18, grt=-0.15,
    ),
    "dynamic": _e(
        0.7,
        "Wide range between the quiet and loud parts. Reads as more energy "
        "and more density than a compressed record of the same material.",
        eng=0.20, den=0.20, spa=0.15,
    ),
    "groove": _e(
        0.75,
        "Locked, syncopated, mid-tempo. A rhythm-section claim.",
        val=0.15, eng=0.18, den=0.20,
    ),
    "horns": _e(
        0.75,
        "A brass or reed section: acoustic, loud, and adds a lot of layers.",
        eng=0.18, aco=0.30, den=0.25,
    ),
    "tribal": _e(
        0.75,
        "Percussion-led with interlocking parts. Nothing about mood.",
        eng=0.22, aco=0.25, den=0.30,
    ),
    "bass": _e(
        0.5,
        "Weak: usually means 'the low end is the hook'. Slight density and "
        "energy lean, nothing more.",
        eng=0.10, den=0.10,
    ),

    # ----------------------------------------------------------------
    # 10. LATE ADDITIONS — tags the seed corpus surfaced that the first
    # pass missed. Real, common, and distinctive enough to earn entries
    # of their own rather than being folded into a neighbour.
    # ----------------------------------------------------------------
    "anatolian rock": _e(
        0.9,
        "Turkish psych: saz through a fuzz pedal, non-Western modes over a "
        "rock rhythm section. Valence stays neutral because the scales read "
        "as neither major nor minor to a Western ear.",
        val=-0.05, eng=0.25, tmp=0.12, aco=0.05, den=0.20, grt=0.28, spa=0.15,
    ),
    "dark jazz": _e(
        0.9,
        "Noir jazz at a crawl. Very slow, very sparse, very reverberant, and "
        "genuinely ominous rather than merely sad.",
        val=-0.35, eng=-0.25, tmp=-0.40, aco=0.30, den=-0.25, spa=0.35,
    ),
    "reggae": _e(
        0.85,
        "Offbeat skank, bass-forward, mid-tempo, and constitutionally warm "
        "even when the lyrics are not.",
        val=0.20, eng=0.05, tmp=-0.10, aco=0.15, den=0.10, spa=0.20,
    ),
    "devotional": _e(
        0.8,
        "Music addressed to something. Elevated rather than cheerful, "
        "acoustic, and almost always recorded in a resonant space.",
        val=0.20, eng=0.05, aco=0.35, den=0.15, spa=0.35,
    ),
})


# ==========================================================================
# ALIASES
# ==========================================================================
# Canonicalisation (casefold, strip accents, punctuation -> space) already
# collapses "Post-Rock", "post_rock", "POST ROCK" and "post rock". What it
# cannot collapse is the run-together spelling and the genuine synonyms, so
# those are enumerated here. Keys are stored pre-folded; values must be
# members of LEXICON.
_RAW_ALIASES: Final[dict[str, str]] = {
    # --- run-together spellings -----------------------------------------
    "postrock": "post rock",
    "postpunk": "post punk",
    "postmetal": "post metal",
    "coldwave": "cold wave",
    "minimalwave": "minimal wave",
    "newwave": "new wave",
    "nowave": "no wave",
    "dreampop": "dream pop",
    "artpop": "art pop",
    "indiepop": "indie pop",
    "indierock": "indie rock",
    "synthwave": "synthwave",
    "synth pop": "synthpop",
    "synth wave": "synthwave",
    "dnb": "drum and bass",
    "d n b": "drum and bass",
    "drum n bass": "drum and bass",
    "drum & bass": "drum and bass",
    "drumandbass": "drum and bass",
    "lofi": "lo fi",
    "lo-fi": "lo fi",
    "low fi": "lo fi",
    "hifi": "hi fi",
    "acapella": "a cappella",
    "hiphop": "hip hop",
    "rnb": "r&b",
    "r n b": "r&b",
    "rhythm and blues": "r&b",
    "trip-hop": "trip hop",
    "triphop": "trip hop",
    "boombap": "boom bap",
    "jazzrap": "jazz rap",
    "downbeat": "downtempo",
    "down tempo": "downtempo",
    "shoe gaze": "shoegaze",
    "gaze": "shoegaze",
    "slow core": "slowcore",
    "sad core": "sadcore",
    "krautrock": "krautrock",
    "kraut rock": "krautrock",
    "kraut": "krautrock",
    "blackmetal": "black metal",
    "deathmetal": "death metal",
    "doommetal": "doom metal",
    "4 track": "four track",
    "4track": "four track",
    "3 am": "3am",
    "sunday": "sunday morning",

    # --- genuine synonyms and near-synonyms ------------------------------
    "melancholic": "melancholy",
    "melancholia": "melancholy",
    "sombre": "melancholy",
    "somber": "melancholy",
    "wistfulness": "wistful",
    "depressing": "sad",
    "sadness": "sad",
    "happiness": "happy",
    "joyful": "happy",
    "cheerful": "happy",
    "upbeat": "uplifting",
    "feel good": "uplifting",
    "euphoria": "euphoric",
    "blissful": "euphoric",
    "sinister": "menacing",
    "ominous": "menacing",
    "threatening": "menacing",
    "creepy": "eerie",
    "unsettling": "eerie",
    "spooky": "eerie",
    "ghostly": "haunting",
    "beautiful but sad": "bittersweet",
    "hypnotising": "hypnotic",
    "hypnotizing": "hypnotic",
    "trancelike": "hypnotic",
    "trance like": "hypnotic",
    "relaxing": "calm",
    "relax": "calm",
    "peaceful": "calm",
    "soothing": "calm",
    "laid back": "mellow",
    "laidback": "mellow",
    "smooth": "mellow",
    "chillout": "chill",
    "chill out": "chill",
    "chilled": "chill",
    "reflective": "contemplative",
    "introspective": "contemplative",
    "pensive": "contemplative",
    "thoughtful": "contemplative",
    "grandiose": "epic",
    "anthemic": "triumphant",
    "harsh": "noise",
    "harsh noise": "noise",
    "brutal": "aggressive",
    "heavy": "aggressive",
    "intense": "aggressive",
    "angsty": "angry",
    "rage": "angry",
    "dreamlike": "dreamy",
    "hazy": "dreamy",
    "otherworldly": "ethereal",
    "celestial": "ethereal",
    "airy": "ethereal",
    "lush": "wall of sound",
    "dense production": "dense",
    "stripped down": "sparse",
    "stripped back": "sparse",
    "bare": "sparse",
    "quiet": "sparse",
    "spacey": "atmospheric",
    "spacy": "atmospheric",
    "ambience": "atmospheric",
    "ambiance": "atmospheric",
    "soundscape": "atmospheric",
    "soundscapes": "atmospheric",
    "cinematic music": "cinematic",
    "filmic": "cinematic",
    "film score": "soundtrack",
    "score": "soundtrack",
    "ost": "soundtrack",
    "reverb drenched": "reverb",
    "reverby": "reverb",
    "echo": "reverb",
    "delay": "reverb",
    "cavernous": "reverb",
    "noisy": "distorted",
    "overdriven": "distorted",
    "saturated": "tape",
    "tape hiss": "tape",
    "tape loops": "tape",
    "analogue": "analog synth",
    "analog": "analog synth",
    "modular": "modular synth",
    "eurorack": "modular synth",
    "sequencer": "berlin school",
    "no vocals": "instrumental",
    "instrumental music": "instrumental",
    "vocal free": "instrumental",
    "acoustic guitar": "acoustic",
    "nylon guitar": "acoustic",
    "solo piano": "piano",
    "sax": "saxophone",
    "orchestra": "orchestral",
    "symphonic": "orchestral",
    "string quartet": "chamber music",
    "classical": "contemporary classical",
    "modern classical": "neoclassical",
    "post classical": "neoclassical",
    "minimalist": "minimalism",
    "steve reich": "minimalism",  # tagged as a genre often enough to matter
    "bedroom": "bedroom pop",
    "diy": "home recording",
    "lo fi bedroom": "bedroom pop",

    # --- genre synonyms --------------------------------------------------
    "intelligent dance music": "idm",
    "braindance": "idm",
    "ambient techno": "dub techno",
    "chain smoking techno": "dub techno",
    "basic channel": "dub techno",
    "detroit techno": "techno",
    "tech house": "house",
    "chicago house": "house",
    "nu disco": "disco",
    "boogie": "disco",
    "electronica": "downtempo",
    "big beat": "breakbeat",
    "2 step": "uk garage",
    "two step": "uk garage",
    "garage": "uk garage",  # ambiguous with garage rock, but on Last.fm the
                            # bare tag skews overwhelmingly UK dance
    "juke": "footwork",
    "ragga jungle": "jungle",
    "atmospheric drum and bass": "drum and bass",
    "liquid dnb": "drum and bass",
    "cosmische": "kosmische",
    "cosmic": "kosmische",
    "space music": "kosmische",
    "psychedelic": "psychedelic rock",
    "psych": "psychedelic rock",
    "psych rock": "psychedelic rock",
    "prog": "progressive rock",
    "prog rock": "progressive rock",
    "krautrock revival": "krautrock",
    "shoegazing": "shoegaze",
    "nu gaze": "shoegaze",
    "blackgaze": "atmospheric black metal",
    "dsbm": "atmospheric black metal",
    "atmospheric bm": "atmospheric black metal",
    "stoner": "stoner rock",
    "stoner metal": "stoner rock",
    "drone metal": "drone",
    "drone doom": "funeral doom",
    "hardcore": "hardcore punk",
    "punk rock": "punk",
    "post hardcore": "emo",
    "screamo": "emo",
    "twinkly": "midwest emo",
    "goth": "gothic rock",
    "gothic": "gothic rock",
    "darkwave": "cold wave",
    "dark wave": "cold wave",
    "ethereal wave": "dream pop",
    "4ad": "dream pop",
    "power noise": "power electronics",
    "harsh noise wall": "power electronics",
    "death industrial": "power electronics",
    "rhythmic noise": "industrial",
    "electronic body music": "ebm",
    "acid": "acid house",
    "acid techno": "acid house",
    "spiritual": "spiritual jazz",
    "astral jazz": "spiritual jazz",
    "cosmic jazz": "spiritual jazz",
    "avant garde jazz": "free jazz",
    "avantgarde jazz": "free jazz",
    "fusion": "jazz fusion",
    "hard bop": "modal jazz",
    "post bop": "modal jazz",
    "bebop": "jazz",
    "smooth jazz": "cool jazz",
    "west coast jazz": "cool jazz",
    "mpb": "bossa nova",
    "brazilian": "bossa nova",
    "tropicalia": "bossa nova",
    "ethiopian jazz": "ethio jazz",
    "ethiopiques": "ethio jazz",
    "ethio": "ethio jazz",
    "tishoumaren": "desert blues",
    "saharan blues": "desert blues",
    "sahel": "desert blues",
    "assouf": "desert blues",
    "touareg": "tuareg",
    "african": "afrobeat",
    "afro beat": "afrobeat",
    "afrobeats": "afrobeat",
    "juju": "highlife",
    "country blues": "delta blues",
    "acoustic blues": "delta blues",
    "rural blues": "delta blues",
    "electric blues": "blues",
    "old time": "bluegrass",
    "appalachian": "bluegrass",
    "folk rock": "folk",
    "acid folk": "freak folk",
    "psych folk": "freak folk",
    "psychedelic folk": "freak folk",
    "wyrd folk": "freak folk",
    "alt-country": "alt country",
    "insurgent country": "alt country",
    "roots": "americana",
    "gospel music": "gospel",
    "soul jazz": "soul",
    "motown": "soul",
    "southern soul": "soul",
    "modern soul": "neo soul",
    "quiet storm": "neo soul",
    "japanese city pop": "city pop",
    "j pop": "city pop",
    "aor": "yacht rock",
    "soft rock": "yacht rock",
    "west coast": "yacht rock",
    "pop": "dance pop",
    "electropop": "synthpop",
    "electro pop": "synthpop",
    "italo": "italo disco",
    "hauntology": "vaporwave",
    "plunderphonics": "vaporwave",
    "mallsoft": "vaporwave",
    "future funk": "vaporwave",
    "trap": "cloud rap",
    "abstract hip hop": "jazz rap",
    "instrumental hip hop": "jazz rap",
    "conscious hip hop": "boom bap",
    "rap": "hip hop",
    "beats": "hip hop",
    "world": "highlife",
    "world music": "highlife",
    "indian classical": "raga",
    "hindustani": "raga",
    "carnatic": "raga",
    "sufi": "qawwali",
    "indonesian": "gamelan",
    "balinese": "gamelan",
    "javanese": "gamelan",
    "portuguese": "fado",
    "spanish guitar": "flamenco",
    "irish": "celtic",
    "scottish": "celtic",
    "concrete": "musique concrete",
    "tape music": "musique concrete",
    "electroacoustic": "musique concrete",
    "found sound": "field recording",
    "environmental": "field recording",
    "nature sounds": "field recording",
    "healing": "new age",
    "meditation": "meditative",
    "yoga": "meditative",
    "sleep music": "sleep",
    "insomnia": "3am",
    "night": "late night",
    "nocturnal": "late night",
    "midnight": "late night",
    "after hours": "late night",
    "rain": "rainy day",
    "rainy": "rainy day",
    "rainy days": "rainy day",
    "raining": "rainy day",
    "grey": "rainy day",
    "gray": "rainy day",
    "overcast": "fog",
    "misty": "fog",
    "foggy": "fog",
    "hazy weather": "fog",
    "thunderstorm": "storm",
    "stormy": "storm",
    "wind": "storm",
    "snow": "winter",
    "cold": "winter",
    "frost": "winter",
    "christmas": "winter",
    "fall": "autumn",
    "summertime": "summer",
    "sunshine": "summer",
    "sunny": "summer",
    "heat": "summer",
    "springtime": "spring",
    "surf": "beach",
    "tropical": "beach",
    "arid": "desert",
    "sahara": "desert",
    "dusty": "desert",
    "cars": "driving",
    "highway": "driving",
    "motorway": "driving",
    "roadtrip": "road trip",
    "cruising": "night drive",
    "gym": "workout",
    "running": "workout",
    "exercise": "workout",
    "studying": "study",
    "concentration": "study",
    "focus": "study",
    "background music": "study",
    "cafe": "coffee shop",
    "coffeehouse": "coffee shop",
    "dance": "party",
    "club": "party",
    "banger": "party",
    "sunday morning music": "sunday morning",
    "lazy sunday": "sunday morning",

    # --- instrument names, which listeners use as genre tags --------------
    "cello": "strings",
    "harp": "strings",
    "violin": "strings",
    "double bass": "strings",
    "oud": "acoustic",
    "saz": "anatolian rock",
    "brass": "horns",
    "trumpet": "horns",
    "flute": "horns",
    "organ": "gospel",
    "synthesizer": "analog synth",
    "drum machine": "minimal wave",
    "percussion": "tribal",
    "low end": "bass",
    "sub bass": "bass",

    # --- compound genre names seen in the seed corpus ---------------------
    "doom jazz": "dark jazz",
    "noir jazz": "dark jazz",
    "indie folk": "folk",
    "contemporary folk": "folk",
    "industrial metal": "industrial",
    "jazz funk": "funk",
    "soul funk": "funk",
    "sahrawi": "desert blues",
    "western sahara": "desert blues",
    "turkish psych": "anatolian rock",
    "turkish": "anatolian rock",
    "dub reggae": "dub",
    "roots reggae": "reggae",
    "ska": "reggae",
    "dancehall": "reggae",
    "spiritual music": "devotional",
    "sacred": "devotional",
    "hymn": "devotional",
    "mantra": "devotional",
    "grooves": "groove",
    "funky": "groove",
    "danceable": "groove",
    "hot": "warm",
    "warmth": "warm",
    "close miked": "dry",
    "deadpan": "dry",
    "loud quiet loud": "dynamic",
}

#: Public alias map: folded surface form -> canonical lexicon key.
#: Entries that fold onto themselves (``"lo-fi"`` -> ``"lo fi"``,
#: ``"trip-hop"`` -> ``"trip hop"``) are dropped: folding already handles
#: them, and keeping them would shadow the real entry.
ALIASES: Final[dict[str, str]] = {
    folded_key: folded_value
    for folded_key, folded_value in (
        (_fold(k), _fold(v)) for k, v in _RAW_ALIASES.items()
    )
    if folded_key != folded_value
}

#: Every tag the lexicon has an opinion about, in canonical form.
KNOWN_TAGS: Final[frozenset[str]] = frozenset(LEXICON)


def _validate_lexicon() -> None:
    """Fail at import time rather than at 3am, if the tables disagree."""
    dangling = {alias: target for alias, target in ALIASES.items() if target not in LEXICON}
    if dangling:
        raise RuntimeError(f"aliases pointing at unknown lexicon entries: {sorted(dangling)}")
    unfolded = [tag for tag in LEXICON if _fold(tag) != tag]
    if unfolded:
        raise RuntimeError(f"lexicon keys must already be in canonical form: {sorted(unfolded)}")
    # An alias that shadows a real entry would be silently unreachable.
    shadowed = sorted(set(ALIASES) & set(LEXICON))
    if shadowed:
        raise RuntimeError(f"aliases shadowing real lexicon entries: {shadowed}")


_validate_lexicon()


# ==========================================================================
# THE ESTIMATOR
# ==========================================================================
#: How fast a dimension approaches its asserted value as evidence accumulates.
#: value = 0.5 + mean_delta * (w / (w + K)). With K = 0.35 a single
#: full-confidence tag realises ~74% of its delta, two realise ~85%, four
#: ~92%. A lone tag should move a dimension decisively but never pin it.
_SATURATION_K: Final[float] = 0.35

#: Confidence reaches ~0.5 at three recognised tags, ~0.8 at twelve.
_CONFIDENCE_K: Final[float] = 3.0


def canonical_tag(tag: str) -> str | None:
    """Fold *tag* and resolve aliases. Returns ``None`` if unrecognised.

    >>> canonical_tag("Post-Rock") == canonical_tag("postrock") == "post rock"
    True
    >>> canonical_tag("entirely made up") is None
    True
    """
    folded = _fold(tag)
    if not folded:
        return None
    if folded in LEXICON:
        return folded
    aliased = ALIASES.get(folded)
    if aliased in LEXICON:
        return aliased
    # Last.fm users pluralise freely: "ballads", "breaks", "drones".
    if folded.endswith("s"):
        singular = folded[:-1]
        if singular in LEXICON:
            return singular
        aliased = ALIASES.get(singular)
        if aliased in LEXICON:
            return aliased
    return None


def canonical_tags(tags: Iterable[str]) -> list[str]:
    """Canonicalise an iterable, dropping unknowns and preserving first-seen order."""
    seen: dict[str, None] = {}
    for tag in tags:
        canon = canonical_tag(tag)
        if canon is not None and canon not in seen:
            seen[canon] = None
    return list(seen)


def _as_weighted(tags: Sequence[str] | Mapping[str, float]) -> dict[str, float]:
    """Normalise the two accepted input shapes into ``canonical -> 0..1 weight``.

    A plain list is treated as uniform weight 1.0. A mapping is Last.fm's
    ``tag -> count``, which is rescaled so the *largest* count becomes 1.0;
    the absolute magnitude is meaningless (``artist.getTopTags`` uses 0..100,
    ``user.getTopTags`` uses raw scrobble counts) but the ratios are not.

    Duplicate tags that collapse onto the same canonical form take the larger
    of the two weights rather than summing, so that a set containing both
    "post-rock" and "postrock" is not counted twice.
    """
    if isinstance(tags, Mapping):
        raw: dict[str, float] = {}
        for tag, count in tags.items():
            canon = canonical_tag(tag)
            if canon is None:
                continue
            try:
                value = float(count)
            except (TypeError, ValueError):
                value = 0.0
            raw[canon] = max(raw.get(canon, 0.0), max(0.0, value))
        if not raw:
            return {}
        peak = max(raw.values())
        if peak <= 0.0:
            # All-zero counts still carry membership information.
            return {tag: 1.0 for tag in raw}
        return {tag: value / peak for tag, value in raw.items()}

    return {tag: 1.0 for tag in canonical_tags(tags)}


def recognised_tags(tags: Sequence[str] | Mapping[str, float]) -> list[str]:
    """The canonical tags from *tags* the lexicon actually knows."""
    return list(_as_weighted(tags))


def tag_coverage(tags: Sequence[str] | Mapping[str, float]) -> float:
    """Fraction of the supplied tags that the lexicon recognises, 0..1."""
    total = len(tags)
    if not total:
        return 0.0
    return len(recognised_tags(tags)) / float(total)


def estimate_with_confidence(
    tags: Sequence[str] | Mapping[str, float],
) -> tuple[SonicVector, float]:
    """Estimate a :class:`SonicVector` and report how much to trust it.

    Pure and deterministic: same input, same output, no network, no clock.

    Per dimension, only the tags that actually assert something about that
    dimension contribute. Their deltas are combined as a weighted mean — so
    a set of tags that disagree cancel out rather than compounding — and then
    scaled by a saturation term that grows with the total evidence weight.

    Returns the neutral vector and 0.0 confidence if nothing was recognised,
    which is the correct answer to "what does this untagged track sound
    like": we do not know.
    """
    weighted = _as_weighted(tags)
    if not weighted:
        return SonicVector.neutral(), 0.0

    numerator: dict[str, float] = {dim: 0.0 for dim in SONIC_DIMS}
    denominator: dict[str, float] = {dim: 0.0 for dim in SONIC_DIMS}

    for tag, input_weight in weighted.items():
        profile = LEXICON[tag]
        weight = input_weight * profile.weight
        if weight <= 0.0:
            continue
        for dim, delta in profile.deltas.items():
            numerator[dim] += delta * weight
            denominator[dim] += weight

    values: list[float] = []
    for dim in SONIC_DIMS:
        evidence = denominator[dim]
        if evidence <= 0.0:
            values.append(0.5)
            continue
        mean_delta = numerator[dim] / evidence
        saturation = evidence / (evidence + _SATURATION_K)
        values.append(clamp(0.5 + mean_delta * saturation))

    # Confidence rides on the amount of recognised evidence, tempered by how
    # much of the input we had to throw away. Forty scrobbles of "rock" is
    # not the same evidence as forty tags of "dub techno".
    evidence_total = sum(LEXICON[t].weight * w for t, w in weighted.items())
    breadth = evidence_total / (evidence_total + _CONFIDENCE_K)
    coverage = tag_coverage(tags)
    confidence = clamp(breadth * (0.55 + 0.45 * coverage))

    return SonicVector.from_array(values), confidence


def estimate_from_tags(tags: Sequence[str] | Mapping[str, float]) -> SonicVector:
    """The ``/audio-features`` replacement.

    Accepts either a plain list of tags or Last.fm's ``tag -> count`` mapping.
    Never raises, never touches the network, always returns a vector; an
    unrecognised tag set yields exactly :meth:`SonicVector.neutral`.
    """
    vector, _ = estimate_with_confidence(tags)
    return vector


def tag_affinity(
    tags: Sequence[str] | Mapping[str, float],
    corridor_tags: Sequence[str],
) -> float:
    """How well a tag set sits inside a genre corridor, 0..1.

    Three sources of credit, in descending order of confidence:

    1. **Direct overlap.** The tag set literally contains a corridor tag.
       Weighted by the input weights, so a track whose *top* tag is
       "krautrock" scores higher than one where it is a footnote.
    2. **Sonic proximity.** Even with no shared vocabulary, a track can sit
       inside the corridor's sound. Cosine-free: a plain normalised distance
       between the two estimated vectors, inverted.
    3. Nothing else. An empty corridor means "no constraint" and returns 1.0,
       matching :meth:`GenreCorridor.any`.

    The blend is deliberately overlap-heavy (0.65/0.35): a corridor is a
    statement about vocabulary first and timbre second. Two records can
    measure identically and still not belong on the same playlist.
    """
    corridor_canon = set(canonical_tags(corridor_tags))
    if not corridor_canon:
        return 1.0

    weighted = _as_weighted(tags)
    if not weighted:
        return 0.0

    total_weight = sum(weighted.values()) or 1.0
    hit_weight = sum(w for tag, w in weighted.items() if tag in corridor_canon)
    # Square-root so that a single strong hit already counts for a lot; a
    # track does not need to be *entirely* krautrock to belong in the
    # krautrock corridor.
    overlap = (hit_weight / total_weight) ** 0.5

    track_vector = estimate_from_tags(weighted)
    corridor_vector = estimate_from_tags(sorted(corridor_canon))
    # `distance` is a weighted RMS over dims already in 0..1, so it is itself
    # bounded by 1.0 and needs no further scaling.
    proximity = clamp(1.0 - track_vector.distance(corridor_vector))

    return clamp(0.65 * overlap + 0.35 * proximity)

"""BAROGROOVE's offline seed corpus.

A hand-curated body of real records, tagged the way Last.fm's community would
tag them, spanning all eight BAROGROOVE themes and the main genre corridors.
It exists so that ``forge_playlist`` produces a genuinely good, genuinely
explained playlist with no network and no credentials — the demo path, and an
explicit acceptance criterion — and so the test suite has something honest to
assert against.

The data is deliberately plain: a frozen dataclass and tuples, with no
dependency on ``pydantic`` or on ``backend.app.contracts``. That keeps the
fixture importable from anywhere in the tree (tests, the offline oracle, a
notebook) without dragging the application package along with it.
``backend/app/lastfm/offline.py`` converts these into ``Track`` instances.

Curation notes
--------------
* Tags are what a Last.fm listener would plausibly have applied, not a
  taxonomy. That means overlap, inconsistency and the occasional mood word —
  which is exactly the input the lexicon is built to eat.
* Every track is assigned to one or two themes. One is the common case; a
  second is used only where a record genuinely reads both ways, such as
  Talk Talk's *Laughing Stock*, which is petrichor and first frost at once.
* Nothing here is filler. If a track is in this list it is because it is the
  right answer to some weather.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

__all__ = [
    "SeedTrack",
    "SEED_CORPUS",
    "THEMES",
    "THEME_TAGS",
    "CORRIDOR_TAGS",
    "by_theme",
    "all_tags",
]


#: The eight BAROGROOVE themes, in the order the product uses them.
THEMES: Final[tuple[str, ...]] = (
    "petrichor",
    "golden_hour",
    "nordic_fog",
    "storm_front",
    "heatwave_cruise",
    "blue_hour",
    "first_frost",
    "sirocco",
)

#: The tag vocabulary each theme reaches for. These are real Last.fm tags,
#: not invented ones, so the same strings work against the live API.
THEME_TAGS: Final[dict[str, tuple[str, ...]]] = {
    "petrichor": ("rainy day", "ambient", "post rock", "slowcore", "dreamy", "melancholy"),
    "golden_hour": ("soul", "spiritual jazz", "bossa nova", "summer", "uplifting", "warm"),
    "nordic_fog": ("ambient", "modern classical", "drone", "winter", "eerie", "atmospheric"),
    "storm_front": ("industrial", "noise rock", "post punk", "menacing", "aggressive", "storm"),
    "heatwave_cruise": ("krautrock", "desert blues", "afrobeat", "driving", "disco", "summer"),
    "blue_hour": ("trip hop", "dub techno", "dream pop", "late night", "downtempo", "neo soul"),
    "first_frost": ("folk", "neoclassical", "slowcore", "winter", "wistful", "sparse"),
    "sirocco": ("desert blues", "drone", "raga", "psychedelic rock", "desert", "hypnotic"),
}

#: The genre corridors the engine can be constrained to. A corridor narrows
#: the pool without changing the weather.
CORRIDOR_TAGS: Final[dict[str, tuple[str, ...]]] = {
    "any": (),
    "ambient": ("ambient", "drone", "atmospheric", "minimal"),
    "krautrock": ("krautrock", "motorik", "kosmische", "space rock"),
    "shoegaze": ("shoegaze", "dream pop", "wall of sound", "reverb"),
    "jazz": ("spiritual jazz", "modal jazz", "free jazz", "jazz"),
    "electronic": ("dub techno", "techno", "idm", "downtempo"),
    "folk": ("folk", "singer songwriter", "acoustic", "freak folk"),
    "soul": ("soul", "neo soul", "funk", "gospel"),
    "heavy": ("post metal", "doom metal", "noise rock", "industrial"),
    "global": ("desert blues", "afrobeat", "ethio jazz", "raga"),
}


@dataclass(frozen=True, slots=True)
class SeedTrack:
    """One curated record.

    ``duration_ms`` is approximate to the nearest few seconds; it is there so
    the sequencer can budget a playlist length, not so anyone can cue it.
    """

    artist: str
    title: str
    album: str | None = None
    year: int | None = None
    duration_ms: int | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    themes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def key(self) -> str:
        """Mirrors ``contracts.Track.key`` closely enough for fixture use."""
        return f"{self.artist.casefold()}|{self.title.casefold()}"


def _t(
    artist: str,
    title: str,
    album: str,
    year: int,
    seconds: int,
    tags: str,
    themes: str,
) -> SeedTrack:
    """Compact constructor. ``tags`` and ``themes`` are comma-separated."""
    return SeedTrack(
        artist=artist,
        title=title,
        album=album,
        year=year,
        duration_ms=seconds * 1000,
        tags=tuple(t.strip() for t in tags.split(",") if t.strip()),
        themes=tuple(t.strip() for t in themes.split(",") if t.strip()),
    )


# ==========================================================================
# THE CORPUS
# ==========================================================================
SEED_CORPUS: Final[tuple[SeedTrack, ...]] = (
    # ----------------------------------------------------------------
    # PETRICHOR — after the rain, not during it. Wet, patient, hopeful
    # in a way that stops short of cheerful.
    # ----------------------------------------------------------------
    _t("Talk Talk", "New Grass", "Laughing Stock", 1991, 578,
       "post rock, art rock, ambient, jazz, atmospheric, bittersweet, rainy day",
       "petrichor, first_frost"),
    _t("Talk Talk", "I Believe in You", "Spirit of Eden", 1988, 388,
       "art rock, post rock, melancholy, atmospheric, reverb, rainy day",
       "petrichor"),
    _t("Mark Hollis", "A Life (1895-1915)", "Mark Hollis", 1998, 508,
       "singer songwriter, sparse, acoustic, minimal, contemplative, rainy day",
       "petrichor, first_frost"),
    _t("Bark Psychosis", "Absent Friend", "Hex", 1994, 391,
       "post rock, dream pop, atmospheric, melancholy, reverb, rainy day",
       "petrichor"),
    _t("Grouper", "Heavy Water/I'd Rather Be Sleeping", "Dragging a Dead Deer Up a Hill", 2008, 232,
       "ambient, dream pop, lo fi, tape, ethereal, rainy day, melancholy",
       "petrichor, nordic_fog"),
    _t("Burial", "Archangel", "Untrue", 2007, 236,
       "uk garage, dubstep, downtempo, rainy day, melancholy, atmospheric, late night",
       "petrichor, blue_hour"),
    _t("Burial", "Night Bus", "Burial", 2006, 143,
       "ambient, dubstep, rainy day, late night, field recording, atmospheric",
       "petrichor, blue_hour"),
    _t("Slowdive", "Dagger", "Souvlaki", 1993, 210,
       "shoegaze, dream pop, acoustic, melancholy, reverb, rainy day",
       "petrichor"),
    _t("Slowdive", "Souvlaki Space Station", "Souvlaki", 1993, 353,
       "shoegaze, dream pop, wall of sound, reverb, hypnotic, atmospheric",
       "petrichor, blue_hour"),
    _t("Low", "Sunflower", "Things We Lost in the Fire", 2001, 259,
       "slowcore, sadcore, minimal, sparse, melancholy, rainy day",
       "petrichor, first_frost"),
    _t("Codeine", "Sea", "Frigid Stars", 1990, 322,
       "slowcore, sadcore, minimal, melancholy, distorted, sparse",
       "petrichor, first_frost"),
    _t("Duster", "Inside Out", "Stratosphere", 1998, 172,
       "slowcore, lo fi, space rock, tape, sparse, melancholy",
       "petrichor"),
    _t("Boards of Canada", "Everything You Do Is a Balloon", "Music Has the Right to Children", 1998, 424,
       "idm, downtempo, ambient, nostalgic, tape, hypnotic, rainy day",
       "petrichor, blue_hour"),
    _t("Loscil", "Sturgeon", "Submers", 2002, 393,
       "ambient, dub techno, minimal, atmospheric, hypnotic, rainy day",
       "petrichor, nordic_fog"),
    _t("Gas", "Pop 1", "Pop", 2000, 618,
       "ambient, dub techno, drone, hypnotic, atmospheric, repetitive",
       "petrichor, nordic_fog"),
    _t("Brian Eno", "An Ending (Ascent)", "Apollo: Atmospheres and Soundtracks", 1983, 265,
       "ambient, drone, ethereal, atmospheric, instrumental, calm",
       "petrichor, nordic_fog"),
    _t("Harold Budd & Brian Eno", "The Pearl", "The Pearl", 1984, 253,
       "ambient, piano, reverb, minimal, dreamy, calm",
       "petrichor"),
    _t("Julianna Barwick", "The Harbinger", "Nepenthe", 2013, 246,
       "ambient, a cappella, ethereal, reverb, choral, atmospheric",
       "petrichor, nordic_fog"),
    _t("Arthur Russell", "A Little Lost", "Another Thought", 1994, 195,
       "singer songwriter, minimal, bedroom pop, bittersweet, strings, lo fi",
       "petrichor, blue_hour"),
    _t("Arthur Russell", "This Is How We Walk on the Moon", "Another Thought", 1994, 289,
       "minimal, avant garde jazz, strings, hypnotic, bittersweet, repetitive",
       "petrichor, sirocco"),
    _t("Sibylle Baier", "Tonight", "Colour Green", 2006, 178,
       "folk, singer songwriter, acoustic, lo fi, home recording, melancholy",
       "petrichor, first_frost"),
    _t("Nick Drake", "Northern Sky", "Bryter Layter", 1971, 217,
       "folk, singer songwriter, acoustic, strings, bittersweet, wistful",
       "petrichor, golden_hour"),

    # ----------------------------------------------------------------
    # GOLDEN HOUR — low sun, warm air, and music that is generous
    # rather than merely happy. Spiritual jazz sits here for the
    # elevation, not the cheer.
    # ----------------------------------------------------------------
    _t("Alice Coltrane", "Journey in Satchidananda", "Journey in Satchidananda", 1971, 396,
       "spiritual jazz, modal jazz, harp, hypnotic, raga, meditative",
       "golden_hour, sirocco"),
    _t("Alice Coltrane", "Turiya and Ramakrishna", "Ptah, the El Daoud", 1970, 481,
       "spiritual jazz, modal jazz, piano, blues, contemplative, warm",
       "golden_hour"),
    _t("Pharoah Sanders", "The Creator Has a Master Plan", "Karma", 1969, 1967,
       "spiritual jazz, free jazz, long songs, uplifting, saxophone, improvisation",
       "golden_hour"),
    _t("Floating Points & Pharoah Sanders", "Movement 6", "Promises", 2021, 344,
       "spiritual jazz, ambient, minimalism, strings, contemplative, atmospheric",
       "golden_hour, sirocco"),
    _t("Dorothy Ashby", "Soul Vibrations", "Afro-Harping", 1968, 165,
       "soul jazz, funk, harp, warm, uplifting, sample based",
       "golden_hour"),
    _t("Don Cherry", "Brown Rice", "Brown Rice", 1975, 500,
       "spiritual jazz, jazz fusion, raga, hypnotic, world, improvisation",
       "golden_hour, sirocco"),
    _t("Elis Regina & Antonio Carlos Jobim", "Aguas de Marco", "Elis & Tom", 1974, 209,
       "bossa nova, mpb, brazilian, acoustic, playful, warm",
       "golden_hour"),
    _t("Joao Gilberto", "Chega de Saudade", "Chega de Saudade", 1959, 121,
       "bossa nova, brazilian, acoustic, nylon guitar, bittersweet, mellow",
       "golden_hour"),
    _t("Arthur Verocai", "Caboclo", "Arthur Verocai", 1972, 217,
       "mpb, brazilian, strings, jazz fusion, warm, orchestral",
       "golden_hour"),
    _t("Marcos Valle", "Estrelar", "Vontade de Rever Voce", 1983, 320,
       "brazilian, boogie, disco, funk, summer, uplifting",
       "golden_hour, heatwave_cruise"),
    _t("Milton Nascimento", "Cravo e Canela", "Clube da Esquina", 1972, 145,
       "mpb, brazilian, folk, warm, uplifting, acoustic",
       "golden_hour"),
    _t("Roy Ayers", "Everybody Loves the Sunshine", "Everybody Loves the Sunshine", 1976, 267,
       "soul, jazz funk, summer, mellow, hypnotic, warm",
       "golden_hour, heatwave_cruise"),
    _t("Curtis Mayfield", "Move On Up", "Curtis", 1970, 528,
       "soul, funk, uplifting, horns, driving, summer",
       "golden_hour, heatwave_cruise"),
    _t("Bill Withers", "Lovely Day", "Menagerie", 1977, 254,
       "soul, funk, uplifting, happy, summer, warm",
       "golden_hour"),
    _t("Minnie Riperton", "Les Fleurs", "Come to My Garden", 1970, 213,
       "soul, orchestral, strings, euphoric, uplifting, romantic",
       "golden_hour"),
    _t("Terry Callier", "Dancing Girl", "What Color Is Love", 1972, 552,
       "soul, folk, spiritual jazz, strings, long songs, contemplative",
       "golden_hour"),
    _t("Nina Simone", "Feeling Good", "I Put a Spell on You", 1965, 175,
       "soul, jazz, orchestral, triumphant, female vocalists, uplifting",
       "golden_hour"),
    _t("Sam Cooke", "A Change Is Gonna Come", "Ain't That Good News", 1964, 191,
       "soul, gospel, orchestral, bittersweet, strings, uplifting",
       "golden_hour"),
    _t("The Staple Singers", "I'll Take You There", "Be Altitude: Respect Yourself", 1972, 278,
       "soul, gospel, funk, uplifting, warm, happy",
       "golden_hour"),
    _t("Aretha Franklin", "Wholy Holy", "Amazing Grace", 1972, 320,
       "gospel, soul, live, choral, reverb, uplifting",
       "golden_hour"),
    _t("Donny Hathaway", "A Song for You", "Donny Hathaway", 1971, 316,
       "soul, piano, romantic, bittersweet, warm, live",
       "golden_hour, blue_hour"),
    _t("Tatsuro Yamashita", "Ride on Time", "Ride on Time", 1980, 315,
       "city pop, funk, summer, uplifting, hi fi, driving",
       "golden_hour, heatwave_cruise"),
    _t("Mariya Takeuchi", "Plastic Love", "Variety", 1984, 479,
       "city pop, disco, bittersweet, late night, hi fi, female vocalists",
       "golden_hour, blue_hour"),
    _t("Anri", "Last Summer Whisper", "Heaven Beach", 1982, 322,
       "city pop, aor, summer, mellow, warm, beach",
       "golden_hour, heatwave_cruise"),
    _t("Khruangbin", "August 10", "Con Todo El Mundo", 2018, 232,
       "psychedelic, funk, instrumental, dub, mellow, summer",
       "golden_hour, heatwave_cruise"),

    # ----------------------------------------------------------------
    # NORDIC FOG — cold, wide, low visibility. The reverb here is an
    # empty landscape rather than a cathedral.
    # ----------------------------------------------------------------
    _t("Sigur Ros", "Svefn-g-englar", "Agaetis Byrjun", 1999, 601,
       "post rock, ambient, ethereal, reverb, long songs, atmospheric, winter",
       "nordic_fog"),
    _t("Johann Johannsson", "Odi et Amo", "Englaborn", 2002, 240,
       "modern classical, neoclassical, strings, ethereal, melancholy, winter",
       "nordic_fog, first_frost"),
    _t("Olafur Arnalds", "Near Light", "Living Room Songs", 2011, 197,
       "neoclassical, piano, strings, wistful, minimal, winter",
       "nordic_fog, first_frost"),
    _t("Arvo Part", "Spiegel im Spiegel", "Alina", 1999, 606,
       "minimalism, modern classical, piano, sparse, meditative, calm",
       "nordic_fog, first_frost"),
    _t("Arvo Part", "Fur Alina", "Alina", 1999, 641,
       "minimalism, solo piano, sparse, contemplative, quiet, modern classical",
       "nordic_fog, first_frost"),
    _t("Biosphere", "Kobresia", "Substrata", 1997, 288,
       "ambient, field recording, atmospheric, winter, minimal, eerie",
       "nordic_fog"),
    _t("Deathprod", "Treetop Drive 1", "Treetop Drive", 1994, 787,
       "dark ambient, drone, eerie, atmospheric, long songs, minimal",
       "nordic_fog"),
    _t("Jan Garbarek & The Hilliard Ensemble", "Parce Mihi Domine", "Officium", 1994, 386,
       "choral, spiritual jazz, saxophone, reverb, contemplative, ethereal",
       "nordic_fog, golden_hour"),
    _t("Nils Frahm", "Says", "Spaces", 2013, 517,
       "neoclassical, minimalism, analog synth, piano, hypnotic, uplifting",
       "nordic_fog"),
    _t("Mum", "Green Grass of Tunnel", "Finally We Are No One", 2002, 292,
       "idm, ambient, glitch, ethereal, dreamy, winter",
       "nordic_fog"),
    _t("Alva Noto & Ryuichi Sakamoto", "Logic Moon", "Insen", 2005, 260,
       "glitch, minimal, modern classical, piano, sparse, eerie",
       "nordic_fog"),
    _t("Tim Hecker", "The Piano Drop", "Ravedeath, 1972", 2011, 258,
       "drone, ambient, noise, distorted, atmospheric, eerie",
       "nordic_fog, storm_front"),
    _t("Fennesz", "Endless Summer", "Endless Summer", 2001, 214,
       "glitch, ambient, drone, distorted, dreamy, atmospheric",
       "nordic_fog, petrichor"),
    _t("Stars of the Lid", "Requiem for Dying Mothers, Pt. 1", "The Tired Sounds of Stars of the Lid", 2001, 401,
       "drone, ambient, strings, minimal, meditative, melancholy",
       "nordic_fog, first_frost"),
    _t("Bohren & der Club of Gore", "Prowler", "Black Earth", 2002, 496,
       "dark jazz, doom jazz, drone, saxophone, menacing, late night",
       "nordic_fog, blue_hour"),
    _t("Wolves in the Throne Room", "Prayer of Transformation", "Two Hunters", 2007, 700,
       "atmospheric black metal, post metal, distorted, long songs, winter, epic",
       "nordic_fog, storm_front"),
    _t("Burzum", "Dunkelheit", "Filosofem", 1996, 428,
       "black metal, atmospheric black metal, lo fi, hypnotic, dark, winter",
       "nordic_fog, storm_front"),
    _t("Alcest", "Ecailles de Lune, Pt. 1", "Ecailles de Lune", 2010, 585,
       "blackgaze, shoegaze, atmospheric black metal, reverb, melancholy, epic",
       "nordic_fog, storm_front"),
    _t("Ulver", "Wolf and Fear", "Bergtatt", 1995, 328,
       "black metal, folk, atmospheric, choral, winter, eerie",
       "nordic_fog"),
    _t("Hildur Gudnadottir", "Erupting Light", "Saman", 2014, 293,
       "modern classical, cello, drone, sparse, melancholy, winter",
       "nordic_fog, first_frost"),
)

SEED_CORPUS = SEED_CORPUS + (
    # ----------------------------------------------------------------
    # STORM FRONT — pressure dropping. Weight, turbulence and threat.
    # The jungle entries belong here for the same reason the doom ones
    # do: both are about a system under load.
    # ----------------------------------------------------------------
    _t("Godspeed You! Black Emperor", "The Dead Flag Blues", "F# A# Infinity", 1997, 973,
       "post rock, drone, spoken word, cinematic, menacing, long songs, epic",
       "storm_front"),
    _t("Swans", "Screen Shot", "To Be Kind", 2014, 465,
       "no wave, post punk, industrial, repetitive, menacing, aggressive",
       "storm_front"),
    _t("Swans", "A Little God in My Hands", "To Be Kind", 2014, 424,
       "no wave, industrial, funk, aggressive, distorted, hypnotic",
       "storm_front"),
    _t("Neurosis", "Locust Star", "Through Silver in Blood", 1996, 401,
       "post metal, sludge, doom metal, aggressive, distorted, epic",
       "storm_front"),
    _t("Sunn O)))", "Big Church", "Monoliths & Dimensions", 2009, 585,
       "drone metal, doom metal, choral, drone, menacing, reverb",
       "storm_front, nordic_fog"),
    _t("Godflesh", "Like Rats", "Streetcleaner", 1989, 279,
       "industrial metal, sludge, distorted, repetitive, menacing, aggressive",
       "storm_front"),
    _t("Throbbing Gristle", "Hamburger Lady", "D.o.A: The Third and Final Report", 1978, 250,
       "industrial, power electronics, noise, eerie, dark, distorted",
       "storm_front"),
    _t("Einsturzende Neubauten", "Halber Mensch", "Halber Mensch", 1985, 240,
       "industrial, a cappella, noise, polyrhythmic, aggressive, menacing",
       "storm_front"),
    _t("Public Image Ltd", "Poptones", "Metal Box", 1979, 350,
       "post punk, dub, repetitive, menacing, bass, hypnotic",
       "storm_front, blue_hour"),
    _t("Joy Division", "Atrocity Exhibition", "Closer", 1980, 366,
       "post punk, cold wave, tribal, menacing, dark, distorted",
       "storm_front"),
    _t("The Birthday Party", "Release the Bats", "Release the Bats", 1981, 168,
       "post punk, no wave, garage rock, aggressive, distorted, angry",
       "storm_front"),
    _t("Shellac", "Prayer to God", "1000 Hurts", 2000, 220,
       "noise rock, post hardcore, dry, angry, distorted, minimal",
       "storm_front"),
    _t("Slint", "Good Morning, Captain", "Spiderland", 1991, 469,
       "post rock, slowcore, math rock, spoken word, menacing, dynamic",
       "storm_front, petrichor"),
    _t("My Bloody Valentine", "You Made Me Realise", "You Made Me Realise", 1988, 229,
       "shoegaze, noise rock, wall of sound, distorted, aggressive, reverb",
       "storm_front"),
    _t("Photek", "Ni Ten Ichi Ryu", "Modus Operandi", 1997, 402,
       "drum and bass, jungle, minimal, menacing, polyrhythmic, hypnotic",
       "storm_front, blue_hour"),
    _t("Source Direct", "Snake Style", "Exorcise the Demons", 1999, 388,
       "drum and bass, jungle, dark, menacing, breakbeat, atmospheric",
       "storm_front"),
    _t("Goldie", "Inner City Life", "Timeless", 1995, 470,
       "drum and bass, jungle, atmospheric, strings, euphoric, breakbeat",
       "storm_front, blue_hour"),
    _t("Dillinja", "The Angels Fell", "The Angels Fell", 1995, 344,
       "jungle, drum and bass, ragga jungle, breakbeat, menacing, bass",
       "storm_front"),
    _t("Autechre", "Gantz Graf", "Gantz Graf", 2002, 240,
       "idm, glitch, breakbeat, aggressive, distorted, polyrhythmic",
       "storm_front"),
    _t("Aphex Twin", "Come to Daddy (Pappy Mix)", "Come to Daddy", 1997, 251,
       "idm, breakbeat, industrial, aggressive, distorted, menacing",
       "storm_front"),
    _t("Nine Inch Nails", "The Great Destroyer", "Year Zero", 2007, 217,
       "industrial, ebm, glitch, aggressive, distorted, angry",
       "storm_front"),
    _t("Portishead", "Machine Gun", "Third", 2008, 291,
       "trip hop, industrial, menacing, distorted, minimal, dark",
       "storm_front, blue_hour"),

    # ----------------------------------------------------------------
    # HEATWAVE CRUISE — forward motion in high temperature. Motorik and
    # desert blues are the same idea approached from opposite ends of
    # the map: a loop you do not get off.
    # ----------------------------------------------------------------
    _t("Neu!", "Hallogallo", "Neu!", 1972, 610,
       "krautrock, motorik, repetitive, driving, instrumental, hypnotic",
       "heatwave_cruise"),
    _t("Neu!", "Fur Immer", "Neu! 2", 1973, 671,
       "krautrock, motorik, driving, distorted, repetitive, long songs",
       "heatwave_cruise"),
    _t("Harmonia", "Watussi", "Musik von Harmonia", 1974, 285,
       "krautrock, kosmische, analog synth, playful, hypnotic, instrumental",
       "heatwave_cruise"),
    _t("Harmonia", "Dino", "Musik von Harmonia", 1974, 208,
       "krautrock, kosmische, motorik, driving, analog synth, repetitive",
       "heatwave_cruise"),
    _t("Cluster", "Hollywood", "Zuckerzeit", 1974, 293,
       "krautrock, kosmische, analog synth, playful, minimal, repetitive",
       "heatwave_cruise, blue_hour"),
    _t("Can", "Vitamin C", "Ege Bamyasi", 1972, 208,
       "krautrock, funk, psychedelic rock, driving, hypnotic, groove",
       "heatwave_cruise"),
    _t("Can", "Halleluwah", "Tago Mago", 1971, 1121,
       "krautrock, motorik, psychedelic rock, long songs, repetitive, driving",
       "heatwave_cruise"),
    _t("La Dusseldorf", "Rheinita", "Viva", 1978, 505,
       "krautrock, motorik, kosmische, euphoric, driving, analog synth",
       "heatwave_cruise"),
    _t("Kraftwerk", "Autobahn", "Autobahn", 1974, 1382,
       "krautrock, kosmische, analog synth, driving, long songs, motorik",
       "heatwave_cruise"),
    _t("Popol Vuh", "Aguirre I (Lacrime di Rei)", "Aguirre", 1975, 366,
       "kosmische, krautrock, drone, choral, meditative, soundtrack",
       "heatwave_cruise, sirocco"),
    _t("Tinariwen", "Cler Achel", "Aman Iman: Water Is Life", 2007, 275,
       "desert blues, tuareg, hypnotic, driving, world, repetitive",
       "heatwave_cruise, sirocco"),
    _t("Tinariwen", "Tenere Taqqim Tossam", "Tassili", 2011, 244,
       "desert blues, tuareg, acoustic, hypnotic, desert, world",
       "sirocco, heatwave_cruise"),
    _t("Mdou Moctar", "Chismiten", "Afrique Victime", 2021, 253,
       "desert blues, tuareg, psychedelic rock, driving, distorted, aggressive",
       "heatwave_cruise, sirocco"),
    _t("Bombino", "Amidinine", "Nomad", 2013, 261,
       "desert blues, tuareg, driving, hypnotic, guitar, world",
       "heatwave_cruise, sirocco"),
    _t("Ali Farka Toure", "Ai Du", "Ali Farka Toure", 1988, 431,
       "desert blues, delta blues, acoustic, hypnotic, world, warm",
       "sirocco, heatwave_cruise"),
    _t("Fela Kuti", "Water No Get Enemy", "Expensive Shit", 1975, 691,
       "afrobeat, funk, long songs, horns, polyrhythmic, driving",
       "heatwave_cruise, golden_hour"),
    _t("Tony Allen", "Asiko", "Black Voices", 1999, 512,
       "afrobeat, funk, polyrhythmic, dub, hypnotic, driving",
       "heatwave_cruise"),
    _t("Donna Summer", "I Feel Love", "I Remember Yesterday", 1977, 486,
       "disco, italo disco, analog synth, euphoric, sequencer, driving",
       "heatwave_cruise"),
    _t("Giorgio Moroder", "The Chase", "Midnight Express", 1978, 511,
       "italo disco, synthwave, sequencer, driving, night drive, instrumental",
       "heatwave_cruise, blue_hour"),
    _t("Chic", "Good Times", "Risque", 1979, 494,
       "disco, funk, party, happy, summer, groove",
       "heatwave_cruise, golden_hour"),
    _t("Mr. Fingers", "Can You Feel It", "Can You Feel It", 1986, 232,
       "deep house, chicago house, hypnotic, euphoric, analog synth, night drive",
       "heatwave_cruise, blue_hour"),
    _t("Moodymann", "Shades of Jae", "Silentintroduction", 1997, 371,
       "deep house, detroit techno, sample based, warm, hypnotic, late night",
       "heatwave_cruise, blue_hour"),
    _t("Underground Resistance", "Transition", "Interstellar Fugitives", 1998, 402,
       "detroit techno, techno, driving, hypnotic, analog synth, dark",
       "heatwave_cruise, storm_front"),
)

SEED_CORPUS = SEED_CORPUS + (
    # ----------------------------------------------------------------
    # BLUE HOUR — the twenty minutes after sunset. Synthetic, wide,
    # nocturnal, and warmer than nordic fog despite the shared reverb.
    # ----------------------------------------------------------------
    _t("Portishead", "Roads", "Dummy", 1994, 322,
       "trip hop, downtempo, strings, melancholy, late night, cinematic",
       "blue_hour"),
    _t("Massive Attack", "Teardrop", "Mezzanine", 1998, 330,
       "trip hop, downtempo, atmospheric, melancholy, late night, female vocalists",
       "blue_hour"),
    _t("Tricky", "Hell Is Round the Corner", "Maxinquaye", 1995, 234,
       "trip hop, downtempo, sample based, dark, hypnotic, late night",
       "blue_hour"),
    _t("Cocteau Twins", "Cherry-Coloured Funk", "Heaven or Las Vegas", 1990, 194,
       "dream pop, shoegaze, ethereal, reverb, 4ad, dreamy",
       "blue_hour"),
    _t("Cocteau Twins", "Blue Bell Knoll", "Blue Bell Knoll", 1988, 208,
       "dream pop, ethereal, reverb, wall of sound, dreamy, atmospheric",
       "blue_hour, petrichor"),
    _t("Beach House", "Space Song", "Depression Cherry", 2015, 320,
       "dream pop, shoegaze, reverb, bittersweet, dreamy, night drive",
       "blue_hour"),
    _t("Mazzy Star", "Fade Into You", "So Tonight That I Might See", 1993, 295,
       "dream pop, slowcore, acoustic, melancholy, reverb, wistful",
       "blue_hour, first_frost"),
    _t("Chris Isaak", "Wicked Game", "Heart Shaped World", 1989, 288,
       "dream pop, surf rock, reverb, romantic, melancholy, night drive",
       "blue_hour"),
    _t("Basic Channel", "Phylyps Trak", "BCD", 1995, 421,
       "dub techno, minimal techno, hypnotic, repetitive, reverb, hi fi",
       "blue_hour"),
    _t("Rhythm & Sound", "Never Tell You", "With the Artists", 2003, 353,
       "dub techno, dub, reggae, hypnotic, reverb, minimal",
       "blue_hour"),
    _t("Deepchord", "Sunset Blvd", "Hash-Bar Loops", 2011, 449,
       "dub techno, ambient, hypnotic, reverb, late night, minimal",
       "blue_hour, petrichor"),
    _t("Gas", "Zauberberg 1", "Zauberberg", 1997, 604,
       "ambient techno, drone, hypnotic, dark, repetitive, atmospheric",
       "blue_hour, nordic_fog"),
    _t("Nightmares on Wax", "Les Nuits", "Carboot Soul", 1999, 315,
       "downtempo, trip hop, sample based, mellow, late night, groove",
       "blue_hour"),
    _t("Sade", "Cherish the Day", "Love Deluxe", 1992, 337,
       "neo soul, quiet storm, mellow, romantic, late night, hypnotic",
       "blue_hour, golden_hour"),
    _t("D'Angelo", "Untitled (How Does It Feel)", "Voodoo", 2000, 434,
       "neo soul, r&b, sensual, warm, late night, minimal",
       "blue_hour"),
    _t("Erykah Badu", "Didn't Cha Know", "Mama's Gun", 2000, 235,
       "neo soul, jazz rap, hypnotic, mellow, warm, groove",
       "blue_hour"),
    _t("The xx", "Night Time", "xx", 2009, 254,
       "dream pop, minimal, sparse, late night, reverb, melancholy",
       "blue_hour"),
    _t("Cigarettes After Sex", "Apocalypse", "Cigarettes After Sex", 2017, 289,
       "dream pop, slowcore, reverb, romantic, melancholy, late night",
       "blue_hour"),
    _t("DJ Shadow", "Midnight in a Perfect World", "Endtroducing.....", 1996, 292,
       "trip hop, instrumental hip hop, sample based, late night, mellow, atmospheric",
       "blue_hour"),
    _t("Madlib", "Slim's Return", "Shades of Blue", 2003, 172,
       "jazz rap, instrumental hip hop, sample based, mellow, groove, warm",
       "blue_hour, golden_hour"),
    _t("J Dilla", "Nothing Like This", "Donuts", 2006, 118,
       "instrumental hip hop, boom bap, sample based, lo fi, melancholy, warm",
       "blue_hour"),

    # ----------------------------------------------------------------
    # FIRST FROST — the morning it turns. Sparse, acoustic, quiet,
    # a low sun with no heat in it.
    # ----------------------------------------------------------------
    _t("Vashti Bunyan", "Diamond Day", "Just Another Diamond Day", 1970, 130,
       "folk, freak folk, acoustic, sparse, wistful, quiet",
       "first_frost"),
    _t("Sibylle Baier", "The End", "Colour Green", 2006, 176,
       "folk, singer songwriter, lo fi, home recording, melancholy, sparse",
       "first_frost, petrichor"),
    _t("Nick Drake", "Place to Be", "Pink Moon", 1972, 161,
       "folk, singer songwriter, acoustic, sparse, melancholy, quiet",
       "first_frost"),
    _t("Bon Iver", "Skinny Love", "For Emma, Forever Ago", 2007, 238,
       "folk, indie folk, lo fi, home recording, melancholy, winter",
       "first_frost"),
    _t("Sufjan Stevens", "Death with Dignity", "Carrie & Lowell", 2015, 234,
       "folk, singer songwriter, acoustic, sparse, melancholy, wistful",
       "first_frost"),
    _t("Elliott Smith", "Between the Bars", "Either/Or", 1997, 143,
       "singer songwriter, folk, lo fi, acoustic, sad, quiet",
       "first_frost"),
    _t("Red House Painters", "Katy Song", "Down Colorful Hill", 1992, 500,
       "slowcore, sadcore, melancholy, long songs, sparse, reverb",
       "first_frost, petrichor"),
    _t("Songs: Ohia", "Farewell Transmission", "The Magnolia Electric Co.", 2003, 442,
       "alt country, slowcore, americana, melancholy, long songs, distorted",
       "first_frost"),
    _t("Mount Eerie", "Real Death", "A Crow Looked at Me", 2017, 227,
       "folk, lo fi, sparse, spoken word, sad, home recording",
       "first_frost"),
    _t("Grouper", "Alien Observer", "A I A: Alien Observer", 2011, 316,
       "ambient, dream pop, tape, ethereal, reverb, melancholy",
       "first_frost, nordic_fog"),
    _t("Julee Cruise", "Falling", "Floating into the Night", 1989, 265,
       "dream pop, ethereal, reverb, soundtrack, dreamy, melancholy",
       "first_frost, blue_hour"),
    _t("Ryuichi Sakamoto", "Merry Christmas Mr. Lawrence", "Merry Christmas Mr. Lawrence", 1983, 259,
       "modern classical, soundtrack, piano, wistful, minimal, winter",
       "first_frost"),
    _t("Max Richter", "On the Nature of Daylight", "The Blue Notebooks", 2004, 366,
       "neoclassical, minimalism, strings, melancholy, cinematic, sad",
       "first_frost, nordic_fog"),
    _t("Henryk Gorecki", "Symphony No. 3: II. Lento e Largo", "Symphony No. 3", 1992, 559,
       "modern classical, orchestral, choral, sad, long songs, epic",
       "first_frost, nordic_fog"),
    _t("Joni Mitchell", "River", "Blue", 1971, 240,
       "folk, singer songwriter, piano, winter, melancholy, wistful",
       "first_frost"),
    _t("Kate Bush", "And Dream of Sheep", "Hounds of Love", 1985, 169,
       "art pop, piano, ethereal, sparse, wistful, female vocalists",
       "first_frost, nordic_fog"),
    _t("Low", "Just Like Christmas", "Christmas", 1999, 149,
       "slowcore, indie pop, winter, bittersweet, reverb, sparse",
       "first_frost"),
    _t("American Football", "Never Meant", "American Football", 1999, 316,
       "midwest emo, math rock, bittersweet, autumn, guitar, wistful",
       "first_frost"),
    _t("Duster", "Constellations", "Stratosphere", 1998, 172,
       "slowcore, lo fi, space rock, sparse, tape, melancholy",
       "first_frost, petrichor"),
    _t("Talk Talk", "Wealth", "Spirit of Eden", 1988, 366,
       "art rock, ambient, sparse, choral, contemplative, quiet",
       "first_frost, petrichor"),

    # ----------------------------------------------------------------
    # SIROCCO — hot wind off a continent. Dry spatiality, modal rather
    # than major or minor, and a great deal of patience.
    # ----------------------------------------------------------------
    _t("Tinariwen", "Sastanaqqam", "Elwan", 2017, 258,
       "desert blues, tuareg, hypnotic, desert, acoustic, world",
       "sirocco"),
    _t("Terakaft", "Amazzagh", "Aratan N Azawad", 2011, 271,
       "desert blues, tuareg, driving, guitar, hypnotic, desert",
       "sirocco, heatwave_cruise"),
    _t("Ali Farka Toure & Toumani Diabate", "Debe", "In the Heart of the Moon", 2005, 340,
       "desert blues, world, acoustic, improvisation, warm, meditative",
       "sirocco, golden_hour"),
    _t("Group Doueh", "Zaya Koum", "Guitar Music from the Western Sahara", 2007, 396,
       "desert blues, sahrawi, lo fi, distorted, hypnotic, live",
       "sirocco"),
    _t("Om", "Addis", "Advaitic Songs", 2012, 592,
       "doom metal, drone, raga, meditative, hypnotic, long songs",
       "sirocco, storm_front"),
    _t("Dead Can Dance", "The Host of Seraphim", "The Serpent's Egg", 1988, 386,
       "ethereal wave, world, choral, drone, haunting, epic",
       "sirocco, nordic_fog"),
    _t("Muslimgauze", "Hamas Arc", "Hamas Arc", 1993, 428,
       "industrial, world, dub, hypnotic, repetitive, dark",
       "sirocco, storm_front"),
    _t("Anouar Brahem", "The Astounding Eyes of Rita", "The Astounding Eyes of Rita", 2009, 371,
       "world, jazz, oud, acoustic, contemplative, sparse",
       "sirocco, golden_hour"),
    _t("Erkin Koray", "Estarabim", "Elektronik Turkuler", 1974, 268,
       "anatolian rock, psychedelic rock, distorted, driving, world, hypnotic",
       "sirocco, heatwave_cruise"),
    _t("Selda Bagcan", "Yaz Gazeteci Yaz", "Selda", 1976, 246,
       "anatolian rock, psychedelic rock, folk, angry, driving, world",
       "sirocco"),
    _t("Baris Manco", "Daglar Daglar", "Daglar Daglar", 1970, 388,
       "anatolian rock, folk, psychedelic rock, wistful, world, strings",
       "sirocco"),
    _t("Mulatu Astatke", "Yekermo Sew", "Mulatu of Ethiopia", 1972, 285,
       "ethio jazz, jazz, hypnotic, warm, instrumental, cinematic",
       "sirocco, golden_hour"),
    _t("Hailu Mergia", "Tezeta", "Hailu Mergia & His Classical Instrument", 1985, 344,
       "ethio jazz, lo fi, analog synth, mellow, hypnotic, warm",
       "sirocco, blue_hour"),
    _t("Ravi Shankar", "Raga Jog", "Three Ragas", 1956, 971,
       "raga, indian classical, acoustic, improvisation, meditative, long songs",
       "sirocco"),
    _t("Nusrat Fateh Ali Khan", "Allah Hoo Allah Hoo", "Shahen-Shah", 1989, 656,
       "qawwali, sufi, devotional, euphoric, live, world",
       "sirocco, golden_hour"),
    _t("Popol Vuh", "Morgengruss II", "Hosianna Mantra", 1972, 214,
       "kosmische, krautrock, acoustic, meditative, spiritual, sparse",
       "sirocco, first_frost"),
    _t("Sun City Girls", "Space Prophet Dogon", "Torch of the Mystics", 1990, 254,
       "psychedelic rock, world, drone, lo fi, hypnotic, improvisation",
       "sirocco"),
    _t("Sandy Bull", "Blend", "Fantasias for Guitar and Banjo", 1963, 1180,
       "folk, raga, oud, improvisation, long songs, hypnotic",
       "sirocco, golden_hour"),
    _t("Alice Coltrane", "Om Rama", "Universal Consciousness", 1971, 379,
       "spiritual jazz, raga, harp, drone, meditative, free jazz",
       "sirocco, golden_hour"),
    _t("Don Cherry & Ed Blackwell", "Mutron", "El Corazon", 1982, 344,
       "free jazz, improvisation, spiritual jazz, sparse, playful, world",
       "sirocco"),
)


# ==========================================================================
# accessors
# ==========================================================================
def by_theme(theme: str) -> tuple[SeedTrack, ...]:
    """Every seed track tagged with *theme*. Unknown themes yield ``()``."""
    needle = theme.strip().casefold()
    return tuple(t for t in SEED_CORPUS if needle in (x.casefold() for x in t.themes))


def all_tags() -> tuple[str, ...]:
    """Every distinct tag used in the corpus, sorted. Useful for coverage tests."""
    seen: set[str] = set()
    for track in SEED_CORPUS:
        seen.update(tag.casefold() for tag in track.tags)
    return tuple(sorted(seen))


def _validate_corpus() -> None:
    """Catch curation slips at import time: bad themes, duplicates, empties."""
    bad_themes = sorted(
        {t for track in SEED_CORPUS for t in track.themes if t not in THEMES}
    )
    if bad_themes:
        raise RuntimeError(f"seed corpus references unknown themes: {bad_themes}")

    keys: set[str] = set()
    duplicates: list[str] = []
    for track in SEED_CORPUS:
        if track.key in keys:
            duplicates.append(track.key)
        keys.add(track.key)
    if duplicates:
        raise RuntimeError(f"duplicate seed tracks: {sorted(duplicates)}")

    untagged = [t.key for t in SEED_CORPUS if not t.tags or not t.themes]
    if untagged:
        raise RuntimeError(f"seed tracks missing tags or themes: {untagged}")

    empty = [theme for theme in THEMES if not by_theme(theme)]
    if empty:
        raise RuntimeError(f"themes with no seed tracks: {empty}")


_validate_corpus()

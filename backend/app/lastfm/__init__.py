"""Last.fm subsystem: the acoustic oracle for BAROGROOVE.

Spotify's recommendation surface (``/recommendations``, ``/audio-features``,
``/audio-analysis``, ``/artists/{id}/related-artists``, the ``/browse``
playlist endpoints) has returned 403 to every non-grandfathered application
since 27 Nov 2024, with no waitlist and no replacement. Spotify is therefore
demoted to identity resolution and a playlist write sink.

This package is the replacement brain:

* ``lexicon``  -- curated tag -> sonic-dimension deltas, standing in for
  ``/audio-features``. Pure, synchronous, deterministic, offline.
* ``oracle``   -- taste-graph traversal over the Last.fm similarity graph,
  standing in for ``/recommendations``.
* ``offline``  -- the same protocol backed by a hand-curated seed corpus, so
  the demo path works with no network and no credentials.
* ``client``   -- a thin typed wrapper over the Last.fm 2.0 REST API.
* ``pairing``  -- the Last.fm web auth flow, so users pair in-app.
"""

from __future__ import annotations

from .lexicon import ALIASES, KNOWN_TAGS, estimate_from_tags, tag_affinity

__all__ = [
    "ALIASES",
    "KNOWN_TAGS",
    "estimate_from_tags",
    "tag_affinity",
]

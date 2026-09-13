"""The demo seed corpus, and the line between reading it and writing it.

Item 5 of the multi-tenancy rework. See ``docs/TENANCY_AUDIT.md`` finding 10.

What the seed corpus is
-----------------------
``data/scrobbles/`` holds one real listening history -- ~160k scrobbles over 15
years, hydrated from one Last.fm account -- as ``summary_cache.json``,
``track_catalog.jsonl`` and ``qna_cache/``. Demo mode uses it as a **seed
taste**, so an unauthenticated visitor gets a real-feeling almanac instead of a
blank page. It is checked into git on purpose (see ``.gitignore``, which
re-includes exactly those three paths).

The bug this module fixes
-------------------------
The corpus was also the *runtime cache directory*::

    CACHE_DIR = DATA_SCROBBLES_DIR if DATA_SCROBBLES_DIR.exists() else ...
    _QNA_CACHE_DIR = _REPO_ROOT / "data" / "scrobbles" / "qna_cache"
    _QNA_CACHE_DIR.mkdir(parents=True, exist_ok=True)   # at import time

So merely importing the app created directories inside the corpus, and every
Data-QnA cache miss, summary refresh and BigQuery query wrote into it. The
demo corpus was not read-only in any sense: it was the app's scratch space,
and a git-tracked artifact that the running app mutated. The stray untracked
files that kept appearing under ``data/scrobbles/qna_cache/`` during
development were this, observed and misfiled as noise.

The rule
--------
**Reads may touch the seed corpus. Writes may never.**

* :data:`SEED_CORPUS_DIR` -- read-only. Shipped, git-tracked, never written.
* :data:`RUNTIME_CACHE_DIR` -- writable. Everything the app generates at run
  time lands here, and it is gitignored.

:func:`readable_path` looks in the runtime cache first and falls back to the
seed, so a regenerated artifact shadows the shipped one without overwriting
it. :func:`writable_path` always returns a runtime-cache path.
:func:`refuse_if_seed` is the backstop: it raises rather than letting a write
through, because a demo that silently rewrites its own seed is a demo that
drifts, and a corpus that drifts is one nobody can reproduce.

This is deliberately a *refusal*, not a redirect. Silently rewriting the
target would be the same shape as the identity fallbacks the rest of this
rework removes: the caller believes something happened that did not.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("barogroove.almanac.seed_corpus")

_REPO_ROOT = Path(__file__).resolve().parents[3]

#: Read-only. The shipped demo corpus.
SEED_CORPUS_DIR = _REPO_ROOT / "data" / "scrobbles"

#: Writable. Everything generated at run time.
RUNTIME_CACHE_DIR = _REPO_ROOT / ".cache" / "scrobbles"

#: The uid the seed corpus is attributed to in its own rows. It is a real
#: Last.fm handle, which is precisely why it must not double as a fallback
#: identity anywhere -- see audit findings 5, 7 and 9.
SEED_CORPUS_HANDLE = "jpaquay"


class SeedCorpusWriteRefused(RuntimeError):
    """Raised when something tries to write inside the read-only seed corpus."""


def is_seed_path(path: Path | str) -> bool:
    """True if ``path`` resolves inside the read-only seed corpus.

    Resolved on both sides, so ``data/scrobbles/../scrobbles/x.json`` and a
    symlink into the corpus are both caught.
    """
    try:
        candidate = Path(path).resolve()
    except OSError:  # pragma: no cover - unresolvable path is not a seed path
        return False
    try:
        seed = SEED_CORPUS_DIR.resolve()
    except OSError:  # pragma: no cover - no corpus checked out
        return False
    return candidate == seed or seed in candidate.parents


def refuse_if_seed(path: Path | str, *, operation: str = "write") -> None:
    """Raise :class:`SeedCorpusWriteRefused` if ``path`` is in the seed corpus.

    Call this immediately before any write. It is cheap and it is the only
    thing standing between demo mode and a mutated seed.
    """
    if is_seed_path(path):
        raise SeedCorpusWriteRefused(
            f"refusing to {operation} {path}: the demo seed corpus at "
            f"{SEED_CORPUS_DIR} is read-only. Write to {RUNTIME_CACHE_DIR} "
            f"instead (see backend/app/almanac/seed_corpus.py)."
        )


def writable_path(*parts: str) -> Path:
    """A path under the runtime cache, with parent directories created.

    Never returns a location inside the seed corpus, whatever it is handed.
    """
    target = RUNTIME_CACHE_DIR.joinpath(*parts)
    refuse_if_seed(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def readable_path(*parts: str) -> Path | None:
    """The best available copy of a corpus artifact, or ``None``.

    Runtime cache first -- a regenerated artifact shadows the shipped one --
    then the read-only seed. Returns ``None`` when neither exists, rather than
    a path that is not there, so callers branch on presence explicitly.
    """
    runtime = RUNTIME_CACHE_DIR.joinpath(*parts)
    if runtime.exists():
        return runtime
    seed = SEED_CORPUS_DIR.joinpath(*parts)
    if seed.exists():
        return seed
    return None


def write_text(path: Path, payload: str, *, encoding: str = "utf-8") -> None:
    """Guarded ``Path.write_text``. Refuses seed-corpus targets."""
    refuse_if_seed(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding=encoding)


__all__ = [
    "RUNTIME_CACHE_DIR",
    "SEED_CORPUS_DIR",
    "SEED_CORPUS_HANDLE",
    "SeedCorpusWriteRefused",
    "is_seed_path",
    "readable_path",
    "refuse_if_seed",
    "writable_path",
    "write_text",
]

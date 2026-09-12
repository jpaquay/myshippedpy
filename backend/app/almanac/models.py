"""Typed records for everything the Almanac persists.

Both stores — the in-process :class:`~.memory_store.MemoryAlmanac` and the
Firestore-backed one owned by another worker — read and write exactly these
shapes. Nothing else crosses the storage boundary: no bare dicts, no
half-populated ``Playlist`` objects, no "we'll re-join it later".

Three records:

``ForgeRecord``
    One playlist, flattened for storage. Everything the learner and the
    retrospective need is denormalised into it, because the alternative is a
    fan-out read per playlist at training time.

``FeedbackEvent``
    One love or skip, *with the sky and sonic context captured at the moment
    it happened*. This is deliberate and it is the single most important
    modelling decision in this file. A love is only interpretable relative to
    the weather that produced the playlist; a love recorded bare and re-joined
    to its forge later is a love recorded against whatever the forge record
    has drifted into. Capture the context at write time or do not bother.

``NudgeDocument``
    The 9x7 per-user delta to the transfer matrix, plus enough metadata to
    know whether to trust it and whether it was fitted by a version of the
    matrix we still ship.

Wire format
-----------
Field names on the Python side are snake_case. The serialised form uses the
aliases agreed with the Firestore worker (``skyVector``, ``sonicVector``,
``theme``, ``genre``, ...). ``to_json_dict()`` emits aliases and JSON-safe
scalars; ``from_json_dict()`` accepts either spelling.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..contracts import SKY_DIMS, SONIC_DIMS, Playlist, SkyVector, SonicVector

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Bumped whenever the base transfer matrix changes shape or semantics. A nudge
#: fitted against matrix version N is meaningless once the base moves to N+1 —
#: the cells no longer mean the same thing — so consumers must discard nudges
#: whose ``matrix_version`` does not match the running engine.
MATRIX_VERSION: str = "sky9-sonic7-v1"

#: Shape of every nudge / transfer matrix in the system: [sky_dim][sonic_dim].
SKY_N: int = len(SKY_DIMS)
SONIC_N: int = len(SONIC_DIMS)

Signal = Literal["loved", "skipped"]


def _utc(value: datetime | None) -> datetime:
    """Normalise to timezone-aware UTC.

    Records get sorted and differenced constantly (history ordering, seasonal
    drift in the retrospective). A single naive datetime sneaking in turns
    every comparison into a TypeError at the worst possible moment, so we
    coerce at the boundary rather than defending everywhere downstream.
    """
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class _Record(BaseModel):
    """Shared config: alias-aware in both directions, extras tolerated.

    Extras are ignored rather than rejected because the Firestore worker may
    add metadata columns ahead of us; a forward-compatible reader is cheaper
    than a lockstep deploy.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    def to_json_dict(self) -> dict[str, Any]:
        """JSON-safe dict using the agreed wire aliases."""
        return self.model_dump(mode="json", by_alias=True)

    @classmethod
    def from_json_dict(cls, data: Mapping[str, Any]) -> "_Record":
        """Inverse of :meth:`to_json_dict`; accepts alias or field names."""
        return cls.model_validate(dict(data))


# ---------------------------------------------------------------------------
# Forge records
# ---------------------------------------------------------------------------


class TrackRecord(_Record):
    """A track as it appeared in a forged playlist.

    We store the track's *estimated* sonic vector alongside its identity. The
    catalogue's estimate for a track can be re-derived later, but it can also
    change; the learner needs the number the engine actually used when it put
    this track in front of this user.
    """

    key: str
    title: str = ""
    artist: str = ""
    tags: list[str] = Field(default_factory=list)
    sonic: SonicVector | None = None
    role: str = "body"
    position: int = 0

    @classmethod
    def from_scored(cls, scored: Any) -> "TrackRecord":
        track = scored.track
        return cls(
            key=track.key,
            title=track.title,
            artist=track.artist,
            tags=list(track.tags or []),
            sonic=track.estimated,
            role=getattr(scored, "role", "body") or "body",
            position=int(getattr(scored, "position", 0) or 0),
        )


class ForgeRecord(_Record):
    """One playlist, flattened.

    ``sky`` is the reading the playlist was forged from; ``sonic`` is the
    target the transfer matrix produced from it. Keeping both is what makes
    supervised learning possible at all — the pair (input, engine output) is
    the thing feedback is a correction to.
    """

    playlist_id: str = Field(alias="id")
    user_id: str | None = Field(default=None, alias="user_id")
    sky: SkyVector = Field(alias="skyVector")
    sonic: SonicVector = Field(alias="sonicVector")
    theme_id: str = Field(default="default", alias="theme")
    genre_id: str = Field(default="default", alias="genre")
    tracks: list[TrackRecord] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    title: str = ""
    subtitle: str = ""

    @field_validator("created_at", mode="before")
    @classmethod
    def _coerce_created_at(cls, v: Any) -> Any:
        return _utc(v) if isinstance(v, datetime) else v

    @model_validator(mode="after")
    def _normalise_created_at(self) -> "ForgeRecord":
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", _utc(self.created_at))
        return self

    # -- construction ------------------------------------------------------

    @classmethod
    def from_playlist(cls, playlist: Playlist) -> "ForgeRecord":
        return cls(
            playlist_id=playlist.id,
            user_id=playlist.user_id,
            sky=playlist.sky,
            sonic=playlist.sonic_target,
            theme_id=playlist.theme_id,
            genre_id=playlist.genre_id,
            tracks=[TrackRecord.from_scored(s) for s in playlist.tracks],
            created_at=_utc(playlist.created_at),
            title=playlist.title,
            subtitle=playlist.subtitle,
        )

    # -- lookups -----------------------------------------------------------

    def track(self, key: str) -> TrackRecord | None:
        for t in self.tracks:
            if t.key == key:
                return t
        return None

    def sky_array(self) -> list[float]:
        return self.sky.as_array()

    def sonic_array(self) -> list[float]:
        return self.sonic.as_array()


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------


class FeedbackEvent(_Record):
    """A love or a skip, with its weather attached.

    ``sky`` / ``sonic_target`` / ``track_sonic`` are copied from the forge at
    the instant feedback arrives. The learner reads only this record; it never
    goes back to the ``ForgeRecord`` for context. See the module docstring for
    why.
    """

    user_id: str
    playlist_id: str
    track_key: str
    signal: Signal
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Context captured at write time.
    sky: SkyVector = Field(default_factory=SkyVector, alias="skyVector")
    sonic_target: SonicVector = Field(
        default_factory=SonicVector, alias="sonicTarget"
    )
    track_sonic: SonicVector | None = Field(default=None, alias="trackSonic")
    theme_id: str = Field(default="default", alias="theme")
    genre_id: str = Field(default="default", alias="genre")
    track_title: str = ""
    track_artist: str = ""
    track_tags: list[str] = Field(default_factory=list)

    @field_validator("created_at", mode="before")
    @classmethod
    def _coerce_created_at(cls, v: Any) -> Any:
        return _utc(v) if isinstance(v, datetime) else v

    @classmethod
    def from_forge(
        cls,
        record: ForgeRecord,
        *,
        user_id: str,
        track_key: str,
        signal: Signal,
        created_at: datetime | None = None,
    ) -> "FeedbackEvent":
        """Build an event by snapshotting the forge it refers to."""
        track = record.track(track_key)
        return cls(
            user_id=user_id,
            playlist_id=record.playlist_id,
            track_key=track_key,
            signal=signal,
            created_at=_utc(created_at),
            sky=record.sky,
            sonic_target=record.sonic,
            track_sonic=track.sonic if track else None,
            theme_id=record.theme_id,
            genre_id=record.genre_id,
            track_title=track.title if track else "",
            track_artist=track.artist if track else "",
            track_tags=list(track.tags) if track else [],
        )

    @property
    def is_love(self) -> bool:
        return self.signal == "loved"

    def trainable(self) -> bool:
        """Only events that know what the track sounded like can train.

        A skip on a track with no estimated vector carries no direction in
        sonic space; it is a fact about the user but not a usable gradient.
        """
        return self.track_sonic is not None


# ---------------------------------------------------------------------------
# Nudge
# ---------------------------------------------------------------------------


class NudgeDiagnostics(_Record):
    """Fit quality, kept so a human can audit a nudge before believing it."""

    #: Coefficient of determination per sonic dimension, SONIC_DIMS order.
    r2: list[float] = Field(default_factory=list)
    #: Mean of ``r2``. A convenience for dashboards, not used in the maths.
    mean_r2: float = 0.0
    #: Ridge penalty actually used.
    lam: float = 0.0
    #: Confidence multiplier applied to the raw solution, in [0, 1].
    confidence: float = 0.0
    #: Largest absolute coefficient after clamping. If this equals the clamp
    #: bound, the fit wanted to go further than we let it.
    max_abs_coefficient: float = 0.0
    #: True when the normal equations were degenerate and ridge alone carried
    #: the solve. Not fatal — that is what ridge is for — but worth surfacing.
    degenerate: bool = False
    loved: int = 0
    skipped: int = 0


class NudgeDocument(_Record):
    """The per-user 9x7 delta added to the base transfer matrix.

    Never a replacement. ``matrix[i][j]`` is added to base cell
    ``[SKY_DIMS[i]][SONIC_DIMS[j]]``.
    """

    matrix: list[list[float]]
    samples: int = 0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    matrix_version: str = Field(default=MATRIX_VERSION, alias="matrixVersion")
    diagnostics: NudgeDiagnostics = Field(default_factory=NudgeDiagnostics)

    @field_validator("updated_at", mode="before")
    @classmethod
    def _coerce_updated_at(cls, v: Any) -> Any:
        return _utc(v) if isinstance(v, datetime) else v

    @field_validator("matrix")
    @classmethod
    def _check_shape(cls, v: list[list[float]]) -> list[list[float]]:
        if len(v) != SKY_N:
            raise ValueError(f"nudge matrix must have {SKY_N} rows, got {len(v)}")
        for i, row in enumerate(v):
            if len(row) != SONIC_N:
                raise ValueError(
                    f"nudge matrix row {i} must have {SONIC_N} columns, got {len(row)}"
                )
        return [[float(x) for x in row] for row in v]

    @classmethod
    def zeros(cls) -> "NudgeDocument":
        return cls(matrix=[[0.0] * SONIC_N for _ in range(SKY_N)])

    def as_matrix(self) -> list[list[float]]:
        """Plain nested list, safe to hand to ``apply_transfer(nudge=...)``."""
        return [list(row) for row in self.matrix]

    def cell(self, sky_dim: str, sonic_dim: str) -> float:
        """Read a coefficient by name. Convenient in tests and explanations."""
        return self.matrix[SKY_DIMS.index(sky_dim)][SONIC_DIMS.index(sonic_dim)]

    def is_current(self, version: str = MATRIX_VERSION) -> bool:
        return self.matrix_version == version

    @property
    def is_empty(self) -> bool:
        return all(x == 0.0 for row in self.matrix for x in row)


def matrix_from_rows(rows: Sequence[Sequence[float]]) -> list[list[float]]:
    """Defensive copy + shape check for anything arriving as a bare array."""
    out = [[float(x) for x in row] for row in rows]
    if len(out) != SKY_N or any(len(r) != SONIC_N for r in out):
        raise ValueError(f"expected a {SKY_N}x{SONIC_N} matrix")
    return out


__all__ = [
    "MATRIX_VERSION",
    "SKY_N",
    "SONIC_N",
    "Signal",
    "TrackRecord",
    "ForgeRecord",
    "FeedbackEvent",
    "NudgeDiagnostics",
    "NudgeDocument",
    "matrix_from_rows",
]

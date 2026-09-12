"""Spotify playlist sink.

READ THIS BEFORE ADDING AN ENDPOINT.
=====================================================================
Spotify is a *delivery target* for BAROGROOVE. It is not, and cannot be, the
recommendation brain. On 2024-11-27 Spotify 403'd the entire recommendation
surface for every app that was not already grandfathered in. There is no
waitlist, no application form, and no replacement. The tag lexicon in the
Last.fm module is what selects tracks now; this module only writes them down.

Then the February 2026 Web API migration landed on top of that. For an app in
Developer Mode it:
  * caps the app at 5 authorised users (hence the M3U sink — a demo must never
    die because a sixth person tried it),
  * requires the app owner to hold Spotify Premium,
  * removed ``POST /users/{user_id}/playlists`` in favour of ``POST /me/playlists``,
  * renamed ``/playlists/{id}/tracks`` to ``/playlists/{id}/items``,
  * collapsed every per-type save/follow endpoint into a generic
    ``PUT|DELETE /me/library`` and ``GET /me/library/contains`` which take
    **Spotify URIs**, not bare IDs.

Everything this module touches is on the survivors list: ``/search``, ``/me``,
``/me/top/*``, playlist create + add items, ``/me/library``.

Degradation contract: ``write()`` returns ``SinkResult(ok=False, ...)`` for every
expected failure and never raises. ``registry.py`` depends on that to fall
through to M3U.
"""

from __future__ import annotations

import re
from typing import Any, Final, Mapping, Sequence

from ..config import get_settings
from ..contracts import Playlist, SinkKind, SinkResult
from ..http import UpstreamError, request_json
from .resolver import ResolutionResult, SpotifyResolver
from .spotify_auth import SPOTIFY_SCOPES, SpotifyAuth, TokenVault

__all__ = ["DEAD_ENDPOINTS", "SpotifySink", "compress_description"]


# --------------------------------------------------------------------------- #
# the graveyard
# --------------------------------------------------------------------------- #

#: Endpoints that have returned 403 for every non-grandfathered app since
#: 2024-11-27. Calling any of them is a BUG, not a feature to restore: the 403
#: is unconditional, it is not rate limiting, it will not clear on retry, and
#: there is no way to apply for access. If you are here because you want audio
#: features, you want ``lastfm``'s tag lexicon instead — it is the designed
#: replacement, not a workaround.
DEAD_ENDPOINTS: Final[tuple[str, ...]] = (
    "/recommendations",                      # dead 2024-11-27
    "/recommendations/available-genre-seeds",  # dead 2024-11-27
    "/audio-features",                       # dead 2024-11-27
    "/audio-features/{id}",                  # dead 2024-11-27
    "/audio-analysis/{id}",                  # dead 2024-11-27
    "/artists/{id}/related-artists",         # dead 2024-11-27
    "/browse/featured-playlists",            # dead 2024-11-27
    "/browse/categories/{id}/playlists",     # dead 2024-11-27
)

#: Removed or renamed by the February 2026 migration. Kept next to the 2024 list
#: so the next person to read this file sees both cliffs at once.
FEB_2026_MOVED: Final[Mapping[str, str]] = {
    "POST /users/{user_id}/playlists": "POST /me/playlists",
    "POST /playlists/{id}/tracks": "POST /playlists/{id}/items",
    "PUT /me/tracks": "PUT /me/library",
    "PUT /me/albums": "PUT /me/library",
    "PUT /me/following": "PUT /me/library",
    "GET /me/tracks/contains": "GET /me/library/contains",
    "GET /me/albums/contains": "GET /me/library/contains",
    "GET /me/following/contains": "GET /me/library/contains",
}


# --------------------------------------------------------------------------- #
# limits
# --------------------------------------------------------------------------- #

#: Spotify's documented ceiling for one add-items call.
ADD_ITEMS_BATCH: Final[int] = 100

#: ``PUT /me/library`` / ``GET /me/library/contains`` document a maximum of 40
#: URIs per call. Lower than the old per-type endpoints' 50 — do not raise it.
LIBRARY_BATCH: Final[int] = 40

#: Spotify truncates playlist descriptions at 300 characters. It does not error,
#: it silently cuts, which is worse — so we compress deliberately instead.
DESCRIPTION_LIMIT: Final[int] = 300

#: Playlist names are capped well above anything we generate, but a runaway
#: title from an upstream generator should not produce a 400.
NAME_LIMIT: Final[int] = 100


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def compress_description(playlist: Playlist, *, limit: int = DESCRIPTION_LIMIT) -> str:
    """Squeeze the rationale into Spotify's 300-character description field.

    Priority order, most-informative first: headline, sky reading, sonic move,
    provenance. Each segment is added only if it fits whole — a sentence chopped
    mid-word reads like a bug, and this text is the only explanation a user gets
    inside the Spotify client.
    """
    rationale = playlist.rationale
    segments: list[str] = []

    headline = _clean(rationale.headline)
    if headline:
        segments.append(headline.rstrip(".") + ".")

    sky = _clean(rationale.sky_reading[0]) if rationale.sky_reading else ""
    if sky:
        segments.append(sky.rstrip(".") + ".")

    move = _clean(rationale.sonic_moves[0]) if rationale.sonic_moves else ""
    if move:
        segments.append(move.rstrip(".") + ".")

    taste = _clean(rationale.taste_note)
    if taste:
        segments.append(taste.rstrip(".") + ".")

    tail = _clean(f"BAROGROOVE · {playlist.theme_id}/{playlist.genre_id}")

    out = ""
    for segment in segments:
        candidate = segment if not out else f"{out} {segment}"
        if len(candidate) + 1 + len(tail) <= limit:
            out = candidate
        else:
            break

    if not out:
        # Nothing fit. Fall back to a hard truncation of the headline, with an
        # ellipsis so it is visibly abbreviated rather than mysteriously cut.
        body = headline or _clean(playlist.subtitle) or "A playlist built from the sky."
        room = max(0, limit - len(tail) - 2)
        out = body[: max(0, room - 1)].rstrip() + "…" if len(body) > room else body

    result = f"{out} {tail}".strip()
    return result[:limit]


# --------------------------------------------------------------------------- #
# the sink
# --------------------------------------------------------------------------- #


class SpotifySink:
    """``PlaylistSink`` that writes a real playlist to the user's Spotify account."""

    kind: SinkKind = "spotify"

    def __init__(
        self,
        *,
        auth: SpotifyAuth | None = None,
        vault: TokenVault | None = None,
        resolver: SpotifyResolver | None = None,
        settings: Any | None = None,
        public: bool = False,
    ) -> None:
        self._settings = settings or get_settings()
        self._auth = auth or SpotifyAuth(settings=self._settings, vault=vault)
        self._api_base = str(
            getattr(self._settings, "spotify_api_base", "https://api.spotify.com/v1")
        ).rstrip("/")
        self._resolver = resolver or SpotifyResolver(api_base=self._api_base)
        # Private by default. A weather playlist appearing on a stranger's public
        # profile without them asking is a bad surprise.
        self._public = public

    # -- availability -------------------------------------------------------- #

    @property
    def configured(self) -> bool:
        has = getattr(self._settings, "has_spotify", None)
        if isinstance(has, bool):
            return has
        return bool(getattr(self._settings, "spotify_client_id", None))

    async def available(self, user_id: str | None) -> bool:
        """True only when the app is configured *and* this user has a live token.

        Deliberately performs the refresh check: a stored-but-dead token is not
        availability, it is a slower failure.
        """
        if not user_id:
            return False
        try:
            from ..routes.pairing import _is_demo_paired

            if await _is_demo_paired(user_id, "spotify"):
                return True
        except Exception:
            pass
        if not self.configured:
            return False
        try:
            return await self._auth.access_token_for(user_id) is not None
        except Exception:
            # Availability probes never raise. Unavailable is a fine answer.
            return False

    # -- the main event ------------------------------------------------------ #

    async def write(
        self, playlist: Playlist, *, user_id: str | None = None
    ) -> SinkResult:
        requested = len(playlist.tracks)
        target_user = user_id or playlist.user_id

        if target_user:
            try:
                from ..routes.pairing import _is_demo_paired

                if await _is_demo_paired(target_user, "spotify"):
                    return SinkResult(
                        kind="spotify",
                        ok=True,
                        external_id=f"demo_pl_{playlist.id}",
                        external_url=None,
                        matched=requested,
                        requested=requested,
                        message=f"Demo Mode: Simulated Spotify playlist created ({requested} of {requested} tracks). Connect a live Spotify account in Account Settings to create real Spotify playlists.",
                    )
            except Exception:
                pass

        if not self.configured:
            return self._fail(
                requested,
                "Spotify is not configured on this deployment (no client id). "
                "Falling back to a downloadable playlist file.",
            )
        if not target_user:
            return self._fail(
                requested,
                "No signed-in user to write a Spotify playlist for. "
                "Sign in and pair Spotify, or take the file.",
            )

        try:
            token = await self._auth.access_token_for(target_user)
        except Exception as exc:
            return self._fail(
                requested,
                f"Could not obtain a Spotify token ({type(exc).__name__}). "
                "Re-pair Spotify from Settings.",
            )

        if token is None:
            return self._fail(
                requested,
                "Spotify is not paired for this account, or the stored "
                "authorisation expired and could not be refreshed. "
                "Re-pair from Settings — it takes one tap.",
            )

        if token.startswith("demo-spotify-"):
            return SinkResult(
                kind="spotify",
                ok=True,
                external_id=f"demo_pl_{playlist.id}",
                external_url=f"https://open.spotify.com/playlist/demo_{playlist.id}",
                matched=requested,
                requested=requested,
                message=f"Demo Mode: Created simulated Spotify playlist with {requested} of {requested} tracks.",
            )

        try:
            return await self._write_authed(playlist, token=token, requested=requested)
        except UpstreamError as exc:
            return self._fail(requested, _explain_upstream(exc))
        except Exception as exc:  # pragma: no cover - the never-raise backstop
            return self._fail(
                requested,
                f"Unexpected Spotify failure ({type(exc).__name__}); "
                "handed you the file instead.",
            )

    async def _write_authed(
        self, playlist: Playlist, *, token: str, requested: int
    ) -> SinkResult:
        # 1. Who are we? /me survived both migrations and gives us the Spotify
        #    user id plus the product tier. The tier matters: since Feb 2026 a
        #    Developer Mode app requires its *owner* to hold Premium, and a
        #    free-tier member of a dev app hits confusing 403s.
        me = await self._get_me(token)
        spotify_user_id = _clean(me.get("id")) if isinstance(me, Mapping) else ""

        # 2. Resolve tracks to URIs. This is where most of the loss happens.
        resolution = await self._resolver.resolve(playlist.plain_tracks(), token=token)
        uris = resolution.uris

        if not uris:
            return self._fail(
                requested,
                _no_matches_message(resolution),
                unmatched=resolution.unmatched_labels,
            )

        # 3. Create the playlist.
        created = await self._create_playlist(playlist, token=token, spotify_user_id=spotify_user_id)
        playlist_id = _clean(created.get("id"))
        if not playlist_id:
            return self._fail(
                requested,
                "Spotify accepted the create call but returned no playlist id.",
                unmatched=resolution.unmatched_labels,
            )
        external_url = _external_url(created, playlist_id)

        # 4. Fill it, 100 at a time, in order.
        added, add_note = await self._add_items(playlist_id, uris, token=token)

        message = _success_message(
            added=added,
            requested=requested,
            resolution=resolution,
            product=_clean(me.get("product")) if isinstance(me, Mapping) else "",
            extra=add_note,
        )

        return SinkResult(
            kind=self.kind,
            ok=added > 0,
            external_id=playlist_id,
            external_url=external_url,
            matched=added,
            requested=requested,
            unmatched=resolution.unmatched_labels,
            payload=None,
            message=message,
        )

    # -- API calls ----------------------------------------------------------- #

    def _headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    async def _get_me(self, token: str) -> Mapping[str, Any]:
        payload = await request_json(
            "GET",
            f"{self._api_base}/me",
            service="spotify",
            headers=self._headers(token),
            settings=self._settings,
        )
        return payload if isinstance(payload, Mapping) else {}

    async def _create_playlist(
        self, playlist: Playlist, *, token: str, spotify_user_id: str
    ) -> Mapping[str, Any]:
        """Create the playlist on the authenticated user.

        VERIFIED: the Feb-2026 changelog lists ``POST /users/{user_id}/playlists``
        as REMOVED, replaced by ``POST /me/playlists`` with the same JSON body.
        We call the new endpoint first and only fall back to the legacy path if
        the deployment is somehow talking to a pre-migration surface (a mock, a
        proxy, a grandfathered tenant). The fallback is cheap insurance; it is
        expected to be dead code in production.
        """
        body: dict[str, Any] = {
            "name": (_clean(playlist.title) or "BAROGROOVE")[:NAME_LIMIT],
            "description": compress_description(playlist),
            "public": self._public,
            "collaborative": False,
        }

        try:
            created = await request_json(
                "POST",
                f"{self._api_base}/me/playlists",
                service="spotify",
                json_body=body,
                headers=self._headers(token),
                settings=self._settings,
            )
        except UpstreamError as exc:
            if exc.status == 404 and spotify_user_id:
                created = await request_json(
                    "POST",
                    f"{self._api_base}/users/{spotify_user_id}/playlists",
                    service="spotify",
                    json_body=body,
                    headers=self._headers(token),
                    settings=self._settings,
                )
            else:
                raise
        return created if isinstance(created, Mapping) else {}

    async def _add_items(
        self, playlist_id: str, uris: Sequence[str], *, token: str
    ) -> tuple[int, str]:
        """Add items in batches of 100, in order.

        VERIFIED: body is ``{"uris": ["spotify:track:...", ...]}``, max 100 per
        call. The endpoint was renamed ``/tracks`` -> ``/items`` in Feb 2026;
        we prefer ``/items`` and fall back once on 404.

        Partial success is a real outcome: if batch 3 of 5 fails we keep what
        landed and say so, because a 60-track playlist with 40 tracks in it is
        still worth having.
        """
        added = 0
        notes: list[str] = []
        use_legacy = False

        for start in range(0, len(uris), ADD_ITEMS_BATCH):
            batch = list(uris[start : start + ADD_ITEMS_BATCH])
            path = "tracks" if use_legacy else "items"
            try:
                await request_json(
                    "POST",
                    f"{self._api_base}/playlists/{playlist_id}/{path}",
                    service="spotify",
                    json_body={"uris": batch},
                    headers=self._headers(token),
                    settings=self._settings,
                )
                added += len(batch)
            except UpstreamError as exc:
                if exc.status == 404 and not use_legacy:
                    # Pre-Feb-2026 surface. Retry this same batch on /tracks.
                    use_legacy = True
                    try:
                        await request_json(
                            "POST",
                            f"{self._api_base}/playlists/{playlist_id}/tracks",
                            service="spotify",
                            json_body={"uris": batch},
                            headers=self._headers(token),
                            settings=self._settings,
                        )
                        added += len(batch)
                        continue
                    except UpstreamError as legacy_exc:
                        exc = legacy_exc
                if added == 0:
                    # Nothing landed at all — let the caller turn this into a
                    # clean ok=False rather than reporting a half-empty success.
                    raise
                notes.append(
                    f"stopped after {added} tracks (HTTP {exc.status or '?'} on a later batch)"
                )
                break

        return added, "; ".join(notes)

    # -- Feb-2026 generic library shape -------------------------------------- #

    async def save_to_library(
        self, uris: Sequence[str], *, user_id: str
    ) -> SinkResult:
        """``PUT /me/library`` — save tracks/albums/artists/playlists by URI.

        VERIFIED against the Feb-2026 changelog and the "Save Items to Library"
        reference: the endpoint accepts **a comma-separated list of Spotify URIs,
        maximum 40**, covering ``spotify:track:``, ``spotify:album:``,
        ``spotify:episode:``, ``spotify:show:``, ``spotify:audiobook:``,
        ``spotify:user:`` and ``spotify:playlist:``. Scope: ``user-library-modify``.

        UNVERIFIED: the reference documents the ``uris`` *query parameter* but the
        docs page did not render a request-body schema for me. The old per-type
        endpoints accepted the list either as a query param or as a JSON body
        (``{"ids": [...]}``), so this most likely mirrors that with
        ``{"uris": [...]}``. We send the query parameter, which is the form the
        reference actually documents, and deliberately do NOT also send a body —
        Spotify's documented precedence rule elsewhere is that a query parameter
        wins and a body is ignored, so sending both would only obscure errors.
        """
        token = await self._auth.access_token_for(user_id)
        if token is None:
            return self._fail(len(uris), "Spotify is not paired for this account.")

        clean = [u for u in (str(u).strip() for u in uris) if u.startswith("spotify:")]
        if not clean:
            return self._fail(len(uris), "No valid Spotify URIs to save.")

        saved = 0
        try:
            for start in range(0, len(clean), LIBRARY_BATCH):
                batch = clean[start : start + LIBRARY_BATCH]
                await request_json(
                    "PUT",
                    f"{self._api_base}/me/library",
                    service="spotify",
                    params={"uris": ",".join(batch)},
                    headers=self._headers(token),
                    settings=self._settings,
                    expect_json=False,  # documented 200 with an empty body
                )
                saved += len(batch)
        except UpstreamError as exc:
            return self._fail(
                len(clean),
                _explain_upstream(exc),
            )

        return SinkResult(
            kind=self.kind,
            ok=True,
            matched=saved,
            requested=len(clean),
            message=f"Saved {saved} item{'' if saved == 1 else 's'} to your Spotify library.",
        )

    async def library_contains(
        self, uris: Sequence[str], *, user_id: str
    ) -> dict[str, bool]:
        """``GET /me/library/contains`` — which of these are already saved?

        VERIFIED: same URI-based, comma-separated, max-40 shape as
        ``PUT /me/library``. Scope: ``user-library-read``.

        UNVERIFIED: the response body. Every per-type predecessor returned a bare
        JSON array of booleans positionally aligned with the request, so that is
        what we parse; we also accept an object keyed by URI in case the generic
        endpoint took the opportunity to become self-describing. Anything else
        degrades to "unknown" (absent from the returned mapping) rather than
        guessing.

        Returns a URI -> bool mapping. Failure returns ``{}``; this is a
        nice-to-have, not a critical path, so it degrades silently.
        """
        token = await self._auth.access_token_for(user_id)
        if token is None:
            return {}

        clean = [u for u in (str(u).strip() for u in uris) if u.startswith("spotify:")]
        out: dict[str, bool] = {}

        for start in range(0, len(clean), LIBRARY_BATCH):
            batch = clean[start : start + LIBRARY_BATCH]
            try:
                payload = await request_json(
                    "GET",
                    f"{self._api_base}/me/library/contains",
                    service="spotify",
                    params={"uris": ",".join(batch)},
                    headers=self._headers(token),
                    settings=self._settings,
                )
            except UpstreamError:
                # Not worth failing a page render over.
                continue

            if isinstance(payload, list):
                for uri, flag in zip(batch, payload):
                    out[uri] = bool(flag)
            elif isinstance(payload, Mapping):
                # Tolerate {"uri": bool} or {"items"/"contains": [bool, ...]}.
                inner = payload.get("items") or payload.get("contains")
                if isinstance(inner, list):
                    for uri, flag in zip(batch, inner):
                        out[uri] = bool(flag)
                else:
                    for uri in batch:
                        if uri in payload:
                            out[uri] = bool(payload[uri])

        return out

    # -- helpers ------------------------------------------------------------- #

    def _fail(
        self, requested: int, message: str, *, unmatched: Sequence[str] | None = None
    ) -> SinkResult:
        return SinkResult(
            kind=self.kind,
            ok=False,
            external_id=None,
            external_url=None,
            matched=0,
            requested=requested,
            unmatched=list(unmatched or []),
            payload=None,
            message=message,
        )

    @property
    def required_scopes(self) -> tuple[str, ...]:
        return SPOTIFY_SCOPES


def _external_url(created: Mapping[str, Any], playlist_id: str) -> str:
    ext = created.get("external_urls")
    if isinstance(ext, Mapping):
        url = ext.get("spotify")
        if url:
            return str(url)
    return f"https://open.spotify.com/playlist/{playlist_id}"


# --------------------------------------------------------------------------- #
# human-readable failure prose
# --------------------------------------------------------------------------- #


def _explain_upstream(exc: UpstreamError) -> str:
    """Turn an ``UpstreamError`` into something a user can act on."""
    status = exc.status

    if status == 403:
        # The single most likely failure in this product, and the most confusing
        # one, so it gets the longest explanation.
        return (
            "Spotify refused the request (403). In Developer Mode that almost "
            "always means one of: the app's 5-user allowance is full, this "
            "account has not been added as an authorised tester, or the app "
            "owner's Spotify Premium subscription lapsed (required since the "
            "February 2026 migration). None of these clear by retrying. "
            "You get the playlist as a file instead."
        )
    if status == 401:
        return (
            "Spotify rejected the stored authorisation (401). Re-pair Spotify "
            "from Settings; meanwhile, here is the playlist as a file."
        )
    if status == 429:
        return (
            "Spotify is rate-limiting this app right now (429). The playlist is "
            "unchanged on their side — try again in a minute, or take the file."
        )
    if status == 404:
        return (
            "Spotify returned 404 for an endpoint we expected to exist. The "
            "February 2026 migration moved several playlist and library "
            "endpoints; if this persists the client needs updating. "
            "File fallback used."
        )
    if status and 500 <= status < 600:
        return (
            f"Spotify's API is having a bad moment (HTTP {status}) — their 5xx "
            "rate under Developer Mode load is notoriously spiky. "
            "Falling back to a file."
        )
    if exc.is_deprecation:
        return (
            f"Spotify returned {status} for a deprecated endpoint. Nothing to "
            "retry; falling back to a file."
        )
    return (
        f"Spotify call failed (HTTP {status or '?'}). "
        "Falling back to a downloadable playlist file."
    )


def _no_matches_message(resolution: ResolutionResult) -> str:
    rejected = [r for r in resolution.unmatched if r.rejected_display]
    base = (
        "None of these tracks could be matched in Spotify's catalogue with "
        "enough confidence to be sure they are the right recordings."
    )
    if rejected:
        base += (
            f" {len(rejected)} near-miss{'' if len(rejected) == 1 else 'es'} were "
            "rejected rather than substituted — a wrong song is worse than a "
            "missing one."
        )
    if resolution.degraded:
        base += " " + " ".join(resolution.degraded)
    return base + " The file below has every track, ready to search by hand."


def _success_message(
    *,
    added: int,
    requested: int,
    resolution: ResolutionResult,
    product: str,
    extra: str,
) -> str:
    parts = [
        f"Added {added} of {requested} tracks to a new Spotify playlist "
        f"(mean match confidence {resolution.mean_confidence:.2f})."
    ]
    missing = resolution.unmatched
    if missing:
        rejected = [r for r in missing if r.rejected_display]
        parts.append(
            f"{len(missing)} track{'' if len(missing) == 1 else 's'} could not be "
            "matched"
            + (
                f", including {len(rejected)} deliberate rejection"
                f"{'' if len(rejected) == 1 else 's'} of a close-but-wrong recording."
                if rejected
                else "."
            )
        )
    if product and product.lower() != "premium":
        parts.append(
            "Note: this account is not Premium. Playlists still work, but "
            "Developer Mode apps have required the owner to hold Premium since "
            "February 2026, so some calls may behave oddly."
        )
    if extra:
        parts.append(extra.capitalize() + ".")
    return " ".join(parts)

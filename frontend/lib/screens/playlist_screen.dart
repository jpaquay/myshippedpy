/// The set view.
///
/// ## How this screen gets its UI
///
/// Preferred path: after a forge, we send `showPlaylist` to
/// `POST /api/surfaces/action` with the playlist id, and the agent replies
/// with the A2UI messages that describe the page. The server decides whether
/// the rationale goes above or below the tracklist, whether the sky dial
/// repeats here, and what the export affordance says.
///
/// Fallback path: if that action fails (older backend, offline, the demo
/// forge), we synthesise a MINIMAL envelope locally from the typed
/// [ForgeResult] — see [_fallbackEnvelope]. Read that function before you
/// judge it: it does not lay anything out by hand. It emits the same catalog
/// components the server would emit (RationaleCard, TrackList, SkyDial) in
/// the obvious order and lets the renderer do the rest. It exists so that a
/// backend that has not shipped its playlist surface yet still produces a
/// usable page, and it is the ONLY place in this client where the client
/// chooses a composition.
///
/// If you are extending the playlist page, extend the SERVER surface. Adding
/// a component to [_fallbackEnvelope] and stopping there means the real path
/// never gets it.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../a2ui/actions.dart';
import '../a2ui/messages.dart';
import '../a2ui/renderer.dart';
import '../api/models.dart';
import '../app_theme.dart';
import '../providers.dart';
import 'shell.dart';
import 'widgets/status_notes.dart';

class PlaylistScreen extends ConsumerStatefulWidget {
  const PlaylistScreen({super.key});

  @override
  ConsumerState<PlaylistScreen> createState() => _PlaylistScreenState();
}

class _PlaylistScreenState extends ConsumerState<PlaylistScreen> {
  bool _loading = false;
  bool _usedFallback = false;
  String? _error;
  String? _loadedPlaylistId;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // A new forge means a new surface.
    final ForgeResult? forge = ref.read(lastForgeProvider);
    if (forge != null && forge.playlist.id != _loadedPlaylistId) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _load());
    }
  }

  Future<void> _load() async {
    final ForgeResult? forge = ref.read(lastForgeProvider);
    if (forge == null) return;

    setState(() {
      _loading = true;
      _error = null;
      _usedFallback = false;
    });

    final A2uiSurfaceController controller =
        ref.read(surfaceControllerProvider('playlist'))..reset();

    // Ask the agent to describe this playlist.
    final ActionOutcome outcome =
        await ref.read(actionDispatcherProvider).send(
              ActionResponse(
                surfaceId: 'playlist',
                actionId: 'showPlaylist',
                payload: <String, Object?>{
                  'playlist_id': forge.playlist.id,
                },
              ),
            );

    if (!mounted) return;

    if (outcome.ok && outcome.messages.isNotEmpty) {
      controller.applyAll(outcome.messages);
      setState(() {
        _loading = false;
        _loadedPlaylistId = forge.playlist.id;
      });
      return;
    }

    // Fallback: render the typed result through the same catalog.
    controller.applyAll(_fallbackEnvelope(forge));
    setState(() {
      _loading = false;
      _usedFallback = true;
      _loadedPlaylistId = forge.playlist.id;
      _error = outcome.error;
    });
  }

  @override
  Widget build(BuildContext context) {
    final ForgeResult? forge = ref.watch(lastForgeProvider);
    final A2uiSurfaceController controller =
        ref.watch(surfaceControllerProvider('playlist'));

    if (forge == null) {
      return _EmptySet(
        onGoForge: () => AppShell.of(context)?.go(BgDestination.forge),
      );
    }

    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.symmetric(
          horizontal: BgSpace.xl,
          vertical: BgSpace.lg,
        ),
        children: <Widget>[
          _SetHeader(playlist: forge.playlist),
          const SizedBox(height: BgSpace.lg),

          // The sink. Shell chrome: this is about getting the set OUT of the
          // app, which is a client concern.
          _SinkBar(sink: forge.playlist.sink),

          if (forge.degraded.isNotEmpty) ...<Widget>[
            const SizedBox(height: BgSpace.lg),
            DegradedNotes(
              title: 'This forge ran degraded',
              notes: forge.degraded,
            ),
          ],

          if (_usedFallback) ...<Widget>[
            const SizedBox(height: BgSpace.lg),
            DegradedNotes(
              title: 'Rendered from the local fallback',
              notes: <String>[
                if (_error != null)
                  _error!
                else
                  'The backend did not return a playlist surface.',
                'The page below was composed by the client, not the agent. '
                    'Everything in it still comes from the same catalog, but '
                    'the ordering is a guess.',
              ],
            ),
          ],

          const SizedBox(height: BgSpace.xl),

          if (_loading)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: BgSpace.xxl),
              child: Center(child: CircularProgressIndicator()),
            )
          else
            A2uiSurfaceView(
              controller: controller,
              padding: EdgeInsets.zero,
            ),

          const SizedBox(height: BgSpace.xxl),
        ],
      ),
    );
  }
}

// ===========================================================================
// The fallback envelope
// ===========================================================================

/// Builds the minimum A2UI stream that renders a [ForgeResult].
///
/// This is a SHIM, not a design. It emits four components — root, the
/// rationale, the tracklist, the sky dial — using the exact same catalog
/// types the server uses, and puts the whole typed result into the data model
/// so the components bind to it normally. Nothing here knows what a rationale
/// looks like; it only knows that the server would have used a RationaleCard.
///
/// Note that even the fallback goes THROUGH the renderer. There is no code
/// path in this app that lays out domain content with Flutter widgets
/// directly, and that is worth keeping true.
List<A2uiMessage> _fallbackEnvelope(ForgeResult forge) {
  final Playlist p = forge.playlist;

  final JsonMap dataModel = <String, Object?>{
    'sky': p.sky.toJson(),
    'rationale': <String, Object?>{
      'headline': p.rationale.headline,
      'body': p.rationale.body,
      'sky_reading': p.rationale.skyReading,
      'sonic_moves': p.rationale.sonicMoves,
      'taste_note': p.rationale.tasteNote,
      'confidence': p.rationale.confidence,
      'degraded': p.rationale.degraded,
    },
    'tracks': <Object?>[
      for (final ScoredTrack t in p.tracks)
        <String, Object?>{
          'track': <String, Object?>{
            'title': t.track.title,
            'artist': t.track.artist,
            'album': t.track.album,
            'duration_ms': t.track.durationMs,
            'tags': t.track.tags,
            'spotify_uri': t.track.spotifyUri,
            'lastfm_url': t.track.lastfmUrl,
          },
          'score': t.score,
          'sonic_distance': t.sonicDistance,
          'taste_affinity': t.tasteAffinity,
          'corridor_fit': t.corridorFit,
          'novelty': t.novelty,
          'role': t.role,
          'position': t.position,
          'why': t.why,
          'track_key': t.track.spotifyUri ?? t.track.lastfmUrl ?? t.track.title,
        },
    ],
    'title': p.title,
    'subtitle': p.subtitle,
  };

  return A2uiMessage.parseBatch(<Object?>[
    <String, Object?>{
      'createSurface': <String, Object?>{
        'surfaceId': 'playlist',
        'dataModel': dataModel,
        'components': <Object?>[
          <String, Object?>{
            'id': 'root',
            'componentProperties': <String, Object?>{
              'Column': <String, Object?>{
                'gap': 24,
                'children': <String>['why', 'tracks', 'sky'],
              },
            },
          },
          <String, Object?>{
            'id': 'why',
            'componentProperties': <String, Object?>{
              'RationaleCard': <String, Object?>{
                'rationale': <String, Object?>{'path': '/rationale'},
              },
            },
          },
          <String, Object?>{
            'id': 'tracks',
            'componentProperties': <String, Object?>{
              'TrackList': <String, Object?>{
                'title': <String, Object?>{'path': '/title'},
                'subtitle': <String, Object?>{'path': '/subtitle'},
                'tracks': <String, Object?>{'path': '/tracks'},
                'feedbackAction': <String, Object?>{
                  'actionId': 'trackFeedback',
                  'payload': <String, Object?>{
                    'playlist_id': <String, Object?>{'literalString': p.id},
                  },
                },
              },
            },
          },
          <String, Object?>{
            'id': 'sky',
            'componentProperties': <String, Object?>{
              'SkyDial': <String, Object?>{
                'title': <String, Object?>{
                  'literalString': 'THE SKY THAT MADE THIS',
                },
                'vector': <String, Object?>{'path': '/sky'},
              },
            },
          },
        ],
      },
    },
  ]);
}

// ===========================================================================
// Shell chrome
// ===========================================================================

class _SetHeader extends StatelessWidget {
  const _SetHeader({required this.playlist});

  final Playlist playlist;

  @override
  Widget build(BuildContext context) {
    final TextTheme text = Theme.of(context).textTheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        Text('THE SET', style: text.labelSmall),
        const SizedBox(height: BgSpace.xs),
        Text(playlist.title, style: text.displaySmall),
        if (playlist.subtitle.isNotEmpty) ...<Widget>[
          const SizedBox(height: BgSpace.xs),
          Text(
            playlist.subtitle,
            style: text.bodyLarge?.copyWith(
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
          ),
        ],
      ],
    );
  }
}

/// Where the set went, and how to get at it.
class _SinkBar extends StatelessWidget {
  const _SinkBar({required this.sink});

  final PlaylistSink sink;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    final (IconData icon, String label, String detail) = switch (sink.kind) {
      'spotify' when sink.ok => (
          Icons.check_circle_outline,
          'Saved to Spotify',
          sink.message ?? 'The playlist is in your account.',
        ),
      'm3u' => (
          Icons.description_outlined,
          'Exported as M3U',
          sink.message ??
              'Spotify is not connected, so the set came back as a file.',
        ),
      _ => (
          Icons.remove_circle_outline,
          'Not exported',
          sink.message ?? 'Connect a provider in Settings to save sets.',
        ),
    };

    return Container(
      padding: const EdgeInsets.all(BgSpace.lg),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BgSpace.brSm,
        border: Border.all(color: colors.outlineVariant),
      ),
      child: Row(
        children: <Widget>[
          Icon(icon,
              size: 18,
              color: sink.ok ? BgPalette.ok : colors.onSurfaceVariant),
          const SizedBox(width: BgSpace.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                Text(label, style: text.titleSmall),
                Text(detail, style: text.bodySmall),
              ],
            ),
          ),
          if (sink.externalUrl != null && sink.externalUrl!.isNotEmpty)
            OutlinedButton.icon(
              onPressed: () {
                final Uri? uri = Uri.tryParse(sink.externalUrl!);
                if (uri != null) {
                  launchUrl(uri, mode: LaunchMode.externalApplication);
                }
              },
              icon: const Icon(Icons.open_in_new, size: 15),
              label: const Text('Open'),
            ),
        ],
      ),
    );
  }
}

class _EmptySet extends StatelessWidget {
  const _EmptySet({required this.onGoForge});

  final VoidCallback onGoForge;

  @override
  Widget build(BuildContext context) {
    final TextTheme text = Theme.of(context).textTheme;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(BgSpace.xxl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Icon(
              Icons.queue_music_outlined,
              size: 32,
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
            const SizedBox(height: BgSpace.lg),
            Text('No set yet', style: text.headlineSmall),
            const SizedBox(height: BgSpace.sm),
            Text(
              'Read the sky and forge one.',
              style: text.bodyMedium,
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: BgSpace.xl),
            FilledButton(
              onPressed: onGoForge,
              child: const Text('Go to the forge'),
            ),
          ],
        ),
      ),
    );
  }
}

import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;
import 'package:url_launcher/url_launcher.dart';

import '../../api/models.dart';
import '../../app_theme.dart';
import '../../providers.dart';
import 'embedded_player_stub.dart'
    if (dart.library.html) 'embedded_player_web.dart';

class EmbeddedPlayerDeck extends ConsumerStatefulWidget {
  const EmbeddedPlayerDeck({
    required this.playlist,
    super.key,
  });

  final Playlist playlist;

  @override
  ConsumerState<EmbeddedPlayerDeck> createState() => _EmbeddedPlayerDeckState();
}

class _EmbeddedPlayerDeckState extends ConsumerState<EmbeddedPlayerDeck> {
  bool _isPlayingAudio = false;
  bool _loadingPreview = false;
  String? _previewUrl;
  String? _artworkUrl;
  String? _lastFetchedKey;
  bool _showSpotifyEmbed = true;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _ensureInitialTrack();
    });
  }

  @override
  void didUpdateWidget(covariant EmbeddedPlayerDeck oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.playlist.id != widget.playlist.id) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _ensureInitialTrack(forceReset: true);
      });
    }
  }

  void _ensureInitialTrack({bool forceReset = false}) {
    final ActivePlayerTrack? current = ref.read(activePlayerTrackProvider);
    if (current == null || forceReset) {
      if (widget.playlist.tracks.isNotEmpty) {
        final ScoredTrack first = widget.playlist.tracks.first;
        final ActivePlayerTrack initial = ActivePlayerTrack(
          title: first.track.title,
          artist: first.track.artist,
          album: first.track.album,
          spotifyUri: first.track.spotifyUri,
          lastfmUrl: first.track.lastfmUrl,
          playlistExternalUrl: widget.playlist.sink?.externalUrl,
        );
        ref.read(activePlayerTrackProvider.notifier).state = initial;
        _fetchTrackPreview(initial, autoPlay: false);
      }
    } else {
      _fetchTrackPreview(current, autoPlay: false);
    }
  }

  Future<void> _fetchTrackPreview(ActivePlayerTrack track,
      {required bool autoPlay}) async {
    final String key = '${track.artist}:::${track.title}';
    if (_lastFetchedKey == key && _previewUrl != null) {
      if (autoPlay && _previewUrl != null) {
        playHtmlAudio(_previewUrl!);
        setState(() => _isPlayingAudio = true);
      }
      return;
    }

    _lastFetchedKey = key;
    pauseHtmlAudio();
    setState(() {
      _loadingPreview = true;
      _isPlayingAudio = false;
      _previewUrl = null;
      _artworkUrl = null;
    });

    try {
      final String query = Uri.encodeQueryComponent('${track.artist} ${track.title}');
      final Uri url = Uri.parse(
          'https://itunes.apple.com/search?term=$query&entity=song&limit=1');
      final http.Response resp =
          await http.get(url).timeout(const Duration(seconds: 5));
      if (!mounted) return;
      if (resp.statusCode == 200) {
        final Map<String, dynamic> data =
            jsonDecode(resp.body) as Map<String, dynamic>;
        final List<dynamic> results =
            (data['results'] as List<dynamic>?) ?? <dynamic>[];
        if (results.isNotEmpty) {
          final Map<String, dynamic> item =
              results.first as Map<String, dynamic>;
          final String? preview = item['previewUrl'] as String?;
          final String? artwork = item['artworkUrl100'] as String?;
          setState(() {
            _previewUrl = preview;
            _artworkUrl = artwork;
            _loadingPreview = false;
          });
          if (autoPlay && preview != null) {
            playHtmlAudio(preview);
            setState(() => _isPlayingAudio = true);
          }
          return;
        }
      }
    } catch (_) {
      // Fallback gracefully if preview lookup fails
    }
    if (mounted) {
      setState(() => _loadingPreview = false);
    }
  }

  void _togglePlayPause() {
    if (_isPlayingAudio) {
      pauseHtmlAudio();
      setState(() => _isPlayingAudio = false);
    } else if (_previewUrl != null) {
      playHtmlAudio(_previewUrl!);
      setState(() => _isPlayingAudio = true);
    }
  }

  String? _resolveSpotifyEmbedUrl(ActivePlayerTrack? active) {
    // 1. If active track has a Spotify track URI
    final String? trackUri = active?.spotifyUri;
    if (trackUri != null && trackUri.startsWith('spotify:track:')) {
      final String id = trackUri.substring('spotify:track:'.length);
      return 'https://open.spotify.com/embed/track/$id?utm_source=generator&theme=0';
    }
    if (trackUri != null && trackUri.contains('open.spotify.com/track/')) {
      final Uri? u = Uri.tryParse(trackUri);
      if (u != null && u.pathSegments.length >= 2) {
        return 'https://open.spotify.com/embed/track/${u.pathSegments[1]}?utm_source=generator&theme=0';
      }
    }
    // 2. Otherwise if the playlist sink has a real Spotify playlist URL
    final String? plUrl =
        active?.playlistExternalUrl ?? widget.playlist.sink?.externalUrl;
    if (plUrl != null && plUrl.contains('open.spotify.com/playlist/')) {
      final Uri? u = Uri.tryParse(plUrl);
      if (u != null && u.pathSegments.length >= 2) {
        final String id = u.pathSegments[1];
        if (!id.startsWith('demo_')) {
          return 'https://open.spotify.com/embed/playlist/$id?utm_source=generator&theme=0';
        }
      }
    }
    return null;
  }

  @override
  void dispose() {
    pauseHtmlAudio();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    ref.listen<ActivePlayerTrack?>(activePlayerTrackProvider,
        (ActivePlayerTrack? prev, ActivePlayerTrack? next) {
      if (next != null &&
          (prev?.title != next.title || prev?.artist != next.artist)) {
        _fetchTrackPreview(next, autoPlay: true);
      }
    });

    final ActivePlayerTrack? active = ref.watch(activePlayerTrackProvider);
    if (active == null) return const SizedBox.shrink();

    final String? spotifyEmbedUrl = _resolveSpotifyEmbedUrl(active);
    final String spotifySearchUrl =
        'https://open.spotify.com/search/${Uri.encodeComponent("${active.artist} ${active.title}")}';
    final String ytMusicSearchUrl =
        'https://music.youtube.com/search?q=${Uri.encodeComponent("${active.artist} ${active.title}")}';

    return Container(
      decoration: BoxDecoration(
        color: colors.surfaceContainerHighest.withValues(alpha: 0.65),
        borderRadius: BorderRadius.circular(12.0),
        border: Border.all(color: colors.primary.withValues(alpha: 0.35)),
      ),
      padding: const EdgeInsets.all(BgSpace.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          // Header row: NOW PLAYING badge + Track selector / controls
          Row(
            children: <Widget>[
              Icon(
                Icons.graphic_eq_rounded,
                size: 18,
                color: colors.primary,
              ),
              const SizedBox(width: BgSpace.xs),
              Text(
                'IN-APP SOUNDTRACK DECK',
                style: text.labelSmall?.copyWith(
                  color: colors.primary,
                  letterSpacing: 1.1,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const Spacer(),
              if (spotifyEmbedUrl != null && kIsWeb)
                SegmentedButton<bool>(
                  segments: const <ButtonSegment<bool>>[
                    ButtonSegment<bool>(
                      value: false,
                      label: Text('Audio Preview'),
                      icon: Icon(Icons.headphones_rounded, size: 15),
                    ),
                    ButtonSegment<bool>(
                      value: true,
                      label: Text('Spotify Embed'),
                      icon: Icon(Icons.album_outlined, size: 15),
                    ),
                  ],
                  selected: <bool>{_showSpotifyEmbed},
                  onSelectionChanged: (Set<bool> selection) {
                    setState(() => _showSpotifyEmbed = selection.first);
                  },
                  style: const ButtonStyle(
                    visualDensity: VisualDensity.compact,
                  ),
                ),
            ],
          ),
          const SizedBox(height: BgSpace.sm),

          // Main player area
          if (spotifyEmbedUrl != null && _showSpotifyEmbed && kIsWeb) ...<Widget>[
            buildWebIframe(
              url: spotifyEmbedUrl,
              height: spotifyEmbedUrl.contains('/playlist/') ? 152 : 80,
            ),
            const SizedBox(height: BgSpace.xs),
          ],

          // Direct audio preview bar (always available so any track can play immediately)
          Container(
            padding: const EdgeInsets.symmetric(
              horizontal: BgSpace.md,
              vertical: BgSpace.sm,
            ),
            decoration: BoxDecoration(
              color: colors.surface.withValues(alpha: 0.85),
              borderRadius: BorderRadius.circular(8.0),
              border: Border.all(color: colors.outlineVariant),
            ),
            child: Row(
              children: <Widget>[
                // Artwork or vinyl placeholder
                ClipRRect(
                  borderRadius: BorderRadius.circular(6),
                  child: _artworkUrl != null
                      ? Image.network(
                          _artworkUrl!,
                          width: 44,
                          height: 44,
                          fit: BoxFit.cover,
                          errorBuilder: (_, __, ___) => _VinylPlaceholder(colors: colors),
                        )
                      : _VinylPlaceholder(colors: colors),
                ),
                const SizedBox(width: BgSpace.md),

                // Play/Pause button
                if (_loadingPreview)
                  const SizedBox(
                    width: 36,
                    height: 36,
                    child: Padding(
                      padding: EdgeInsets.all(8.0),
                      child: CircularProgressIndicator(strokeWidth: 2),
                    ),
                  )
                else
                  IconButton.filled(
                    onPressed: _previewUrl != null ? _togglePlayPause : null,
                    icon: Icon(
                      _isPlayingAudio
                          ? Icons.pause_rounded
                          : Icons.play_arrow_rounded,
                    ),
                    tooltip: _previewUrl != null
                        ? (_isPlayingAudio ? 'Pause preview' : 'Play 30s audio preview')
                        : 'No audio stream available for this track',
                  ),
                const SizedBox(width: BgSpace.md),

                // Track title & artist
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: <Widget>[
                      Text(
                        active.title,
                        style: text.titleSmall?.copyWith(
                          fontWeight: FontWeight.w700,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      Text(
                        active.album != null && active.album!.isNotEmpty
                            ? '${active.artist} · ${active.album}'
                            : active.artist,
                        style: text.bodySmall?.copyWith(
                          color: colors.onSurfaceVariant,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ],
                  ),
                ),

                // Quick launch links
                Wrap(
                  spacing: BgSpace.xs,
                  children: <Widget>[
                    TextButton.icon(
                      onPressed: () => launchUrl(
                        Uri.parse(spotifySearchUrl),
                        mode: LaunchMode.externalApplication,
                      ),
                      icon: const Icon(Icons.open_in_new, size: 14),
                      label: const Text('Spotify'),
                    ),
                    TextButton.icon(
                      onPressed: () => launchUrl(
                        Uri.parse(ytMusicSearchUrl),
                        mode: LaunchMode.externalApplication,
                      ),
                      icon: const Icon(Icons.play_circle_outline, size: 14),
                      label: const Text('YT Music'),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _VinylPlaceholder extends StatelessWidget {
  const _VinylPlaceholder({required this.colors});
  final ColorScheme colors;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 44,
      height: 44,
      color: colors.surfaceContainerHighest,
      child: Icon(
        Icons.album_rounded,
        color: colors.primary,
        size: 24,
      ),
    );
  }
}

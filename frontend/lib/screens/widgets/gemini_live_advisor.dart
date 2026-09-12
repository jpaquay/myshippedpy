import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../advisor/voice_io.dart';
import '../../api/client.dart';
import '../../api/models.dart';
import '../../app_theme.dart';
import '../../providers.dart';
import '../shell.dart';

/// Responsive Desktop & Mobile Gemini Live Forge Advisor & Executor Bar.
///
/// Allows the user to speak naturally (or tap quick voice prompt chips / type)
/// to teleport the Weathercaster across World Street-Art Geo-Caches, seed tracks
/// from their Firestore Sonic Almanac, and immediately forge & play an 18-track
/// Weather-Inspired Daylist.
class GeminiLiveAdvisorBanner extends ConsumerStatefulWidget {
  const GeminiLiveAdvisorBanner({
    this.onSurfaceRefreshNeeded,
    super.key,
  });

  final VoidCallback? onSurfaceRefreshNeeded;

  @override
  ConsumerState<GeminiLiveAdvisorBanner> createState() =>
      _GeminiLiveAdvisorBannerState();
}

class _GeminiLiveAdvisorBannerState
    extends ConsumerState<GeminiLiveAdvisorBanner>
    with SingleTickerProviderStateMixin {
  late final VoiceIo _voice;
  late final AnimationController _pulseController;
  final TextEditingController _textController = TextEditingController();

  bool _isListening = false;
  bool _isSpeaking = false;
  bool _isExecuting = false;
  bool _muted = false;
  String _liveTranscript = '';
  String? _error;

  List<AdvisorSuggestionItem> _suggestions = const <AdvisorSuggestionItem>[];
  AdvisorLiveResponse? _lastResponse;

  void _syncPulseAnimation() {
    if (_isListening || _isSpeaking || _isExecuting) {
      if (!_pulseController.isAnimating) {
        _pulseController.repeat(reverse: true);
      }
    } else {
      if (_pulseController.isAnimating) {
        _pulseController.animateTo(0.35, duration: const Duration(milliseconds: 240));
      }
    }
  }

  @override
  void initState() {
    super.initState();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1400),
      value: 0.35,
    );

    _voice = VoiceIo(
      onTranscript: (String text, bool isFinal) {
        if (!mounted) return;
        setState(() {
          _liveTranscript = text;
          _textController.text = text;
        });
        if (isFinal && text.trim().length > 3 && !_isExecuting) {
          _executeTurn(text.trim());
        }
      },
      onListeningChanged: (bool listening) {
        if (!mounted) return;
        setState(() => _isListening = listening);
        _syncPulseAnimation();
      },
      onSpeakingChanged: (bool speaking) {
        if (!mounted) return;
        setState(() => _isSpeaking = speaking);
        _syncPulseAnimation();
      },
      onError: (String err) {
        if (!mounted) return;
        setState(() => _error = err);
      },
    );

    _loadSuggestions();
  }

  @override
  void dispose() {
    _voice.dispose();
    _pulseController.dispose();
    _textController.dispose();
    super.dispose();
  }

  Future<void> _loadSuggestions() async {
    final BarogrooveApi api = ref.read(apiProvider);
    final ApiResult<List<AdvisorSuggestionItem>> res =
        await api.advisorSuggestions();
    if (!mounted) return;
    res.when(
      ok: (List<AdvisorSuggestionItem> items) {
        setState(() => _suggestions = items);
      },
      failed: (_) {},
    );
  }

  Future<void> _executeTurn(String prompt) async {
    if (prompt.trim().isEmpty || _isExecuting) return;
    HapticFeedback.lightImpact();
    _voice.stopListening();

    setState(() {
      _isExecuting = true;
      _error = null;
      _liveTranscript = prompt;
    });
    _syncPulseAnimation();

    final BarogrooveApi api = ref.read(apiProvider);
    final ForgeSelection currentSel = ref.read(forgeSelectionProvider);
    final StreetArtGeoCache? activeGc = ref.read(activeGeocacheProvider);

    final AdvisorLiveRequest req = AdvisorLiveRequest(
      prompt: prompt,
      currentGeocacheId: activeGc?.id ?? currentSel.geocacheId,
      currentThemeId: currentSel.themeId,
      currentGenreId: currentSel.genreId,
      autoForge: true,
    );

    final ApiResult<AdvisorLiveResponse> res = await api.advisorLiveTurn(req);
    if (!mounted) return;

    res.when(
      ok: (AdvisorLiveResponse r) {
        HapticFeedback.mediumImpact();
        setState(() {
          _lastResponse = r;
          _isExecuting = false;
        });
        _syncPulseAnimation();

        // Apply autonomous tool changes to app state
        final StreetArtGeoCache? gc = r.selectedGeocache;
        if (gc != null) {
          ref.read(activeGeocacheProvider.notifier).state = gc;
        }
        ref.read(forgeSelectionProvider.notifier).state =
            ref.read(forgeSelectionProvider).copyWith(
                  lat: gc?.lat,
                  lon: gc?.lon,
                  label: gc?.label,
                  geocacheId: gc?.id,
                  themeId: r.selectedThemeId,
                  genreId: r.selectedGenreId,
                  seedScrobbles:
                      r.seededScrobbles.map((ScrobbleEntry s) => s.id).toList(),
                );
        if (r.seededScrobbles.isNotEmpty) {
          ref.read(selectedSeedScrobblesProvider.notifier).state =
              r.seededScrobbles.map((ScrobbleEntry s) => s.id).toSet();
        }
        if (r.forgeResult != null) {
          ref.read(lastForgeProvider.notifier).state = r.forgeResult;
        }

        widget.onSurfaceRefreshNeeded?.call();

        // Speak the atmospheric DJ intro out loud
        if (!_muted && r.spokenSummary.isNotEmpty) {
          _voice.speak(r.spokenSummary, muted: _muted);
        }
      },
      failed: (ApiFailure<AdvisorLiveResponse> f) {
        setState(() {
          _error = f.message;
          _isExecuting = false;
        });
        _syncPulseAnimation();
      },
    );
  }

  void _openFullStudioModal(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (BuildContext ctx) => _GeminiLiveStudioSheet(
        parentState: this,
        onExecutePrompt: _executeTurn,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;
    final bool isMobile = MediaQuery.sizeOf(context).width < 680;

    return Container(
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: <Color>[
            colors.primary.withValues(alpha: 0.16),
            colors.surfaceContainerHighest.withValues(alpha: 0.45),
            colors.tertiary.withValues(alpha: 0.12),
          ],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(
          color: _isListening
              ? Colors.redAccent.withValues(alpha: 0.85)
              : _isSpeaking || _isExecuting
                  ? colors.primary.withValues(alpha: 0.85)
                  : colors.primary.withValues(alpha: 0.35),
          width: _isListening || _isSpeaking || _isExecuting ? 1.8 : 1.2,
        ),
        boxShadow: <BoxShadow>[
          BoxShadow(
            color: (_isListening ? Colors.redAccent : colors.primary)
                .withValues(alpha: _isListening || _isSpeaking ? 0.18 : 0.06),
            blurRadius: 18,
            spreadRadius: 1,
          ),
        ],
      ),
      padding: EdgeInsets.all(isMobile ? BgSpace.md : BgSpace.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          // Top Header Row: Animated Orb + Title + Controls
          Row(
            children: <Widget>[
              _AnimatedLiveOrb(
                isListening: _isListening,
                isSpeaking: _isSpeaking,
                isExecuting: _isExecuting,
                pulseController: _pulseController,
                onTap: () {
                  if (_isListening) {
                    _voice.stopListening();
                  } else {
                    _voice.startListening();
                  }
                },
              ),
              const SizedBox(width: BgSpace.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Row(
                      children: <Widget>[
                        Flexible(
                          child: Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 8,
                              vertical: 2,
                            ),
                            decoration: BoxDecoration(
                              color: colors.primary.withValues(alpha: 0.2),
                              borderRadius: BorderRadius.circular(999),
                            ),
                            child: Text(
                              isMobile
                                  ? 'GEMINI LIVE 2.5 • ADVISOR'
                                  : 'GEMINI LIVE 2.5 • VOICE ADVISOR & EXECUTOR',
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: text.labelSmall?.copyWith(
                                color: colors.primary,
                                fontWeight: FontWeight.w800,
                                letterSpacing: 0.8,
                                fontSize: 10,
                              ),
                            ),
                          ),
                        ),
                        if (_isSpeaking) ...<Widget>[
                          const SizedBox(width: 8),
                          _SpeakingWaveIndicator(color: colors.primary),
                        ],
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      _isListening
                          ? 'Listening... Speak your mood, city, or artist'
                          : _isExecuting
                              ? 'Autonomous Forge in progress: teleporting & curating...'
                              : 'Speak to teleport the Weathercaster & forge a Daylist',
                      style: text.titleSmall?.copyWith(
                        fontWeight: FontWeight.w700,
                        color: _isListening ? Colors.redAccent : colors.onSurface,
                      ),
                    ),
                  ],
                ),
              ),
              // Voice Mute/Unmute Toggle
              IconButton(
                tooltip: _muted ? 'Unmute Advisor Voice' : 'Mute Advisor Voice',
                onPressed: () {
                  setState(() => _muted = !_muted);
                  if (_muted) _voice.stopSpeaking();
                },
                icon: Icon(
                  _muted ? Icons.volume_off_outlined : Icons.volume_up_rounded,
                  size: 20,
                  color: _muted ? colors.onSurfaceVariant : colors.primary,
                ),
              ),
              // Expand Studio Button
              OutlinedButton.icon(
                onPressed: () => _openFullStudioModal(context),
                icon: const Icon(Icons.graphic_eq_rounded, size: 16),
                label: Text(isMobile ? 'STUDIO' : 'LIVE STUDIO'),
                style: OutlinedButton.styleFrom(
                  visualDensity: VisualDensity.compact,
                  side: BorderSide(color: colors.primary.withValues(alpha: 0.45)),
                ),
              ),
            ],
          ),

          const SizedBox(height: BgSpace.md),

          // Microphone / Text Input Bar (Blended Desktop + Mobile)
          Row(
            children: <Widget>[
              // Prominent Push-to-Talk Button
              FilledButton.icon(
                onPressed: _isExecuting
                    ? null
                    : () {
                        if (_isListening) {
                          _voice.stopListening();
                        } else {
                          _voice.startListening();
                        }
                      },
                style: FilledButton.styleFrom(
                  backgroundColor:
                      _isListening ? Colors.redAccent : colors.primary,
                  foregroundColor:
                      _isListening ? Colors.white : colors.onPrimary,
                  padding: EdgeInsets.symmetric(
                    horizontal: isMobile ? 14 : 18,
                    vertical: 12,
                  ),
                ),
                icon: Icon(
                  _isListening ? Icons.stop_rounded : Icons.mic_rounded,
                  size: 20,
                ),
                label: Text(
                  _isListening
                      ? 'STOP MIC'
                      : isMobile
                          ? 'SPEAK'
                          : 'SPEAK TO FORGE',
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
              ),
              const SizedBox(width: BgSpace.sm),
              // Natural Language Prompt Box
              Expanded(
                child: TextField(
                  controller: _textController,
                  enabled: !_isExecuting,
                  onSubmitted: (String val) => _executeTurn(val),
                  style: text.bodyMedium,
                  decoration: InputDecoration(
                    hintText: isMobile
                        ? 'Or type: "Tokyo night trip-hop..."'
                        : 'Or tell Gemini Live: e.g. "Take me to Tokyo at night & forge a rainy trip-hop set with Massive Attack"',
                    isDense: true,
                    contentPadding: const EdgeInsets.symmetric(
                      horizontal: 14,
                      vertical: 11,
                    ),
                    filled: true,
                    fillColor: colors.surface.withValues(alpha: 0.7),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(10),
                      borderSide: BorderSide(color: colors.outlineVariant),
                    ),
                    suffixIcon: IconButton(
                      tooltip: 'Execute Live Forge',
                      onPressed: _isExecuting
                          ? null
                          : () => _executeTurn(_textController.text),
                      icon: _isExecuting
                          ? const SizedBox(
                              width: 16,
                              height: 16,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : Icon(Icons.send_rounded,
                              size: 18, color: colors.primary),
                    ),
                  ),
                ),
              ),
            ],
          ),

          // Quick Voice Prompt Chips Ribbon
          if (_suggestions.isNotEmpty) ...<Widget>[
            const SizedBox(height: BgSpace.sm),
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: _suggestions.map((AdvisorSuggestionItem item) {
                  return Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: ActionChip(
                      avatar: Icon(
                        Icons.auto_awesome_rounded,
                        size: 15,
                        color: colors.primary,
                      ),
                      label: Text(
                        '${item.badge} (${item.title})',
                        style: text.labelSmall?.copyWith(
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      backgroundColor:
                          colors.surfaceContainerHighest.withValues(alpha: 0.6),
                      side: BorderSide(
                        color: colors.primary.withValues(alpha: 0.28),
                      ),
                      onPressed: _isExecuting
                          ? null
                          : () {
                              _textController.text = item.prompt;
                              _executeTurn(item.prompt);
                            },
                    ),
                  );
                }).toList(),
              ),
            ),
          ],

          // Error Banner if any
          if (_error != null) ...<Widget>[
            const SizedBox(height: BgSpace.sm),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              decoration: BoxDecoration(
                color: colors.errorContainer.withValues(alpha: 0.7),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Row(
                children: <Widget>[
                  Icon(Icons.info_outline,
                      size: 16, color: colors.onErrorContainer),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      _error!,
                      style: text.bodySmall
                          ?.copyWith(color: colors.onErrorContainer),
                    ),
                  ),
                ],
              ),
            ),
          ],

          // Executed Turn Result & Telemetry Card
          if (_lastResponse != null) ...<Widget>[
            const SizedBox(height: BgSpace.md),
            _ExecutedTurnTelemetryCard(
              response: _lastResponse!,
              isSpeaking: _isSpeaking,
              onReplayVoice: () =>
                  _voice.speak(_lastResponse!.spokenSummary, muted: false),
              onOpenPlaylist: () {
                AppShell.of(context)?.go(BgDestination.playlist);
              },
            ),
          ],
        ],
      ),
    );
  }
}

/// Animated concentric microphone/barometric orb.
class _AnimatedLiveOrb extends StatelessWidget {
  const _AnimatedLiveOrb({
    required this.isListening,
    required this.isSpeaking,
    required this.isExecuting,
    required this.pulseController,
    required this.onTap,
  });

  final bool isListening;
  final bool isSpeaking;
  final bool isExecuting;
  final AnimationController pulseController;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final Color activeColor = isListening
        ? Colors.redAccent
        : isSpeaking || isExecuting
            ? colors.primary
            : colors.primary.withValues(alpha: 0.8);

    return RepaintBoundary(
      child: GestureDetector(
        onTap: onTap,
        child: AnimatedBuilder(
          animation: pulseController,
          builder: (BuildContext context, Widget? child) {
            final double scale = (isListening || isSpeaking || isExecuting)
                ? 1.0 + (pulseController.value * 0.14)
                : 1.0;
            return Transform.scale(
              scale: scale,
              child: Container(
                width: 48,
                height: 48,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  gradient: RadialGradient(
                    colors: <Color>[
                      activeColor.withValues(alpha: 0.9),
                      activeColor.withValues(alpha: 0.25),
                    ],
                  ),
                  boxShadow: <BoxShadow>[
                    BoxShadow(
                      color: activeColor.withValues(alpha: 0.45),
                      blurRadius: isListening || isSpeaking ? 16 : 8,
                      spreadRadius: isListening || isSpeaking ? 3 : 1,
                    ),
                  ],
                ),
                child: Icon(
                  isListening
                      ? Icons.mic_rounded
                      : isExecuting
                          ? Icons.sync_rounded
                          : isSpeaking
                              ? Icons.graphic_eq_rounded
                              : Icons.mic_none_rounded,
                  color: Colors.white,
                  size: 24,
                ),
              ),
            );
          },
        ),
      ),
    );
  }
}

/// Animated 4-bar waveform indicator when Gemini Live is speaking.
class _SpeakingWaveIndicator extends StatefulWidget {
  const _SpeakingWaveIndicator({required this.color});
  final Color color;

  @override
  State<_SpeakingWaveIndicator> createState() => _SpeakingWaveIndicatorState();
}

class _SpeakingWaveIndicatorState extends State<_SpeakingWaveIndicator>
    with SingleTickerProviderStateMixin {
  late final AnimationController _ctrl;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 500),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return RepaintBoundary(
      child: AnimatedBuilder(
        animation: _ctrl,
        builder: (BuildContext context, Widget? _) {
          return Row(
            mainAxisSize: MainAxisSize.min,
            children: List<Widget>.generate(4, (int i) {
              final double phase = (i * 0.25 + _ctrl.value) % 1.0;
              final double h = 6 + math.sin(phase * math.pi) * 10;
              return Container(
                width: 3,
                height: h,
                margin: const EdgeInsets.symmetric(horizontal: 1.2),
                decoration: BoxDecoration(
                  color: widget.color,
                  borderRadius: BorderRadius.circular(2),
                ),
              );
            }),
          );
        },
      ),
    );
  }
}

/// Card displaying the autonomous actions executed by Gemini Live and DJ commentary.
class _ExecutedTurnTelemetryCard extends StatelessWidget {
  const _ExecutedTurnTelemetryCard({
    required this.response,
    required this.isSpeaking,
    required this.onReplayVoice,
    required this.onOpenPlaylist,
  });

  final AdvisorLiveResponse response;
  final bool isSpeaking;
  final VoidCallback onReplayVoice;
  final VoidCallback onOpenPlaylist;

  IconData _iconForTool(String tool) {
    switch (tool) {
      case 'teleport_geocache':
        return Icons.public_rounded;
      case 'select_sonic_parameters':
        return Icons.tune_rounded;
      case 'seed_from_almanac':
        return Icons.album_rounded;
      case 'execute_forge':
        return Icons.bolt_rounded;
      default:
        return Icons.check_circle_outline_rounded;
    }
  }

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Container(
      padding: const EdgeInsets.all(BgSpace.md),
      decoration: BoxDecoration(
        color: colors.surface.withValues(alpha: 0.85),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: colors.primary.withValues(alpha: 0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          // DJ Spoken Commentary Row
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Icon(Icons.record_voice_over_rounded,
                  size: 18, color: colors.primary),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  '"${response.spokenSummary}"',
                  style: text.bodyMedium?.copyWith(
                    fontStyle: FontStyle.italic,
                    color: colors.onSurface,
                    height: 1.35,
                  ),
                ),
              ),
              IconButton(
                tooltip: 'Replay Voice Commentary',
                visualDensity: VisualDensity.compact,
                onPressed: onReplayVoice,
                icon: Icon(
                  isSpeaking
                      ? Icons.volume_up_rounded
                      : Icons.replay_circle_filled_rounded,
                  size: 20,
                  color: colors.primary,
                ),
              ),
            ],
          ),

          const SizedBox(height: BgSpace.sm),

          // Telemetry Badges Wrap
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: response.actionsExecuted.map((AdvisorActionBadge badge) {
              return Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 10,
                  vertical: 6,
                ),
                decoration: BoxDecoration(
                  color: colors.primaryContainer.withValues(alpha: 0.35),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(
                    color: colors.primary.withValues(alpha: 0.3),
                  ),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: <Widget>[
                    Icon(
                      _iconForTool(badge.tool),
                      size: 15,
                      color: colors.primary,
                    ),
                    const SizedBox(width: 6),
                    Flexible(
                      child: Text(
                        badge.label,
                        style: text.labelSmall?.copyWith(
                          fontWeight: FontWeight.w700,
                          color: colors.onSurface,
                        ),
                      ),
                    ),
                  ],
                ),
              );
            }).toList(),
          ),

          if (response.forgeResult != null) ...<Widget>[
            const SizedBox(height: BgSpace.sm),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: <Widget>[
                Expanded(
                  child: Text(
                    '✓ 18-Track Daylist active in Player Deck: ${response.forgeResult!.playlist.title}',
                    style: text.labelSmall?.copyWith(
                      color: colors.primary,
                      fontWeight: FontWeight.w700,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                const SizedBox(width: 8),
                FilledButton.tonalIcon(
                  onPressed: onOpenPlaylist,
                  icon: const Icon(Icons.queue_music_rounded, size: 16),
                  label: const Text('OPEN SET & PLAY'),
                  style: FilledButton.styleFrom(
                    visualDensity: VisualDensity.compact,
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

/// Full-screen / Bottom-Sheet Gemini Live Voice Studio for mobile & desktop.
class _GeminiLiveStudioSheet extends StatefulWidget {
  const _GeminiLiveStudioSheet({
    required this.parentState,
    required this.onExecutePrompt,
  });

  final _GeminiLiveAdvisorBannerState parentState;
  final Future<void> Function(String prompt) onExecutePrompt;

  @override
  State<_GeminiLiveStudioSheet> createState() => _GeminiLiveStudioSheetState();
}

class _GeminiLiveStudioSheetState extends State<_GeminiLiveStudioSheet> {
  final TextEditingController _studioInput = TextEditingController();

  @override
  void dispose() {
    _studioInput.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;
    final _GeminiLiveAdvisorBannerState p = widget.parentState;

    return DraggableScrollableSheet(
      initialChildSize: 0.78,
      minChildSize: 0.5,
      maxChildSize: 0.95,
      builder: (BuildContext context, ScrollController scrollController) {
        return Container(
          decoration: BoxDecoration(
            color: colors.surface,
            borderRadius: const BorderRadius.vertical(top: Radius.circular(28)),
            border: Border.all(color: colors.primary.withValues(alpha: 0.35)),
          ),
          padding: const EdgeInsets.all(BgSpace.xl),
          child: ListView(
            controller: scrollController,
            children: <Widget>[
              // Drag handle
              Center(
                child: Container(
                  width: 44,
                  height: 4,
                  decoration: BoxDecoration(
                    color: colors.outlineVariant,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
              const SizedBox(height: BgSpace.lg),

              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: <Widget>[
                  Row(
                    children: <Widget>[
                      Icon(Icons.auto_awesome_rounded,
                          color: colors.primary, size: 24),
                      const SizedBox(width: 10),
                      Text(
                        'GEMINI LIVE FORGE STUDIO',
                        style: text.titleMedium?.copyWith(
                          fontWeight: FontWeight.w900,
                          letterSpacing: 0.8,
                        ),
                      ),
                    ],
                  ),
                  IconButton(
                    onPressed: () => Navigator.of(context).pop(),
                    icon: const Icon(Icons.close_rounded),
                  ),
                ],
              ),
              const SizedBox(height: 6),
              Text(
                'Speak naturally or tap any atmospheric destination below. Gemini Live will teleport your Weathercaster, seed tracks from your 15-year Firestore Almanac, and forge a fresh 18-track Daylist.',
                style: text.bodyMedium?.copyWith(color: colors.onSurfaceVariant),
              ),

              const SizedBox(height: BgSpace.xl),

              // Center Big Interactive Mic Orb for Mobile & Desktop Studio
              Center(
                child: Column(
                  children: <Widget>[
                    GestureDetector(
                      onTap: () {
                        if (p._isListening) {
                          p._voice.stopListening();
                        } else {
                          p._voice.startListening();
                        }
                        setState(() {});
                      },
                      child: Container(
                        width: 96,
                        height: 96,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          gradient: RadialGradient(
                            colors: <Color>[
                              p._isListening
                                  ? Colors.redAccent
                                  : colors.primary,
                              colors.primaryContainer.withValues(alpha: 0.2),
                            ],
                          ),
                          boxShadow: <BoxShadow>[
                            BoxShadow(
                              color: (p._isListening
                                      ? Colors.redAccent
                                      : colors.primary)
                                  .withValues(alpha: 0.4),
                              blurRadius: 28,
                              spreadRadius: 6,
                            ),
                          ],
                        ),
                        child: Icon(
                          p._isListening
                              ? Icons.stop_rounded
                              : Icons.mic_rounded,
                          size: 44,
                          color: Colors.white,
                        ),
                      ),
                    ),
                    const SizedBox(height: BgSpace.md),
                    Text(
                      p._isListening
                          ? 'Listening... Tap orb when finished speaking'
                          : 'Tap Microphone Orb to Speak',
                      style: text.titleSmall?.copyWith(
                        fontWeight: FontWeight.w700,
                        color: p._isListening
                            ? Colors.redAccent
                            : colors.primary,
                      ),
                    ),
                    if (p._liveTranscript.isNotEmpty) ...<Widget>[
                      const SizedBox(height: 8),
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 14,
                          vertical: 8,
                        ),
                        decoration: BoxDecoration(
                          color: colors.surfaceContainerHighest,
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: Text(
                          '"${p._liveTranscript}"',
                          style: text.bodyMedium?.copyWith(
                            fontStyle: FontStyle.italic,
                          ),
                          textAlign: TextAlign.center,
                        ),
                      ),
                    ],
                  ],
                ),
              ),

              const SizedBox(height: BgSpace.xl),

              // Quick Voice Destination Cards
              Text(
                'ONE-TAP GLOBAL ATMOSPHERIC PROMPTS',
                style: text.labelSmall?.copyWith(
                  color: colors.primary,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 0.9,
                ),
              ),
              const SizedBox(height: BgSpace.sm),
              ...p._suggestions.map((AdvisorSuggestionItem item) {
                return Card(
                  margin: const EdgeInsets.only(bottom: 10),
                  color: colors.surfaceContainerHighest.withValues(alpha: 0.5),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(12),
                    side: BorderSide(
                      color: colors.primary.withValues(alpha: 0.25),
                    ),
                  ),
                  child: ListTile(
                    leading: CircleAvatar(
                      backgroundColor: colors.primary.withValues(alpha: 0.2),
                      child: Icon(Icons.public_rounded,
                          color: colors.primary, size: 20),
                    ),
                    title: Text(
                      '${item.badge} • ${item.title}',
                      style: text.titleSmall
                          ?.copyWith(fontWeight: FontWeight.w700),
                    ),
                    subtitle: Text(
                      item.prompt,
                      style: text.bodySmall,
                    ),
                    trailing: FilledButton.tonal(
                      onPressed: () {
                        Navigator.of(context).pop();
                        widget.onExecutePrompt(item.prompt);
                      },
                      child: const Text('FORGE'),
                    ),
                  ),
                );
              }),
            ],
          ),
        );
      },
    );
  }
}

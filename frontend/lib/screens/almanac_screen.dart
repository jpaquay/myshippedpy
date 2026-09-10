/// The Almanac.
///
/// Asks the agent for the almanac surface via `POST /api/surfaces/action`
/// (`showAlmanac`) and renders whatever comes back. Falls back to composing
/// an AlmanacTimeline from the typed history endpoints if the agent has
/// nothing to say — same shim policy as the playlist screen, same reasoning:
/// the fallback picks a component, never a layout.
///
/// The Almanac requires a session. Signed out, we say so plainly rather than
/// showing an empty timeline that implies you have no history.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../a2ui/actions.dart';
import '../a2ui/messages.dart';
import '../a2ui/renderer.dart';
import '../api/client.dart';
import '../api/models.dart';
import '../app_theme.dart';
import '../auth/auth_service.dart';
import '../providers.dart';
import 'widgets/status_notes.dart';

class AlmanacScreen extends ConsumerStatefulWidget {
  const AlmanacScreen({super.key});

  @override
  ConsumerState<AlmanacScreen> createState() => _AlmanacScreenState();
}

class _AlmanacScreenState extends ConsumerState<AlmanacScreen> {
  bool _loading = true;
  bool _usedFallback = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    if (!ref.read(isSignedInProvider)) {
      setState(() => _loading = false);
      return;
    }

    setState(() {
      _loading = true;
      _error = null;
      _usedFallback = false;
    });

    final A2uiSurfaceController controller =
        ref.read(surfaceControllerProvider('almanac'))..reset();

    final ActionOutcome outcome =
        await ref.read(actionDispatcherProvider).send(
              const ActionResponse(
                surfaceId: 'almanac',
                actionId: 'showAlmanac',
              ),
            );

    if (!mounted) return;

    if (outcome.ok && outcome.messages.isNotEmpty) {
      controller.applyAll(outcome.messages);
      setState(() => _loading = false);
      return;
    }

    // Fallback: typed history + retrospective, bound to the same component.
    final BarogrooveApi api = ref.read(apiProvider);
    final results = await Future.wait(<Future<Object>>[
      api.almanacHistory(),
      api.retrospective(),
    ]);

    if (!mounted) return;

    final ApiResult<List<AlmanacEntry>> history =
        results[0] as ApiResult<List<AlmanacEntry>>;
    final ApiResult<Retrospective> retro =
        results[1] as ApiResult<Retrospective>;

    if (!history.isOk) {
      setState(() {
        _loading = false;
        _error = history.failureOrNull?.message;
      });
      return;
    }

    controller.applyAll(
      _fallbackEnvelope(
        history.valueOrNull ?? const <AlmanacEntry>[],
        retro.valueOrNull ?? Retrospective.empty,
      ),
    );

    setState(() {
      _loading = false;
      _usedFallback = true;
    });
  }

  @override
  Widget build(BuildContext context) {
    final BgUser? user = ref.watch(authStateProvider).valueOrNull;
    final A2uiSurfaceController controller =
        ref.watch(surfaceControllerProvider('almanac'));

    if (user == null) {
      return const _SignInRequired();
    }

    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.symmetric(
          horizontal: BgSpace.xl,
          vertical: BgSpace.lg,
        ),
        children: <Widget>[
          Text('Almanac', style: Theme.of(context).textTheme.displaySmall),
          const SizedBox(height: BgSpace.xs),
          Text(
            'Every set you have forged, and what the sky was doing at the '
            'time.',
            style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
          ),
          const SizedBox(height: BgSpace.xl),

          if (_error != null) ...<Widget>[
            DegradedNotes(
              title: 'Could not load your Almanac',
              notes: <String>[_error!],
              tone: DegradedTone.error,
              action: OutlinedButton(
                onPressed: _load,
                child: const Text('Retry'),
              ),
            ),
            const SizedBox(height: BgSpace.lg),
          ],

          if (_usedFallback) ...<Widget>[
            const DegradedNotes(
              title: 'Rendered from the local fallback',
              notes: <String>[
                'The agent did not return an almanac surface, so the client '
                    'composed one from the history endpoint.',
              ],
            ),
            const SizedBox(height: BgSpace.lg),
          ],

          if (_loading)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: BgSpace.xxl),
              child: Center(child: CircularProgressIndicator()),
            )
          else
            A2uiSurfaceView(controller: controller, padding: EdgeInsets.zero),

          const SizedBox(height: BgSpace.xxl),
        ],
      ),
    );
  }
}

List<A2uiMessage> _fallbackEnvelope(
  List<AlmanacEntry> history,
  Retrospective retro,
) {
  final String retrospectiveLine = retro.items.isEmpty
      ? ''
      : retro.items
          .map((RetrospectiveItem i) =>
              i.label.isEmpty ? i.detail : '${i.label}: ${i.detail}')
          .join('  ·  ');

  return A2uiMessage.parseBatch(<Object?>[
    <String, Object?>{
      'createSurface': <String, Object?>{
        'surfaceId': 'almanac',
        'dataModel': <String, Object?>{
          'retrospective': retrospectiveLine,
          'entries': <Object?>[
            for (final AlmanacEntry e in history)
              <String, Object?>{
                'id': e.id,
                'title': e.title,
                'theme_id': e.themeId,
                'created_at': e.createdAt,
                'track_count': e.trackCount,
                'headline': e.headline,
                'pressure_trend_6h': e.pressureTrend6h,
              },
          ],
        },
        'components': <Object?>[
          <String, Object?>{
            'id': 'root',
            'componentProperties': <String, Object?>{
              'AlmanacTimeline': <String, Object?>{
                'entries': <String, Object?>{'path': '/entries'},
                'retrospective': <String, Object?>{'path': '/retrospective'},
                'action': <String, Object?>{'actionId': 'openPastSet'},
              },
            },
          },
        ],
      },
    },
  ]);
}

class _SignInRequired extends StatelessWidget {
  const _SignInRequired();

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
              Icons.lock_outline,
              size: 30,
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
            const SizedBox(height: BgSpace.lg),
            Text('The Almanac needs an account', style: text.headlineSmall),
            const SizedBox(height: BgSpace.sm),
            ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 380),
              child: Text(
                'It is a record of your forges, so it has to know whose they '
                'are. Sign in from the menu at the top right.',
                style: text.bodyMedium,
                textAlign: TextAlign.center,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

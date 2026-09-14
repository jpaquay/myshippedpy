// BAROGROOVE — Data Viz.
//
// The **dynamic analytics surface**: ask a question about your listening data
// in natural language, get a chart and a sentence back. It does not merge with
// Almanac, which is the static archive (UX_IA_SPEC.md §3.4).
//
// This file used to be 2127 lines. It is now composition only; everything it
// draws lives in `lib/screens/dataviz/`:
//
//   dataviz_models.dart          JSON models, incl. the answer chart spec
//   dataviz_qna_transport.dart   the ONE exit point for a question — the seam
//                                for the assistant overlay (items 10 + 11)
//   dataviz_conversation.dart    turns, and the four states of an answer
//   dataviz_question_entry.dart  the entry field, the ≤3 chips, the empty hint
//   dataviz_answer_card.dart     one card: answer / loading / error / no rows
//   dataviz_answer_chart.dart    the four chart geometries
//   dataviz_dashboard.dart       the KPI ribbon and the four standing cards
//   dataviz_tokens.dart          spec tokens app_theme.dart does not have yet
//
// Gone from this destination, on purpose:
//   * the `SegmentedButton` and its `Live AI Telemetry & Trace Inspector`
//     segment — telemetry is ops, not analytics (§3.4). `TelemetryInspectorPanel`
//     itself is untouched and keeps its other entry points; only this
//     destination stops embedding it.
//   * `_buildGeminiLiveQnaBanner`, the slate900→slate800 gradient box (§6.1).
//     Its voice affordance is now the mic in the entry field.
//   * the duplicate `NetdevFooter` this file declared — the real one is
//     `widgets/netdev_footer.dart`, and §3.4 does not put a footer here.

import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;

import '../advisor/assistant_dataviz_bridge.dart';
import '../advisor/assistant_providers.dart';
import '../advisor/voice_io.dart';
import '../api/auth_interceptor.dart';
import '../app_theme.dart';
import '../config.dart';
import 'dataviz/dataviz_answer_card.dart';
import 'dataviz/dataviz_conversation.dart';
import 'dataviz/dataviz_dashboard.dart';
import 'dataviz/dataviz_models.dart';
import 'dataviz/dataviz_question_entry.dart';
import 'dataviz/dataviz_tokens.dart';

export 'dataviz/dataviz_models.dart';

class DataVizScreen extends ConsumerStatefulWidget {
  const DataVizScreen({super.key, this.conversation});

  /// Injectable for tests, and the second half of the overlay seam: pass a
  /// `DataVizConversation` built with a different `DataVizQnaTransport` and
  /// every question on this screen goes there instead.
  final DataVizConversation? conversation;

  @override
  ConsumerState<DataVizScreen> createState() => _DataVizScreenState();
}

class _DataVizScreenState extends ConsumerState<DataVizScreen> {
  late final DataVizConversation _conversation;
  late final VoiceIo _voice;

  final TextEditingController _questionController = TextEditingController();
  final FocusNode _questionFocus = FocusNode();

  /// Nothing until the backend answers.
  ///
  /// This used to be seeded with `DataVizDashboardModel.fallback()` — ~90 lines
  /// of invented analytics. Because it was the *initialiser*, every user saw
  /// 160,717 scrobbles, 102.4 BPM and "High Pressure Clarity — 20,893
  /// scrobbles" before any real data loaded, and kept seeing them if the load
  /// failed. §2 rule 4: an empty state says what is missing; it does not stand
  /// in a number.
  DataVizDashboardModel _dashboard = DataVizDashboardModel.empty;

  /// True while the first dashboard fetch is in flight, so the cards can show
  /// a shaped loading state rather than an empty one (§2 rule 3).
  bool _dashboardLoading = true;

  /// True once the dashboard fetch has failed. The cards stay empty and this
  /// drives the retry notice; there is no canned dashboard to fall back to.
  bool _dashboardFailed = false;

  bool _isDictating = false;

  /// The standing card the newest answer refers to, held for 4 s (§3.4).
  String? _highlight;
  Timer? _highlightTimer;

  @override
  void initState() {
    super.initState();

    // The overlay seam, taken (§3.4 + §6.4). The question field stays exactly
    // where it was; its ONE exit point now routes through the shared
    // conversation store as well as the analytics endpoint, so a question
    // asked here is in the assistant's history on every other destination —
    // and its `spoken_summary` is spoken by the overlay, under the overlay's
    // mute toggle. `dataviz_qna_transport.dart` is untouched.
    _conversation = widget.conversation ??
        DataVizConversation(
          transport: sharedConversationDataVizTransport(
            store: ref.read(assistantConversationProvider),
            controller: ref.read(assistantControllerProvider),
          ),
        );
    _conversation.addListener(_onConversationChanged);

    _voice = VoiceIo(
      // Dictation only. This screen does not speak, does not hold a session,
      // and does not own a conversation transport — all three belong to the
      // app-wide assistant overlay (§6).
      onTranscript: (String text, bool isFinal) {
        if (!mounted) return;
        _questionController.text = text;
        if (isFinal && text.trim().length > 3) {
          _submit(text);
        }
      },
      onListeningChanged: (bool listening) {
        if (!mounted) return;
        setState(() => _isDictating = listening);
      },
      onSpeakingChanged: (_) {},
      onError: (_) {
        if (!mounted) return;
        setState(() => _isDictating = false);
      },
    );

    unawaited(_fetchDashboard());
    unawaited(_conversation.loadStarters());
  }

  @override
  void dispose() {
    _highlightTimer?.cancel();
    _conversation.removeListener(_onConversationChanged);
    if (widget.conversation == null) _conversation.dispose();
    _voice.dispose();
    _questionController.dispose();
    _questionFocus.dispose();
    super.dispose();
  }

  void _onConversationChanged() {
    if (!mounted) return;
    final String? section = _conversation.highlightSection;
    if (section != null && section != _highlight) {
      _highlightTimer?.cancel();
      setState(() => _highlight = section);
      _highlightTimer = Timer(const Duration(seconds: 4), () {
        if (mounted) setState(() => _highlight = null);
      });
    } else {
      setState(() {});
    }
  }

  Future<void> _fetchDashboard() async {
    if (mounted) {
      setState(() {
        _dashboardLoading = true;
        _dashboardFailed = false;
      });
    }
    try {
      final Uri uri = BgConfig.resolve('/api/dataviz/dashboard');
      final Map<String, String> headers = await authHeaders();
      final http.Response resp =
          await http.get(uri, headers: headers).timeout(
                const Duration(seconds: 8),
              );

      if (resp.statusCode == 200 && mounted) {
        final Map<String, dynamic> body =
            jsonDecode(resp.body) as Map<String, dynamic>;
        setState(() {
          _dashboard = DataVizDashboardModel.fromJson(body);
          _dashboardLoading = false;
          _dashboardFailed = false;
        });
        return;
      }
    } catch (_) {
      // fall through to the failure notice below
    }
    // A failed load leaves the dashboard empty. It used to leave the canned
    // one on screen behind a "sample data" note, which asked the reader to
    // remember that every number in front of them was fictional.
    if (mounted) {
      setState(() {
        _dashboard = DataVizDashboardModel.empty;
        _dashboardLoading = false;
        _dashboardFailed = true;
      });
    }
  }

  // ---------------------------------------------------------------------
  // THE SUBMISSION PATH — one method, one call site each way.
  //
  // Every affordance on this screen that can ask something (the field's
  // submit, its send button, a suggestion chip, "Ask a follow-up", "Widen to
  // all weather", dictation) funnels through here, and this funnels into
  // `DataVizConversation.ask`, which funnels into the single
  // `DataVizQnaTransport`. The overlay worker (items 10 + 11) needs to change
  // exactly one thing — the transport passed to `DataVizConversation` — to
  // route this screen's questions into the shared conversation store.
  // ---------------------------------------------------------------------
  void _submit(String question) {
    final String q = question.trim();
    if (q.isEmpty) return;
    HapticFeedback.selectionClick();
    _questionController.clear();
    _questionFocus.unfocus();
    unawaited(_conversation.ask(q));
  }

  void _prefill(String question) {
    _questionController.text = question;
    _questionController.selection =
        TextSelection.collapsed(offset: question.length);
    _questionFocus.requestFocus();
  }

  void _toggleDictation() {
    HapticFeedback.selectionClick();
    if (_isDictating) {
      _voice.stopListening();
    } else {
      _voice.startListening();
    }
  }

  // ---------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: LayoutBuilder(
        builder: (BuildContext context, BoxConstraints constraints) {
          final double width = constraints.maxWidth;
          final bool isCompact = DvBreak.isCompact(width);
          final bool isExpanded = DvBreak.isExpanded(width);
          final double gutter = isCompact ? BgSpace.md : BgSpace.xl;
          final double maxWidth = isExpanded ? 1080 : 720;

          final Widget field = DataVizQuestionField(
            controller: _questionController,
            focusNode: _questionFocus,
            onSubmit: _submit,
            onMicPressed: _toggleDictation,
            isDictating: _isDictating,
            isBusy: _conversation.isBusy,
          );

          final Widget scroller = ListView(
            physics: const BouncingScrollPhysics(
              parent: AlwaysScrollableScrollPhysics(),
            ),
            padding: EdgeInsets.fromLTRB(
              gutter,
              isCompact ? BgSpace.md : BgSpace.lg,
              gutter,
              // §6.2 — the floating assistant bubble must never cover content.
              DvSpace.bubbleClearance,
            ),
            children: <Widget>[
              Center(
                child: ConstrainedBox(
                  constraints: BoxConstraints(maxWidth: maxWidth),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: <Widget>[
                      if (!isCompact) ...<Widget>[
                        field,
                        const SizedBox(height: BgSpace.md),
                      ],
                      DataVizSuggestionChips(
                        suggestions: _conversation.suggestions,
                        onTap: _submit,
                        enabled: !_conversation.isBusy,
                      ),
                      if (_conversation.isEmpty) ...<Widget>[
                        const SizedBox(height: BgSpace.md),
                        DataVizEmptyHint(
                          isDegraded: !_conversation.startersLoaded ||
                              _dashboardFailed,
                        ),
                      ],
                      const SizedBox(height: BgSpace.xl),
                      ..._conversationCards(isExpanded: isExpanded),
                      if (_dashboardFailed) ...<Widget>[
                        _DashboardUnavailableNotice(onRetry: _fetchDashboard),
                        const SizedBox(height: BgSpace.lg),
                      ],
                      DataVizDashboard(
                        dashboard: _dashboard,
                        isExpanded: isExpanded,
                        highlightSection: _highlight,
                        pinned: _pinnedCards(isExpanded: isExpanded),
                        isLoading: _dashboardLoading,
                      ),
                    ],
                  ),
                ),
              ),
            ],
          );

          if (!isCompact) return scroller;

          // Compact: the field is sticky at the top of the scroll view (§3.4).
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Padding(
                padding: const EdgeInsets.fromLTRB(
                  BgSpace.md,
                  BgSpace.sm,
                  BgSpace.md,
                  BgSpace.sm,
                ),
                child: field,
              ),
              Expanded(child: scroller),
            ],
          );
        },
      ),
    );
  }

  List<Widget> _conversationCards({required bool isExpanded}) {
    return <Widget>[
      for (final DataVizTurn turn in _conversation.turns)
        if (!turn.pinned) _card(turn, isExpanded: isExpanded),
    ];
  }

  List<Widget> _pinnedCards({required bool isExpanded}) {
    return <Widget>[
      for (final DataVizTurn turn in _conversation.turns)
        if (turn.pinned) _card(turn, isExpanded: isExpanded),
    ];
  }

  Widget _card(DataVizTurn turn, {required bool isExpanded}) {
    return DataVizAnswerCard(
      key: ValueKey<String>(turn.id),
      turn: turn,
      isExpanded: isExpanded,
      onRetry: () => unawaited(_conversation.retry(turn)),
      onCancel: () => _conversation.cancel(turn),
      onTogglePin: () => _conversation.togglePin(turn),
      onAskFollowUp: _prefill,
      onWiden: _submit,
    );
  }
}

/// Rung 0, never collapsed: the dashboard did not load, so it is empty.
///
/// This used to read "Showing the bundled sample dashboard ... illustrative
/// figures, not your scrobbles" above a full set of invented charts. A warning
/// label does not make a fabricated number honest — it just asks the reader to
/// keep remembering. The cards are empty now and this says why.
class _DashboardUnavailableNotice extends StatelessWidget {
  const _DashboardUnavailableNotice({required this.onRetry});

  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme colors = theme.colorScheme;

    return Container(
      key: const ValueKey<String>('dataviz-unavailable-notice'),
      padding: const EdgeInsets.all(BgSpace.md),
      decoration: BoxDecoration(
        borderRadius: BgSpace.brSm,
        border: Border.all(color: BgPalette.warn.withValues(alpha: 0.45)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const Icon(Icons.info_outline, size: 16, color: BgPalette.warn),
          const SizedBox(width: BgSpace.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(
                  'Your dashboard did not load.',
                  style: theme.textTheme.bodyMedium,
                ),
                const SizedBox(height: BgSpace.xs),
                Text(
                  'The analytics backend did not answer, so the cards below '
                  'are empty rather than filled in. Questions you ask are '
                  'still sent to the agent.',
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: colors.onSurfaceVariant),
                ),
              ],
            ),
          ),
          const SizedBox(width: BgSpace.sm),
          TextButton(onPressed: onRetry, child: const Text('Retry')),
        ],
      ),
    );
  }
}

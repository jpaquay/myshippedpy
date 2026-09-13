// The one conversation.
//
// UX_IA_SPEC.md §6.4: conversation state lives *above* the destinations, so
// switching tabs never loses history. This object is held by a Riverpod
// provider declared in `assistant_providers.dart`, which hangs off the
// `ProviderScope` at the root of the app — strictly above `AppShell`, above
// the `IndexedStack`, and therefore untouched by navigation, by a destination
// being rebuilt, or by the overlay being closed and reopened.
//
// It holds no widgets and no `BuildContext` on purpose: everything in §6.5
// (a write proposal, an edit to its arguments, a refusal, a receipt) is a
// method call here and can be asserted in a unit test with no network.

import 'package:flutter/foundation.dart';

import 'assistant_models.dart';

/// Turns, transport-independent voice flags, and the mute preference.
class AssistantConversation extends ChangeNotifier {
  AssistantConversation();

  final List<AssistantTurn> _turns = <AssistantTurn>[];

  /// Oldest first — the overlay renders newest at the bottom and auto-scrolls
  /// there (§6.3).
  List<AssistantTurn> get turns => List<AssistantTurn>.unmodifiable(_turns);

  int _seq = 0;
  bool _disposed = false;

  bool get isEmpty => _turns.isEmpty;

  /// Server-issued thread id, echoed back on every subsequent turn so the
  /// agent keeps its own context across destinations too.
  String? conversationId;

  // ---------------------------------------------------------------------
  // Voice and transport flags. The overlay paints them; nothing else may.
  // ---------------------------------------------------------------------

  bool _muted = false;

  /// Auto-speaking of `spoken_summary` used to live on the Data Viz answer
  /// card. It is the overlay's job now (§6.1), and so is the switch that
  /// turns it off.
  bool get muted => _muted;
  set muted(bool value) {
    if (_muted == value) return;
    _muted = value;
    _notify();
  }

  bool _listening = false;
  bool get listening => _listening;
  set listening(bool value) {
    if (_listening == value) return;
    _listening = value;
    _notify();
  }

  bool _speaking = false;
  bool get speaking => _speaking;
  set speaking(bool value) {
    if (_speaking == value) return;
    _speaking = value;
    _notify();
  }

  bool get busy => _turns.any((AssistantTurn t) => t.pending);

  /// True while anything at all is happening. Drives the single 2 px ring on
  /// the resting bubble (§6.2) — one ring, no halos.
  bool get active => _listening || _speaking || busy;

  String _liveTranscript = '';
  String get liveTranscript => _liveTranscript;
  set liveTranscript(String value) {
    if (_liveTranscript == value) return;
    _liveTranscript = value;
    _notify();
  }

  /// Voice was asked for and is not available here (the stub platform, a
  /// refused mic permission). Stated plainly rather than by a dead button.
  String? voiceUnavailable;

  List<String> _suggestions = const <String>[];

  /// At most three, same rule as Data Viz (§3.4). Never a carousel.
  List<String> get suggestions => _suggestions.take(3).toList(growable: false);
  set suggestions(List<String> value) {
    _suggestions = List<String>.of(value);
    _notify();
  }

  /// The newest still-pending write proposal, if any. Voice confirmation
  /// resolves against this and nothing else.
  AssistantAction? get pendingAction {
    for (int i = _turns.length - 1; i >= 0; i--) {
      final AssistantAction? a = _turns[i].action;
      if (a != null && a.isPending) return a;
    }
    return null;
  }

  // ---------------------------------------------------------------------
  // Mutations
  // ---------------------------------------------------------------------

  String _nextId(String prefix) => '$prefix-${_seq++}';

  AssistantTurn addUser(
    String text, {
    AssistantOrigin origin = AssistantOrigin.overlay,
  }) {
    final AssistantTurn turn = AssistantTurn(
      id: _nextId('u'),
      role: AssistantRole.user,
      origin: origin,
      at: DateTime.now(),
      text: text,
    );
    _turns.add(turn);
    _notify();
    return turn;
  }

  /// A placeholder agent turn, already on screen, waiting for its answer.
  AssistantTurn addPendingAgent({
    AssistantOrigin origin = AssistantOrigin.overlay,
  }) {
    final AssistantTurn turn = AssistantTurn(
      id: _nextId('a'),
      role: AssistantRole.agent,
      origin: origin,
      at: DateTime.now(),
      pending: true,
    );
    _turns.add(turn);
    _notify();
    return turn;
  }

  AssistantTurn addAgent(
    String text, {
    AssistantOrigin origin = AssistantOrigin.overlay,
    String spoken = '',
    bool error = false,
  }) {
    final AssistantTurn turn = AssistantTurn(
      id: _nextId('a'),
      role: AssistantRole.agent,
      origin: origin,
      at: DateTime.now(),
      text: text,
      spoken: spoken,
      error: error,
    );
    _turns.add(turn);
    _notify();
    return turn;
  }

  /// Fill in a placeholder in place, so the list does not jump.
  void settle(
    AssistantTurn turn, {
    required String text,
    String spoken = '',
    bool error = false,
    AssistantAction? action,
  }) {
    turn
      ..pending = false
      ..text = text
      ..spoken = spoken
      ..error = error
      ..action = action;
    _notify();
  }

  /// Attach a write proposal as its own agent turn. Full width in the list,
  /// never a modal dialog (§6.5).
  AssistantTurn addAction(AssistantAction action, {String lead = ''}) {
    final AssistantTurn turn = AssistantTurn(
      id: _nextId('c'),
      role: AssistantRole.agent,
      origin: action.voiceInitiated
          ? AssistantOrigin.voice
          : AssistantOrigin.overlay,
      at: DateTime.now(),
      text: lead,
      action: action,
    );
    _turns.add(turn);
    _notify();
    return turn;
  }

  void editArgument(AssistantAction action, String name, String value) {
    action.edit(name, value);
    _notify();
  }

  void markRunning(AssistantAction action) {
    action.status = AssistantActionStatus.running;
    _notify();
  }

  /// Collapse the card to a receipt (§6.5). One line, `BgText.meta`.
  void markSettled(
    AssistantAction action, {
    required AssistantActionStatus status,
    required String receipt,
  }) {
    action
      ..status = status
      ..receipt = receipt;
    _notify();
  }

  void clear() {
    _turns.clear();
    conversationId = null;
    _notify();
  }

  void _notify() {
    if (_disposed) return;
    notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}

// The overlay's controller.
//
// UX_IA_SPEC.md §6.1 lifts the machinery out of the 1019-line
// `GeminiLiveAdvisorBanner` — `VoiceIo`, the live turn, the execution state —
// and makes it the assistant's controller rather than a page widget. This is
// that object. It owns exactly three things:
//
//   * the voice plumbing (`advisor/voice_io.dart`, reused, not forked),
//   * the transport,
//   * the rules in §6.5 for proposing, confirming and refusing a write.
//
// It holds no `BuildContext`, so it can outlive any destination, and so the
// whole of item 11's client-side behaviour is testable with a fake transport.

import 'dart:async';

import 'assistant_models.dart';
import 'assistant_store.dart';
import 'assistant_transport.dart';
import 'voice_io.dart';

/// Glue between the store, the transport and the microphone.
class AssistantController {
  AssistantController({
    required AssistantConversation store,
    required AssistantTransport transport,
    VoiceIo Function({
      required void Function(String text, bool isFinal) onTranscript,
      required void Function(bool listening) onListeningChanged,
      required void Function(bool speaking) onSpeakingChanged,
      required void Function(String error) onError,
    })? voiceFactory,
  })  : _store = store,
        _transport = transport {
    final VoiceIo Function({
      required void Function(String, bool) onTranscript,
      required void Function(bool) onListeningChanged,
      required void Function(bool) onSpeakingChanged,
      required void Function(String) onError,
    }) make = voiceFactory ?? VoiceIo.new;

    _voice = make(
      onTranscript: _onTranscript,
      onListeningChanged: (bool v) => _store.listening = v,
      onSpeakingChanged: (bool v) => _store.speaking = v,
      onError: (String e) {
        _store
          ..listening = false
          ..voiceUnavailable = e;
      },
    );
  }

  final AssistantConversation _store;
  final AssistantTransport _transport;
  late final VoiceIo _voice;

  AssistantConversation get store => _store;

  bool get voiceSupported => _voice.isSupported;

  List<AssistantCapability> _capabilities = const <AssistantCapability>[];
  bool _capabilitiesLoaded = false;

  /// Whether the backend declares [function] as a write.
  ///
  /// Read from the manifest, never from a hardcoded list. Unknown functions
  /// are treated as writes: the safe default when we have not been told.
  bool writes(String function) {
    for (final AssistantCapability c in _capabilities) {
      if (c.name == function) return c.writes;
    }
    return true;
  }

  AssistantCapability? capability(String function) {
    for (final AssistantCapability c in _capabilities) {
      if (c.name == function) return c;
    }
    return null;
  }

  /// Pull the capability manifest once. Failure is not fatal — the server
  /// still refuses unconfirmed writes on its own.
  Future<void> loadCapabilities() async {
    if (_capabilitiesLoaded) return;
    _capabilitiesLoaded = true;
    _capabilities = await _transport.capabilities();
  }

  // ---------------------------------------------------------------------
  // Voice
  // ---------------------------------------------------------------------

  void toggleListening() {
    if (_store.listening) {
      _voice.stopListening();
    } else {
      _store.voiceUnavailable = null;
      _voice.startListening();
    }
  }

  void toggleMute() {
    _store.muted = !_store.muted;
    if (_store.muted) _voice.stopSpeaking();
  }

  /// Auto-TTS of `spoken_summary`, re-homed here from the Data Viz answer
  /// card (§6.1). The mute toggle in the overlay header is the only switch.
  Future<void> speak(String text) async {
    if (text.trim().isEmpty || _store.muted) return;
    await _voice.speak(text, muted: _store.muted);
  }

  void _onTranscript(String text, bool isFinal) {
    _store.liveTranscript = text;
    if (!isFinal) return;

    final String said = text.trim();
    _store.liveTranscript = '';
    if (said.isEmpty) return;

    // §6.5 — a voice-initiated write needs an explicit affirmative. If a
    // proposal is on screen and was raised by voice, the next thing said is
    // read as an answer to it *only* when it is unambiguously yes or no.
    // Anything else is a new question, and the card stays pending.
    final AssistantAction? pending = _store.pendingAction;
    if (pending != null && pending.voiceInitiated) {
      final String normalised = said
          .toLowerCase()
          .replaceAll(RegExp(r'[^a-z\s]'), '')
          .replaceAll(RegExp(r'\s+'), ' ')
          .trim();
      if (kAffirmatives.contains(normalised)) {
        unawaited(confirm(pending));
        return;
      }
      if (kNegatives.contains(normalised)) {
        decline(pending);
        return;
      }
    }

    unawaited(submit(said, origin: AssistantOrigin.voice));
  }

  // ---------------------------------------------------------------------
  // Turns
  // ---------------------------------------------------------------------

  /// Ask the assistant something. Every entry point funnels here.
  Future<void> submit(
    String prompt, {
    AssistantOrigin origin = AssistantOrigin.overlay,
  }) async {
    final String text = prompt.trim();
    if (text.isEmpty) return;

    unawaited(loadCapabilities());

    _store.addUser(text, origin: origin);
    final AssistantTurn slot = _store.addPendingAgent(origin: origin);

    try {
      final AssistantReply reply = await _transport.turn(
        text,
        conversationId: _store.conversationId,
        spoken: origin == AssistantOrigin.voice,
      );
      _store.conversationId = reply.conversationId ?? _store.conversationId;
      if (reply.suggestions.isNotEmpty) _store.suggestions = reply.suggestions;

      final AssistantProposal? p = reply.proposal;
      _store.settle(
        slot,
        text: reply.text.isEmpty
            ? (p == null ? 'No answer came back.' : '')
            : reply.text,
        spoken: reply.spoken,
        action: p == null
            ? null
            : _actionFrom(p, voiceInitiated: origin == AssistantOrigin.voice),
      );
      await speak(reply.spoken);
    } on AssistantUnreachable catch (e) {
      // The honest offline path. Say what broke and what to try; do not
      // pretend, do not spin forever, do not drop the question.
      _store.settle(
        slot,
        text: '${e.summary} ${e.recovery}',
        error: true,
      );
    } catch (e) {
      _store.settle(
        slot,
        text: 'An unexpected fault reached the assistant: $e. Retry.',
        error: true,
      );
    }
  }

  /// Ask the backend to run [function].
  ///
  /// Reads and selects go straight through. Writes come back as
  /// `confirmation_required` with a ticket, and become an inline card — the
  /// client never decides on its own that a write is allowed.
  Future<void> invoke(
    String function,
    Map<String, Object?> arguments, {
    bool voiceInitiated = false,
    String lead = '',
  }) async {
    await loadCapabilities();
    try {
      final AssistantActResult result =
          await _transport.act(function, arguments);
      switch (result.status) {
        case AssistantActStatus.done:
          _store.addAgent(result.receipt, origin: AssistantOrigin.overlay);
        case AssistantActStatus.confirmationRequired:
          final AssistantProposal? p = result.proposal;
          if (p == null) {
            _store.addAgent(
              'The backend asked for confirmation but sent no ticket, so '
              'nothing ran. Retry.',
              error: true,
            );
            return;
          }
          _store.addAction(
            _actionFrom(p, voiceInitiated: voiceInitiated),
            lead: lead,
          );
        case AssistantActStatus.error:
          _store.addAgent(result.message, error: true);
      }
    } on AssistantUnreachable catch (e) {
      _store.addAgent('${e.summary} ${e.recovery}', error: true);
    }
  }

  AssistantAction _actionFrom(
    AssistantProposal p, {
    required bool voiceInitiated,
  }) {
    final Map<String, Map<String, Object?>> schema = p.argumentSchema.isNotEmpty
        ? p.argumentSchema
        : (capability(p.function)?.arguments ??
            const <String, Map<String, Object?>>{});

    final List<AssistantArg> args = <AssistantArg>[];
    for (final MapEntry<String, Object?> e in p.arguments.entries) {
      final Map<String, Object?> spec =
          schema[e.key] ?? const <String, Object?>{};
      args.add(
        AssistantArg(
          name: e.key,
          label: (spec['title'] ?? _humanise(e.key)).toString(),
          value: e.value?.toString() ?? '',
          kind: _kindOf(spec['type']?.toString(), e.value),
        ),
      );
    }

    return AssistantAction(
      id: '${p.function}-${DateTime.now().microsecondsSinceEpoch}',
      function: p.function,
      title: p.title.isEmpty ? _humanise(p.function) : p.title,
      detail: p.detail,
      confirmationToken: p.token,
      args: args,
      voiceInitiated: voiceInitiated,
    );
  }

  static AssistantArgKind _kindOf(String? declared, Object? value) {
    switch (declared) {
      case 'integer':
        return AssistantArgKind.integer;
      case 'number':
        return AssistantArgKind.number;
      case 'boolean':
        return AssistantArgKind.boolean;
      case 'string':
        return AssistantArgKind.text;
    }
    if (value is int) return AssistantArgKind.integer;
    if (value is double) return AssistantArgKind.number;
    if (value is bool) return AssistantArgKind.boolean;
    return AssistantArgKind.text;
  }

  static String _humanise(String raw) {
    final String spaced = raw
        .replaceAll('_', ' ')
        .replaceAllMapped(RegExp(r'([a-z])([A-Z])'),
            (Match m) => '${m[1]} ${m[2]?.toLowerCase()}')
        .trim();
    if (spaced.isEmpty) return raw;
    return spaced[0].toUpperCase() + spaced.substring(1);
  }

  // ---------------------------------------------------------------------
  // §6.5 — confirming a write
  // ---------------------------------------------------------------------

  /// The user said yes. Sends the ticket back with whatever the arguments
  /// were *edited* to, and collapses the card to a receipt either way.
  Future<void> confirm(AssistantAction action) async {
    if (!action.isPending) return;
    _store.markRunning(action);

    try {
      final AssistantActResult result = await _transport.act(
        action.function,
        action.payload,
        confirmationToken: action.confirmationToken,
      );
      switch (result.status) {
        case AssistantActStatus.done:
          _store.markSettled(
            action,
            status: AssistantActionStatus.done,
            receipt:
                result.receipt.isEmpty ? '${action.title} — done.' : result.receipt,
          );
          await speak(result.receipt);
        case AssistantActStatus.confirmationRequired:
          // The ticket expired or had already been spent. Say so plainly and
          // make the user ask again rather than silently minting a new one.
          _store.markSettled(
            action,
            status: AssistantActionStatus.failed,
            receipt: 'Confirmation expired. Nothing was changed — ask again.',
          );
        case AssistantActStatus.error:
          _store.markSettled(
            action,
            status: AssistantActionStatus.failed,
            receipt: result.message,
          );
      }
    } on AssistantUnreachable catch (e) {
      _store.markSettled(
        action,
        status: AssistantActionStatus.failed,
        receipt: '${e.summary} Nothing was changed.',
      );
    }
  }

  /// The user said no. The ticket is simply never spent; it expires unused.
  void decline(AssistantAction action) {
    if (!action.isPending) return;
    _store.markSettled(
      action,
      status: AssistantActionStatus.declined,
      receipt: 'Cancelled. Nothing was changed.',
    );
  }

  void editArgument(AssistantAction action, String name, String value) =>
      _store.editArgument(action, name, value);

  void dispose() => _voice.dispose();
}

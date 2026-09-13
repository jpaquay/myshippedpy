// The assistant's conversation vocabulary.
//
// Deliberately widget-free and `BuildContext`-free: every state the overlay
// can be in (UX_IA_SPEC.md §6.3–§6.5) is expressible here, which is what makes
// the offline path, the write gate and the voice-confirmation rule testable
// without a network and without pumping a frame.

import 'package:flutter/foundation.dart';

/// Who said it.
enum AssistantRole {
  /// The person. Right-aligned, no bubble fill (§6.3).
  user,

  /// The agent. Left-aligned on `surfaceRaised` (§6.3).
  agent,
}

/// Where a turn entered the conversation.
///
/// There is exactly one conversation (§6.4), but it is reachable from two
/// places: the overlay itself and the Data Viz question field (§3.4). The
/// origin is kept so a turn can say where it came from, not so the store can
/// behave differently.
enum AssistantOrigin {
  /// Typed into the overlay's footer field.
  overlay,

  /// Spoken into the overlay's mic.
  voice,

  /// Asked on the Data Viz analytics surface.
  dataviz,
}

/// Lifecycle of an inline confirmation card (§6.5).
enum AssistantActionStatus {
  /// Proposed, arguments editable, waiting for an explicit Confirm.
  pending,

  /// Confirmed and in flight.
  running,

  /// Ran. The card has collapsed to a receipt.
  done,

  /// Ran and failed. Still a receipt, with the failure in it.
  failed,

  /// The user declined. Receipt says so; nothing was written.
  declined,
}

/// One editable argument on a confirmation card.
///
/// Values are carried as strings because the card lets the user retype them
/// before confirming; [AssistantAction.payload] coerces back on the way out
/// using the declared [kind].
enum AssistantArgKind { text, number, integer, boolean }

@immutable
class AssistantArg {
  const AssistantArg({
    required this.name,
    required this.label,
    required this.value,
    this.kind = AssistantArgKind.text,
    this.editable = true,
  });

  final String name;
  final String label;
  final String value;
  final AssistantArgKind kind;
  final bool editable;

  AssistantArg withValue(String next) => AssistantArg(
        name: name,
        label: label,
        value: next,
        kind: kind,
        editable: editable,
      );

  Object? get coerced {
    switch (kind) {
      case AssistantArgKind.text:
        return value;
      case AssistantArgKind.number:
        return double.tryParse(value.trim());
      case AssistantArgKind.integer:
        return int.tryParse(value.trim());
      case AssistantArgKind.boolean:
        final String v = value.trim().toLowerCase();
        return v == 'true' || v == 'yes' || v == '1';
    }
  }
}

/// A function the assistant wants to run on the user's behalf.
///
/// Read/select functions never become one of these — they act immediately
/// (§6.5, and the user's standing policy). Anything the **backend** declares
/// as a write arrives here first, as an inline card in the conversation.
class AssistantAction {
  AssistantAction({
    required this.id,
    required this.function,
    required this.title,
    required this.confirmationToken,
    required List<AssistantArg> args,
    this.detail = '',
    this.voiceInitiated = false,
  }) : _args = List<AssistantArg>.of(args);

  /// Client-side id, unique within a conversation.
  final String id;

  /// The backend's name for the function, e.g. `forge_playlist`.
  final String function;

  /// Human sentence for the card header, e.g. `Forge a new playlist`.
  final String title;

  /// One line of context under the title. May be empty.
  final String detail;

  /// Single-use ticket minted by the server when it refused to run the write.
  /// Without it the backend refuses again, which is the whole point: the
  /// client cannot manufacture consent (§6.5, item 11).
  final String confirmationToken;

  /// True when the proposal came out of a spoken turn. A voice-initiated
  /// write needs an explicit affirmative — tapping Confirm, or saying one of
  /// [kAffirmatives]. Ambiguous speech is treated as a new question.
  final bool voiceInitiated;

  final List<AssistantArg> _args;
  List<AssistantArg> get args => List<AssistantArg>.unmodifiable(_args);

  AssistantActionStatus status = AssistantActionStatus.pending;

  /// What the card collapses to once it has run (§6.5).
  String receipt = '';

  bool get isPending => status == AssistantActionStatus.pending;
  bool get isSettled =>
      status == AssistantActionStatus.done ||
      status == AssistantActionStatus.failed ||
      status == AssistantActionStatus.declined;

  void edit(String name, String value) {
    final int i = _args.indexWhere((AssistantArg a) => a.name == name);
    if (i < 0) return;
    _args[i] = _args[i].withValue(value);
  }

  /// The arguments as the backend wants them, after any edits.
  Map<String, Object?> get payload => <String, Object?>{
        for (final AssistantArg a in _args)
          if (a.coerced != null) a.name: a.coerced,
      };
}

/// Words that count as an explicit spoken yes (§6.5).
///
/// Short, unambiguous, and checked as whole words against the *entire* final
/// transcript. "Yes, but change the length to 20" is not on this list and so
/// does not confirm anything.
const Set<String> kAffirmatives = <String>{
  'confirm',
  'confirmed',
  'yes',
  'yes please',
  'do it',
  'go ahead',
  'run it',
  'ok do it',
};

/// Words that count as an explicit spoken no.
const Set<String> kNegatives = <String>{
  'cancel',
  'no',
  'no thanks',
  'stop',
  'never mind',
  'nevermind',
  'don\'t',
  'do not',
};

/// One line in the conversation.
class AssistantTurn {
  AssistantTurn({
    required this.id,
    required this.role,
    required this.origin,
    required this.at,
    this.text = '',
    this.spoken = '',
    this.action,
    this.pending = false,
    this.error = false,
  });

  final String id;
  final AssistantRole role;
  final AssistantOrigin origin;
  final DateTime at;

  String text;

  /// What the agent would say out loud. Empty when there is nothing to speak.
  String spoken;

  /// Present only on an agent turn that proposes a write.
  AssistantAction? action;

  /// The agent turn is a placeholder while its answer is in flight.
  bool pending;

  /// The turn is a failure notice, rendered in the error tone. Errors are
  /// never collapsed (§2, rule 2) and never silently swallowed.
  bool error;

  bool get isAction => action != null;
}

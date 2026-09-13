// Everything the assistant sends over the wire, behind one interface.
//
// Two endpoints, both on the backend this app already talks to:
//
//   POST /api/advisor/live   a conversational turn (the Gemini Live engine)
//   POST /api/advisor/act    invoke a named MCP capability by conversation
//   GET  /api/advisor/tools  which capabilities exist and which of them WRITE
//
// The third one matters as much as the other two. **Dart does not know which
// functions write.** It asks. The `writes` flag is declared once on the
// backend — in `backend/app/a2ui/catalog.py` for agent functions and on the
// `ToolSpec` in `backend/app/mcp/manifest.py` for MCP tools — and travels to
// the client in the manifest. There is no list of function names in this
// package, and adding a sixth write on the backend must not require a Flutter
// change (item 11 / UX_IA_SPEC.md §6.5).
//
// Nor is the flag load-bearing for safety: it only decides whether the UI
// *expects* a confirmation card. The refusal itself happens on the server.
// A client that ignores the flag and posts straight to `/api/advisor/act`
// gets `confirmation_required` and no write.

import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../api/auth_interceptor.dart';
import '../config.dart';

/// A capability the assistant may invoke, as the backend describes it.
class AssistantCapability {
  const AssistantCapability({
    required this.name,
    required this.title,
    required this.description,
    required this.writes,
    this.arguments = const <String, Map<String, Object?>>{},
    this.required = const <String>[],
  });

  final String name;
  final String title;
  final String description;

  /// Declared by the backend. `true` means a confirmation card is expected
  /// before this can run.
  final bool writes;

  /// JSON-Schema `properties` for the arguments, used to build the editable
  /// rows on the confirmation card.
  final Map<String, Map<String, Object?>> arguments;
  final List<String> required;

  static AssistantCapability fromJson(Map<String, dynamic> json) {
    final Map<String, dynamic> schema =
        (json['arguments'] as Map<String, dynamic>?) ?? <String, dynamic>{};
    final Map<String, dynamic> props =
        (schema['properties'] as Map<String, dynamic>?) ?? <String, dynamic>{};
    return AssistantCapability(
      name: (json['name'] ?? '').toString(),
      title: (json['title'] ?? json['name'] ?? '').toString(),
      description: (json['description'] ?? '').toString(),
      writes: json['writes'] == true,
      arguments: <String, Map<String, Object?>>{
        for (final MapEntry<String, dynamic> e in props.entries)
          if (e.value is Map)
            e.key: Map<String, Object?>.from(e.value as Map<dynamic, dynamic>),
      },
      required: <String>[
        for (final Object? r in (schema['required'] as List<dynamic>?) ??
            const <dynamic>[])
          r.toString(),
      ],
    );
  }
}

/// What came back from a conversational turn.
class AssistantReply {
  const AssistantReply({
    this.text = '',
    this.spoken = '',
    this.conversationId,
    this.suggestions = const <String>[],
    this.proposal,
  });

  final String text;
  final String spoken;
  final String? conversationId;
  final List<String> suggestions;

  /// The turn decided a write is wanted. The server has already refused to do
  /// it and handed back a ticket; the overlay renders the card.
  final AssistantProposal? proposal;
}

/// A refused write, plus the single-use ticket that will let it through.
class AssistantProposal {
  const AssistantProposal({
    required this.function,
    required this.title,
    required this.token,
    required this.arguments,
    this.detail = '',
    this.argumentSchema = const <String, Map<String, Object?>>{},
  });

  final String function;
  final String title;
  final String detail;

  /// Minted server-side. The client cannot forge one.
  final String token;
  final Map<String, Object?> arguments;
  final Map<String, Map<String, Object?>> argumentSchema;

  static AssistantProposal? fromJson(Map<String, dynamic>? json) {
    if (json == null) return null;
    final String token = (json['token'] ?? '').toString();
    if (token.isEmpty) return null;
    final Map<String, dynamic> schema =
        (json['argument_schema'] as Map<String, dynamic>?) ??
            <String, dynamic>{};
    final Map<String, dynamic> props =
        (schema['properties'] as Map<String, dynamic>?) ?? <String, dynamic>{};
    return AssistantProposal(
      function: (json['function'] ?? '').toString(),
      title: (json['title'] ?? json['function'] ?? '').toString(),
      detail: (json['detail'] ?? '').toString(),
      token: token,
      arguments: Map<String, Object?>.from(
        (json['arguments'] as Map<String, dynamic>?) ?? <String, dynamic>{},
      ),
      argumentSchema: <String, Map<String, Object?>>{
        for (final MapEntry<String, dynamic> e in props.entries)
          if (e.value is Map)
            e.key: Map<String, Object?>.from(e.value as Map<dynamic, dynamic>),
      },
    );
  }
}

/// The outcome of `/api/advisor/act`.
enum AssistantActStatus { done, confirmationRequired, error }

class AssistantActResult {
  const AssistantActResult({
    required this.status,
    this.receipt = '',
    this.message = '',
    this.proposal,
  });

  final AssistantActStatus status;

  /// One line for the collapsed card (§6.5).
  final String receipt;

  /// Plain-language failure, when [status] is [AssistantActStatus.error].
  final String message;

  /// Present when the server refused for want of confirmation.
  final AssistantProposal? proposal;
}

/// Raised when the assistant cannot be reached at all.
///
/// Gemini and Vertex are genuinely unreachable in some deployments (and in
/// every offline build of this app). That is a state the overlay must render
/// honestly — a plain sentence and a Retry — not a spinner that never ends.
class AssistantUnreachable implements Exception {
  const AssistantUnreachable(this.summary, this.recovery);

  final String summary;
  final String recovery;

  @override
  String toString() => '$summary $recovery';
}

/// The seam. One implementation talks HTTP; tests pass their own.
abstract class AssistantTransport {
  /// Which capabilities exist, and which of them write.
  Future<List<AssistantCapability>> capabilities();

  /// One conversational turn.
  Future<AssistantReply> turn(
    String prompt, {
    String? conversationId,
    bool spoken = false,
  });

  /// Invoke a capability. Omit [confirmationToken] to *propose* a write and
  /// receive a ticket; supply it to actually run one.
  Future<AssistantActResult> act(
    String function,
    Map<String, Object?> arguments, {
    String? confirmationToken,
  });
}

const Duration _kTimeout = Duration(seconds: 20);

/// Talks to the real backend.
class HttpAssistantTransport implements AssistantTransport {
  HttpAssistantTransport({http.Client? client}) : _client = client;

  final http.Client? _client;

  Future<http.Response> _post(String path, Map<String, Object?> body) async {
    final http.Client c = _client ?? http.Client();
    try {
      return await c
          .post(
            BgConfig.resolve(path),
            headers: <String, String>{
              'Content-Type': 'application/json',
              ...(await authHeaders()),
            },
            body: jsonEncode(body),
          )
          .timeout(_kTimeout);
    } on TimeoutException {
      throw const AssistantUnreachable(
        'The assistant did not answer in time.',
        'It may be starting up. Try again in a moment.',
      );
    } catch (_) {
      throw const AssistantUnreachable(
        'The assistant is unreachable.',
        'Check your connection, then retry.',
      );
    }
  }

  @override
  Future<List<AssistantCapability>> capabilities() async {
    final http.Client c = _client ?? http.Client();
    try {
      final http.Response resp = await c
          .get(
            BgConfig.resolve('/api/advisor/tools'),
            headers: await authHeaders(),
          )
          .timeout(const Duration(seconds: 8));
      if (resp.statusCode != 200) return const <AssistantCapability>[];
      final Map<String, dynamic> body =
          jsonDecode(resp.body) as Map<String, dynamic>;
      final List<dynamic> raw =
          (body['capabilities'] as List<dynamic>?) ?? const <dynamic>[];
      return <AssistantCapability>[
        for (final dynamic item in raw)
          if (item is Map<String, dynamic>) AssistantCapability.fromJson(item),
      ];
    } catch (_) {
      // A missing manifest is not fatal: the server still refuses writes.
      return const <AssistantCapability>[];
    }
  }

  @override
  Future<AssistantReply> turn(
    String prompt, {
    String? conversationId,
    bool spoken = false,
  }) async {
    final http.Response resp = await _post('/api/advisor/live', <String, Object?>{
      'prompt': prompt,
      if (conversationId != null) 'conversation_id': conversationId,
      // Nothing is forged as a side effect of talking. A write is proposed,
      // shown, and confirmed — never autoforged behind the user's back.
      'auto_forge': false,
    });

    if (resp.statusCode != 200) {
      throw AssistantUnreachable(
        'The assistant refused the request (HTTP ${resp.statusCode}).',
        'Retry, or rephrase the question.',
      );
    }

    final Map<String, dynamic> body;
    try {
      body = jsonDecode(resp.body) as Map<String, dynamic>;
    } catch (_) {
      throw const AssistantUnreachable(
        'The assistant sent something this app could not read.',
        'Retry. If it keeps happening the backend needs a look.',
      );
    }

    return AssistantReply(
      text: (body['reply_text'] ?? '').toString(),
      spoken: (body['spoken_summary'] ?? '').toString(),
      conversationId: body['conversation_id']?.toString(),
      suggestions: <String>[
        for (final Object? s in (body['suggested_followups'] as List<dynamic>?) ??
            const <dynamic>[])
          s.toString(),
      ],
      proposal: AssistantProposal.fromJson(
        body['confirmation'] as Map<String, dynamic>?,
      ),
    );
  }

  @override
  Future<AssistantActResult> act(
    String function,
    Map<String, Object?> arguments, {
    String? confirmationToken,
  }) async {
    final http.Response resp = await _post('/api/advisor/act', <String, Object?>{
      'function': function,
      'arguments': arguments,
      if (confirmationToken != null) 'confirmation_token': confirmationToken,
    });

    final Map<String, dynamic> body;
    try {
      body = jsonDecode(resp.body) as Map<String, dynamic>;
    } catch (_) {
      return const AssistantActResult(
        status: AssistantActStatus.error,
        message: 'The backend sent something this app could not read.',
      );
    }

    switch ((body['status'] ?? 'error').toString()) {
      case 'done':
        return AssistantActResult(
          status: AssistantActStatus.done,
          receipt: (body['receipt'] ?? 'Done.').toString(),
        );
      case 'confirmation_required':
        return AssistantActResult(
          status: AssistantActStatus.confirmationRequired,
          message: (body['message'] ?? '').toString(),
          proposal: AssistantProposal.fromJson(
            body['confirmation'] as Map<String, dynamic>?,
          ),
        );
      default:
        final Map<String, dynamic> err =
            (body['error'] as Map<String, dynamic>?) ?? <String, dynamic>{};
        return AssistantActResult(
          status: AssistantActStatus.error,
          message: (err['message'] ?? body['message'] ?? 'That did not work.')
              .toString(),
        );
    }
  }
}

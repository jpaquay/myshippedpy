/// The return path: renderer -> agent.
///
/// This file is what makes a theme chip *talk to the agent* instead of being
/// local state. When the user taps a chip, we do not mutate a local
/// `selectedTheme` variable and rebuild. We POST an `actionResponse` to
/// `/api/surfaces/action`, the agent decides what that means, and it sends
/// back A2UI messages that update the surface. The client has no opinion
/// about what a theme selection *does*.
///
/// That indirection is the point of the architecture. Resist the urge to
/// "optimise" it into local state: the moment the client decides what an
/// interaction means, the UI is defined twice.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../config.dart';
import 'messages.dart';

/// A declarative action attached to a component by the agent.
///
/// Wire shape (inside a component's properties):
/// ```json
/// "action": { "actionId": "selectTheme",
///             "payload": { "themeId": {"path": "/themes/3/id"} } }
/// ```
/// Payload values may themselves be Dynamic, so a template-generated row can
/// carry the id of *its* element. The renderer resolves them at fire time,
/// against the row's scope.
@immutable
final class A2uiAction {
  const A2uiAction({
    required this.actionId,
    this.payload = const <String, DynamicValue>{},
    this.confirm,
  });

  final String actionId;

  /// Payload entries, unresolved. The renderer resolves them against the
  /// firing node's scope so template rows send their own data.
  final Map<String, DynamicValue> payload;

  /// Optional confirmation prompt. If the agent sets it we show a dialog
  /// before firing — the agent, not the client, decides what is destructive.
  final String? confirm;

  static A2uiAction? parse(Object? raw) {
    final JsonMap? map = asJsonMap(raw);
    if (map == null) {
      // Bare string is shorthand for an action id with no payload.
      final String? id = asStringOrNull(raw);
      return id == null ? null : A2uiAction(actionId: id);
    }
    final String? id = asStringOrNull(map['actionId']) ??
        asStringOrNull(map['action']) ??
        asStringOrNull(map['id']) ??
        asStringOrNull(map['name']);
    if (id == null) return null;

    final Map<String, DynamicValue> payload = <String, DynamicValue>{};
    final JsonMap? rawPayload =
        asJsonMap(map['payload']) ?? asJsonMap(map['parameters']);
    if (rawPayload != null) {
      for (final MapEntry<String, Object?> e in rawPayload.entries) {
        final DynamicValue? v = DynamicValue.parse(e.value);
        if (v != null) payload[e.key] = v;
      }
    }

    return A2uiAction(
      actionId: id,
      payload: payload,
      confirm: asStringOrNull(map['confirm']) ??
          asStringOrNull(map['confirmation']),
    );
  }
}

/// What came back from the agent after we sent something.
@immutable
final class ActionOutcome {
  const ActionOutcome({required this.messages, this.error});

  const ActionOutcome.failed(String this.error)
      : messages = const <A2uiMessage>[];

  /// Follow-up A2UI messages to apply to the surface. Frequently empty — an
  /// action that changes nothing visible is legitimate.
  final List<A2uiMessage> messages;

  /// Human-readable failure. Non-null means the round trip did not complete;
  /// the renderer shows this inline rather than swallowing it.
  final String? error;

  bool get ok => error == null;
}

/// Sends renderer -> agent messages and returns the agent's follow-up.
abstract interface class A2uiActionDispatcher {
  Future<ActionOutcome> send(RendererMessage message);
}

/// Posts to `POST /api/surfaces/action`.
///
/// Deliberately conservative: a short timeout, one retry on a transient
/// failure, and an honest error string on the way out. Actions are user-
/// initiated, so a long silent hang is worse than a fast visible failure.
final class HttpActionDispatcher implements A2uiActionDispatcher {
  HttpActionDispatcher({
    required Future<Map<String, String>> Function() headers,
    http.Client? client,
    String path = '/api/surfaces/action',
  })  : _headers = headers,
        _client = client ?? http.Client(),
        _path = path;

  final Future<Map<String, String>> Function() _headers;
  final http.Client _client;
  final String _path;

  static const int _maxAttempts = 2;

  @override
  Future<ActionOutcome> send(RendererMessage message) async {
    final Uri uri = BgConfig.resolve(_path);
    final String body = jsonEncode(message.toJson());

    Object? lastError;
    for (var attempt = 1; attempt <= _maxAttempts; attempt++) {
      try {
        final Map<String, String> h = <String, String>{
          'content-type': 'application/json',
          'accept': 'application/json',
          ...await _headers(),
        };
        final http.Response res = await _client
            .post(uri, headers: h, body: body)
            .timeout(BgConfig.requestTimeout);

        if (res.statusCode >= 200 && res.statusCode < 300) {
          if (res.body.trim().isEmpty) {
            return const ActionOutcome(messages: <A2uiMessage>[]);
          }
          return ActionOutcome(messages: A2uiMessage.parseJson(res.body));
        }

        // 4xx is the agent telling us the action was wrong. Do not retry it;
        // retrying a rejected action just annoys the server.
        if (res.statusCode >= 400 && res.statusCode < 500) {
          return ActionOutcome.failed(
            'Agent rejected action "${_describe(message)}" '
            '(${res.statusCode}). ${_snippet(res.body)}',
          );
        }
        lastError = 'HTTP ${res.statusCode}';
      } on TimeoutException {
        lastError = 'timed out after ${BgConfig.requestTimeout.inSeconds}s';
      } catch (e) {
        lastError = e;
      }

      if (attempt < _maxAttempts) {
        await Future<void>.delayed(
          Duration(milliseconds: 250 * pow(2, attempt - 1).toInt()),
        );
      }
    }

    return ActionOutcome.failed(
      'Could not reach the agent for "${_describe(message)}": $lastError',
    );
  }

  static String _describe(RendererMessage m) => switch (m) {
        ActionResponse() => m.actionId,
        CallAgentFunction() => m.name,
        RendererFunctionResponse() => 'response:${m.functionCallId}',
      };

  static String _snippet(String body) {
    final String trimmed = body.trim();
    if (trimmed.isEmpty) return '';
    return trimmed.length <= 200 ? trimmed : '${trimmed.substring(0, 200)}…';
  }

  void dispose() => _client.close();
}

/// In-memory dispatcher for tests and for the offline demo surface. Records
/// what was sent and replays a canned response.
final class RecordingActionDispatcher implements A2uiActionDispatcher {
  RecordingActionDispatcher({this.respond});

  final List<RendererMessage> sent = <RendererMessage>[];
  final ActionOutcome Function(RendererMessage)? respond;

  @override
  Future<ActionOutcome> send(RendererMessage message) async {
    sent.add(message);
    return respond?.call(message) ??
        const ActionOutcome(messages: <A2uiMessage>[]);
  }
}

/// Generates the ids we attach to outbound function calls so the agent's
/// `agentFunctionResponse` can be correlated back.
final class CallIdGenerator {
  CallIdGenerator([Random? random]) : _random = random ?? Random();

  final Random _random;
  int _counter = 0;

  String next(String prefix) {
    _counter++;
    final int salt = _random.nextInt(0xFFFFFF);
    return '$prefix-$_counter-${salt.toRadixString(16).padLeft(6, '0')}';
  }
}

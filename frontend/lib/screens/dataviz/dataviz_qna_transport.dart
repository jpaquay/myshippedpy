// Data Viz — the ONE place a question leaves this screen.
//
// ============================================================================
// SEAM FOR PLAN ITEMS 10 + 11 (the app-wide Gemini Live assistant overlay)
// ============================================================================
// UX_IA_SPEC.md §6.1 deletes `_buildGeminiLiveQnaBanner` and folds every
// conversational affordance into one floating assistant. §3.4 keeps the Data
// Viz *analytics* question field, and says it will later write into the same
// shared conversation store as that overlay.
//
// This file is that hand-off point, and it is deliberately tiny. Everything
// downstream of a question — the HTTP call, the phase reporting, the failure
// vocabulary — is behind the single `DataVizQnaTransport` function type below.
// `DataVizConversation` takes one in its constructor and defaults to
// [httpDataVizQnaTransport].
//
// To redirect Data Viz into the shared overlay conversation, the overlay
// worker writes ONE new `DataVizQnaTransport` implementation and passes it
// where `DataVizScreen` builds its `DataVizConversation`. No widget in
// `lib/screens/dataviz/` needs to change, and there is no second chat
// transport to retire: this screen never opens its own socket, never speaks,
// and never holds voice state. Dictation is the only voice concern here and it
// stops at filling the text field.
// ============================================================================

import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../api/auth_interceptor.dart';
import '../../config.dart';
import 'dataviz_models.dart';

/// Where a question currently is in the real request pipeline.
///
/// UX_IA_SPEC.md §3.4 requires the loading status line to be "driven by real
/// agent events, not a timer", and these transitions are emitted from the
/// actual lifecycle of the actual call — never from a `Timer`.
///
/// Honest limitation: these are the three phases the *client* can observe over
/// a plain request/response call. The agent's finer-grained events (THOUGHT,
/// SQL, CHART) exist, but only on the SSE endpoint
/// `POST /api/almanac/qna/stream`, and this app has no SSE transport (and may
/// not add a dependency to get one). When the overlay worker brings a
/// streaming transport, it can emit these same three phases at the exact
/// moments the agent reports them and every widget here keeps working.
enum DataVizQnaPhase {
  /// The turn has been accepted and the request is being composed.
  understanding,

  /// The request is in flight; the agent is planning SQL and hitting BigQuery.
  querying,

  /// Bytes are back; the answer and its chart geometry are being decoded.
  drawing,
}

extension DataVizQnaPhaseLabel on DataVizQnaPhase {
  /// The `labelSmall` status line under the shimmer. Present tense, specific,
  /// and never a lie about which stage we are at.
  String get label {
    switch (this) {
      case DataVizQnaPhase.understanding:
        return 'Understanding question…';
      case DataVizQnaPhase.querying:
        return 'Querying BigQuery…';
      case DataVizQnaPhase.drawing:
        return 'Drawing…';
    }
  }
}

/// A failure the answer card can explain in plain language.
///
/// Every throw site fills in both halves: [summary] says *what failed*,
/// [recovery] says *what to try*. UX_IA_SPEC.md §3.4 makes both mandatory —
/// "an error state that says what failed and what to try".
class DataVizQnaFailure implements Exception {
  const DataVizQnaFailure(this.summary, this.recovery, {this.generatedSql = ''});

  final String summary;
  final String recovery;

  /// If the agent got as far as producing a query before failing, it is shown
  /// in an auto-expanded `SOURCE QUERY` so the user can see what was attempted.
  final String generatedSql;

  @override
  String toString() => '$summary $recovery';
}

typedef DataVizQnaPhaseSink = void Function(DataVizQnaPhase phase);

/// The seam. One function in, one answer out.
typedef DataVizQnaTransport = Future<DataVizQnAResponseModel> Function(
  String question, {
  required DataVizQnaPhaseSink onPhase,
  String? conversationId,
});

const Duration _kQnaTimeout = Duration(seconds: 20);

/// Default transport: `POST /api/dataviz/qna`.
///
/// That endpoint returns the narrative *and* — since the Data Viz answer card
/// needs them — the generated SQL, the chart geometry and the row count, so a
/// turn is one round trip. See `backend/app/dataviz/engine.py`.
Future<DataVizQnAResponseModel> httpDataVizQnaTransport(
  String question, {
  required DataVizQnaPhaseSink onPhase,
  String? conversationId,
  http.Client? client,
}) async {
  onPhase(DataVizQnaPhase.understanding);

  final Uri uri = BgConfig.resolve('/api/dataviz/qna');
  final Map<String, String> headers = <String, String>{
    'Content-Type': 'application/json',
    ...(await authHeaders()),
  };
  final String body = jsonEncode(<String, dynamic>{
    'question': question,
    'voice_mode': false,
    if (conversationId != null && conversationId.isNotEmpty)
      'conversation_id': conversationId,
  });

  onPhase(DataVizQnaPhase.querying);

  final http.Response resp;
  try {
    final Future<http.Response> pending = client == null
        ? http.post(uri, headers: headers, body: body)
        : client.post(uri, headers: headers, body: body);
    resp = await pending.timeout(_kQnaTimeout);
  } on TimeoutException {
    throw DataVizQnaFailure(
      'The analytics agent did not answer within '
      '${_kQnaTimeout.inSeconds} seconds.',
      'BigQuery may be cold. Retry, or ask something narrower — a single '
      'metric over a single period.',
    );
  } catch (_) {
    throw DataVizQnaFailure(
      'Could not reach the analytics backend at ${uri.origin}.',
      'Check the backend is running and reachable, then retry. The standing '
      'dashboard below is still readable while the agent is offline.',
    );
  }

  if (resp.statusCode != 200) {
    throw DataVizQnaFailure(
      'The analytics agent returned HTTP ${resp.statusCode}.',
      'This is a backend fault, not a bad question. Retry — the same question '
      'often succeeds once the agent has warmed up.',
    );
  }

  onPhase(DataVizQnaPhase.drawing);

  try {
    final Map<String, dynamic> decoded =
        jsonDecode(resp.body) as Map<String, dynamic>;
    return DataVizQnAResponseModel.fromJson(decoded);
  } catch (_) {
    throw const DataVizQnaFailure(
      'The agent answered in a shape this screen does not understand.',
      'The backend and the app are probably on different versions. Retry, and '
      'if it repeats, the Data Viz QnA contract has drifted.',
    );
  }
}

/// Starter questions for the empty state.
///
/// Real backend data: `GET /api/almanac/qna/status` publishes `starter_prompts`
/// from `STARTER_PROMPTS` in `backend/app/almanac/data_qna.py`, and those are
/// exactly the questions with warm disk-cache entries, so tapping one answers
/// even with no network. The local list is only a last resort when the status
/// call itself fails.
Future<List<String>> fetchStarterQuestions({http.Client? client}) async {
  try {
    final Uri uri = BgConfig.resolve('/api/almanac/qna/status');
    final Map<String, String> headers = await authHeaders();
    final Future<http.Response> pending = client == null
        ? http.get(uri, headers: headers)
        : client.get(uri, headers: headers);
    final http.Response resp =
        await pending.timeout(const Duration(seconds: 6));
    if (resp.statusCode != 200) return kFallbackStarterQuestions;

    final Map<String, dynamic> decoded =
        jsonDecode(resp.body) as Map<String, dynamic>;
    final List<dynamic> raw =
        (decoded['starter_prompts'] as List<dynamic>?) ?? const <dynamic>[];
    final List<String> prompts = raw
        .whereType<Map<String, dynamic>>()
        .map((Map<String, dynamic> e) => (e['prompt'] as String?) ?? '')
        .where((String p) => p.isNotEmpty)
        .toList();
    return prompts.isEmpty ? kFallbackStarterQuestions : prompts;
  } catch (_) {
    return kFallbackStarterQuestions;
  }
}

/// Used only when `/api/almanac/qna/status` cannot be reached. Kept identical
/// to the first three entries of the backend's `STARTER_PROMPTS` so the
/// offline experience matches the online one.
const List<String> kFallbackStarterQuestions = <String>[
  'Show me a bar chart of my top 8 artists by scrobble count',
  'Show me the distribution of scrobbles across different weather themes',
  'What is the yearly trend of my scrobbles from 2012 to 2026?',
];

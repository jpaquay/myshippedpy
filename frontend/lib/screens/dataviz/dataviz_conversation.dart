// Data Viz — conversation state.
//
// One turn per question, newest first. Holds no widgets and no `BuildContext`:
// the four states UX_IA_SPEC.md §3.4 mandates (empty / loading / error /
// no rows) are all expressible here, which is what makes them testable without
// a network.

import 'dart:async';

import 'package:flutter/foundation.dart';

import 'dataviz_models.dart';
import 'dataviz_qna_transport.dart';

/// What an answer card is currently showing.
enum DataVizTurnStatus {
  /// In flight. The card is already on screen with the question echoed.
  loading,

  /// Answered, with or without a chart.
  answered,

  /// The query ran and matched nothing. Deliberately *not* [failed]: a
  /// question that is merely too narrow is a different thing from a broken
  /// agent, and the card says so.
  noRows,

  /// Something broke. [failureSummary] / [failureRecovery] are always set.
  failed,
}

/// One question and whatever came back for it.
class DataVizTurn {
  DataVizTurn({required this.id, required this.question})
      : status = DataVizTurnStatus.loading,
        phase = DataVizQnaPhase.understanding;

  final String id;
  final String question;

  DataVizTurnStatus status;
  DataVizQnaPhase phase;
  DataVizQnAResponseModel? answer;

  String failureSummary = '';
  String failureRecovery = '';

  /// SQL to show even on failure, when the agent produced one before dying.
  String failureSql = '';

  /// "Pin to dashboard" — promotes the card below the KPI ribbon permanently
  /// (UX_IA_SPEC.md §3.4, answer-card actions).
  bool pinned = false;

  bool get isLoading => status == DataVizTurnStatus.loading;

  String get generatedSql =>
      status == DataVizTurnStatus.failed ? failureSql : (answer?.generatedSql ?? '');

  /// The `SOURCE QUERY` disclosure is collapsed by default, *except* on
  /// failure, where §3.4 auto-expands it so the user can see what was
  /// attempted.
  bool get sourceQueryStartsExpanded => status == DataVizTurnStatus.failed;

  /// The clause that narrowed the result to nothing, best-effort, from the
  /// question itself.
  ///
  /// Honest: this is a local heuristic over the question text, not something
  /// the agent reports. The backend returns a row count, not the predicate it
  /// filtered on, so the card shows the narrowing terms it can actually see
  /// and nothing more. If none are recognised the card omits the line rather
  /// than invent one.
  String get narrowing => describeNarrowing(question);
}

/// Terms worth echoing back as "this is what you narrowed to". Order matters:
/// the card prints them in the order found.
const Map<String, String> _kNarrowingTerms = <String, String>{
  'rain': 'Rain',
  'petrichor': 'Petrichor',
  'drizzle': 'Drizzle',
  'storm': 'Storm',
  'snow': 'Snow',
  'fog': 'Fog',
  'sun': 'Sun',
  'solar': 'Solar',
  'night': 'Night',
  'morning': 'Morning',
  'evening': 'Evening',
  '1980s': '1980s',
  '1990s': '1990s',
  '2000s': '2000s',
  '2010s': '2010s',
  'trip-hop': 'Trip-hop',
  'chanson': 'Chanson',
  'techno': 'Techno',
  'jazz': 'Jazz',
};

@visibleForTesting
String describeNarrowing(String question) {
  final String q = question.toLowerCase();
  final List<String> found = <String>[];
  _kNarrowingTerms.forEach((String needle, String pretty) {
    if (q.contains(needle) && !found.contains(pretty)) found.add(pretty);
  });
  if (found.isEmpty) return '';
  return found.take(3).join(' + ');
}

/// Rewrites a question so it stops filtering on weather.
///
/// Backs the single action on the no-rows card ("Widen to all weather"). Local
/// string surgery, not an agent call — it just strips the weather clause and
/// resubmits, which is what a user would do by hand.
String widenToAllWeather(String question) {
  const List<String> weatherWords = <String>[
    'in the rain',
    'when it rains',
    'rainy',
    'rain',
    'petrichor',
    'drizzle',
    'stormy',
    'storm',
    'snowy',
    'snow',
    'foggy',
    'fog',
    'sunny',
    'solar',
  ];
  String out = question;
  for (final String w in weatherWords) {
    out = out.replaceAll(RegExp(RegExp.escape(w), caseSensitive: false), '');
  }
  out = out.replaceAll(RegExp(r'\s{2,}'), ' ').trim();
  // `replaceAll` takes a literal, so the trailing-space-before-punctuation
  // tidy-up needs `replaceAllMapped` to keep the punctuation it matched.
  out = out.replaceAllMapped(
    RegExp(r'\s+([?.,])'),
    (Match m) => m.group(1)!,
  );
  if (out.isEmpty || out.length < 8) {
    return 'Show me the distribution of scrobbles across different weather themes';
  }
  return out;
}

/// The conversation behind the Data Viz question field.
class DataVizConversation extends ChangeNotifier {
  DataVizConversation({DataVizQnaTransport? transport})
      // The seam: swap this one argument and every question on this screen
      // goes somewhere else. See dataviz_qna_transport.dart.
      : _transport = transport ?? httpDataVizQnaTransport;

  final DataVizQnaTransport _transport;

  final List<DataVizTurn> _turns = <DataVizTurn>[];
  List<DataVizTurn> get turns => List<DataVizTurn>.unmodifiable(_turns);

  List<String> _starters = kFallbackStarterQuestions;
  bool _startersLoaded = false;
  bool get startersLoaded => _startersLoaded;

  int _seq = 0;
  bool _disposed = false;

  /// Turn ids abandoned by [cancel]; their results are dropped on arrival.
  final Set<String> _abandoned = <String>{};

  bool get isEmpty => _turns.isEmpty;
  bool get isBusy => _turns.any((DataVizTurn t) => t.isLoading);

  DataVizTurn? get newest => _turns.isEmpty ? null : _turns.first;

  /// Which standing dashboard card the newest answer refers to, or null.
  /// Drives the 4 s accent rule in `dataviz_dashboard.dart`.
  String? get highlightSection {
    for (final DataVizTurn t in _turns) {
      if (t.status == DataVizTurnStatus.answered) {
        return t.answer?.highlightSection;
      }
    }
    return null;
  }

  /// At most three chips, per §3.4 — never more, never a carousel.
  ///
  /// Live conversation → the agent's own `suggested_followups` from the newest
  /// answered turn. Otherwise → starter prompts published by the backend.
  List<String> get suggestions {
    for (final DataVizTurn t in _turns) {
      final List<String> f = t.answer?.suggestedFollowups ?? const <String>[];
      if (f.isNotEmpty) {
        return f
            .where((String s) => s.trim().isNotEmpty)
            .take(3)
            .toList(growable: false);
      }
    }
    return _starters.take(3).toList(growable: false);
  }

  Future<void> loadStarters() async {
    final List<String> fetched = await fetchStarterQuestions();
    if (_disposed) return;
    _starters = fetched;
    _startersLoaded = true;
    notifyListeners();
  }

  /// Ask. The only way a question enters the pipeline from this screen.
  Future<void> ask(String rawQuestion) async {
    final String question = rawQuestion.trim();
    if (question.isEmpty) return;

    final DataVizTurn turn =
        DataVizTurn(id: 'turn_${_seq++}', question: question);
    _turns.insert(0, turn);
    notifyListeners();

    await _run(turn);
  }

  /// Re-run a turn in place, from the `Retry` button on a failed card.
  Future<void> retry(DataVizTurn turn) async {
    if (!_turns.contains(turn) || turn.isLoading) return;
    turn.status = DataVizTurnStatus.loading;
    turn.phase = DataVizQnaPhase.understanding;
    turn.failureSummary = '';
    turn.failureRecovery = '';
    turn.failureSql = '';
    _abandoned.remove(turn.id);
    notifyListeners();
    await _run(turn);
  }

  /// Drop a turn that is still loading.
  ///
  /// The HTTP request is abandoned rather than aborted — `package:http` has no
  /// cancellation and no dependency may be added — so the response is ignored
  /// when it lands. The card disappears immediately, which is what cancel
  /// means to the user.
  void cancel(DataVizTurn turn) {
    if (!turn.isLoading) return;
    _abandoned.add(turn.id);
    _turns.remove(turn);
    notifyListeners();
  }

  void togglePin(DataVizTurn turn) {
    turn.pinned = !turn.pinned;
    notifyListeners();
  }

  void dismiss(DataVizTurn turn) {
    _turns.remove(turn);
    _abandoned.add(turn.id);
    notifyListeners();
  }

  Future<void> _run(DataVizTurn turn) async {
    try {
      final DataVizQnAResponseModel result = await _transport(
        turn.question,
        onPhase: (DataVizQnaPhase phase) {
          if (_disposed || _abandoned.contains(turn.id)) return;
          turn.phase = phase;
          notifyListeners();
        },
      );
      if (_disposed || _abandoned.contains(turn.id)) return;

      turn.answer = result;
      final bool plotted = result.chartSpec?.hasData ?? false;
      final bool emptyResult = !plotted &&
          result.rowCount == 0 &&
          result.generatedSql.isNotEmpty;
      turn.status =
          emptyResult ? DataVizTurnStatus.noRows : DataVizTurnStatus.answered;
    } on DataVizQnaFailure catch (e) {
      if (_disposed || _abandoned.contains(turn.id)) return;
      turn.status = DataVizTurnStatus.failed;
      turn.failureSummary = e.summary;
      turn.failureRecovery = e.recovery;
      turn.failureSql = e.generatedSql;
    } catch (e) {
      if (_disposed || _abandoned.contains(turn.id)) return;
      turn.status = DataVizTurnStatus.failed;
      turn.failureSummary = 'The question could not be answered.';
      turn.failureRecovery =
          'An unexpected fault reached the screen: $e. Retry, or rephrase.';
    } finally {
      if (!_disposed) notifyListeners();
    }
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}

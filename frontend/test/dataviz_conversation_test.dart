// Data Viz — the four states UX_IA_SPEC.md §3.4 makes mandatory.
//
// These tests never touch the network: the conversation takes a
// `DataVizQnaTransport`, so every state is reachable by returning (or
// throwing) from a fake. That is the whole point of the seam.

import 'dart:async';

import 'package:barogroove/screens/dataviz/dataviz_answer_card.dart';
import 'package:barogroove/screens/dataviz/dataviz_conversation.dart';
import 'package:barogroove/screens/dataviz/dataviz_models.dart';
import 'package:barogroove/screens/dataviz/dataviz_qna_transport.dart';
import 'package:barogroove/screens/dataviz/dataviz_question_entry.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

// ---------------------------------------------------------------------------
// Fixtures, shaped exactly like what `POST /api/dataviz/qna` returns offline.
// ---------------------------------------------------------------------------

Map<String, dynamic> _answerJson({
  int rowCount = 7,
  bool withSeries = true,
  String sql = 'SELECT weather_theme, COUNT(*) AS n\nFROM scrobbles\nGROUP BY 1',
  List<String> followups = const <String>[
    'How does that change at night?',
    'Which artist leads that theme?',
    'Show me the same split by decade',
  ],
}) {
  return <String, dynamic>{
    'answer_text':
        'Warm front haze leads at 25,090 plays, just ahead of petrichor.',
    'spoken_summary': 'Warm front haze leads.',
    'highlight_section': 'weather_affinity',
    'key_metric_badge': 'Warm front haze #1',
    'suggested_followups': followups,
    'matching_scrobbles': <dynamic>[],
    'model_used': 'gemini-2.5-flash',
    'generated_sql': sql,
    'row_count': rowCount,
    'data_engine': 'bigquery_data_qna_v1beta',
    'chart_spec': withSeries
        ? <String, dynamic>{
            'chart_type': 'horizontal_bar',
            'title': 'Scrobble Count by Weather Theme',
            'subtitle': 'BigQuery OLAP',
            'x_label': 'Weather Theme',
            'y_label': 'Scrobble Count',
            'series': <dynamic>[
              <String, dynamic>{
                'label': 'warm_front_haze',
                'value': 25090.0,
                'color_hex': '#FFB74D',
                'percentage': 15.6,
                'extra_label': '25,090',
              },
              <String, dynamic>{
                'label': 'petrichor',
                'value': 24376.0,
                'color_hex': '#4FC3F7',
                'percentage': 15.2,
                'extra_label': '24,376',
              },
            ],
          }
        : null,
  };
}

DataVizQnaTransport _okTransport(Map<String, dynamic> json) {
  return (String q, {required DataVizQnaPhaseSink onPhase, String? conversationId}) async {
    onPhase(DataVizQnaPhase.understanding);
    onPhase(DataVizQnaPhase.querying);
    onPhase(DataVizQnaPhase.drawing);
    return DataVizQnAResponseModel.fromJson(json);
  };
}

DataVizQnaTransport _failingTransport(DataVizQnaFailure failure) {
  return (String q, {required DataVizQnaPhaseSink onPhase, String? conversationId}) async {
    onPhase(DataVizQnaPhase.querying);
    throw failure;
  };
}

/// Never completes until [gate] is resolved — parks a turn in `loading`.
DataVizQnaTransport _hangingTransport(
  Completer<DataVizQnAResponseModel> gate, {
  DataVizQnaPhase stopAt = DataVizQnaPhase.querying,
}) {
  return (String q, {required DataVizQnaPhaseSink onPhase, String? conversationId}) {
    onPhase(DataVizQnaPhase.understanding);
    if (stopAt == DataVizQnaPhase.querying ||
        stopAt == DataVizQnaPhase.drawing) {
      onPhase(DataVizQnaPhase.querying);
    }
    if (stopAt == DataVizQnaPhase.drawing) {
      onPhase(DataVizQnaPhase.drawing);
    }
    return gate.future;
  };
}

Widget _host(Widget child) => MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(
          child: SizedBox(width: 390, child: child),
        ),
      ),
    );

Widget _cardHost(DataVizTurn turn) => _host(
      DataVizAnswerCard(
        turn: turn,
        isExpanded: false,
        onRetry: () {},
        onCancel: () {},
        onTogglePin: () {},
        onAskFollowUp: (_) {},
        onWiden: (_) {},
      ),
    );

void main() {
  group('DataVizConversation — state machine', () {
    test('starts empty and offers at most three starter questions', () {
      final DataVizConversation c =
          DataVizConversation(transport: _okTransport(_answerJson()));
      addTearDown(c.dispose);

      expect(c.isEmpty, isTrue);
      expect(c.isBusy, isFalse);
      expect(c.suggestions.length, lessThanOrEqualTo(3));
      expect(c.suggestions, equals(kFallbackStarterQuestions.take(3)));
    });

    test('a question with rows lands as answered and carries its SQL + chart',
        () async {
      final DataVizConversation c =
          DataVizConversation(transport: _okTransport(_answerJson()));
      addTearDown(c.dispose);

      await c.ask('Show me the distribution across weather themes');

      expect(c.turns, hasLength(1));
      final DataVizTurn t = c.turns.first;
      expect(t.status, DataVizTurnStatus.answered);
      expect(t.generatedSql, contains('SELECT weather_theme'));
      expect(t.answer!.chartSpec!.geometry, QnaChartGeometry.horizontalBar);
      expect(t.answer!.chartSpec!.series, hasLength(2));
      expect(t.sourceQueryStartsExpanded, isFalse);
    });

    test('zero rows with a real query is noRows, not failed', () async {
      final DataVizConversation c = DataVizConversation(
        transport: _okTransport(_answerJson(rowCount: 0, withSeries: false)),
      );
      addTearDown(c.dispose);

      await c.ask('Which 1990s trip-hop do I play in the rain?');

      expect(c.turns.first.status, DataVizTurnStatus.noRows);
      expect(c.turns.first.narrowing, 'Rain + 1990s + Trip-hop');
    });

    test('a transport failure keeps both halves of the message', () async {
      final DataVizConversation c = DataVizConversation(
        transport: _failingTransport(
          const DataVizQnaFailure(
            'The analytics agent did not answer within 20 seconds.',
            'BigQuery may be cold. Retry, or ask something narrower.',
            generatedSql: 'SELECT 1',
          ),
        ),
      );
      addTearDown(c.dispose);

      await c.ask('anything');

      final DataVizTurn t = c.turns.first;
      expect(t.status, DataVizTurnStatus.failed);
      expect(t.failureSummary, contains('did not answer'));
      expect(t.failureRecovery, contains('Retry'));
      // §3.4 — SOURCE QUERY is auto-expanded on failure.
      expect(t.sourceQueryStartsExpanded, isTrue);
      expect(t.generatedSql, 'SELECT 1');
    });

    test('phases advance through the real call, not a timer', () async {
      final Completer<DataVizQnAResponseModel> gate =
          Completer<DataVizQnAResponseModel>();
      final DataVizConversation c =
          DataVizConversation(transport: _hangingTransport(gate));
      addTearDown(c.dispose);

      final Future<void> pending = c.ask('slow one');
      expect(c.isBusy, isTrue);
      expect(c.turns.first.phase, DataVizQnaPhase.querying);
      expect(c.turns.first.phase.label, 'Querying BigQuery…');

      gate.complete(DataVizQnAResponseModel.fromJson(_answerJson()));
      await pending;
      expect(c.isBusy, isFalse);
    });

    test('cancel removes the pending card and ignores the late answer',
        () async {
      final Completer<DataVizQnAResponseModel> gate =
          Completer<DataVizQnAResponseModel>();
      final DataVizConversation c =
          DataVizConversation(transport: _hangingTransport(gate));
      addTearDown(c.dispose);

      final Future<void> pending = c.ask('slow one');
      c.cancel(c.turns.first);
      expect(c.turns, isEmpty);

      gate.complete(DataVizQnAResponseModel.fromJson(_answerJson()));
      await pending;
      expect(c.turns, isEmpty);
    });

    test('retry re-runs a failed turn in place', () async {
      bool firstCall = true;
      final DataVizConversation c = DataVizConversation(
        transport: (String q,
            {required DataVizQnaPhaseSink onPhase, String? conversationId}) async {
          if (firstCall) {
            firstCall = false;
            throw const DataVizQnaFailure('boom', 'try again');
          }
          return DataVizQnAResponseModel.fromJson(_answerJson());
        },
      );
      addTearDown(c.dispose);

      await c.ask('flaky');
      expect(c.turns.first.status, DataVizTurnStatus.failed);

      await c.retry(c.turns.first);
      expect(c.turns, hasLength(1));
      expect(c.turns.first.status, DataVizTurnStatus.answered);
    });

    test('suggestions switch from starters to the agent follow-ups', () async {
      final DataVizConversation c =
          DataVizConversation(transport: _okTransport(_answerJson()));
      addTearDown(c.dispose);

      expect(c.suggestions.first, kFallbackStarterQuestions.first);
      await c.ask('anything');
      expect(c.suggestions, <String>[
        'How does that change at night?',
        'Which artist leads that theme?',
        'Show me the same split by decade',
      ]);
    });

    test('an answer nominates the standing card to highlight', () async {
      final DataVizConversation c =
          DataVizConversation(transport: _okTransport(_answerJson()));
      addTearDown(c.dispose);

      expect(c.highlightSection, isNull);
      await c.ask('anything');
      expect(c.highlightSection, 'weather_affinity');
    });

    test('pinning moves a card without losing it', () async {
      final DataVizConversation c =
          DataVizConversation(transport: _okTransport(_answerJson()));
      addTearDown(c.dispose);

      await c.ask('anything');
      expect(c.turns.first.pinned, isFalse);
      c.togglePin(c.turns.first);
      expect(c.turns.first.pinned, isTrue);
      expect(c.turns, hasLength(1));
    });
  });

  group('Question-text helpers', () {
    test('describeNarrowing echoes only terms it can actually see', () {
      expect(describeNarrowing('Which 1990s tracks do I play in the rain?'),
          'Rain + 1990s');
      expect(describeNarrowing('what are my top artists'), '');
    });

    test('widenToAllWeather strips the weather clause', () {
      expect(
        widenToAllWeather('Which 1990s tracks do I play in the rain?'),
        'Which 1990s tracks do I play?',
      );
    });

    test('widenToAllWeather falls back rather than emit a stub question', () {
      expect(widenToAllWeather('rain'), contains('weather themes'));
    });
  });

  group('Answer card — the four renderings', () {
    testWidgets('loading echoes the question, shimmers, and names the stage',
        (WidgetTester tester) async {
      final DataVizTurn turn =
          DataVizTurn(id: 't1', question: 'What do I play in the rain?')
            ..phase = DataVizQnaPhase.querying;

      await tester.pumpWidget(_cardHost(turn));
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text('“What do I play in the rain?”'), findsOneWidget);
      expect(find.byKey(const ValueKey<String>('dataviz-loading-status')),
          findsOneWidget);
      expect(find.text('Querying BigQuery…'), findsOneWidget);
      // Cancel is available for the whole duration.
      expect(find.text('Cancel'), findsOneWidget);
      expect(find.text('Pin to dashboard'), findsNothing);

      await tester.pumpWidget(const SizedBox.shrink());
    });

    testWidgets('answered shows the sentence, the chart and SOURCE QUERY',
        (WidgetTester tester) async {
      final DataVizTurn turn = DataVizTurn(id: 't2', question: 'Weather split?')
        ..status = DataVizTurnStatus.answered
        ..answer = DataVizQnAResponseModel.fromJson(_answerJson());

      await tester.pumpWidget(_cardHost(turn));
      await tester.pumpAndSettle();

      expect(find.textContaining('Warm front haze leads'), findsOneWidget);
      expect(find.text('SOURCE QUERY'), findsOneWidget);
      expect(find.text('Ask a follow-up'), findsOneWidget);
      expect(find.text('Pin to dashboard'), findsOneWidget);

      // Collapsed by default; the SQL is not on screen until asked for.
      expect(find.textContaining('SELECT weather_theme'), findsNothing);
      await tester.tap(find.text('SOURCE QUERY'));
      await tester.pumpAndSettle();
      expect(find.textContaining('SELECT weather_theme'), findsOneWidget);
      expect(find.text('Gemini Data Analytics · BigQuery'), findsOneWidget);
    });

    testWidgets('error says what failed, what to try, and offers Retry',
        (WidgetTester tester) async {
      final DataVizTurn turn = DataVizTurn(id: 't3', question: 'Weather split?')
        ..status = DataVizTurnStatus.failed
        ..failureSummary = 'Could not reach the analytics backend.'
        ..failureRecovery = 'Check the backend is running, then retry.'
        ..failureSql = 'SELECT 1';

      await tester.pumpWidget(_cardHost(turn));
      await tester.pumpAndSettle();

      expect(find.byKey(const ValueKey<String>('dataviz-error-notice')),
          findsOneWidget);
      expect(find.text('Could not reach the analytics backend.'), findsOneWidget);
      expect(find.text('Check the backend is running, then retry.'),
          findsOneWidget);
      expect(find.widgetWithText(OutlinedButton, 'Retry'), findsOneWidget);
      // Auto-expanded so the user sees what was attempted.
      expect(find.textContaining('SELECT 1'), findsOneWidget);
    });

    testWidgets('no rows is distinct from error and offers one action',
        (WidgetTester tester) async {
      final DataVizTurn turn = DataVizTurn(
        id: 't4',
        question: 'Which 1990s trip-hop do I play in the rain?',
      )
        ..status = DataVizTurnStatus.noRows
        ..answer = DataVizQnAResponseModel.fromJson(
            _answerJson(rowCount: 0, withSeries: false));

      await tester.pumpWidget(_cardHost(turn));
      await tester.pumpAndSettle();

      expect(find.byKey(const ValueKey<String>('dataviz-no-rows')),
          findsOneWidget);
      expect(find.text('Nothing matched that.'), findsOneWidget);
      expect(find.textContaining('Rain + 1990s + Trip-hop'), findsOneWidget);
      expect(find.widgetWithText(OutlinedButton, 'Widen to all weather'),
          findsOneWidget);
      expect(find.byKey(const ValueKey<String>('dataviz-error-notice')),
          findsNothing);
    });
  });

  group('Question entry', () {
    testWidgets('the field is the spec field, not a banner',
        (WidgetTester tester) async {
      final TextEditingController controller = TextEditingController();
      final FocusNode node = FocusNode();
      addTearDown(controller.dispose);
      addTearDown(node.dispose);

      String? asked;
      await tester.pumpWidget(_host(
        DataVizQuestionField(
          controller: controller,
          focusNode: node,
          onSubmit: (String q) => asked = q,
          onMicPressed: () {},
          isDictating: false,
          isBusy: false,
        ),
      ));

      expect(find.text('Ask about your listening data'), findsOneWidget);
      expect(find.byIcon(Icons.search), findsOneWidget);
      expect(find.byIcon(Icons.mic_none), findsOneWidget);

      await tester.enterText(
          find.byKey(const ValueKey<String>('dataviz-question-field')),
          'top artists');
      await tester.testTextInput.receiveAction(TextInputAction.search);
      expect(asked, 'top artists');
    });

    testWidgets('never renders more than three chips',
        (WidgetTester tester) async {
      await tester.pumpWidget(_host(
        DataVizSuggestionChips(
          suggestions: const <String>['a', 'b', 'c', 'd', 'e'],
          onTap: (_) {},
          enabled: true,
        ),
      ));

      expect(find.byType(ActionChip), findsNWidgets(3));
    });
  });
}

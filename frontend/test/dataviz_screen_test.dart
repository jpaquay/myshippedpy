// Data Viz — the composed destination at 390 × 844 and at 1280.
//
// Offline is the normal case for this test (and for the sandbox): the
// dashboard fetch fails, so what renders is the degraded-but-honest surface.
// That is exactly the state worth pinning down.

import 'package:barogroove/screens/dataviz/dataviz_conversation.dart';
import 'package:barogroove/screens/dataviz/dataviz_qna_transport.dart';
import 'package:barogroove/screens/dataviz_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

DataVizQnaTransport _staticTransport = (
  String q, {
  required DataVizQnaPhaseSink onPhase,
  String? conversationId,
}) async {
  onPhase(DataVizQnaPhase.drawing);
  return DataVizQnAResponseModel.fromJson(<String, dynamic>{
    'answer_text': 'Warm front haze leads at 25,090 plays.',
    'spoken_summary': '',
    'highlight_section': 'weather_affinity',
    'key_metric_badge': 'Warm front haze #1',
    'suggested_followups': <String>['And at night?'],
    'matching_scrobbles': <dynamic>[],
    'model_used': 'gemini-2.5-flash',
    'generated_sql': 'SELECT 1',
    'row_count': 1,
    'data_engine': 'local_olap_synthesizer',
    'chart_spec': <String, dynamic>{
      'chart_type': 'donut',
      'title': 'Share',
      'subtitle': '',
      'x_label': '',
      'y_label': '',
      'series': <dynamic>[
        <String, dynamic>{
          'label': 'warm_front_haze',
          'value': 3.0,
          'color_hex': '',
          'percentage': 60.0,
          'extra_label': '3',
        },
        <String, dynamic>{
          'label': 'petrichor',
          'value': 2.0,
          'color_hex': '',
          'percentage': 40.0,
          'extra_label': '2',
        },
      ],
    },
  });
};

Future<void> _pumpAt(WidgetTester tester, Size size,
    DataVizConversation conversation) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);

  await tester.pumpWidget(
    ProviderScope(
      child: MaterialApp(home: DataVizScreen(conversation: conversation)),
    ),
  );
  // Let the failing dashboard/starters fetches settle without waiting on a
  // real timeout.
  await tester.pump();
  await tester.pump(const Duration(seconds: 1));
}

void main() {
  testWidgets('renders at 390 × 844 with no overflow and no telemetry segment',
      (WidgetTester tester) async {
    final DataVizConversation c =
        DataVizConversation(transport: _staticTransport);
    addTearDown(c.dispose);

    await _pumpAt(tester, const Size(390, 844), c);

    // The question field is rung 0 and present before anything is asked.
    expect(find.byKey(const ValueKey<String>('dataviz-question-field')),
        findsOneWidget);
    expect(find.text('Ask about your listening data'), findsOneWidget);

    // Empty state teaches rather than showing a hero card.
    expect(find.byKey(const ValueKey<String>('dataviz-empty-hint')),
        findsOneWidget);
    expect(find.textContaining('Welcome to Data Viz'), findsNothing);

    // §3.4 removes the telemetry inspector from this destination.
    expect(find.byType(SegmentedButton<int>), findsNothing);
    expect(find.text('Live AI Telemetry & Trace Inspector'), findsNothing);

    // The standing dashboard is the empty state, and it is still there.
    expect(find.text('SUMMARY'), findsOneWidget);

    expect(tester.takeException(), isNull);
  });

  testWidgets('asking a question renders an answer card with its chart',
      (WidgetTester tester) async {
    final DataVizConversation c =
        DataVizConversation(transport: _staticTransport);
    addTearDown(c.dispose);

    await _pumpAt(tester, const Size(390, 844), c);

    await tester.enterText(
      find.byKey(const ValueKey<String>('dataviz-question-field')),
      'Which weather theme do I play most?',
    );
    await tester.testTextInput.receiveAction(TextInputAction.search);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    expect(find.text('“Which weather theme do I play most?”'), findsOneWidget);
    expect(find.textContaining('Warm front haze leads'), findsOneWidget);
    expect(find.text('SOURCE QUERY'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('renders at 1280 without overflow', (WidgetTester tester) async {
    final DataVizConversation c =
        DataVizConversation(transport: _staticTransport);
    addTearDown(c.dispose);

    await _pumpAt(tester, const Size(1280, 900), c);

    expect(find.byKey(const ValueKey<String>('dataviz-question-field')),
        findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}

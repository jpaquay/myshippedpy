// The one assistant overlay — UX_IA_SPEC.md §6.
//
// The live session cannot be exercised for real here: Gemini and Vertex are
// unreachable from this sandbox. That is the point of several of these tests.
// The offline path is a *product state*, not a gap, and it is pinned down the
// same way the happy path is.

import 'package:barogroove/advisor/assistant_action_card.dart';
import 'package:barogroove/advisor/assistant_controller.dart';
import 'package:barogroove/advisor/assistant_models.dart';
import 'package:barogroove/advisor/assistant_overlay.dart';
import 'package:barogroove/advisor/assistant_providers.dart';
import 'package:barogroove/advisor/assistant_store.dart';
import 'package:barogroove/advisor/assistant_transport.dart';
import 'package:barogroove/advisor/assistant_dataviz_bridge.dart';
import 'package:barogroove/app_theme.dart';
import 'package:barogroove/screens/dataviz/dataviz_conversation.dart';
import 'package:barogroove/screens/dataviz/dataviz_models.dart';
import 'package:barogroove/screens/dataviz/dataviz_qna_transport.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

// ======================================================================
// A transport that never touches the network.
// ======================================================================

class _FakeTransport implements AssistantTransport {
  _FakeTransport({
    this.reply,
    this.unreachable = false,
    this.capabilityList = const <AssistantCapability>[],
    this.actResults = const <AssistantActResult>[],
  });

  AssistantReply? reply;
  bool unreachable;
  List<AssistantCapability> capabilityList;
  List<AssistantActResult> actResults;

  final List<({String function, Map<String, Object?> args, String? token})>
      calls = <({String function, Map<String, Object?> args, String? token})>[];

  int _actIndex = 0;

  @override
  Future<List<AssistantCapability>> capabilities() async => capabilityList;

  @override
  Future<AssistantReply> turn(
    String prompt, {
    String? conversationId,
    bool spoken = false,
  }) async {
    if (unreachable) {
      throw const AssistantUnreachable(
        'The assistant is unreachable.',
        'Check your connection, then retry.',
      );
    }
    return reply ?? AssistantReply(text: 'Heard: $prompt');
  }

  @override
  Future<AssistantActResult> act(
    String function,
    Map<String, Object?> arguments, {
    String? confirmationToken,
  }) async {
    calls.add((function: function, args: arguments, token: confirmationToken));
    if (_actIndex < actResults.length) return actResults[_actIndex++];
    return const AssistantActResult(status: AssistantActStatus.done);
  }
}

/// Voice that does nothing, so the controller can be built off-web.
AssistantController _controller(
  AssistantConversation store,
  AssistantTransport transport,
) =>
    AssistantController(store: store, transport: transport);

Widget _host({
  required AssistantConversation store,
  required AssistantTransport transport,
  required Widget child,
}) {
  return ProviderScope(
    overrides: <Override>[
      assistantConversationProvider.overrideWith((Ref ref) => store),
      assistantTransportProvider.overrideWithValue(transport),
    ],
    child: MaterialApp(
      theme: BgTheme.light(),
      home: Scaffold(body: child),
    ),
  );
}

void main() {
  // ====================================================================
  // §6.2 — resting state
  // ====================================================================

  group('the bubble', () {
    testWidgets('is one 56 px monochrome circle with a forum icon',
        (WidgetTester tester) async {
      final AssistantConversation store = AssistantConversation();
      await tester.pumpWidget(
        _host(
          store: store,
          transport: _FakeTransport(),
          child: const BgAssistantBubble(),
        ),
      );

      expect(find.byIcon(Icons.forum_outlined), findsOneWidget);

      final Finder sized = find.descendant(
        of: find.byType(BgAssistantBubble),
        matching: find.byType(AnimatedContainer),
      );
      final AnimatedContainer box = tester.widget<AnimatedContainer>(sized);
      expect(box.constraints?.maxWidth ?? 0, 56);
      expect(box.constraints?.maxHeight ?? 0, 56);
    });

    testWidgets('reserves exactly the bubble-clearance token',
        (WidgetTester tester) async {
      late double inset;
      await tester.pumpWidget(
        MaterialApp(
          home: Builder(
            builder: (BuildContext context) {
              inset = BgAssistantBubble.reservedBottomInset(context);
              return const SizedBox.shrink();
            },
          ),
        ),
      );
      expect(inset, BgSpace.bubbleClearance);
    });

    testWidgets('fades and shrinks away when the bubble is hidden',
        (WidgetTester tester) async {
      final AssistantConversation store = AssistantConversation();
      final ProviderContainer container = ProviderContainer();
      addTearDown(container.dispose);

      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: ProviderScope(
            overrides: <Override>[
              assistantConversationProvider.overrideWith((Ref ref) => store),
              assistantTransportProvider
                  .overrideWithValue(_FakeTransport()),
            ],
            child: MaterialApp(
              theme: BgTheme.light(),
              home: const Scaffold(body: BgAssistantBubble()),
            ),
          ),
        ),
      );

      expect(
        tester.widget<AnimatedOpacity>(find.byType(AnimatedOpacity)).opacity,
        1,
      );
    });
  });

  // ====================================================================
  // §6.4 — one conversation, above the destinations
  // ====================================================================

  group('conversation persistence', () {
    test('the store is the same object across provider reads', () {
      final ProviderContainer container = ProviderContainer();
      addTearDown(container.dispose);

      final AssistantConversation a =
          container.read(assistantConversationProvider);
      a.addUser('first question');

      // Reading again — which is what a freshly built destination does — must
      // hand back the same conversation, not a new one.
      final AssistantConversation b =
          container.read(assistantConversationProvider);
      expect(identical(a, b), isTrue);
      expect(b.turns.single.text, 'first question');
    });

    testWidgets('history survives a destination being torn down and rebuilt',
        (WidgetTester tester) async {
      final AssistantConversation store = AssistantConversation();
      final _FakeTransport transport = _FakeTransport();

      Widget page(String label) => _host(
            store: store,
            transport: transport,
            child: Column(
              children: <Widget>[
                Text(label),
                const Expanded(child: AssistantPanelBody()),
              ],
            ),
          );

      await tester.pumpWidget(page('forge'));
      store.addUser('what is the sky doing');
      await tester.pump();
      expect(find.text('what is the sky doing'), findsOneWidget);

      // Navigate away: the whole subtree is replaced.
      await tester.pumpWidget(
        _host(
          store: store,
          transport: transport,
          child: const Text('somewhere else'),
        ),
      );
      await tester.pump();
      expect(find.text('what is the sky doing'), findsNothing);

      // …and back. The turn is still there.
      await tester.pumpWidget(page('dataviz'));
      await tester.pump();
      expect(find.text('what is the sky doing'), findsOneWidget);
    });
  });

  // ====================================================================
  // The offline path — honest, not a spinner
  // ====================================================================

  group('offline', () {
    test('an unreachable assistant becomes a plain, recoverable sentence',
        () async {
      final AssistantConversation store = AssistantConversation();
      final AssistantController c =
          _controller(store, _FakeTransport(unreachable: true));

      await c.submit('forge me something');

      expect(store.turns.length, 2);
      final AssistantTurn agent = store.turns.last;
      expect(agent.role, AssistantRole.agent);
      expect(agent.pending, isFalse, reason: 'never a spinner that never ends');
      expect(agent.error, isTrue);
      expect(agent.text, contains('unreachable'));
      expect(agent.text, contains('retry'.toLowerCase()),
          reason: 'says what to try, not only what broke');
    });

    testWidgets('the failure is rendered in the error tone, never collapsed',
        (WidgetTester tester) async {
      final AssistantConversation store = AssistantConversation();
      await tester.pumpWidget(
        _host(
          store: store,
          transport: _FakeTransport(unreachable: true),
          child: const AssistantPanelBody(),
        ),
      );

      await tester.enterText(find.byType(TextField).last, 'hello');
      await tester.testTextInput.receiveAction(TextInputAction.send);
      await tester.pumpAndSettle();

      expect(
        find.textContaining('The assistant is unreachable.'),
        findsOneWidget,
      );
    });
  });

  // ====================================================================
  // §6.5 — confirming writes, on the client side
  // ====================================================================

  group('write confirmation', () {
    AssistantAction proposal({bool voice = false}) => AssistantAction(
          id: 'a1',
          function: 'forge_playlist',
          title: 'Forge a playlist from the sky',
          confirmationToken: 'tok-1',
          voiceInitiated: voice,
          args: const <AssistantArg>[
            AssistantArg(
              name: 'length',
              label: 'Length',
              value: '18',
              kind: AssistantArgKind.integer,
            ),
          ],
        );

    test('a proposal runs nothing until the user confirms', () async {
      final AssistantConversation store = AssistantConversation();
      final _FakeTransport transport = _FakeTransport();
      final AssistantController c = _controller(store, transport);

      final AssistantAction action = proposal();
      store.addAction(action);
      expect(transport.calls, isEmpty);

      await c.confirm(action);
      expect(transport.calls.single.function, 'forge_playlist');
      expect(transport.calls.single.token, 'tok-1');
      expect(action.status, AssistantActionStatus.done);
    });

    test('declining spends no ticket and writes nothing', () {
      final AssistantConversation store = AssistantConversation();
      final _FakeTransport transport = _FakeTransport();
      final AssistantController c = _controller(store, transport);

      final AssistantAction action = proposal();
      store.addAction(action);
      c.decline(action);

      expect(transport.calls, isEmpty);
      expect(action.status, AssistantActionStatus.declined);
      expect(action.receipt, contains('Nothing was changed'));
    });

    test('edited arguments are what gets sent', () async {
      final AssistantConversation store = AssistantConversation();
      final _FakeTransport transport = _FakeTransport();
      final AssistantController c = _controller(store, transport);

      final AssistantAction action = proposal();
      store.addAction(action);
      c.editArgument(action, 'length', '24');
      await c.confirm(action);

      expect(transport.calls.single.args['length'], 24);
    });

    test('the backend, not Dart, decides what writes', () async {
      final AssistantConversation store = AssistantConversation();
      final _FakeTransport transport = _FakeTransport(
        capabilityList: const <AssistantCapability>[
          AssistantCapability(
            name: 'select_theme',
            title: 'Select theme',
            description: '',
            writes: false,
          ),
          AssistantCapability(
            name: 'forge_playlist',
            title: 'Forge',
            description: '',
            writes: true,
          ),
        ],
      );
      final AssistantController c = _controller(store, transport);
      await c.loadCapabilities();

      expect(c.writes('select_theme'), isFalse);
      expect(c.writes('forge_playlist'), isTrue);
      // Unknown is treated as a write: the safe default when we have not
      // been told. No hardcoded name list anywhere in Dart.
      expect(c.writes('something_new_the_backend_added'), isTrue);
    });

    test('a read/select capability is not gratuitously gated', () async {
      final AssistantConversation store = AssistantConversation();
      final _FakeTransport transport = _FakeTransport(
        actResults: const <AssistantActResult>[
          AssistantActResult(
            status: AssistantActStatus.done,
            receipt: 'Theme set to petrichor.',
          ),
        ],
      );
      final AssistantController c = _controller(store, transport);

      await c.invoke('select_theme', <String, Object?>{'themeId': 'petrichor'});

      expect(store.turns.single.text, 'Theme set to petrichor.');
      expect(store.turns.single.action, isNull,
          reason: 'no confirmation card for a select');
    });

    test('a write proposed by the server becomes a card, not an execution',
        () async {
      final AssistantConversation store = AssistantConversation();
      final _FakeTransport transport = _FakeTransport(
        actResults: const <AssistantActResult>[
          AssistantActResult(
            status: AssistantActStatus.confirmationRequired,
            proposal: AssistantProposal(
              function: 'reforge',
              title: 'Forge another pass',
              token: 'tok-9',
              arguments: <String, Object?>{'lat': 50.85, 'lon': 4.35},
            ),
          ),
        ],
      );
      final AssistantController c = _controller(store, transport);

      await c.invoke('reforge', <String, Object?>{'lat': 50.85, 'lon': 4.35});

      final AssistantAction? card = store.turns.single.action;
      expect(card, isNotNull);
      expect(card!.isPending, isTrue);
      expect(card.confirmationToken, 'tok-9');
      // One call — the refused proposal. Nothing ran.
      expect(transport.calls.length, 1);
      expect(transport.calls.single.token, isNull);
    });

    testWidgets('the card is inline, shows every argument, and does NOT '
        'autofocus Confirm', (WidgetTester tester) async {
      final AssistantConversation store = AssistantConversation();
      store.addAction(proposal());

      await tester.pumpWidget(
        _host(
          store: store,
          transport: _FakeTransport(),
          child: const AssistantPanelBody(),
        ),
      );

      expect(find.byType(AssistantActionCard), findsOneWidget);
      // Never a modal dialog (§6.5).
      expect(find.byType(Dialog), findsNothing);
      expect(find.byType(AlertDialog), findsNothing);

      expect(find.text('LENGTH'), findsOneWidget);
      expect(find.widgetWithText(FilledButton, 'Confirm'), findsOneWidget);
      expect(find.widgetWithText(TextButton, 'Cancel'), findsOneWidget);

      final FilledButton confirm = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, 'Confirm'),
      );
      expect(confirm.autofocus, isFalse);
    });

    testWidgets('it collapses to a receipt once it has run',
        (WidgetTester tester) async {
      final AssistantConversation store = AssistantConversation();
      final AssistantAction action = proposal();
      store.addAction(action);

      await tester.pumpWidget(
        _host(
          store: store,
          transport: _FakeTransport(),
          child: const AssistantPanelBody(),
        ),
      );
      expect(find.widgetWithText(FilledButton, 'Confirm'), findsOneWidget);

      store.markSettled(
        action,
        status: AssistantActionStatus.done,
        receipt: 'Forged 18 tracks.',
      );
      await tester.pumpAndSettle();

      expect(find.widgetWithText(FilledButton, 'Confirm'), findsNothing);
      expect(find.text('Forged 18 tracks.'), findsOneWidget);
    });
  });

  // ====================================================================
  // §6.5 — a voice-initiated write needs an explicit affirmative
  // ====================================================================

  group('voice confirmation', () {
    test('“confirm” and “yes” are affirmatives; “maybe later” is not', () {
      expect(kAffirmatives.contains('confirm'), isTrue);
      expect(kAffirmatives.contains('yes'), isTrue);
      expect(kAffirmatives.contains('maybe later'), isFalse);
      expect(kAffirmatives.contains('yes but make it 20 tracks'), isFalse);
    });

    test('a voice proposal carries the flag so the card can say so', () {
      final AssistantConversation store = AssistantConversation();
      final AssistantAction action = AssistantAction(
        id: 'v1',
        function: 'rate_track',
        title: 'Love this track',
        confirmationToken: 'tok-v',
        voiceInitiated: true,
        args: const <AssistantArg>[],
      );
      store.addAction(action);
      expect(store.pendingAction, same(action));
      expect(store.pendingAction!.voiceInitiated, isTrue);
    });

    testWidgets('the card tells a voice user what counts as yes',
        (WidgetTester tester) async {
      final AssistantConversation store = AssistantConversation();
      store.addAction(
        AssistantAction(
          id: 'v2',
          function: 'rate_track',
          title: 'Love this track',
          confirmationToken: 'tok-v',
          voiceInitiated: true,
          args: const <AssistantArg>[],
        ),
      );

      await tester.pumpWidget(
        _host(
          store: store,
          transport: _FakeTransport(),
          child: const AssistantPanelBody(),
        ),
      );

      expect(find.textContaining('Say “confirm”'), findsOneWidget);
    });
  });

  // ====================================================================
  // §3.4 + §6.4 — Data Viz writes into the SAME conversation
  // ====================================================================

  group('the Data Viz seam', () {
    DataVizQnAResponseModel answer() =>
        DataVizQnAResponseModel.fromJson(<String, dynamic>{
          'answer_text': 'The 1990s — 31% of wet-weather plays.',
          'spoken_summary': 'Mostly nineties when it rains.',
          'highlight_section': 'weather_affinity',
          'key_metric_badge': '',
          'suggested_followups': <String>['And at night?'],
          'matching_scrobbles': <dynamic>[],
          'model_used': 'gemini-2.5-flash',
          'generated_sql': 'SELECT 1',
          'row_count': 1,
          'data_engine': 'local_olap_synthesizer',
        });

    test('an analytics question and its answer land in the shared store',
        () async {
      final AssistantConversation store = AssistantConversation();
      final AssistantController controller =
          _controller(store, _FakeTransport());

      final DataVizQnaTransport transport =
          sharedConversationDataVizTransport(
        store: store,
        controller: controller,
        inner: (
          String q, {
          required DataVizQnaPhaseSink onPhase,
          String? conversationId,
        }) async =>
            answer(),
      );

      final DataVizConversation conversation =
          DataVizConversation(transport: transport);
      addTearDown(conversation.dispose);

      await conversation.ask('Which decade do I play in the rain?');

      // Two turns in the ONE conversation, tagged as coming from Data Viz.
      expect(store.turns.length, 2);
      expect(store.turns.first.role, AssistantRole.user);
      expect(store.turns.first.origin, AssistantOrigin.dataviz);
      expect(store.turns.last.text, contains('1990s'));
      expect(store.turns.last.spoken, 'Mostly nineties when it rains.');

      // And the answer card on Data Viz is unaffected — it still got the
      // full model, SQL and all.
      expect(conversation.turns.single.answer?.generatedSql, 'SELECT 1');
    });

    test('a failed analytics question is recorded, not lost', () async {
      final AssistantConversation store = AssistantConversation();
      final AssistantController controller =
          _controller(store, _FakeTransport());

      final DataVizQnaTransport transport =
          sharedConversationDataVizTransport(
        store: store,
        controller: controller,
        inner: (
          String q, {
          required DataVizQnaPhaseSink onPhase,
          String? conversationId,
        }) async =>
            throw const DataVizQnaFailure(
          'The analytics agent is unreachable.',
          'Retry in a moment.',
        ),
      );

      final DataVizConversation conversation =
          DataVizConversation(transport: transport);
      addTearDown(conversation.dispose);

      await conversation.ask('anything');

      expect(store.turns.last.error, isTrue);
      expect(store.turns.last.text, contains('unreachable'));
    });

    test('mute is the overlay’s switch, and it silences the Data Viz answer',
        () async {
      final AssistantConversation store = AssistantConversation();
      final AssistantController controller =
          _controller(store, _FakeTransport());

      expect(store.muted, isFalse);
      controller.toggleMute();
      expect(store.muted, isTrue,
          reason: 'auto-TTS and its toggle were re-homed here from the '
              'Data Viz answer card (§6.1)');
    });
  });
}

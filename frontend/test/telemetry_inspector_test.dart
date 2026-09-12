import 'package:barogroove/a2ui/messages.dart';
import 'package:barogroove/a2ui/renderer.dart';
import 'package:barogroove/api/models.dart';
import 'package:barogroove/screens/widgets/telemetry_inspector_panel.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('Telemetry JSON Models (F12)', () {
    test('TelemetrySummaryModel.fromJson parses full payload and surface breakdown', () {
      final json = <String, dynamic>{
        'total_calls': 42,
        'total_tokens': 18450,
        'total_input_tokens': 12300,
        'total_output_tokens': 6150,
        'avg_latency_ms': 142.8,
        'active_sessions': 5,
        'stored_memories': 12,
        'by_surface': <String, dynamic>{
          'advisor': 18,
          'dataviz': 12,
          'forge': 8,
          'a2ui': 4,
        },
      };

      final summary = TelemetrySummaryModel.fromJson(json);
      expect(summary.totalCalls, 42);
      expect(summary.totalAiCalls, 42);
      expect(summary.totalTokens, 18450);
      expect(summary.totalInputTokens, 12300);
      expect(summary.totalOutputTokens, 6150);
      expect(summary.avgLatencyMs, closeTo(142.8, 0.01));
      expect(summary.activeSessions, 5);
      expect(summary.storedMemories, 12);
      expect(summary.bySurface['advisor'], 18);
      expect(summary.bySurface['dataviz'], 12);
    });

    test('TrajectoryRecordModel.fromJson parses W3C trace context, tokens, and tool steps', () {
      final json = <String, dynamic>{
        'trajectory_id': 'traj_9981',
        'trace_id': '4bf92f3577b34da6a3ce929d0e0e4736',
        'span_id': '00f067aa0ba902b7',
        'gcp_trace_path': 'projects/barogroove-ai/traces/4bf92f3577b34da6a3ce929d0e0e4736',
        'timestamp_utc': '2026-09-12T12:00:00Z',
        'surface': 'advisor',
        'operation': 'advisor_live_turn',
        'execution_path': 'vertex_gemini_2.5_flash',
        'model': 'gemini-2.5-flash',
        'system_instruction': 'You are the BaroGroove atmospheric advisor.',
        'prompt': 'Suggest a rainy afternoon set.',
        'output': 'Here is a Petrichor & Rain Front set led by Massive Attack.',
        'latency_ms': 285.4,
        'status': 'ok',
        'session_id': 'sess_01',
        'conversation_id': 'conv_01',
        'tokens': <String, dynamic>{
          'prompt_tokens': 310,
          'candidate_tokens': 140,
          'total_tokens': 450,
        },
        'tool_steps': <Map<String, dynamic>>[
          <String, dynamic>{
            'name': 'query_weather_scrobbles',
            'args': <String, dynamic>{'theme': 'petrichor'},
            'result_summary': 'Found 42 matching tracks',
            'latency_ms': 38.2,
          },
        ],
      };

      final traj = TrajectoryRecordModel.fromJson(json);
      expect(traj.trajectoryId, 'traj_9981');
      expect(traj.traceId, '4bf92f3577b34da6a3ce929d0e0e4736');
      expect(traj.spanId, '00f067aa0ba902b7');
      expect(traj.gcpTracePath, contains('projects/barogroove-ai/traces/'));
      expect(traj.surface, 'advisor');
      expect(traj.executionPath, 'vertex_gemini_2.5_flash');
      expect(traj.tokens.totalTokens, 450);
      expect(traj.toolSteps.length, 1);
      expect(traj.toolSteps.first.name, 'query_weather_scrobbles');
    });

    test('HealthStatus parses nested TelemetrySummaryModel', () {
      final json = <String, dynamic>{
        'ok': true,
        'degraded': <String>[],
        'telemetry': <String, dynamic>{
          'total_calls': 15,
          'total_tokens': 6400,
          'active_sessions': 2,
          'stored_memories': 7,
        },
      };

      final health = HealthStatus.fromJson(json);
      expect(health.ok, isTrue);
      expect(health.telemetry, isNotNull);
      expect(health.telemetry!.totalCalls, 15);
      expect(health.telemetry!.storedMemories, 7);
    });

    test('AdvisorLiveRequest and AdvisorLiveResponse serialize/parse session and trace metadata', () {
      const req = AdvisorLiveRequest(
        prompt: 'Play something for falling barometric pressure',
        sessionId: 'sess_abc',
        conversationId: 'conv_xyz',
      );
      final reqJson = req.toJson();
      expect(reqJson['session_id'], 'sess_abc');
      expect(reqJson['conversation_id'], 'conv_xyz');

      final resp = AdvisorLiveResponse.fromJson(<String, dynamic>{
        'reply_text': 'Cueing Bristol trip-hop.',
        'spoken_summary': 'Cueing Bristol trip-hop.',
        'model_used': 'gemini-2.5-flash',
        'trajectory_id': 'traj_live_01',
        'session_id': 'sess_abc',
        'conversation_id': 'conv_xyz',
        'latency_ms': 198.5,
      });
      expect(resp.trajectoryId, 'traj_live_01');
      expect(resp.sessionId, 'sess_abc');
      expect(resp.conversationId, 'conv_xyz');
      expect(resp.latencyMs, closeTo(198.5, 0.1));
    });
  });

  group('TelemetryInspectorPanel Widget Tests (F14)', () {
    const sampleSummary = TelemetrySummaryModel(
      totalAiCalls: 28,
      tokenUsage: TokenUsageModel(
        promptTokens: 8200,
        candidateTokens: 4200,
        totalTokens: 12400,
      ),
      activeSessions: 3,
      totalSessions: 5,
      totalConversations: 4,
      storedMemories: 4,
      avgLatencyMs: 175.0,
      trajectoryCountsBySurface: <String, int>{
        'advisor': 14,
        'dataviz': 10,
        'forge': 4,
      },
      trajectoryCountsByPath: <String, int>{
        'vertex_gemini_2.5_flash': 28,
      },
      errorCount: 0,
    );

    final sampleTrajectories = <TrajectoryRecordModel>[
      const TrajectoryRecordModel(
        trajectoryId: 'traj_test_1',
        sessionId: 'sess_test_1',
        conversationId: 'conv_test_1',
        userId: 'demo',
        surface: 'advisor',
        endpoint: 'generate_sonic_advice',
        createdAt: '2026-09-12T13:15:00Z',
        latencyMs: 210.5,
        traceId: 'trace_w3c_000111222333',
        spanId: 'span_0001',
        gcpTrace: 'projects/bgwork/traces/trace_w3c_000111222333',
        requestedModel: 'gemini-2.5-flash',
        executionPath: 'vertex_gemini_2.5_flash',
        httpStatus: 200,
        tokenUsage: TokenUsageModel(
          promptTokens: 250,
          candidateTokens: 120,
          totalTokens: 370,
        ),
        systemInstruction: 'You are the BaroGroove Sonic Advisor.',
        userPrompt: 'What fits a 1002 hPa storm front?',
        multimodalMetadata: <String, dynamic>{},
        rawModelResponse: 'Portishead - Dummy fits low-pressure storm fronts.',
        parsedPlan: <String, dynamic>{},
        toolSteps: <ToolStepModel>[
          ToolStepModel(
            stepId: 'step_1',
            toolName: 'fetch_barometric_affinity',
            label: 'fetch_barometric_affinity',
            detail: 'pressure_hpa=1002',
            latencyMs: 42.0,
            inputArgs: <String, dynamic>{'pressure_hpa': 1002},
            outputSummary: 'Returned 12 storm-front tracks',
          ),
        ],
        extractedMemoryIds: <String>[],
      ),
    ];

    final sampleConversations = <ConversationRecordModel>[
      const ConversationRecordModel(
        conversationId: 'conv_test_1',
        sessionId: 'sess_test_1',
        userId: 'demo',
        surface: 'advisor',
        title: 'Storm Front Inquiry',
        summary: 'Discussed Portishead and low-pressure storm fronts.',
        createdAt: '2026-09-12T13:10:00Z',
        updatedAt: '2026-09-12T13:15:00Z',
        turns: <ConversationTurnModel>[
          ConversationTurnModel(
            turnId: 'turn_1',
            turnIndex: 0,
            role: 'user',
            timestamp: '2026-09-12T13:14:55Z',
            content: 'What fits a 1002 hPa storm front?',
            actionsExecuted: <String>[],
            trajectoryId: 'traj_test_1',
          ),
          ConversationTurnModel(
            turnId: 'turn_2',
            turnIndex: 1,
            role: 'model',
            timestamp: '2026-09-12T13:15:00Z',
            content: 'Portishead - Dummy fits low-pressure storm fronts.',
            actionsExecuted: <String>['fetch_barometric_affinity'],
            trajectoryId: 'traj_test_1',
          ),
        ],
      ),
    ];

    final sampleSessions = <SessionRecordModel>[
      const SessionRecordModel(
        sessionId: 'sess_test_1',
        userId: 'demo',
        clientSurface: 'advisor',
        startedAt: '2026-09-12T13:00:00Z',
        lastActiveAt: '2026-09-12T13:15:00Z',
        turnCount: 4,
        conversationIds: <String>['conv_test_1'],
        trajectoryIds: <String>['traj_test_1'],
      ),
    ];

    final sampleMemories = <MemoryRecordModel>[
      const MemoryRecordModel(
        memoryId: 'mem_test_1',
        userId: 'demo',
        sourceType: 'conversation',
        category: 'preference',
        subject: 'weather:low-pressure',
        content: 'User prefers 1990s Bristol Trip-Hop during rainy low-pressure weather.',
        sentiment: 'positive',
        confidence: 0.92,
        tags: <String>['trip-hop', 'rain', 'low-pressure'],
        createdAt: '2026-09-12T12:30:00Z',
        lastReinforcedAt: '2026-09-12T12:30:00Z',
        reinforcementCount: 1,
        trajectoryId: 'traj_test_1',
      ),
    ];

    testWidgets('renders KPI banner, expands trajectory trace details, and navigates all 4 tabs', (WidgetTester tester) async {
      await tester.binding.setSurfaceSize(const Size(1400, 1000));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      await tester.pumpWidget(
        ProviderScope(
          child: MaterialApp(
            home: Scaffold(
              body: SizedBox(
                width: 1300,
                height: 900,
                child: TelemetryInspectorPanel(
                  initialSummary: sampleSummary,
                  initialTrajectories: sampleTrajectories,
                  initialConversations: sampleConversations,
                  initialSessions: sampleSessions,
                  initialMemories: sampleMemories,
                ),
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Verify KPI Banner values
      expect(find.text('28'), findsWidgets); // Total AI Calls
      expect(find.text('12400'), findsOneWidget); // Total Tokens
      expect(find.text('175.0 ms'), findsOneWidget); // Avg Latency

      // Verify Trajectory card is visible on Tab 1 and expanded by default
      expect(find.text('generate_sonic_advice'), findsOneWidget);
      expect(find.textContaining('traj_test_1'), findsWidgets);
      expect(find.textContaining('trace_w3c_000111222333'), findsWidgets);
      expect(find.textContaining('fetch_barometric_affinity'), findsWidgets);
      expect(find.textContaining('Portishead - Dummy fits low-pressure storm fronts.'), findsOneWidget);

      // Tap trajectory card to collapse, then tap again to expand
      await tester.tap(find.text('generate_sonic_advice'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('generate_sonic_advice'));
      await tester.pumpAndSettle();
      expect(find.textContaining('trace_w3c_000111222333'), findsWidgets);

      // Switch to Tab 2: Conversations
      await tester.tap(find.text('Conversations'));
      await tester.pumpAndSettle();
      expect(find.textContaining('conv_test_1'), findsWidgets);

      // Switch to Tab 3: Sessions
      await tester.tap(find.text('Sessions'));
      await tester.pumpAndSettle();
      expect(find.textContaining('sess_test_1'), findsWidgets);

      // Switch to Tab 4: Semantic Memories
      await tester.tap(find.text('Semantic Memories'));
      await tester.pumpAndSettle();
      expect(
        find.text('User prefers 1990s Bristol Trip-Hop during rainy low-pressure weather.'),
        findsOneWidget,
      );
      expect(find.text('#trip-hop'), findsOneWidget);
    });
  });

  group('A2UI TelemetryInspector Component (F13)', () {
    testWidgets('renders TelemetryInspector and TelemetryEntry from A2UI surface envelope', (WidgetTester tester) async {
      final catalog = buildBarogrooveCatalog();
      expect(catalog.contains('TelemetryInspector'), isTrue);
      expect(catalog.contains('TelemetryEntry'), isTrue);

      final controller = A2uiSurfaceController(
        surfaceId: 'telemetry_surface',
        catalog: catalog,
      )..applyAll(A2uiMessage.parseBatch(<Object?>[
          <String, Object?>{
            'createSurface': <String, Object?>{
              'surfaceId': 'telemetry_surface',
              'components': <Object?>[
                <String, Object?>{
                  'id': 'root',
                  'componentProperties': <String, Object?>{
                    'TelemetryInspector': <String, Object?>{
                      'title': 'Atmospheric AI Trace Log',
                      'totalCalls': 19,
                      'totalTokens': 8420,
                      'avgLatencyMs': 154,
                      'activeSessions': 2,
                      'storedMemories': 5,
                      'children': <Object?>['entry_1'],
                    },
                  },
                },
                <String, Object?>{
                  'id': 'entry_1',
                  'componentProperties': <String, Object?>{
                    'TelemetryEntry': <String, Object?>{
                      'surface': 'advisor',
                      'operation': 'sonic_weather_query',
                      'executionPath': 'vertex_gemini_2.5_flash',
                      'model': 'gemini-2.5-flash',
                      'latencyMs': 188,
                      'totalTokens': 410,
                      'traceId': 'a2ui_trace_999',
                      'status': 'ok',
                      'prompt': 'Analyze 1008 hPa wind shift',
                      'output': 'Recommended Air - Moon Safari.',
                    },
                  },
                },
              ],
            },
          },
        ]));

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: A2uiSurfaceView(controller: controller),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('Atmospheric AI Trace Log'), findsOneWidget);
      expect(find.text('19'), findsOneWidget);
      expect(find.text('sonic_weather_query'), findsOneWidget);
      expect(find.textContaining('a2ui_trace_999'), findsOneWidget);
    });
  });
}

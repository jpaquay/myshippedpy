/// Tests for the renderer's pure logic.
///
/// Scope is deliberate: envelope parsing, JSON-Pointer resolution, ChildList
/// template expansion, and graceful degradation. These are the parts where a
/// bug is silent — a widget that renders wrong is obvious in review, whereas a
/// pointer that resolves to the wrong subtree just quietly shows the wrong
/// number.
///
/// Run with `flutter test`.
library;

import 'package:barogroove/a2ui/actions.dart';
import 'package:barogroove/a2ui/catalog.dart';
import 'package:barogroove/a2ui/data_model.dart';
import 'package:barogroove/a2ui/messages.dart';
import 'package:barogroove/a2ui/renderer.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  // =========================================================================
  group('envelope parsing', () {
    test('parses the canonical single-key createSurface form', () {
      final A2uiMessage message = A2uiMessage.parse(<String, Object?>{
        'createSurface': <String, Object?>{
          'surfaceId': 'sky',
          'catalogUri': 'https://bg.netdev.be/api/surfaces/catalog',
          'surfaceProperties': <String, Object?>{'accent': '#0284C7'},
        },
      });

      expect(message, isA<CreateSurface>());
      final CreateSurface create = message as CreateSurface;
      expect(create.surfaceId, 'sky');
      expect(create.catalogUri, contains('/api/surfaces/catalog'));
      expect(create.surfaceProperties.accentHex, '#0284C7');
    });

    test('accepts surfaceProperties under the pre-1.0 name "theme"', () {
      // v1.0 renamed `theme` to `surfaceProperties`. We keep reading the old
      // key so a backend mid-migration does not lose its accent.
      final A2uiMessage message = A2uiMessage.parse(<String, Object?>{
        'createSurface': <String, Object?>{
          'surfaceId': 's',
          'theme': <String, Object?>{'accent': '#B45309'},
        },
      });
      expect(
        (message as CreateSurface).surfaceProperties.accentHex,
        '#B45309',
      );
    });

    test('parses all six agent -> renderer message types', () {
      final List<A2uiMessage> parsed = A2uiMessage.parseBatch(<Object?>[
        <String, Object?>{
          'createSurface': <String, Object?>{'surfaceId': 's'},
        },
        <String, Object?>{
          'updateComponents': <String, Object?>{
            'surfaceId': 's',
            'components': <Object?>[
              <String, Object?>{
                'id': 'root',
                'componentProperties': <String, Object?>{
                  'Text': <String, Object?>{'text': 'hi'},
                },
              },
            ],
          },
        },
        <String, Object?>{
          'updateDataModel': <String, Object?>{
            'surfaceId': 's',
            'path': '/a',
            'contents': 1,
          },
        },
        <String, Object?>{
          'callRendererFunction': <String, Object?>{
            'surfaceId': 's',
            'functionCallId': 'c1',
            'name': 'scrollToPeak',
          },
        },
        <String, Object?>{
          'agentFunctionResponse': <String, Object?>{
            'surfaceId': 's',
            'functionCallId': 'c1',
            'result': <String, Object?>{'ok': true},
          },
        },
        <String, Object?>{
          'deleteSurface': <String, Object?>{'surfaceId': 's'},
        },
      ]);

      expect(parsed[0], isA<CreateSurface>());
      expect(parsed[1], isA<UpdateComponents>());
      expect(parsed[2], isA<UpdateDataModel>());
      expect(parsed[3], isA<CallRendererFunction>());
      expect(parsed[4], isA<AgentFunctionResponse>());
      expect(parsed[5], isA<DeleteSurface>());
    });

    test('single-message instantiation carries components and data', () {
      // v1.0 allows an entire UI in one createSurface.
      final CreateSurface create = A2uiMessage.parse(<String, Object?>{
        'createSurface': <String, Object?>{
          'surfaceId': 's',
          'dataModel': <String, Object?>{'name': 'Petrichor'},
          'components': <Object?>[
            <String, Object?>{
              'id': 'root',
              'componentProperties': <String, Object?>{
                'Text': <String, Object?>{
                  'text': <String, Object?>{'path': '/name'},
                },
              },
            },
          ],
        },
      }) as CreateSurface;

      expect(create.components, hasLength(1));
      expect(create.components.single.id, 'root');
      expect(create.components.single.type, 'Text');
      expect(create.initialDataModel?['name'], 'Petrichor');
    });

    test('malformed input degrades to UnknownA2uiMessage, never throws', () {
      expect(A2uiMessage.parse(null), isA<UnknownA2uiMessage>());
      expect(A2uiMessage.parse('not an object'), isA<UnknownA2uiMessage>());
      expect(
        A2uiMessage.parse(<String, Object?>{'somethingElse': 1}),
        isA<UnknownA2uiMessage>(),
      );
      expect(A2uiMessage.parseJson('{{{ broken'), hasLength(1));
      expect(A2uiMessage.parseJson('{{{ broken').single,
          isA<UnknownA2uiMessage>());
    });

    test('a batch survives one bad element', () {
      final List<A2uiMessage> parsed = A2uiMessage.parseBatch(<Object?>[
        <String, Object?>{'deleteSurface': <String, Object?>{'surfaceId': 'a'}},
        'garbage',
        <String, Object?>{'deleteSurface': <String, Object?>{'surfaceId': 'b'}},
      ]);
      expect(parsed, hasLength(3));
      expect(parsed[0], isA<DeleteSurface>());
      expect(parsed[1], isA<UnknownA2uiMessage>());
      expect(parsed[2], isA<DeleteSurface>());
    });
  });

  // =========================================================================
  group('DynamicValue', () {
    test('recognises literal, path and functionCall forms', () {
      expect(
        DynamicValue.parse(<String, Object?>{'literalString': 'x'})!.kind,
        DynamicKind.literal,
      );
      expect(
        DynamicValue.parse(<String, Object?>{'path': '/a/b'})!.kind,
        DynamicKind.path,
      );
      expect(
        DynamicValue.parse(<String, Object?>{
          'functionCall': <String, Object?>{
            'name': 'concat',
            'args': <Object?>['a', 'b'],
          },
        })!.kind,
        DynamicKind.functionCall,
      );
    });

    test('accepts a bare scalar as a literal', () {
      final DynamicValue? v = DynamicValue.parse('Hello');
      expect(v!.kind, DynamicKind.literal);
      expect(v.literalValue, 'Hello');
    });

    test('reports its data-model dependencies', () {
      final DynamicValue v = DynamicValue.parse(<String, Object?>{
        'functionCall': <String, Object?>{
          'name': 'concat',
          'args': <Object?>[
            <String, Object?>{'path': '/sky/gust_variance'},
            ' and ',
            <String, Object?>{'path': '/sky/cloud_depth'},
          ],
        },
      })!;

      expect(
        v.dependencies.toList(),
        <String>['/sky/gust_variance', '/sky/cloud_depth'],
      );
    });
  });

  // =========================================================================
  group('JsonPointer', () {
    test('parses and round-trips', () {
      expect(JsonPointer.parse('').isRoot, isTrue);
      expect(JsonPointer.parse('/').isRoot, isTrue);
      expect(JsonPointer.parse('/a/b').segments, <String>['a', 'b']);
      expect(JsonPointer.parse('/a/b').canonical, '/a/b');
    });

    test('unescapes ~1 and ~0 in the right order', () {
      expect(JsonPointer.parse('/a~1b').segments.single, 'a/b');
      expect(JsonPointer.parse('/a~0b').segments.single, 'a~b');
      // ~01 must decode to ~1, not to /.
      expect(JsonPointer.parse('/a~01b').segments.single, 'a~1b');
    });

    test('tolerates a missing leading slash', () {
      expect(JsonPointer.parse('sky/gust').segments, <String>['sky', 'gust']);
    });

    test('containment and intersection', () {
      final JsonPointer sky = JsonPointer.parse('/sky');
      final JsonPointer gust = JsonPointer.parse('/sky/gust_variance');
      final JsonPointer tracks = JsonPointer.parse('/tracks');

      expect(sky.contains(gust), isTrue);
      expect(gust.contains(sky), isFalse);
      // Either direction counts as "might affect".
      expect(gust.intersects(sky), isTrue);
      expect(sky.intersects(tracks), isFalse);
      expect(JsonPointer.root.contains(tracks), isTrue);
    });
  });

  // =========================================================================
  group('SurfaceDataModel', () {
    late SurfaceDataModel model;

    setUp(() {
      model = SurfaceDataModel(<String, Object?>{
        'sky': <String, Object?>{
          'pressure_trend_6h': -0.62,
          'notes': <Object?>['barometer falling', 'gusting'],
        },
        'tracks': <Object?>[
          <String, Object?>{'title': 'One', 'role': 'opener'},
          <String, Object?>{'title': 'Two', 'role': 'peak'},
        ],
      });
    });

    test('resolves object, array and nested pointers', () {
      expect(model.resolveDouble('/sky/pressure_trend_6h'), -0.62);
      expect(model.resolveString('/tracks/1/title'), 'Two');
      expect(model.resolveString('/sky/notes/0'), 'barometer falling');
      expect(model.resolveList('/tracks'), hasLength(2));
    });

    test('the empty pointer resolves to the whole document', () {
      expect(model.resolve(''), isA<Map<String, Object?>>());
    });

    test('a miss reports which segment failed, and does not throw', () {
      final PointerLookup lookup = model.resolveEntry('/sky/humidity');
      expect(lookup.found, isFalse);
      expect(lookup.missingSegment, 'humidity');
      expect(model.resolve('/nope/nope/nope'), isNull);
      // Descending into a scalar is a miss, not a crash.
      expect(model.resolveEntry('/sky/pressure_trend_6h/x').found, isFalse);
      // An out-of-range index is a miss.
      expect(model.resolveEntry('/tracks/9').found, isFalse);
    });

    test('distinguishes absent from present-and-null', () {
      model.apply('/sky/observed_at', null);
      final PointerLookup present = model.resolveEntry('/sky/observed_at');
      expect(present.found, isTrue);
      expect(present.value, isNull);
      expect(model.resolveEntry('/sky/never_set').found, isFalse);
    });

    test('apply writes at a pointer and creates intermediates', () {
      model.apply('/forge/settings/width', 0.4);
      expect(model.resolveDouble('/forge/settings/width'), 0.4);

      // A numeric next-segment creates a list, not a map.
      model.apply('/queue/0/title', 'First');
      expect(model.resolveList('/queue'), hasLength(1));
      expect(model.resolveString('/queue/0/title'), 'First');
    });

    test('apply at the root replaces the document', () {
      model.apply('', <String, Object?>{'replaced': true});
      expect(model.resolveBool('/replaced'), isTrue);
      expect(model.resolve('/sky'), isNull);
    });

    test('revisionFor only moves for intersecting pointers', () {
      final int before = model.revisionFor('/sky');
      model.apply('/tracks/0/loved', true);

      // A write under /tracks must not invalidate anything bound to /sky.
      expect(model.revisionFor('/sky'), before);
      expect(model.revisionFor('/tracks'), greaterThan(before));

      model.apply('/sky/cloud_depth', 0.8);
      expect(model.revisionFor('/sky'), greaterThan(before));
      // And a write to a child invalidates a binding on the parent.
      expect(
        model.revisionFor('/sky/cloud_depth'),
        model.revisionFor('/sky'),
      );
    });

    test('notifies listeners on write', () {
      var notifications = 0;
      model.addListener(() => notifications++);
      model.apply('/sky/cloud_depth', 0.5);
      model.apply('/sky/cloud_depth', 0.6);
      expect(notifications, 2);
    });

    test('ScopedDataModel rebases relative pointers, absolute ones escape', () {
      final ScopedDataModel scope = model.scoped('/tracks/1');
      expect(scope.resolve('title'), 'Two');
      expect(scope.resolve('/sky/pressure_trend_6h'), -0.62);
      expect(scope.absolute('title'), '/tracks/1/title');
      expect(scope.absolute('/sky'), '/sky');
    });
  });

  // =========================================================================
  group('ChildList', () {
    test('parses the explicit form, including a bare array', () {
      final ChildList explicit = ChildList.parse(<String, Object?>{
        'explicitList': <Object?>['a', 'b'],
      });
      expect(explicit.isTemplate, isFalse);
      expect(explicit.ids, <String>['a', 'b']);

      expect(ChildList.parse(<Object?>['x', 'y']).ids, <String>['x', 'y']);
    });

    test('parses the template form', () {
      final ChildList template = ChildList.parse(<String, Object?>{
        'template': <String, Object?>{
          'componentId': 'trackRow',
          'dataBinding': '/tracks',
        },
      });
      expect(template.isTemplate, isTrue);
      expect(template.templateComponentId, 'trackRow');
      expect(template.templatePath, '/tracks');
    });

    test('an unparseable child list is empty, not an exception', () {
      expect(ChildList.parse(null).ids, isEmpty);
      expect(ChildList.parse(42).ids, isEmpty);
      expect(
        ChildList.parse(<String, Object?>{'template': <String, Object?>{}}).ids,
        isEmpty,
      );
    });
  });

  // =========================================================================
  group('surface controller', () {
    A2uiSurfaceController controller({A2uiActionDispatcher? dispatcher}) =>
        A2uiSurfaceController(
          surfaceId: 'test',
          catalog: buildBarogrooveCatalog(),
          dispatcher: dispatcher,
        );

    test('createSurface resets, updateComponents merges', () {
      final A2uiSurfaceController c = controller();

      c.applyAll(A2uiMessage.parseBatch(<Object?>[
        <String, Object?>{
          'createSurface': <String, Object?>{
            'surfaceId': 'test',
            'components': <Object?>[
              <String, Object?>{
                'id': 'root',
                'componentProperties': <String, Object?>{
                  'Text': <String, Object?>{'text': 'a'},
                },
              },
            ],
          },
        },
      ]));

      expect(c.isCreated, isTrue);
      expect(c.hasRoot, isTrue);

      c.apply(A2uiMessage.parse(<String, Object?>{
        'updateComponents': <String, Object?>{
          'surfaceId': 'test',
          'components': <Object?>[
            <String, Object?>{
              'id': 'extra',
              'componentProperties': <String, Object?>{
                'Text': <String, Object?>{'text': 'b'},
              },
            },
          ],
        },
      }));

      expect(c.componentIds, containsAll(<String>['root', 'extra']));

      // A second createSurface wipes the slate.
      c.apply(A2uiMessage.parse(<String, Object?>{
        'createSurface': <String, Object?>{'surfaceId': 'test'},
      }));
      expect(c.componentIds, isEmpty);
      expect(c.hasRoot, isFalse);
    });

    test('messages for another surface are ignored, not errors', () {
      final A2uiSurfaceController c = controller();
      c.apply(A2uiMessage.parse(<String, Object?>{
        'createSurface': <String, Object?>{'surfaceId': 'somewhere-else'},
      }));
      expect(c.isCreated, isFalse);
      expect(c.issues, isEmpty);
    });

    test('an unknown component type is recorded as an issue', () {
      final A2uiSurfaceController c = controller();
      c.applyAll(A2uiMessage.parseBatch(<Object?>[
        <String, Object?>{
          'createSurface': <String, Object?>{
            'surfaceId': 'test',
            'components': <Object?>[
              <String, Object?>{
                'id': 'root',
                'componentProperties': <String, Object?>{
                  'HolographicNeonBlob': <String, Object?>{},
                },
              },
            ],
          },
        },
      ]));

      expect(c.issues, isNotEmpty);
      expect(c.issues.first.summary, contains('HolographicNeonBlob'));
    });

    test('an unreadable message is recorded, not thrown', () {
      final A2uiSurfaceController c = controller();
      c.applyAll(A2uiMessage.parseBatch(<Object?>['nonsense']));
      expect(c.issues, hasLength(1));
      expect(c.issues.single.summary, 'Unreadable message');
    });

    test('client-side functions evaluate as documented', () {
      final A2uiSurfaceController c = controller();
      expect(c.callFunction('concat', <Object?>['a', 'b']), 'ab');
      expect(c.callFunction('percent', <Object?>[0.42]), '42%');
      expect(c.callFunction('signed', <Object?>[-0.6, 2]), '−0.60');
      expect(c.callFunction('signed', <Object?>[0.6, 2]), '+0.60');
      expect(c.callFunction('duration', <Object?>[215000]), '3:35');
      expect(c.callFunction('isEmpty', <Object?>[<Object?>[]]), isTrue);
      // An unknown function is null, not an exception.
      expect(c.callFunction('teleport', <Object?>[]), isNull);
    });

    test('an action is dispatched with its payload resolved in scope', () async {
      final RecordingActionDispatcher dispatcher = RecordingActionDispatcher();
      final A2uiSurfaceController c = controller(dispatcher: dispatcher);

      c.applyAll(A2uiMessage.parseBatch(<Object?>[
        <String, Object?>{
          'createSurface': <String, Object?>{
            'surfaceId': 'test',
            'dataModel': <String, Object?>{
              'themes': <Object?>[
                <String, Object?>{'id': 'petrichor'},
                <String, Object?>{'id': 'storm_front'},
              ],
            },
          },
        },
      ]));

      c.fireAction(
        const A2uiAction(
          actionId: 'selectTheme',
          payload: <String, DynamicValue>{
            'themeId': DynamicValue.path('/themes/1/id'),
          },
        ),
        c.dataModel.scoped(''),
        componentId: 'chips',
      );

      // Give the dispatch microtask a turn.
      await Future<void>.delayed(Duration.zero);

      expect(dispatcher.sent, hasLength(1));
      final ActionResponse sent = dispatcher.sent.single as ActionResponse;
      expect(sent.actionId, 'selectTheme');
      expect(sent.componentId, 'chips');
      expect(sent.payload['themeId'], 'storm_front');
    });

    test('a surface with no dispatcher records the dropped action', () async {
      final A2uiSurfaceController c = controller();
      c.fireAction(
        const A2uiAction(actionId: 'selectTheme'),
        c.dataModel.scoped(''),
      );
      expect(c.issues.single.summary, contains('selectTheme'));
    });

    test('ActionResponse serialises to the canonical envelope', () {
      final Map<String, Object?> json = const ActionResponse(
        surfaceId: 'sky',
        actionId: 'reforge',
        componentId: 'button1',
        payload: <String, Object?>{'genreId': 'ambient'},
      ).toJson();

      final Map<String, Object?>? body =
          json['actionResponse'] as Map<String, Object?>?;
      expect(body, isNotNull);
      expect(body!['surfaceId'], 'sky');
      expect(body['actionId'], 'reforge');
      expect(body['sourceComponentId'], 'button1');
      expect(body['payload'], <String, Object?>{'genreId': 'ambient'});
      expect(body['timestamp'], isA<String>());
    });

    test('CallAgentFunction and RendererFunctionResponse serialise', () {
      expect(
        const CallAgentFunction(
          surfaceId: 's',
          functionCallId: 'c1',
          name: 'reforge',
        ).toJson().keys.single,
        'callAgentFunction',
      );
      expect(
        const RendererFunctionResponse(
          surfaceId: 's',
          functionCallId: 'c1',
          result: 'done',
        ).toJson().keys.single,
        'rendererFunctionResponse',
      );
    });
  });

  // =========================================================================
  group('widget rendering', () {
    /// Pumps a controller inside a minimal MaterialApp.
    Future<A2uiSurfaceController> pump(
      WidgetTester tester,
      List<Object?> envelopes, {
      A2uiActionDispatcher? dispatcher,
    }) async {
      final A2uiSurfaceController controller = A2uiSurfaceController(
        surfaceId: 'test',
        catalog: buildBarogrooveCatalog(),
        dispatcher: dispatcher,
      )..applyAll(A2uiMessage.parseBatch(envelopes));

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: A2uiSurfaceView(controller: controller),
            ),
          ),
        ),
      );
      return controller;
    }

    testWidgets('renders the component with id "root"', (tester) async {
      await pump(tester, <Object?>[
        <String, Object?>{
          'createSurface': <String, Object?>{
            'surfaceId': 'test',
            'dataModel': <String, Object?>{'greeting': 'Barometer falling'},
            'components': <Object?>[
              <String, Object?>{
                'id': 'root',
                'componentProperties': <String, Object?>{
                  'Text': <String, Object?>{
                    'text': <String, Object?>{'path': '/greeting'},
                  },
                },
              },
            ],
          },
        },
      ]);

      expect(find.text('Barometer falling'), findsOneWidget);
    });

    testWidgets('a surface without a root says so instead of blanking',
        (tester) async {
      await pump(tester, <Object?>[
        <String, Object?>{
          'createSurface': <String, Object?>{
            'surfaceId': 'test',
            'components': <Object?>[
              <String, Object?>{
                'id': 'notRoot',
                'componentProperties': <String, Object?>{
                  'Text': <String, Object?>{'text': 'orphan'},
                },
              },
            ],
          },
        },
      ]);

      expect(find.textContaining('Surface has no root'), findsOneWidget);
    });

    testWidgets('an unknown component type degrades to a placeholder',
        (tester) async {
      await pump(tester, <Object?>[
        <String, Object?>{
          'createSurface': <String, Object?>{
            'surfaceId': 'test',
            'components': <Object?>[
              <String, Object?>{
                'id': 'root',
                'componentProperties': <String, Object?>{
                  'QuantumFluxCapacitor': <String, Object?>{'spin': 3},
                },
              },
            ],
          },
        },
      ]);

      // Visible, specific, and the app is still standing.
      expect(find.byType(A2uiPlaceholder), findsWidgets);
      expect(
        find.textContaining('Unsupported component "QuantumFluxCapacitor"'),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    });

    testWidgets('a reference to an undefined component is a placeholder',
        (tester) async {
      await pump(tester, <Object?>[
        <String, Object?>{
          'createSurface': <String, Object?>{
            'surfaceId': 'test',
            'components': <Object?>[
              <String, Object?>{
                'id': 'root',
                'componentProperties': <String, Object?>{
                  'Column': <String, Object?>{
                    'children': <Object?>['ghost'],
                  },
                },
              },
            ],
          },
        },
      ]);

      expect(find.textContaining('never defined it'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('ChildList template expands once per bound element',
        (tester) async {
      await pump(tester, <Object?>[
        <String, Object?>{
          'createSurface': <String, Object?>{
            'surfaceId': 'test',
            'dataModel': <String, Object?>{
              'themes': <Object?>[
                <String, Object?>{'name': 'Petrichor'},
                <String, Object?>{'name': 'Storm Front'},
                <String, Object?>{'name': 'First Frost'},
              ],
            },
            'components': <Object?>[
              <String, Object?>{
                'id': 'root',
                'componentProperties': <String, Object?>{
                  'Column': <String, Object?>{
                    'children': <String, Object?>{
                      'template': <String, Object?>{
                        'componentId': 'themeRow',
                        'dataBinding': '/themes',
                      },
                    },
                  },
                },
              },
              <String, Object?>{
                'id': 'themeRow',
                'componentProperties': <String, Object?>{
                  // Relative path: resolved against each element's scope.
                  'Text': <String, Object?>{
                    'text': <String, Object?>{'path': 'name'},
                  },
                },
              },
            ],
          },
        },
      ]);

      expect(find.text('Petrichor'), findsOneWidget);
      expect(find.text('Storm Front'), findsOneWidget);
      expect(find.text('First Frost'), findsOneWidget);
    });

    testWidgets('a template bound to a missing path shows a placeholder',
        (tester) async {
      await pump(tester, <Object?>[
        <String, Object?>{
          'createSurface': <String, Object?>{
            'surfaceId': 'test',
            'components': <Object?>[
              <String, Object?>{
                'id': 'root',
                'componentProperties': <String, Object?>{
                  'Column': <String, Object?>{
                    'children': <String, Object?>{
                      'template': <String, Object?>{
                        'componentId': 'row',
                        'dataBinding': '/nothing/here',
                      },
                    },
                  },
                },
              },
              <String, Object?>{
                'id': 'row',
                'componentProperties': <String, Object?>{
                  'Text': <String, Object?>{'text': 'x'},
                },
              },
            ],
          },
        },
      ]);

      expect(find.textContaining('is not in the data model'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('a component cycle is cut rather than blowing the stack',
        (tester) async {
      await pump(tester, <Object?>[
        <String, Object?>{
          'createSurface': <String, Object?>{
            'surfaceId': 'test',
            'components': <Object?>[
              <String, Object?>{
                'id': 'root',
                'componentProperties': <String, Object?>{
                  'Column': <String, Object?>{
                    'children': <Object?>['root'],
                  },
                },
              },
            ],
          },
        },
      ]);

      expect(find.textContaining('Component cycle'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('updateDataModel refreshes a bound value', (tester) async {
      final A2uiSurfaceController controller = await pump(tester, <Object?>[
        <String, Object?>{
          'createSurface': <String, Object?>{
            'surfaceId': 'test',
            'dataModel': <String, Object?>{'headline': 'Steady'},
            'components': <Object?>[
              <String, Object?>{
                'id': 'root',
                'componentProperties': <String, Object?>{
                  'Text': <String, Object?>{
                    'text': <String, Object?>{'path': '/headline'},
                  },
                },
              },
            ],
          },
        },
      ]);

      expect(find.text('Steady'), findsOneWidget);

      controller.apply(A2uiMessage.parse(<String, Object?>{
        'updateDataModel': <String, Object?>{
          'surfaceId': 'test',
          'path': '/headline',
          'contents': 'Falling sharply',
        },
      }));
      await tester.pump();

      expect(find.text('Steady'), findsNothing);
      expect(find.text('Falling sharply'), findsOneWidget);
    });

    testWidgets('the six BAROGROOVE components are all registered',
        (tester) async {
      final catalog = buildBarogrooveCatalog();
      for (final String type in const <String>[
        'SkyDial',
        'ThemeChips',
        'GenreCorridor',
        'TrackList',
        'RationaleCard',
        'AlmanacTimeline',
      ]) {
        expect(catalog.contains(type), isTrue, reason: '$type is missing');
      }
    });

    testWidgets('SkyDial renders and gives the derivative the hero slot',
        (tester) async {
      await tester.binding.setSurfaceSize(const Size(900, 1400));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      await pump(tester, <Object?>[
        <String, Object?>{
          'createSurface': <String, Object?>{
            'surfaceId': 'test',
            'dataModel': <String, Object?>{
              'sky': <String, Object?>{
                'pressure_trend_6h': -0.62,
                'pressure_norm_deviation': -0.2,
                'temp_norm_deviation': 0.1,
                'sun_elevation': 0.3,
                'golden_hour_proximity': 0.8,
                'gust_variance': 0.55,
                'cloud_depth': 0.7,
                'precip_intensity': 0.4,
                'daylight_delta': -0.05,
                'stale': false,
                'notes': <Object?>['barometer falling'],
              },
            },
            'components': <Object?>[
              <String, Object?>{
                'id': 'root',
                'componentProperties': <String, Object?>{
                  'SkyDial': <String, Object?>{
                    'vector': <String, Object?>{'path': '/sky'},
                  },
                },
              },
            ],
          },
        },
      ]);

      // The hero readout, in words and in figures.
      expect(find.text('PRESSURE TREND · 6 H'), findsOneWidget);
      expect(find.text('Falling sharply'), findsOneWidget);
      expect(find.text('−0.62'), findsWidgets);
      expect(tester.takeException(), isNull);
    });

    testWidgets('SkyDial with no bound vector degrades', (tester) async {
      await pump(tester, <Object?>[
        <String, Object?>{
          'createSurface': <String, Object?>{
            'surfaceId': 'test',
            'components': <Object?>[
              <String, Object?>{
                'id': 'root',
                'componentProperties': <String, Object?>{
                  'SkyDial': <String, Object?>{},
                },
              },
            ],
          },
        },
      ]);

      expect(find.textContaining('no SkyVector bound'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('RationaleCard shows degraded reasons rather than hiding them',
        (tester) async {
      await tester.binding.setSurfaceSize(const Size(900, 1600));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      await pump(tester, <Object?>[
        <String, Object?>{
          'createSurface': <String, Object?>{
            'surfaceId': 'test',
            'dataModel': <String, Object?>{
              'rationale': <String, Object?>{
                'headline': 'A falling barometer wants low ceilings.',
                'body': 'The pressure has dropped through the afternoon.',
                'sky_reading': <Object?>['Pressure down 0.62 over six hours'],
                'sonic_moves': <Object?>['Pulled valence down'],
                'taste_note': '',
                'confidence': 0.41,
                'degraded': <Object?>['Last.fm unavailable — no taste signal'],
              },
            },
            'components': <Object?>[
              <String, Object?>{
                'id': 'root',
                'componentProperties': <String, Object?>{
                  'RationaleCard': <String, Object?>{
                    'rationale': <String, Object?>{'path': '/rationale'},
                  },
                },
              },
            ],
          },
        },
      ]);

      expect(
        find.text('A falling barometer wants low ceilings.'),
        findsOneWidget,
      );
      expect(find.text('RUNNING DEGRADED'), findsOneWidget);
      expect(
        find.textContaining('Last.fm unavailable'),
        findsOneWidget,
      );
      // 0.41 reads as "Partial", not as a bare number.
      expect(find.text('Partial'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('a deleted surface renders nothing and does not throw',
        (tester) async {
      final A2uiSurfaceController controller = await pump(tester, <Object?>[
        <String, Object?>{
          'createSurface': <String, Object?>{
            'surfaceId': 'test',
            'components': <Object?>[
              <String, Object?>{
                'id': 'root',
                'componentProperties': <String, Object?>{
                  'Text': <String, Object?>{'text': 'here'},
                },
              },
            ],
          },
        },
      ]);

      expect(find.text('here'), findsOneWidget);

      controller.apply(A2uiMessage.parse(<String, Object?>{
        'deleteSurface': <String, Object?>{'surfaceId': 'test'},
      }));
      await tester.pump();

      expect(find.text('here'), findsNothing);
      expect(tester.takeException(), isNull);
    });
  });
}

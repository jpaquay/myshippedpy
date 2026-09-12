/// The renderer: consume A2UI messages, build a widget tree.
///
/// ## Architecture in one paragraph
///
/// [A2uiSurfaceController] owns the *state* of one surface — the component
/// map keyed by id, the [SurfaceDataModel], the surface properties and any
/// errors accumulated from bad messages. It implements [A2uiHost], so
/// component builders can reach back into it for children, actions and
/// client-side functions. [A2uiSurfaceView] is a dumb widget that listens to
/// the controller and builds the component whose id is `root`. Everything
/// else — every screen in this app that shows domain content — is a
/// consequence of what the server sent.
///
/// ## What it deliberately does not do
///
/// It does not know what a SkyDial means, what a theme chip should do when
/// tapped, or what order the sections go in. Those are all server decisions
/// arriving as JSON. The client contributes exactly two things: the pixels,
/// and the refusal to render a type it has not vetted.
///
/// ## Failure policy
///
/// Nothing in the render path throws. A malformed message is recorded and
/// shown as a placeholder banner. An unknown component type is a placeholder
/// inline. A binding that does not resolve is a placeholder inline. A cycle
/// in the component graph is cut and reported. The worst outcome available is
/// "part of the page says what is wrong with it".
library;

import 'dart:async';

import 'package:flutter/material.dart';

import '../app_theme.dart';
import 'actions.dart';
import 'catalog.dart';
import 'data_model.dart';
import 'messages.dart';

export 'catalog.dart' show buildBarogrooveCatalog;

/// A renderer-side function the agent may invoke via `callRendererFunction`.
typedef RendererFunction = FutureOr<Object?> Function(JsonMap parameters);

/// A non-fatal problem encountered while applying messages.
@immutable
final class SurfaceIssue {
  const SurfaceIssue(this.summary, {this.detail});

  final String summary;
  final String? detail;
}

// ===========================================================================
// Controller
// ===========================================================================

class A2uiSurfaceController extends ChangeNotifier implements A2uiHost {
  A2uiSurfaceController({
    required this.surfaceId,
    required A2uiCatalog catalog,
    A2uiActionDispatcher? dispatcher,
    Map<String, RendererFunction>? rendererFunctions,
  })  : _catalog = catalog,
        _dispatcher = dispatcher,
        _rendererFunctions = <String, RendererFunction>{
          ...?rendererFunctions,
        };

  @override
  final String surfaceId;

  final A2uiCatalog _catalog;
  final A2uiActionDispatcher? _dispatcher;
  final Map<String, RendererFunction> _rendererFunctions;
  final CallIdGenerator _callIds = CallIdGenerator();

  @override
  final SurfaceDataModel dataModel = SurfaceDataModel();

  final Map<String, A2uiComponent> _components = <String, A2uiComponent>{};
  final List<SurfaceIssue> _issues = <SurfaceIssue>[];

  /// Outstanding `callAgentFunction` ids awaiting an `agentFunctionResponse`.
  final Map<String, Completer<Object?>> _pendingAgentCalls =
      <String, Completer<Object?>>{};

  SurfaceProperties _surfaceProperties = SurfaceProperties.none;
  bool _created = false;
  bool _deleted = false;
  int _busyCount = 0;

  /// Ids currently on the build stack, for cycle detection.
  final Set<String> _building = <String>{};

  SurfaceProperties get surfaceProperties => _surfaceProperties;

  /// True once a `createSurface` has been seen. Before that the view shows a
  /// neutral empty state rather than "missing root", because "the stream has
  /// not started" is not an error.
  bool get isCreated => _created;

  bool get isDeleted => _deleted;

  List<SurfaceIssue> get issues => List<SurfaceIssue>.unmodifiable(_issues);

  Iterable<String> get componentIds => _components.keys;

  @override
  bool get busy => _busyCount > 0;

  bool get hasRoot => _components.containsKey('root');

  // --- Applying messages -------------------------------------------------

  /// Applies a batch in order. One bad message does not stop the rest.
  void applyAll(Iterable<A2uiMessage> messages) {
    var changed = false;
    for (final A2uiMessage m in messages) {
      changed = _applyOne(m) || changed;
    }
    if (changed) notifyListeners();
  }

  void apply(A2uiMessage message) {
    if (_applyOne(message)) notifyListeners();
  }

  /// Convenience for a raw JSON body straight off the wire.
  void applyJson(String body) => applyAll(A2uiMessage.parseJson(body));

  /// Returns true if the message changed anything worth a rebuild.
  bool _applyOne(A2uiMessage message) {
    // A message addressed to a different surface is not an error; multi-
    // surface streams are legal. Ignore it quietly.
    if (message.surfaceId.isNotEmpty && message.surfaceId != surfaceId) {
      return false;
    }

    switch (message) {
      case final CreateSurface create:
        // createSurface resets the surface. v1.0 allows the entire UI in one
        // message, so components and the initial data model may ride along.
        _components.clear();
        _issues.clear();
        _deleted = false;
        _created = true;
        _surfaceProperties = create.surfaceProperties;
        final JsonMap? initial = create.initialDataModel;
        if (initial != null) {
          dataModel.replaceAll(initial);
        }
        _ingest(create.components);
        return true;

      case UpdateComponents(:final List<A2uiComponent> components):
        // Components may legitimately arrive before createSurface if the
        // server batches oddly; accept them rather than dropping the UI.
        _created = true;
        _ingest(components);
        return true;

      case UpdateDataModel(:final String path, :final Object? contents):
        dataModel.apply(path, contents);
        // The data model is its own ChangeNotifier, but the view listens to
        // the controller, so republish.
        return true;

      case DeleteSurface():
        _components.clear();
        _deleted = true;
        return true;

      case CallRendererFunction(
          :final String name,
          :final String functionCallId,
          :final JsonMap parameters,
        ):
        unawaited(_runRendererFunction(name, functionCallId, parameters));
        return false;

      case AgentFunctionResponse(
          :final String functionCallId,
          :final Object? result,
          :final String? error,
        ):
        final Completer<Object?>? pending =
            _pendingAgentCalls.remove(functionCallId);
        if (pending != null && !pending.isCompleted) {
          if (error != null) {
            pending.completeError(StateError(error));
          } else {
            pending.complete(result);
          }
        }
        if (error != null) {
          _issues.add(SurfaceIssue('Agent function failed', detail: error));
          return true;
        }
        return false;

      case UnknownA2uiMessage(:final String reason):
        _issues.add(SurfaceIssue('Unreadable message', detail: reason));
        return true;
    }
  }

  void _ingest(List<A2uiComponent> components) {
    for (final A2uiComponent c in components) {
      if (c.type.isEmpty) {
        _issues.add(
          SurfaceIssue(
            'Component "${c.id}" has no type',
            detail: 'It will render as a placeholder.',
          ),
        );
      } else if (!_catalog.contains(c.type)) {
        // Recorded once at ingest so the banner tells you about a catalog
        // mismatch even if the component is off-screen.
        _issues.add(
          SurfaceIssue(
            'Unknown component type "${c.type}"',
            detail: 'Referenced by "${c.id}". Client catalog is behind the '
                'server catalog.',
          ),
        );
      }
      _components[c.id] = c;
    }
  }

  // --- Host implementation -----------------------------------------------

  @override
  Widget buildById(String id, ScopedDataModel scope, BuildContext context) {
    final A2uiComponent? component = _components[id];
    if (component == null) {
      return A2uiPlaceholder(
        title: 'Missing component',
        detail: 'The stream referenced "$id" but never defined it.',
      );
    }

    // Cycle guard. A self-referential graph is a server bug, and blowing the
    // stack is a poor way to report it.
    if (_building.contains(id)) {
      return A2uiPlaceholder(
        title: 'Component cycle',
        detail: '"$id" is its own ancestor; the branch was cut here.',
      );
    }

    final A2uiComponentBuilder? builder = _catalog.builderFor(component.type);
    if (builder == null) {
      return A2uiPlaceholder.unknownType(
        componentId: id,
        type: component.type,
        known: _catalog.types,
      );
    }

    _building.add(id);
    try {
      return builder(
        A2uiNode(
          component: component,
          scope: scope,
          host: this,
          context: context,
        ),
      );
    } catch (e, stack) {
      // A component builder throwing is our bug, not the server's, but the
      // user should still get a working page.
      assert(() {
        debugPrint('A2UI: builder for "${component.type}" threw: $e\n$stack');
        return true;
      }());
      return A2uiPlaceholder(
        title: 'Could not render "${component.type}"',
        detail: '$e',
        severity: A2uiPlaceholderSeverity.error,
      );
    } finally {
      _building.remove(id);
    }
  }

  @override
  void fireAction(
    A2uiAction action,
    ScopedDataModel scope, {
    String? componentId,
  }) {
    final A2uiActionDispatcher? dispatcher = _dispatcher;
    if (dispatcher == null) {
      _issues.add(
        SurfaceIssue(
          'Action "${action.actionId}" went nowhere',
          detail: 'This surface has no dispatcher (offline or demo mode).',
        ),
      );
      notifyListeners();
      return;
    }

    // Resolve the payload now, in the firing node's scope, so a template row
    // sends its own element's values.
    final JsonMap payload = <String, Object?>{};
    for (final MapEntry<String, DynamicValue> e in action.payload.entries) {
      final DynamicValue d = e.value;
      payload[e.key] = switch (d.kind) {
        DynamicKind.literal => d.literalValue,
        DynamicKind.path => scope.resolve(d.pointer!),
        DynamicKind.functionCall => callFunction(
            d.call!.name,
            <Object?>[
              for (final DynamicValue a in d.call!.args)
                a.kind == DynamicKind.path
                    ? scope.resolve(a.pointer!)
                    : a.literalValue,
            ],
          ),
      };
    }

    unawaited(
      _withBusy(() async {
        final ActionOutcome outcome = await dispatcher.send(
          ActionResponse(
            surfaceId: surfaceId,
            actionId: action.actionId,
            componentId: componentId,
            payload: payload,
          ),
        );
        if (!outcome.ok) {
          _issues.add(
            SurfaceIssue('Action failed', detail: outcome.error),
          );
          notifyListeners();
          return;
        }
        applyAll(outcome.messages);
      }),
    );
  }

  /// Sends a `callAgentFunction` and completes when the matching
  /// `agentFunctionResponse` arrives (or the follow-up batch carries it).
  Future<Object?> callAgentFunction(
    String name, {
    JsonMap parameters = const <String, Object?>{},
    Duration timeout = const Duration(seconds: 20),
  }) async {
    final A2uiActionDispatcher? dispatcher = _dispatcher;
    if (dispatcher == null) return null;

    final String callId = _callIds.next('rf');
    final Completer<Object?> completer = Completer<Object?>();
    _pendingAgentCalls[callId] = completer;

    await _withBusy(() async {
      final ActionOutcome outcome = await dispatcher.send(
        CallAgentFunction(
          surfaceId: surfaceId,
          functionCallId: callId,
          name: name,
          parameters: parameters,
        ),
      );
      if (!outcome.ok) {
        _pendingAgentCalls.remove(callId);
        if (!completer.isCompleted) {
          completer.completeError(StateError(outcome.error!));
        }
        _issues.add(SurfaceIssue('Agent call failed', detail: outcome.error));
        notifyListeners();
        return;
      }
      applyAll(outcome.messages);
    });

    if (completer.isCompleted) return completer.future;
    return completer.future.timeout(
      timeout,
      onTimeout: () {
        _pendingAgentCalls.remove(callId);
        return null;
      },
    );
  }

  /// Client-side functions available to `FunctionCall` bindings.
  ///
  /// Kept small on purpose. These are formatting and arithmetic helpers, not
  /// business logic — the moment a function here decides something about
  /// music or weather, the UI is being defined in two places again.
  @override
  Object? callFunction(String name, List<Object?> args) {
    Object? arg(int i) => i < args.length ? args[i] : null;
    double num0(int i) => asDoubleOrNull(arg(i)) ?? 0;
    String str0(int i) => arg(i) == null ? '' : '${arg(i)}';

    switch (name) {
      case 'concat':
        return args.map((Object? a) => a == null ? '' : '$a').join();
      case 'join':
        final List<Object?> items = asJsonList(arg(0)) ?? const <Object?>[];
        return items.map((Object? a) => '$a').join(str0(1).isEmpty ? ', ' : str0(1));
      case 'upper':
        return str0(0).toUpperCase();
      case 'lower':
        return str0(0).toLowerCase();
      case 'not':
        return !(asBoolOrNull(arg(0)) ?? false);
      case 'and':
        return args.every((Object? a) => asBoolOrNull(a) ?? a != null);
      case 'or':
        return args.any((Object? a) => asBoolOrNull(a) ?? false);
      case 'isEmpty':
        final Object? v = arg(0);
        if (v == null) return true;
        if (v is String) return v.isEmpty;
        if (v is List) return v.isEmpty;
        if (v is Map) return v.isEmpty;
        return false;
      case 'length':
        final Object? v = arg(0);
        if (v is String) return v.length;
        if (v is List) return v.length;
        if (v is Map) return v.length;
        return 0;
      case 'percent':
        return '${(num0(0) * 100).round()}%';
      case 'signed':
        // Signed dimensions read better with an explicit sign; -0.0 is not
        // a thing anyone wants to see.
        final double v = num0(0);
        final int digits = (asDoubleOrNull(arg(1)) ?? 2).round();
        if (v == 0) return (0).toStringAsFixed(digits);
        return '${v > 0 ? '+' : '−'}${v.abs().toStringAsFixed(digits)}';
      case 'fixed':
        return num0(0).toStringAsFixed((asDoubleOrNull(arg(1)) ?? 1).round());
      case 'duration':
        // Milliseconds -> m:ss.
        final int ms = num0(0).round();
        final int totalSeconds = ms ~/ 1000;
        final int m = totalSeconds ~/ 60;
        final int s = totalSeconds % 60;
        return '$m:${s.toString().padLeft(2, '0')}';
      case 'ifElse':
        return (asBoolOrNull(arg(0)) ?? false) ? arg(1) : arg(2);
      default:
        // Unknown functions return null rather than throwing; the binding
        // then renders as missing, which is visible and survivable.
        assert(() {
          debugPrint('A2UI: unknown client function "$name"');
          return true;
        }());
        return null;
    }
  }

  /// Registers a function the agent may invoke on us.
  void registerRendererFunction(String name, RendererFunction fn) {
    _rendererFunctions[name] = fn;
  }

  Future<void> _runRendererFunction(
    String name,
    String callId,
    JsonMap parameters,
  ) async {
    final RendererFunction? fn = _rendererFunctions[name];
    final A2uiActionDispatcher? dispatcher = _dispatcher;

    if (fn == null) {
      _issues.add(
        SurfaceIssue(
          'Agent asked for renderer function "$name"',
          detail: 'This client does not implement it.',
        ),
      );
      notifyListeners();
      await dispatcher?.send(
        RendererFunctionResponse(
          surfaceId: surfaceId,
          functionCallId: callId,
          error: 'unimplemented renderer function "$name"',
        ),
      );
      return;
    }

    try {
      final Object? result = await fn(parameters);
      final ActionOutcome? outcome = await dispatcher?.send(
        RendererFunctionResponse(
          surfaceId: surfaceId,
          functionCallId: callId,
          result: result,
        ),
      );
      if (outcome != null && outcome.ok) applyAll(outcome.messages);
    } catch (e) {
      await dispatcher?.send(
        RendererFunctionResponse(
          surfaceId: surfaceId,
          functionCallId: callId,
          error: '$e',
        ),
      );
    }
  }

  Future<void> _withBusy(Future<void> Function() body) async {
    _busyCount++;
    notifyListeners();
    try {
      await body();
    } finally {
      _busyCount--;
      notifyListeners();
    }
  }

  /// Clears accumulated issues — used by the "dismiss" affordance on the
  /// diagnostics banner.
  void clearIssues() {
    if (_issues.isEmpty) return;
    _issues.clear();
    notifyListeners();
  }

  /// Wipes everything. Used when a screen re-fetches its surface.
  void reset() {
    _components.clear();
    _issues.clear();
    _pendingAgentCalls.clear();
    _created = false;
    _deleted = false;
    _surfaceProperties = SurfaceProperties.none;
    dataModel.replaceAll(<String, Object?>{});
    notifyListeners();
  }
}

// ===========================================================================
// View
// ===========================================================================

/// Renders a surface.
///
/// Per A2UI v1.0, `createSurface` implicitly instantiates a Surface container
/// whose child is the component with id `root`. That is the entire contract
/// this widget implements: find `root`, build it, and wrap the result in the
/// surface's properties.
class A2uiSurfaceView extends StatelessWidget {
  const A2uiSurfaceView({
    required this.controller,
    this.padding = const EdgeInsets.all(BgSpace.lg),
    this.showDiagnostics = true,
    this.emptyState,
    super.key,
  });

  final A2uiSurfaceController controller;
  final EdgeInsets padding;

  /// Whether to show the issue banner. On in dev and staging; you may want it
  /// off in a kiosk build, but note that hiding it does not fix anything.
  final bool showDiagnostics;

  /// Shown before the first `createSurface` arrives.
  final Widget? emptyState;

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: controller,
      builder: (BuildContext context, Widget? _) {
        if (controller.isDeleted) {
          return const SizedBox.shrink();
        }

        if (!controller.isCreated) {
          return emptyState ?? const SizedBox.shrink();
        }

        final ThemeData theme = _themedFor(context);
        final Widget body = controller.hasRoot
            ? controller.buildById(
                'root',
                controller.dataModel.scoped(''),
                context,
              )
            : A2uiPlaceholder(
                title: 'Surface has no root',
                detail: 'A2UI requires exactly one component with id "root". '
                    'The stream defined: '
                    '${controller.componentIds.isEmpty ? '(nothing)' : controller.componentIds.join(', ')}.',
                severity: A2uiPlaceholderSeverity.error,
              );

        return Theme(
          data: theme,
          child: Padding(
            padding: padding,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                if (showDiagnostics && controller.issues.isNotEmpty)
                  _IssueBanner(controller: controller),
                body,
              ],
            ),
          ),
        );
      },
    );
  }

  /// Applies `surfaceProperties` as a tint on the ambient theme.
  ///
  /// The surface may move the accent. It may not repaint the app. Theme
  /// palettes coming back from `/api/themes` are expressive — storm_front is
  /// not petrichor — but BAROGROOVE stays an instrument, so the tint is
  /// applied to interaction colour only.
  ThemeData _themedFor(BuildContext context) {
    final ThemeData base = Theme.of(context);
    final String? accentHex = controller.surfaceProperties.accentHex;
    if (accentHex == null) return base;
    return BgTheme.tinted(
      base,
      BgTheme.parseHex(accentHex, fallback: base.colorScheme.primary),
    );
  }
}

/// Honest, dismissible diagnostics. Errors from the agent are not hidden.
class _IssueBanner extends StatelessWidget {
  const _IssueBanner({required this.controller});

  final A2uiSurfaceController controller;

  @override
  Widget build(BuildContext context) {
    final List<SurfaceIssue> issues = controller.issues;
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Container(
      margin: const EdgeInsets.only(bottom: BgSpace.lg),
      padding: const EdgeInsets.all(BgSpace.md),
      decoration: BoxDecoration(
        color: colors.surfaceContainerLow,
        borderRadius: BgSpace.brSm,
        border: Border.all(color: BgPalette.warn.withValues(alpha: 0.45)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const Icon(Icons.report_gmailerrorred_outlined,
              size: 18, color: BgPalette.warn),
          const SizedBox(width: BgSpace.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(
                  issues.length == 1
                      ? '1 rendering issue'
                      : '${issues.length} rendering issues',
                  style: text.titleSmall?.copyWith(color: BgPalette.warn),
                ),
                const SizedBox(height: BgSpace.xs),
                for (final SurfaceIssue i in issues.take(4))
                  Padding(
                    padding: const EdgeInsets.only(bottom: 2),
                    child: Text(
                      i.detail == null
                          ? i.summary
                          : '${i.summary} — ${i.detail}',
                      style: text.bodySmall,
                    ),
                  ),
                if (issues.length > 4)
                  Text('…and ${issues.length - 4} more.',
                      style: text.bodySmall),
              ],
            ),
          ),
          IconButton(
            tooltip: 'Dismiss',
            visualDensity: VisualDensity.compact,
            icon: const Icon(Icons.close, size: 16),
            onPressed: controller.clearIssues,
          ),
        ],
      ),
    );
  }
}

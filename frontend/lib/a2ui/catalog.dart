/// The catalog: type name -> Flutter widget builder.
///
/// ## The rule this file exists to enforce
///
/// BAROGROOVE's component catalog is DECLARED once, in Python, and served
/// from `GET /api/surfaces/catalog`. What lives here is not a second
/// declaration — it is the *binding*: for each type name the server may use,
/// which Flutter widget draws it. The schema, the property names, the
/// defaults and the semantics all come from the server. If you find yourself
/// inventing a property here that the server does not send, you are building
/// the UI twice. Stop.
///
/// The registry is also the security boundary A2UI is built around: the agent
/// can only name types that are in this map. An unknown type does not
/// execute anything; it renders a placeholder.
library;

import 'package:flutter/material.dart';

import '../app_theme.dart';
import 'actions.dart';
import 'components/almanac_timeline.dart';
import 'components/genre_corridor.dart';
import 'components/rationale_card.dart';
import 'components/sky_dial.dart';
import 'components/telemetry_inspector.dart';
import 'components/theme_chips.dart';
import 'components/track_list.dart';
import 'data_model.dart';
import 'messages.dart';

// ===========================================================================
// Host — what a component may ask of the surface it lives in
// ===========================================================================

/// The surface controller, as seen by a component builder.
///
/// Declared as an interface here (rather than importing the controller) so
/// that `components/` depends only on `catalog.dart` and the dependency graph
/// stays acyclic.
abstract interface class A2uiHost {
  String get surfaceId;

  SurfaceDataModel get dataModel;

  /// Builds a component by id, in the given scope. Used for children.
  /// Returns a placeholder if the id is unknown.
  Widget buildById(String id, ScopedDataModel scope, BuildContext context);

  /// Fires a declarative action back at the agent.
  void fireAction(
    A2uiAction action,
    ScopedDataModel scope, {
    String? componentId,
  });

  /// True while an action round trip is in flight. Components use it to
  /// disable affordances rather than letting the user double-fire.
  bool get busy;

  /// Client-side functions available to `FunctionCall` bindings.
  Object? callFunction(String name, List<Object?> args);
}

// ===========================================================================
// Node — the argument every component builder receives
// ===========================================================================

/// One component instance, bound to a data scope, ready to build.
///
/// All property access goes through here so that binding resolution,
/// null-handling and template scoping happen in exactly one place.
final class A2uiNode {
  const A2uiNode({
    required this.component,
    required this.scope,
    required this.host,
    required this.context,
  });

  final A2uiComponent component;
  final ScopedDataModel scope;
  final A2uiHost host;
  final BuildContext context;

  String get id => component.id;

  ThemeData get theme => Theme.of(context);
  ColorScheme get colors => Theme.of(context).colorScheme;
  TextTheme get text => Theme.of(context).textTheme;

  // --- Binding resolution ------------------------------------------------

  /// Resolves a [DynamicValue] to a concrete value.
  ///
  /// Literals pass through. Paths are read from the scoped data model.
  /// Function calls are evaluated against the host's function registry, with
  /// their own arguments resolved first.
  Object? resolveDynamic(DynamicValue? d) {
    if (d == null) return null;
    switch (d.kind) {
      case DynamicKind.literal:
        return d.literalValue;
      case DynamicKind.path:
        return scope.resolve(d.pointer!);
      case DynamicKind.functionCall:
        final FunctionCall call = d.call!;
        final List<Object?> args = <Object?>[
          for (final DynamicValue a in call.args) resolveDynamic(a),
        ];
        return host.callFunction(call.name, args);
    }
  }

  /// Resolves a named property.
  Object? value(String key) => resolveDynamic(component.dyn(key));

  String? string(String key) {
    final Object? v = value(key);
    if (v == null) return null;
    return v is String ? v : '$v';
  }

  /// Non-null string with a fallback, for properties that must render
  /// something. Empty strings count as absent.
  String stringOr(String key, String fallback) {
    final String? s = string(key);
    return (s == null || s.isEmpty) ? fallback : s;
  }

  double? number(String key) => asDoubleOrNull(value(key));

  double numberOr(String key, double fallback) => number(key) ?? fallback;

  bool boolean(String key, {bool fallback = false}) =>
      asBoolOrNull(value(key)) ?? fallback;

  List<Object?> list(String key) => asJsonList(value(key)) ?? const <Object?>[];

  JsonMap? map(String key) => asJsonMap(value(key));

  List<String> strings(String key) => asStringList(value(key));

  /// The pointer a property is bound to, if it is a path binding. Components
  /// that iterate a bound list (TrackList, AlmanacTimeline) need the pointer
  /// itself, not just the value, so they can scope their rows.
  String? boundPath(String key) {
    final DynamicValue? d = component.dyn(key);
    return d?.kind == DynamicKind.path ? d!.pointer : null;
  }

  /// Every data-model pointer this component reads. The renderer uses this to
  /// skip rebuilds for unrelated `updateDataModel` messages.
  Iterable<String> get dependencies sync* {
    for (final Object? raw in component.properties.values) {
      final DynamicValue? d = DynamicValue.parse(raw);
      if (d != null) yield* d.dependencies;
    }
    final ChildList children = component.children();
    if (children.isTemplate) yield children.templatePath!;
  }

  // --- Children ----------------------------------------------------------

  /// Builds the children named by [key], handling both ChildList forms.
  ///
  /// Explicit: each id is built once in the current scope.
  /// Template: the bound array is read, and the prototype component is built
  /// once per element with the scope rebased onto `<path>/<index>`. That
  /// rebasing is what lets the prototype say `title` and get the right row's
  /// title without the agent emitting one component per row.
  List<Widget> childrenOf([String key = 'children']) {
    final ChildList spec = component.children(key);

    if (!spec.isTemplate) {
      return <Widget>[
        for (final String childId in spec.ids)
          host.buildById(childId, scope, context),
      ];
    }

    final String path = spec.templatePath!;
    final String prototypeId = spec.templateComponentId!;
    final PointerLookup lookup = scope.resolveEntry(path);

    if (!lookup.found) {
      return <Widget>[
        A2uiPlaceholder.binding(
          componentId: component.id,
          detail: 'template list "$path" is not in the data model'
              '${lookup.missingSegment == null ? '' : ' '
                  '(missing "${lookup.missingSegment}")'}',
        ),
      ];
    }

    final List<Object?>? items = asJsonList(lookup.value);
    if (items == null) {
      return <Widget>[
        A2uiPlaceholder.binding(
          componentId: component.id,
          detail: 'template list "$path" is not an array',
        ),
      ];
    }
    if (items.isEmpty) return const <Widget>[];

    final String absoluteBase = scope.absolute(path);
    final ScopedDataModel listScope =
        ScopedDataModel(scope.model, JsonPointer.parse(absoluteBase));

    return <Widget>[
      for (var i = 0; i < items.length; i++)
        KeyedSubtree(
          key: ValueKey<String>('$prototypeId#$i'),
          child: host.buildById(prototypeId, listScope.index(i), context),
        ),
    ];
  }

  /// Builds a single child named by [key], e.g. `"child": "header"`.
  Widget? childOf(String key) {
    final String? childId = component.constString(key);
    if (childId == null) return null;
    return host.buildById(childId, scope, context);
  }

  // --- Actions -----------------------------------------------------------

  /// The action attached to this component under [key], if any.
  A2uiAction? action([String key = 'action']) =>
      A2uiAction.parse(component.properties[key]);

  /// A tap handler for [key], or `null` if the component declares no action
  /// (which correctly renders the affordance as disabled).
  VoidCallback? onTap([String key = 'action']) {
    final A2uiAction? a = action(key);
    if (a == null) return null;
    if (host.busy) return null;
    return () => host.fireAction(a, scope, componentId: component.id);
  }

  /// Fires an action with extra payload resolved at the call site — used by
  /// components whose payload depends on gesture detail (a slider value, the
  /// index of the tapped row).
  void fire(A2uiAction action, {JsonMap extra = const <String, Object?>{}}) {
    host.fireAction(
      extra.isEmpty
          ? action
          : A2uiAction(
              actionId: action.actionId,
              payload: <String, DynamicValue>{
                ...action.payload,
                for (final MapEntry<String, Object?> e in extra.entries)
                  e.key: DynamicValue.literal(e.value),
              },
              confirm: action.confirm,
            ),
      scope,
      componentId: component.id,
    );
  }
}

// ===========================================================================
// Registry
// ===========================================================================

typedef A2uiComponentBuilder = Widget Function(A2uiNode node);

/// Immutable map of type name -> builder.
final class A2uiCatalog {
  const A2uiCatalog(this._builders);

  final Map<String, A2uiComponentBuilder> _builders;

  bool contains(String type) => _builders.containsKey(type);

  Iterable<String> get types => _builders.keys;

  A2uiComponentBuilder? builderFor(String type) => _builders[type];

  /// Returns a new catalog with [others] layered on top. Later wins, so a
  /// BAROGROOVE component may override a primitive of the same name.
  A2uiCatalog merge(Map<String, A2uiComponentBuilder> others) =>
      A2uiCatalog(<String, A2uiComponentBuilder>{..._builders, ...others});
}

// ===========================================================================
// Placeholder — the graceful-degradation surface
// ===========================================================================

/// What we render when something is wrong.
///
/// Visible, bounded, non-fatal and *specific*. A silent blank teaches nobody
/// anything; a red screen of death loses the rest of the page. This is a
/// small bordered note that names the problem and lets the surrounding UI
/// carry on.
class A2uiPlaceholder extends StatelessWidget {
  const A2uiPlaceholder({
    required this.title,
    required this.detail,
    this.severity = A2uiPlaceholderSeverity.warning,
    super.key,
  });

  /// An unrecognised component type.
  factory A2uiPlaceholder.unknownType({
    required String componentId,
    required String type,
    required Iterable<String> known,
  }) {
    final String label = type.isEmpty ? '(no type)' : type;
    return A2uiPlaceholder(
      title: 'Unsupported component "$label"',
      detail: 'Component "$componentId" asked for a type this build does not '
          'know. The server catalog and this client are out of step. '
          'Known types: ${(known.toList()..sort()).join(', ')}.',
    );
  }

  /// A binding that did not resolve.
  factory A2uiPlaceholder.binding({
    required String componentId,
    required String detail,
  }) =>
      A2uiPlaceholder(
        title: 'Missing data',
        detail: '"$componentId": $detail',
      );

  /// A message we could not parse at all.
  factory A2uiPlaceholder.message({required String reason}) =>
      A2uiPlaceholder(
        title: 'Malformed A2UI message',
        detail: reason,
        severity: A2uiPlaceholderSeverity.error,
      );

  final String title;
  final String detail;
  final A2uiPlaceholderSeverity severity;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;
    final Color tone = switch (severity) {
      A2uiPlaceholderSeverity.error => colors.error,
      A2uiPlaceholderSeverity.warning => BgPalette.warn,
    };

    // The accent bar is a clipped child, not a BorderSide.
    //
    // A BoxDecoration cannot combine a borderRadius with a Border whose sides
    // differ in colour -- Flutter throws "a borderRadius can only be given on
    // borders with uniform colors" at paint time. This widget is the
    // placeholder every degradation path renders, so that exception turned any
    // single unknown component into a crashed surface: the failure handler was
    // the thing that failed.
    //
    // Uniform outline on the decoration, coloured edge drawn inside a
    // ClipRRect, so the rounded corners and the accent both survive.
    return Semantics(
      liveRegion: true,
      child: Container(
        width: double.infinity,
        margin: const EdgeInsets.symmetric(vertical: BgSpace.sm),
        decoration: BoxDecoration(
          color: colors.surfaceContainerLow,
          borderRadius: BgSpace.brSm,
          border: Border.all(color: colors.outlineVariant),
        ),
        child: ClipRRect(
          borderRadius: BgSpace.brSm,
          child: IntrinsicHeight(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: <Widget>[
                SizedBox(width: 3, child: ColoredBox(color: tone)),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.all(BgSpace.md),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisSize: MainAxisSize.min,
                      children: <Widget>[
                        Text(
                          title,
                          style: text.titleSmall?.copyWith(color: tone),
                        ),
                        const SizedBox(height: BgSpace.xs),
                        Text(detail, style: text.bodySmall),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

enum A2uiPlaceholderSeverity { warning, error }

// ===========================================================================
// Primitives
// ===========================================================================

/// The layout and text primitives from the A2UI basic catalog.
///
/// BAROGROOVE's Python catalog composes its six domain components inside
/// these, so the client has to know them. They are deliberately plain: all
/// the visual identity lives in [BgTheme], not in per-component styling.
Map<String, A2uiComponentBuilder> basicComponents() =>
    <String, A2uiComponentBuilder>{
      'Text': (A2uiNode n) {
        final String content = n.stringOr('text', '');
        final String variant = n.component.constString('variant') ??
            n.component.constString('style') ??
            'body';
        final TextTheme t = n.text;
        final TextStyle? style = switch (variant) {
          'h1' || 'display' => t.displaySmall,
          'h2' => t.headlineMedium,
          'h3' => t.headlineSmall,
          'h4' || 'title' => t.titleLarge,
          'h5' => t.titleMedium,
          'h6' || 'subtitle' => t.titleSmall,
          'caption' => t.bodySmall,
          'eyebrow' || 'label' => t.labelSmall,
          _ => t.bodyMedium,
        };
        final Widget child = Text(
          variant == 'eyebrow' ? content.toUpperCase() : content,
          style: style,
          textAlign: switch (n.component.constString('align')) {
            'center' => TextAlign.center,
            'end' || 'right' => TextAlign.end,
            _ => TextAlign.start,
          },
        );
        return content.isEmpty ? const SizedBox.shrink() : child;
      },
      'Column': (A2uiNode n) {
        final String? heading = n.string('heading');
        final String? subheading = n.string('subheading');
        final double gap = switch (n.component.constString('gap')) {
          'section' || 'xl' => BgSpace.xl,
          'lg' => BgSpace.lg,
          'sm' => BgSpace.sm,
          _ => n.numberOr('gap', BgSpace.md),
        };
        return Column(
          crossAxisAlignment: _crossAxis(n.component.constString('align')),
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            if (heading != null && heading.isNotEmpty) ...<Widget>[
              Text(
                heading,
                style: n.text.titleLarge?.copyWith(fontWeight: FontWeight.w700),
              ),
              if (subheading != null && subheading.isNotEmpty) ...<Widget>[
                const SizedBox(height: 4),
                Text(
                  subheading,
                  style: n.text.bodyMedium?.copyWith(
                    color: n.colors.onSurfaceVariant,
                  ),
                ),
              ],
              const SizedBox(height: BgSpace.md),
            ],
            ..._spaced(
              n.childrenOf(),
              gap,
              Axis.vertical,
            ),
          ],
        );
      },
      'Row': (A2uiNode n) => Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            mainAxisAlignment: _mainAxis(n.component.constString('justify')),
            children: _spaced(
              n.childrenOf(),
              n.numberOr('gap', BgSpace.md),
              Axis.horizontal,
            ),
          ),
      'Wrap': (A2uiNode n) => Wrap(
            spacing: n.numberOr('gap', BgSpace.sm),
            runSpacing: n.numberOr('runGap', BgSpace.sm),
            children: n.childrenOf(),
          ),
      'Card': (A2uiNode n) {
        final String? heading = n.string('title');
        return Card(
          child: Padding(
            padding: const EdgeInsets.all(BgSpace.lg),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                if (heading != null && heading.isNotEmpty) ...<Widget>[
                  Text(heading, style: n.text.titleMedium),
                  const SizedBox(height: BgSpace.md),
                ],
                ..._spaced(n.childrenOf(), BgSpace.md, Axis.vertical),
              ],
            ),
          ),
        );
      },
      'Divider': (A2uiNode _) => const Divider(height: BgSpace.xl),
      'Spacer': (A2uiNode n) =>
          SizedBox(height: n.numberOr('size', BgSpace.lg)),
      'Button': (A2uiNode n) {
        final String label = n.stringOr('label', n.stringOr('text', 'Continue'));
        final VoidCallback? onPressed = n.onTap();
        final String kind = n.component.constString('kind') ??
            n.component.constString('variant') ??
            'filled';
        return switch (kind) {
          'text' => TextButton(onPressed: onPressed, child: Text(label)),
          'outlined' =>
            OutlinedButton(onPressed: onPressed, child: Text(label)),
          _ => FilledButton(onPressed: onPressed, child: Text(label)),
        };
      },
      'Image': (A2uiNode n) {
        final String? url = n.string('url') ?? n.string('src');
        if (url == null || url.isEmpty) return const SizedBox.shrink();
        return ClipRRect(
          borderRadius: BgSpace.brSm,
          child: Image.network(
            url,
            fit: BoxFit.cover,
            // A dead image URL must not take the surface with it.
            errorBuilder: (_, __, ___) => Container(
              height: 96,
              color: n.colors.surfaceContainer,
              alignment: Alignment.center,
              child: Icon(Icons.image_not_supported_outlined,
                  color: n.colors.onSurfaceVariant),
            ),
          ),
        );
      },
      'List': (A2uiNode n) => Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            mainAxisSize: MainAxisSize.min,
            children: _spaced(
              n.childrenOf('children'),
              n.numberOr('gap', BgSpace.sm),
              Axis.vertical,
            ),
          ),
      'Badge': (A2uiNode n) {
        final String label = n.stringOr('label', '');
        if (label.isEmpty) return const SizedBox.shrink();
        return Container(
          padding: const EdgeInsets.symmetric(
              horizontal: BgSpace.sm, vertical: 2),
          decoration: BoxDecoration(
            color: n.colors.surfaceContainer,
            borderRadius: BgSpace.brSm,
            border: Border.all(color: n.colors.outlineVariant),
          ),
          child: Text(label, style: n.text.labelSmall),
        );
      },
    };

CrossAxisAlignment _crossAxis(String? v) => switch (v) {
      'center' => CrossAxisAlignment.center,
      'end' => CrossAxisAlignment.end,
      'stretch' => CrossAxisAlignment.stretch,
      _ => CrossAxisAlignment.start,
    };

MainAxisAlignment _mainAxis(String? v) => switch (v) {
      'center' => MainAxisAlignment.center,
      'end' => MainAxisAlignment.end,
      'between' => MainAxisAlignment.spaceBetween,
      'around' => MainAxisAlignment.spaceAround,
      _ => MainAxisAlignment.start,
    };

List<Widget> _spaced(List<Widget> children, double gap, Axis axis) {
  if (children.length < 2 || gap <= 0) return children;
  final List<Widget> out = <Widget>[];
  for (var i = 0; i < children.length; i++) {
    out.add(children[i]);
    if (i != children.length - 1) {
      out.add(axis == Axis.vertical
          ? SizedBox(height: gap)
          : SizedBox(width: gap));
    }
  }
  return out;
}

/// The full BAROGROOVE catalog: A2UI primitives plus the domain components
/// declared by the Python side, including live AI Telemetry Inspector nodes.
A2uiCatalog buildBarogrooveCatalog() =>
    A2uiCatalog(basicComponents()).merge(<String, A2uiComponentBuilder>{
      'SkyDial': (A2uiNode n) => SkyDialComponent(node: n),
      'ThemeChips': (A2uiNode n) => ThemeChipsComponent(node: n),
      'GenreCorridor': (A2uiNode n) => GenreCorridorComponent(node: n),
      'TrackList': (A2uiNode n) => TrackListComponent(node: n),
      'RationaleCard': (A2uiNode n) => RationaleCardComponent(node: n),
      'AlmanacTimeline': (A2uiNode n) => AlmanacTimelineComponent(node: n),
      'TelemetryInspector': (A2uiNode n) => TelemetryInspectorA2uiWidget(node: n),
      'TelemetryEntry': (A2uiNode n) => TelemetryEntryA2uiWidget(node: n),
    });


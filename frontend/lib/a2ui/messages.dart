/// Typed models for the A2UI v1.0 wire format.
///
/// ## What this file is
///
/// A2UI (a2ui.org) is a declarative protocol for an agent to describe a UI
/// that a client renders with its own native widgets. The agent never ships
/// code; it ships a JSON blueprint referencing a *catalog* of components the
/// client has pre-approved. BAROGROOVE declares that catalog exactly once, in
/// Python, and serves it from `GET /api/surfaces/catalog`.
///
/// ## Spec status (read this before "fixing" anything here)
///
/// A2UI v1.0 is a RELEASE CANDIDATE. The following were confirmed against
/// a2ui.org and the Flutter `genui` implementation notes:
///
///   * Agent -> renderer messages: `createSurface`, `updateComponents`,
///     `updateDataModel`, `deleteSurface`, `callRendererFunction`,
///     `agentFunctionResponse`.
///   * Renderer -> agent messages: `callAgentFunction`,
///     `rendererFunctionResponse`, `actionResponse`.
///   * v1.0 renamed `theme` to `surfaceProperties`, introduced action IDs,
///     and allows a whole UI to be instantiated from a single message.
///   * `createSurface` implicitly instantiates a Surface container whose
///     child is the component with `"id": "root"`. Exactly one component in
///     the stream must carry that id.
///   * Data binding uses Dynamic* types that accept a literal, a JSON-Pointer
///     path into the data model, or a FunctionCall.
///   * `ChildList` accepts either an explicit array of component ids or a
///     template + data-binding path.
///
/// UNVERIFIED (the RC moved during development; these are the shapes we
/// implement, and the parser is deliberately lenient about all of them):
///   * The exact JSON key spelling inside Dynamic* wrappers. We accept
///     `literalString`/`literalNumber`/`literalBoolean`, plain `literal`,
///     `path`, and `functionCall`, and we also accept a bare scalar.
///   * The exact key names inside ChildList. We accept `explicitList`, a bare
///     array, and `template` + (`dataBinding` | `path`).
///   * Whether `actionResponse` carries `timestamp`. We send it; a server
///     that ignores it loses nothing.
///
/// ## Parsing philosophy
///
/// Everything in this file is total: no parse path throws. A malformed
/// message becomes an [UnknownA2uiMessage] carrying the raw map and a reason,
/// which the renderer surfaces as a visible-but-non-fatal placeholder. A bad
/// message from the agent must never white-screen the app.
library;

import 'dart:convert';

// ===========================================================================
// Low-level JSON helpers
// ===========================================================================

/// A decoded JSON object. Used at the protocol boundary only; nothing past
/// the parse layer traffics in `dynamic`.
typedef JsonMap = Map<String, Object?>;

/// Safely reads a nested JSON object, returning `null` rather than throwing.
JsonMap? asJsonMap(Object? value) {
  if (value is Map<String, Object?>) return value;
  if (value is Map) {
    // Decoded JSON is normally Map<String, dynamic>; this covers the odd
    // Map<dynamic, dynamic> that turns up from some codecs.
    return value.map<String, Object?>(
      (Object? k, Object? v) => MapEntry<String, Object?>('$k', v),
    );
  }
  return null;
}

/// Safely reads a JSON list.
List<Object?>? asJsonList(Object? value) => value is List ? value : null;

String? asStringOrNull(Object? value) => value is String ? value : null;

double? asDoubleOrNull(Object? value) {
  if (value is num) return value.toDouble();
  if (value is String) return double.tryParse(value);
  return null;
}

bool? asBoolOrNull(Object? value) {
  if (value is bool) return value;
  if (value is String) {
    if (value == 'true') return true;
    if (value == 'false') return false;
  }
  return null;
}

List<String> asStringList(Object? value) {
  final List<Object?>? raw = asJsonList(value);
  if (raw == null) return const <String>[];
  return <String>[
    for (final Object? e in raw)
      if (e != null) '$e',
  ];
}

// ===========================================================================
// Dynamic values — the data-binding primitive
// ===========================================================================

/// How a [DynamicValue] gets its value.
enum DynamicKind {
  /// An inline constant baked into the component description.
  literal,

  /// A JSON Pointer (RFC 6901) into the surface data model, e.g. `/sky/gust`.
  path,

  /// A call into a client-side function registered by the renderer.
  functionCall,
}

/// A value in a component's properties that may be constant, bound to the
/// data model, or computed.
///
/// The renderer resolves these lazily at build time against the current
/// [SurfaceDataModel], so an `updateDataModel` on `/sky` rebuilds only the
/// widgets that read a path under `/sky`.
final class DynamicValue {
  const DynamicValue.literal(Object? value)
      : kind = DynamicKind.literal,
        literalValue = value,
        pointer = null,
        call = null;

  const DynamicValue.path(String this.pointer)
      : kind = DynamicKind.path,
        literalValue = null,
        call = null;

  const DynamicValue.function(FunctionCall this.call)
      : kind = DynamicKind.functionCall,
        literalValue = null,
        pointer = null;

  final DynamicKind kind;
  final Object? literalValue;
  final String? pointer;
  final FunctionCall? call;

  /// Parses any of the accepted Dynamic* encodings.
  ///
  /// Accepts, in order of preference:
  ///   `{"path": "/a/b"}`
  ///   `{"functionCall": {...}}`
  ///   `{"literalString": "x"}` / `literalNumber` / `literalBoolean` /
  ///   `literalArray` / `literalObject` / `literal`
  ///   a bare scalar (`"x"`, `3`, `true`) — treated as a literal
  ///
  /// Returns `null` only when [raw] is `null`, so callers can distinguish
  /// "absent" from "present but empty".
  static DynamicValue? parse(Object? raw) {
    if (raw == null) return null;

    final JsonMap? map = asJsonMap(raw);
    if (map == null) {
      // Bare scalar or bare list. Lenient by design: a server that inlines
      // `"text": "Hello"` instead of `{"literalString": "Hello"}` still works.
      return DynamicValue.literal(raw);
    }

    final String? pointer = asStringOrNull(map['path']);
    if (pointer != null) return DynamicValue.path(pointer);

    final JsonMap? fn = asJsonMap(map['functionCall']);
    if (fn != null) {
      final FunctionCall? parsed = FunctionCall.parse(fn);
      if (parsed != null) return DynamicValue.function(parsed);
    }

    for (final String key in _literalKeys) {
      if (map.containsKey(key)) return DynamicValue.literal(map[key]);
    }

    // A map that is not a Dynamic wrapper at all — e.g. a nested object
    // property. Pass it through as a literal object.
    return DynamicValue.literal(map);
  }

  static const List<String> _literalKeys = <String>[
    'literalString',
    'literalNumber',
    'literalBoolean',
    'literalArray',
    'literalObject',
    'literal',
    'value',
  ];

  /// Every data-model pointer this value depends on. Used by the renderer to
  /// decide whether an `updateDataModel` affects this subtree.
  Iterable<String> get dependencies sync* {
    switch (kind) {
      case DynamicKind.path:
        yield pointer!;
      case DynamicKind.functionCall:
        yield* call!.dependencies;
      case DynamicKind.literal:
        break;
    }
  }

  @override
  String toString() => switch (kind) {
        DynamicKind.literal => 'literal(${jsonEncode(_safe(literalValue))})',
        DynamicKind.path => 'path($pointer)',
        DynamicKind.functionCall => 'call(${call!.name})',
      };

  static Object? _safe(Object? v) =>
      v is String || v is num || v is bool || v == null ? v : '$v';
}

/// A call to a renderer-side function used inside a data binding, e.g.
/// `{"name": "formatSigned", "args": [{"path": "/sky/pressure_trend_6h"}]}`.
final class FunctionCall {
  const FunctionCall({required this.name, required this.args});

  final String name;
  final List<DynamicValue> args;

  static FunctionCall? parse(JsonMap map) {
    final String? name = asStringOrNull(map['name']) ??
        asStringOrNull(map['function']) ??
        asStringOrNull(map['functionName']);
    if (name == null) return null;

    // Args may arrive as a positional list or a named map. We normalise the
    // map form into a positional list ordered by key, which is what our
    // registered functions expect; named-arg functions read `namedArgs`.
    final List<DynamicValue> args = <DynamicValue>[];
    final List<Object?>? list =
        asJsonList(map['args']) ?? asJsonList(map['parameters']);
    if (list != null) {
      for (final Object? a in list) {
        final DynamicValue? parsed = DynamicValue.parse(a);
        if (parsed != null) args.add(parsed);
      }
    } else {
      final JsonMap? named =
          asJsonMap(map['args']) ?? asJsonMap(map['parameters']);
      if (named != null) {
        final List<String> keys = named.keys.toList()..sort();
        for (final String k in keys) {
          final DynamicValue? parsed = DynamicValue.parse(named[k]);
          if (parsed != null) args.add(parsed);
        }
      }
    }
    return FunctionCall(name: name, args: args);
  }

  Iterable<String> get dependencies sync* {
    for (final DynamicValue a in args) {
      yield* a.dependencies;
    }
  }
}

// ===========================================================================
// ChildList — explicit ids or a template over a bound list
// ===========================================================================

/// The two ways a component names its children.
///
/// Explicit: `{"explicitList": ["header", "body"]}`
/// Template: `{"template": {"componentId": "trackRow", "dataBinding": "/tracks"}}`
///
/// The template form is how the agent describes a list without emitting one
/// component per row: it names a prototype component and a pointer to an
/// array, and the renderer instantiates the prototype once per element with
/// the data-model scope rebased onto that element.
final class ChildList {
  const ChildList.explicit(this.ids)
      : templateComponentId = null,
        templatePath = null;

  const ChildList.template({
    required String this.templateComponentId,
    required String this.templatePath,
  }) : ids = const <String>[];

  final List<String> ids;
  final String? templateComponentId;
  final String? templatePath;

  bool get isTemplate => templateComponentId != null;

  static const ChildList empty = ChildList.explicit(<String>[]);

  static ChildList parse(Object? raw) {
    if (raw == null) return empty;

    // Bare array of ids.
    final List<Object?>? bare = asJsonList(raw);
    if (bare != null) return ChildList.explicit(asStringList(bare));

    final JsonMap? map = asJsonMap(raw);
    if (map == null) return empty;

    final JsonMap? template = asJsonMap(map['template']);
    if (template != null) {
      final String? componentId = asStringOrNull(template['componentId']) ??
          asStringOrNull(template['component']) ??
          asStringOrNull(template['id']);
      final String? path = asStringOrNull(template['dataBinding']) ??
          asStringOrNull(template['path']) ??
          asStringOrNull(template['items']);
      if (componentId != null && path != null) {
        return ChildList.template(
          templateComponentId: componentId,
          templatePath: path,
        );
      }
      return empty;
    }

    final List<Object?>? explicit =
        asJsonList(map['explicitList']) ?? asJsonList(map['ids']);
    if (explicit != null) return ChildList.explicit(asStringList(explicit));

    return empty;
  }
}

// ===========================================================================
// Component
// ===========================================================================

/// One node in the component tree.
///
/// Wire shape:
/// ```json
/// { "id": "skyHero",
///   "componentProperties": { "SkyDial": { "vector": {"path": "/sky"} } } }
/// ```
/// The single key inside `componentProperties` is the component *type*, which
/// must be present in the catalog. This double-wrapping is what lets the
/// renderer dispatch on type without a discriminator field.
final class A2uiComponent {
  const A2uiComponent({
    required this.id,
    required this.type,
    required this.properties,
    this.raw = const <String, Object?>{},
  });

  /// Component id. `"root"` is the implicit child of the surface container.
  final String id;

  /// Catalog type name, e.g. `SkyDial`, `Column`, `Text`.
  final String type;

  /// Raw property map for this type, values un-resolved. Read through
  /// [dyn] / [children] rather than directly.
  final JsonMap properties;

  /// The original JSON, kept for the placeholder renderer to display when a
  /// type is unknown.
  final JsonMap raw;

  /// Reads a property as a [DynamicValue]. Returns `null` if absent.
  DynamicValue? dyn(String key) => DynamicValue.parse(properties[key]);

  /// Reads a property as a [ChildList].
  ChildList children([String key = 'children']) =>
      ChildList.parse(properties[key]);

  /// Reads a property that is a plain, never-bound constant (e.g. an enum
  /// name the agent would not bind). Falls back through the Dynamic wrapper
  /// so both encodings work.
  String? constString(String key) {
    final Object? v = properties[key];
    final String? direct = asStringOrNull(v);
    if (direct != null) return direct;
    final DynamicValue? d = DynamicValue.parse(v);
    if (d != null && d.kind == DynamicKind.literal) {
      final Object? lit = d.literalValue;
      return lit == null ? null : '$lit';
    }
    return null;
  }

  static A2uiComponent? parse(Object? raw) {
    final JsonMap? map = asJsonMap(raw);
    if (map == null) return null;

    final String? id = asStringOrNull(map['id']) ??
        asStringOrNull(map['componentId']);
    if (id == null) return null;

    // v1.0 nests the type inside componentProperties. Some emitters use a
    // flat `{"id":..., "component": "Text", "properties": {...}}`; accept both.
    final JsonMap? wrapper = asJsonMap(map['componentProperties']) ??
        asJsonMap(map['component']);
    if (wrapper != null && wrapper.length == 1) {
      final String type = wrapper.keys.first;
      return A2uiComponent(
        id: id,
        type: type,
        properties: asJsonMap(wrapper[type]) ?? const <String, Object?>{},
        raw: map,
      );
    }

    final String? flatType = asStringOrNull(map['component']) ??
        asStringOrNull(map['type']) ??
        asStringOrNull(map['componentType']);
    if (flatType != null) {
      final JsonMap merged = <String, Object?>{
        for (final MapEntry<String, Object?> entry in map.entries)
          if (entry.key != 'id' &&
              entry.key != 'componentId' &&
              entry.key != 'component' &&
              entry.key != 'type' &&
              entry.key != 'componentType' &&
              entry.key != 'properties' &&
              entry.key != 'componentProperties')
            entry.key: entry.value,
        ...?asJsonMap(map['componentProperties']),
        ...?asJsonMap(map['properties']),
      };
      return A2uiComponent(
        id: id,
        type: flatType,
        properties: merged,
        raw: map,
      );
    }

    // Present but untypeable. Return a node so the renderer can show a
    // placeholder naming the id, which is far more useful than dropping it.
    return A2uiComponent(
      id: id,
      type: '',
      properties: const <String, Object?>{},
      raw: map,
    );
  }
}

// ===========================================================================
// Surface properties (v1.0 rename of `theme`)
// ===========================================================================

/// Presentation hints for a whole surface. v1.0 renamed this from `theme`.
///
/// BAROGROOVE uses it narrowly: an accent hex from the active theme palette
/// and an optional density. The app's slate/sky register is not negotiable, so
/// we ignore anything that would take us out of it.
final class SurfaceProperties {
  const SurfaceProperties({
    this.accentHex,
    this.backgroundHex,
    this.density,
    this.title,
    this.extras = const <String, Object?>{},
  });

  final String? accentHex;
  final String? backgroundHex;
  final String? density;
  final String? title;
  final JsonMap extras;

  static const SurfaceProperties none = SurfaceProperties();

  static SurfaceProperties parse(Object? raw) {
    final JsonMap? map = asJsonMap(raw);
    if (map == null) return none;
    return SurfaceProperties(
      accentHex: asStringOrNull(map['accent']) ??
          asStringOrNull(map['primaryColor']) ??
          asStringOrNull(map['accentColor']),
      backgroundHex: asStringOrNull(map['background']) ??
          asStringOrNull(map['backgroundColor']),
      density: asStringOrNull(map['density']),
      title: asStringOrNull(map['title']),
      extras: map,
    );
  }
}

// ===========================================================================
// Agent -> renderer messages
// ===========================================================================

/// Base type for every message the agent sends us.
sealed class A2uiMessage {
  const A2uiMessage({required this.surfaceId});

  /// Surface this message applies to. `''` when the emitter omitted it, in
  /// which case the renderer assumes its own surface.
  final String surfaceId;

  /// Parses one envelope.
  ///
  /// An envelope is a single-key object whose key names the message type:
  /// `{"updateDataModel": {"surfaceId": "sky", "path": "/sky", ...}}`.
  /// We also accept a flattened form with an explicit `type` discriminator,
  /// because some emitters produce that.
  ///
  /// Never throws. Unrecognised input becomes [UnknownA2uiMessage].
  static A2uiMessage parse(Object? raw) {
    final JsonMap? envelope = asJsonMap(raw);
    if (envelope == null) {
      return UnknownA2uiMessage(
        surfaceId: '',
        reason: 'envelope is not a JSON object',
        raw: <String, Object?>{'value': '$raw'},
      );
    }

    // Flattened form: {"type": "updateDataModel", ...}
    final String? explicitType = asStringOrNull(envelope['type']) ??
        asStringOrNull(envelope['messageType']);
    if (explicitType != null) {
      return _byType(explicitType, envelope, envelope);
    }

    // Canonical form: exactly one known key.
    for (final String key in envelope.keys) {
      if (_knownTypes.contains(key)) {
        final JsonMap body =
            asJsonMap(envelope[key]) ?? const <String, Object?>{};
        return _byType(key, body, envelope);
      }
    }

    return UnknownA2uiMessage(
      surfaceId: asStringOrNull(envelope['surfaceId']) ?? '',
      reason: 'no recognised message type in keys ${envelope.keys.toList()}',
      raw: envelope,
    );
  }

  /// Parses a batch. Our backend returns a JSON array of envelopes from
  /// `/api/surfaces/*`; this is the entry point for that.
  static List<A2uiMessage> parseBatch(Object? raw) {
    final List<Object?>? list = asJsonList(raw);
    if (list != null) {
      return <A2uiMessage>[for (final Object? e in list) A2uiMessage.parse(e)];
    }
    final JsonMap? map = asJsonMap(raw);
    if (map != null) {
      // `{"messages": [...]}` is a common wrapper.
      final List<Object?>? inner =
          asJsonList(map['messages']) ?? asJsonList(map['a2ui_operations']);
      if (inner != null) {
        return <A2uiMessage>[
          for (final Object? e in inner) A2uiMessage.parse(e),
        ];
      }
      return <A2uiMessage>[A2uiMessage.parse(map)];
    }
    return <A2uiMessage>[
      UnknownA2uiMessage(
        surfaceId: '',
        reason: 'batch is neither array nor object',
        raw: <String, Object?>{'value': '$raw'},
      ),
    ];
  }

  /// Convenience for a JSON string body.
  static List<A2uiMessage> parseJson(String source) {
    try {
      return parseBatch(jsonDecode(source));
    } on FormatException catch (e) {
      return <A2uiMessage>[
        UnknownA2uiMessage(
          surfaceId: '',
          reason: 'malformed JSON: ${e.message}',
          raw: <String, Object?>{
            'preview': source.substring(0, source.length.clamp(0, 240)),
          },
        ),
      ];
    }
  }

  static const Set<String> _knownTypes = <String>{
    'createSurface',
    'updateComponents',
    'updateDataModel',
    'deleteSurface',
    'callRendererFunction',
    'agentFunctionResponse',
  };

  static A2uiMessage _byType(String type, JsonMap body, JsonMap envelope) {
    final String surfaceId = asStringOrNull(body['surfaceId']) ??
        asStringOrNull(envelope['surfaceId']) ??
        '';
    switch (type) {
      case 'createSurface':
        return CreateSurface(
          surfaceId: surfaceId,
          catalogUri: asStringOrNull(body['catalogUri']) ??
              asStringOrNull(body['catalog']),
          surfaceProperties: SurfaceProperties.parse(
            body['surfaceProperties'] ?? body['theme'],
          ),
          // v1.0 allows a whole UI in one message, so createSurface may carry
          // both the components and the initial data model.
          components: _components(body['components']),
          initialDataModel: asJsonMap(body['dataModel']) ??
              asJsonMap(body['contents']),
        );

      case 'updateComponents':
        return UpdateComponents(
          surfaceId: surfaceId,
          components: _components(body['components']),
        );

      case 'updateDataModel':
        return UpdateDataModel(
          surfaceId: surfaceId,
          // A pointer of '' or '/' means "replace the whole model".
          path: asStringOrNull(body['path']) ?? '',
          contents: body.containsKey('contents')
              ? body['contents']
              : body['value'] ?? body['data'],
        );

      case 'deleteSurface':
        return DeleteSurface(surfaceId: surfaceId);

      case 'callRendererFunction':
        return CallRendererFunction(
          surfaceId: surfaceId,
          functionCallId: asStringOrNull(body['functionCallId']) ??
              asStringOrNull(body['callId']) ??
              '',
          name: asStringOrNull(body['name']) ?? '',
          parameters: asJsonMap(body['parameters']) ??
              asJsonMap(body['args']) ??
              const <String, Object?>{},
        );

      case 'agentFunctionResponse':
        return AgentFunctionResponse(
          surfaceId: surfaceId,
          functionCallId: asStringOrNull(body['functionCallId']) ??
              asStringOrNull(body['callId']) ??
              '',
          result: body['result'] ?? body['response'],
          error: asStringOrNull(body['error']),
        );

      default:
        return UnknownA2uiMessage(
          surfaceId: surfaceId,
          reason: 'unhandled message type "$type"',
          raw: envelope,
        );
    }
  }

  static List<A2uiComponent> _components(Object? raw) {
    final List<Object?>? list = asJsonList(raw);
    if (list == null) {
      // Single component, not wrapped in an array.
      final A2uiComponent? one = A2uiComponent.parse(raw);
      return one == null ? const <A2uiComponent>[] : <A2uiComponent>[one];
    }
    final List<A2uiComponent> out = <A2uiComponent>[];
    for (final Object? e in list) {
      final A2uiComponent? c = A2uiComponent.parse(e);
      if (c != null) out.add(c);
    }
    return out;
  }
}

/// Creates (or resets) a surface.
///
/// Per v1.0 this implicitly instantiates a Surface container whose child is
/// the component with id `root`. If no such component ever arrives, the
/// renderer shows a placeholder saying so — that is a server bug worth seeing.
final class CreateSurface extends A2uiMessage {
  const CreateSurface({
    required super.surfaceId,
    required this.surfaceProperties,
    required this.components,
    this.catalogUri,
    this.initialDataModel,
  });

  final String? catalogUri;
  final SurfaceProperties surfaceProperties;

  /// v1.0 single-message instantiation: components may ride along here.
  final List<A2uiComponent> components;
  final JsonMap? initialDataModel;
}

/// Adds or replaces components by id. Ids not mentioned are left alone.
final class UpdateComponents extends A2uiMessage {
  const UpdateComponents({
    required super.surfaceId,
    required this.components,
  });

  final List<A2uiComponent> components;
}

/// Writes [contents] into the data model at JSON Pointer [path].
///
/// An empty path replaces the root. The renderer uses [path] to rebuild only
/// the subtrees whose bindings depend on it.
final class UpdateDataModel extends A2uiMessage {
  const UpdateDataModel({
    required super.surfaceId,
    required this.path,
    required this.contents,
  });

  final String path;
  final Object? contents;
}

/// Tears the surface down.
final class DeleteSurface extends A2uiMessage {
  const DeleteSurface({required super.surfaceId});
}

/// The agent asks the renderer to run a client-side function (e.g. "scroll to
/// the peak track", "open the pairing sheet"). We reply with a
/// [RendererFunctionResponse].
final class CallRendererFunction extends A2uiMessage {
  const CallRendererFunction({
    required super.surfaceId,
    required this.functionCallId,
    required this.name,
    required this.parameters,
  });

  final String functionCallId;
  final String name;
  final JsonMap parameters;
}

/// The agent's answer to a [CallAgentFunction] we sent earlier.
final class AgentFunctionResponse extends A2uiMessage {
  const AgentFunctionResponse({
    required super.surfaceId,
    required this.functionCallId,
    required this.result,
    this.error,
  });

  final String functionCallId;
  final Object? result;
  final String? error;
}

/// Anything we could not make sense of. Rendered as a visible placeholder;
/// never thrown.
final class UnknownA2uiMessage extends A2uiMessage {
  const UnknownA2uiMessage({
    required super.surfaceId,
    required this.reason,
    required this.raw,
  });

  final String reason;
  final JsonMap raw;
}

// ===========================================================================
// Renderer -> agent messages
// ===========================================================================

/// Base for everything we POST to `/api/surfaces/action`.
sealed class RendererMessage {
  const RendererMessage({required this.surfaceId});

  final String surfaceId;

  /// Serialises to the canonical single-key envelope.
  JsonMap toJson();
}

/// A user action fired from a component that declares an action id.
///
/// v1.0 introduced action IDs specifically so the agent can correlate a tap
/// with the affordance it described, rather than guessing from component ids.
/// This is what makes a theme chip talk to the agent instead of being local
/// state.
final class ActionResponse extends RendererMessage {
  const ActionResponse({
    required super.surfaceId,
    required this.actionId,
    this.componentId,
    this.payload = const <String, Object?>{},
    this.timestamp,
  });

  final String actionId;
  final String? componentId;
  final JsonMap payload;
  final DateTime? timestamp;

  @override
  JsonMap toJson() => <String, Object?>{
        'actionResponse': <String, Object?>{
          'surfaceId': surfaceId,
          'actionId': actionId,
          if (componentId != null) 'sourceComponentId': componentId,
          'payload': payload,
          'timestamp':
              (timestamp ?? DateTime.now().toUtc()).toIso8601String(),
        },
      };
}

/// The renderer asks the agent to run a function — the escape hatch for
/// interactions richer than a tap (e.g. "re-forge with this genre width").
final class CallAgentFunction extends RendererMessage {
  const CallAgentFunction({
    required super.surfaceId,
    required this.functionCallId,
    required this.name,
    this.parameters = const <String, Object?>{},
  });

  final String functionCallId;
  final String name;
  final JsonMap parameters;

  @override
  JsonMap toJson() => <String, Object?>{
        'callAgentFunction': <String, Object?>{
          'surfaceId': surfaceId,
          'functionCallId': functionCallId,
          'name': name,
          'parameters': parameters,
        },
      };
}

/// Our answer to a [CallRendererFunction].
final class RendererFunctionResponse extends RendererMessage {
  const RendererFunctionResponse({
    required super.surfaceId,
    required this.functionCallId,
    this.result,
    this.error,
  });

  final String functionCallId;
  final Object? result;
  final String? error;

  @override
  JsonMap toJson() => <String, Object?>{
        'rendererFunctionResponse': <String, Object?>{
          'surfaceId': surfaceId,
          'functionCallId': functionCallId,
          if (result != null) 'result': result,
          if (error != null) 'error': error,
        },
      };
}

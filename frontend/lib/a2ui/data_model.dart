/// The surface data model: a JSON document addressed by JSON Pointer, with
/// path-scoped change notification.
///
/// ## Why this is not just a Map
///
/// A2UI separates *structure* (components, sent once) from *state* (the data
/// model, updated continuously). A single `updateDataModel` on `/sky` should
/// rebuild the SkyDial and nothing else — not the track list, not the
/// rationale card. To do that the model has to tell subscribers not merely
/// "something changed" but "this pointer changed", and each bound widget has
/// to decide whether that pointer intersects its own dependencies.
///
/// [SurfaceDataModel] is a [ChangeNotifier] for coarse listeners plus a
/// [revisionFor] mechanism for fine-grained ones. A widget bound to `/sky/gust`
/// holds the revision it last built with; when it is notified it compares
/// revisions and skips the rebuild if its own subtree is untouched.
///
/// ## Pointer semantics (RFC 6901)
///
///   ''            -> the whole document
///   '/'           -> the property named '' (per spec); we treat it as root,
///                    because no real emitter means the empty-string key and
///                    treating it as root is the forgiving choice
///   '/a/b'        -> document['a']['b']
///   '/list/0'     -> document['list'][0]
///   '/a~1b'       -> document['a/b']   (~1 is '/')
///   '/a~0b'       -> document['a~b']   (~0 is '~')
///
/// Resolution never throws. A miss returns `null`, which the renderer
/// distinguishes from a legitimate null by [resolveEntry].
library;

import 'package:flutter/foundation.dart';

import 'messages.dart';

/// Result of a pointer lookup, distinguishing "absent" from "present, null".
@immutable
final class PointerLookup {
  const PointerLookup.found(this.value)
      : found = true,
        missingSegment = null;

  const PointerLookup.missing(this.missingSegment)
      : found = false,
        value = null;

  final bool found;
  final Object? value;

  /// The first segment that could not be walked. Useful in placeholder text:
  /// "no data at /sky/gust (missing 'gust')" beats a silent blank.
  final String? missingSegment;
}

/// Parses and escapes RFC 6901 JSON Pointers.
final class JsonPointer {
  const JsonPointer(this.segments, {required this.isRoot});

  final List<String> segments;
  final bool isRoot;

  static const JsonPointer root = JsonPointer(<String>[], isRoot: true);

  /// Parses a pointer string. Tolerates a missing leading slash (`sky/gust`)
  /// because emitters get that wrong often enough to be worth absorbing.
  factory JsonPointer.parse(String pointer) {
    if (pointer.isEmpty || pointer == '/' || pointer == '#') {
      return root;
    }
    var s = pointer;
    if (s.startsWith('#')) s = s.substring(1);
    if (s.startsWith('/')) s = s.substring(1);
    if (s.isEmpty) return root;

    return JsonPointer(
      s.split('/').map(unescape).toList(growable: false),
      isRoot: false,
    );
  }

  /// `~1` -> `/`, `~0` -> `~`. Order matters: `~0` last, or `~01` decodes
  /// wrongly.
  static String unescape(String segment) =>
      segment.replaceAll('~1', '/').replaceAll('~0', '~');

  static String escape(String segment) =>
      segment.replaceAll('~', '~0').replaceAll('/', '~1');

  /// Renders back to canonical form.
  String get canonical =>
      isRoot ? '' : '/${segments.map(escape).join('/')}';

  /// True when [other] is this pointer or lives underneath it.
  /// `/sky`.contains(`/sky/gust`) == true. Root contains everything.
  bool contains(JsonPointer other) {
    if (isRoot) return true;
    if (other.segments.length < segments.length) return false;
    for (var i = 0; i < segments.length; i++) {
      if (segments[i] != other.segments[i]) return false;
    }
    return true;
  }

  /// True when a change at [changed] could affect a read of this pointer.
  /// That is either direction of containment: a write to `/sky` affects a
  /// read of `/sky/gust`, and a write to `/sky/gust` affects a read of `/sky`.
  bool intersects(JsonPointer changed) =>
      contains(changed) || changed.contains(this);

  /// This pointer with [child] appended.
  JsonPointer child(String segment) => JsonPointer(
        <String>[...segments, segment],
        isRoot: false,
      );

  /// This pointer with an array index appended.
  JsonPointer index(int i) => child('$i');

  @override
  String toString() => canonical;

  @override
  bool operator ==(Object other) =>
      other is JsonPointer && other.canonical == canonical;

  @override
  int get hashCode => canonical.hashCode;
}

/// The observable data model for one surface.
class SurfaceDataModel extends ChangeNotifier {
  SurfaceDataModel([JsonMap? initial])
      : _root = initial == null
            ? <String, Object?>{}
            : Map<String, Object?>.of(initial);

  Object? _root;
  int _revision = 0;

  /// Pointers written since the model was created, each with the revision at
  /// which it was written. Bound widgets consult this to decide on rebuild.
  final Map<String, int> _writes = <String, int>{};

  /// Monotonically increasing; bumped on every successful write.
  int get revision => _revision;

  /// The whole document. Treat as read-only.
  Object? get root => _root;

  /// The revision at which anything intersecting [pointer] last changed.
  ///
  /// A widget stores this alongside its built output and rebuilds only when
  /// the number moves. This is the mechanism that keeps an `updateDataModel`
  /// on `/tracks` from repainting the SkyDial.
  int revisionFor(String pointer) {
    final JsonPointer p = JsonPointer.parse(pointer);
    var latest = 0;
    for (final MapEntry<String, int> e in _writes.entries) {
      final JsonPointer written = JsonPointer.parse(e.key);
      if (p.intersects(written) && e.value > latest) latest = e.value;
    }
    return latest;
  }

  /// Highest revision across a set of dependencies. The renderer passes a
  /// component's full dependency set here.
  int revisionForAll(Iterable<String> pointers) {
    var latest = 0;
    for (final String p in pointers) {
      final int r = revisionFor(p);
      if (r > latest) latest = r;
    }
    return latest;
  }

  /// Reads [pointer], reporting whether it resolved.
  PointerLookup resolveEntry(String pointer) {
    final JsonPointer p = JsonPointer.parse(pointer);
    if (p.isRoot) return PointerLookup.found(_root);

    Object? cursor = _root;
    for (final String segment in p.segments) {
      if (cursor is Map) {
        final Map<String, Object?>? m = asJsonMap(cursor);
        if (m == null || !m.containsKey(segment)) {
          return PointerLookup.missing(segment);
        }
        cursor = m[segment];
      } else if (cursor is List) {
        final int? i = int.tryParse(segment);
        if (i == null || i < 0 || i >= cursor.length) {
          return PointerLookup.missing(segment);
        }
        cursor = cursor[i];
      } else {
        // Tried to descend into a scalar.
        return PointerLookup.missing(segment);
      }
    }
    return PointerLookup.found(cursor);
  }

  /// Reads [pointer], or `null` if absent.
  Object? resolve(String pointer) => resolveEntry(pointer).value;

  String? resolveString(String pointer) {
    final Object? v = resolve(pointer);
    if (v == null) return null;
    return v is String ? v : '$v';
  }

  double? resolveDouble(String pointer) => asDoubleOrNull(resolve(pointer));

  bool? resolveBool(String pointer) => asBoolOrNull(resolve(pointer));

  List<Object?>? resolveList(String pointer) => asJsonList(resolve(pointer));

  JsonMap? resolveMap(String pointer) => asJsonMap(resolve(pointer));

  /// Applies an `updateDataModel`.
  ///
  /// Writing to the root replaces the whole document. Writing to a deeper
  /// pointer creates intermediate containers as needed — maps for
  /// non-numeric segments, lists for numeric ones — so the agent can send
  /// `/tracks/3/loved` without having pre-declared `/tracks`.
  void apply(String pointer, Object? contents) {
    final JsonPointer p = JsonPointer.parse(pointer);

    if (p.isRoot) {
      _root = contents is Map
          ? Map<String, Object?>.of(asJsonMap(contents)!)
          : contents;
      _recordWrite(p);
      return;
    }

    _root ??= <String, Object?>{};
    if (_root is! Map && _root is! List) {
      // The document was a scalar; a deep write means it should have been a
      // container. Promote rather than fail.
      _root = <String, Object?>{};
    }

    Object? cursor = _root;
    for (var i = 0; i < p.segments.length - 1; i++) {
      final String segment = p.segments[i];
      final String next = p.segments[i + 1];
      final bool nextIsIndex = int.tryParse(next) != null;

      if (cursor is Map) {
        final Map<Object?, Object?> m = cursor;
        Object? childValue = m[segment];
        if (childValue is! Map && childValue is! List) {
          childValue = nextIsIndex ? <Object?>[] : <String, Object?>{};
          m[segment] = childValue;
        }
        cursor = childValue;
      } else if (cursor is List) {
        final int? idx = int.tryParse(segment);
        if (idx == null || idx < 0) return; // Unwritable path; drop quietly.
        while (cursor.length <= idx) {
          cursor.add(nextIsIndex ? <Object?>[] : <String, Object?>{});
        }
        Object? childValue = cursor[idx];
        if (childValue is! Map && childValue is! List) {
          childValue = nextIsIndex ? <Object?>[] : <String, Object?>{};
          cursor[idx] = childValue;
        }
        cursor = childValue;
      } else {
        return;
      }
    }

    final String leaf = p.segments.last;
    if (cursor is Map) {
      (cursor as Map<Object?, Object?>)[leaf] = contents;
    } else if (cursor is List) {
      final int? idx = int.tryParse(leaf);
      if (idx == null || idx < 0) return;
      while (cursor.length <= idx) {
        cursor.add(null);
      }
      cursor[idx] = contents;
    } else {
      return;
    }

    _recordWrite(p);
  }

  /// Replaces the entire document without going through pointer machinery.
  void replaceAll(JsonMap document) {
    _root = Map<String, Object?>.of(document);
    _recordWrite(JsonPointer.root);
  }

  /// A model scoped to a subtree, used for `ChildList` template expansion:
  /// each generated row sees the element as its `.` context while still being
  /// able to reach absolute pointers.
  ScopedDataModel scoped(String pointer) =>
      ScopedDataModel(this, JsonPointer.parse(pointer));

  void _recordWrite(JsonPointer p) {
    _revision++;
    _writes[p.canonical] = _revision;
    // Prune: only the most recent write per pointer matters, and a root write
    // subsumes everything before it.
    if (p.isRoot) {
      _writes
        ..clear()
        ..[''] = _revision;
    }
    notifyListeners();
  }

  @override
  String toString() => 'SurfaceDataModel(rev=$_revision)';
}

/// A read-only view of a [SurfaceDataModel] rebased at a pointer.
///
/// Template-generated children resolve relative pointers against [base] and
/// absolute ones (those starting `/`) against the real root. In practice the
/// agent writes `item/title` in a template and `/sky/cloud_depth` when it
/// wants the surface-wide value, and both work.
final class ScopedDataModel {
  const ScopedDataModel(this.model, this.base);

  final SurfaceDataModel model;
  final JsonPointer base;

  /// Rewrites a possibly-relative pointer into an absolute one.
  String absolute(String pointer) {
    if (pointer.startsWith('/') || pointer.isEmpty) return pointer;
    // Relative: strip a leading './' and graft onto the base.
    var rel = pointer;
    if (rel.startsWith('./')) rel = rel.substring(2);
    final JsonPointer p = JsonPointer.parse(rel);
    return JsonPointer(
      <String>[...base.segments, ...p.segments],
      isRoot: false,
    ).canonical;
  }

  PointerLookup resolveEntry(String pointer) =>
      model.resolveEntry(absolute(pointer));

  Object? resolve(String pointer) => model.resolve(absolute(pointer));

  ScopedDataModel index(int i) => ScopedDataModel(model, base.index(i));
}

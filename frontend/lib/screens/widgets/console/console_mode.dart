/// The three rungs of the Forge console (`docs/UX_IA_SPEC.md` §5).
///
/// The *state* lives in `forgeSelectionProvider.consoleMode` as a string
/// (`'guided' | 'easy' | 'expert'`) because that is what `ForgeSelection.
/// toRequest()` switches on. This enum is the typed view of that string so the
/// widgets never compare raw literals, and so the show/hide table in §5.2 is
/// expressed once, in code, rather than re-derived in every widget.
enum ConsoleMode {
  guided(
    id: 'guided',
    label: 'Guided',
    helper: 'Guided — we choose everything.',
  ),
  easy(
    id: 'easy',
    label: 'Easy',
    helper: 'Easy — nudge three dials.',
  ),
  expert(
    id: 'expert',
    label: 'Expert',
    helper: 'Expert — the full instrument panel.',
  );

  const ConsoleMode({
    required this.id,
    required this.label,
    required this.helper,
  });

  /// The value stored in `ForgeSelection.consoleMode`.
  final String id;

  /// Segment label. One word, no icon (§5.1).
  final String label;

  /// The permanent one-line helper under the segmented control (§5.1).
  final String helper;

  static ConsoleMode fromId(String? id) => switch (id) {
        'easy' => ConsoleMode.easy,
        'expert' => ConsoleMode.expert,
        _ => ConsoleMode.guided,
      };

  // ----- §5.2, the show/hide table, stated once ---------------------------

  /// Temperature / light / colour-K cursors. These are exactly the fields
  /// `toRequest()` sends outside Guided.
  bool get showsCursors => this != ConsoleMode.guided;

  /// Pressure / trend / target-BPM. `toRequest()` sends these in Expert only.
  bool get showsExpertSliders => this == ConsoleMode.expert;

  /// Telemetry badges, COEFFICIENTS, SOURCE REQUEST.
  bool get showsInstrumentation => this == ConsoleMode.expert;

  /// The A2UI SkyDial: hidden in Guided, rung 1 in Easy, rung 0 in Expert.
  bool get showsSkyDialAtGlance => this == ConsoleMode.expert;
  bool get showsSkyDialBehindDisclosure => this == ConsoleMode.easy;

  /// The three-value sky strip is replaced by the dial in Expert.
  bool get showsSkyStrip => this != ConsoleMode.expert;
}

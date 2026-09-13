// Data Viz — spec tokens that do not exist in `app_theme.dart` *yet*.
//
// UX_IA_SPEC.md §4 and §7.2 put `BgBreak.compact/expanded` and
// `BgSpace.bubbleClearance` in `frontend/lib/app_theme.dart`. That file belongs
// to the design-system worker (items 12–14) and is off-limits to this one, so
// the two values the Data Viz surface needs are declared here, verbatim from
// the spec, in a single place.
//
// MIGRATION: when the design-system worker lands `BgBreak` and
// `BgSpace.bubbleClearance`, delete this file and replace the three references
// to it (`dataviz_screen.dart`, `dataviz_dashboard.dart`,
// `dataviz_conversation.dart`). Nothing here may grow: it is a shim, not a
// second token system. No colours, no type, no radii — those all come from
// `BgPalette` / `BgSpace` / `Theme.of(context).textTheme`.

/// UX_IA_SPEC.md §4 — three breakpoints, and only three. The screen used to
/// hard-code 920; the spec unifies the whole app on 600 / 900.
class DvBreak {
  const DvBreak._();

  /// `< 600` — compact.
  static const double compact = 600;

  /// `>= 900` — expanded: nav rail, two columns, rung-1 defaults expanded.
  static const double expanded = 900;

  static bool isCompact(double width) => width < compact;
  static bool isExpanded(double width) => width >= expanded;
}

/// UX_IA_SPEC.md §7.2 — additions to `BgSpace`.
class DvSpace {
  const DvSpace._();

  /// Destination bottom padding / empty-state breathing room.
  static const double xxxl = 48;

  /// §6.2 — clearance reserved at the bottom of every scroll view so the
  /// app-wide assistant bubble (items 10+11) can never cover content.
  static const double bubbleClearance = 96;
}

// Data Viz — deprecated forwarders to the real tokens.
//
// This file used to declare `600` / `900` / `48` / `96` by hand, because the
// Data Viz worker could not edit `app_theme.dart` while the design-system
// worker owned it. Those tokens now exist for real: `BgBreak.compact`,
// `BgBreak.expanded`, `BgSpace.xxxl` and `BgSpace.bubbleClearance`.
//
// Every number below is gone — what is left forwards, so the values cannot
// drift from `app_theme.dart` by construction.
//
// MIGRATION (last step, not ours to take): the only remaining call site is
// `frontend/lib/screens/dataviz_screen.dart` (the import, `DvBreak.isCompact`,
// `DvBreak.isExpanded`, `DvSpace.bubbleClearance`), which belongs to the
// assistant-overlay worker. When that file switches to `BgBreak.forWidth(...)`
// and `BgSpace.bubbleClearance`, delete this file. The two `dataviz_dashboard`
// / `dataviz_conversation` references the original note mentioned are already
// gone.

import '../../app_theme.dart';

/// Deprecated. Use [BgBreak] (`UX_IA_SPEC.md` §4 — three breakpoints, and only
/// three). Kept as a forwarder because it takes a raw width where [BgBreak]
/// takes a `BuildContext`.
class DvBreak {
  const DvBreak._();

  static const double compact = BgBreak.compact;
  static const double expanded = BgBreak.expanded;

  static bool isCompact(double width) =>
      BgBreak.forWidth(width) == BgBreakpoint.compact;

  static bool isExpanded(double width) =>
      BgBreak.forWidth(width) == BgBreakpoint.expanded;
}

/// Deprecated. Use [BgSpace] (`UX_IA_SPEC.md` §7.2).
class DvSpace {
  const DvSpace._();

  static const double xxxl = BgSpace.xxxl;
  static const double bubbleClearance = BgSpace.bubbleClearance;
}

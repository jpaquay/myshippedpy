import 'package:flutter/widgets.dart';

/// Layout constants the Forge console needs from §4 / §7 of `docs/UX_IA_SPEC.md`
/// that `app_theme.dart` does not expose *yet*.
///
/// `BgBreak` (§4) and `BgSpace.bubbleClearance` (§7.2) are owned by the
/// design-system item, not by item 8, and the console may not edit
/// `app_theme.dart`. These mirrors carry the same numbers so nothing here
/// hard-codes a stray pixel; when the real tokens land, delete this file and
/// point the imports at `app_theme.dart`.
class ForgeMetrics {
  const ForgeMetrics._();

  /// `BgBreak.compact` — below this we are on a phone.
  static const double compactBreak = 600;

  /// `BgBreak.expanded` — at or above this we may use two/three columns.
  static const double expandedBreak = 900;

  /// `BgSpace.bubbleClearance` — bottom padding that keeps the future
  /// app-wide assistant bubble (§6.2) off the FORGE call to action.
  static const double bubbleClearance = 96;

  /// §5.3: "If an implementer's Guided mode is taller than 120 px, it is
  /// wrong." Asserted by `test/forge_console_modes_test.dart`.
  static const double guidedBodyBudget = 120;

  static bool isExpanded(BuildContext context) =>
      MediaQuery.sizeOf(context).width >= expandedBreak;

  static bool isCompact(BuildContext context) =>
      MediaQuery.sizeOf(context).width < compactBreak;
}

/// Keys used by the widget tests to measure what each mode renders.
class ForgeKeys {
  const ForgeKeys._();

  static const Key modeControl = Key('forge.console.modeControl');
  static const Key modeHelper = Key('forge.console.modeHelper');
  static const Key body = Key('forge.console.body');
  static const Key outcomeCard = Key('forge.console.outcome');
  static const Key cursorTemp = Key('forge.console.cursor.temp');
  static const Key cursorLight = Key('forge.console.cursor.light');
  static const Key cursorKelvin = Key('forge.console.cursor.kelvin');
  static const Key sliderPressure = Key('forge.console.slider.pressure');
  static const Key sliderTrend = Key('forge.console.slider.trend');
  static const Key sliderBpm = Key('forge.console.slider.bpm');
  static const Key telemetryRow = Key('forge.console.telemetry');
  static const Key whyTheseThree = Key('forge.console.whyTheseThree');
  static const Key coefficients = Key('forge.console.coefficients');
  static const Key sourceRequest = Key('forge.console.sourceRequest');
  static const Key skyStrip = Key('forge.sky.strip');
  static const Key skyDial = Key('forge.sky.dial');
  static const Key skyDetail = Key('forge.sky.detail');
}

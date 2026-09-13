import 'package:flutter/widgets.dart';

import '../../../app_theme.dart';

/// Console-local layout facts.
///
/// This used to mirror `BgBreak.compact` / `BgBreak.expanded` /
/// `BgSpace.bubbleClearance` by hand, because item 8 could not edit
/// `app_theme.dart` while item 12 owned it. Those tokens now exist for real and
/// the mirrors are gone: the console reads `BgBreak` and `BgSpace` directly.
///
/// What is left is one number that genuinely belongs to the console, plus one
/// alias that cannot be retired from here.
class ForgeMetrics {
  const ForgeMetrics._();

  /// §5.3: "If an implementer's Guided mode is taller than 120 px, it is
  /// wrong." Asserted by `test/forge_console_modes_test.dart`. Console-owned:
  /// it is an acceptance budget, not a design token.
  static const double guidedBodyBudget = 120;

  /// Deprecated alias for [BgSpace.bubbleClearance], kept only because its
  /// last call site (`home_screen.dart`) belongs to the assistant-overlay
  /// worker and could not be edited from here. It forwards rather than
  /// repeating 96, so the value cannot drift. Delete both together.
  static const double bubbleClearance = BgSpace.bubbleClearance;
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

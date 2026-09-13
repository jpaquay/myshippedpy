import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// BAROGROOVE's visual register.
///
/// The brief is an executive instrument panel, not a music app: slate,
/// sky blue, a restrained gold accent, high contrast, quiet. The reference
/// point is the EHDS portal — institutional, legible at a glance. Nothing
/// here glows.
///
/// **This file is the only place a colour, a font size, a padding, a radius
/// or a breakpoint may be declared.** Screens read them back through
/// [BgText], [BgSpace], [BgBreak] and `Theme.of(context).bg` ([BgColors]).
/// See `docs/UX_IA_SPEC.md` §7.
///
/// Theme palettes returned by `/api/themes` (petrichor, storm_front, …) *tint*
/// this surface via [BgTheme.tinted]; they never replace it. A theme can move
/// the accent and the faintest wash behind a card. It cannot make the app
/// purple. The A2UI renderer tints through the same entry point, so an
/// agent-described surface and hand-built chrome share one token set.
class BgPalette {
  const BgPalette._();

  // Slate — the structural colour. Text, chrome, borders.
  static const Color slate950 = Color(0xFF0B1220);
  static const Color slate900 = Color(0xFF0F172A);
  static const Color slate800 = Color(0xFF1E293B);
  static const Color slate700 = Color(0xFF334155);
  static const Color slate600 = Color(0xFF475569);
  static const Color slate500 = Color(0xFF64748B);
  static const Color slate400 = Color(0xFF94A3B8);
  static const Color slate300 = Color(0xFFCBD5E1);
  static const Color slate200 = Color(0xFFE2E8F0);
  static const Color slate100 = Color(0xFFF1F5F9);
  static const Color slate50 = Color(0xFFF8FAFC);

  // Sky — the primary. Used for interaction, never for decoration.
  static const Color sky700 = Color(0xFF0369A1);
  static const Color sky600 = Color(0xFF0284C7);
  static const Color sky500 = Color(0xFF0EA5E9);
  static const Color sky200 = Color(0xFFBAE6FD);
  static const Color sky50 = Color(0xFFF0F9FF);

  // Gold — the accent, rationed. Confidence marks, the hero rationale rule,
  // the "peak" track in a playlist. If it is everywhere it is nowhere.
  static const Color gold600 = Color(0xFFB45309);
  static const Color gold500 = Color(0xFFD97706);
  static const Color gold300 = Color(0xFFFCD34D);
  static const Color gold50 = Color(0xFFFFFBEB);

  // Semantics.
  static const Color danger = Color(0xFFB91C1C);
  static const Color warn = Color(0xFFB45309);
  static const Color ok = Color(0xFF047857);

  static const Color white = Color(0xFFFFFFFF);
}

/// Spacing and radius scale. Four-point grid.
///
/// Radius discipline: **nothing is rounder than 10** except [radiusSheet],
/// which is the grab-edge of a rung-2 bottom sheet and is the single documented
/// exemption (spec §7.2). `circular(20)` / `circular(16)` / `circular(14)` are
/// not tokens and must not reappear.
class BgSpace {
  const BgSpace._();
  static const double xxs = 2; // icon-to-label only
  static const double xs = 4;
  static const double sm = 8;
  static const double md = 12;
  static const double lg = 16;
  static const double xl = 24;
  static const double xxl = 32;
  static const double xxxl = 48; // destination bottom padding, empty states

  static const double radius = 10;
  static const double radiusSm = 6;

  /// The ONLY radius above 10. Sheet tops only.
  static const double radiusSheet = 16;

  /// Bottom padding every destination's scroll view must reserve so the
  /// floating assistant bubble never covers content (spec §6.2).
  static const double bubbleClearance = 96;

  /// Height of the floating mini-player, when visible. The assistant bubble
  /// stacks above it.
  static const double miniPlayerHeight = 64;

  static const BorderRadius br = BorderRadius.all(Radius.circular(radius));
  static const BorderRadius brSm = BorderRadius.all(Radius.circular(radiusSm));
  static const BorderRadius brSheet =
      BorderRadius.vertical(top: Radius.circular(radiusSheet));
}

/// Icon sizes. Spec §7.6: monochrome, outlined at rest, filled when selected.
class BgIcon {
  const BgIcon._();

  /// Header, menus, any app chrome. Nothing in the header is bigger.
  static const double chrome = 20;

  /// Inline with text, inside cards and rows.
  static const double inline = 18;

  /// Tab bar / navigation rail only.
  static const double nav = 24;

  /// The health pip's visual dot.
  static const double dot = 8;
}

/// The three — and only three — breakpoints (spec §4).
///
/// `shell.dart` used 900/600 and `dataviz_screen.dart` used 920. Unified here.
/// No screen may hard-code a pixel breakpoint again.
enum BgBreakpoint { compact, medium, expanded }

class BgBreak {
  const BgBreak._();

  /// Below this width: bottom `NavigationBar`, tight gutter, no header badges.
  static const double compact = 600;

  /// At or above this width: `NavigationRail`, header badges, two columns.
  static const double expanded = 900;

  static BgBreakpoint of(BuildContext context) =>
      forWidth(MediaQuery.sizeOf(context).width);

  static BgBreakpoint forWidth(double width) {
    if (width >= expanded) return BgBreakpoint.expanded;
    if (width >= compact) return BgBreakpoint.medium;
    return BgBreakpoint.compact;
  }

  /// `true` when the navigation rail replaces the bottom bar.
  static bool isExpanded(BuildContext context) =>
      of(context) == BgBreakpoint.expanded;

  /// `true` on phones. Kept as a named helper so nobody writes `< 600` again.
  static bool isCompact(BuildContext context) =>
      of(context) == BgBreakpoint.compact;

  /// Horizontal screen gutter: 12 on compact, 24 everywhere else.
  static double gutter(BuildContext context) =>
      isCompact(context) ? BgSpace.md : BgSpace.xl;

  /// Vertical rhythm between sections: 24 compact, 32 expanded.
  static double sectionGap(BuildContext context) =>
      of(context) == BgBreakpoint.expanded ? BgSpace.xxl : BgSpace.xl;

  /// The smallest phone we design for. Not a layout breakpoint — the one
  /// width at which a secondary line of copy is allowed to shorten.
  static const double narrowPhone = 390;

  /// Content column ceiling. Single-column pages cap at 720; the shell caps
  /// the whole content area at 1080.
  static const double readingMaxWidth = 720;
  static const double shellMaxWidth = 1080;

  /// Rung-1 disclosures default open on desktop and closed on phones.
  static bool disclosureDefaultOpen(BuildContext context) =>
      isExpanded(context);
}

/// Named colour roles (spec §7.3).
///
/// Screens stop reaching into [BgPalette] and ask the theme instead:
/// `Theme.of(context).bg.hairline`. Carried as a [ThemeExtension] so it
/// survives `copyWith`, so it is available to the A2UI renderer's generic
/// widgets, and so a tinted surface theme keeps every role but the accent.
@immutable
class BgColors extends ThemeExtension<BgColors> {
  const BgColors({
    required this.surfaceBase,
    required this.surfaceRaised,
    required this.surfaceSunken,
    required this.hairline,
    required this.inkPrimary,
    required this.inkSecondary,
    required this.inkTertiary,
    required this.accent,
    required this.onAccent,
    required this.accentWash,
    required this.markGold,
    required this.statusOk,
    required this.statusWarn,
    required this.statusDanger,
  });

  /// Page background.
  final Color surfaceBase;

  /// Cards, sheets, the assistant bubble.
  final Color surfaceRaised;

  /// Input fields, skeletons, chart plot areas.
  final Color surfaceSunken;

  /// 1 px separators and card borders. The primary structuring device.
  final Color hairline;

  /// Headings, values.
  final Color inkPrimary;

  /// Body, labels.
  final Color inkSecondary;

  /// Disabled, unlinked, placeholders.
  final Color inkTertiary;

  /// Interaction only — filled buttons, selected segment, focus ring.
  final Color accent;

  /// Text on [accent].
  final Color onAccent;

  /// The faintest possible selected-row tint. One per screen.
  final Color accentWash;

  /// Rationed. Never more than one gold element per viewport.
  final Color markGold;

  /// Only in the health sheet and the linked-badge dot. Never a header dot.
  final Color statusOk;
  final Color statusWarn;
  final Color statusDanger;

  /// A linked connection badge is monochrome — *not* green.
  Color get connected => inkPrimary;

  /// An unlinked connection badge.
  Color get disconnected => inkTertiary;

  static const BgColors _light = BgColors(
    surfaceBase: BgPalette.slate50,
    surfaceRaised: BgPalette.white,
    surfaceSunken: BgPalette.slate100,
    hairline: BgPalette.slate200,
    inkPrimary: BgPalette.slate900,
    inkSecondary: BgPalette.slate600,
    inkTertiary: BgPalette.slate400,
    accent: BgPalette.sky600,
    onAccent: BgPalette.white,
    accentWash: BgPalette.sky50,
    markGold: BgPalette.gold600,
    statusOk: BgPalette.ok,
    statusWarn: BgPalette.warn,
    statusDanger: BgPalette.danger,
  );

  static const BgColors _dark = BgColors(
    surfaceBase: BgPalette.slate900,
    surfaceRaised: BgPalette.slate800,
    surfaceSunken: BgPalette.slate950,
    hairline: BgPalette.slate700,
    inkPrimary: BgPalette.slate100,
    inkSecondary: BgPalette.slate400,
    inkTertiary: BgPalette.slate500,
    accent: BgPalette.sky500,
    onAccent: BgPalette.slate900,
    // sky700 @ 14 % (alpha 0x24) — a wash, not a fill. Dark mode separates
    // with hairlines, so the wash only has to be perceptible, not present.
    accentWash: Color(0x240369A1),
    markGold: BgPalette.gold500,
    statusOk: BgPalette.ok,
    statusWarn: BgPalette.warn,
    statusDanger: BgPalette.danger,
  );

  static BgColors forBrightness(Brightness brightness) =>
      brightness == Brightness.light ? _light : _dark;

  @override
  BgColors copyWith({
    Color? surfaceBase,
    Color? surfaceRaised,
    Color? surfaceSunken,
    Color? hairline,
    Color? inkPrimary,
    Color? inkSecondary,
    Color? inkTertiary,
    Color? accent,
    Color? onAccent,
    Color? accentWash,
    Color? markGold,
    Color? statusOk,
    Color? statusWarn,
    Color? statusDanger,
  }) {
    return BgColors(
      surfaceBase: surfaceBase ?? this.surfaceBase,
      surfaceRaised: surfaceRaised ?? this.surfaceRaised,
      surfaceSunken: surfaceSunken ?? this.surfaceSunken,
      hairline: hairline ?? this.hairline,
      inkPrimary: inkPrimary ?? this.inkPrimary,
      inkSecondary: inkSecondary ?? this.inkSecondary,
      inkTertiary: inkTertiary ?? this.inkTertiary,
      accent: accent ?? this.accent,
      onAccent: onAccent ?? this.onAccent,
      accentWash: accentWash ?? this.accentWash,
      markGold: markGold ?? this.markGold,
      statusOk: statusOk ?? this.statusOk,
      statusWarn: statusWarn ?? this.statusWarn,
      statusDanger: statusDanger ?? this.statusDanger,
    );
  }

  @override
  BgColors lerp(ThemeExtension<BgColors>? other, double t) {
    if (other is! BgColors) return this;
    Color mix(Color a, Color b) => Color.lerp(a, b, t) ?? a;
    return BgColors(
      surfaceBase: mix(surfaceBase, other.surfaceBase),
      surfaceRaised: mix(surfaceRaised, other.surfaceRaised),
      surfaceSunken: mix(surfaceSunken, other.surfaceSunken),
      hairline: mix(hairline, other.hairline),
      inkPrimary: mix(inkPrimary, other.inkPrimary),
      inkSecondary: mix(inkSecondary, other.inkSecondary),
      inkTertiary: mix(inkTertiary, other.inkTertiary),
      accent: mix(accent, other.accent),
      onAccent: mix(onAccent, other.onAccent),
      accentWash: mix(accentWash, other.accentWash),
      markGold: mix(markGold, other.markGold),
      statusOk: mix(statusOk, other.statusOk),
      statusWarn: mix(statusWarn, other.statusWarn),
      statusDanger: mix(statusDanger, other.statusDanger),
    );
  }
}

/// `Theme.of(context).bg.hairline` — the ergonomic way to reach a colour role.
extension BgThemeRoles on ThemeData {
  BgColors get bg =>
      extension<BgColors>() ?? BgColors.forBrightness(brightness);
}

/// Type scale aliases (spec §7.1). One name per role, so a screen never has to
/// remember whether a card title is `titleLarge` or `headlineSmall`.
///
/// Hard rules enforced by the scale itself: no fractional sizes, nothing above
/// 24 on the five destinations ([hero] is the sign-in screen only), and exactly
/// two weights in product chrome — w400 and w600. w500 is reserved for [meta];
/// w700 is banned.
class BgText {
  const BgText._();

  /// 34 / w600. **Sign-in screen only.** Banned on the five destinations.
  static TextStyle? hero(BuildContext c) => Theme.of(c).textTheme.displaySmall;

  /// 24 / w600. The one H1 per destination.
  static TextStyle? screenTitle(BuildContext c) =>
      Theme.of(c).textTheme.headlineMedium;

  /// 20 / w600.
  static TextStyle? sectionTitle(BuildContext c) =>
      Theme.of(c).textTheme.headlineSmall;

  /// 18 / w600.
  static TextStyle? cardTitle(BuildContext c) =>
      Theme.of(c).textTheme.titleLarge;

  /// 15 / w600.
  static TextStyle? rowTitle(BuildContext c) =>
      Theme.of(c).textTheme.titleMedium;

  /// 13 / w600, muted.
  static TextStyle? rowSubtitle(BuildContext c) =>
      Theme.of(c).textTheme.titleSmall;

  /// 16 / w400. Rationale prose only.
  static TextStyle? bodyLead(BuildContext c) => Theme.of(c).textTheme.bodyLarge;

  /// 14 / w400.
  static TextStyle? body(BuildContext c) => Theme.of(c).textTheme.bodyMedium;

  /// 13 / w400, muted.
  static TextStyle? caption(BuildContext c) => Theme.of(c).textTheme.bodySmall;

  /// 14 / w600. Buttons.
  static TextStyle? action(BuildContext c) => Theme.of(c).textTheme.labelLarge;

  /// 12 / w500. Badges, chips, receipts.
  static TextStyle? meta(BuildContext c) => Theme.of(c).textTheme.labelMedium;

  /// 11 / w600 / +0.9. UPPERCASE by convention.
  static TextStyle? eyebrow(BuildContext c) =>
      Theme.of(c).textTheme.labelSmall;

  /// Tabular figures, so a value does not shift as it updates. Wrap any KPI,
  /// telemetry counter or chart label.
  static TextStyle numeric(TextStyle? base) =>
      (base ?? const TextStyle()).copyWith(
        fontFeatures: const <FontFeature>[FontFeature.tabularFigures()],
      );
}

class BgTheme {
  const BgTheme._();

  /// System UI overlay matching the light surface.
  static const SystemUiOverlayStyle lightOverlay = SystemUiOverlayStyle(
    statusBarColor: Colors.transparent,
    statusBarIconBrightness: Brightness.dark,
    statusBarBrightness: Brightness.light,
  );

  static ThemeData light({Color? accent}) =>
      _build(Brightness.light, accent ?? BgPalette.sky600);

  static ThemeData dark({Color? accent}) =>
      _build(Brightness.dark, accent ?? BgPalette.sky500);

  /// Applies a theme palette from `/api/themes` as a tint over the base
  /// scheme. The palette supplies a primary hex; we keep slate typography and
  /// slate chrome so the app stays in register.
  ///
  /// The [BgColors] extension is carried forward with only [BgColors.accent]
  /// and [BgColors.accentWash] moved — an A2UI surface cannot acquire a private
  /// palette by way of a tint.
  static ThemeData tinted(ThemeData base, Color accent) {
    final ColorScheme scheme = base.colorScheme.copyWith(
      primary: accent,
      secondary: accent,
    );
    final BgColors roles = base.bg.copyWith(
      accent: accent,
      accentWash: accent.withValues(alpha: 0.12),
    );
    return base.copyWith(
      colorScheme: scheme,
      extensions: <ThemeExtension<dynamic>>[roles],
      // Deliberately narrow: we recolour interaction affordances only.
      // Backgrounds, text and dividers stay slate.
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(backgroundColor: accent),
      ),
      progressIndicatorTheme: ProgressIndicatorThemeData(color: accent),
    );
  }

  static ThemeData _build(Brightness brightness, Color accent) {
    final bool isLight = brightness == Brightness.light;
    final BgColors roles =
        BgColors.forBrightness(brightness).copyWith(accent: accent);

    final ColorScheme scheme = ColorScheme(
      brightness: brightness,
      primary: accent,
      onPrimary: roles.onAccent,
      primaryContainer: isLight ? BgPalette.sky50 : BgPalette.slate800,
      onPrimaryContainer: isLight ? BgPalette.sky700 : BgPalette.sky200,
      secondary: roles.markGold,
      onSecondary: isLight ? BgPalette.white : BgPalette.slate900,
      secondaryContainer: isLight ? BgPalette.gold50 : BgPalette.slate800,
      onSecondaryContainer: isLight ? BgPalette.gold600 : BgPalette.gold300,
      error: roles.statusDanger,
      onError: BgPalette.white,
      surface: roles.surfaceRaised,
      onSurface: roles.inkPrimary,
      surfaceContainerLowest: roles.surfaceSunken,
      surfaceContainerLow: roles.surfaceBase,
      surfaceContainer: isLight ? BgPalette.slate100 : BgPalette.slate800,
      surfaceContainerHigh: isLight ? BgPalette.slate200 : BgPalette.slate700,
      surfaceContainerHighest:
          isLight ? BgPalette.slate200 : BgPalette.slate700,
      onSurfaceVariant: roles.inkSecondary,
      outline: isLight ? BgPalette.slate300 : BgPalette.slate700,
      outlineVariant: roles.hairline,
      inverseSurface: isLight ? BgPalette.slate900 : BgPalette.slate100,
      onInverseSurface: isLight ? BgPalette.slate50 : BgPalette.slate900,
      // Dark mode raises surfaces with a hairline, not with elevation, so
      // there is nothing for a shadow to do (spec §7.3.4).
      shadow: isLight ? const Color(0x14000000) : Colors.transparent,
      scrim: const Color(0x66000000),
    );

    final Color ink = roles.inkPrimary;
    final Color muted = roles.inkSecondary;

    // Typography: confident and quiet. Tight tracking on display sizes,
    // generous line height on body copy — the rationale card is long-form and
    // has to be genuinely readable, not decorative. Whole numbers only.
    final TextTheme text = TextTheme(
      displaySmall: TextStyle(
        fontSize: 34,
        height: 1.15,
        fontWeight: FontWeight.w600,
        letterSpacing: -0.8,
        color: ink,
      ),
      headlineMedium: TextStyle(
        fontSize: 24,
        height: 1.2,
        fontWeight: FontWeight.w600,
        letterSpacing: -0.5,
        color: ink,
      ),
      headlineSmall: TextStyle(
        fontSize: 20,
        height: 1.25,
        fontWeight: FontWeight.w600,
        letterSpacing: -0.3,
        color: ink,
      ),
      titleLarge: TextStyle(
        fontSize: 18,
        height: 1.3,
        fontWeight: FontWeight.w600,
        letterSpacing: -0.2,
        color: ink,
      ),
      titleMedium: TextStyle(
        fontSize: 15,
        height: 1.35,
        fontWeight: FontWeight.w600,
        color: ink,
      ),
      titleSmall: TextStyle(
        fontSize: 13,
        height: 1.35,
        fontWeight: FontWeight.w600,
        color: muted,
      ),
      bodyLarge: TextStyle(fontSize: 16, height: 1.55, color: ink),
      bodyMedium: TextStyle(fontSize: 14, height: 1.55, color: ink),
      bodySmall: TextStyle(fontSize: 13, height: 1.5, color: muted),
      labelLarge: TextStyle(
        fontSize: 14,
        height: 1.2,
        fontWeight: FontWeight.w600,
        letterSpacing: 0.1,
        color: ink,
      ),
      // Badges, chips, receipts. The one w500 in the scale.
      labelMedium: TextStyle(
        fontSize: 12,
        height: 1.3,
        fontWeight: FontWeight.w500,
        letterSpacing: 0.2,
        color: muted,
      ),
      // Small caps-ish label used for axis names and section eyebrows.
      labelSmall: TextStyle(
        fontSize: 11,
        height: 1.2,
        fontWeight: FontWeight.w600,
        letterSpacing: 0.9,
        color: muted,
      ),
    );

    return ThemeData(
      useMaterial3: true,
      brightness: brightness,
      colorScheme: scheme,
      extensions: <ThemeExtension<dynamic>>[roles],
      scaffoldBackgroundColor: roles.surfaceBase,
      textTheme: text,
      splashFactory: InkSparkle.splashFactory,
      // Chrome icons are monochrome and never larger than 20 (spec §7.6).
      iconTheme: IconThemeData(size: BgIcon.chrome, color: muted),
      dividerTheme: DividerThemeData(
        color: roles.hairline,
        thickness: 1,
        space: 1,
      ),
      appBarTheme: AppBarTheme(
        backgroundColor: scheme.surface,
        surfaceTintColor: Colors.transparent,
        foregroundColor: ink,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
        titleTextStyle: text.titleLarge,
        iconTheme: IconThemeData(size: BgIcon.chrome, color: muted),
        actionsIconTheme: IconThemeData(size: BgIcon.chrome, color: muted),
        shape: Border(bottom: BorderSide(color: roles.hairline)),
      ),
      cardTheme: CardThemeData(
        color: roles.surfaceRaised,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BgSpace.br,
          side: BorderSide(color: roles.hairline),
        ),
      ),
      chipTheme: ChipThemeData(
        backgroundColor: scheme.surface,
        selectedColor: roles.accentWash,
        side: BorderSide(color: scheme.outline),
        labelStyle: text.labelLarge,
        shape: const RoundedRectangleBorder(borderRadius: BgSpace.brSm),
        showCheckmark: false,
        padding: const EdgeInsets.symmetric(
          horizontal: BgSpace.md,
          vertical: BgSpace.sm,
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: scheme.primary,
          foregroundColor: scheme.onPrimary,
          textStyle: text.labelLarge,
          padding: const EdgeInsets.symmetric(
            horizontal: BgSpace.xl,
            vertical: BgSpace.lg,
          ),
          shape: const RoundedRectangleBorder(borderRadius: BgSpace.brSm),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: ink,
          side: BorderSide(color: scheme.outline),
          textStyle: text.labelLarge,
          padding: const EdgeInsets.symmetric(
            horizontal: BgSpace.lg,
            vertical: BgSpace.md,
          ),
          shape: const RoundedRectangleBorder(borderRadius: BgSpace.brSm),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: scheme.primary,
          textStyle: text.labelLarge,
        ),
      ),
      segmentedButtonTheme: SegmentedButtonThemeData(
        style: SegmentedButton.styleFrom(
          // Selection is a wash plus an accent label, never a filled block.
          backgroundColor: roles.surfaceRaised,
          foregroundColor: muted,
          selectedBackgroundColor: roles.accentWash,
          selectedForegroundColor: scheme.primary,
          side: BorderSide(color: roles.hairline),
          textStyle: text.labelLarge,
          shape: const RoundedRectangleBorder(borderRadius: BgSpace.brSm),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: roles.surfaceSunken,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: BgSpace.lg,
          vertical: BgSpace.md,
        ),
        border: OutlineInputBorder(
          borderRadius: BgSpace.brSm,
          borderSide: BorderSide(color: scheme.outline),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BgSpace.brSm,
          borderSide: BorderSide(color: scheme.outline),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BgSpace.brSm,
          borderSide: BorderSide(color: scheme.primary, width: 1.6),
        ),
      ),
      bottomSheetTheme: BottomSheetThemeData(
        backgroundColor: roles.surfaceRaised,
        surfaceTintColor: Colors.transparent,
        modalBackgroundColor: roles.surfaceRaised,
        elevation: 0,
        modalElevation: 0,
        showDragHandle: true,
        shape: const RoundedRectangleBorder(borderRadius: BgSpace.brSheet),
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: roles.surfaceRaised,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BgSpace.br,
          side: BorderSide(color: roles.hairline),
        ),
      ),
      navigationRailTheme: NavigationRailThemeData(
        backgroundColor: scheme.surface,
        indicatorColor: roles.accentWash,
        selectedIconTheme:
            IconThemeData(size: BgIcon.nav, color: scheme.primary),
        unselectedIconTheme: IconThemeData(size: BgIcon.nav, color: muted),
        selectedLabelTextStyle: text.labelLarge,
        unselectedLabelTextStyle: text.bodySmall,
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: scheme.surface,
        surfaceTintColor: Colors.transparent,
        indicatorColor: roles.accentWash,
        elevation: 0,
        iconTheme: WidgetStateProperty.resolveWith<IconThemeData>(
          (Set<WidgetState> states) => IconThemeData(
            size: BgIcon.nav,
            color:
                states.contains(WidgetState.selected) ? scheme.primary : muted,
          ),
        ),
        labelTextStyle: WidgetStatePropertyAll<TextStyle?>(text.labelSmall),
      ),
      tooltipTheme: TooltipThemeData(
        decoration: BoxDecoration(
          color: scheme.inverseSurface,
          borderRadius: BgSpace.brSm,
        ),
        textStyle: TextStyle(
          color: scheme.onInverseSurface,
          fontSize: 12,
          height: 1.3,
        ),
      ),
      snackBarTheme: SnackBarThemeData(
        backgroundColor: scheme.inverseSurface,
        contentTextStyle: TextStyle(color: scheme.onInverseSurface),
        behavior: SnackBarBehavior.floating,
        shape: const RoundedRectangleBorder(borderRadius: BgSpace.brSm),
      ),
    );
  }

  /// Parses a `#RRGGBB` (or `#AARRGGBB`) hex string from a theme palette.
  /// Returns [fallback] on anything malformed — a bad palette must not be
  /// able to crash the app.
  static Color parseHex(String? hex, {Color fallback = BgPalette.sky600}) {
    if (hex == null) return fallback;
    var s = hex.trim().replaceFirst('#', '');
    if (s.length == 6) s = 'FF$s';
    if (s.length != 8) return fallback;
    final int? value = int.tryParse(s, radix: 16);
    return value == null ? fallback : Color(value);
  }
}

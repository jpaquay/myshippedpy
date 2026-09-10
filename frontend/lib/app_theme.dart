import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// BAROGROOVE's visual register.
///
/// The brief is an executive instrument panel, not a music app: slate,
/// sky blue, a restrained gold accent, high contrast, light mode by default.
/// The reference point is the EHDS portal — institutional, quiet, legible at
/// a glance. Nothing here glows.
///
/// Theme palettes returned by `/api/themes` (petrichor, storm_front, …) *tint*
/// this surface via [BgTheme.tinted]; they never replace it. A theme can move
/// the accent and the faintest wash behind a card. It cannot make the app
/// purple.
class BgPalette {
  const BgPalette._();

  // Slate — the structural colour. Text, chrome, borders.
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

/// Spacing and radius scale. Four-point grid; nothing rounder than 10.
class BgSpace {
  const BgSpace._();
  static const double xs = 4;
  static const double sm = 8;
  static const double md = 12;
  static const double lg = 16;
  static const double xl = 24;
  static const double xxl = 32;

  static const double radius = 10;
  static const double radiusSm = 6;
  static const BorderRadius br = BorderRadius.all(Radius.circular(radius));
  static const BorderRadius brSm = BorderRadius.all(Radius.circular(radiusSm));
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
  static ThemeData tinted(ThemeData base, Color accent) {
    final ColorScheme scheme = base.colorScheme.copyWith(
      primary: accent,
      secondary: accent,
    );
    return base.copyWith(
      colorScheme: scheme,
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

    final ColorScheme scheme = ColorScheme(
      brightness: brightness,
      primary: accent,
      onPrimary: BgPalette.white,
      primaryContainer: isLight ? BgPalette.sky50 : BgPalette.slate800,
      onPrimaryContainer: isLight ? BgPalette.sky700 : BgPalette.sky200,
      secondary: BgPalette.gold600,
      onSecondary: BgPalette.white,
      secondaryContainer: isLight ? BgPalette.gold50 : BgPalette.slate800,
      onSecondaryContainer: isLight ? BgPalette.gold600 : BgPalette.gold300,
      error: BgPalette.danger,
      onError: BgPalette.white,
      surface: isLight ? BgPalette.white : BgPalette.slate900,
      onSurface: isLight ? BgPalette.slate900 : BgPalette.slate100,
      surfaceContainerLowest: isLight ? BgPalette.white : const Color(0xFF0B1220),
      surfaceContainerLow: isLight ? BgPalette.slate50 : BgPalette.slate900,
      surfaceContainer: isLight ? BgPalette.slate100 : BgPalette.slate800,
      surfaceContainerHigh: isLight ? BgPalette.slate200 : BgPalette.slate700,
      surfaceContainerHighest: isLight ? BgPalette.slate200 : BgPalette.slate700,
      onSurfaceVariant: isLight ? BgPalette.slate600 : BgPalette.slate400,
      outline: isLight ? BgPalette.slate300 : BgPalette.slate700,
      outlineVariant: isLight ? BgPalette.slate200 : BgPalette.slate800,
      inverseSurface: isLight ? BgPalette.slate900 : BgPalette.slate100,
      onInverseSurface: isLight ? BgPalette.slate50 : BgPalette.slate900,
      shadow: const Color(0x14000000),
      scrim: const Color(0x66000000),
    );

    final Color ink = scheme.onSurface;
    final Color muted = scheme.onSurfaceVariant;

    // Typography: confident and quiet. Tight tracking on display sizes,
    // generous line height on body copy — the rationale card is long-form and
    // has to be genuinely readable, not decorative.
    final TextTheme text = TextTheme(
      displaySmall: TextStyle(
        fontSize: 34,
        height: 1.15,
        fontWeight: FontWeight.w600,
        letterSpacing: -0.8,
        color: ink,
      ),
      headlineMedium: TextStyle(
        fontSize: 26,
        height: 1.2,
        fontWeight: FontWeight.w600,
        letterSpacing: -0.5,
        color: ink,
      ),
      headlineSmall: TextStyle(
        fontSize: 21,
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
      bodyMedium: TextStyle(fontSize: 14.5, height: 1.55, color: ink),
      bodySmall: TextStyle(fontSize: 13, height: 1.5, color: muted),
      labelLarge: TextStyle(
        fontSize: 14,
        height: 1.2,
        fontWeight: FontWeight.w600,
        letterSpacing: 0.1,
        color: ink,
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
      scaffoldBackgroundColor: scheme.surfaceContainerLow,
      textTheme: text,
      splashFactory: InkSparkle.splashFactory,
      dividerTheme: DividerThemeData(
        color: scheme.outlineVariant,
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
        shape: Border(bottom: BorderSide(color: scheme.outlineVariant)),
      ),
      cardTheme: CardThemeData(
        color: scheme.surface,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BgSpace.br,
          side: BorderSide(color: scheme.outlineVariant),
        ),
      ),
      chipTheme: ChipThemeData(
        backgroundColor: scheme.surface,
        selectedColor: scheme.primaryContainer,
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
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: scheme.surface,
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
      navigationRailTheme: NavigationRailThemeData(
        backgroundColor: scheme.surface,
        indicatorColor: scheme.primaryContainer,
        selectedLabelTextStyle: text.labelLarge,
        unselectedLabelTextStyle: text.bodySmall,
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: scheme.surface,
        surfaceTintColor: Colors.transparent,
        indicatorColor: scheme.primaryContainer,
        elevation: 0,
        labelTextStyle: WidgetStatePropertyAll<TextStyle?>(text.labelSmall),
      ),
      tooltipTheme: TooltipThemeData(
        decoration: BoxDecoration(
          color: scheme.inverseSurface,
          borderRadius: BgSpace.brSm,
        ),
        textStyle: TextStyle(color: scheme.onInverseSurface, fontSize: 12.5),
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

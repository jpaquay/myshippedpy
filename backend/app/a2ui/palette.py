"""BAROGROOVE design tokens: the base surface properties and the eight theme tints.

HOUSE STYLE (non-negotiable)
----------------------------
Professional, executive-level, high-contrast, clean -- the register of the EHDS
(European Health Data Space) portal.  Slate structure, Sky Blue action, subtle
Gold as the *rare* accent.  LIGHT MODE IS THE DEFAULT.  Explicitly NOT neon: a
theme may tint the accent and the canvas, but it may never leave this house.

The eight themes are weather *states*, not genres -- the genre corridor is an
orthogonal axis (see :mod:`app.a2ui.catalog`).  "Petrichor x krautrock" is a
crossing of two independent knobs, and the palette exists to make the theme axis
legible at a glance without shouting.

CONTRAST
--------
Every theme declares four pairs that are asserted to clear WCAG 2.1 AA:
  ink/canvas and ink/surface at >= 7.0 (AAA body text -- this is a data product,
  people read the rationale), accent/surface and accentInk/accentSoft at >= 4.5.
:func:`contrast_ratio` and :func:`audit_palettes` are exported so the test suite
and any downstream renderer can re-check rather than trust a comment.

A2UI mapping
------------
:data:`SURFACE_PROPERTIES` is what goes into ``createSurface.surfaceProperties``
(v1.0's rename of ``theme``).  Per the v1.0 evolution guide, custom *primary brand
colours* are no longer part of the surface schema, so we ship the palette as
plain token maps under our own namespaced keys rather than trying to reuse a
removed ``primaryColor`` field.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "BASE",
    "TYPOGRAPHY",
    "SPACING",
    "RADIUS",
    "ELEVATION",
    "MOTION",
    "THEME_PALETTES",
    "THEME_IDS",
    "PALETTE_KEYS",
    "CONTRAST_PAIRS",
    "SURFACE_PROPERTIES",
    "surface_properties_for",
    "contrast_ratio",
    "relative_luminance",
    "audit_palettes",
    "is_hex",
]

# --------------------------------------------------------------------------- #
# Base tokens -- the neutral chassis every theme tints
# --------------------------------------------------------------------------- #

BASE: Final[dict[str, str]] = {
    # Structure: cool slate, never grey-brown.
    "canvas": "#F5F7FA",  # page background, a hair off white so cards read as cards
    "surface": "#FFFFFF",  # card / panel
    "surfaceSunken": "#EDF1F6",  # wells, table stripes, inactive chips
    "surfaceRaised": "#FFFFFF",
    "border": "#CBD5E1",  # slate-300 hairlines
    "borderStrong": "#94A3B8",  # slate-400, focus rings and axis lines
    # Ink: near-black slate for maximum legibility of long-form rationale text.
    "ink": "#0F172A",  # 17.4:1 on white
    "inkMuted": "#475569",  # 7.4:1 on white -- still AAA, used for secondary copy
    "inkSubtle": "#64748B",  # 4.8:1 on white -- labels/units only, never body text
    "inkInverse": "#FFFFFF",
    # Action: EHDS sky blue.  One blue, used consistently, never decoratively.
    "accent": "#0369A1",
    "accentStrong": "#075985",
    "accentSoft": "#E0F2FE",
    "accentInk": "#0C4A6E",  # text on accentSoft
    "onAccent": "#FFFFFF",  # text on accent
    # Gold: the restraint token.  Reserved for "this is the answer" moments --
    # the rationale headline rule and the peak track badge.  Nothing else.
    "gold": "#A16207",
    "goldSoft": "#FEF3C7",
    "goldInk": "#713F12",
    # Semantics.
    "positive": "#15803D",
    "warning": "#B45309",
    "critical": "#B91C1C",
    "criticalSoft": "#FEE2E2",
    "criticalInk": "#7F1D1D",
    # Data-viz ramp for the SkyDial: cold -> neutral -> warm, colour-blind safe,
    # all readable as small marks on `surface`.
    "dataCold": "#1D4ED8",
    "dataCool": "#0369A1",
    "dataNeutral": "#64748B",
    "dataWarm": "#A16207",
    "dataHot": "#B45309",
}

TYPOGRAPHY: Final[dict[str, object]] = {
    "fontFamily": "Inter, 'IBM Plex Sans', 'Segoe UI', system-ui, sans-serif",
    "fontFamilyMono": "'IBM Plex Mono', 'SF Mono', ui-monospace, monospace",
    # A tight 1.2 modular scale; display sizes exist for exactly two things --
    # the rationale headline and the SkyDial hero readout.
    "scale": {
        "display": {"size": 34, "lineHeight": 40, "weight": 650, "tracking": -0.6},
        "title": {"size": 24, "lineHeight": 30, "weight": 620, "tracking": -0.3},
        "heading": {"size": 18, "lineHeight": 24, "weight": 600, "tracking": -0.1},
        "body": {"size": 15, "lineHeight": 23, "weight": 400, "tracking": 0.0},
        "bodyStrong": {"size": 15, "lineHeight": 23, "weight": 600, "tracking": 0.0},
        "caption": {"size": 13, "lineHeight": 18, "weight": 500, "tracking": 0.1},
        "label": {"size": 11, "lineHeight": 14, "weight": 650, "tracking": 0.8},
        "numeric": {"size": 15, "lineHeight": 20, "weight": 550, "tracking": 0.0},
    },
    #: Sky dimensions are numbers that must be comparable down a column.
    "tabularNumerals": True,
}

#: 4pt base grid.  Executive density: generous around the hero, tight in lists.
SPACING: Final[dict[str, int]] = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 24,
    "xxl": 32,
    "section": 40,
}

RADIUS: Final[dict[str, int]] = {
    "sm": 4,
    "md": 8,
    "lg": 12,
    "pill": 999,
}

#: Shadows are hairline-plus-lift, never glow.  High contrast comes from the
#: border, not from the shadow.
ELEVATION: Final[dict[str, str]] = {
    "flat": "none",
    "card": "0 1px 2px rgba(15, 23, 42, 0.06), 0 0 0 1px rgba(15, 23, 42, 0.06)",
    "hero": "0 2px 8px rgba(15, 23, 42, 0.08), 0 0 0 1px rgba(15, 23, 42, 0.08)",
    "overlay": "0 12px 32px rgba(15, 23, 42, 0.16)",
}

MOTION: Final[dict[str, object]] = {
    "durationFast": 120,
    "durationBase": 200,
    "durationSlow": 320,
    "easing": "cubic-bezier(0.2, 0, 0, 1)",
    #: The dial animates its needle; nothing else is allowed to move on load.
    "respectsReducedMotion": True,
}

#: Every theme palette declares exactly these keys, so a renderer can switch
#: themes by swapping one map with no undefined lookups.
PALETTE_KEYS: Final[tuple[str, ...]] = (
    "canvas",
    "surface",
    "surfaceSunken",
    "border",
    "ink",
    "inkMuted",
    "accent",
    "accentSoft",
    "accentInk",
    "onAccent",
    "gold",
    "goldSoft",
    "goldInk",
)

#: (foreground, background, minimum ratio) asserted for every theme.
CONTRAST_PAIRS: Final[tuple[tuple[str, str, float], ...]] = (
    ("ink", "canvas", 7.0),
    ("ink", "surface", 7.0),
    ("inkMuted", "surface", 4.5),
    ("accent", "surface", 4.5),
    ("onAccent", "accent", 4.5),
    ("accentInk", "accentSoft", 4.5),
    ("goldInk", "goldSoft", 4.5),
)


# --------------------------------------------------------------------------- #
# The eight theme tints
# --------------------------------------------------------------------------- #
#
# Each theme keeps the slate ink and the white surface -- only the canvas wash,
# the accent hue and the soft fills move.  That is deliberate: the user should
# feel the weather without ever losing the executive register, and a screenshot
# of any two themes side by side should still look like the same product.

THEME_PALETTES: Final[dict[str, dict[str, str]]] = {
    # Falling pressure, rain arriving on warm stone.  The signature theme.
    # Wet slate-green accent: damp, not gloomy.
    "petrichor": {
        **BASE,
        "canvas": "#F1F5F4",
        "surfaceSunken": "#E4EDEA",
        "border": "#C2D4CE",
        "accent": "#0F6656",
        "accentStrong": "#0B4A3E",
        "accentSoft": "#DCF0EA",
        "accentInk": "#0A3F35",
        "gold": "#8A6A12",
        "goldSoft": "#F7EDD3",
        "goldInk": "#5C4409",
    },
    # First hard frost: clear, low sun, air like glass.  Coldest blue we allow.
    "first_frost": {
        **BASE,
        "canvas": "#F2F6FB",
        "surfaceSunken": "#E6EDF7",
        "border": "#C4D3E6",
        "accent": "#1D4ED8",
        "accentStrong": "#1E3A8A",
        "accentSoft": "#DDE7FE",
        "accentInk": "#1E3A8A",
        "gold": "#94660B",
        "goldSoft": "#FBEED0",
        "goldInk": "#653F05",
    },
    # Stable high, deep clear sky, nothing happening and that IS the story.
    # This is the house palette, unmodified -- the baseline other themes bend from.
    "high_pressure_blue": {
        **BASE,
    },
    # Gust variance spiking, pressure collapsing.  Urgent without being an alarm:
    # a hard indigo, and the only theme where the semantic warning colour is
    # allowed near the accent.
    "gale_warning": {
        **BASE,
        "canvas": "#F4F4F8",
        "surfaceSunken": "#E9E9F2",
        "border": "#CACAD9",
        "accent": "#4338CA",
        "accentStrong": "#312E81",
        "accentSoft": "#E4E1FB",
        "accentInk": "#312E81",
        "gold": "#9A5B08",
        "goldSoft": "#FBE9CF",
        "goldInk": "#6B3D04",
    },
    # Sun elevation low, golden-hour proximity high.  The one theme where gold
    # leads -- still a bronze-gold, never a highlighter yellow.
    "golden_hour": {
        **BASE,
        "canvas": "#FAF7F1",
        "surfaceSunken": "#F3ECE0",
        "border": "#DDD0BA",
        "accent": "#9A5B08",
        "accentStrong": "#6B3D04",
        "accentSoft": "#FAEBD3",
        "accentInk": "#6B3D04",
        "gold": "#8A6A12",
        "goldSoft": "#F7EDD3",
        "goldInk": "#5C4409",
    },
    # Deep cloud depth, flat pressure, no light.  Lowest-chroma theme; carries
    # its weight with typography rather than colour.
    "blanket_grey": {
        **BASE,
        "canvas": "#F4F5F6",
        "surfaceSunken": "#EAECEE",
        "border": "#CDD2D7",
        "accent": "#3F5566",
        "accentStrong": "#2B3B47",
        "accentSoft": "#E5EAEE",
        "accentInk": "#2B3B47",
        "gold": "#8A6A12",
        "goldSoft": "#F5EEDC",
        "goldInk": "#5C4409",
    },
    # Temperature far above norm, sun high, air standing still.  Warm canvas,
    # burnt-red accent, deliberately dry rather than tropical.
    "heat_shimmer": {
        **BASE,
        "canvas": "#FBF6F3",
        "surfaceSunken": "#F4E9E3",
        "border": "#E0CBC0",
        "accent": "#A03A1E",
        "accentStrong": "#7A2A14",
        "accentSoft": "#FBE5DC",
        "accentInk": "#7A2A14",
        "gold": "#8A6A12",
        "goldSoft": "#F8EED6",
        "goldInk": "#5C4409",
    },
    # Daylight delta shrinking fast; the long autumn dusk.  Muted violet-slate,
    # the most reflective of the eight.
    "long_dusk": {
        **BASE,
        "canvas": "#F7F5FA",
        "surfaceSunken": "#EEEAF4",
        "border": "#D4CCE2",
        "accent": "#6D28A8",
        "accentStrong": "#4C1D80",
        "accentSoft": "#EFE3FA",
        "accentInk": "#4C1D80",
        "gold": "#8A6A12",
        "goldSoft": "#F6EDD6",
        "goldInk": "#5C4409",
    },
}

#: Stable, ordered theme ids.  The ThemeChips component renders them in this order.
THEME_IDS: Final[tuple[str, ...]] = (
    "petrichor",
    "first_frost",
    "high_pressure_blue",
    "gale_warning",
    "golden_hour",
    "blanket_grey",
    "heat_shimmer",
    "long_dusk",
)

#: Human-facing one-liners, kept next to the colours so the intent travels with
#: the tint.  ``app.sonic.themes`` owns the authoritative Theme objects; these are
#: only used when that module is unavailable (see the surfaces router).
THEME_INTENT: Final[dict[str, str]] = {
    "petrichor": "Pressure is falling and rain is close. Wet slate-green, held low.",
    "first_frost": "Clear, cold and bright. The coldest blue in the system.",
    "high_pressure_blue": "A settled high. The unmodified house palette.",
    "gale_warning": "Gusts spiking, pressure collapsing. Urgent, not alarming.",
    "golden_hour": "Sun low, light long. The one theme where gold leads.",
    "blanket_grey": "Deep cloud, flat pressure. Lowest chroma; typography carries it.",
    "heat_shimmer": "Far above the norm, air standing still. Dry heat, not tropics.",
    "long_dusk": "Daylight shrinking fast. Muted violet-slate, reflective.",
}


# --------------------------------------------------------------------------- #
# surfaceProperties
# --------------------------------------------------------------------------- #

SURFACE_PROPERTIES: Final[dict[str, object]] = {
    "colorScheme": "light",  # light mode is the default, always
    "contrast": "high",
    "density": "comfortable",
    "palette": dict(BASE),
    "typography": TYPOGRAPHY,
    "spacing": dict(SPACING),
    "radius": dict(RADIUS),
    "elevation": dict(ELEVATION),
    "motion": MOTION,
}


def surface_properties_for(theme_id: str | None = None) -> dict[str, object]:
    """``createSurface.surfaceProperties`` for a theme (or the house default).

    Unknown theme ids fall back to the base palette rather than raising -- a
    surface must always render, even if the sonic layer invents a theme we have
    not styled yet.
    """
    props = {
        "colorScheme": "light",
        "contrast": "high",
        "density": "comfortable",
        "palette": dict(THEME_PALETTES.get(theme_id or "", BASE)),
        "typography": TYPOGRAPHY,
        "spacing": dict(SPACING),
        "radius": dict(RADIUS),
        "elevation": dict(ELEVATION),
        "motion": MOTION,
    }
    if theme_id:
        props["themeId"] = theme_id
    return props


# --------------------------------------------------------------------------- #
# Contrast maths (WCAG 2.1)
# --------------------------------------------------------------------------- #

_HEX_DIGITS = set("0123456789abcdefABCDEF")


def is_hex(value: str) -> bool:
    """True for ``#RRGGBB`` (the only colour form BAROGROOVE emits)."""
    return (
        isinstance(value, str)
        and len(value) == 7
        and value[0] == "#"
        and all(c in _HEX_DIGITS for c in value[1:])
    )


def _channel(value: int) -> float:
    c = value / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_colour: str) -> float:
    """WCAG relative luminance of an ``#RRGGBB`` colour."""
    if not is_hex(hex_colour):
        raise ValueError(f"not a #RRGGBB colour: {hex_colour!r}")
    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG contrast ratio between two ``#RRGGBB`` colours (1.0 .. 21.0)."""
    a, b = relative_luminance(foreground), relative_luminance(background)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def audit_palettes() -> list[str]:
    """Return a list of human-readable contrast failures (empty means all pass)."""
    failures: list[str] = []
    for theme_id in THEME_IDS:
        palette = THEME_PALETTES[theme_id]
        for key in PALETTE_KEYS:
            if key not in palette:
                failures.append(f"{theme_id}: missing palette key {key!r}")
            elif not is_hex(palette[key]):
                failures.append(f"{theme_id}.{key}: not a #RRGGBB colour ({palette[key]!r})")
        for fg, bg, minimum in CONTRAST_PAIRS:
            if fg not in palette or bg not in palette:
                continue
            ratio = contrast_ratio(palette[fg], palette[bg])
            if ratio < minimum:
                failures.append(
                    f"{theme_id}: {fg} on {bg} is {ratio:.2f}:1, needs {minimum:.1f}:1"
                )
    return failures

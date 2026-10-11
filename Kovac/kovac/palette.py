# SPDX-License-Identifier: LGPL-2.1-or-later
"""Kovač design tokens — the single source for every color in the app, icons and docs.

Pure Python (no FreeCAD import) so the icon generator and tests can use it.
"""

# Three brand-accent proposals, named after steel heat-tint / patina colors.
# ACCENT selects the active one until the owner picks (M1 approval gate).
ACCENTS = {
    "patina": "#14857D",  # weathered-copper green-teal
    "temper": "#6B4FD8",  # tempered-steel violet
    "straw": "#B07F22",   # straw temper colour
}
ACCENT = "patina"

THEMES = {
    "light": {
        "bg": "#F4F5F7",
        "surface": "#FFFFFF",
        "surface2": "#ECEEF1",
        "border": "#D5D9DE",
        "text": "#1C2026",
        "text_muted": "#5B636E",
        "viewport_top": "#F7F8FA",
        "viewport_bottom": "#D6DCE3",
        "model": "#B8C0CA",
        "edge": "#2A3038",
        # icon tones: outline + three face tones that suggest 3D form
        "icon_line": "#2A3038",
        "icon_top": "#FFFFFF",
        "icon_left": "#D3D9E0",
        "icon_right": "#AEB7C2",
        "icon_hole": "#59626E",
    },
    "dark": {                     # the default look: deep near-black, high contrast
        "bg": "#0E1012",
        "surface": "#15181B",
        "surface2": "#1D2125",
        "border": "#2D3339",
        "text": "#EDEFF2",
        "text_muted": "#A3ACB6",
        "viewport_top": "#1B1F23",
        "viewport_bottom": "#08090B",
        "model": "#A4AEB9",
        "edge": "#050607",
        "icon_line": "#E8ECF0",
        "icon_top": "#6E7884",
        "icon_left": "#4C5560",
        "icon_right": "#353C45",
        "icon_hole": "#0E1012",
    },
}

SEMANTIC = {
    "preselect": "#FFC857",
    "select": "#00A3D9",
    "error": "#D64545",
    "warning": "#E39B21",
    "success": "#2E9E6A",
    "sketch_free": "#3D8BFF",
    "sketch_fixed": "#2E9E6A",
    "axis_x": "#F25F5C",
    "axis_y": "#52C46B",
    "axis_z": "#5B83F0",
}

FONT_UI = '"Inter", "Segoe UI", "Noto Sans", "DejaVu Sans", sans-serif'


def accent(name=None):
    return ACCENTS[name or ACCENT]


def theme(name):
    return dict(THEMES[name], accent=accent(), **SEMANTIC)


def rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    """Linear mix of two hex colors, t=0 -> a, t=1 -> b."""
    ca, cb = rgb(a), rgb(b)
    return "#%02X%02X%02X" % tuple(round(x + (y - x) * t) for x, y in zip(ca, cb))


def packed_rgba(hex_color, alpha=255):
    """FreeCAD parameter color format: 0xRRGGBBAA as unsigned int."""
    r, g, b = rgb(hex_color)
    return (r << 24) | (g << 16) | (b << 8) | alpha

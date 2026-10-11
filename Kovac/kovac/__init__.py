# SPDX-License-Identifier: LGPL-2.1-or-later
"""Kovač — design-to-manufacture environment built on FreeCAD."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARAM = "User parameter:BaseApp/Preferences/Mod/Kovac"


def prefs():
    import FreeCAD
    return FreeCAD.ParamGet(PARAM)


def theme_name():
    """'light' or 'dark': our own setting, else whatever FreeCAD's theme is."""
    try:
        import FreeCAD
    except ImportError:  # outside FreeCAD (generator, plain-Python tests)
        return "dark"
    fc = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/MainWindow").GetString("Theme", "")
    return prefs().GetString("Theme", "") or ("light" if "light" in fc.lower() else "dark")


def icon(name, theme=None):
    p = os.path.join(ROOT, "Resources", "icons", theme or theme_name(), name + ".svg")
    return p if os.path.exists(p) else ""

# SPDX-License-Identifier: LGPL-2.1-or-later
"""Light/dark looks generated from palette.py:

- qss(): stylesheet for Kovač's own widgets (scoped by object name, so stock FreeCAD
  widgets keep FreeCAD's theme, which the preference pack tints with our accent).
- write_prefpacks(): "Kovac Light"/"Kovac Dark" FreeCAD preference packs (viewport,
  selection, sketch, orientation cube, autosave/recovery, navigation defaults).
Regenerate with: py tools/build_assets.py
"""
import os
from xml.sax.saxutils import escape

from kovac import palette

ADDON = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


LOOK_VERSION = 6       # bump when the default look changes; older profiles get it once on start


def _rgba(hex_color, a):
    return "rgba(%d, %d, %d, %.2f)" % (palette.rgb(hex_color) + (a,))


def qss(name):
    t = palette.theme(name)
    t.update(glass=_rgba(t["surface"], 0.62), glass_border=_rgba(t["border"], 0.70), accent_soft=_rgba(t["accent"], 0.16),
             accent_sel=_rgba(t["accent"], 0.30), divider=_rgba(t["text"], 0.38))
    return """
#kovacAppBar, #kovacModes, QToolBar[kovacGroup="true"], QToolBar#kovacSketchBar {{ background: {surface}; border: none; spacing: 2px; padding: 3px 8px; }}
#kovacAppBar QToolButton {{ font-size: 16px; }}
QLabel#kovacGroupLabel {{ color: {text_muted}; font-size: 12px; font-weight: 600; letter-spacing: 1px; padding: 1px 4px 0 4px; }}
QFrame#kovacRibbonDivider {{ border: none; min-width: 2px; max-width: 2px; margin: 6px 4px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 transparent, stop:0.5 {divider}, stop:1 transparent); }}
QGraphicsView Gui--QuantitySpinBox, QGraphicsView QAbstractSpinBox {{ background: {surface}; color: {text}; border: 1px solid {accent};
    border-radius: 5px; padding: 2px 6px; font-weight: 600; selection-background-color: {accent}; }}
QToolButton#kovacModeButton {{ color: {text}; background: {surface2}; border: 1px solid {border}; border-radius: 6px; padding: 6px 14px; font-size: 16px; font-weight: 700; letter-spacing: 1px; }}
QToolButton#kovacModeButton:hover {{ border-color: {accent}; }}
QToolButton#kovacModeButton::menu-indicator {{ subcontrol-position: right center; right: 6px; }}
#kovacAppBar QToolButton, QToolBar[kovacGroup="true"] QToolButton, QToolBar#kovacSketchBar QToolButton {{ color: {text}; background: transparent; border: 1px solid transparent; border-radius: 5px; padding: 4px; }}
#kovacAppBar QToolButton:hover, QToolBar[kovacGroup="true"] QToolButton:hover, QToolBar#kovacSketchBar QToolButton:hover {{ border-color: {border}; background: {surface2}; }}
#kovacAppBar QToolButton:checked, QToolBar#kovacSketchBar QToolButton:checked {{ background: {surface2}; border-color: {accent}; }}
QToolButton#kovacChoice {{ background: {surface2}; border: 1px solid {border}; border-radius: 5px; padding: 3px; }}
QToolButton#kovacChoice:checked {{ background: {accent_sel}; border-color: {accent}; }}
QToolButton#kovacChoice:hover {{ border-color: {accent}; }}
QDockWidget#kovacModel, QDockWidget#kovacTimeline {{ background: {surface}; color: {text}; }}
QDockWidget#kovacModel::title {{ background: {surface2}; color: {text_muted}; padding: 4px 8px; text-align: left; }}
#kovacTimelineList, #kovacSearch QListWidget, #kovacRadialList {{ background: {surface}; color: {text}; border: none; }}
QFrame#kovacBrowser {{ background: {glass}; border: 1px solid {glass_border}; border-radius: 8px; }}
QFrame#kovacBrowser QTreeWidget {{ background: transparent; border: none; color: {text}; }}
#kovacTree::item {{ padding: 2px 0; border-radius: 4px; }}
#kovacTree::item:hover {{ background: {accent_soft}; }}
#kovacTree::item:selected {{ background: {accent_sel}; color: {text}; }}
#kovacTree::branch:selected {{ background: transparent; }}
QToolButton#kovacBrowserToggle {{ border: none; color: {text_muted}; font-size: 12px; }}
#kovacTimelineList::item:selected, #kovacSearch QListWidget::item:selected, #kovacRadialList::item:selected {{ background: {accent}; color: #FFFFFF; }}
#kovacTimeline {{ background: {surface2}; }}
#kovacTimeline QToolButton {{ color: {text}; border: none; padding: 2px 6px; }}
#kovacSearch {{ background: {surface}; border: 1px solid {border}; border-radius: 8px; }}
#kovacSearch QLineEdit {{ background: {surface2}; color: {text}; border: 1px solid {border}; border-radius: 6px; padding: 6px 8px; font-size: 13px; }}
#kovacSearch QLineEdit:focus {{ border-color: {accent}; }}
#kovacRadialList {{ border: 1px solid {border}; border-radius: 6px; }}
#kovacMeasure QPlainTextEdit {{ background: {surface2}; color: {text}; border: none; font-family: Consolas, "DejaVu Sans Mono", monospace; }}
QLabel#kovacMuted {{ color: {text_muted}; }}
QLineEdit#kovacValue, QLineEdit#kovacFloatingField {{ background: {surface}; color: {text}; border: 1px solid {border}; border-radius: 4px; padding: 3px 6px; }}
QLineEdit#kovacFloatingField {{ border-color: {accent}; font-weight: 600; }}
QLineEdit#kovacValue:focus {{ border-color: {accent}; }}
QMdiArea QTabBar::tab {{ background: {surface2}; color: {text_muted}; padding: 5px 14px; border: none; border-right: 1px solid {border}; }}
QMdiArea QTabBar::tab:selected {{ background: {surface}; color: {text}; border-bottom: 2px solid {accent}; }}
#kovacStart {{ background: {bg}; }}
#kovacStart QLabel {{ color: {text}; }}
#kovacStart QLabel#kovacMuted {{ color: {text_muted}; }}
QLineEdit#kovacValue, QLineEdit#kovacFloatingField {{ background: {surface}; color: {text}; border: 1px solid {border}; border-radius: 4px; padding: 3px 6px; }}
QLineEdit#kovacFloatingField {{ border-color: {accent}; font-weight: 600; }}
QLineEdit#kovacValue:focus {{ border-color: {accent}; }}
QMdiArea QTabBar::tab {{ background: {surface2}; color: {text_muted}; padding: 5px 14px; border: none; border-right: 1px solid {border}; }}
QMdiArea QTabBar::tab:selected {{ background: {surface}; color: {text}; border-bottom: 2px solid {accent}; }}
#kovacStart QLabel#kovacTitle {{ font-size: 26px; font-weight: 700; }}
#kovacStart QPushButton {{ background: {surface}; color: {text}; border: 1px solid {border}; border-radius: 6px; padding: 8px 14px; text-align: left; }}
#kovacStart QPushButton:hover {{ border-color: {accent}; }}
#kovacStart QPushButton#kovacPrimary {{ background: {accent}; color: #FFFFFF; border: none; font-weight: 600; }}
#kovacStart QToolButton {{ background: {surface}; color: {text}; border: 1px solid {border}; border-radius: 6px; padding: 6px; }}
#kovacStart QToolButton:hover {{ border-color: {accent}; }}
""".format(**t)


# ---------------------------------------------------------------- preference packs

def _entry(name, value):
    if isinstance(value, bool):
        return '<FCBool Name="%s" Value="%d"/>' % (name, value)
    if isinstance(value, int):
        return '<FCInt Name="%s" Value="%d"/>' % (name, value)
    if isinstance(value, float):
        return '<FCFloat Name="%s" Value="%s"/>' % (name, repr(value))
    if isinstance(value, Color):
        return '<FCUInt Name="%s" Value="%d"/>' % (name, palette.packed_rgba(value))
    return '<FCText Name="%s">%s</FCText>' % (name, escape(value))


class Color(str):
    pass


def settings(name):
    t = {k: Color(v) for k, v in palette.theme(name).items()}
    return {
        "MainWindow": {"StyleSheet": "FreeCAD.qss", "QtStyle": "FreeCAD",
                       "Theme": "FreeCAD Dark" if name == "dark" else "FreeCAD Light"},
        "Themes": {"ThemeAccentColor1": t["accent"],
                   "ThemeAccentColor2": Color(palette.mix(t["accent"], "#FFFFFF", 0.35)),
                   "ThemeAccentColor3": Color(palette.mix(t["accent"], "#000000", 0.25))},
        "View": {
            "Simple": False, "Gradient": True, "RadialGradient": False, "UseBackgroundColorMid": False,
            "BackgroundColor2": t["viewport_top"], "BackgroundColor3": t["viewport_bottom"],
            "HighlightColor": t["preselect"], "SelectionColor": t["select"],
            "DefaultShapeColor": t["model"], "DefaultShapeLineColor": t["edge"], "DefaultShapeVertexColor": t["edge"],
            "SketchEdgeColor": t["sketch_free"], "SketchVertexColor": t["sketch_free"],
            "EditedEdgeColor": t["sketch_free"], "CreateLineColor": t["sketch_free"],
            "CursorCrosshairColor": t["text"], "CursorTextColor": t["text"],
            "FullyConstrainedColor": t["sketch_fixed"], "FullyConstraintElementColor": t["sketch_fixed"],
            "AxisXColor": t["axis_x"], "AxisYColor": t["axis_y"], "AxisZColor": t["axis_z"],
            "NavigationStyle": "Gui::CADNavigationStyle", "ZoomAtCursor": True,
            "EnableHeadlight": True, "HeadlightIntensity": 70, "EnableBacklight": False,   # plus views.add_light
            "UseNavigationAnimations": True, "AnimationDuration": 280, "PickRadius": 5.0,
        },
        # orientation cube, design variant A (docs/design/orientation-cube.md)
        "NaviCube": {"BaseColor": t["surface2"], "EmphaseColor": t["text_muted"], "HiliteColor": t["accent"],
                     "ChamferSize": 0.16, "BorderWidth": 1.0, "FontString": "Inter", "FontWeight": 600,
                     "CubeSize": 120, "InactiveOpacity": 55, "ShowCS": False, "CornerNaviCube": 1},
        "Document": {"SaveThumbnail": True, "AddThumbnailLogo": False, "AutoSaveEnabled": True,
                     "AutoSaveTimeout": 5, "RecoveryEnabled": True, "CreateBackupFiles": True,
                     "CountBackupFiles": 3, "CanAbortRecompute": True},
        # sketch grid: quiet lines, no bright major lines competing with the red/green axes
        "Mod/Sketcher/General": {"GridLineColor": Color(palette.mix(t["viewport_bottom"], t["text_muted"], 0.22)),
                                 "GridDivLineColor": Color(palette.mix(t["viewport_bottom"], t["text_muted"], 0.32))},
        # drawing sheets: white paper on the theme's background, our pre-selection/selection colours
        "Mod/TechDraw/Colors": {"Background": t["viewport_bottom"], "PageColor": Color("#FFFFFF"),
                                "PreSelectColor": t["preselect"], "SelectColor": t["select"]},
        "Mod/TechDraw/General": {"SwitchToWB": False},          # opening a sheet stays in Kovač
        "Mod/Kovac": {"Theme": name, "LookVersion": LOOK_VERSION},
    }


def user_template(name="dark"):
    """user.cfg for a fresh Kovač profile (branded build, isolated test runs)."""
    # no FreeCAD version in the title: it would read as a Kovač version
    extra = {"General": {"AutoloadModule": "KovacWorkbench", "ShowVersionInTitle": False},
             "Mod/Start": {"ShowOnStartup": False}}
    return cfg(name, extra)


def apply(name):
    """Write a look straight into the running session's parameters (what the pack does)."""
    import FreeCAD as App
    for group, values in settings(name).items():
        g = App.ParamGet("User parameter:BaseApp/Preferences/" + group)
        for k, v in values.items():
            if isinstance(v, bool):
                g.SetBool(k, v)
            elif isinstance(v, int):
                g.SetInt(k, v)
            elif isinstance(v, float):
                g.SetFloat(k, v)
            elif isinstance(v, Color):
                g.SetUnsigned(k, palette.packed_rgba(v))
            else:
                g.SetString(k, v)


def cfg(name, extra=None):
    lines = ['<?xml version="1.0" encoding="UTF-8" standalone="no" ?>', "<FCParameters>",
             '  <FCParamGroup Name="Root">', '    <FCParamGroup Name="BaseApp">', '      <FCParamGroup Name="Preferences">']
    for group, values in dict(settings(name), **(extra or {})).items():
        names = group.split("/")
        for depth, n in enumerate(names):
            lines.append("  " * (4 + depth) + '<FCParamGroup Name="%s">' % n)
        ind = "  " * (4 + len(names))
        lines += [ind + _entry(k, v) for k, v in values.items()]
        for depth in reversed(range(len(names))):
            lines.append("  " * (4 + depth) + "</FCParamGroup>")
    lines += ["      </FCParamGroup>", "    </FCParamGroup>", "  </FCParamGroup>", "</FCParameters>", ""]
    return "\n".join(lines)


def write_prefpacks(root=ADDON):
    for name, title in (("light", "Kovac Light"), ("dark", "Kovac Dark")):
        d = os.path.join(root, title)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, title + ".cfg"), "w", encoding="utf-8") as f:
            f.write(cfg(name))

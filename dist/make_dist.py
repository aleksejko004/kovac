# SPDX-License-Identifier: LGPL-2.1-or-later
"""Assemble the branded Kovač distribution from a FreeCAD binary build (portable layout).

    py tools/fc.py cmd dist/make_dist.py [--fresh]   (inside FreeCADCmd for Qt image rendering;
                                                      --fresh re-copies the FreeCAD tree)

Output: %LOCALAPPDATA%/Kovac/dist/Kovac-<version>-<os> (outside OneDrive; ~1.5 GB).
What it adds to the FreeCAD tree: bin/branding.xml, branding/ images, bin/kovac-user.cfg
(first-start profile), Mod/Kovac, and a Kovac launcher. FreeCAD's files stay untouched,
so its LICENSE and credits ship as they are.
"""
import os
import platform
import shutil
import sys

import FreeCAD as App

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "Kovac"))
from kovac import palette, shell, theme  # noqa: E402

SRC = os.path.normpath(App.getHomePath())
NAME = "Kovac-%s-%s-%s" % (shell.VERSION, platform.system().lower(), platform.machine().lower())
DEST = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/share"), "Kovac", "dist", NAME)

BRANDING = """<?xml version="1.0" encoding="UTF-8"?>
<Branding>
  <Application>Kovač</Application>
  <WindowTitle>Kovač</WindowTitle>
  <WindowIcon>branding/kovac-icon.png</WindowIcon>
  <ProgramIcons>branding</ProgramIcons>
  <SplashScreen>kovac-splash</SplashScreen>
  <AboutImage>kovac-about</AboutImage>
  <SplashAlignment>Bottom|Left</SplashAlignment>
  <SplashTextColor>#FFFFFF</SplashTextColor>
  <SplashInfoColor>#FFFFFF</SplashInfoColor>
  <SplashInfoPosition>40,60</SplashInfoPosition>
  <StartWorkbench>KovacWorkbench</StartWorkbench>
  <ExeName>Kovac</ExeName>
  <ExeVendor>Kovac</ExeVendor>
  <NavigationStyle>Gui::CADNavigationStyle</NavigationStyle>
  <UserParameterTemplate>bin/kovac-user.cfg</UserParameterTemplate>
</Branding>
"""


def render_images(out):
    from PySide import QtCore, QtGui
    try:
        from PySide import QtSvg
    except ImportError:
        from PySide6 import QtSvg
    # the offscreen platform has no fonts on Windows; the native one renders text fine headless
    args = ["kovac-dist"] if os.name == "nt" else ["kovac-dist", "-platform", "offscreen"]
    app = QtGui.QGuiApplication.instance() or QtGui.QGuiApplication(args)  # noqa: F841
    logo = QtSvg.QSvgRenderer(os.path.join(ROOT, "Kovac", "Resources", "icons", "light", "app.svg"))
    accent = QtGui.QColor(palette.accent())

    def canvas(w, h, title, sub, mark):
        img = QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32)
        img.fill(accent)
        p = QtGui.QPainter(img)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        logo.render(p, QtCore.QRectF(w - mark - 40, 40, mark, mark))
        f = QtGui.QFont("Inter")
        f.setStyleHint(QtGui.QFont.SansSerif)
        f.setPixelSize(int(h * 0.16))
        f.setWeight(QtGui.QFont.Bold)
        p.setFont(f)
        p.setPen(QtGui.QColor("#FFFFFF"))
        p.drawText(QtCore.QRectF(40, h * 0.22, w, h * 0.22), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, title)
        f.setPixelSize(int(h * 0.055))
        f.setWeight(QtGui.QFont.Normal)
        p.setFont(f)
        p.setPen(QtGui.QColor(255, 255, 255, 215))
        p.drawText(QtCore.QRectF(42, h * 0.45, w, h * 0.1), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, sub)
        p.end()
        return img

    os.makedirs(out, exist_ok=True)
    built = "Built on FreeCAD %s  ·  version %s" % (".".join(App.Version()[:3]), shell.VERSION)
    for k, suffix in ((1, ""), (2, "_2x")):   # FreeCAD picks <name>_2x on HiDPI screens
        canvas(1000 * k, 560 * k, "Kovač", built, 220 * k).save(os.path.join(out, "kovac-splash%s.png" % suffix))
        canvas(640 * k, 240 * k, "Kovač", built, 120 * k).save(os.path.join(out, "kovac-about%s.png" % suffix))
    icon = QtGui.QImage(256, 256, QtGui.QImage.Format_ARGB32)
    icon.fill(0)
    p = QtGui.QPainter(icon)
    logo.render(p)
    p.end()
    icon.save(os.path.join(out, "kovac-icon.png"))


def main():
    print("FreeCAD tree:", SRC)
    print("output:      ", DEST)
    if "--fresh" in sys.argv or not os.path.isdir(os.path.join(DEST, "bin")):
        shutil.copytree(SRC, DEST, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(os.path.join(ROOT, "Kovac"), os.path.join(DEST, "Mod", "Kovac"), dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"))
    render_images(os.path.join(DEST, "branding"))
    with open(os.path.join(DEST, "bin", "branding.xml"), "w", encoding="utf-8") as f:
        f.write(BRANDING)
    with open(os.path.join(DEST, "bin", "kovac-user.cfg"), "w", encoding="utf-8") as f:
        f.write(theme.user_template("dark"))
    if os.name == "nt":
        shutil.copy2(os.path.join(DEST, "FreeCAD.exe"), os.path.join(DEST, "Kovac.exe"))
    else:   # AppImage/extracted tree: plain launcher script
        launcher = os.path.join(DEST, "kovac")
        with open(launcher, "w") as f:
            f.write('#!/bin/sh\nexec "$(dirname "$0")/bin/FreeCAD" "$@"\n')
        os.chmod(launcher, 0o755)
    print("done")


main()
os._exit(0)

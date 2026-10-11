# SPDX-License-Identifier: LGPL-2.1-or-later
"""Icon system tests: generator rules, files on disk current, raster regression.

The raster test renders every icon with Qt's SVG renderer (what FreeCAD uses) at 16/24/32 px
on both themes and compares pixel hashes with tests/golden/icons.json. After an approved
style change:  set KOVAC_UPDATE_GOLDEN=1 and run the suite once.
"""
import hashlib
import json
import os
import re
import unittest

import icongen
from kovac import palette

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden", "icons.json")
FORBIDDEN = re.compile(r"<(clipPath|filter|mask|linearGradient|radialGradient|image|foreignObject)\b")


class Generator(unittest.TestCase):
    def test_every_icon_renders_in_both_themes_within_live_area(self):
        for name in icongen.ICONS:
            for theme in palette.THEMES:
                svg = icongen.render(name, theme)   # raises if it leaves the 20 px live area
                self.assertTrue(svg.startswith("<svg"))
                self.assertIsNone(FORBIDDEN.search(svg), "%s uses SVG features Qt's renderer lacks" % name)
                self.assertIn('viewBox="0 0 24 24"', svg)

    def test_accent_marks_the_action(self):
        for name, (_, family) in icongen.ICONS.items():
            self.assertIn(palette.accent().upper(), icongen.render(name, "light").upper(), name)

    def test_files_on_disk_are_current(self):
        for name in icongen.ICONS:
            for theme in palette.THEMES:
                path = os.path.join(icongen.ROOT, "Kovac", "Resources", "icons", theme, name + ".svg")
                with open(path, encoding="utf-8") as f:
                    self.assertEqual(f.read(), icongen.render(name, theme), "run: py tools/build_assets.py")


def raster_hashes():
    from PySide import QtCore, QtGui
    try:
        from PySide import QtSvg
    except ImportError:
        from PySide6 import QtSvg
    if QtGui.QGuiApplication.instance() is None:
        raster_hashes.app = QtGui.QGuiApplication(["kovac-test", "-platform", "offscreen"])
    out = {}
    for name in icongen.ICONS:
        for theme in palette.THEMES:
            r = QtSvg.QSvgRenderer(QtCore.QByteArray(icongen.render(name, theme).encode()))
            for px in (16, 24, 32):
                img = QtGui.QImage(px, px, QtGui.QImage.Format_ARGB32_Premultiplied)
                img.fill(0)
                p = QtGui.QPainter(img)
                r.render(p)
                p.end()
                out["%s/%s/%d" % (theme, name, px)] = hashlib.sha256(bytes(img.constBits())).hexdigest()[:16]
    return out


class Raster(unittest.TestCase):
    def test_pixels_match_golden(self):
        got = raster_hashes()
        if os.environ.get("KOVAC_UPDATE_GOLDEN") == "1" or not os.path.exists(GOLDEN):
            os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
            with open(GOLDEN, "w") as f:
                json.dump(got, f, indent=1, sort_keys=True)
            if os.environ.get("KOVAC_UPDATE_GOLDEN") != "1":
                self.fail("golden file was missing and has been created; review and re-run")
        with open(GOLDEN) as f:
            want = json.load(f)
        changed = sorted(k for k in set(got) | set(want) if got.get(k) != want.get(k))
        self.assertEqual(changed, [], "icons changed: %s (approved? KOVAC_UPDATE_GOLDEN=1)" % changed[:8])


if __name__ == "__main__":
    unittest.main()

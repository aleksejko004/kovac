# SPDX-License-Identifier: LGPL-2.1-or-later
"""Launched inside the branded build by tests/run_dist.py: report what the user would see."""
import json
import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets


def probe():
    mw = Gui.getMainWindow()
    res = {
        "window_title": mw.windowTitle(),
        "workbench": Gui.activeWorkbench().name(),
        "menubar_visible": mw.menuBar().isVisible(),
        "stock_toolbars_visible": [t.objectName() for t in mw.findChildren(QtWidgets.QToolBar)
                                   if t.isVisible() and not t.objectName().startswith("kovac")],
        "start_page": any(s.widget() and s.widget().objectName() == "kovacStart"
                          for s in mw.findChild(QtWidgets.QMdiArea).subWindowList()),
        "user_data_dir": App.getUserAppDataDir(),
        "exe_name": App.ConfigGet("ExeName"),
        "application": App.ConfigGet("Application"),
        "selection_color": App.ParamGet("User parameter:BaseApp/Preferences/View").GetUnsigned("SelectionColor"),
    }
    with open(os.environ["KOVAC_RESULT"], "w") as f:
        json.dump(res, f, indent=1)
    os._exit(0)


QtCore.QTimer.singleShot(2500, probe)

# SPDX-License-Identifier: LGPL-2.1-or-later
"""Run 1 of the recovery test (see run_recovery.py): edit a document, wait for FreeCAD's
autosave (timeout 1 min in the seeded profile), check the recovery file, then "crash"."""
import json
import os

import FreeCAD as App
from PySide import QtCore

OUT = os.environ["KOVAC_RESULT"]


def edit():
    doc = App.newDocument("Unsaved")
    from kovac import commands
    with commands.transaction("Box", doc):
        doc.addObject("Part::Box", "Box").Length = 42
    App.ParamGet("User parameter:BaseApp/Preferences/Document").SetBool("AutoSaveEnabled", True)
    QtCore.QTimer.singleShot(80000, lambda: crash(doc))


def crash(doc):
    files = os.listdir(doc.TransientDir)
    with open(OUT, "w") as f:
        json.dump({"transient_dir": doc.TransientDir, "files": files}, f)
    os._exit(9)   # no save, no cleanup: what a crash leaves behind


QtCore.QTimer.singleShot(1000, edit)

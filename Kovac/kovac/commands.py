# SPDX-License-Identifier: LGPL-2.1-or-later
"""Command layer. Every user action runs through here:

    with transaction("Extrude"):      # one user action = one transaction = one undo step,
        ...                           # recomputed before it is committed

add() registers a GUI command whose activation goes through invoke(), which records the
last command (for "repeat last") and turns exceptions into a plain status-bar message
instead of a modal error wall.
"""
import contextlib

import FreeCAD as App

REGISTRY = {}   # command id -> _Command (ours only)
last = None     # id of the last command run, ours or stock
last_trace = ""  # traceback of the last failed command (console log, tests)


@contextlib.contextmanager
def transaction(name, doc=None):
    doc = doc or App.ActiveDocument
    if doc is None:
        raise RuntimeError("No document is open.")
    nested = doc.HasPendingTransaction
    if not nested:
        doc.openTransaction(name)
    try:
        yield doc
        doc.recompute()
    except Exception:
        if not nested:
            doc.abortTransaction()
        raise
    if not nested:
        doc.commitTransaction()


def report(message, error=True):
    """Local, non-modal feedback: console + status bar. Never a dialog."""
    (App.Console.PrintError if error else App.Console.PrintMessage)("Kovač: %s\n" % message)
    try:
        import FreeCADGui as Gui
        Gui.getMainWindow().statusBar().showMessage(str(message), 8000)
    except Exception:
        pass


def invoke(cid, fn):
    global last
    last = cid
    try:
        fn()
    except Exception as e:  # plain-language message, details stay in the console
        import traceback
        global last_trace
        last_trace = traceback.format_exc()
        App.Console.PrintLog(last_trace)
        report("%s failed: %s" % (REGISTRY[cid].text if cid in REGISTRY else cid, e))


def run(cid):
    """Run any command by id (ours or stock), recording it as the last command."""
    import FreeCADGui as Gui
    if cid in REGISTRY:
        invoke(cid, REGISTRY[cid].fn)
    else:
        global last
        last = cid
        Gui.runCommand(cid)


class _Command:
    def __init__(self, cid, text, tip, fn, icon, key, active):
        self.cid, self.text, self.tip, self.fn, self.icon, self.key, self.active = cid, text, tip, fn, icon, key, active

    def GetResources(self):
        r = {"MenuText": self.text, "ToolTip": self.tip}
        if self.icon:
            r["Pixmap"] = self.icon
        if self.key:
            r["Accel"] = self.key
        return r

    def IsActive(self):
        try:
            return bool(self.active()) if self.active else True
        except Exception:
            return False

    def Activated(self, *_):
        invoke(self.cid, self.fn)


def add(cid, text, tip, fn, icon="", key="", active=None):
    import FreeCADGui as Gui
    REGISTRY[cid] = _Command(cid, text, tip, fn, icon, key, active)
    Gui.addCommand(cid, REGISTRY[cid])
    return cid


def has_doc():
    return App.ActiveDocument is not None

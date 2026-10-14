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
_running = []   # [stop, owner command id] of tools that stay on until ended (see started())


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


def started(stop, cid=None):
    """A tool that stays on until it is ended (the sketch-plane picker, Drag, the Joint panel)
    calls this with its stop function. Modelling commands end it before they start, except
    the tool's own command `cid`, which decides itself (Drag's toggles it off). Hand the
    returned entry to ended() when the tool stops."""
    entry = [stop, cid]
    _running.append(entry)
    return entry


def ended(entry):
    if entry in _running:
        _running.remove(entry)


def end_tools(keep=None):
    """Stop every running tool except those owned by `keep`; how many were stopped."""
    n = 0
    for entry in list(_running):
        if entry[1] is not None and entry[1] == keep:
            continue
        ended(entry)
        n += 1
        try:
            entry[0]()
        except Exception:
            import traceback
            App.Console.PrintLog(traceback.format_exc())
    return n


def step(cid):
    """Undo or redo (`cid` is "Std_Undo" or "Std_Redo"). While a tool is running, a step back
    only leaves the tool: it never takes back work done before the tool started."""
    if end_tools():
        report("Left the running tool; nothing was undone.", error=False)
        return
    import FreeCADGui as Gui
    Gui.runCommand(cid)


def invoke(cid, fn):
    global last
    last = cid
    if cid in REGISTRY and REGISTRY[cid].ends_tools:
        end_tools(keep=cid)
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
    def __init__(self, cid, text, tip, fn, icon, key, active, ends_tools):
        self.cid, self.text, self.tip, self.fn, self.icon, self.key, self.active = cid, text, tip, fn, icon, key, active
        self.ends_tools = ends_tools

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


def add(cid, text, tip, fn, icon="", key="", active=None, ends_tools=False):
    """`ends_tools`: a modelling command, which ends running tools first (started())."""
    import FreeCADGui as Gui
    REGISTRY[cid] = _Command(cid, text, tip, fn, icon, key, active, ends_tools)
    Gui.addCommand(cid, REGISTRY[cid])
    return cid


def has_doc():
    return App.ActiveDocument is not None

# SPDX-License-Identifier: LGPL-2.1-or-later
"""Panels. Command panels float near the work, never block the view or the tree, remember
where they were put, and can be docked from their title bar (Qt dock widgets give us
float/dock/move for free). Fixed docks (tree, timeline) use the same helper.
"""
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

import kovac

_open = {}


def _key(pid):
    return "Panel_" + pid


def dock(pid, title, body, area=None, floating=False):
    mw = Gui.getMainWindow()
    d = mw.findChild(QtWidgets.QDockWidget, "kovac" + pid)
    if d is None:
        d = QtWidgets.QDockWidget(title, mw)
        d.setObjectName("kovac" + pid)
        d.setWidget(body)
        mw.addDockWidget(area or QtCore.Qt.RightDockWidgetArea, d)
        if floating:
            _restore(d, pid)
            d.topLevelChanged.connect(lambda *_: _save(d, pid))
            d.installEventFilter(_Saver(d, pid))
    return d


def _restore(d, pid):
    d.setFloating(True)
    geo = kovac.prefs().GetString(_key(pid), "")
    if geo:
        d.restoreGeometry(QtCore.QByteArray.fromHex(geo.encode()))
    else:  # first time: next to the cursor
        d.resize(300, 220)
        d.move(QtGui.QCursor.pos() + QtCore.QPoint(32, 24))


def _save(d, pid):
    kovac.prefs().SetString(_key(pid), bytes(d.saveGeometry().toHex()).decode())


class _Saver(QtCore.QObject):
    def __init__(self, d, pid):
        super().__init__(d)
        self.d, self.pid = d, pid

    def eventFilter(self, _o, ev):
        if ev.type() in (QtCore.QEvent.Move, QtCore.QEvent.Resize, QtCore.QEvent.Hide):
            _save(self.d, self.pid)
        return False


def show(pid, title, factory):
    """Open (or raise) a floating command panel; factory() builds its body once."""
    if pid not in _open:
        _open[pid] = dock(pid, title, factory(), floating=True)
    d = _open[pid]
    d.show()
    d.raise_()
    return d

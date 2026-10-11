# SPDX-License-Identifier: LGPL-2.1-or-later
"""Command search: one key (Kovac_Search, default "S", remappable like any FreeCAD shortcut)
opens a field that finds every command. Ctrl+D or the star pins a favourite; favourites and
recent commands fill the list before you type.
"""
import time

stats = {"last_query_ms": None, "entries": 0}


def score(query, text):
    """Fuzzy score (higher is better), None if the query is not a subsequence of text.
    Substring hits beat scattered ones; word starts and runs of consecutive letters count more."""
    q, t = query.lower().strip(), text.lower()
    if not q:
        return 0
    if q in t:
        k = t.index(q)
        return 1000 - k + (200 if k == 0 or t[k - 1] in " _-" else 0)
    i, s, prev = 0, 0, -2
    for j, ch in enumerate(t):
        if i < len(q) and ch == q[i]:
            s += 3 if j == prev + 1 else (2 if j == 0 or t[j - 1] in " _-" else 1)
            prev, i = j, i + 1
    return s if i == len(q) else None


def rank(query, entries, favorites=()):
    """entries: [(cid, label, tip)] -> matching cids, best first; favourites break ties upward."""
    hits = []
    for cid, label, tip in entries:
        s = score(query, label)
        if s is None:
            s = score(query, tip)
            s = None if s is None else s / 4
        if s is not None:
            hits.append((-(s + (50 if cid in favorites else 0)), label, cid))
    return [cid for _, _, cid in sorted(hits)]


def _list_pref(name):
    import kovac
    return [x for x in kovac.prefs().GetString(name, "").split(",") if x]


def _set_list_pref(name, items):
    import kovac
    kovac.prefs().SetString(name, ",".join(items))


def entries(advanced=False):
    import FreeCADGui as Gui
    out = []
    for cid in Gui.listCommands():
        if not advanced and not cid.startswith(("Kovac_", "Std_")):
            continue
        cmd = Gui.Command.get(cid)
        info = cmd.getInfo() if cmd else None
        label = (info or {}).get("menuText", "").replace("&", "").replace("...", "").strip()
        if label:
            out.append((cid, label, (info.get("toolTip") or "").replace("\n", " ")))
    return out


def popup():
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets

    import kovac
    from kovac import commands

    class Search(QtWidgets.QFrame):
        def __init__(self, parent):
            super().__init__(parent, QtCore.Qt.Popup)
            self.setObjectName("kovacSearch")
            self.edit = QtWidgets.QLineEdit(self, placeholderText="Search commands…")
            self.list = QtWidgets.QListWidget(self)
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(8, 8, 8, 8)
            lay.addWidget(self.edit)
            lay.addWidget(self.list)
            self.resize(460, 380)
            self.entries = entries(kovac.prefs().GetBool("Advanced", False))
            stats["entries"] = len(self.entries)
            self.by_id = {e[0]: e for e in self.entries}
            self.edit.textChanged.connect(self.refresh)
            self.list.itemActivated.connect(lambda it: self.run(it.data(QtCore.Qt.UserRole)))
            self.edit.installEventFilter(self)
            self.refresh("")

        def refresh(self, text):
            t0 = time.perf_counter()
            favs = _list_pref("Favorites")
            ids = rank(text, self.entries, favs) if text else \
                [c for c in favs + _list_pref("Recent") if c in self.by_id]
            self.list.clear()
            for cid in dict.fromkeys(ids[:60]):
                cmd = Gui.Command.get(cid)
                info = cmd.getInfo()
                pix = info.get("pixmap", "")
                icon = QtGui.QIcon(pix) if pix.endswith(".svg") else (Gui.getIcon(pix) if pix else QtGui.QIcon())
                star = "★ " if cid in favs else ""
                origin = "" if cid.startswith("Kovac_") else "   · FreeCAD"   # same names exist in both
                it = QtWidgets.QListWidgetItem(icon or QtGui.QIcon(), "%s%s%s" % (star, self.by_id[cid][1], origin))
                it.setToolTip(self.by_id[cid][2])
                it.setData(QtCore.Qt.UserRole, cid)
                self.list.addItem(it)
            self.list.setCurrentRow(0)
            stats["last_query_ms"] = (time.perf_counter() - t0) * 1000

        def eventFilter(self, _o, ev):
            if ev.type() == QtCore.QEvent.KeyPress:
                k = ev.key()
                if k in (QtCore.Qt.Key_Down, QtCore.Qt.Key_Up):
                    self.list.setCurrentRow(max(0, self.list.currentRow() + (1 if k == QtCore.Qt.Key_Down else -1)))
                    return True
                if k in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter) and self.list.currentItem():
                    self.run(self.list.currentItem().data(QtCore.Qt.UserRole))
                    return True
                if k == QtCore.Qt.Key_D and ev.modifiers() & QtCore.Qt.ControlModifier and self.list.currentItem():
                    self.toggle_favorite(self.list.currentItem().data(QtCore.Qt.UserRole))
                    return True
            return False

        def toggle_favorite(self, cid):
            favs = _list_pref("Favorites")
            _set_list_pref("Favorites", [f for f in favs if f != cid] if cid in favs else favs + [cid])
            row = self.list.currentRow()
            self.refresh(self.edit.text())
            self.list.setCurrentRow(row)

        def run(self, cid):
            _set_list_pref("Recent", ([cid] + [c for c in _list_pref("Recent") if c != cid])[:8])
            self.close()
            QtCore.QTimer.singleShot(0, lambda: commands.run(cid))

    mw = Gui.getMainWindow()
    w = Search(mw)
    w.move(mw.mapToGlobal(QtCore.QPoint((mw.width() - w.width()) // 2, 90)))
    w.show()
    w.edit.setFocus()
    return w

# SPDX-License-Identifier: LGPL-2.1-or-later
"""The Export panel: what goes out (the selection, or every shown part), the format, one file
or one per part, and for meshes how fine. Export asks where to save."""
import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

import kovac
from kovac import commands, export

_panel = []


def open_panel():
    if not _panel:
        _panel.append(Panel())
    p = _panel[0]
    p.refresh()
    p.dock.show()
    p.dock.raise_()
    return p


class Panel:
    def __init__(self):
        from kovac import panel
        from kovac.editor import IconChoice
        prefs = kovac.prefs()
        w = QtWidgets.QWidget(objectName="kovacExport")
        lay = QtWidgets.QVBoxLayout(w)
        self.what = QtWidgets.QLabel(objectName="kovacMuted")
        self.what.setWordWrap(True)
        lay.addWidget(self.what)
        self.format = IconChoice(list(export.FORMATS), prefs.GetString("ExportFormat", "STEP"))
        self.format.setObjectName("kovacExportFormat")
        self.files = IconChoice(["One file", "One file per part"], prefs.GetString("ExportFiles", "One file"))
        self.files.setObjectName("kovacExportFiles")
        self.fine_label = QtWidgets.QLabel("Mesh")
        self.fine = IconChoice(list(export.FINENESS), prefs.GetString("ExportFineness", "Normal"))
        self.fine.setObjectName("kovacExportFineness")
        for label, field in (("Format", self.format), ("Files", self.files)):
            lay.addWidget(QtWidgets.QLabel(label))
            lay.addWidget(field)
        lay.addWidget(self.fine_label)
        lay.addWidget(self.fine)
        self.format.currentTextChanged.connect(lambda _v: self.refresh())
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        close = QtWidgets.QPushButton("Close")
        self.go = QtWidgets.QPushButton("Export…", objectName="kovacPrimary")
        close.clicked.connect(lambda: self.dock.hide())
        self.go.clicked.connect(self.run)
        buttons.addWidget(close)
        buttons.addWidget(self.go)
        lay.addLayout(buttons)
        self.dock = panel.dock("Export", "Export", w, floating=True)
        self.dock.setWindowTitle("Export")
        Gui.Selection.addObserver(self)

    # selection observer: the summary follows what is picked
    def _changed(self, *_a):
        QtCore.QTimer.singleShot(0, self.refresh)

    addSelection = removeSelection = setSelection = clearSelection = _changed

    def objects(self):
        doc = App.ActiveDocument
        if doc is None:
            return []
        return export.items(doc, _picked())

    def refresh(self):
        try:
            self.what.isVisible()
        except RuntimeError:                       # the panel's widgets are gone (closing down)
            return
        objs = self.objects()
        picked = bool(_picked())
        names = ", ".join(o.Label for o in objs[:4]) + (" …" if len(objs) > 4 else "")
        if not objs:
            self.what.setText("Nothing to export: pick bodies or components, or show some.")
        else:
            self.what.setText("%s %d part%s: %s" % ("Selected:" if picked else "Everything shown:",
                                                     len(objs), "" if len(objs) == 1 else "s", names))
        mesh = self.format.currentText() != "STEP"
        self.fine_label.setVisible(mesh)
        self.fine.setVisible(mesh)
        self.go.setEnabled(bool(objs))

    def run(self):
        objs = self.objects()
        fmt, files, fine = self.format.currentText(), self.files.currentText(), self.fine.currentText()
        prefs = kovac.prefs()
        prefs.SetString("ExportFormat", fmt)
        prefs.SetString("ExportFiles", files)
        prefs.SetString("ExportFineness", fine)
        ext = export.FORMATS[fmt]
        doc = App.ActiveDocument
        base = objs[0].Label if len(objs) == 1 else (doc.Label if doc else "design")
        start = os.path.join(prefs.GetString("ExportDir", export.default_dir()), export._name(base) + ext)
        title = "Export %s" % fmt + (" (one file per part: this name is the start of each)" if files != "One file" else "")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), title, start, "%s (*%s)" % (fmt, ext))
        if not path:
            return
        if not path.lower().endswith(ext) and not (ext == ".step" and path.lower().endswith(".stp")):
            path += ext
        prefs.SetString("ExportDir", os.path.dirname(path))
        try:
            out = export.export(objs, path, separate=files != "One file", fineness=fine)
        except Exception as e:
            commands.report(e)
            return
        commands.report(export.report(out), error=False)


def _picked():
    """The picked objects: through a face or edge pick, the body or component it is on."""
    out = []
    for s in Gui.Selection.getSelectionEx("", 0):
        subs = s.SubElementNames or [""]
        for sub in subs:
            o = s.Object
            if sub:
                path = sub[:len(sub) - len(sub.split(".")[-1])]
                leaf = o.getSubObject(path, 1) if path else o
                o = _part_of(leaf if leaf is not None else o, o, path)
            if o not in out:
                out.append(o)
    return out


def _part_of(leaf, top, path):
    """A pick deep in the design counts as the component it went through at the top (an
    instance is its own part), else the body itself."""
    from kovac import components, tree
    if path and tree.role(top) == "component" and components.is_root(top):
        first = top.getSubObject(path.split(".")[0] + ".", 1)
        if first is not None:
            return first if tree.role(first) in ("component", "linked") else leaf
    return leaf

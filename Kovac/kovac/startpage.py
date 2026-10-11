# SPDX-License-Identifier: LGPL-2.1-or-later
"""Start page: new design, open/import, templates, an example, recent files with thumbnails."""
import os
import zipfile

import FreeCAD as App

from kovac import commands

RECENT = "User parameter:BaseApp/Preferences/RecentFiles"


def recent_files(limit=8):
    grp = App.ParamGet(RECENT)
    files = [grp.GetString("MRU%d" % i, "") for i in range(grp.GetInt("RecentFiles", 8))]
    return [f for f in files if f and os.path.exists(f)][:limit]


def thumbnail(path):
    """PNG bytes FreeCAD stored inside the .FCStd, or None."""
    try:
        with zipfile.ZipFile(path) as z:
            return z.read("thumbnails/Thumbnail.png")
    except (OSError, KeyError, zipfile.BadZipFile):
        return None


def new_design(name="Design", unit_system=None):
    doc = App.newDocument(name)
    if unit_system is not None and "UnitSystem" in doc.PropertiesList:
        doc.UnitSystem = unit_system
    return doc


def example_bracket():
    """L-bracket built from Part features (shows a real history in the timeline)."""
    doc = new_design("Bracket_example")
    with commands.transaction("Example bracket", doc):
        base = doc.addObject("Part::Box", "Base")
        base.Length, base.Width, base.Height = 60, 40, 6
        wall = doc.addObject("Part::Box", "Wall")
        wall.Length, wall.Width, wall.Height = 6, 40, 40
        joined = doc.addObject("Part::MultiFuse", "Bracket")
        joined.Shapes = [base, wall]
        holes = []
        for i, (x, y) in enumerate(((22, 12), (22, 28), (44, 12), (44, 28))):
            h = doc.addObject("Part::Cylinder", "Hole%d" % (i + 1))
            h.Radius, h.Height = 2.75, 6
            h.Placement.Base = App.Vector(x, y, 0)
            holes.append(h)
        tools = doc.addObject("Part::MultiFuse", "Holes")
        tools.Shapes = holes
        cut = doc.addObject("Part::Cut", "Drilled")
        cut.Base, cut.Tool = joined, tools
    return doc


def create():
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets

    import kovac

    class Start(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.setObjectName("kovacStart")
            self.setWindowTitle("Start")
            self.setAttribute(QtCore.Qt.WA_StyledBackground)
            outer = QtWidgets.QVBoxLayout(self)
            outer.setContentsMargins(48, 36, 48, 36)
            head = QtWidgets.QHBoxLayout()
            logo = QtWidgets.QLabel()
            logo.setPixmap(QtGui.QIcon(kovac.icon("app")).pixmap(56, 56))
            title = QtWidgets.QLabel("Kovač", objectName="kovacTitle")
            credit = QtWidgets.QLabel('Built on <a href="https://www.freecad.org">FreeCAD</a>', objectName="kovacMuted")
            credit.setOpenExternalLinks(True)
            col = QtWidgets.QVBoxLayout()
            col.addWidget(title)
            col.addWidget(credit)
            head.addWidget(logo)
            head.addLayout(col)
            head.addStretch()
            outer.addLayout(head)
            body = QtWidgets.QHBoxLayout()
            body.setSpacing(40)
            outer.addLayout(body, 1)

            left = QtWidgets.QVBoxLayout()
            body.addLayout(left)
            self.button(left, "New design", lambda: self.go(new_design), primary=True)
            self.button(left, "Open…", lambda: Gui.runCommand("Std_Open"))
            self.button(left, "Import STEP…", lambda: commands.run("Kovac_ImportStep"))
            left.addSpacing(16)
            left.addWidget(QtWidgets.QLabel("Templates", objectName="kovacMuted"))
            self.button(left, "Part · millimetres", lambda: self.go(lambda: new_design("Part", 0)))
            self.button(left, "Part · inches", lambda: self.go(lambda: new_design("Part", 3)))
            left.addSpacing(16)
            left.addWidget(QtWidgets.QLabel("Examples", objectName="kovacMuted"))
            self.button(left, "L-bracket with holes", lambda: self.go(example_bracket))
            left.addStretch()

            right = QtWidgets.QVBoxLayout()
            body.addLayout(right, 1)
            right.addWidget(QtWidgets.QLabel("Recent", objectName="kovacMuted"))
            grid = QtWidgets.QGridLayout()
            files = recent_files()
            for i, path in enumerate(files):
                b = QtWidgets.QToolButton()
                b.setToolButtonStyle(QtCore.Qt.ToolButtonTextUnderIcon)
                b.setText(os.path.splitext(os.path.basename(path))[0])
                b.setToolTip(path)
                b.setIconSize(QtCore.QSize(128, 128))
                b.setFixedSize(156, 172)
                png = thumbnail(path)
                pix = QtGui.QPixmap()
                if png and pix.loadFromData(png):
                    b.setIcon(QtGui.QIcon(pix))
                else:
                    b.setIcon(QtGui.QIcon(kovac.icon("app")))
                b.clicked.connect(lambda _=False, p=path: Gui.open(p))
                grid.addWidget(b, i // 4, i % 4)
            if not files:
                grid.addWidget(QtWidgets.QLabel("Files you save will appear here.", objectName="kovacMuted"), 0, 0)
            right.addLayout(grid)
            right.addStretch()

        @staticmethod
        def button(layout, text, fn, primary=False):
            b = QtWidgets.QPushButton(text)
            if primary:
                b.setObjectName("kovacPrimary")
            b.setMinimumWidth(220)
            b.clicked.connect(fn)
            layout.addWidget(b)

        @staticmethod
        def go(fn):
            doc = fn()
            from kovac import views
            if Gui.activeView() is not None and hasattr(Gui.activeView(), "graphicsView"):
                views.home(Gui.activeView())
            return doc

    mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    for sub in mdi.subWindowList():
        if sub.widget() and sub.widget().objectName() == "kovacStart":
            mdi.setActiveSubWindow(sub)
            return sub
    sub = mdi.addSubWindow(Start())
    sub.setWindowIcon(QtGui.QIcon(kovac.icon("app")))
    sub.showMaximized()
    return sub

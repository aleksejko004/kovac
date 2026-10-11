# SPDX-License-Identifier: LGPL-2.1-or-later
"""Model browser: document settings, named views, components -> bodies, sketches, reference
geometry, joints, analyses. FreeCAD machinery (origins, binders, links, features consumed
into other shapes) never shows here; features live in the history timeline.

The browser floats over the left of the 3D view, see-through, collapsible. Every item has
its own icon; the eye column shows and hides (a folder's eye toggles everything in it).
"""
import FreeCAD as App

from kovac import selection

META_VIEW = "kovac.view."
FOLDERS = (("body", "Bodies"), ("sketch", "Sketches"), ("reference", "Reference geometry"),
           ("joint", "Joints"), ("analysis", "Analyses"))
CONTAINERS = ("App::Part", "Assembly::AssemblyObject")
_FEATURE_PROXIES = {"Extrude", "Revolve", "Sweep", "Loft", "Primitive", "Hole", "Fillet", "Chamfer", "Shell", "Draft",
                    "FacePull", "DeleteFace", "Combine", "SplitBody", "Transform", "Scale", "Mirror", "Pattern",
                    "Thread", "Import", "RemoveBody"}
ICONS = {"body": "body", "sketch": "sketch", "component": "component", "joint": "joint", "analysis": "section",
         "reference": "plane"}


def role(obj):
    """What the user sees an object as: component, body, sketch, reference, joint, analysis,
    feature (timeline only) or machinery (never shown)."""
    proxy = type(getattr(obj, "Proxy", None)).__name__
    if proxy == "BodyProxy":
        return "body" if not obj.Shape.isNull() else "machinery"
    if proxy == "HistoryProxy":
        return "machinery"
    if proxy == "SectionProxy":
        return "analysis"
    if proxy in ("DatumPlane", "DatumAxis", "DatumPoint"):
        return "machinery" if getattr(obj, "Auto", False) else "reference"
    if proxy in _FEATURE_PROXIES:
        return "feature"
    tid = obj.TypeId
    if tid in ("App::Origin", "App::Link", "App::VarSet") or tid.endswith("Binder"):
        return "machinery"
    if tid in ("App::Line", "App::Plane", "App::Point") and any(p.TypeId == "App::Origin" for p in obj.InList):
        return "machinery"
    if tid in CONTAINERS:
        return "component"
    if tid == "PartDesign::Body":
        return "body"
    if tid.startswith("Sketcher::"):
        return "sketch"
    if tid in selection.REFERENCE_TYPES:
        return "reference"
    if tid.startswith("Assembly::Joint") or hasattr(obj, "JointType"):
        return "joint"
    if tid.startswith("Fem::FemAnalysis"):
        return "analysis"
    if tid.startswith("PartDesign::"):
        return "feature"
    if hasattr(obj, "Shape"):
        consumers = [o for o in obj.InList if hasattr(o, "Shape") and o.TypeId not in CONTAINERS
                     and o.TypeId != "PartDesign::Body" and o.TypeId != "App::DocumentObjectGroup"]
        return "feature" if consumers else "body"
    return "machinery"


def children(doc, parent=None):
    """Direct user-visible children of the document root or of a component."""
    objs = parent.Group if parent is not None else [
        o for o in doc.Objects if not any(p.TypeId in CONTAINERS + ("PartDesign::Body",) for p in o.InList)]
    return [o for o in objs if role(o) not in ("machinery", "feature")]


def body_sketches(body):
    return [o for o in getattr(body, "Group", []) if role(o) == "sketch"]


def named_views(doc):
    return sorted(k[len(META_VIEW):] for k in doc.Meta if k.startswith(META_VIEW))


def save_view(doc, name, camera):
    meta = doc.Meta
    meta[META_VIEW + name] = camera
    doc.Meta = meta


def item_icon(obj):
    """Our icon for a browser row (reference geometry by its kind)."""
    import kovac
    r = role(obj)
    if r == "reference":
        kind = type(getattr(obj, "Proxy", None)).__name__
        return kovac.icon({"DatumAxis": "axis", "DatumPoint": "point"}.get(kind, "plane"))
    return kovac.icon(ICONS.get(r, "feature"))


# ---------------------------------------------------------------- widget
_browser = None     # findChild would hand back a plain QFrame wrapper, not this object

def create():
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets

    import kovac
    from kovac import commands

    OBJ, VIEW, MEMBERS = QtCore.Qt.UserRole, QtCore.Qt.UserRole + 1, QtCore.Qt.UserRole + 2
    EYE = 1

    def qicon(name):
        return QtGui.QIcon(kovac.icon(name))

    class SelectionSync:
        """FreeCAD's selection observer for the tree, kept off the tree itself: its callbacks are
        named setSelection and clearSelection, the same as QAbstractItemView's own methods, and
        on the widget they replaced them -- Qt's click-to-select called our re-sync instead, which
        read back FreeCAD's still-empty selection, so no row could be selected by mouse at all."""

        def __init__(self, tree):
            self.tree = tree

        def addSelection(self, *_):
            self.tree.from_selection()

        removeSelection = setSelection = clearSelection = addSelection

    class Tree(QtWidgets.QTreeWidget):
        def __init__(self):
            super().__init__()
            self.setObjectName("kovacTree")
            self.setHeaderHidden(True)
            self.setColumnCount(2)
            self.header().setStretchLastSection(False)
            self.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
            self.header().setSectionResizeMode(EYE, QtWidgets.QHeaderView.Fixed)
            self.setColumnWidth(EYE, 26)
            self.setIconSize(QtCore.QSize(18, 18))
            self.setIndentation(14)
            self.setFrameShape(QtWidgets.QFrame.NoFrame)
            self.viewport().setAutoFillBackground(False)
            self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
            self.setEditTriggers(QtWidgets.QAbstractItemView.EditKeyPressed | QtWidgets.QAbstractItemView.SelectedClicked)
            self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            self.customContextMenuRequested.connect(self.menu)
            self.itemChanged.connect(self.changed)
            self.itemClicked.connect(self.on_click)
            self.itemSelectionChanged.connect(self.to_selection)
            self.itemDoubleClicked.connect(self.double)
            self.syncing = False
            self.timer = QtCore.QTimer(self, singleShot=True, interval=30)
            self.timer.timeout.connect(self.rebuild)
            App.addDocumentObserver(self)
            self.sel_observer = SelectionSync(self)
            Gui.Selection.addObserver(self.sel_observer)
            self.rebuild()

        # ---------------------------------------------------- build
        def item(self, parent, text, obj=None, icon=None, visible=None, editable=True):
            it = QtWidgets.QTreeWidgetItem(parent, [text, ""])
            flags = QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable
            if obj is not None:
                it.setData(0, OBJ, (obj.Document.Name, obj.Name))
                if editable:
                    flags |= QtCore.Qt.ItemIsEditable
            if icon is not None:
                it.setIcon(0, icon)
            if visible is not None:
                it.setIcon(EYE, qicon("eye" if visible else "eyeoff"))
                it.setData(EYE, OBJ, bool(visible))
                it.setToolTip(EYE, "Hide" if visible else "Show")
            it.setFlags(flags)
            return it

        def rebuild(self):
            self.syncing = True
            expanded = {self.key(it) for it in self.walk() if it.isExpanded()}
            self.clear()
            doc = App.ActiveDocument
            if doc:
                self.item(self, "Document settings · %s" % getattr(doc, "UnitSystem", "mm"), icon=qicon("settings"))
                views = named_views(doc)
                if views:
                    vf = self.item(self, "Named views", icon=qicon("views"))
                    for name in views:
                        self.item(vf, name, icon=qicon("views")).setData(0, VIEW, name)
                self.fill(self, doc, None)
            for it in self.walk():
                it.setExpanded(self.key(it) in expanded or not expanded)
            self.syncing = False
            self.from_selection()

        def fill(self, parent, doc, container):
            objs = children(doc, container)
            view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
            active = view.getActiveObject("part") if view is not None and hasattr(view, "getActiveObject") else None
            for c in [o for o in objs if role(o) == "component"]:
                it = self.item(parent, c.Label, c, QtGui.QIcon(item_icon(c)), c.Visibility)
                if active is not None and active.Name == c.Name:
                    f = it.font(0)
                    f.setBold(True)
                    it.setFont(0, f)
                    it.setToolTip(0, "Active component: new geometry goes here")
                self.fill(it, doc, c)
            for r, title in FOLDERS:
                members = [o for o in objs if role(o) == r]
                if not members:
                    continue
                folder = self.item(parent, "%s  (%d)" % (title, len(members)), icon=qicon("folder"),
                                   visible=any(o.Visibility for o in members))
                folder.setData(0, MEMBERS, [(o.Document.Name, o.Name) for o in members])
                for o in members:
                    it = self.item(folder, o.Label, o, QtGui.QIcon(item_icon(o)), o.Visibility)
                    for sk in body_sketches(o) if r == "body" else []:
                        self.item(it, sk.Label, sk, QtGui.QIcon(item_icon(sk)), sk.Visibility)

        def walk(self, parent=None):
            parent = parent or self.invisibleRootItem()
            for i in range(parent.childCount()):
                yield parent.child(i)
                yield from self.walk(parent.child(i))

        @staticmethod
        def key(it):
            return it.data(0, OBJ) or it.text(0).split("  (")[0]

        @staticmethod
        def obj(it):
            d = it.data(0, OBJ)
            return App.getDocument(d[0]).getObject(d[1]) if d else None

        # ---------------------------------------------------- edits
        def on_click(self, it, col):
            if col != EYE or it.data(EYE, OBJ) is None:
                return
            show = not it.data(EYE, OBJ)
            o = self.obj(it)
            targets = [o] if o is not None else [App.getDocument(d).getObject(n) for d, n in (it.data(0, MEMBERS) or [])]
            for t in targets:
                if t is not None:
                    t.Visibility = show
            self.rebuild()

        def changed(self, it, col):
            if self.syncing or col != 0:
                return
            o = self.obj(it)
            if o is not None and it.text(0) != o.Label:
                with commands.transaction("Rename", o.Document):
                    o.Label = it.text(0)

        def double(self, it, col):
            if col == EYE:
                return
            o = self.obj(it)
            if o is not None and role(o) == "component":
                Gui.ActiveDocument.ActiveView.setActiveObject("part", o)
                self.rebuild()
            elif it.data(0, VIEW):
                Gui.activeView().setCamera(App.ActiveDocument.Meta[META_VIEW + it.data(0, VIEW)])

        def menu(self, pos):
            it = self.itemAt(pos)
            o = self.obj(it) if it else None
            sel = [x for x in (self.obj(s) for s in self.selectedItems()) if x is not None]
            m = QtWidgets.QMenu(self)
            if o is not None:
                m.addAction("Rename", lambda: self.editItem(it, 0))
                m.addAction("Hide" if o.Visibility else "Show", lambda: (setattr(o, "Visibility", not o.Visibility), self.rebuild()))
                if role(o) == "component":
                    m.addAction("Activate", lambda: self.double(it, 0))
                if role(o) == "body":
                    m.addAction("Material…", lambda: commands.run("Kovac_Material"))
                if len(sel) > 1 and o in sel:
                    m.addAction("Delete %d selected" % len(sel), self.delete_selected)
                else:
                    m.addAction("Delete", lambda: self.delete(o))
            m.addAction("Save current view…", self.save_view)
            m.exec(self.viewport().mapToGlobal(pos))

        def keyPressEvent(self, ev):
            if ev.key() in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
                self.delete_selected()
                return
            super().keyPressEvent(ev)

        def delete(self, o):
            self.delete_selected([o])

        def delete_selected(self, objs=None):
            """Every selected item (or `objs`, for the single-item context menu action and the
            Delete / Backspace key), as one undo step."""
            from kovac import model
            objs = objs if objs is not None else [self.obj(it) for it in self.selectedItems()]
            objs = list(dict.fromkeys(o for o in objs if o is not None))
            if not objs:
                return
            doc = objs[0].Document
            hist = model.items(doc)
            objs.sort(key=lambda o: hist.index(o) if o in hist else -1, reverse=True)   # dependents first
            label = "Delete %s" % objs[0].Label if len(objs) == 1 else "Delete %d items" % len(objs)
            try:
                with commands.transaction(label, doc):
                    for o in objs:
                        if doc.getObject(o.Name) is None:      # already gone (e.g. with its body)
                            continue
                        if o in model.items(doc):
                            model.remove(doc, o)
                        else:
                            doc.removeObject(o.Name)
            except Exception as e:
                commands.report(e)

        def save_view(self):
            doc = App.ActiveDocument
            if doc is None:
                return
            name, ok = QtWidgets.QInputDialog.getText(self, "Save view", "Name:", text="View %d" % (len(named_views(doc)) + 1))
            if ok and name:
                with commands.transaction("Save view", doc):
                    save_view(doc, name, Gui.activeView().getCamera())

        # ---------------------------------------------------- selection sync
        def to_selection(self):
            if self.syncing:
                return
            self.syncing = True
            Gui.Selection.clearSelection()
            for it in self.selectedItems():
                o = self.obj(it)
                if o is not None:
                    Gui.Selection.addSelection(o)
            self.syncing = False

        def from_selection(self, *_):
            if self.syncing:
                return
            self.syncing = True
            names = {(s.Object.Document.Name, s.Object.Name) for s in Gui.Selection.getSelectionEx("*", 0)}
            for it in self.walk():
                it.setSelected(it.data(0, OBJ) in names)
            self.syncing = False


        # ---------------------------------------------------- document observer
        def slotCreatedObject(self, _o):
            self.timer.start()

        slotDeletedObject = slotActivateDocument = slotDeletedDocument = slotUndoDocument = slotRedoDocument = \
            slotRecomputedDocument = slotCreatedObject

        def slotChangedObject(self, _o, prop):
            if prop in ("Label", "Visibility", "Group", "Meta"):
                self.timer.start()

        def slotChangedDocument(self, _doc, prop):
            if prop == "Meta":
                self.timer.start()

    class Browser(QtWidgets.QFrame):
        """See-through panel floating over the left of the 3D view."""

        def __init__(self, area):
            super().__init__(area)
            self.setObjectName("kovacBrowser")
            self.area = area
            self.tree = Tree()
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(6, 4, 6, 6)
            lay.setSpacing(2)
            head = QtWidgets.QHBoxLayout()
            self.toggle = QtWidgets.QToolButton(objectName="kovacBrowserToggle", autoRaise=True)
            self.toggle.clicked.connect(self.collapse)
            head.addWidget(self.toggle)
            head.addWidget(QtWidgets.QLabel("BROWSER", objectName="kovacGroupLabel"))
            head.addStretch()
            lay.addLayout(head)
            lay.addWidget(self.tree, 1)
            m = self.tree.model()
            for sig in (self.tree.itemExpanded, self.tree.itemCollapsed, m.rowsInserted, m.rowsRemoved, m.modelReset):
                sig.connect(lambda *_: QtCore.QTimer.singleShot(0, self.place))
            self.collapsed = kovac.prefs().GetBool("BrowserCollapsed", False)
            self.apply_collapsed()
            area.installEventFilter(self)
            self.place()

        def apply_collapsed(self):
            self.tree.setVisible(not self.collapsed)
            self.toggle.setText("▸" if self.collapsed else "▾")
            self.toggle.setToolTip("Show the browser" if self.collapsed else "Fold the browser away")

        def collapse(self):
            self.collapsed = not self.collapsed
            kovac.prefs().SetBool("BrowserCollapsed", self.collapsed)
            self.apply_collapsed()
            self.place()

        def place(self):
            w = kovac.prefs().GetInt("BrowserWidth", 270)
            tabs = 34                     # keep the document tabs at the bottom clickable
            rows, item = 0, self.tree.topLevelItem(0)
            while item is not None:       # fit the shown rows; the rest of the view stays clear
                rows, item = rows + 1, self.tree.itemBelow(item)
            want = 40 + rows * max(self.tree.sizeHintForRow(0), 22)
            h = 34 if self.collapsed else min(max(80, want), self.area.height() - 16 - tabs)
            self.setGeometry(8, 8, w, h)
            self.raise_()

        def eventFilter(self, _o, ev):
            if ev.type() in (QtCore.QEvent.Resize, QtCore.QEvent.ChildAdded, QtCore.QEvent.Show, QtCore.QEvent.LayoutRequest):
                QtCore.QTimer.singleShot(0, self.place)
            return False

        def widget(self):
            return self.tree

    global _browser
    if _browser is not None:
        try:
            _browser.objectName()             # still alive?
            return _browser
        except RuntimeError:
            pass
    _browser = Browser(Gui.getMainWindow().findChild(QtWidgets.QMdiArea))
    return _browser

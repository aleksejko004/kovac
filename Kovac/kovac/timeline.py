# SPDX-License-Identifier: LGPL-2.1-or-later
"""History timeline: every feature in model order, one strip for the whole document.

The accent bar is the rollback marker: drag it (or use the step buttons) to see the model
as it was; new features go in at the marker. Drag a feature to reorder it (refused, with
the reason, if it would come before something it uses). Double-click edits; right-click
for edit, suppress, roll to here, move, rename, group, dependencies and delete. Hovering a
feature tints every face it made; picking a face highlights the feature that made it.
States: error (red, with the reason in the tooltip), suppressed (grey), rolled back (faded).
"""
import FreeCAD as App

from kovac import tree


def features(doc):
    """History items in order (Kovač documents), else shape features and sketches in creation order."""
    from kovac import model
    its = model.items(doc)
    if its:
        return [o for o in its if not getattr(o, "Auto", False)]
    return [o for o in doc.Objects if tree.role(o) in ("feature", "sketch")
            or (tree.role(o) == "body" and o.TypeId != "PartDesign::Body")]


def state(obj):
    if getattr(obj, "Status", "") or "Invalid" in obj.State or "Error" in obj.State:
        return "error"
    if getattr(obj, "Suppressed", False):
        return "suppressed"
    proxy = getattr(obj, "Proxy", None)
    if hasattr(proxy, "damaged"):              # Kovač features know from their regeneration
        return "warning" if proxy.damaged else "ok"
    shape = getattr(obj, "Shape", None)
    if shape is not None and not shape.isNull() and not obj.TypeId.startswith("Sketcher::") and not shape.isValid():
        return "warning"
    return "ok"


def creator(obj, sub):
    """Feature that created a picked element (Kovač face tags, else FreeCAD element history)."""
    from kovac import model
    owner = model.owner_of(obj, sub)
    if owner is not None:
        return owner
    element = sub.split(".")[-1] if sub else ""
    target = obj.getSubObject(sub[:-len(element)]) if sub and sub[:-len(element)] else obj
    if element and hasattr(target, "getElementHistory"):
        try:
            hist = target.getElementHistory(element)
            if hist and hist[0][0] is not None:
                return hist[0][0]
        except Exception:
            pass
    return target


def made_by(face_tag, name):
    """True if a face tag comes from the named feature (directly or as a pattern instance)."""
    return face_tag.split(":")[0].split("@")[0] == name or ("@%s." % name) in face_tag


def create():
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets

    from kovac import commands, model, overlay, palette, panel

    OBJ, MARK = QtCore.Qt.UserRole, QtCore.Qt.UserRole + 1

    def marker_icon():
        pm = QtGui.QPixmap(6, 30)
        pm.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(pm)
        p.fillRect(1, 0, 4, 30, QtGui.QColor(palette.accent()))
        p.end()
        return QtGui.QIcon(pm)

    class Strip(QtWidgets.QListWidget):
        def __init__(self, owner):
            super().__init__()
            self.owner = owner
            self.setObjectName("kovacTimelineList")
            self.setFlow(QtWidgets.QListView.LeftToRight)
            self.setWrapping(False)
            self.setIconSize(QtCore.QSize(24, 24))
            self.setFixedHeight(48)
            self.setMouseTracking(True)
            self.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
            self.setDefaultDropAction(QtCore.Qt.MoveAction)
            self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
            self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)

        def dropEvent(self, ev):
            moved = self.currentItem()
            key = (moved.data(OBJ), moved.data(MARK)) if moved is not None else None
            super().dropEvent(ev)
            QtCore.QTimer.singleShot(0, lambda: self.owner.dropped(key))

        def keyPressEvent(self, ev):
            if ev.key() in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
                self.owner.delete_selected()
                return
            super().keyPressEvent(ev)

    class Timeline(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.setObjectName("kovacTimeline")
            lay = QtWidgets.QHBoxLayout(self)
            lay.setContentsMargins(4, 2, 4, 2)
            for glyph, tip, step in (("«", "Roll back to the start", "start"), ("‹", "Step back", -1),
                                     ("►", "Play through the history", "play"), ("›", "Step forward", 1),
                                     ("»", "Roll to the end", "end")):
                b = QtWidgets.QToolButton(text=glyph, toolTip=tip)
                b.clicked.connect(lambda _=False, s=step: self.step(s))
                lay.addWidget(b)
            self.list = Strip(self)
            self.list.itemEntered.connect(self.hover)
            self.list.itemDoubleClicked.connect(self.double)
            self.list.customContextMenuRequested.connect(self.menu)
            self.list.viewport().installEventFilter(self)
            lay.addWidget(self.list, 1)
            self.collapsed = set()
            self.hover_node = None
            self.player = QtCore.QTimer(self, interval=450)
            self.player.timeout.connect(self.play_step)
            self.timer = QtCore.QTimer(self, singleShot=True, interval=40)
            self.timer.timeout.connect(self.rebuild)
            self.syncing = False
            App.addDocumentObserver(self)
            Gui.Selection.addObserver(self)
            self.rebuild()

        # ------------------------------------------------------------- build
        @staticmethod
        def obj(it):
            d = it.data(OBJ) if it else None
            return App.getDocument(d[0]).getObject(d[1]) if d else None

        def _items(self):
            return [self.list.item(i) for i in range(self.list.count())]

        def _add_marker(self):
            it = QtWidgets.QListWidgetItem(marker_icon(), "")
            it.setData(MARK, True)
            it.setToolTip("Rollback marker: drag it; new features go in here")
            it.setSizeHint(QtCore.QSize(10, 40))
            self.list.addItem(it)

        def rebuild(self):
            import kovac
            t = palette.theme(kovac.theme_name())
            self.list.clear()
            doc = App.ActiveDocument
            if doc is None:
                return
            hist = model.items(doc)
            marker_at = model.rollback_index(doc)
            marker_done, groups = False, set()
            for o in features(doc):
                if hist and o in hist and hist.index(o) >= marker_at and not marker_done:
                    self._add_marker()
                    marker_done = True
                g = getattr(o, "TimelineGroup", "")
                if g and g in self.collapsed:
                    if g not in groups:
                        groups.add(g)
                        it = QtWidgets.QListWidgetItem("▸ " + g)
                        it.setToolTip("Group %s (double-click to open)" % g)
                        it.setData(OBJ, (o.Document.Name, o.Name))
                        self.list.addItem(it)
                    continue
                vo = getattr(o, "ViewObject", None)
                icon = QtGui.QIcon(kovac.icon("sketch")) if o.TypeId.startswith("Sketcher::") else (vo.Icon if vo else QtGui.QIcon())
                # Named, not just "▾": a bare arrow on every member of every group looks the
                # same whichever group it is, or even that it's grouped at all rather than each
                # one just happening to have its own little arrow -- the name on every member
                # (not only the first) reads as one thing even scrolled to the middle of it.
                it = QtWidgets.QListWidgetItem(icon, ("▾ " + g) if g else "")
                st = state(o)
                active = not hist or o not in hist or hist.index(o) < marker_at
                tip = o.Label + ("" if st == "ok" else "  —  " + (getattr(o, "Status", "") or st))
                it.setToolTip((("Group %s: " % g) if g else "") + tip + ("" if active else "  (rolled back)"))
                it.setData(OBJ, (o.Document.Name, o.Name))
                if st != "ok":
                    col = QtGui.QColor(t[{"error": "error", "warning": "warning", "suppressed": "border"}[st]])
                    col.setAlphaF(0.5)
                    it.setBackground(col)
                elif not active:
                    it.setForeground(QtGui.QColor(t["text_muted"]))
                    it.setBackground(QtGui.QColor(t["surface2"]))
                elif g:         # a faint, shared tint so the group's members read as one row of things
                    it.setBackground(QtGui.QColor(palette.mix(t["viewport_bottom"], palette.accent(), 0.12)))
                self.list.addItem(it)
            if hist and not marker_done:
                self._add_marker()

        # ------------------------------------------------------------- drag & drop
        def dropped(self, key):
            doc = App.ActiveDocument
            if doc is None or key is None:
                return
            order = self._items()
            hist = model.items(doc)
            moved = next((x for x in order if (x.data(OBJ), x.data(MARK)) == key), None)
            if moved is None:
                return
            i = order.index(moved)
            before = next((self.obj(x) for x in reversed(order[:i]) if not x.data(MARK)), None)
            try:
                if moved.data(MARK):
                    model.set_rollback(doc, hist.index(before) + 1 if before in hist else 0)
                    model.commit(doc)
                else:
                    obj = self.obj(moved)
                    target = (hist.index(before) + 1) if before in hist else 0
                    if hist.index(obj) < target:
                        target -= 1
                    with commands.transaction("Reorder " + obj.Label, doc):
                        model.move(doc, obj, target)
                        model.commit(doc)
            except Exception as e:
                commands.report(e)
            self.rebuild()

        # ------------------------------------------------------------- hover / edit / menu
        def eventFilter(self, _o, ev):
            if ev.type() == QtCore.QEvent.Leave:
                self.clear_hover()
            return False

        def clear_hover(self):
            overlay.remove(self.hover_node)
            self.hover_node = None
            Gui.Selection.clearPreselection()

        def hover(self, it):
            self.clear_hover()
            o = self.obj(it)
            if o is None or it.data(MARK) or Gui.activeView() is None or not hasattr(Gui.activeView(), "graphicsView"):
                return
            tip = model.tip(o.Document)
            faces = [f for b in (model.state_of(tip).values() if tip is not None else [])
                     for f, tag in zip(b.shape.Faces, b.tags) if made_by(tag, o.Name)]
            if faces:
                from pivy import coin
                sep = coin.SoSeparator()
                for f in faces:
                    sep.addChild(overlay.face_node(f, palette.SEMANTIC["preselect"], 0.35))
                self.hover_node = overlay.add(sep)
            elif not model.is_feature(o) and getattr(o, "ViewObject", None) is not None and o.ViewObject.Visibility:
                Gui.Selection.setPreselection(o, "")

        def double(self, it):
            if it.data(MARK):
                return
            o = self.obj(it)
            if it.text().startswith("▸"):
                self.collapsed.discard(getattr(o, "TimelineGroup", ""))
                self.rebuild()
                return
            self.edit(o)

        @staticmethod
        def edit(o):
            from kovac import editor, sketchmode
            if o.TypeId.startswith("Sketcher::"):
                sketchmode.edit(o)
            elif model.is_feature(o) and o.Kind in editor.SCHEMAS:
                editor.edit(o)

        def menu(self, pos):
            it = self.list.itemAt(pos)
            o = self.obj(it) if it is not None and not it.data(MARK) else None
            doc = App.ActiveDocument
            if o is None or doc is None:
                return
            hist = model.items(doc)
            m = QtWidgets.QMenu(self)
            m.addAction("Edit", lambda: self.edit(o))
            if model.is_feature(o):
                m.addAction("Unsuppress" if o.Suppressed else "Suppress",
                            lambda: self.run("Suppress", lambda: setattr(o, "Suppressed", not o.Suppressed)))
            if o in hist:
                m.addAction("Roll to here", lambda: self.roll(hist.index(o) + 1))
                m.addAction("Move earlier", lambda: self.run("Reorder", lambda: model.move(doc, o, hist.index(o) - 1)))
                m.addAction("Move later", lambda: self.run("Reorder", lambda: model.move(doc, o, hist.index(o) + 1)))
            m.addAction("Rename…", lambda: self.rename(o))
            m.addAction("Show dependencies", lambda: self.dependencies(o))
            sel = [self.obj(x) for x in self.list.selectedItems() if not x.data(MARK)]
            if len(sel) > 1:
                m.addAction("Group selected", lambda: self.group(sel))
            g = getattr(o, "TimelineGroup", "")
            if g:
                m.addAction("Collapse group", lambda: (self.collapsed.add(g), self.rebuild()))
                m.addAction("Ungroup", lambda: self.group([x for x in features(doc) if getattr(x, "TimelineGroup", "") == g], ""))
            m.addSeparator()
            if len(sel) > 1:
                m.addAction("Delete %d selected" % len(sel), self.delete_selected)
            else:
                m.addAction("Delete", lambda: self.run("Delete " + o.Label, lambda: model.remove(doc, o)))
            m.exec(self.list.viewport().mapToGlobal(pos))

        def delete_selected(self):
            """Every selected item (a selected collapsed group stands for all its members), as
            one undo step; in dependency order so one freshly-selected feature using another
            doesn't block it. Also reachable from the Delete / Backspace key."""
            doc = App.ActiveDocument
            if doc is None:
                return
            objs = []
            for it in self.list.selectedItems():
                if it.data(MARK):
                    continue
                if it.text().startswith("▸"):               # a collapsed group row: every member
                    g = getattr(self.obj(it), "TimelineGroup", "")
                    objs += [x for x in features(doc) if getattr(x, "TimelineGroup", "") == g]
                else:
                    o = self.obj(it)
                    if o is not None:
                        objs.append(o)
            objs = list(dict.fromkeys(objs))                 # de-duplicate, keep order
            if not objs:
                return
            hist = model.items(doc)
            objs.sort(key=lambda o: hist.index(o) if o in hist else -1, reverse=True)   # later ones (likely dependents) first
            label = "Delete " + objs[0].Label if len(objs) == 1 else "Delete %d features" % len(objs)
            self.run(label, lambda: [model.remove(doc, o) for o in objs])

        def roll(self, k):
            doc = App.ActiveDocument
            model.set_rollback(doc, k)
            model.commit(doc)
            self.rebuild()

        def run(self, what, fn):
            doc = App.ActiveDocument
            try:
                with commands.transaction(what, doc):
                    fn()
                    model.commit(doc)
            except Exception as e:
                commands.report(e)
            self.rebuild()

        def rename(self, o):
            name, ok = QtWidgets.QInputDialog.getText(self, "Rename", "Name:", text=o.Label)
            if ok and name:
                self.run("Rename", lambda: setattr(o, "Label", name))

        def group(self, objs, name=None):
            if name is None:
                name, ok = QtWidgets.QInputDialog.getText(self, "Group", "Group name:", text="Group")
                if not ok or not name:
                    return

            def apply():
                for x in objs:
                    if not hasattr(x, "TimelineGroup"):
                        x.addProperty("App::PropertyString", "TimelineGroup", "Kovac", "timeline group", 4)
                    x.TimelineGroup = name
            self.run("Group", apply)

        def dependencies(self, o):
            its = features(o.Document)
            related = {x for x in o.OutList if x in its} | {x for x in o.InList if x in its}
            if model.is_feature(o):
                related -= {o.Previous}
                related -= {x for x in its if getattr(x, "Previous", None) is o}
            self.list.clearSelection()
            for x in self._items():
                if self.obj(x) in related:
                    x.setSelected(True)
            commands.report("%s uses / is used by: %s" % (o.Label, ", ".join(sorted(x.Label for x in related)) or "nothing"),
                            error=False)

        # ------------------------------------------------------------- step controls (rollback)
        def step(self, s):
            doc = App.ActiveDocument
            if doc is None or not model.items(doc):
                return
            n, k = len(model.items(doc)), model.rollback_index(doc)
            if s == "play":
                self.roll(0)
                self.player.start()
                return
            self.roll({"start": 0, "end": n}[s] if isinstance(s, str) else max(0, min(n, k + s)))

        def play_step(self):
            doc = App.ActiveDocument
            if doc is None or model.rollback_index(doc) >= len(model.items(doc)):
                self.player.stop()
                return
            self.step(1)

        # ------------------------------------------------------------- selection: face -> feature
        def addSelection(self, doc, obj, sub, _pnt=None):
            if self.syncing:
                return
            o = App.getDocument(doc).getObject(obj)
            f = creator(o, sub) if o else None
            for x in self._items():
                if f is not None and x.data(OBJ) == (f.Document.Name, f.Name):
                    self.list.setCurrentItem(x)
                    self.list.scrollToItem(x)
                    return

        def clearSelection(self, *_):
            self.list.clearSelection()

        # ------------------------------------------------------------- document observer
        def slotCreatedObject(self, _o):
            self.timer.start()

        slotDeletedObject = slotActivateDocument = slotDeletedDocument = slotUndoDocument = slotRedoDocument = \
            slotRecomputedDocument = slotCreatedObject

        def slotChangedObject(self, _o, prop):
            if prop in ("Label", "Suppressed", "Status", "Features", "Rollback", "TimelineGroup"):
                self.timer.start()

    d = panel.dock("Timeline", "History", Timeline(), QtCore.Qt.BottomDockWidgetArea)
    d.setTitleBarWidget(QtWidgets.QWidget())
    return d

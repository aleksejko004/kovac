# SPDX-License-Identifier: LGPL-2.1-or-later
"""Viewport interaction, installed as a Qt event filter on every 3D view's viewport.

- Mouse preset (remappable): default pan = Middle, orbit = Shift+Middle, wheel zooms toward
  the cursor (InvertZoom flips it), double middle click fits everything. Same in sketches.
- Orbit pivot = point under the cursor (or selection centre, preference), shown briefly.
  Free or turntable orbit.
- Selection is owned here (outside edit modes): click selects, Ctrl toggles, Shift adds,
  Esc clears, press-and-hold or Alt+click opens a pick list, drag = window (left->right,
  enclosed only) or crossing (right->left, touched) selection, double-click = tangent chain.
- Right button opens the radial menu.
While a FreeCAD edit mode (e.g. a sketch) is active, left/right buttons go to FreeCAD.
"""
import math

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

import kovac
from kovac import palette, selection

V = App.Vector
PRESETS = {
    "kovac": "pan=Middle; orbit=Shift+Middle",
    "middle-orbit": "orbit=Middle; pan=Shift+Middle",
    "touchpad": "orbit=Shift+Right; pan=Ctrl+Right",
}
HOLD_MS, DRAG_PX, ORBIT_RAD_PER_PX, ZOOM_PER_NOTCH = 450, 4, 0.006, 0.85
GESTURE_PX = 12          # a right drag this long while a sketch tool runs opens the radial menu
_BUTTONS = {QtCore.Qt.LeftButton: "Left", QtCore.Qt.MiddleButton: "Middle", QtCore.Qt.RightButton: "Right"}
_MODS = ((QtCore.Qt.ShiftModifier, "Shift"), (QtCore.Qt.ControlModifier, "Ctrl"), (QtCore.Qt.AltModifier, "Alt"))
_installed = {}
last_error = ""
hooks = []      # on-canvas tools (manipulators, region pickers): press(it, pos) -> True to take the drag


def parse_preset(spec):
    """'pan=Middle; orbit=Shift+Middle' -> {'pan': ('Middle', frozenset()), 'orbit': ('Middle', {'Shift'})}"""
    out = {}
    for part in filter(None, (p.strip() for p in spec.split(";"))):
        action, chord = (s.strip() for s in part.split("="))
        keys = chord.split("+")
        out[action] = (keys[-1], frozenset(keys[:-1]))
    return out


def bindings():
    p = kovac.prefs()
    return parse_preset(p.GetString("MouseBindings", "") or PRESETS[p.GetString("MousePreset", "kovac")])


def _mods(ev):
    m = ev.modifiers()
    return frozenset(name for flag, name in _MODS if m & flag)


def in_edit():
    gd = Gui.ActiveDocument
    return bool(gd and gd.getInEdit())


def camera_focus(cam):
    """The point cam is looking at (its orbit centre): position, stepped back along view
    direction by focalDistance. Works for both camera kinds; it is the most robust 'what is
    this view centred on' a caller can get without a model or a successful ray cast."""
    pos3 = V(*cam.position.getValue().getValue())
    rot = App.Rotation(*cam.orientation.getValue().getValue())
    return pos3 - rot.multVec(V(0, 0, 1)) * cam.focalDistance.getValue()


class Band(QtWidgets.QWidget):
    """Window (solid accent) vs crossing (dashed green) rectangle."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.rect_, self.crossing = QtCore.QRect(), False
        self.hide()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        col = QtGui.QColor(palette.SEMANTIC["success"] if self.crossing else palette.accent())
        pen = QtGui.QPen(col, 1.5, QtCore.Qt.DashLine if self.crossing else QtCore.Qt.SolidLine)
        fill = QtGui.QColor(col)
        fill.setAlphaF(0.10)
        p.setPen(pen)
        p.setBrush(fill)
        p.drawRect(self.rect_.adjusted(0, 0, -1, -1))


def _close_stock_menu():
    """Close a FreeCAD pop-up menu that a replayed right click opened (runs inside its event loop)."""
    w = QtWidgets.QApplication.activePopupWidget()
    if isinstance(w, QtWidgets.QMenu):
        w.close()


class SnapMarker(QtWidgets.QWidget):
    """Shows where a click will land when it snaps: a small square with a short tick across the
    middle of each side and a dot in the centre; yellow on an existing point, teal on the grid."""
    SIZE, HALF, TICK = 28, 7, 4

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.resize(self.SIZE, self.SIZE)
        self.kind = "grid"
        self.hide()

    def show_at(self, q, kind):
        self.kind = kind
        self.move(int(round(q.x() - self.SIZE / 2)), int(round(q.y() - self.SIZE / 2)))
        self.show()
        self.raise_()
        self.update()

    def paintEvent(self, _):
        from kovac import palette
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        col = QtGui.QColor(palette.SEMANTIC["preselect"] if self.kind == "point" else palette.accent())
        c, h, t = self.SIZE / 2, self.HALF, self.TICK
        halo = QtGui.QColor(0, 0, 0, 140)             # reads on light and dark backgrounds
        for pen in (QtGui.QPen(halo, 3.6), QtGui.QPen(col, 1.6)):
            p.setPen(pen)
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawRect(QtCore.QRectF(c - h, c - h, 2 * h, 2 * h))
            for x1, y1, x2, y2 in ((c, c - h - t, c, c - h + t), (c, c + h - t, c, c + h + t),
                                   (c - h - t, c, c - h + t, c), (c + h - t, c, c + h + t, c)):
                p.drawLine(QtCore.QPointF(x1, y1), QtCore.QPointF(x2, y2))
        p.setPen(QtGui.QPen(halo, 1))
        p.setBrush(col)
        p.drawEllipse(QtCore.QPointF(c, c), 2.4, 2.4)


class Interactor(QtCore.QObject):
    def __init__(self, view):
        super().__init__()
        self.view = view
        self.vp = view.graphicsView().viewport()
        self.band = Band(self.vp)
        self.snap_marker = SnapMarker(self.vp)
        self.drag = None          # (kind, start QPoint, last QPoint, data)
        self.press_info = None
        self.hold = QtCore.QTimer(self, singleShot=True, interval=HOLD_MS)
        self.hold.timeout.connect(self._hold_fired)
        self.marker = None
        self.vp.installEventFilter(self)

    # ------------------------------------------------------------ helpers
    def coin(self, pos):
        """Qt widget coords -> Coin viewport coords (device px, origin bottom-left)."""
        r = self.vp.devicePixelRatioF()
        return int(pos.x() * r), int((self.vp.height() - pos.y()) * r)

    def qt(self, xy):
        r = self.vp.devicePixelRatioF()
        return xy[0] / r, self.vp.height() - xy[1] / r

    def info_at(self, pos):
        """What a click at pos picks: among everything under the cursor at (nearly) the front
        depth, a vertex beats an edge beats a face (brief §3.3). Tolerance: PickPriorityPx."""
        hits = self.view.getObjectsInfo(self.coin(pos)) or []
        if not hits:
            return None
        first = V(hits[0]["x"], hits[0]["y"], hits[0]["z"])
        tol = kovac.prefs().GetFloat("PickPriorityPx", 4.0) * self.px_size()
        near = [h for h in hits if (V(h["x"], h["y"], h["z"]) - first).Length <= tol and h["Object"] == hits[0]["Object"]]

        def rank(h):
            el = (h.get("SubName") or h.get("Component") or "").split(".")[-1]
            return 0 if el.startswith("Vertex") else 1 if el.startswith("Edge") else 2
        return min(near, key=rank)

    def in_cube(self, pos):
        """Inside the orientation cube's corner square (NaviCube parameters)."""
        g = App.ParamGet("User parameter:BaseApp/Preferences/NaviCube")
        if not App.ParamGet("User parameter:BaseApp/Preferences/View").GetBool("ShowNaviCube", True):
            return False
        size = g.GetInt("CubeSize", 132) * 1.1
        corner = g.GetInt("CornerNaviCube", 1)       # 0 top-left, 1 top-right, 2 bottom-left, 3 bottom-right
        x = pos.x() if corner in (0, 2) else self.vp.width() - pos.x()
        y = pos.y() if corner in (0, 1) else self.vp.height() - pos.y()
        return 0 <= x <= size + g.GetInt("OffsetX", 0) and 0 <= y <= size + g.GetInt("OffsetY", 0)

    def snap_sketch(self, ev):
        """In a sketch the cursor jumps to a nearby existing point, or a nearby grid point (see
        grid.sketch_target), and the snap marker shows it; FreeCAD's own snapping then lands
        exactly there. Not while panning, not with Alt held."""
        if not in_edit():
            return False
        if ev.modifiers() & QtCore.Qt.AltModifier:
            self.snap_marker.hide()
            return False
        if ev.type() == QtCore.QEvent.MouseMove and ev.buttons() & ~QtCore.Qt.LeftButton:
            return False
        if ev.type() != QtCore.QEvent.MouseMove and ev.button() != QtCore.Qt.LeftButton:
            return False
        from kovac import grid, sketchmode
        if not sketchmode.in_sketch():
            return False
        pos = ev.position().toPoint()
        target = grid.sketch_target(self, pos)
        if target is None:
            self.snap_marker.hide()
            return False
        q, kind = target
        self.snap_marker.show_at(q, kind)
        if abs(q.x() - ev.position().x()) + abs(q.y() - ev.position().y()) < 0.5:
            return False
        moved = QtGui.QMouseEvent(ev.type(), q, QtCore.QPointF(self.vp.mapToGlobal(q.toPoint())), ev.button(),
                                  ev.buttons(), ev.modifiers())
        self.replaying = True
        try:
            QtWidgets.QApplication.sendEvent(self.vp, moved)
        finally:
            self.replaying = False
        return True

    def replay_click(self, pos):
        """Hand the cube a matched press/release pair (it never saw the swallowed press)."""
        g = QtCore.QPointF(self.vp.mapToGlobal(pos))
        self.replaying = True
        try:
            for kind, held in ((QtCore.QEvent.MouseButtonPress, QtCore.Qt.LeftButton),
                               (QtCore.QEvent.MouseButtonRelease, QtCore.Qt.NoButton)):
                QtWidgets.QApplication.sendEvent(self.vp, QtGui.QMouseEvent(
                    kind, QtCore.QPointF(pos), g, QtCore.Qt.LeftButton, held, QtCore.Qt.NoModifier))
        finally:
            self.replaying = False

    def model_center(self):
        box = App.BoundBox()
        doc = App.ActiveDocument
        for o in doc.Objects if doc else []:
            vo = getattr(o, "ViewObject", None)
            shape = getattr(o, "Shape", None)
            if vo is not None and vo.Visibility and shape is not None and not shape.isNull():
                box.add(shape.BoundBox)
        if box.isValid():
            return box.Center
        return camera_focus(self.camera())

    def px_size(self):
        """World length of one screen pixel at the focal plane."""
        cam = self.camera()
        span = min(self.vp.width(), self.vp.height()) or 1
        if hasattr(cam, "height"):
            return cam.height.getValue() / span
        return 2 * cam.focalDistance.getValue() * math.tan(cam.heightAngle.getValue() / 2) / span

    @staticmethod
    def target(info):
        """(document object, subname) usable with Gui.Selection from an object-info dict."""
        doc = App.getDocument(info["Document"])
        if info.get("ParentObject") is not None and info.get("SubName"):
            return info["ParentObject"], info["SubName"]
        return doc.getObject(info["Object"]), info.get("Component", "")

    # ------------------------------------------------------------ events
    def eventFilter(self, _obj, ev):
        t = ev.type()
        if getattr(self, "replaying", False):
            return False
        try:
            if t in (QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease) \
                    and self.snap_sketch(ev):
                return True
            if t == QtCore.QEvent.MouseButtonPress:
                return self.press(ev)
            if t == QtCore.QEvent.MouseMove:
                return self.move(ev)
            if t == QtCore.QEvent.MouseButtonRelease:
                return self.release(ev)
            if t == QtCore.QEvent.MouseButtonDblClick:
                return self.double(ev)
            if t == QtCore.QEvent.Wheel:
                return self.wheel(ev)
            if t == QtCore.QEvent.ContextMenu:       # right click is ours (radial) or the running tool's, never a stock menu
                from kovac import sketchmode
                return not in_edit() or sketchmode.in_sketch()
            if t == QtCore.QEvent.KeyPress and ev.key() == QtCore.Qt.Key_Escape and not in_edit():
                Gui.Selection.clearSelection()
        except Exception as e:  # never let an interaction bug kill the viewport, but say so
            import traceback
            global last_error
            last_error = traceback.format_exc()
            App.Console.PrintError("Kovač navigation: %s\n%s" % (e, last_error))
            from kovac import commands
            commands.report("View interaction failed: %s" % e)
        return False

    def press(self, ev):
        button, mods, pos = _BUTTONS.get(ev.button()), _mods(ev), ev.position().toPoint()
        for action, chord in bindings().items():
            if chord == (button, mods):
                self.drag = (action, pos, pos, self.start_orbit(pos) if action == "orbit" else None)
                return True
        if button == "Left" and not mods and self.in_cube(pos):
            self.drag = ("cube", pos, pos, None)     # a drag orbits; a click is replayed to the cube on release
            return True
        if button == "Right" and not mods and self.sketch_menu():
            from kovac import radial
            radial.open_at(ev.globalPosition().toPoint(), None, sketch=True)
            return True
        if button == "Right" and not mods and in_edit():
            from kovac import sketchmode
            if sketchmode.in_sketch():           # a tool is running: a drag is a menu gesture, a click ends the tool
                self.drag = ("gesture", pos, pos, ev.globalPosition().toPoint())
                return True
        if in_edit():
            return False
        if button == "Right" and not mods:
            from kovac import radial
            radial.open_at(ev.globalPosition().toPoint(), self.info_at(pos))
            return True
        if button == "Left" and not mods and kovac.prefs().GetString("LeftDrag", "select") != "select":
            kind = kovac.prefs().GetString("LeftDrag")
            self.drag = (kind, pos, pos, self.start_orbit(pos) if kind == "orbit" else None)
            return True
        if button == "Left" and not mods:
            for h in list(hooks):
                if h.press(self, pos):
                    self.drag = ("hook", pos, pos, h)
                    return True
        if button == "Left":
            if mods == {"Alt"}:
                self.pick_list(pos)
                return True
            self.drag = ("left", pos, pos, mods)
            self.press_info, self.press_pos = self.info_at(pos), pos
            self.hold.start()
            return True
        return False

    def sketch_menu(self):
        """Right click in a sketch opens the radial menu, unless a drawing tool is running
        (the sketcher shows its own cursor then, and a right click ends the tool)."""
        from kovac import sketchmode, sketchtools
        return sketchmode.in_sketch() and not sketchtools.tool_running()

    def move(self, ev):
        if not self.drag:
            if not in_edit() and not ev.buttons():
                from kovac import editor, regionpick
                pos = ev.position().toPoint()
                regionpick.hover.move(self, pos)
                for h in list(hooks):                    # on-canvas tools that light up what is under the cursor
                    if hasattr(h, "highlight"):
                        h.highlight(self, pos)
                row = editor.point_input()               # a point input: show where a click would land
                target = row.hover(self, pos) if row is not None else None
                if target:
                    self.snap_marker.show_at(*target)
                else:
                    self.snap_marker.hide()
            return False
        kind, start, last, data = self.drag
        pos = ev.position().toPoint()
        self.drag = (kind, start, pos, data)
        d = pos - last
        if kind == "gesture":
            if (pos - start).manhattanLength() > GESTURE_PX:
                from kovac import radial
                self.drag = None
                radial.open_at(data, None, sketch=True, gesture_to=ev.globalPosition().toPoint())
            return True
        if kind == "cube":
            if data is None and (pos - start).manhattanLength() <= DRAG_PX:
                return False
            if data is None:
                data = self.model_center()
                self.drag = (kind, start, pos, data)
            self.orbit(d.x(), d.y(), data)
            return True
        if kind == "hook":
            data.move(self, pos)
        elif kind == "orbit":
            self.orbit(d.x(), d.y(), data)
        elif kind == "pan":
            self.pan(d.x(), d.y())
        elif kind == "zoom":
            self.zoom(ZOOM_PER_NOTCH ** (-d.y() / 40.0), start)
        elif kind == "left" and (pos - start).manhattanLength() > DRAG_PX:
            self.hold.stop()
            self.band.crossing = pos.x() < start.x()
            self.band.rect_ = QtCore.QRect(start, pos).normalized()
            self.band.setGeometry(self.vp.rect())
            self.band.show()
            self.band.update()
        return True

    def release(self, ev):
        if not self.drag:   # e.g. the release after a double-click: still ours outside edit mode
            if ev.button() == QtCore.Qt.RightButton and in_edit():
                from kovac import sketchmode
                if sketchmode.in_sketch():       # FreeCAD's sketch menu (opened on release) never shows
                    return True
            return ev.button() == QtCore.Qt.LeftButton and not in_edit()
        kind, start, pos, data = self.drag
        self.drag = None
        if kind == "gesture":                    # no drag: the click belongs to the running tool
            g = QtCore.QPointF(data)
            QtCore.QTimer.singleShot(0, _close_stock_menu)   # FreeCAD opens its sketch menu once the tool has ended
            self.replaying = True
            try:
                for k, held in ((QtCore.QEvent.MouseButtonPress, QtCore.Qt.RightButton),
                                (QtCore.QEvent.MouseButtonRelease, QtCore.Qt.NoButton)):
                    QtWidgets.QApplication.sendEvent(self.vp, QtGui.QMouseEvent(
                        k, QtCore.QPointF(start), g, QtCore.Qt.RightButton, held, QtCore.Qt.NoModifier))
            finally:
                self.replaying = False
            return True
        if kind == "cube":
            if data is None:
                self.replay_click(start)
            return True
        if kind == "hook":
            data.release(self, pos)
        elif kind == "orbit":
            QtCore.QTimer.singleShot(500, self.clear_marker)
        elif kind == "left":
            if self.band.isVisible():
                self.band.hide()
                self.window_select(start, pos, crossing=pos.x() < start.x(), mods=data)
            elif self.hold.isActive():
                self.hold.stop()
                self.click_select(self.press_info, data)
        return True

    def double(self, ev):
        if ev.button() == QtCore.Qt.MiddleButton:          # double middle click: fit everything
            Gui.activeView().fitAll()
            return True
        if in_edit() or ev.button() != QtCore.Qt.LeftButton:
            return False
        info = self.info_at(ev.position().toPoint())
        if not info:
            return True
        obj, sub = self.target(info)
        element = sub.split(".")[-1]
        sobj = obj.getSubObject(sub[:-len(element)]) if sub[:-len(element)] else obj
        shape = getattr(sobj, "Shape", None)
        if shape is None or not element[:4] in ("Edge", "Face"):
            return True
        idx = int(element[4:])
        chain = selection.tangent_edges(shape, idx) if element.startswith("Edge") else selection.tangent_faces(shape, idx)
        prefix = sub[:-len(element)]
        for i in chain:
            Gui.Selection.addSelection(obj.Document.Name, obj.Name, "%s%s%d" % (prefix, element[:4], i))
        return True

    # ------------------------------------------------------------ selection
    def click_select(self, info, mods):
        from kovac import regionpick
        if regionpick.hover.click(mods, self, getattr(self, "press_pos", None)):   # a sketch area under the cursor
            return
        if not info:
            if not mods:
                Gui.Selection.clearSelection()
            return
        obj, sub = self.target(info)
        xyz = (info["x"], info["y"], info["z"])        # the picked point travels with the pick
        if not mods:
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(obj, sub, *xyz)
        elif "Ctrl" in mods and Gui.Selection.isSelected(obj, sub):
            Gui.Selection.removeSelection(obj, sub)
        else:
            Gui.Selection.addSelection(obj, sub, *xyz)

    def _hold_fired(self):
        if self.drag and self.drag[0] == "left":
            pos = self.drag[1]
            self.drag = None
            self.pick_list(pos)

    def pick_list(self, pos):
        seen, items = set(), []
        for info in self.view.getObjectsInfo(self.coin(pos)) or []:
            obj, sub = self.target(info)
            if (obj.Name, sub) not in seen:
                seen.add((obj.Name, sub))
                items.append((obj, sub))
        if not items:
            return
        menu = QtWidgets.QMenu(self.vp)
        for obj, sub in items:
            act = menu.addAction("%s  ·  %s" % (obj.Label, sub.split(".")[-1] or "body"))
            act.setData((obj.Document.Name, obj.Name, sub))
        menu.hovered.connect(lambda a: Gui.Selection.setPreselection(App.getDocument(a.data()[0]).getObject(a.data()[1]), a.data()[2]))
        chosen = menu.exec(self.vp.mapToGlobal(pos))
        Gui.Selection.clearPreselection()
        if chosen:
            d, o, s = chosen.data()
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(d, o, s)

    def window_select(self, a, b, crossing, mods):
        doc = App.ActiveDocument
        if not doc:
            return
        rect = (a.x(), a.y(), b.x(), b.y())
        kinds = getattr(select_filter, "kinds", None) or {"body"}
        if not mods:
            Gui.Selection.clearSelection()
        if crossing:   # anything visible under the box counts as touched
            for x in range(5):
                for y in range(5):
                    q = QtCore.QPoint(a.x() + (b.x() - a.x()) * x // 4, a.y() + (b.y() - a.y()) * y // 4)
                    info = self.info_at(q)
                    if info:
                        obj, sub = self.target(info)
                        kind = selection.classify(obj, sub)
                        if kind in kinds:
                            Gui.Selection.addSelection(obj, sub)
                        elif "body" in kinds:
                            Gui.Selection.addSelection(obj)
        for obj in doc.Objects:
            shape = getattr(obj, "Shape", None)
            vo = getattr(obj, "ViewObject", None)
            if shape is None or shape.isNull() or not (vo and vo.Visibility) or selection.classify(obj, "") != "body":
                continue
            to_world = obj.getGlobalPlacement().multiply(obj.Placement.inverse())

            def hit(element):
                pts = [self.qt(self.view.getPointOnViewport(to_world.multVec(p))) for p in selection.samples(element)]
                return selection.window_hit(pts, rect, crossing)

            if "body" in kinds and hit(shape):
                Gui.Selection.addSelection(obj)
            for kind, attr, prefix in (("face", "Faces", "Face"), ("edge", "Edges", "Edge"), ("vertex", "Vertexes", "Vertex")):
                if kind in kinds:
                    for i, el in enumerate(getattr(shape, attr), 1):
                        if hit(el):
                            Gui.Selection.addSelection(obj, "%s%d" % (prefix, i))

    # ------------------------------------------------------------ camera
    def camera(self):
        import pivy.coin  # noqa: F401  (getCameraNode needs the SWIG wrapper loaded)
        return self.view.getCameraNode()

    def start_orbit(self, pos):
        cam = self.camera()
        info = self.info_at(pos)
        if info:
            pivot = V(info["x"], info["y"], info["z"])
        elif kovac.prefs().GetString("OrbitPivot", "cursor") == "selection" and Gui.Selection.hasSelection():
            box = App.BoundBox()
            for s in Gui.Selection.getSelectionEx():
                if hasattr(s.Object, "Shape"):
                    box.add(s.Object.Shape.BoundBox)
            pivot = box.Center
        else:
            pivot = camera_focus(cam)
        self.show_marker(pivot)
        return pivot

    def orbit(self, dx, dy, pivot):
        cam = self.camera()
        pos = V(*cam.position.getValue().getValue())
        rot = App.Rotation(*cam.orientation.getValue().getValue())
        yaw, pitch = math.degrees(-dx * ORBIT_RAD_PER_PX), math.degrees(-dy * ORBIT_RAD_PER_PX)
        if kovac.prefs().GetString("OrbitMode", "free") == "turntable":
            r = App.Rotation(V(0, 0, 1), yaw).multiply(App.Rotation(rot.multVec(V(1, 0, 0)), pitch))
        else:
            r = App.Rotation(rot.multVec(V(0, 1, 0)), yaw).multiply(App.Rotation(rot.multVec(V(1, 0, 0)), pitch))
        new_pos = pivot + r.multVec(pos - pivot)
        cam.orientation.setValue(*r.multiply(rot).Q)
        cam.position.setValue(new_pos.x, new_pos.y, new_pos.z)

    def pan(self, dx, dy):
        cam = self.camera()
        rot = App.Rotation(*cam.orientation.getValue().getValue())
        span = min(self.vp.width(), self.vp.height()) or 1
        if hasattr(cam, "height"):
            per_px = cam.height.getValue() / span
        else:
            per_px = 2 * cam.focalDistance.getValue() * math.tan(cam.heightAngle.getValue() / 2) / span
        pos = V(*cam.position.getValue().getValue())
        pos += rot.multVec(V(-dx, dy, 0)) * per_px
        cam.position.setValue(pos.x, pos.y, pos.z)

    def wheel(self, ev):
        notches = ev.angleDelta().y() / 120.0
        if kovac.prefs().GetBool("InvertZoom", False):
            notches = -notches
        self.zoom(ZOOM_PER_NOTCH ** notches, ev.position().toPoint())
        return True

    def zoom(self, factor, at):
        """Scale the view by factor (<1 zooms in), keeping the point under `at` fixed."""
        cam = self.camera()
        rot = App.Rotation(*cam.orientation.getValue().getValue())
        span = min(self.vp.width(), self.vp.height()) or 1
        dx, dy = at.x() - self.vp.width() / 2, at.y() - self.vp.height() / 2
        pos = V(*cam.position.getValue().getValue())
        if hasattr(cam, "height"):
            per_px = cam.height.getValue() / span
            cam.height.setValue(cam.height.getValue() * factor)
            pos += rot.multVec(V(dx, -dy, 0)) * per_px * (1 - factor)
        else:
            fd = cam.focalDistance.getValue()
            per_px = 2 * fd * math.tan(cam.heightAngle.getValue() / 2) / span
            target = pos + rot.multVec(V(dx * per_px, -dy * per_px, -fd))
            pos = target + (pos - target) * factor
            cam.focalDistance.setValue(fd * factor)
        cam.position.setValue(pos.x, pos.y, pos.z)

    def show_marker(self, p):
        from pivy import coin
        self.clear_marker()
        sep = coin.SoAnnotation()
        col = coin.SoBaseColor()
        col.rgb = tuple(c / 255 for c in palette.rgb(palette.accent()))
        tr = coin.SoTranslation()
        tr.translation = (p.x, p.y, p.z)
        ms = coin.SoMarkerSet()
        ms.markerIndex = Gui.getMarkerIndex("CIRCLE_FILLED", 9)
        crd = coin.SoCoordinate3()
        crd.point.setValue(0, 0, 0)
        for n in (col, tr, crd, ms):
            sep.addChild(n)
        self.view.getSceneGraph().addChild(sep)
        self.marker = sep

    def clear_marker(self):
        if self.marker is not None:
            try:
                self.view.getSceneGraph().removeChild(self.marker)
            except Exception:
                pass
            self.marker = None


class _Filter:
    kinds = set()


select_filter = _Filter()


def set_filter(kinds):
    """Selection filter: empty = everything. Applied as a FreeCAD selection gate too."""
    select_filter.kinds = set(kinds)
    Gui.Selection.removeSelectionGate()
    if kinds:
        Gui.Selection.addSelectionGate(selection.Gate(kinds))


class _SelectionHighlight:
    """Translucent wash over the whole shape of every selected object, not just the clicked
    face -- layered under FreeCAD's own per-element selection colour, not replacing it (see
    overlay.shape_node). Off while sketching: 2D sketch elements have no whole-body shape."""

    def __init__(self):
        self.node, self.view = None, None

    def _clear(self):
        if self.node is not None and self.view is not None:
            from kovac import overlay
            overlay.remove(self.node, self.view)
        self.node = self.view = None

    def _refresh(self):
        self._clear()
        try:
            self._build()
        except Exception:
            pass      # a selection observer that raises can interrupt whatever called it (a
                       # cube-click's own view-snap, mid-sequence) -- never let this one do that

    def _build(self):
        if in_edit():
            return
        view = Gui.activeView()
        if view is None or not hasattr(view, "graphicsView"):
            return
        from kovac import overlay, palette
        from pivy import coin
        sep = None
        for s in Gui.Selection.getSelectionEx("*", 0):
            o = s.Object
            shape = getattr(o, "Shape", None)
            vo = getattr(o, "ViewObject", None)
            if shape is None or shape.isNull() or (vo is not None and not vo.Visibility):
                continue
            sep = sep or coin.SoSeparator()
            sep.addChild(overlay.shape_node(shape, palette.SEMANTIC["select"]))
        if sep is not None:
            self.node = overlay.add(sep, view)
            self.view = view

    def addSelection(self, *_a):
        self._refresh()

    def removeSelection(self, *_a):
        self._refresh()

    def setSelection(self, *_a):
        self._refresh()

    def clearSelection(self, *_a):
        try:
            self._clear()
        except Exception:
            pass


_sel_highlight = None


def install_selection_highlight():
    global _sel_highlight
    if _sel_highlight is None:
        _sel_highlight = _SelectionHighlight()
        Gui.Selection.addObserver(_sel_highlight)


def install(view=None):
    view = view or Gui.activeView()
    if view is None or not hasattr(view, "graphicsView"):
        return None
    vp = view.graphicsView().viewport()
    import shiboken6
    key = shiboken6.getCppPointer(vp)[0]       # the widget itself: Python wrappers of it come and go
    if key not in _installed:
        _installed[key] = Interactor(view)
        from kovac import views
        views.add_light(view)
        vp.destroyed.connect(lambda *_, k=key: _installed.pop(k, None))
    return _installed[key]


def uninstall_all():
    for it in list(_installed.values()):
        it.vp.removeEventFilter(it)
    _installed.clear()

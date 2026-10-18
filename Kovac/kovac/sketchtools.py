# SPDX-License-Identifier: LGPL-2.1-or-later
"""Kovač's additions to the sketcher's own tools.

- Polyline: FreeCAD's line tool, chained. Every finished segment starts the next one at its
  end, so each segment keeps the line tool's typed length and angle. Esc or a right click ends it.
- Polygon around a circle: FreeCAD's regular polygon (corners on the construction circle),
  turned into the circumscribed one (sides touching the circle), so the drawn radius is the
  inner radius.
- Midpoint: FreeCAD's sketcher has no constraint of its own that ties a point to the middle of
  a line or arc. A Symmetric constraint between the curve's own two endpoints, about the point,
  is exactly that (the point is forced to be their mirror centre) -- the point just needs to
  not also be driving the curve itself, or the solver is free to move the curve instead.
"""
import math
import re

import FreeCAD as App
import FreeCADGui as Gui
import Part
import Sketcher
from PySide import QtCore

_state = {"chain": False, "around": False, "count": 0, "start": 0, "first": None, "done": set(), "dims": {}}
# Curve geometry whose endpoints (PosId 1 = start, 2 = end) a midpoint can be taken between.
# A circle or full ellipse has no start/end (PosId 3 is its centre, a different thing).
_HAS_ENDPOINTS = {"Part::GeomLineSegment", "Part::GeomArcOfCircle", "Part::GeomArcOfEllipse",
                  "Part::GeomArcOfHyperbola", "Part::GeomArcOfParabola", "Part::GeomBSplineCurve"}


def circumscribe(sk, circle):
    """Sides tangent to construction circle `circle` (its radius kept) instead of corners on it.
    The corners move to a second, outer construction circle: with equal sides that keeps the
    polygon regular (sides touching a circle alone would allow a rhombus), so one side touching
    the inner circle is enough (more would be redundant). Returns the side count."""
    drop = [i for i, c in enumerate(sk.Constraints) if c.Type == "PointOnObject" and c.Second == circle]
    corners = [(sk.Constraints[i].First, sk.Constraints[i].FirstPos) for i in drop]
    c = sk.Geometry[circle]
    for i in reversed(drop):
        sk.delConstraint(i)
    outer = sk.addGeometry(Part.Circle(c.Center, App.Vector(0, 0, 1), c.Radius / math.cos(math.pi / len(corners))), True)
    hold = [sk.addConstraint(k) for k in (Sketcher.Constraint("Radius", circle, c.Radius),   # the drawn circle stays
                                          Sketcher.Constraint("DistanceX", -1, 1, circle, 3, c.Center.x),  # put while
                                          Sketcher.Constraint("DistanceY", -1, 1, circle, 3, c.Center.y))]  # the sides move
    sk.addConstraint([Sketcher.Constraint("Coincident", outer, 3, circle, 3)]
                     + [Sketcher.Constraint("PointOnObject", g, pos, outer) for g, pos in corners]
                     + [Sketcher.Constraint("Tangent", corners[0][0], circle)])     # one side; regularity does the rest
    sk.solve()
    for k in reversed(hold):
        sk.delConstraint(k)
    return len(corners)


def tool_running():
    """A sketcher tool is active: it shows its own cursor, or its settings widget is up."""
    from PySide import QtWidgets
    view = Gui.activeView()
    if view is None or not hasattr(view, "graphicsView"):
        return False
    if view.graphicsView().viewport().cursor().shape() == QtCore.Qt.BitmapCursor:
        return True
    tasks = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Tasks")
    return tasks is not None and any(w.metaObject().className() == "SketcherGui::SketcherToolDefaultWidget"
                                     and w.isVisibleTo(tasks) for w in tasks.findChildren(QtWidgets.QWidget))


def end_running():
    """Our own tools (Offset, Move) end the sketcher tool still running: drawing tools stay on
    after each shape, and left running it would keep taking the clicks meant for picking."""
    if tool_running():
        Gui.runCommand("Sketcher_StopOperation")
    stop()


def stop():
    """Another tool was picked (or the tool ended): our variants end, an open value box keeps its value."""
    _state.update(chain=False, around=False, idle=0)
    close_box()


def poll():
    """Called every few hundred ms: our variants end once their tool has been gone twice running."""
    if not (_state["chain"] or _state["around"]):
        return
    _state["idle"] = 0 if tool_running() else _state.get("idle", 0) + 1
    if _state["idle"] >= 2:
        stop()


def polyline():
    from kovac import commands
    stop()
    sk = _edited_sketch()
    _state.update(chain=True, count=len(sk.Geometry) if sk else 0, first=None, prev=None)
    commands.run("Sketcher_CreateLine")


def polygon_around():
    from kovac import commands
    stop()
    sk = _edited_sketch()
    _state.update(around=True, start=len(sk.Geometry) if sk else 0)
    commands.run("Sketcher_CreateRegularPolygon")


def add_midpoint(sk, point_geoid, point_posid, line_geoid):
    """Constrain point (point_geoid, point_posid) to the midpoint of line_geoid's own two
    endpoints. line_geoid's geometry must have distinct start/end points (checked by the
    caller; not true of a circle or full ellipse, which have none)."""
    sk.addConstraint(Sketcher.Constraint("Symmetric", line_geoid, 1, line_geoid, 2, point_geoid, point_posid))


def midpoint():
    """Kovac_ConstrainMidpoint: select one point (a free point, an endpoint of another curve,
    ...) and one line/arc, in either order, then constrain the point to the line's midpoint."""
    from kovac import commands
    sk = _edited_sketch()
    if sk is None:
        return
    point_ref, line_ref = None, None
    for sel in Gui.Selection.getSelectionEx(sk.Document.Name):
        if sel.Object is not sk:
            continue
        for name in sel.SubElementNames:
            if name.startswith("Vertex") and point_ref is None:
                gid, pid = sk.getGeoVertexIndex(int(name[len("Vertex"):]))
                if gid >= 0 and pid in (1, 2, 3):
                    point_ref = (gid, pid)
            elif name.startswith("Edge") and line_ref is None:
                gid = int(name[len("Edge"):]) - 1
                if 0 <= gid < len(sk.Geometry) and sk.Geometry[gid].TypeId in _HAS_ENDPOINTS:
                    line_ref = gid
    if point_ref is None or line_ref is None or point_ref[0] == line_ref:
        commands.report("Midpoint: select a point and a line or arc (not its own endpoint), then Midpoint.")
        return
    with commands.transaction("Midpoint constraint", sk.Document):
        add_midpoint(sk, point_ref[0], point_ref[1], line_ref)


LENGTHS = ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter")
DIMENSIONS = LENGTHS + ("Angle",)


def match_dimension(sk, source, target):
    """Make dimension `target` always equal dimension `source` (an expression on its value, so
    it follows later edits). Lengths of any kind match each other (between a radius and a
    diameter, the circles match); angles match angles. Returns a plain-language reason if it can't be done."""
    if source == target:
        return "pick two different dimensions"
    a, b = sk.Constraints[source], sk.Constraints[target]
    if a.Type not in DIMENSIONS or b.Type not in DIMENSIONS:
        return "only dimensions can be made equal"
    if (a.Type == "Angle") != (b.Type == "Angle"):
        return "a length can't equal an angle"
    if not b.Driving:
        return "the dimension to change is a reference dimension"
    src, dst = _ref(sk, source), _ref(sk, target)
    if any(path == src and dst in expr for path, expr in sk.ExpressionEngine):
        return "the first dimension already follows the second"
    expr = src
    if a.Type in ("DistanceX", "DistanceY"):          # these carry a sign
        expr = "abs(%s)" % expr
    if (a.Type, b.Type) == ("Diameter", "Radius"):     # the same circle size
        expr += " / 2"
    elif (a.Type, b.Type) == ("Radius", "Diameter"):
        expr += " * 2"
    if b.Type in ("DistanceX", "DistanceY") and b.Value < 0:
        expr = "-(%s)" % expr
    sk.setExpression(dst, expr)
    return ""


def _ref(sk, i):
    """Expression path of constraint i by name, naming it if it has none: the sketcher doesn't
    renumber '.Constraints[i]' when an earlier constraint is deleted, so a link by number
    slides onto the wrong dimension (names can't look like units, hence the underscore)."""
    c = sk.Constraints[i]
    if not c.Name:
        taken = {k.Name for k in sk.Constraints}
        n = next(k for k in range(1, len(taken) + 2) if "dim_%d" % k not in taken)
        sk.renameConstraint(i, "dim_%d" % n)
    return ".Constraints.%s" % sk.Constraints[i].Name


_REF = re.compile(r"\.Constraints(?:\.(\w+)|\[(\d+)\])")


def prune_links(sk):
    """Drop dimension links whose constraint is gone (deleted, or a stale number from an older
    file); the dimension keeps the value it has. A broken link leaves the sketch unable to
    regenerate. Returns how many went."""
    names, n = {c.Name for c in sk.Constraints if c.Name}, len(sk.Constraints)

    def gone(text):
        return any((name and name not in names) or (num and int(num) >= n)
                   for name, num in _REF.findall(text))
    dead = [path for path, expr in sk.ExpressionEngine
            if path.startswith(".Constraints") and (gone(path) or gone(expr))]
    for path in dead:
        _clear(sk, path)
    return len(dead)


def _clear(sk, path):
    """Remove the expression on path. The sketcher refuses while path names a constraint
    number past the end: stand-in constraints fill up to it for the moment."""
    try:
        sk.setExpression(path, None)
        return
    except IndexError:
        pass
    want = int(re.search(r"\[(\d+)\]", path).group(1))
    p = sk.addGeometry(Part.Point(App.Vector()), True)
    first = len(sk.Constraints)
    for _ in range(want - first + 1):
        sk.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, p, 1, 0.0))
    sk.setExpression(path, None)
    sk.delGeometry(p)                           # takes the stand-ins with it


# The sketcher's own value dialog after a new dimension is modal: nothing in the view can be
# clicked until it closes. Kovač turns it off (sketchmode.edit) and opens this box instead.
DIMENSION_TOOLS = {"Sketcher_Dimension", "Sketcher_ConstrainDistance", "Sketcher_ConstrainDistanceX",
                   "Sketcher_ConstrainDistanceY", "Sketcher_ConstrainRadius", "Sketcher_ConstrainDiameter",
                   "Sketcher_ConstrainRadiam", "Sketcher_ConstrainAngle"}
_box = []          # the open ValueBox, if any


def value_text(sk, i):
    c = sk.Constraints[i]
    if c.Type == "Angle":
        return App.Units.Quantity(math.degrees(c.Value), App.Units.Angle).UserString
    return App.Units.Quantity(abs(c.Value), App.Units.Length).UserString


def set_value(sk, i, text):
    """Dimension i takes the typed value ("25", "25 mm", "1 in", "30°"); a signed horizontal or
    vertical distance keeps its direction."""
    c = sk.Constraints[i]
    text = text.strip().replace("°", " deg")
    q = App.Units.Quantity(text)
    if q.Unit == App.Units.Unit():                     # a bare number: mm, or degrees for an angle
        q = App.Units.Quantity(text + (" deg" if c.Type == "Angle" else " mm"))
    if c.Type in ("DistanceX", "DistanceY") and c.Value < 0 < q.Value:
        q = -q
    sk.setDatum(i, q)


class ValueBox:
    """Small box by the cursor for a dimension just placed: type a value and Enter, or click a
    dimension already in the sketch to make the new one equal it. Esc, or a click anywhere else,
    keeps the measured value. The view stays live the whole time. The dimension tool pauses
    while the box is open (a running tool hides which dimension is under the cursor) and
    carries on after it closes; a click elsewhere is handed to it."""

    def __init__(self, sk, i, tool):
        from PySide import QtGui, QtWidgets
        from kovac import commands, navigation
        close_box()
        self.sk, self.i, self.tool = sk, i, tool
        self.it = navigation.install()
        if tool_running():
            Gui.runCommand("Sketcher_StopOperation")
        self.field = QtWidgets.QLineEdit(self.it.vp)
        self.field.setObjectName("kovacDimensionValue")
        self.field.setText(value_text(sk, i))
        self.field.setFixedWidth(110)
        self.field.selectAll()
        self.field.returnPressed.connect(self.typed)
        self.esc = QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Escape), self.field, lambda: self.close(True))
        self.esc.setContext(QtCore.Qt.WidgetShortcut)
        pos = self.it.vp.mapFromGlobal(QtGui.QCursor.pos()) + QtCore.QPoint(18, 18)
        self.field.move(max(0, min(pos.x(), self.it.vp.width() - 120)), max(0, min(pos.y(), self.it.vp.height() - 30)))
        self.field.show()
        self.field.setFocus()
        _box.append(self)
        commands.report("Type the value and Enter, or click a dimension to make this one equal it (Esc keeps it).",
                        error=False)

    def typed(self):
        from kovac import commands
        try:
            with commands.transaction("Set dimension", self.sk.Document):
                set_value(self.sk, self.i, self.field.text())
        except Exception as e:
            commands.report("That value doesn't fit: %s" % e)
            return
        self.close(True)

    def press(self, under, pos):
        """A left click in the view while the box is open; under = the constraint under the
        cursor. Always used: it makes the new dimension equal another, or goes on to the tool."""
        from kovac import commands
        if under is not None and under != self.i and 0 <= under < len(self.sk.Constraints) \
                and self.sk.Constraints[under].Type in DIMENSIONS:
            with commands.transaction("Equal dimensions", self.sk.Document):
                why = match_dimension(self.sk, under, self.i)
            if why:
                commands.report("Equal: %s." % why)
                return True
            commands.report("The new dimension now equals the one you clicked.", error=False)
            self.close(True)
            return True
        self.close(True, pos)
        return True

    def close(self, resume=False, click=None):
        """Close the box; resume: the dimension tool carries on (and gets click, a view point)."""
        from kovac import commands
        if self in _box:
            _box.remove(self)
        f, self.field = self.field, None
        if f is None:
            return
        f.hide()
        f.deleteLater()
        self.it.vp.setFocus()
        if resume and _edited_sketch() is self.sk:
            commands.run(self.tool)
            if click is not None:
                QtCore.QTimer.singleShot(60, lambda: _click(self.it, click))


def _click(it, q):
    """A plain left click at viewport point q, past Kovač's own handling (to the sketcher)."""
    from PySide import QtGui, QtWidgets
    g = QtCore.QPointF(it.vp.mapToGlobal(q))
    it.replaying = True
    try:
        for kind, button, held in ((QtCore.QEvent.MouseMove, QtCore.Qt.NoButton, QtCore.Qt.NoButton),
                                   (QtCore.QEvent.MouseButtonPress, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton),
                                   (QtCore.QEvent.MouseButtonRelease, QtCore.Qt.LeftButton, QtCore.Qt.NoButton)):
            QtWidgets.QApplication.sendEvent(it.vp, QtGui.QMouseEvent(kind, QtCore.QPointF(q), g, button, held,
                                                                       QtCore.Qt.NoModifier))
    finally:
        it.replaying = False


def close_box():
    for b in list(_box):
        b.close()


def open_box():
    return _box[0] if _box else None


def _placed(doc):
    """A step was committed: if a dimension tool just placed a dimension in the edited sketch,
    open the box for it. Placing is the commit (the tool's dimension follows the cursor until
    then); the counts tell a new dimension from other steps."""
    from kovac import commands
    sk = _edited_sketch()
    if sk is None or sk.Document is not doc:
        return
    n, before = len(sk.Constraints), _state["dims"].get(sk.Name)
    _state["dims"][sk.Name] = n
    if before is None or n <= before or commands.last not in DIMENSION_TOOLS or _state.get("busy") or _box:
        return
    c = sk.Constraints[n - 1]
    if c.Type in DIMENSIONS and c.Driving:
        tool = commands.last
        QtCore.QTimer.singleShot(0, lambda: _edited_sketch() is sk and len(sk.Constraints) == n
                                 and ValueBox(sk, n - 1, tool))


def _recount(doc):
    """Undo or redo: count again, so the next commit compares with what is there now."""
    sk = _edited_sketch()
    if sk is not None and sk.Document is doc:
        _state["dims"][sk.Name] = len(sk.Constraints)


def _project_from_step(sk):
    """Edges just projected from a body: from the body as it is at this sketch's step (an
    extruded sketch projecting from the live body would feed itself)."""
    from kovac import commands, projection
    try:
        if sk.Document is not None:
            with commands.transaction("Project", sk.Document):
                if projection.retarget(sk):
                    commands.report("That geometry only exists after this sketch's step, so it can't be projected here.")
    except Exception as e:
        commands.report("Projecting failed: %s" % e)
    finally:
        _state["projecting"] = False


def _edited_sketch():
    gd = Gui.ActiveDocument
    vp = gd.getInEdit() if gd else None
    return vp.Object if vp is not None and vp.Object.TypeId.startswith("Sketcher::") else None


class _Watcher:
    """Reacts when the sketch being edited gains geometry while one of our variants is on,
    or a dimension tool adds a dimension."""

    def slotCommitTransaction(self, doc):
        _placed(doc)

    def slotUndoDocument(self, doc):
        _recount(doc)

    def slotRedoDocument(self, doc):
        _recount(doc)

    def slotChangedObject(self, obj, prop):
        if prop == "ExternalGeometry" and obj is _edited_sketch() and not _state.get("projecting"):
            from kovac import model
            if any(isinstance(getattr(o, "Proxy", None), model.BodyProxy) for o, _ in obj.ExternalGeometry):
                _state["projecting"] = True        # once: the swap itself changes the list again
                QtCore.QTimer.singleShot(0, lambda: _project_from_step(obj))
        if prop == "Constraints" and obj.TypeId.startswith("Sketcher::") and obj.ExpressionEngine \
                and not _state.get("pruning"):
            _state["pruning"] = True              # after the change is complete (a delete renumbers)
            QtCore.QTimer.singleShot(0, lambda: _prune(obj))
        if prop == "Constraints" and obj is _edited_sketch():
            from kovac import commands
            if commands.last not in DIMENSION_TOOLS:     # changes by anything but a dimension tool
                _state["dims"][obj.Name] = len(obj.Constraints)
        if prop not in ("Geometry", "Constraints") or not (_state["chain"] or _state["around"]) or _state.get("busy"):
            return
        if obj is not _edited_sketch():
            return
        n = len(obj.Geometry)
        if _state["around"] and n > _state["start"]:     # only circles drawn since the variant began
            c = n - 1
            if obj.Geometry[c].TypeId == "Part::GeomCircle" and obj.getConstruction(c) and (obj.Name, c) not in _state["done"]                     and any(k.Type == "PointOnObject" and k.Second == c for k in obj.Constraints):
                _state["done"].add((obj.Name, c))
                QtCore.QTimer.singleShot(0, lambda: _around(obj, c))
        grew, _state["count"] = n > _state["count"], n     # deletions and undo never chain anything
        if _state["chain"] and grew:
            seg = obj.Geometry[-1]
            if seg.TypeId != "Part::GeomLineSegment" or obj.getConstruction(n - 1):
                return
            prev, _state["prev"] = _state.get("prev"), n - 1
            if prev is not None and prev < n - 1:      # the new segment must start where the last one ended
                QtCore.QTimer.singleShot(0, lambda: _join(obj, prev, n - 1))
            if _state["first"] is None:
                _state["first"] = seg.StartPoint
            elif (seg.EndPoint - _state["first"]).Length < 1e-6:       # closed back on its start: done
                _state["chain"] = False
                return
            QtCore.QTimer.singleShot(80, lambda: _continue_at(obj, n - 1))


def _prune(sk):
    _state["pruning"] = False
    try:
        if sk.isValid() and prune_links(sk):
            sk.recompute() if not _edited_sketch() is sk else sk.solve()
    except Exception:
        pass


def _around(sk, circle):
    _state["busy"] = True
    try:
        circumscribe(sk, circle)
        sk.solve()
        sk.recompute()
    except Exception as e:
        from kovac import commands
        commands.report("Polygon around a circle: %s" % e)
    finally:
        _state["busy"] = False
        _state["done"].add((sk.Name, len(sk.Geometry) - 1))


def _join(sk, a, b):
    """Polyline: segment b starts exactly at segment a's end, coincident. A snap that pulled
    b's start elsewhere (a grid point near an end that isn't on the grid) is undone."""
    import Sketcher
    if sk.Document is None or b >= len(sk.Geometry) or a >= len(sk.Geometry):
        return
    end = sk.getPoint(a, 2)
    joined = any(c.Type == "Coincident" and {(c.First, c.FirstPos), (c.Second, c.SecondPos)} == {(a, 2), (b, 1)}
                 for c in sk.Constraints)
    if joined and (sk.getPoint(b, 1) - end).Length < 1e-7:
        return
    _state["busy"] = True
    try:
        wrong = [i for i, c in enumerate(sk.Constraints)
                 if (c.Type == "Coincident" and (b, 1) in ((c.First, c.FirstPos), (c.Second, c.SecondPos)))
                 or (c.Type == "PointOnObject" and (c.First, c.FirstPos) == (b, 1))]
        for i in reversed(wrong):
            sk.delConstraint(i)
        sk.movePoint(b, 1, end)
        sk.addConstraint(Sketcher.Constraint("Coincident", a, 2, b, 1))
        sk.solve()
        sk.recompute()
    except Exception as e:
        from kovac import commands
        commands.report("Polyline: couldn't join the segments: %s" % e)
    finally:
        _state["busy"] = False


def _continue_at(sk, seg):
    """Click the end of the segment just drawn: the line tool starts the next one there.
    Grid snapping is off for that click (the end needn't be on the grid); snapping to the end
    point itself stays on."""
    if not _state["chain"] or not tool_running() or sk.Document is None or seg >= len(sk.Geometry):
        _state["chain"] = False
        return
    point = sk.getGlobalPlacement().multVec(sk.getPoint(seg, 2))
    from kovac import navigation
    from PySide import QtGui, QtWidgets
    it = navigation.install()
    view = Gui.activeView()
    x, y = view.getPointOnViewport(point)
    r = it.vp.devicePixelRatioF()
    q = QtCore.QPointF(x / r, it.vp.height() - y / r)
    g = QtCore.QPointF(it.vp.mapToGlobal(q.toPoint()))
    snap = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Sketcher/Snap")
    grid_on = snap.GetBool("SnapToGrid", False)
    snap.SetBool("SnapToGrid", False)
    it.replaying = True
    try:
        for kind, button, held in ((QtCore.QEvent.MouseMove, QtCore.Qt.NoButton, QtCore.Qt.NoButton),
                                   (QtCore.QEvent.MouseButtonPress, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton),
                                   (QtCore.QEvent.MouseButtonRelease, QtCore.Qt.LeftButton, QtCore.Qt.NoButton)):
            QtWidgets.QApplication.sendEvent(it.vp, QtGui.QMouseEvent(kind, q, g, button, held, QtCore.Qt.NoModifier))
    finally:
        it.replaying = False
        snap.SetBool("SnapToGrid", grid_on)


_watcher = None


def install():
    global _watcher
    if _watcher is None:
        _watcher = _Watcher()
        App.addDocumentObserver(_watcher)

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

import FreeCAD as App
import FreeCADGui as Gui
import Part
import Sketcher
from PySide import QtCore

_state = {"chain": False, "around": False, "count": 0, "start": 0, "first": None, "done": set()}
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


def stop():
    """Another tool was picked (or the tool ended): our variants end."""
    _state.update(chain=False, around=False, idle=0)


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
    _state.update(chain=True, count=len(sk.Geometry) if sk else 0, first=None)
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


def _edited_sketch():
    gd = Gui.ActiveDocument
    vp = gd.getInEdit() if gd else None
    return vp.Object if vp is not None and vp.Object.TypeId.startswith("Sketcher::") else None


class _Watcher:
    """Reacts when the sketch being edited gains geometry while one of our variants is on."""

    def slotChangedObject(self, obj, prop):
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
            if _state["first"] is None:
                _state["first"] = seg.StartPoint
            elif (seg.EndPoint - _state["first"]).Length < 1e-6:       # closed back on its start: done
                _state["chain"] = False
                return
            end = obj.getGlobalPlacement().multVec(seg.EndPoint)
            QtCore.QTimer.singleShot(80, lambda: _continue_at(end))


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


def _continue_at(point):
    """Click the end of the segment just drawn: the line tool starts the next one there."""
    if not _state["chain"] or not tool_running():
        _state["chain"] = False
        return
    from kovac import navigation
    from PySide import QtGui, QtWidgets
    it = navigation.install()
    view = Gui.activeView()
    x, y = view.getPointOnViewport(point)
    r = it.vp.devicePixelRatioF()
    q = QtCore.QPointF(x / r, it.vp.height() - y / r)
    g = QtCore.QPointF(it.vp.mapToGlobal(q.toPoint()))
    it.replaying = True
    try:
        for kind, button, held in ((QtCore.QEvent.MouseMove, QtCore.Qt.NoButton, QtCore.Qt.NoButton),
                                   (QtCore.QEvent.MouseButtonPress, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton),
                                   (QtCore.QEvent.MouseButtonRelease, QtCore.Qt.LeftButton, QtCore.Qt.NoButton)):
            QtWidgets.QApplication.sendEvent(it.vp, QtGui.QMouseEvent(kind, q, g, button, held, QtCore.Qt.NoModifier))
    finally:
        it.replaying = False


_watcher = None


def install():
    global _watcher
    if _watcher is None:
        _watcher = _Watcher()
        App.addDocumentObserver(_watcher)

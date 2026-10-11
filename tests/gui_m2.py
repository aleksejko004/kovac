# SPDX-License-Identifier: LGPL-2.1-or-later
"""M2 GUI end-to-end, run inside FreeCAD's GUI by tests/run_gui.py gui_m2.py.

The L-bracket purely through Kovač's UI: sketch on a picked plane, extrude in the panel, sketch
the wall on a picked face, holes placed by clicking, a fillet on a clicked edge, base thickness
named as a parameter and changed 5 -> 8 mm in the Parameters panel. Fillet and holes must
survive and the volume must match an independent construction. Also: open panels never block
orbiting or the tree; interaction counts for the five benchmark tasks are recorded.
"""
import json
import math
import os
import sys
import time
import traceback

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtGui, QtWidgets

V = App.Vector
OUT = os.environ["KOVAC_RESULT"]
SHOTS = os.path.join(os.path.dirname(OUT), "screens")
os.makedirs(SHOTS, exist_ok=True)
res = {"checks": [], "metrics": {}, "errors": [], "interactions": {}}
COUNT = {"clicks": 0, "keys": 0}


def check(name, ok, detail=""):
    res["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)})
    with open(OUT + ".progress", "a", encoding="utf-8") as f:      # survives a crash: shows how far it got
        f.write("%s  %s\n" % ("ok  " if ok else "FAIL", name))


def finish(code=0):
    res["passed"] = all(c["ok"] for c in res["checks"]) and not res["errors"]
    with open(OUT, "w") as f:
        json.dump(res, f, indent=1, default=str)
    os._exit(code)


sys.excepthook = lambda t, v, tb: res["errors"].append("".join(traceback.format_exception(t, v, tb)))
import faulthandler  # noqa: E402
_hang_log = open(OUT + ".hang", "w")
faulthandler.dump_traceback_later(240, file=_hang_log)    # a hang leaves the stack it is stuck in
QtCore.QTimer.singleShot(300000, lambda: (res["errors"].append("watchdog: %s" % [
    (type(w).__name__, w.windowTitle()) for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible()]), finish(3)))


# ------------------------------------------------------------------ user simulation (counted)
def view():
    return Gui.activeView()


def vp():
    return view().graphicsView().viewport()


def to_qt(p):
    r = vp().devicePixelRatioF()
    x, y = view().getPointOnViewport(p)
    return QtCore.QPoint(int(round(x / r)), int(round(vp().height() - y / r)))


def mouse(kind, pos, button=QtCore.Qt.NoButton, buttons=QtCore.Qt.NoButton, mods=QtCore.Qt.NoModifier):
    ev = QtGui.QMouseEvent(kind, QtCore.QPointF(pos), QtCore.QPointF(vp().mapToGlobal(pos)), button, buttons, mods)
    QtWidgets.QApplication.sendEvent(vp(), ev)


def click_at(p3, mods=QtCore.Qt.NoModifier):
    """User clicks the 3D point p3 in the viewport."""
    COUNT["clicks"] += 1
    q = to_qt(p3)
    mouse(QtCore.QEvent.MouseButtonPress, q, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, mods)
    mouse(QtCore.QEvent.MouseButtonRelease, q, QtCore.Qt.LeftButton, QtCore.Qt.NoButton, mods)


def press(widget):
    """User clicks a button."""
    COUNT["clicks"] += 1
    widget.click()


def command(cid):
    """User clicks a toolbar button (one click)."""
    from kovac import commands
    COUNT["clicks"] += 1
    Gui.getMainWindow().statusBar().clearMessage()
    commands.run(cid)
    msg = Gui.getMainWindow().statusBar().currentMessage()
    if msg:
        res.setdefault("messages", []).append((cid, msg))
        if "failed" in msg:
            res.setdefault("traces", []).append(commands.last_trace)


def type_into(widget, text, enter=False):
    """User types into a field (one key per character; Tab/Enter counted)."""
    COUNT["keys"] += len(text) + 1
    widget.setFocus()
    if hasattr(widget, "lineEdit") and callable(widget.lineEdit) and widget.lineEdit() is not None:
        widget.lineEdit().selectAll()
        widget.lineEdit().setText(text)
        widget.lineEdit().editingFinished.emit()
    else:
        widget.setText(text)
        if hasattr(widget, "editingFinished"):
            widget.editingFinished.emit()


def answer_dialog(text):
    """Next modal input dialog gets text + Enter."""
    def fill():
        d = QtWidgets.QApplication.activeModalWidget()
        if isinstance(d, QtWidgets.QInputDialog):
            COUNT["keys"] += len(text) + 1
            d.setTextValue(text)
            d.accept()
        else:
            QtCore.QTimer.singleShot(50, fill)
    QtCore.QTimer.singleShot(50, fill)


def editor_field(label):
    from kovac import editor
    ed = editor.current()
    form = ed.layout().itemAt(0).layout()
    for r in range(form.rowCount()):
        lab = form.itemAt(r, QtWidgets.QFormLayout.LabelRole)
        fld = form.itemAt(r, QtWidgets.QFormLayout.FieldRole)
        if lab is not None and lab.widget() is not None and lab.widget().text() == label:
            return fld.widget() if fld.widget() is not None else fld.layout()
    raise KeyError(label)


def ok_button():
    from kovac import editor
    return [b for b in editor.current().findChildren(QtWidgets.QPushButton) if b.text() == "OK"][0]


def shot(name):
    mw = Gui.getMainWindow()
    img = mw.grab().toImage()
    if view() is not None and hasattr(view(), "saveImage") and vp().isVisible():
        w = vp()
        r = w.devicePixelRatioF()
        tmp = os.path.join(SHOTS, "_3d.png")
        view().saveImage(tmp, int(w.width() * r), int(w.height() * r), "Current")
        p = QtGui.QPainter(img)
        p.drawImage(QtCore.QRect(w.mapTo(mw, QtCore.QPoint(0, 0)), w.size()), QtGui.QImage(tmp))
        origin = mw.mapToGlobal(QtCore.QPoint(0, 0))
        for top in QtWidgets.QApplication.allWidgets():
            if top is not mw and top.isWindow() and top.isVisible() and top.objectName().startswith("kovac"):
                p.drawPixmap(top.mapToGlobal(QtCore.QPoint(0, 0)) - origin, top.grab())
        for top in mw.findChildren(QtWidgets.QFrame, "kovacBrowser"):     # see-through overlay: no window background
            if top.isVisible():
                top.render(p, top.mapTo(mw, QtCore.QPoint(0, 0)), QtGui.QRegion(), QtWidgets.QWidget.RenderFlag.DrawChildren)
        p.end()
        os.remove(tmp)
    img.save(os.path.join(SHOTS, name + ".png"))


def looks_along(d):
    """The camera looks from direction d (model -> camera)."""
    got = V(*view().getViewDirection())
    return (got + V(*d).normalize()).Length < 1e-3, tuple(round(x, 3) for x in got)


def settle(cond, timeout_ms=4000, step=100):
    """Wait (yielding to the event loop) until cond() holds or the time runs out; the app gets slow
    under load, a fixed pause is either too long or too short."""
    for _ in range(timeout_ms // step):
        if cond():
            return
        yield step


def bodies():
    from kovac import model
    return [b for b in model.bodies(App.ActiveDocument) if not b.Shape.isNull()]


def task(name):
    """Start counting interactions for a benchmark task."""
    COUNT["clicks"] = COUNT["keys"] = 0
    res["interactions"][name] = COUNT


def end_task(name):
    res["interactions"][name] = dict(COUNT)


# ------------------------------------------------------------------ scenario
def scenario():
    from kovac import commands, editor, model, navigation, params, sketchmode, views
    mw = Gui.getMainWindow()
    mw.showMaximized()
    yield 600
    commands.run("Kovac_NewDesign")
    yield 400
    navigation.install()
    view().setCameraType("Orthographic")
    views.go(view(), views.view_rotation(views.ISO))
    yield 400

    # -- layout: big mode button, group names under their buttons, no stock navigation picker
    mb = mw.findChild(QtWidgets.QToolButton, "kovacModeButton")
    check("the big mode button shows the mode", mb is not None and mb.isVisible() and mb.text() == "DESIGN", mb and mb.text())
    ribbon = mw.findChild(QtWidgets.QToolBar, "kovacGroup_Design_0")
    below = []
    for grp in ribbon.findChildren(QtWidgets.QWidget, "kovacRibbonGroup"):
        lab = grp.findChild(QtWidgets.QLabel, "kovacGroupLabel")
        btns = grp.findChildren(QtWidgets.QToolButton)
        below.append(bool(btns) and lab.geometry().top() >= max(b.geometry().bottom() for b in btns) - 1)
    check("group names sit under their buttons", len(below) >= 7 and all(below), below)
    nav = mw.statusBar().findChild(QtWidgets.QWidget, "NavigationIndicator")
    check("FreeCAD's navigation-style picker is hidden", nav is None or not nav.isVisible())
    # an older profile's toolbar layout is put back into Kovač's rows
    from kovac import shell
    app_bar = mw.findChild(QtWidgets.QToolBar, "kovacAppBar")
    mw.addToolBar(QtCore.Qt.TopToolBarArea, app_bar)               # app bar dragged after the command row
    yield 100
    shell.arrange()
    yield 200
    check("Kovač's rows are restored over an old layout",
          app_bar.geometry().bottom() <= mb.parentWidget().geometry().top() + 1 and mb.parentWidget() is mw.findChild(QtWidgets.QToolBar, "kovacModes"),
          (app_bar.geometry(), mb.parentWidget().geometry()))

    # -- task 1: sketch a 60 x 40 rectangle on XY (benchmark task: 40 x 20; same click count)
    task("sketch rectangle on XY")
    views.go(view(), views.view_rotation((0, -1, 0)))       # start from some other view
    yield 400
    command("Kovac_Sketch")
    yield 500
    check("Sketch turns to the top-front-right overview", *looks_along(views.ISO))
    click_at(V(8, -8, 0))                     # pick the XY plane where nothing is in front of it
    yield from settle(lambda: sketchmode.in_sketch() and looks_along((0, 0, 1))[0])
    yield 300                                 # the ribbon lays itself out
    sk = App.ActiveDocument.getObject("Sketch")
    check("clicking the XY plane opens a sketch on it", sk is not None and sketchmode.in_sketch())
    check("the camera faces the sketch", *looks_along((0, 0, 1)))
    bar = mw.findChild(QtWidgets.QToolBar, "kovacSketchBar")
    acts = {a.objectName(): a for a in bar.findChildren(QtGui.QAction) if a.objectName().startswith(("Sketcher_", "Kovac_"))}
    want = {"Sketcher_CreateLine", "Sketcher_CreateRectangle", "Sketcher_CreateCircle", "Sketcher_Dimension",
            "Sketcher_ConstrainCoincident", "Sketcher_ConstrainHorizontal", "Sketcher_ConstrainTangent", "Sketcher_Trimming"}
    ribbon_buttons = [b for b in bar.findChildren(QtWidgets.QToolButton) if b.defaultAction() in acts.values()]
    hidden = [b.defaultAction().objectName() for b in ribbon_buttons if not b.isVisible()]
    check("the sketch ribbon shows every tool (51, variants behind arrows), none cut off",
          want <= set(acts) and len(acts) >= 51 and len(ribbon_buttons) >= 30 and not hidden,
          (len(acts), len(ribbon_buttons), hidden, sorted(want - set(acts))))
    yield 400                                 # the task panel watcher runs every 300 ms
    tasks = mw.findChild(QtWidgets.QDockWidget, "Tasks")
    check("the sketcher's task panel stays closed", tasks is None or not tasks.isVisible())
    # a line from the ribbon: clicks near grid points land on them, clicks between them stay put
    from kovac import grid, radial, sketchtools
    g = sk.ViewObject.GridSize.Value
    it = navigation.install()

    def clicks(points, button=QtCore.Qt.LeftButton):
        for p in points:
            q = to_qt(p)
            mouse(QtCore.QEvent.MouseMove, q)
            yield 60
            mouse(QtCore.QEvent.MouseButtonPress, q, button, button)
            mouse(QtCore.QEvent.MouseButtonRelease, q, button, QtCore.Qt.NoButton)
            yield 150

    def new_since(n):
        return [(tuple(x.StartPoint), tuple(x.EndPoint)) for x in sk.Geometry[n:] if hasattr(x, "StartPoint")]

    def on_grid(v):
        return all(abs(c / g - round(c / g)) < 1e-6 for c in v[:2])
    check("between grid points the cursor is left alone", grid.sketch_target(it, to_qt(V(2.5 * g, 1.5 * g, 0))) is None)
    n0 = len(sk.Geometry)
    acts["Sketcher_CreateLine"].trigger()
    yield 200
    yield from clicks([V(2.06 * g, 0.95 * g, 0), V(5.94 * g, 3.05 * g, 0), V(1.04 * g, 4.96 * g, 0), V(3.05 * g, 6.03 * g, 0)])
    Gui.runCommand("Sketcher_StopOperation")
    yield 200
    drawn = new_since(n0)
    check("a line drawn by clicking near grid points lands on them", drawn and on_grid(drawn[0][0]) and on_grid(drawn[0][1]), (g, drawn))
    check("the line tool stays on for the next line", len(drawn) == 2, drawn)
    # polyline: each segment starts where the last one ended
    n1 = len(sk.Geometry)
    acts["Kovac_Polyline"].trigger()
    yield 200
    yield from clicks([V(-6 * g, 1 * g, 0), V(-3 * g, 1 * g, 0), V(-3 * g, 4 * g, 0)])
    Gui.runCommand("Sketcher_StopOperation")
    yield 200
    chain = new_since(n1)
    check("polyline: connected segments from the line tool", len(chain) == 2 and chain[0][1] == chain[1][0], chain)
    # polygon around a circle: the drawn radius is where the sides touch
    n2 = len(sk.Geometry)

    def accept_sides(tries=20):
        d = QtWidgets.QApplication.activeModalWidget()
        if d is not None:
            d.accept()
        elif tries:
            QtCore.QTimer.singleShot(50, lambda: accept_sides(tries - 1))
    QtCore.QTimer.singleShot(50, accept_sides)
    acts["Kovac_PolygonAround"].trigger()
    yield 400
    yield from clicks([V(-8 * g, -6 * g, 0), V(-6 * g, -6 * g, 0)])
    Gui.runCommand("Sketcher_StopOperation")
    yield 300
    circles = [x for x in sk.Geometry[n2:] if x.TypeId == "Part::GeomCircle"]
    sides = [x for x in sk.Geometry[n2:] if x.TypeId == "Part::GeomLineSegment"]
    inner = min(circles, key=lambda c: c.Radius) if circles else None
    touch = inner is not None and sides and all(
        abs(((x.StartPoint + x.EndPoint) * 0.5 - inner.Center).Length - inner.Radius) < 1e-6 for x in sides)
    check("polygon around a circle: its sides touch the drawn circle", touch and abs(inner.Radius - 2 * g) < 1e-6,
          inner and (inner.Radius, len(sides)))
    # right click (no tool running) opens the radial menu with the sketch's own ring
    c0 = to_qt(V(-3 * g, -3 * g, 0))
    mouse(QtCore.QEvent.MouseButtonPress, c0, QtCore.Qt.RightButton, QtCore.Qt.RightButton)
    yield 150
    menu = radial._menu
    check("right click in a sketch: ring with delete left, move = sketch move, finish sketch",
          menu is not None and menu.isVisible() and menu.slots[6] == "Kovac_Delete" and menu.slots[3] == "Sketcher_Translate"
          and menu.slots[5] == "Kovac_FinishSketch", menu and menu.slots)
    if menu is not None:
        menu.close()
    mouse(QtCore.QEvent.MouseButtonRelease, c0, QtCore.Qt.RightButton, QtCore.Qt.NoButton)
    yield 100
    # while a tool runs: a right drag opens the menu mid-gesture; a plain right click ends the tool
    acts["Sketcher_CreateLine"].trigger()
    yield 200
    mouse(QtCore.QEvent.MouseMove, c0)
    yield 60
    mouse(QtCore.QEvent.MouseButtonPress, c0, QtCore.Qt.RightButton, QtCore.Qt.RightButton)
    mouse(QtCore.QEvent.MouseMove, c0 - QtCore.QPoint(20, 0), QtCore.Qt.NoButton, QtCore.Qt.RightButton)
    yield 60
    menu = radial._menu
    if menu is not None and menu.isVisible():       # from here Qt hands the moves to the open menu
        far = menu.mapFromGlobal(vp().mapToGlobal(c0 - QtCore.QPoint(70, 0)))
        QtWidgets.QApplication.sendEvent(menu, QtGui.QMouseEvent(QtCore.QEvent.MouseMove, QtCore.QPointF(far),
                                         QtCore.QPointF(menu.mapToGlobal(far)), QtCore.Qt.NoButton, QtCore.Qt.RightButton,
                                         QtCore.Qt.NoModifier))
        yield 60
    gesture = menu is not None and menu.isVisible() and menu.hover == 6
    check("right drag while drawing opens the menu, aimed at Delete (left)", gesture, menu and (menu.isVisible(), menu.hover))
    if menu is not None:
        menu.close()
    yield 100
    acts["Sketcher_CreateLine"].trigger()
    yield 200
    mouse(QtCore.QEvent.MouseMove, c0)
    yield 60
    mouse(QtCore.QEvent.MouseButtonPress, c0, QtCore.Qt.RightButton, QtCore.Qt.RightButton)
    mouse(QtCore.QEvent.MouseButtonRelease, c0, QtCore.Qt.RightButton, QtCore.Qt.NoButton)
    yield 200
    check("a plain right click while drawing still ends the tool", not sketchtools.tool_running())
    for _ in range(len(sk.Geometry) - n0):
        sk.delGeometry(n0)
    sk.recompute()
    yield 100

    # every sketch tool snaps the same way, and the marker shows it
    import pivy.coin  # noqa: F401
    cam = view().getCameraNode()
    saved = (cam.height.getValue(), cam.position.getValue().getValue())
    cam.height.setValue(340)
    cam.position.setValue(200, 140, 100)
    grid.refresh(force=True)
    yield 400
    g = sk.ViewObject.GridSize.Value
    mouse(QtCore.QEvent.MouseMove, to_qt(V(5.04 * g, 9.03 * g, 0)))
    yield 60
    on_grid_marker = it.snap_marker.isVisible() and it.snap_marker.kind == "grid"
    mouse(QtCore.QEvent.MouseMove, to_qt(V(0.02 * g, 0.03 * g, 0)))
    yield 60
    on_point_marker = it.snap_marker.isVisible() and it.snap_marker.kind == "point"
    mouse(QtCore.QEvent.MouseMove, to_qt(V(5.5 * g, 9.5 * g, 0)))
    yield 60
    check("snap marker: shows on a grid point, marks an existing point, hides in between",
          on_grid_marker and on_point_marker and not it.snap_marker.isVisible(), (on_grid_marker, on_point_marker, it.snap_marker.isVisible()))
    tools = [("Sketcher_CreateLine", [(1, 1), (4, 2)]), ("Sketcher_CreateRectangle", [(6, 1), (9, 3)]),
             ("Sketcher_CreateRectangle_Center", [(12, 2), (14, 3)]), ("Sketcher_CreateCircle", [(17, 2), (19, 2)]),
             ("Kovac_Polyline", [(1, 5), (4, 5), (4, 8)]), ("Sketcher_CreateOblong", [(6, 5), (9, 7), (9, 7)]),
             ("Sketcher_CreateArc", [(12, 6), (14, 6), (12, 8)]), ("Sketcher_Create3PointCircle", [(17, 6), (19, 6), (18, 7)]),
             ("Sketcher_Create3PointArc", [(1, 10), (3, 10), (2, 11)]), ("Sketcher_CreateSlot", [(5, 10), (8, 10), (8, 11)]),
             ("Sketcher_CreateEllipseByCenter", [(11, 11), (14, 11), (11, 12)]), ("Sketcher_CreatePoint", [(19, 13)]),
             ("Sketcher_CreateRegularPolygon", [(16, 10), (18, 10)]), ("Kovac_PolygonAround", [(2, 13), (4, 13)])]
    derived = {"Sketcher_CreateRegularPolygon", "Kovac_PolygonAround", "Sketcher_CreateEllipseByCenter"}  # make own off-grid points
    off_grid = {}
    for cid, cl in tools:
        n3 = len(sk.Geometry)
        if "Polygon" in cid:
            QtCore.QTimer.singleShot(300, accept_sides)
        acts[cid].trigger()
        yield 500
        yield from clicks([V((x + 0.04) * g, (y - 0.03) * g, 0) for x, y in cl])
        Gui.runCommand("Sketcher_StopOperation")
        yield 250
        pts = {tuple(round(c, 6) for c in v[:2]) for x in sk.Geometry[n3:] for v in
               [getattr(x, a) for a in ("StartPoint", "EndPoint", "Center") if hasattr(x, a)] +
               ([V(x.X, x.Y, 0)] if x.TypeId == "Part::GeomPoint" else [])}
        want = {(round(x * g, 6), round(y * g, 6)) for x, y in cl[:1 if cid == "Kovac_PolygonAround" else 2]}  # its 2nd click sets the radius
        bad = sorted(want - pts) if cid in derived else sorted(q for q in pts if not on_grid(q))
        if not pts or bad:
            off_grid[cid] = (bad or "nothing drawn", sorted(pts)[:8], len(sk.Geometry) - n3)
    check("all sketch tools: clicks near grid points land exactly on them", not off_grid, off_grid)
    for _ in range(len(sk.Geometry) - n0):
        sk.delGeometry(n0)
    sk.recompute()
    cam.height.setValue(saved[0])
    cam.position.setValue(*saved[1])
    grid.refresh(force=True)
    yield 300
    # drawing itself happens in FreeCAD's sketcher (2 clicks for a 2-point rectangle + 2 typed
    # dimensions with Tab); the geometry is added the way that tool adds it:
    import Sketcher
    pts = [V(0, 0, 0), V(60, 0, 0), V(60, 40, 0), V(0, 40, 0)]
    for i in range(4):
        sk.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]))
    for i in range(4):
        sk.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
    for c in (Sketcher.Constraint("Horizontal", 0), Sketcher.Constraint("Horizontal", 2), Sketcher.Constraint("Vertical", 1),
              Sketcher.Constraint("Vertical", 3), Sketcher.Constraint("Coincident", 0, 1, -1, 1),
              Sketcher.Constraint("DistanceX", 0, 1, 0, 2, 60), Sketcher.Constraint("DistanceY", 1, 1, 1, 2, 40)):
        sk.addConstraint(c)
    COUNT["clicks"] += 3                      # rectangle tool + 2 corners
    COUNT["keys"] += len("60") + 1 + len("40") + 1
    yield 200
    shot("01_sketch")
    finish_btn = mw.findChild(QtWidgets.QPushButton, "kovacFinish")
    press(finish_btn)
    yield from settle(lambda: not sketchmode.in_sketch() and looks_along(views.ISO)[0])
    yield 200
    check("Finish Sketch leaves sketch mode", not sketchmode.in_sketch())
    check("finishing returns to the top-front-right overview", *looks_along(views.ISO))
    end_task("sketch rectangle on XY")

    # -- task 2: extrude it (the finished sketch is preselected)
    # hovering the closed rectangle shades it; a click selects that area for the next feature
    from kovac import regionpick
    inside = to_qt(V(30, 20, 0))
    mouse(QtCore.QEvent.MouseMove, inside)
    yield 100
    check("hovering a sketch's closed area shades it", regionpick.hover.current is not None and regionpick.hover.node is not None)
    mouse(QtCore.QEvent.MouseButtonPress, inside, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton)
    mouse(QtCore.QEvent.MouseButtonRelease, inside, QtCore.Qt.LeftButton, QtCore.Qt.NoButton)
    yield 100
    picked = dict(regionpick.hover.picked.get(sk.Name, {}))
    check("clicking it selects the area", len(picked) == 1 and Gui.Selection.isSelected(sk), picked)

    task("extrude 10 mm")
    command("Kovac_Extrude")
    yield 300
    ed = editor.current()
    check("Extrude panel opens with the sketch as profile", ed is not None and ed.fp.Profile is sk)
    check("the clicked area is the extrude's profile", list(ed.fp.Regions) == list(picked), list(ed.fp.Regions))
    check("extent, direction and result are icon choices",
          all(isinstance(editor_field(n), editor.IconChoice) for n in ("Extent", "Direction")))
    type_into(editor_field("Distance"), "5 mm")
    yield 700                                 # the arrow redraws at the new distance
    # the arrow drags the distance
    from kovac import navigation
    arrow = next(h for h in navigation.hooks if type(h).__name__ == "Arrow")
    o, n = arrow.axis
    a0 = to_qt(o + n * 5)
    mouse(QtCore.QEvent.MouseButtonPress, a0, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton)
    for k in range(1, 6):
        mouse(QtCore.QEvent.MouseMove, a0 - QtCore.QPoint(0, 12 * k), QtCore.Qt.NoButton, QtCore.Qt.LeftButton)
        yield 40
    mouse(QtCore.QEvent.MouseButtonRelease, a0 - QtCore.QPoint(0, 60), QtCore.Qt.LeftButton, QtCore.Qt.NoButton)
    yield 200
    dragged = ed.fp.Length.Value
    check("dragging the arrow changes the distance", dragged > 6, dragged)
    ed.set("Length", 5)
    yield 300
    # panels never block the view or the tree
    c = QtCore.QPoint(vp().width() // 2, vp().height() // 2)
    import pivy.coin  # noqa: F401
    r0 = App.Rotation(*view().getCameraNode().orientation.getValue().getValue())
    mouse(QtCore.QEvent.MouseButtonPress, c, QtCore.Qt.MiddleButton, QtCore.Qt.MiddleButton, QtCore.Qt.ShiftModifier)
    mouse(QtCore.QEvent.MouseMove, c + QtCore.QPoint(40, 10), QtCore.Qt.NoButton, QtCore.Qt.MiddleButton, QtCore.Qt.ShiftModifier)
    mouse(QtCore.QEvent.MouseButtonRelease, c + QtCore.QPoint(40, 10), QtCore.Qt.MiddleButton, QtCore.Qt.NoButton, QtCore.Qt.ShiftModifier)
    r1 = App.Rotation(*view().getCameraNode().orientation.getValue().getValue())
    check("orbit works while a panel is open", abs(r0.Angle - r1.Angle) > 1e-4 or (r0.Axis - r1.Axis).Length > 1e-4)
    from kovac import shell
    tree = shell._ui["tree"].widget()
    check("tree responds while a panel is open", tree.isEnabled() and not QtWidgets.QApplication.activeModalWidget())
    views.go(view(), views.view_rotation(views.ISO), fit=True)
    yield 400
    shot("02_extrude_panel")
    press(ok_button())
    yield 400
    ex = ed.fp
    check("extrude made a 60 x 40 x 5 body", len(bodies()) == 1 and abs(bodies()[0].Shape.Volume - 12000) < 1e-6,
          [b.Shape.Volume for b in bodies()])
    end_task("extrude 10 mm")

    # name the thickness: Parameters panel, double-click the value's name, type a name
    command("Kovac_Parameters")
    yield 300
    pw = mw.findChild(QtWidgets.QDockWidget, "kovacParams").widget()
    item = next(it for it in [pw.model.topLevelItem(i).child(j) for i in range(pw.model.topLevelItemCount())
                              for j in range(pw.model.topLevelItem(i).childCount())]
                if it.data(0, QtCore.Qt.UserRole) == "%s.Length" % ex.Name)
    answer_dialog("Thickness")
    pw.model_clicked(item, 1)
    COUNT["clicks"] += 2
    yield 400
    check("'Thickness' became a user parameter driving the extrude",
          "Thickness" in params.user_params(App.ActiveDocument) and params.expression(ex, "Length") == "Parameters.Thickness")

    # -- wall: pick the top face, sketch on it, extrude up
    views.go(view(), views.view_rotation(views.ISO), fit=True)
    yield 400
    Gui.Selection.clearSelection()
    click_at(V(40, 20, 5))
    yield 100
    command("Kovac_Sketch")
    yield 500
    wsk = App.ActiveDocument.getObject("Sketch001")
    check("sketch on a picked face", wsk is not None and abs(wsk.getGlobalPlacement().Base.z - 5) < 1e-6,
          wsk.getGlobalPlacement() if wsk else (mw.statusBar().currentMessage(),
                                                [(x.Object.Name, x.SubElementNames) for x in Gui.Selection.getSelectionEx("", 0)],
                                                [o.Name for o in App.ActiveDocument.Objects]))
    wp = [V(0, 0, 0), V(6, 0, 0), V(6, 40, 0), V(0, 40, 0)]
    for i in range(4):
        wsk.addGeometry(Part.LineSegment(wp[i], wp[(i + 1) % 4]))
    for i in range(4):
        wsk.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
    yield 200
    press(mw.findChild(QtWidgets.QPushButton, "kovacFinish"))
    yield 400
    command("Kovac_Extrude")
    yield 300
    type_into(editor_field("Distance"), "35 mm")
    yield 300
    check("wall extrude infers Join", "Join" in editor.current().fp.ResolvedOperation, editor.current().fp.ResolvedOperation)
    press(ok_button())
    yield 400

    # -- holes: pick the base top face, then click two centres
    views.go(view(), views.view_rotation(views.ISO), fit=True)
    yield 400
    Gui.Selection.clearSelection()
    click_at(V(40, 30, 5))
    yield 100
    command("Kovac_Hole")
    yield 300
    click_at(V(25, 20, 5))
    yield 400
    click_at(V(45, 20, 5))
    yield 300
    hole = editor.current().fp
    check("two hole centres placed by clicking, snapped to the grid",
          len(hole.Positions) == 2 and {(round(v.x, 6), round(v.y, 6)) for v in hole.Positions} == {(25, 20), (45, 20)},
          (list(hole.Positions), navigation.last_error[-600:] if navigation.last_error else "", mw.statusBar().currentMessage(), commands.last_trace[-400:]))
    tt = editor_field("Through all")
    tt.setChecked(True)
    COUNT["clicks"] += 1
    yield 300
    press(ok_button())
    yield 400

    # -- fillet: click the inner bend edge
    Gui.Selection.clearSelection()
    click_at(V(6, 20, 5))
    yield 100
    picked = [n for s in Gui.Selection.getSelectionEx("", 0) for n in s.SubElementNames]
    check("clicking the bend picks an edge", picked and picked[0].split(".")[-1].startswith("Edge"), picked)
    command("Kovac_Fillet")
    yield 300
    type_into(editor_field("Radius"), "3 mm")
    yield 300
    press(ok_button())
    yield 500
    shot("03_bracket")

    def reference(t):
        r = Part.makeBox(60, 40, t).fuse(Part.makeBox(6, 40, 35, V(0, 0, t))).removeSplitter()
        for x in (25, 45):
            r = r.cut(Part.makeCylinder(2.75, 200, V(x, 20, -100)))
        r = r.removeSplitter()
        e = [e for e in r.Edges if all(abs(v.Point.x - 6) < 1e-6 and abs(v.Point.z - t) < 1e-6 for v in e.Vertexes)]
        return r.makeFillet(3, e)
    vol5 = bodies()[0].Shape.Volume
    check("bracket at thickness 5 matches the reference", abs(vol5 - reference(5).Volume) < 1e-4, (vol5, reference(5).Volume))

    # -- change the parameter in the Parameters panel: 5 -> 8 mm
    pw.refresh()
    row = next(r for r in range(pw.user.rowCount()) if pw.user.item(r, 0).text() == "Thickness")
    cell = pw.user.item(row, 1)
    COUNT["clicks"] += 2
    COUNT["keys"] += len("8 mm") + 1
    cell.setText("8 mm")
    yield 800
    healthy = [(o.Label, o.Status) for o in model.items(App.ActiveDocument) if model.is_feature(o) and o.Status]
    vol8 = bodies()[0].Shape.Volume
    check("thickness 5 -> 8: every feature still healthy", not healthy, healthy)
    check("thickness 5 -> 8: fillet and holes survive, volume matches the reference",
          abs(vol8 - reference(8).Volume) < 1e-4, (vol8, reference(8).Volume))
    check("holes and fillet still there", len([f for f in bodies()[0].Shape.Faces if isinstance(f.Surface, Part.Cylinder)]) == 3)
    views.go(view(), views.view_rotation(views.ISO), fit=True)
    yield 400
    shot("04_thickness_8")

    # -- timeline: rollback, edit with error state
    tl = shell._ui["timeline"].widget()
    tl.step("start")
    yield 300
    check("rolling back to the start hides the model", not bodies())
    tl.step("end")
    yield 300
    check("rolling forward restores it", len(bodies()) == 1 and abs(bodies()[0].Shape.Volume - vol8) < 1e-6)

    # -- benchmark tasks 3-5 on a fresh 40 x 20 x 10 block (counted)
    commands.run("Kovac_NewDesign")
    yield 300
    navigation.install()
    views.go(view(), views.view_rotation(views.ISO))
    from kovac import features, modify
    doc = App.ActiveDocument
    with commands.transaction("setup", doc):
        s = doc.addObject("Sketcher::SketchObject", "Sketch")
        for i, (a, b) in enumerate(((0, 0), (40, 0), (40, 20), (0, 20))):
            pass
        q = [V(0, 0, 0), V(40, 0, 0), V(40, 20, 0), V(0, 20, 0)]
        for i in range(4):
            s.addGeometry(Part.LineSegment(q[i], q[(i + 1) % 4]))
        model.insert(doc, s)
        model.create(doc, features.Extrude, Profile=s, Length=10)
        model.commit(doc)
    views.go(view(), views.view_rotation(views.ISO), fit=True)
    yield 400
    task("fillet 4 edges at 2 mm")
    Gui.Selection.clearSelection()
    click_at(V(20, 10, 10))                   # the top face: its four edges
    yield 100
    command("Kovac_Fillet")
    yield 200
    type_into(editor_field("Radius"), "2")
    press(ok_button())
    yield 300
    end_task("fillet 4 edges at 2 mm")
    ref = Part.makeBox(40, 20, 10)
    ref = ref.makeFillet(2, [f for f in ref.Faces if f.CenterOfMass.z > 9.99][0].Edges)
    check("benchmark fillet applied", abs(bodies()[0].Shape.Volume - ref.Volume) < 1e-4, (bodies()[0].Shape.Volume, ref.Volume))
    task("add an M5 tapped hole")
    Gui.Selection.clearSelection()
    click_at(V(20, 10, 10))                   # the top face (a side-wall hole leaves no room for a 2 mm wall)
    yield 100
    command("Kovac_Hole")
    yield 200
    click_at(V(20.4, 10.3, 10))               # near the centre: snaps onto it
    yield 100
    hole_type = editor_field("Type")
    COUNT["clicks"] += 2
    hole_type.setCurrentText("Tapped")
    yield 200
    press(ok_button())
    yield 300
    end_task("add an M5 tapped hole")
    holes = [o for o in model.items(App.ActiveDocument) if getattr(o, "Thread", "") == "M5x0.8"]
    check("benchmark tapped hole at the face centre", holes and [(round(v.x, 6), round(v.y, 6)) for v in holes[0].Positions] == [(20, 10)],
          holes and list(holes[0].Positions))
    task("shell the part at 2 mm")
    Gui.Selection.clearSelection()
    click_at(V(30, 15, 10))
    yield 100
    command("Kovac_Shell")
    yield 200
    press(ok_button())
    yield 400
    end_task("shell the part at 2 mm")
    sh = [o for o in model.items(App.ActiveDocument) if getattr(o, "Kind", "") == "Shell"][0]
    check("benchmark shell applied", sh.Status == "", sh.Status)
    # Delete on a whole body takes it out as one undo step
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(bodies()[0])
    commands.run("Kovac_Delete")
    yield 300
    gone = not bodies()
    App.ActiveDocument.undo()
    yield 300
    check("Delete removes a selected body; undo brings it back", gone and len(bodies()) == 1, (gone, len(bodies())))
    shot("05_benchmark_part")


def run(gen):
    try:
        delay = next(gen)
    except StopIteration:
        for d in list(App.listDocuments()):
            App.closeDocument(d)
        finish(0)
        return
    except Exception:
        res["errors"].append(traceback.format_exc())
        finish(1)
        return
    QtCore.QTimer.singleShot(delay, lambda: run(gen))


QtCore.QTimer.singleShot(400, lambda: run(scenario()))

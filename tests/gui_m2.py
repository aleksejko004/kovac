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
from PySide6 import QtTest     # FreeCAD's PySide shim has no QtTest; real key clicks go through the shortcut map

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


def click_widget(w, pos, mods=QtCore.Qt.NoModifier):
    """A left click delivered to a widget the way Qt hands it one (press, release)."""
    for t, held in ((QtCore.QEvent.MouseButtonPress, QtCore.Qt.LeftButton), (QtCore.QEvent.MouseButtonRelease, QtCore.Qt.NoButton)):
        QtWidgets.QApplication.sendEvent(w, QtGui.QMouseEvent(t, QtCore.QPointF(pos), QtCore.QPointF(w.mapToGlobal(pos)),
                                                              QtCore.Qt.LeftButton, held, mods))


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
def setup():
    from kovac import commands, navigation, views
    mw = Gui.getMainWindow()
    mw.showMaximized()
    if mw.screen().availableGeometry().width() < 1700:     # CI screens: the ribbon is laid out for 1700 px
        mw.showNormal()
        mw.setGeometry(0, 30, 1920, 1050)
    yield 600
    commands.run("Kovac_NewDesign")
    yield 400
    navigation.install()
    view().setCameraType("Orthographic")
    views.go(view(), views.view_rotation(views.ISO))
    yield 400


def seg_bracket():
    """The L-bracket through the UI, panels, parameters, timeline, browser, sketch tools."""
    from kovac import commands, curve3d, editor, features, model, move, navigation, params, sketchmode, views  # noqa: F401
    mw = Gui.getMainWindow()  # noqa: F841
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
            "Sketcher_ConstrainCoincident", "Sketcher_ConstrainHorizontal", "Sketcher_ConstrainTangent",
            "Sketcher_Trimming", "Kovac_ConstrainMidpoint"}
    ribbon_buttons = [b for b in bar.findChildren(QtWidgets.QToolButton) if b.defaultAction() in acts.values()]
    hidden = [b.defaultAction().objectName() for b in ribbon_buttons if not b.isVisible()]
    check("the sketch ribbon shows every tool (52, variants behind arrows), none cut off",
          want <= set(acts) and len(acts) >= 52 and len(ribbon_buttons) >= 30 and not hidden,
          ("window %d px, screen %d px" % (mw.width(), mw.screen().availableGeometry().width()),
           len(acts), len(ribbon_buttons), hidden, sorted(want - set(acts))))
    # sketches stay in Kovač, so FreeCAD never built the sketcher's own actions and never
    # registered its default keys: every tooltip came out without one, and the keys did nothing
    no_key = sorted({a.objectName() for a in acts.values()
                     if "(" not in a.toolTip().split("\n")[0] and a.objectName() not in ("Sketcher_ConstrainSymmetric",)})
    check("every sketch tool's tooltip names its shortcut", not no_key, no_key)
    fired = []
    line_act = acts["Sketcher_CreateLine"]
    line_act.triggered.connect(lambda *_: fired.append(1))
    vp().setFocus()
    QtTest.QTest.keyClick(vp(), QtCore.Qt.Key_G)
    QtTest.QTest.keyClick(vp(), QtCore.Qt.Key_L)
    yield 300
    check("typing a sketch tool's shortcut (G, L) starts it", bool(fired))
    QtTest.QTest.keyClick(vp(), QtCore.Qt.Key_Escape)
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
    # Midpoint constraint: select a point and a line on the ribbon, it snaps to the midpoint
    import Sketcher
    n4 = len(sk.Geometry)
    li4 = sk.addGeometry(Part.LineSegment(V(2 * g, 2 * g, 0), V(8 * g, 2 * g, 0)), False)
    pt4 = sk.addGeometry(Part.Point(V(4 * g, 5 * g, 0)), False)
    sk.addConstraint(Sketcher.Constraint("DistanceX", li4, 1, 2 * g))
    sk.addConstraint(Sketcher.Constraint("DistanceY", li4, 1, 2 * g))
    sk.addConstraint(Sketcher.Constraint("DistanceX", li4, 2, 8 * g))
    sk.addConstraint(Sketcher.Constraint("DistanceY", li4, 2, 2 * g))
    sk.recompute()
    vidx = next(i for i in range(1, 4 * len(sk.Geometry) + 2) if sk.getGeoVertexIndex(i) == (pt4, 1))
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(App.ActiveDocument.Name, sk.Name, "Edge%d" % (li4 + 1))
    Gui.Selection.addSelection(App.ActiveDocument.Name, sk.Name, "Vertex%d" % vidx)
    acts["Kovac_ConstrainMidpoint"].trigger()
    yield 200
    check("Midpoint constraint: a point picked with a line snaps to its midpoint",
          abs(sk.Geometry[pt4].X - 5 * g) < 1e-6 and abs(sk.Geometry[pt4].Y - 2 * g) < 1e-6,
          (sk.Geometry[pt4].X, sk.Geometry[pt4].Y))
    for _ in range(len(sk.Geometry) - n4):
        sk.delGeometry(n4)
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
    follows = []
    for k in range(1, 6):
        mouse(QtCore.QEvent.MouseMove, a0 - QtCore.QPoint(0, 12 * k), QtCore.Qt.NoButton, QtCore.Qt.LeftButton)
        follows.append(arrow.seg is not None and abs((arrow.seg[0] - o).dot(n) - ed.fp.Length.Value) < 1e-6)
        yield 40
    mouse(QtCore.QEvent.MouseButtonRelease, a0 - QtCore.QPoint(0, 60), QtCore.Qt.LeftButton, QtCore.Qt.NoButton)
    yield 200
    dragged = ed.fp.Length.Value
    check("dragging the arrow changes the distance", dragged > 6, dragged)
    check("the arrow follows each mouse move at once, not after the preview", all(follows), follows)
    ed.set("Length", 5)
    yield 300
    from kovac import manip
    a, b = arrow.seg
    on_face = min((a - (o + n * 5)).Length, (b - (o + n * 5)).Length) < 1e-6
    check("the extrude arrow keeps one size on screen and starts on the extruded face",
          on_face and abs((b - a).Length / arrow.px - manip.ARROW_PX) < 1, (a, b, arrow.px))
    mid = to_qt((a + b) * 0.5)
    check("the arrow is grabbed along its whole length, not only at its tip",
          arrow._screen_distance(navigation.install(), mid) < 2)
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
    # the panel has its own drag arrow for the radius, at the picked edge, same as Extrude's
    from kovac import navigation
    fillet_ed = editor.current()
    arrow = next((h for h in navigation.hooks if type(h).__name__ == "Arrow"), None)
    check("fillet panel has a drag arrow for its radius", arrow is not None and arrow.axis is not None,
          arrow and arrow.axis)
    if arrow is not None and arrow.axis is not None:
        o, n = arrow.axis
        a0 = to_qt(o + n * arrow.value())
        mouse(QtCore.QEvent.MouseButtonPress, a0, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton)
        for k in range(1, 4):
            mouse(QtCore.QEvent.MouseMove, to_qt(o + n * (arrow.value() + k)), QtCore.Qt.NoButton, QtCore.Qt.LeftButton)
            yield 40
        mouse(QtCore.QEvent.MouseButtonRelease, to_qt(o + n * (arrow.value() + 3)), QtCore.Qt.LeftButton, QtCore.Qt.NoButton)
        yield 150
        check("dragging the fillet arrow changes its radius", fillet_ed.fp.Radius.Value > 1, fillet_ed.fp.Radius.Value)
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

    # Opening a second feature panel while a first one is still open (unclosed, not OK'd or
    # Cancelled) used to crash: the new panel's Cancel could abort the transaction the first
    # panel's own feature was just created under, deleting it out from under its own open
    # panel (editor.py's close_current(), run before, not after, the new one starts).
    from kovac import editor

    def side_rect(name, x0):
        s = App.ActiveDocument.addObject("Sketcher::SketchObject", name)
        s.Placement = App.Placement(V(x0, -60, 0), App.Rotation())
        pts = [V(0, 0, 0), V(10, 0, 0), V(10, 10, 0), V(0, 10, 0)]
        for i in range(4):
            s.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]))
        return s
    rs1 = side_rect("CancelA", 0)
    rs2 = side_rect("CancelB", 30)
    App.ActiveDocument.recompute()
    before_doc = set(App.ActiveDocument.Objects)         # the two sketches stay; only the panels' own objects must not
    ed1 = editor.start(features.Extrude, Profile=rs1, Length=5)
    yield 150
    ed2 = editor.start(features.Extrude, Profile=rs2, Length=7, Operation="New body")    # no crash opening this
    yield 150
    is_current = editor.current() is ed2
    try:                                        # fp1's name may already be reused by fp2; identity is what matters
        ed1.fp.Name
        fp1_gone = False
    except Exception:
        fp1_gone = True
    cancel_btn = next(b for b in ed2.findChildren(QtWidgets.QPushButton) if b.text() == "Cancel")
    press(cancel_btn)
    yield 300
    left_over = set(App.ActiveDocument.Objects) - before_doc
    check("a second panel opened over an unclosed first one doesn't crash, and Cancel leaves nothing behind",
          is_current and fp1_gone and not left_over,
          (is_current, fp1_gone, sorted(o.Name for o in left_over)))

    # -- group-selecting multiple history items: Delete key, and grouping reads as one thing --
    tree = shell._ui["tree"].widget()
    tl = shell._ui["timeline"].widget()
    before_bodies = len(bodies())
    for i, x0 in enumerate((60, 80, 100)):
        s = side_rect("Del%d" % i, x0)
        App.ActiveDocument.recompute()
        ed = editor.start(features.Extrude, Profile=s, Length=5, Operation="New body")
        yield 100
        ed.accept()
        yield 150
    check("three bodies added for the group-select tests", len(bodies()) == before_bodies + 3, len(bodies()))

    # browser: multi-select two bodies, Delete key removes both as one undo step
    # -- picked with real clicks (Ctrl for the second): setSelected() alone once hid that no row
    # could be selected by mouse at all
    tree.clearSelection()
    body_items = [it for it in tree.walk() if tree.obj(it) is not None and hasattr(tree.obj(it), "BodyId")]
    for k, it in enumerate(body_items[-2:]):
        tree.scrollToItem(it)
        r = tree.visualItemRect(it)
        click_widget(tree.viewport(), QtCore.QPoint(r.left() + 30, r.center().y()),
                     QtCore.Qt.ControlModifier if k else QtCore.Qt.NoModifier)
        yield 80
    picked = {s.Object.Name for s in Gui.Selection.getSelectionEx("*", 0)}
    check("browser: click then Ctrl+click selects both bodies, here and in the 3D view",
          len(tree.selectedItems()) == 2 and picked == {tree.obj(it).Name for it in body_items[-2:]},
          ([x.text(0) for x in tree.selectedItems()], sorted(picked)))
    QtWidgets.QApplication.sendEvent(tree, QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Delete, QtCore.Qt.NoModifier))
    yield 200
    after_browser_delete = len(bodies())
    App.ActiveDocument.undo()
    yield 200
    check("browser: Delete key removes every selected body, one undo step",
          after_browser_delete == before_bodies + 1 and len(bodies()) == before_bodies + 3,
          (before_bodies, after_browser_delete, len(bodies())))

    # timeline: multi-select two features, Delete key removes both as one undo step
    tl.rebuild()
    yield 100
    feat_items = [it for it in [tl.list.item(i) for i in range(tl.list.count())] if not it.data(QtCore.Qt.UserRole + 1)]
    before_feats = len(feat_items)
    for it in feat_items[-2:]:
        it.setSelected(True)
    yield 100
    QtWidgets.QApplication.sendEvent(tl.list, QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Delete, QtCore.Qt.NoModifier))
    yield 200
    tl.rebuild()
    after_feats = len([it for it in [tl.list.item(i) for i in range(tl.list.count())] if not it.data(QtCore.Qt.UserRole + 1)])
    App.ActiveDocument.undo()
    tl.rebuild()
    yield 200
    check("timeline: Delete key removes every selected feature, one undo step",
          after_feats == before_feats - 2, (before_feats, after_feats))

    # grouping: picked with real Ctrl+clicks, the group shows as one item -- not one labelled
    # item per member, which read as "each feature is its own group"
    GROUP = QtCore.Qt.UserRole + 2
    feat_items = [it for it in [tl.list.item(i) for i in range(tl.list.count())] if not it.data(QtCore.Qt.UserRole + 1)]
    tl.list.clearSelection()
    for k, it in enumerate(feat_items[-2:]):
        click_widget(tl.list.viewport(), tl.list.visualItemRect(it).center(),
                     QtCore.Qt.ControlModifier if k else QtCore.Qt.NoModifier)
        yield 120
    picked = [tl.obj(it) for it in tl.list.selectedItems()]
    check("timeline: Ctrl+click picks several features", len(picked) == 2, [o.Label for o in picked if o])
    tl.group(picked, "SideBodies")
    yield 150
    rows = [tl.list.item(i) for i in range(tl.list.count())]
    heads = [it for it in rows if it.data(GROUP) == "SideBodies"]
    check("a new group shows as one item standing for all its members",
          len(heads) == 1 and "(2)" in heads[0].text() and len(rows) == len(feat_items) - 2 + 1 + 1,   # + the rollback marker
          ([it.text() for it in rows], len(feat_items)))
    tl.double(heads[0])
    yield 150
    rows = [tl.list.item(i) for i in range(tl.list.count())]
    heads = [k for k, it in enumerate(rows) if it.data(GROUP) == "SideBodies"]
    members = [it for it in rows if tl.obj(it) in picked and not it.data(GROUP)]
    tints = {it.background().color().name() for it in members + [rows[heads[0]]]} if heads else set()
    check("opened, the group is one header in front of its members, sharing its tint",
          len(heads) == 1 and len(members) == 2 and len(tints) == 1 and all(not it.text() for it in members),
          ([it.text() for it in rows], tints))
    App.ActiveDocument.undo()
    yield 150
    yield 100


def seg_curve3d():
    """A sketch's free B-spline becomes a 3D curve; its points drag in 3D."""
    from kovac import commands, curve3d, editor, features, model, move, navigation, params, sketchmode, views  # noqa: F401
    mw = Gui.getMainWindow()  # noqa: F841
    # -- 3D curve: a sketch's free B-spline leaves the sketch; its points then drag in 3D --
    App.newDocument("Curve3DTest")
    yield 300
    from kovac import curve3d
    sk3 = sketchmode.create("XY")
    i = sk3.addGeometry(Part.BSplineCurve([V(0, 0, 0), V(10, 15, 0), V(25, -10, 0), V(40, 5, 0)], None, None, False, 3, None, False))
    sk3.exposeInternalGeometry(i)
    App.ActiveDocument.recompute()
    yield 500
    command("Kovac_Curve3D")
    yield 300
    ed3 = curve3d.current()
    check("3D curve: the sketch's free B-spline becomes a 3D curve, open for editing",
          ed3 is not None and not sketchmode.in_sketch() and not sk3.Geometry,
          (ed3, sketchmode.in_sketch(), len(sk3.Geometry)))
    views.go(view(), views.view_rotation((0, -1, 0)), fit=True)      # from the front: dragging up lifts the point
    yield 800
    p1 = V(ed3.obj.Points[1])
    it3 = navigation.install()                  # the new document's own view
    x, y = it3.qt(view().getPointOnViewport(p1))
    start = QtCore.QPoint(int(x), int(y))
    L = QtCore.Qt.LeftButton
    for t, q, held in [(QtCore.QEvent.MouseButtonPress, start, L)] + \
            [(QtCore.QEvent.MouseMove, start - QtCore.QPoint(0, 8 * k), L) for k in range(1, 11)] + \
            [(QtCore.QEvent.MouseButtonRelease, start - QtCore.QPoint(0, 80), QtCore.Qt.NoButton)]:
        QtWidgets.QApplication.sendEvent(vp(), QtGui.QMouseEvent(t, QtCore.QPointF(q), QtCore.QPointF(vp().mapToGlobal(q)),
                                                                 QtCore.Qt.LeftButton if t != QtCore.QEvent.MouseMove else QtCore.Qt.NoButton,
                                                                 held, QtCore.Qt.NoModifier))
    yield 200
    p1b = V(ed3.obj.Points[1])
    check("3D curve: dragging a point in a side view lifts it out of the sketch plane, one undo step",
          p1b.z > 2 and App.ActiveDocument.UndoNames[:1] == ["Move curve point"], (p1, p1b, App.ActiveDocument.UndoNames[:2]))
    curve3d.finish()
    yield 100


def seg_move():
    """The Move triad: bodies, faces, sketch elements in and out of a sketch, typed amounts."""
    from kovac import commands, curve3d, editor, features, model, move, navigation, params, sketchmode, views  # noqa: F401
    mw = Gui.getMainWindow()  # noqa: F841
    # -- Move: the triad on a body -- drag the X arrow, then the turning handle about Z --
    from kovac import move
    App.newDocument("MoveTest")
    yield 300
    skm = sketchmode.create("XY")
    for a, b in ((V(0, 0, 0), V(40, 0, 0)), (V(40, 0, 0), V(40, 20, 0)), (V(40, 20, 0), V(0, 20, 0)), (V(0, 20, 0), V(0, 0, 0))):
        skm.addGeometry(Part.LineSegment(a, b))
    sketchmode.finish()
    yield 300
    editor.start(features.Extrude, Profile=skm, Length=10).accept()
    yield 300
    bm = bodies()[0]
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(bm)
    views.go(view(), views.view_rotation(views.ISO), fit=True)
    yield 500
    command("Kovac_Move")
    yield 400
    edm = editor.current()
    tri = next(h for h in edm.hooks if isinstance(h, move.Triad))
    itm = navigation.install()
    p, axes = tri.t.frame()
    pxm = itm.px_size()
    sc = lambda q: QtCore.QPointF(*itm.qt(view().getPointOnViewport(q)))   # noqa: E731

    def drag_vp(a, b):
        L = QtCore.Qt.LeftButton
        evs = [(QtCore.QEvent.MouseButtonPress, a, L)] + [(QtCore.QEvent.MouseMove, a + (b - a) * k / 12, L) for k in range(1, 13)] + \
              [(QtCore.QEvent.MouseButtonRelease, b, QtCore.Qt.NoButton)]
        for t, q, held in evs:
            QtWidgets.QApplication.sendEvent(vp(), QtGui.QMouseEvent(t, q, QtCore.QPointF(vp().mapToGlobal(q.toPoint())),
                                                                     L if t != QtCore.QEvent.MouseMove else QtCore.Qt.NoButton, held, QtCore.Qt.NoModifier))
    drag_vp(sc(p + axes[0] * move.ARROW_PX * pxm * 0.8), sc(p + axes[0] * (move.ARROW_PX * pxm * 0.8 + 20)))
    yield 200
    slid = V(edm.fp.Move.Base)
    ring = tri._ring(p + slid, axes[0], axes[1], move.RING_PX * pxm)
    drag_vp(sc(ring[8]), sc(ring[16]) + (sc(ring[16]) - sc(ring[8])) * 0.2)
    yield 200
    turned = math.degrees(edm.fp.Move.Rotation.Angle)
    check("Move: dragging the X arrow slides the body along X, the Z handle turns it",
          slid.x > 5 and abs(slid.y) < 1e-9 and abs(slid.z) < 1e-9 and turned >= 5 and
          (edm.fp.Move.Rotation.Axis - V(0, 0, 1)).Length < 1e-6, (slid, turned, edm.fp.Move.Rotation.Axis))
    combo = edm.findChild(QtWidgets.QComboBox, "kovacMoveType")
    check("the Move panel has a drop-down for what to move", combo is not None and combo.currentText() == "Bodies",
          combo and combo.currentText())
    edm.accept()
    yield 300

    # a face clicked, then Move: the drop-down turns the bodies move into a face move, and back
    top = next(i for i, f in enumerate(bm.Shape.Faces) if abs(f.CenterOfMass.z - 10) < 1e-6 and f.normalAt(0, 0).z > 0.9)
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(bm, "Face%d" % (top + 1))
    command("Kovac_Move")
    yield 400
    edm = editor.current()
    edm.findChild(QtWidgets.QComboBox, "kovacMoveType").setCurrentText("Faces")
    yield 500
    edf = editor.current()
    check("Move: choosing Faces moves the clicked face instead of its body",
          edf is not None and type(edf.fp.Proxy).kind == "MoveFace" and bool(edf.fp.Face) and
          any(isinstance(h, move.Triad) for h in edf.hooks), edf and edf.fp.Face)
    edf.findChild(QtWidgets.QComboBox, "kovacMoveType").setCurrentText("Bodies")
    yield 500
    edb = editor.current()
    check("Move: choosing Bodies again moves the face's body, the face move left nothing behind",
          type(edb.fp.Proxy).kind == "Move" and list(edb.fp.Bodies) == [bm.BodyId] and
          not any(type(getattr(o, "Proxy", None)).__name__ == "MoveFace" for o in App.ActiveDocument.Objects),
          (list(edb.fp.Bodies), [o.Name for o in App.ActiveDocument.Objects]))
    edb.reject()
    yield 300

    # -- Move in a sketch: a corner dragged up out of the plane takes both its lines into 3D --
    App.newDocument("Move3DTest")
    yield 300
    skc = sketchmode.create("XY")
    for a, b in ((V(0, 0, 0), V(40, 0, 0)), (V(40, 0, 0), V(40, 20, 0)), (V(40, 20, 0), V(0, 20, 0)), (V(0, 20, 0), V(0, 0, 0))):
        skc.addGeometry(Part.LineSegment(a, b))
    App.ActiveDocument.recompute()
    yield 400
    vtx = next(k for k in range(20) if skc.getGeoVertexIndex(k) == (0, 2))
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(skc, "Vertex%d" % (vtx + 1))
    command("Kovac_Move")
    views.go(view(), views.view_rotation(views.ISO), fit=True)
    yield 800
    tri = move._session.triad
    itc = navigation.install()
    p, axes = tri.t.frame()
    pxc = itc.px_size()
    scc = lambda q: QtCore.QPointF(*itc.qt(view().getPointOnViewport(q)))   # noqa: E731
    drag_vp(scc(p + axes[2] * move.ARROW_PX * pxc * 0.8), scc(p + axes[2] * (move.ARROW_PX * pxc * 0.8 + 15)))
    yield 200
    lifted = [o for o in App.ActiveDocument.Objects if curve3d.is_curve(o)]
    tops = [max(q.z for q in o.Points) for o in lifted]
    check("Move in a sketch: dragging a corner up lifts it and both its lines out of the plane, one undo step",
          len(skc.Geometry) == 2 and len(lifted) == 2 and all(z > 2 for z in tops) and
          App.ActiveDocument.UndoNames[:1] == ["Move"], (len(skc.Geometry), tops, App.ActiveDocument.UndoNames[:2]))
    move.finish()

    # -- Move "Points" outside the sketch: a corner clicked on the sketch in the view; then a typed length --
    App.newDocument("MovePointsTest")
    yield 300
    skp = sketchmode.create("XY")
    for a, b in ((V(0, 0, 0), V(40, 0, 0)), (V(40, 0, 0), V(40, 20, 0)), (V(40, 20, 0), V(0, 20, 0)), (V(0, 20, 0), V(0, 0, 0))):
        skp.addGeometry(Part.LineSegment(a, b))
    sketchmode.finish()
    App.ActiveDocument.recompute()
    yield 400
    corner = next(k for k, v in enumerate(skp.Shape.Vertexes) if (v.Point - V(40, 0, 0)).Length < 1e-6)
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(skp, "Vertex%d" % (corner + 1))
    command("Kovac_Move")
    views.go(view(), views.view_rotation(views.ISO), fit=True)
    yield 800
    ses = move._session
    combo = ses.dock.widget().findChild(QtWidgets.QComboBox, "kovacMoveType")
    check("Move on sketch points picked in the view opens as Points, with the drop-down",
          ses is not None and ses.move_type == "Points" and combo is not None and combo.currentText() == "Points",
          ses and ses.move_type)
    tri = ses.triad
    itc = navigation.install()
    p, axes = tri.t.frame()
    pxc = itc.px_size()
    drag_vp(scc(p + axes[0] * move.ARROW_PX * pxc * 0.8), scc(p + axes[0] * (move.ARROW_PX * pxc * 0.8 + 25)))
    yield 300
    ends = lambda: sorted((g.StartPoint.x, g.EndPoint.x) for g in skp.Geometry)   # noqa: E731
    xs = [x for pair in ends() for x in pair]
    check("Points: dragging the X arrow moves the clicked corner, both lines stay joined there",
          max(xs) > 41 and xs.count(max(xs)) == 2, ends())
    field = tri.label
    check("the triad shows an editable field with the dragged length",
          isinstance(field, QtWidgets.QLineEdit) and field.isVisible() and "mm" in field.text(), field and field.text())
    field.setText("25 mm")
    field.returnPressed.emit()
    yield 300
    xs = [x for pair in ends() for x in pair]
    check("typing a length in the triad's field moves the corner exactly that far, one undo step",
          abs(max(xs) - 65) < 1e-6 and xs.count(max(xs)) == 2 and App.ActiveDocument.UndoNames[:1] == ["Move"],
          (ends(), App.ActiveDocument.UndoNames[:3]))
    combo.setCurrentText("Bodies")
    yield 500
    edb = editor.current()
    check("Points -> Bodies in the drop-down closes the points window and opens the bodies move",
          move._session is None and edb is not None and type(edb.fp.Proxy).kind == "Move", move._session)
    if edb is not None:
        edb.reject()
    yield 300
    yield 100


def seg_offset():
    """Offset in a sketch: a B-spline (which the sketcher's own Offset drops) by arrow and by typed value."""
    from kovac import navigation, sketchmode, sketchoffset, views
    App.newDocument("OffsetTest")
    yield 300
    sk = sketchmode.create("XY")
    g = sk.addGeometry(Part.BSplineCurve([V(0, 0, 0), V(10, 20, 0), V(30, -10, 0), V(40, 10, 0)], None, None, False, 3, None, False))
    sk.exposeInternalGeometry(g)
    App.ActiveDocument.recompute()
    yield 500
    n0 = len(sk.Geometry)
    Gui.Selection.clearSelection()
    from kovac import sketchtools
    views.go(view(), views.view_rotation((0, 0, 1)), fit=True)
    yield 600
    Gui.runCommand("Sketcher_CreateBSpline")   # the user's case: a drawing tool still on from the last curve
    yield 400
    was_running = sketchtools.tool_running()
    command("Kovac_SketchOffset")              # nothing picked: it opens and waits for the curve
    yield 400
    waiting = sketchoffset._tool
    check("Offset ends the drawing tool still running, then opens and waits for a curve",
          was_running and not sketchtools.tool_running() and waiting is not None and waiting.result is None
          and "Click" in waiting.status.text(), (was_running, sketchtools.tool_running(), waiting))
    curve = sk.Geometry[g]
    on = to_qt(curve.value((curve.FirstParameter + curve.LastParameter) * 0.3))
    for k in (6, 3, 0):                        # hover in, so the sketcher preselects the curve, then click
        mouse(QtCore.QEvent.MouseMove, on + QtCore.QPoint(k, 0))
        yield 80
    mouse(QtCore.QEvent.MouseButtonPress, on, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton)
    mouse(QtCore.QEvent.MouseButtonRelease, on, QtCore.Qt.LeftButton, QtCore.Qt.NoButton)
    yield 500
    tool = sketchoffset._tool
    check("clicking the curve picks it for the offset (no pole added by a leftover tool)",
          tool is not None and tool.picks == [g] and len(sk.Geometry) == n0, (tool and tool.picks, len(sk.Geometry), n0))
    views.go(view(), views.view_rotation(views.ISO), fit=True)
    yield 400
    check("Offset on a B-spline opens Kovač's offset with a live preview",
          tool is not None and tool.result and isinstance(tool.result[0], Part.BSplineCurve) and tool.preview_node is not None,
          tool and tool.result)
    if tool is None:
        return
    it = navigation.install()
    a, b = tool.arrow.seg
    sc = lambda q: QtCore.QPointF(*it.qt(view().getPointOnViewport(q)))   # noqa: E731
    d0 = tool.d
    start, end = sc((a + b) * 0.5), sc((a + b) * 0.5 + tool.arrow.n * 6)
    Lb = QtCore.Qt.LeftButton
    for t, q, held in [(QtCore.QEvent.MouseButtonPress, start, Lb)] + \
            [(QtCore.QEvent.MouseMove, start + (end - start) * k / 10, Lb) for k in range(1, 11)] + \
            [(QtCore.QEvent.MouseButtonRelease, end, QtCore.Qt.NoButton)]:
        QtWidgets.QApplication.sendEvent(vp(), QtGui.QMouseEvent(t, q, QtCore.QPointF(vp().mapToGlobal(q.toPoint())),
                                                                 Lb if t != QtCore.QEvent.MouseMove else QtCore.Qt.NoButton, held,
                                                                 QtCore.Qt.NoModifier))
    yield 200
    check("dragging the offset arrow inside the sketch changes the distance", tool.d > d0 + 3, (d0, tool.d))
    corners = tool.dock.widget().findChild(QtWidgets.QWidget, "kovacOffsetCorners")
    check("the offset panel offers round or sharp corners", corners is not None and
          list(corners.buttons) == ["Round corners", "Sharp corners"], corners and list(corners.buttons))
    tool.field.setText("4 mm")
    tool.field.returnPressed.emit()
    yield 400
    new = [x for x in sk.Geometry[n0:] if isinstance(x, Part.BSplineCurve)]
    base = Part.BSplineCurve([V(0, 0, 0), V(10, 20, 0), V(30, -10, 0), V(40, 10, 0)], None, None, False, 3, None, False).toShape()
    err = max(abs(Part.Vertex(new[0].value(new[0].FirstParameter + (new[0].LastParameter - new[0].FirstParameter) * k / 30))
                  .distToShape(base)[0] - 4) for k in range(31)) if new else None
    check("typing 4 mm and Enter adds the offset spline 4 mm away, one undo step",
          sketchoffset._tool is None and len(new) == 1 and err < 1e-3 and App.ActiveDocument.UndoNames[:1] == ["Offset"],
          (len(new), err, App.ActiveDocument.UndoNames[:2]))
    # sharp corners on a rectangle's outline: four longer lines, no arcs
    Gui.Selection.clearSelection()
    r0 = len(sk.Geometry)
    c = [V(60, 0, 0), V(100, 0, 0), V(100, 20, 0), V(60, 20, 0)]
    for k in range(4):
        sk.addGeometry(Part.LineSegment(c[k], c[(k + 1) % 4]))
    App.ActiveDocument.recompute()
    yield 300
    for k in range(4):
        Gui.Selection.addSelection(sk, "Edge%d" % (r0 + k + 1))
    command("Kovac_SketchOffset")
    yield 400
    tool = sketchoffset._tool
    tool.dock.widget().findChild(QtWidgets.QWidget, "kovacOffsetCorners").setCurrentText("Sharp corners")
    tool.set(abs(tool.d) if tool.d else 2)
    if tool.result and any(isinstance(x, Part.LineSegment) and max(x.StartPoint.x, x.EndPoint.x) < 100 + 1e-9
                           and min(x.StartPoint.x, x.EndPoint.x) > 60 - 1e-9 and abs(x.StartPoint.y - x.EndPoint.y) < 1e-9
                           and x.StartPoint.y > 0 and x.StartPoint.y < 20 for x in tool.result):
        tool.set(-tool.d)                       # it went inside: take the outside
    tool.field.setText("3 mm" if tool.d > 0 else "-3 mm")
    tool.field.returnPressed.emit()
    yield 400
    added = sk.Geometry[r0 + 4:]
    bb = Part.Compound([x.toShape() for x in added]).BoundBox if added else None
    check("sharp corners: a rectangle offsets to a larger rectangle of four lines, no rounded corners",
          len(added) == 4 and all(isinstance(x, Part.LineSegment) for x in added) and bb and
          abs(bb.XLength - 46) < 1e-6 and abs(bb.YLength - 26) < 1e-6, (len(added), bb))
    sketchmode.finish()
    yield 300


def seg_assembly():
    """Components, a joint picked by clicking, dragging a hinged part, instances, Move Components."""
    import Sketcher
    from kovac import assemble, components, editor, features, joints, model, move, navigation, sketchmode, tree, views
    doc = App.newDocument("AssemblyTest")
    yield 300

    def sk_of(geos, name):
        sk = sketchmode.create("XY", name=name)
        for g in geos:
            sk.addGeometry(g)
        sketchmode.finish()
        return sk
    pts = [V(0, 0, 0), V(60, 0, 0), V(60, 40, 0), V(0, 40, 0)]
    plate_sk = sk_of([Part.LineSegment(pts[i], pts[(i + 1) % 4]) for i in range(4)], "Plate")
    yield 300
    editor.start(features.Extrude, Profile=plate_sk, Length=10).accept()
    yield 300
    hole = sk_of([Part.Circle(V(15, 20, 0), V(0, 0, 1), 5)], "Hole")
    hole.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, 0, 3, 15))
    hole.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, 0, 3, 20))
    yield 300
    ed = editor.start(features.Extrude, Profile=hole, Length=10)
    ed.fp.Operation = "Cut"
    ed.accept()
    yield 300
    pin_sk = sk_of([Part.Circle(V(100, 0, 0), V(0, 0, 1), 4.5)], "Pin")
    yield 300
    ed = editor.start(features.Extrude, Profile=pin_sk, Length=30)
    ed.fp.Operation = "New body"
    ed.accept()
    yield 400
    plate_b = next(b for b in bodies() if b.Shape.BoundBox.XMax > 59)
    pin_b = next(b for b in bodies() if b is not plate_b)
    views.go(view(), views.view_rotation(views.ISO), fit=True)
    yield 500

    # -- New Component from a clicked body (twice) --
    Gui.Selection.clearSelection()
    click_at(V(45, 30, 10))
    yield 200
    command("Kovac_NewComponent")
    yield 300
    plate_c = components.holder(plate_b)
    Gui.Selection.clearSelection()
    click_at(V(100, 0, 30))
    yield 200
    command("Kovac_NewComponent")
    yield 400
    pin_c = components.holder(pin_b)
    br = Gui.getMainWindow().findChild(QtWidgets.QFrame, "kovacBrowser")
    tw = br.findChild(QtWidgets.QTreeWidget) if br else None
    labels = [it.text(0) for it in tw.findItems("", QtCore.Qt.MatchContains | QtCore.Qt.MatchRecursive)] if tw else []
    check("New Component: each clicked body (and its sketch) goes into a component of its own, shown at the top of the browser",
          plate_c is not None and pin_c is not None and plate_c != pin_c and pin_sk in pin_c.Group and
          plate_c.Label in labels and pin_c.Label in labels, (plate_c and plate_c.Label, pin_c and pin_c.Label, labels[:12]))

    # -- Joint: hover shows markers, click the hole's rim then the pin's top rim --
    command("Kovac_Joint")
    yield 300
    tool = assemble._tool
    views.go(view(), views.view_rotation(views.ISO), fit=True)
    yield 400
    rim = V(15 + 5 * math.cos(math.radians(225)), 20 + 5 * math.sin(math.radians(225)), 10)   # the rim, facing the camera
    for _ in range(10):                          # the view may still be settling after the turn: hover again
        mouse(QtCore.QEvent.MouseMove, to_qt(rim))
        yield 100
        if tool is not None and tool.nodes:
            break
    check("Joint: hovering the hole's rim shows a joint-origin marker", tool is not None and len(tool.nodes) >= 1,
          tool and len(tool.nodes))
    click_at(rim)
    yield 300
    pin_rim = V(104.5, 0, 30)
    click_at(pin_rim)
    yield 500
    j = tool.joint if tool else None
    check("Joint: two clicks make the joint, the pin snaps onto the hole and the plate is grounded",
          j is not None and joints.satisfied(j) and joints.grounded(doc) == [plate_c] and
          (pin_c.Placement.multVec(V(100, 0, 30)) - V(15, 20, 10)).Length < 1e-4,
          (j and j.Label, tool and tool.status.text(), pin_c.Placement))
    tool.choice.setCurrentText("Revolute")
    yield 300
    press([b for b in tool.dock.findChildren(QtWidgets.QPushButton) if b.text() == "OK"][0])
    yield 400
    check("Joint: Revolute chosen in the panel, OK keeps it as one undo step",
          j.JointType == "Revolute" and doc.UndoNames[:1] == ["Joint"] and assemble._tool is None, (j.JointType, doc.UndoNames[:3]))
    yield 300
    jl = [it.text(0) for it in tw.findItems("Joints", QtCore.Qt.MatchStartsWith | QtCore.Qt.MatchRecursive)] if tw else []
    check("the browser's Joints folder lists the joint and the ground", jl == ["Joints  (2)"], jl)
    shot("assembly_joint")

    # -- driving the joint from its panel: a typed angle, a limit, Play --
    assemble.edit_joint(j)
    yield 400
    ed = assemble._tool
    dock = ed.dock if ed else None
    angle = dock.findChild(QtWidgets.QLineEdit, "kovacJointAngle") if dock else None
    if angle is not None:
        angle.setFocus()
        angle.setText("30")
        angle.returnPressed.emit()
    yield 300
    check("Joint panel: a typed angle turns the pin about the hinge",
          angle is not None and abs(joints.position(j)[0] - 30) < 1e-4 and joints.satisfied(j),
          (angle is not None, joints.position(j)))
    box = dock.findChild(QtWidgets.QCheckBox, "kovacJointAngleLimit") if dock else None
    lo, hi = (dock.findChild(QtWidgets.QLineEdit, n) for n in ("kovacJointAngleMin", "kovacJointAngleMax")) if dock else (None, None)
    if box is not None:
        lo.setText("-60")
        hi.setText("45")
        box.setChecked(True)
        angle.setText("80")
        angle.returnPressed.emit()
    yield 300
    check("Joint panel: with the angle limited to -60 … 45, typing 80 stops at 45",
          box is not None and joints.limits(j)["angle"] == (-60.0, 45.0) and abs(joints.position(j)[0] - 45) < 1e-4,
          (joints.limits(j), joints.position(j)))
    play = dock.findChild(QtWidgets.QPushButton, "kovacJointPlay") if dock else None
    seen = []
    if play is not None:
        press(play)
        for _ in range(80):
            yield 50
            seen.append(joints.position(j)[0])
            if ed.playing is None:
                break
    check("Play runs the joint between its limits and back to where it was",
          play is not None and ed.playing is None and min(seen) < -59 and max(seen) > 44 and
          abs(joints.position(j)[0] - 45) < 1e-3, (seen and (min(seen), max(seen)), joints.position(j)))
    shot("assembly_joint_motion")
    if ed is not None:
        ed.ok()
    yield 300

    # -- sketching after a joint: a selected face of a component, then a face clicked in the picker --
    def new_sketch(act):
        before = {o.Name for o in doc.Objects}
        yield from act()
        made = [o for o in doc.Objects if o.Name not in before and o.TypeId == "Sketcher::SketchObject"]
        result.append(made[0] if made else None)
        if sketchmode.in_sketch():
            sketchmode.finish()
        yield 300

    def selected_face():
        Gui.Selection.clearSelection()
        click_at(V(45, 30, 10))                        # the plate's top face
        yield 150
        command("Kovac_Sketch")
        yield 600
    result = []
    yield from new_sketch(selected_face)
    sk = result[-1]
    check("after a joint, a selected face of a component still takes a sketch",
          sk is not None and abs(sk.getGlobalPlacement().Base.z - 10) < 1e-6,
          (sk and sk.getGlobalPlacement(), Gui.getMainWindow().statusBar().currentMessage(),
           [(x.Object.Name, x.SubElementNames) for x in Gui.Selection.getSelectionEx("", 0)]))

    def picked_face():
        Gui.Selection.clearSelection()
        command("Kovac_DragComponent")                 # left on: Sketch must end it, or it takes the clicks
        yield 200
        command("Kovac_Sketch")
        yield 600
        top = pin_c.Placement.multVec(V(101, 1, 0))        # the pin stands upside down on the hole: its z = 0 end is on top
        click_at(top)
        yield 600
    yield from new_sketch(picked_face)
    sk = result[-1]
    check("after a joint, with Drag left on, Sketch ends Drag and the picker takes a clicked face of a moved component",
          sk is not None and abs(sk.getGlobalPlacement().Base.z - 40) < 1e-6 and assemble._drag is None,
          (sk and sk.getGlobalPlacement(), Gui.getMainWindow().statusBar().currentMessage()))

    # -- Undo while picking a plane ends the picker and undoes nothing --
    Gui.Selection.clearSelection()
    command("Kovac_Sketch")
    yield 500
    undos = list(doc.UndoNames)
    command("Kovac_Undo")                              # the undo arrow; Ctrl+Z is the same command
    yield 400
    picking = [h for h in navigation.hooks if isinstance(h, sketchmode.PlanePicker)]
    keys = [a.shortcut().toString() for a in Gui.Command.get("Kovac_Undo").getAction()]
    stock = [a.shortcut().toString() for a in Gui.Command.get("Std_Undo").getAction()]
    check("Undo while picking a sketch plane leaves the picker and undoes nothing; Ctrl+Z is Kovač's Undo",
          not picking and list(doc.UndoNames) == undos and not sketchmode.in_sketch() and
          keys == ["Ctrl+Z"] and stock == [""],
          (len(picking), undos[:3], doc.UndoNames[:3], sketchmode.in_sketch(), keys, stock))
    command("Kovac_Undo")                              # nothing running now: a real undo
    yield 400
    check("Undo with no tool running undoes the last step", list(doc.UndoNames) == undos[1:], (undos[:3], doc.UndoNames[:3]))
    command("Kovac_Redo")
    yield 400

    # -- Drag: the pin turns about the hole's axis, the plate holds still --
    command("Kovac_DragComponent")
    yield 200
    rot0 = App.Rotation(pin_c.Placement.Rotation)
    side = pin_c.Placement.multVec(V(104.5, 0, 15))
    a = to_qt(side)
    b = a + QtCore.QPoint(40, 30)
    L = QtCore.Qt.LeftButton
    mouse(QtCore.QEvent.MouseButtonPress, a, L, L)
    for k in range(1, 9):
        mouse(QtCore.QEvent.MouseMove, a + (b - a) * (k / 8), QtCore.Qt.NoButton, L)
        yield 30
    mouse(QtCore.QEvent.MouseButtonRelease, b, L, QtCore.Qt.NoButton)
    yield 300
    turned = math.degrees(rot0.inverted().multiply(pin_c.Placement.Rotation).Angle)
    check("Drag: pulling the pin turns it about the hinge; the joint holds and the grounded plate stays",
          joints.satisfied(j) and plate_c.Placement.isSame(App.Placement(), 1e-9) and
          (pin_c.Placement.multVec(V(100, 0, 30)) - V(15, 20, 10)).Length < 1e-4 and turned > 1,
          (turned, pin_c.Placement))
    command("Kovac_DragComponent")              # the command again ends dragging
    yield 200

    # -- the hole moves by its dimension: the joint follows --
    with __import__("kovac").commands.transaction("Edit hole", doc):
        hole.setDatum(0, App.Units.Quantity("25 mm"))
        model.commit(doc)
    yield 400
    check("a joint follows its hole when the hole's dimension changes",
          j.KovacStatus == "" and (pin_c.Placement.multVec(V(100, 0, 30)) - V(25, 20, 10)).Length < 1e-4, pin_c.Placement)

    # -- New Instance, then Move Components on it --
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(pin_c)
    command("Kovac_NewInstance")
    yield 400
    inst = next((o for o in doc.Objects if components.is_instance(o)), None)
    check("New Instance: a linked copy of the pin component sits beside it", inst is not None and inst.Label.endswith("(2)"),
          inst and inst.Label)
    before = App.Placement(inst.Placement)
    command("Kovac_Move")
    yield 400
    sess = move._session
    check("Move with a component selected moves the component (Components in the drop-down)",
          sess is not None and sess.move_type == "Components", sess and sess.move_type)
    if sess is not None:
        sess.begin(0)
        sess.translate(0, 12)
        sess.end()
        yield 200
        check("Move Components: the instance moves 12 mm along X, not a history step",
              (inst.Placement.Base - before.Base - V(12, 0, 0)).Length < 1e-6 and
              not any(type(getattr(o, "Proxy", None)).__name__ == "Transform" for o in model.items(doc)),
              inst.Placement)
        move.finish()
    yield 200

    # -- undo the joint: gone, the pin back where it was --
    for _ in range(20):
        if doc.UndoNames and doc.UndoNames[0] == "Joint":
            break
        doc.undo()
        yield 100
    doc.undo()
    yield 400
    check("Undo removes the joint again", not joints.all_joints(doc), [o.Name for o in joints.all_joints(doc)])

    # -- Copy, Move to (browser), deleting a moved component: bodies stay where they are shown --
    def shown(b):
        return b.Shape.transformed(components.frame(b).toMatrix()).BoundBox
    pin_c.Placement = App.Placement(V(30, 0, 0), App.Rotation(V(0, 1, 0), 20))
    model.commit(doc)
    yield 200
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(pin_c)
    command("Kovac_CopyComponent")
    yield 400
    copy_c = next((c for c in components.all_components(doc) if c.Label.startswith(pin_c.Label + " copy")), None)
    copy_b = [o for o in (copy_c.Group if copy_c else []) if type(getattr(o, "Proxy", None)).__name__ == "BodyProxy"]
    check("Copy Component: a new component beside the pin with a body of its own",
          copy_c is not None and len(copy_b) == 1 and copy_b[0].BodyId != pin_b.BodyId and
          abs(copy_b[0].Shape.Volume - pin_b.Shape.Volume) < 1e-6, (copy_c and copy_c.Label, len(copy_b)))
    before = shown(plate_b)
    tw.run_move([plate_b], pin_c) if hasattr(tw, "run_move") else None
    yield 400
    after = shown(plate_b)
    check("browser Move to: the plate goes into the turned pin component and stays where it was",
          components.holder(plate_b) == pin_c and all(abs(getattr(before, k) - getattr(after, k)) < 1e-5
                                                       for k in ("XMin", "YMin", "ZMin", "XMax", "YMax", "ZMax")),
          (components.holder(plate_b) and components.holder(plate_b).Label, before, after))
    before = shown(plate_b)
    tw.delete(pin_c)
    yield 400
    after = shown(plate_b)
    check("deleting a moved component leaves its bodies where they are",
          components.holder(plate_b) is None and all(abs(getattr(before, k) - getattr(after, k)) < 1e-5
                                                     for k in ("XMin", "YMin", "ZMin", "XMax", "YMax", "ZMax")),
          (before, after, Gui.getMainWindow().statusBar().currentMessage()))


SEGMENTS = [("bracket", seg_bracket), ("curve3d", seg_curve3d), ("move", seg_move), ("offset", seg_offset),
            ("assembly", seg_assembly)]


def scenario():
    """Every segment, or only those named in KOVAC_SEGMENTS (comma separated), each on
    its own document after the common start-up."""
    wanted = [s.strip() for s in os.environ.get("KOVAC_SEGMENTS", "").split(",") if s.strip()]
    unknown = set(wanted) - {n for n, _ in SEGMENTS}
    if unknown:
        res["errors"].append("unknown segments: %s" % sorted(unknown))
    yield from setup()
    for name, seg in SEGMENTS:
        if not wanted or name in wanted:
            yield from seg()


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

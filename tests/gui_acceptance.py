# SPDX-License-Identifier: LGPL-2.1-or-later
"""M1 GUI acceptance, run inside FreeCAD's GUI by tests/run_gui.py.

start -> open STEP -> orbit/pan/zoom -> select faces -> measure, with no stock workbench UI;
26 cube views, home, define-as-Front; window/crossing/tangent/pick-list selection;
auto-recompute; latency numbers. Writes $KOVAC_RESULT (JSON) and exits.
"""
import json
import math
import os
import statistics
import sys
import tempfile
import time
import traceback

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

V = App.Vector
OUT = os.environ["KOVAC_RESULT"]
SHOTS = os.path.join(os.path.dirname(OUT), "screens")
os.makedirs(SHOTS, exist_ok=True)
res = {"checks": [], "metrics": {}, "errors": []}


def check(name, ok, detail=""):
    res["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)})


def finish(code=0):
    res["passed"] = all(c["ok"] for c in res["checks"]) and not res["errors"]
    with open(OUT, "w") as f:
        json.dump(res, f, indent=1, default=str)
    os._exit(code)


sys.excepthook = lambda t, v, tb: res["errors"].append("".join(traceback.format_exception(t, v, tb)))
QtCore.QTimer.singleShot(240000, lambda: (res["errors"].append("watchdog: %s" % [
    (type(w).__name__, w.windowTitle()) for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible()]), finish(3)))


# ------------------------------------------------------------------ helpers
def view():
    return Gui.activeView()


def vp():
    return view().graphicsView().viewport()


def to_qt(p):
    r = vp().devicePixelRatioF()
    x, y = view().getPointOnViewport(p)
    return QtCore.QPoint(int(x / r), int(vp().height() - y / r))


def mouse(kind, pos, button=QtCore.Qt.NoButton, buttons=QtCore.Qt.NoButton, mods=QtCore.Qt.NoModifier):
    w = vp()
    ev = QtGui.QMouseEvent(kind, QtCore.QPointF(pos), QtCore.QPointF(w.mapToGlobal(pos)), button, buttons, mods)
    QtWidgets.QApplication.sendEvent(w, ev)


def drag(a, b, button, mods=QtCore.Qt.NoModifier, steps=8):
    mouse(QtCore.QEvent.MouseButtonPress, a, button, button, mods)
    for i in range(1, steps + 1):
        mouse(QtCore.QEvent.MouseMove, a + (b - a) * i / steps, QtCore.Qt.NoButton, button, mods)
    mouse(QtCore.QEvent.MouseButtonRelease, b, button, QtCore.Qt.NoButton, mods)


def click(pos, mods=QtCore.Qt.NoModifier):
    mouse(QtCore.QEvent.MouseButtonPress, pos, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, mods)
    mouse(QtCore.QEvent.MouseButtonRelease, pos, QtCore.Qt.LeftButton, QtCore.Qt.NoButton, mods)


def camera():
    import pivy.coin  # noqa: F401
    c = view().getCameraNode()
    return V(*c.position.getValue().getValue()), App.Rotation(*c.orientation.getValue().getValue()), \
        (c.height.getValue() if hasattr(c, "height") else c.focalDistance.getValue())


def picks():
    return [(s.Object.Name, n.split(".")[-1]) for s in Gui.Selection.getSelectionEx("", 0) for n in (s.SubElementNames or [""])]


def shot(name):
    """Window chrome via QWidget.grab with the GL viewport's own render pasted in
    (screen grabs are stale when the window is not in front)."""
    mw = Gui.getMainWindow()
    img = mw.grab().toImage()
    v = view()
    if v is not None and hasattr(v, "saveImage") and vp().isVisible():
        w = vp()
        r = w.devicePixelRatioF()
        tmp = os.path.join(SHOTS, "_3d.png")
        v.saveImage(tmp, int(w.width() * r), int(w.height() * r), "Current")
        painter = QtGui.QPainter(img)
        painter.drawImage(QtCore.QRect(w.mapTo(mw, QtCore.QPoint(0, 0)), w.size()), QtGui.QImage(tmp))
        os.remove(tmp)
        origin = mw.mapToGlobal(QtCore.QPoint(0, 0))
        for top in QtWidgets.QApplication.allWidgets():   # floating panels, radial, search
            if top is not mw and top.isWindow() and top.isVisible() and top.objectName().startswith("kovac"):
                painter.drawPixmap(top.mapToGlobal(QtCore.QPoint(0, 0)) - origin, top.grab())
        for top in mw.findChildren(QtWidgets.QFrame, "kovacBrowser"):     # see-through overlay: no window background
            if top.isVisible():
                top.render(painter, top.mapTo(mw, QtCore.QPoint(0, 0)), QtGui.QRegion(), QtWidgets.QWidget.RenderFlag.DrawChildren)
        painter.end()
    img.save(os.path.join(SHOTS, name + ".png"))


def make_step():
    import Part
    s = Part.makeBox(60, 40, 20)
    vertical = [e for e in s.Edges if abs(e.Vertexes[0].Point.z - e.Vertexes[1].Point.z) > 1]
    s = s.makeFillet(5, vertical)
    s = s.cut(Part.makeCylinder(6, 20, V(30, 20, 0)))
    path = os.path.join(tempfile.gettempdir(), "kovac_accept.step")
    s.exportStep(path)
    return path, s


def face_point(shape, normal):
    """Centre of the planar face with the given outward normal."""
    for i, f in enumerate(shape.Faces, 1):
        if f.Surface.__class__.__name__ == "Plane":
            u, v = f.Surface.parameter(f.CenterOfMass)
            if (f.normalAt(u, v) - normal).Length < 1e-6:
                return i, f.CenterOfMass
    raise RuntimeError("no face with normal %s" % normal)


# ------------------------------------------------------------------ scenario
def scenario():
    from kovac import commands, measure, navigation, radial, search, shell, views
    mw = Gui.getMainWindow()
    mw.showMaximized()
    mw.raise_()
    mw.activateWindow()
    yield 600
    res["metrics"]["startup_to_usable_s"] = round(time.time() - float(os.environ["KOVAC_LAUNCH_T"]), 2)
    check("Kovač workbench active at start", Gui.activeWorkbench().name() == "KovacWorkbench")
    shot("01_start")

    # -- open STEP ------------------------------------------------------------------------
    path, ref = make_step()
    t0 = time.perf_counter()
    doc = shell.import_step(path, App.newDocument("Accept"))
    res["metrics"]["step_import_s"] = round(time.perf_counter() - t0, 3)
    doc.UndoMode = 1
    yield 900
    from kovac import model
    bodies = [o for o in model.bodies(doc) if not o.Shape.isNull()]
    check("STEP imported as a body", len(bodies) == 1 and abs(bodies[0].Shape.Volume - ref.Volume) < 1e-3,
          [o.Name for o in doc.Objects])
    body = bodies[0]
    it = navigation.install()
    check("viewport interaction installed", it is not None)
    view().setCameraType("Orthographic")
    views.go(view(), views.view_rotation(views.ISO), fit=True)
    yield 500
    shot("02_step_open")

    # -- orbit / pan / zoom ---------------------------------------------------------------
    c = QtCore.QPoint(vp().width() // 2, vp().height() // 2)
    p0, r0, h0 = camera()
    drag(c, c + QtCore.QPoint(80, 40), QtCore.Qt.MiddleButton, QtCore.Qt.ShiftModifier)
    p1, r1, h1 = camera()
    check("Shift+middle drag orbits", abs(r0.Angle - r1.Angle) > 1e-3 or (r0.Axis - r1.Axis).Length > 1e-3)
    drag(c, c + QtCore.QPoint(60, -30), QtCore.Qt.MiddleButton)
    p2, r2, _ = camera()
    check("middle drag pans (position moves, orientation kept)",
          (p2 - p1).Length > 1e-3 and abs(r2.Angle - r1.Angle) < 1e-9)
    wheel = QtGui.QWheelEvent(QtCore.QPointF(c), QtCore.QPointF(vp().mapToGlobal(c)), QtCore.QPoint(0, 0),
                              QtCore.QPoint(0, 120), QtCore.Qt.NoButton, QtCore.Qt.NoModifier,
                              QtCore.Qt.NoScrollPhase, False)
    _, _, h2 = camera()
    QtWidgets.QApplication.sendEvent(vp(), wheel)
    yield 100
    _, _, h3 = camera()
    check("wheel zooms in", h3 < h2, (h2, h3))
    half = int(App.ParamGet("User parameter:BaseApp/Preferences/NaviCube").GetInt("CubeSize", 132) * 0.55)
    cc = QtCore.QPoint(vp().width() - half, half)          # the cube sits top-right by default
    _, r4, _ = camera()
    Gui.Selection.clearSelection()
    drag(cc, cc + QtCore.QPoint(-70, 30), QtCore.Qt.LeftButton)
    _, r5, _ = camera()
    check("dragging the cube orbits the view", it.in_cube(cc) and (abs(r4.Angle - r5.Angle) > 1e-3 or (r4.Axis - r5.Axis).Length > 1e-3))
    check("a cube drag selects nothing", picks() == [], picks())
    click(cc)                                               # a plain click still belongs to the cube
    yield 600
    got = V(*view().getViewDirection())
    check("clicking the cube snaps to a standard view", any((got + V(*d).normalize()).Length < 1e-3 for d in views.DIRS), got)
    views.go(view(), views.view_rotation(views.ISO), fit=True)
    yield 500

    # -- select faces, measure ------------------------------------------------------------
    Gui.Selection.clearSelection()
    top_i, top_c = face_point(body.Shape, V(0, 0, 1))
    front_i, front_c = face_point(body.Shape, V(0, -1, 0))
    click(to_qt(V(top_c.x - 15, top_c.y, top_c.z)))
    yield 100
    check("click selects the top face", picks() == [(body.Name, "Face%d" % top_i)], picks())
    click(to_qt(V(front_c.x - 15, front_c.y, front_c.z)), QtCore.Qt.ShiftModifier)
    yield 100
    check("Shift+click adds the front face", len(picks()) == 2, picks())
    tl = shell._ui["timeline"].widget()
    check("timeline highlights the creating feature", tl.list.currentRow() >= 0, tl.list.currentRow())
    commands.run("Kovac_Measure")
    yield 300
    panel = mw.findChild(QtWidgets.QDockWidget, "kovacMeasure")
    text = panel.widget().result.toPlainText() if panel else ""
    check("measure panel shows distance and 90° angle", "Minimum distance" in text and "Angle  90.000°" in text, text)
    check("measure panel floats (non-modal)", panel is not None and panel.isFloating() and not QtWidgets.QApplication.activeModalWidget())
    hover = []
    for _ in range(20):
        t0 = time.perf_counter()
        info = view().getObjectInfo(it.coin(to_qt(top_c)))
        Gui.Selection.setPreselection(body, info["Component"] if info else "Face%d" % top_i)
        hover.append((time.perf_counter() - t0) * 1000)
    res["metrics"]["hover_pick_and_readout_ms_median"] = round(statistics.median(hover), 2)
    res["metrics"]["hover_readout_ms"] = round(measure.stats["last_hover_ms"] or -1, 2)
    Gui.Selection.clearPreselection()
    shot("03_measure")
    Gui.Selection.clearSelection()
    yield 100

    # -- no stock workbench UI ------------------------------------------------------------
    stray_bars = [t.objectName() for t in mw.findChildren(QtWidgets.QToolBar) if t.isVisible() and not t.objectName().startswith("kovac")]
    stray_docks = [d.objectName() for d in mw.findChildren(QtWidgets.QDockWidget) if d.isVisible() and not d.objectName().startswith("kovac")]
    check("no stock toolbars, docks or menu bar visible", not stray_bars and not stray_docks and not mw.menuBar().isVisible(),
          (stray_bars, stray_docks, mw.menuBar().isVisible()))

    # -- orientation: 26 animated views ---------------------------------------------------
    misses = []
    t_anim = None
    for d in views.DIRS:
        t0 = time.perf_counter()
        commands.run("Kovac_View_" + views.name(d).replace(" ", ""))
        yield 330
        t_anim = t_anim or (time.perf_counter() - t0)
        want = -V(*d).normalize()
        got = view().getViewDirection()
        if (V(*got) - want).Length > 1e-3:
            misses.append((views.name(d), tuple(round(x, 3) for x in got)))
    check("all 26 standard views reachable (animated)", not misses, misses)
    commands.run("Kovac_View_Front")
    yield 330
    commands.run("Kovac_SetHome")
    commands.run("Kovac_View_Top")
    yield 330
    commands.run("Kovac_Home")
    yield 330
    check("set home + Home returns there", (V(*view().getViewDirection()) - V(0, 1, 0)).Length < 1e-3, view().getViewDirection())
    commands.run("Kovac_ResetHome")
    commands.run("Kovac_Home")
    yield 330
    check("reset home -> isometric", (V(*view().getViewDirection()) + V(*views.ISO).normalize()).Length < 1e-3, view().getViewDirection())
    commands.run("Kovac_View_Right")
    yield 330
    commands.run("Kovac_DefineFront")
    cube = App.ParamGet(views.CUBE_GROUP)
    labels = cube.GetString("TextRight"), cube.GetString("TextFront")
    commands.run("Kovac_View_Front")
    yield 330
    check("define current view as Front relabels cube and views",
          labels == ("FRONT", "LEFT") and (V(*view().getViewDirection()) - V(-1, 0, 0)).Length < 1e-3,
          (labels, view().getViewDirection()))
    shot("04_defined_front")
    commands.run("Kovac_ResetFront")
    check("reset Front restores labels", cube.GetString("TextFront") == "FRONT")
    views.go(view(), views.view_rotation(views.ISO), fit=True)
    yield 500

    # -- ground grid: the far clip plane always reaches the grid, at any tilt (regression) --
    # Coin's own auto-clipping sizes the far plane from the scene bounding box, and the grid
    # is deliberately excluded from that box (so 'fit all' never zooms out to show it) -- which
    # used to starve the clip planes too, cutting the grid off at the model's edge. Where that
    # cut lands on screen moves with the camera, so it read as "the grid disappears at some
    # angles". Sweep several tilts and check the far plane still reaches every grid corner.
    from kovac import grid
    rot0 = view().getCameraOrientation()
    vd0 = V(*view().getViewDirection())
    local_fwd = rot0.inverted().multVec(vd0)
    short_clip = []
    for elev in (2, 6, 12, 25, 40):      # degrees above the horizon
        target = V(1, -1, math.sin(math.radians(elev))).normalize()
        view().setCameraOrientation(App.Rotation(local_fwd, target))
        grid.refresh(force=True)
        s = grid._state["step"]
        cx, cy = grid._state["centre"]
        reach = max(it.vp.width(), it.vp.height()) * it.px_size()
        half = min(math.ceil(max(s * 30, reach * 1.6) / (5 * s)) * 5 * s, s * 400)
        pos = V(*view().getCameraNode().position.getValue().getValue())
        corner_dist = max((pos - V(cx + sx * half, cy + sy * half, 0)).Length for sx in (-1, 1) for sy in (-1, 1))
        far = view().getCameraNode().farDistance.getValue()
        if far < corner_dist - 1e-6:
            short_clip.append((elev, round(far, 1), round(corner_dist, 1)))
    check("ground grid is never clipped away by the camera's far plane, at any tilt", not short_clip, short_clip)
    views.go(view(), views.view_rotation(views.ISO), fit=True)
    yield 400

    # -- window / crossing / tangent / pick list ------------------------------------------
    bb = body.Shape.BoundBox
    corners = [to_qt(V(x, y, z)) for x in (bb.XMin, bb.XMax) for y in (bb.YMin, bb.YMax) for z in (bb.ZMin, bb.ZMax)]
    xs, ys = [p.x() for p in corners], [p.y() for p in corners]
    tl_pt, br_pt = QtCore.QPoint(min(xs) - 20, min(ys) - 20), QtCore.QPoint(max(xs) + 20, max(ys) + 20)
    drag(tl_pt, br_pt, QtCore.Qt.LeftButton)
    check("window (left->right) around the model selects the body", picks() == [(body.Name, "")], picks())
    mid = to_qt(V(bb.XMin + 8, bb.YMin + 8, bb.ZMax))   # on the top face, away from the bore
    drag(mid + QtCore.QPoint(10, -10), mid + QtCore.QPoint(-10, 10), QtCore.Qt.LeftButton)
    check("crossing (right->left) touching the model selects it", picks() == [(body.Name, "")], picks())
    drag(mid + QtCore.QPoint(-10, -10), mid + QtCore.QPoint(10, 10), QtCore.Qt.LeftButton)
    check("window not enclosing the model selects nothing", picks() == [], picks())
    navigation.set_filter({"face"})
    drag(tl_pt, br_pt, QtCore.Qt.LeftButton)
    n_faces = len(picks())
    navigation.set_filter(set())
    check("face filter: window selects faces", n_faces > 3 and all(n.startswith("Face") for _, n in picks()), n_faces)
    Gui.Selection.clearSelection()
    fillet = next(i for i, f in enumerate(body.Shape.Faces, 1)
                  if f.Surface.__class__.__name__ == "Cylinder" and abs(f.Surface.Radius - 5) < 1e-6
                  and f.CenterOfMass.x > 30 and f.CenterOfMass.y < 20)
    fp = body.Shape.Faces[fillet - 1].CenterOfMass
    pos = to_qt(fp)
    mouse(QtCore.QEvent.MouseButtonDblClick, pos, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton)
    mouse(QtCore.QEvent.MouseButtonRelease, pos, QtCore.Qt.LeftButton, QtCore.Qt.NoButton)
    yield 100
    check("double-click a fillet selects its tangent faces", len(picks()) >= 3, picks())
    Gui.Selection.clearSelection()
    seen = {}

    def grab_popup():
        pop = QtWidgets.QApplication.activePopupWidget()
        seen["items"] = [a.text() for a in pop.actions()] if pop else None
        if pop:
            pop.close()
    QtCore.QTimer.singleShot(300, grab_popup)
    click(to_qt(top_c), QtCore.Qt.AltModifier)
    yield 400
    check("Alt+click opens a pick list of everything under the cursor", seen.get("items") and len(seen["items"]) >= 2, seen.get("items"))

    # -- radial menu + search latency -----------------------------------------------------
    times = []
    for _ in range(10):
        m = radial.open_at(vp().mapToGlobal(c), None)
        times.append(radial.stats["last_open_ms"])
        m.close()
    res["metrics"]["radial_open_ms_median"] = round(statistics.median(times), 2)
    res["metrics"]["radial_open_ms_max"] = round(max(times), 2)
    info = it.info_at(to_qt(top_c))
    m = radial.open_at(vp().mapToGlobal(c), info)
    yield 200
    shot("05_radial")
    check("radial menu: fixed ring (left = delete, right = extrude) plus face commands",
          m.slots[6] == "Kovac_Delete" and m.slots[2] == "Kovac_Extrude" and m.slots[5] == "Kovac_Sketch" and m.slots[0] is not None,
          m.slots)
    m.close()
    w = search.popup()
    qs = []
    for q in ("mea", "front view", "iso", "zz", "sel tan", "home"):
        w.edit.setText(q)
        qs.append(search.stats["last_query_ms"])
    res["metrics"]["search_query_ms_max"] = round(max(qs), 2)
    res["metrics"]["search_entries"] = search.stats["entries"]
    w.edit.setText("measure")
    check("search finds Measure first", w.list.item(0).data(QtCore.Qt.UserRole) == "Kovac_Measure", w.list.item(0).text())
    shot("06_search")
    w.close()
    check("command search key is S", Gui.Command.get("Kovac_Search").getInfo()["shortcut"] == "S")

    # -- regeneration + undo --------------------------------------------------------------
    box = doc.addObject("Part::Box", "Loose")   # outside our command layer, no recompute call
    box.Length = 7
    yield 200
    check("auto-recompute: nothing left touched", "Touched" not in box.State, box.State)
    doc.removeObject("Loose")
    n_before = len(doc.Objects)
    doc.undo()
    yield 100
    while doc.UndoCount and len(doc.Objects) >= n_before:
        doc.undo()
        yield 50
    check("STEP import is one undo step", len([o for o in doc.Objects if hasattr(o, "Shape")]) == 0, [o.Name for o in doc.Objects])
    doc.redo()
    yield 200

    # -- modes keep the model ------------------------------------------------------------
    commands.run("Kovac_Mode_Make")
    yield 100
    visible_groups = [t.objectName() for t in mw.findChildren(QtWidgets.QToolBar) if t.isVisible() and "Group" in t.objectName()]
    check("Make mode swaps the command set, keeps the document", visible_groups == ["kovacGroup_Make_0"] and App.ActiveDocument is doc, visible_groups)
    commands.run("Kovac_Mode_Design")
    shot("07_final")
    res["metrics"]["first_view_animation_s"] = round(t_anim or -1, 3)


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


QtCore.QTimer.singleShot(300, lambda: run(scenario()))

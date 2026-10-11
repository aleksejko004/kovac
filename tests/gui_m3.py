# SPDX-License-Identifier: LGPL-2.1-or-later
"""M3 GUI end-to-end (drawings), run inside FreeCAD's GUI by tests/run_gui.py gui_m3.py.

The L-bracket drawing made through Kovač's Drawing mode only: New drawing panel -> click the
base view down -> drag out the side, top and isometric views -> section and detail by clicking
on the sheet -> hole callouts -> a dimension by clicking two corners -> balloon, parts list ->
PDF and DXF export (checked). Then the thickness changes 6 -> 8 and everything on the sheet
follows with nothing broken or orphaned.
"""
import faulthandler
import json
import os
import sys
import tempfile
import traceback

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtGui, QtWidgets

V = App.Vector
OUT = os.environ["KOVAC_RESULT"]
SHOTS = os.path.join(os.path.dirname(OUT), "screens")
os.makedirs(SHOTS, exist_ok=True)
res = {"checks": [], "metrics": {}, "errors": []}
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_hang = open(OUT + ".hang", "w")
faulthandler.dump_traceback_later(240, file=_hang)


def check(name, ok, detail=""):
    res["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)})
    with open(OUT + ".progress", "a", encoding="utf-8") as f:
        f.write("%s  %s\n" % ("ok  " if ok else "FAIL", name))


def finish(code=0):
    res["passed"] = all(c["ok"] for c in res["checks"]) and not res["errors"]
    with open(OUT, "w") as f:
        json.dump(res, f, indent=1, default=str)
    os._exit(code)


sys.excepthook = lambda t, v, tb: res["errors"].append("".join(traceback.format_exception(t, v, tb)))
QtCore.QTimer.singleShot(280000, lambda: (res["errors"].append("watchdog"), finish(3)))


def settle(cond, timeout_ms=4000, step=100):
    for _ in range(timeout_ms // step):
        if cond():
            return
        yield step


def shot(name):
    Gui.getMainWindow().grab().save(os.path.join(SHOTS, name + ".png"))
    page, _ = sheet()
    if page is not None:                     # the sheet itself, rendered from its scene at 3 px/mm
        import TechDrawGui
        w, h = page.Template.Width.Value, page.Template.Height.Value
        img = QtGui.QImage(int(w * 3), int(h * 3), QtGui.QImage.Format_ARGB32)
        img.fill(QtGui.QColor("white"))
        p = QtGui.QPainter(img)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        TechDrawGui.getSceneForPage(page).render(p, QtCore.QRectF(0, 0, w * 3, h * 3), QtCore.QRectF(0, -h * 10, w * 10, h * 10))
        p.end()
        img.save(os.path.join(SHOTS, name + "_sheet.png"))


def sheet():
    from kovac import drawmode
    return drawmode.page_view_widget()


def mouse(kind, pos, button=QtCore.Qt.NoButton, buttons=QtCore.Qt.NoButton):
    _, gv = sheet()
    w = gv.viewport()
    QtWidgets.QApplication.sendEvent(w, QtGui.QMouseEvent(kind, QtCore.QPointF(pos), QtCore.QPointF(w.mapToGlobal(pos)),
                                                          button, buttons, QtCore.Qt.NoModifier))


def at(x, y):
    from kovac import drawmode
    _, gv = sheet()
    return drawmode.to_screen(gv, x, y)


def click_paper(x, y):
    q = at(x, y)
    mouse(QtCore.QEvent.MouseMove, q)
    mouse(QtCore.QEvent.MouseButtonPress, q, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton)
    mouse(QtCore.QEvent.MouseButtonRelease, q, QtCore.Qt.LeftButton, QtCore.Qt.NoButton)


def drag_paper(a, b, steps=6):
    qa, qb = at(*a), at(*b)
    mouse(QtCore.QEvent.MouseButtonPress, qa, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton)
    for i in range(1, steps + 1):
        mouse(QtCore.QEvent.MouseMove, qa + (qb - qa) * i / steps, QtCore.Qt.NoButton, QtCore.Qt.LeftButton)
    mouse(QtCore.QEvent.MouseButtonRelease, qb, QtCore.Qt.LeftButton, QtCore.Qt.NoButton)


def paper_of(view, p):
    """Paper position of model point p in a view."""
    from kovac import drawing, drawmode
    q = drawing.to_view(view, p)
    ox, oy = drawmode.view_origin(view)
    return ox + q.x, oy - q.y


def bracket(doc):
    from helpers import face_ref, feature, live_bodies, normal, rect, sketch
    from kovac import datum, features, model
    base = sketch(doc, rect(0, 0, 60, 40), name="Base")
    ex = feature(doc, features.Extrude, Profile=base, Length=6)
    body = live_bodies(doc)[0]
    top = face_ref(doc, body, lambda f: normal(f).z > 0.99)
    plane = model.create(doc, datum.DatumPlane, "SketchPlane", Mode="Offset", Base=top, Auto=True)
    doc.recompute()
    wall = datum.sketch_on(doc, plane, "Wall")
    model.insert(doc, wall)
    pts = [V(0, 0, 0), V(6, 0, 0), V(6, 40, 0), V(0, 40, 0)]
    for i in range(4):
        wall.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]))
    model.commit(doc)
    feature(doc, features.Extrude, Profile=wall, Length=34)
    body = live_bodies(doc)[0]
    top = face_ref(doc, body, lambda f: normal(f).z > 0.99 and f.CenterOfMass.x > 10)
    feature(doc, features.Hole, Face=top, Positions=[V(25, 20, 6), V(45, 20, 6)], Size="M5", HoleType="Tapped",
            ThroughAll=True)
    return ex, live_bodies(doc)[0]


def scenario():
    from kovac import commands, drawing, drawmode, shell
    mw = Gui.getMainWindow()
    mw.showMaximized()
    yield 600
    commands.run("Kovac_NewDesign")
    yield 600
    doc = App.ActiveDocument
    ex, body = bracket(doc)
    yield 300

    # New drawing: the panel, then the base view follows the cursor until a click puts it down
    commands.run("Kovac_NewDrawing")
    yield 300
    dock = mw.findChild(QtWidgets.QDockWidget, "kovacNewDrawing")
    check("New drawing opens its panel", dock is not None and dock.isVisible())
    dock.widget().accept()
    yield from settle(lambda: sheet()[0] is not None)
    yield 600
    page, gv = sheet()
    check("the sheet opens in Drawing mode", page is not None and shell.mode() == "Drawing", shell.mode())
    check("title block filled from the design", page.Template.EditableTexts.get("GeneralTolerance") == "ISO 2768-mK"
          and page.Template.EditableTexts.get("Title") == doc.Label, page.Template.EditableTexts)
    click_paper(120, 200)
    yield 800
    groups = [o for o in page.Views if o.TypeId == "TechDraw::DrawProjGroup"]
    check("a click puts the base view down", len(groups) == 1 and abs(groups[0].X.Value - 120) < 1 and abs(groups[0].Y.Value - 200) < 1,
          [(g.X, g.Y) for g in groups])
    g = groups[0]
    front = drawing.front_of(g)
    fw, fh = drawmode._view_size(front)
    ox, oy = drawmode.view_origin(front)
    for target in ((ox + fw + 30, oy), (ox, oy - fh - 30), (ox + fw + 30, oy - fh - 30)):
        drag_paper((ox, oy), target)
        yield 800
    types = sorted(v.Type for v in g.Views)
    check("dragging out adds side, top and isometric views (first angle)", types == ["Front", "FrontTopLeft", "Left", "Top"],
          (types, mw.statusBar().currentMessage(), commands.last_trace[-300:]))
    drawmode._flows.get(id(gv)) and drawmode._flows[id(gv)].finish()
    shot("m3_01_views")

    # section through the holes: click the top view, put the cut line through its middle, place it
    top = next(v for v in g.Views if v.Type == "Top")
    tx, ty = drawmode.view_origin(top)
    commands.run("Kovac_SectionView")
    yield 200
    click_paper(tx, ty)
    yield 200
    mouse(QtCore.QEvent.MouseMove, at(tx, ty))
    yield 100
    click_paper(tx, ty)
    yield 200
    click_paper(330, 200)
    yield 1200
    secs = [o for o in page.Views if o.TypeId == "TechDraw::DrawViewSection"]
    check("section by clicking: hatched, through the holes", len(secs) == 1 and secs[0].CutSurfaceDisplay == "PatHatch"
          and len(secs[0].getVisibleEdges()) > 0 and abs(secs[0].SectionOrigin.y - 20) < 1e-6,
          [(s.SectionOrigin, s.CutSurfaceDisplay) for s in secs])

    # detail of the bend: centre, radius, place
    bx, by = paper_of(front, V(6, 0, 6))
    commands.run("Kovac_DetailView")
    yield 200
    click_paper(bx, by)
    yield 200
    mouse(QtCore.QEvent.MouseMove, at(bx + 5, by))
    yield 100
    click_paper(bx + 5, by)
    yield 200
    click_paper(330, 100)
    yield 1200
    dets = [o for o in page.Views if o.TypeId == "TechDraw::DrawViewDetail"]
    check("detail by clicking", len(dets) == 1 and len(dets[0].getVisibleEdges()) > 0, dets and dets[0].Radius)

    # callouts and centerlines in one go
    commands.run("Kovac_HoleCallouts")
    yield 800
    calls = [o for o in page.Views if hasattr(o, "KovacHole")]
    check("hole and thread callouts from the hole feature", calls and "M5x0.8 - 6H" in calls[0].FormatSpec,
          [c.FormatSpec for c in calls])

    # dimension: click two corners (snap), then where it goes
    commands.run("Kovac_DrawDimension")
    yield 200
    flow = drawmode._flows.get(id(gv))
    for p in (V(60, 0, 0), V(60, 0, 6)):
        x, y = paper_of(front, p)
        mouse(QtCore.QEvent.MouseMove, at(x + 0.4, y + 0.3))
        yield 80
        snapped = flow is not None and flow.marker.isVisible()
        click_paper(x + 0.4, y + 0.3)
        yield 150
    x, y = paper_of(front, V(60, 0, 3))
    click_paper(x + 15, y)
    yield 800
    dims = [o for o in page.Views if hasattr(o, "KovacRefs")]
    check("dimension by clicking two corners, snap marker shown", len(dims) == 1 and snapped and abs(dims[0].getRawValue() - 6) < 1e-6,
          ([d.getRawValue() for d in dims], [d.References2D for d in dims], dims and [__import__("kovac.topo").topo.loads(r)["s"] for r in dims[0].KovacRefs],
           mw.statusBar().currentMessage(), commands.last_trace[-300:], drawing.errors[:2], sorted((round(q.x, 2), round(q.y, 2)) for q in front.getVisibleVertexes())[:12], [tuple(round(c, 2) for c in drawing.to_view(front, p)) for p in (V(60, 0, 0), V(60, 0, 6))], front.getScale()))
    drawmode._flows.get(id(gv)) and drawmode._flows[id(gv)].finish()

    # balloon and parts list
    commands.run("Kovac_Balloon")
    yield 200
    click_paper(*paper_of(front, V(30, 0, 3)))
    yield 150
    click_paper(ox - 10, oy + 30)
    yield 600
    drawmode._flows.get(id(gv)) and drawmode._flows[id(gv)].finish()
    commands.run("Kovac_PartsList")
    yield 800
    check("balloon and parts list placed", any(o.TypeId == "TechDraw::DrawViewBalloon" for o in page.Views)
          and any(o.Name.startswith("PartsList") for o in page.Views))
    shot("m3_02_sheet")

    # export
    tmp = tempfile.mkdtemp()
    pdf, dxf = os.path.join(tmp, "bracket.pdf"), os.path.join(tmp, "bracket.dxf")
    drawing.export_pdf(page, pdf)
    drawing.export_dxf(page, dxf)
    yield 300
    pages = drawing.check_pdf(pdf)
    counts, _ = drawing.check_dxf(dxf)
    check("PDF and DXF export are valid", pages == 1 and counts.get("LINE", 0) > 20, (pages, counts))

    # the model changes: thickness 6 -> 8; the sheet follows by itself
    ex.Length = 8
    from kovac import model
    model.commit(doc)
    yield 1500
    check("thickness 6 -> 8: nothing broken or orphaned on the sheet", not drawing.broken(page)
          and abs(dims[0].getRawValue() - 8) < 1e-6 and all("Invalid" not in o.State for o in page.Views),
          (drawing.broken(page), dims and dims[0].getRawValue(), [o.Label for o in page.Views if "Invalid" in o.State]))
    shot("m3_03_after_change")


def run(gen):
    try:
        delay = next(gen)
    except StopIteration:
        finish(0)
        return
    except Exception:
        res["errors"].append(traceback.format_exc())
        finish(1)
        return
    QtCore.QTimer.singleShot(delay, lambda: run(gen))


QtCore.QTimer.singleShot(400, lambda: run(scenario()))

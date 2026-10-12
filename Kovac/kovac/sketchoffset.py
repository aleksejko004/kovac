# SPDX-License-Identifier: LGPL-2.1-or-later
"""Offset in a sketch, for curves the sketcher's own Offset leaves out.

The sketcher's Offset hands back OpenCascade offset curves, which a sketch cannot hold, for
B-splines and ellipses -- and then adds nothing. Here each picked curve is offset on its own:
a line stays a line and an arc an arc (exact), anything else becomes a cubic B-spline fitted
to its true offset. Picked curves that join end to end are offset as one chain on the same
side: where neighbours' offsets now overlap (an inside corner) both are trimmed to where they
cross, where they part (an outside corner) a round corner about the old point closes the gap.
A selection of only lines, arcs and circles goes to the sketcher's own Offset, as before.
With nothing selected the panel opens and waits: the curves clicked next are offset.
"""
import math

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from kovac import commands, navigation, overlay, palette

V = App.Vector
Z = V(0, 0, 1)
TOL = 1e-6
ARROW_PX, HIT_PX = 130, 14
NATIVE = (Part.LineSegment, Part.ArcOfCircle, Part.Circle)


# ---------------------------------------------------------------- geometry (sketch plane, z = 0)

def _chains(geos):
    """Picked curves grouped into chains that join end to end, each in order as
    [(geometry, reversed)], with whether the chain closes on itself."""
    edges = [g.toShape() for g in geos]
    out = []
    for group in Part.sortEdges(edges):
        w = Part.Wire(group)
        items = []
        for e in w.OrderedEdges:
            i = next(k for k, x in enumerate(edges) if x.isSame(e) or _same(x, e))
            items.append((geos[i], e.Orientation == "Reversed"))
        out.append((items, w.isClosed() if len(items) > 1 else _closed(items[0][0])))
    return out


def _same(a, b):
    return (a.CenterOfMass - b.CenterOfMass).Length < TOL and abs(a.Length - b.Length) < TOL


def _closed(g):
    return isinstance(g, (Part.Circle, Part.Ellipse)) or (
        hasattr(g, "StartPoint") and (g.StartPoint - g.EndPoint).Length < TOL)


def _offset_one(g, d):
    """g offset by d to the left of its own direction (tangent x sketch normal), or None when
    the offset vanishes (an arc shrunk past its centre)."""
    if isinstance(g, Part.LineSegment):
        t = g.EndPoint - g.StartPoint
        n = t.cross(Z).normalize() * d
        return Part.LineSegment(g.StartPoint + n, g.EndPoint + n)
    if isinstance(g, (Part.ArcOfCircle, Part.Circle)):
        c = g.Circle if isinstance(g, Part.ArcOfCircle) else g
        r = c.Radius + d * (1 if c.Axis.z > 0 else -1)
        if r <= TOL:
            return None
        nc = Part.Circle(c.Center, c.Axis, r)
        if isinstance(g, Part.Circle):
            return nc
        nc.XAxis = c.XAxis      # keep the parameter (angle) frame, so the arc's angles carry over
        return Part.ArcOfCircle(nc, g.FirstParameter, g.LastParameter)
    oc = Part.OffsetCurve(g, d, Z)
    a, b = g.FirstParameter, g.LastParameter
    n = 80
    pts = [oc.value(a + (b - a) * k / n) for k in range(n + 1)]
    closed = _closed(g)
    if closed:
        pts = pts[:-1]
    size = max(g.toShape().BoundBox.DiagonalLength, 1.0)
    bs = Part.BSplineCurve()
    if closed:
        bs.interpolate(pts, PeriodicFlag=True)
    else:
        bs.approximate(Points=pts, DegMin=3, DegMax=3, Tolerance=size * 1e-5)
    return bs


def _ends(g, rev):
    """(start, end) along the chain."""
    s, e = g.value(g.FirstParameter), g.value(g.LastParameter)
    return (e, s) if rev else (s, e)


def _trim(g, rev, at_end, p):
    """g cut back (or out) to p at its chain-start or chain-end."""
    u = g.parameter(p)
    a, b = g.FirstParameter, g.LastParameter
    cut_last = at_end != rev            # which parameter end that is
    a, b = (a, u) if cut_last else (u, b)
    if isinstance(g, Part.LineSegment):
        s, e = g.StartPoint, g.EndPoint
        return Part.LineSegment(s, p) if cut_last else Part.LineSegment(p, e)
    if isinstance(g, Part.ArcOfCircle):
        return Part.ArcOfCircle(g.Circle, a, b)
    g = g.copy()
    g.segment(a, b)
    return g


def _round(centre, p, q, r):
    """The short arc about centre from p to q (an outside corner's fill)."""
    a1 = math.atan2(p.y - centre.y, p.x - centre.x)
    a2 = math.atan2(q.y - centre.y, q.x - centre.x)
    sweep = (a2 - a1) % (2 * math.pi)
    if sweep > math.pi:
        a1, a2 = a2, a1
    while a2 <= a1:
        a2 += 2 * math.pi
    return Part.ArcOfCircle(Part.Circle(centre, Z, r), a1, a2)


def offset(geos, d):
    """New geometry for the picked curves offset by d (sketch coordinates). d > 0 is to the left
    of each chain's direction; the caller picks the side by the sign."""
    out = []
    for items, closed in _chains(geos):
        res = []
        for g, rev in items:
            o = _offset_one(g, -d if rev else d)
            if o is None:
                raise ValueError("The offset is larger than an arc's radius.")
            res.append([o, rev])
        joins = list(range(len(res) - 1)) + ([len(res) - 1] if closed and len(res) > 1 else [])
        fills = []
        for i in joins:
            j = (i + 1) % len(res)
            (gi, ri), (gj, rj) = res[i], res[j]
            pe, ps = _ends(gi, ri)[1], _ends(gj, rj)[0]
            if (pe - ps).Length < TOL * 10:
                continue
            corner = _ends(items[i][0], items[i][1])[1]
            dist, pairs, _ = gi.toShape().distToShape(gj.toShape())
            if dist < TOL * 10:                 # inside corner: both run past the other; cut back to the crossing
                x = min((pp[0] for pp in pairs), key=lambda q: (q - corner).Length)
                res[i][0] = _trim(gi, ri, True, x)
                res[j][0] = _trim(res[j][0], rj, False, x)
            else:                               # outside corner: round it about the old point
                fills.append((i, _round(corner, pe, ps, abs(d))))
        for i, arc in reversed(fills):
            res.insert(i + 1, [arc, False])
        out += [g for g, _ in res]
    return out


def add_to(sk, geos):
    """Add geos to sketch sk with their joined ends constrained coincident; B-splines get their
    control points shown, as the sketcher's own spline tool does. Returns the new indices."""
    import Sketcher
    first = len(sk.Geometry)
    ids = [sk.addGeometry(g, False) for g in geos]
    for k in ids:
        if isinstance(sk.Geometry[k], Part.BSplineCurve):
            sk.exposeInternalGeometry(k)
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            for pa in (1, 2):
                for pb in (1, 2):
                    try:
                        if (sk.getPoint(ids[a], pa) - sk.getPoint(ids[b], pb)).Length < 1e-5:
                            sk.addConstraint(Sketcher.Constraint("Coincident", ids[a], pa, ids[b], pb))
                    except Exception:
                        pass
    return list(range(first, first + len(ids)))


# ---------------------------------------------------------------- the tool

def _picks(sk):
    out = []
    for s in Gui.Selection.getSelectionEx("", 1):   # resolved names: a click in a sketch gives ';g1.edge1' unresolved
        if s.Object is not sk:
            continue
        for sub in s.SubElementNames:
            name = sub.split(".")[-1]
            if name.startswith("Edge"):
                g = int(name[4:]) - 1
                if 0 <= g < len(sk.Geometry) and not sk.getConstruction(g) and g not in out:
                    out.append(g)
    return out


class _Arrow:
    """The distance arrow on the first picked curve: drag it across to the other side, or out."""

    in_edit = True

    def __init__(self, tool):
        self.tool, self.node, self.seg, self.dragging = tool, None, None, False
        g = tool.geos[0]
        u = (g.FirstParameter + g.LastParameter) / 2
        rev = next((r for items, _ in _chains(tool.geos) for gg, r in items if gg is g), False)
        t = g.tangent(u)[0]
        n = t.cross(Z).normalize() * (-1 if rev else 1)
        pl = tool.sk.getGlobalPlacement()
        self.base, self.n = pl.multVec(g.value(u)), pl.Rotation.multVec(n)
        navigation.hooks.insert(0, self)
        self.draw()

    def draw(self):
        overlay.remove(self.node)
        it = navigation.install(Gui.activeView())
        px = it.px_size() if it is not None else 0.05
        d = self.tool.d
        at = self.base + self.n * d
        a, b = at, at + self.n * (1 if d >= 0 else -1) * ARROW_PX * px
        self.seg = (a, b)
        self.node = overlay.add(overlay.arrow_node(a, b, palette.accent(), px))

    def handle_at(self, it, pos):
        if self.seg is None:
            return None
        (ax, ay), (bx, by) = (it.qt(it.view.getPointOnViewport(p)) for p in self.seg)
        dx, dy = bx - ax, by - ay
        ll = dx * dx + dy * dy
        t = 0.0 if ll < 1e-9 else max(0.0, min(1.0, ((pos.x() - ax) * dx + (pos.y() - ay) * dy) / ll))
        return True if math.hypot(pos.x() - ax - dx * t, pos.y() - ay - dy * t) <= HIT_PX else None

    def press(self, it, pos):
        if not self.handle_at(it, pos):
            return False
        ro, rd = overlay.ray(it, pos)
        self.grab = self.tool.d - (overlay.closest_on_line(ro, rd, self.base, self.n) - self.base).dot(self.n)
        self.dragging = True
        return True

    def move(self, it, pos):
        ro, rd = overlay.ray(it, pos)
        d = (overlay.closest_on_line(ro, rd, self.base, self.n) - self.base).dot(self.n) + self.grab
        from kovac import grid
        s = grid.step()
        if s and not QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.AltModifier:
            d = round(d / (s / 2)) * (s / 2)
        if abs(d) < 1e-6:
            d = 0.01 if self.tool.d > 0 else -0.01
        self.tool.set(d)

    def release(self, it, pos):
        self.dragging = False

    def detach(self):
        overlay.remove(self.node)
        if self in navigation.hooks:
            navigation.hooks.remove(self)


class Tool:
    """Offset panel: a distance (negative = the other side), a drag arrow, a live preview."""

    def __init__(self, sk, picks):
        from kovac import grid, move, panel
        self.sk, self.picks = sk, picks
        self.geos = [sk.Geometry[k] for k in picks]
        self.arrow = None
        s = grid.step() or 1.0
        self.d, self.preview_node, self.result = s, None, None
        w = QtWidgets.QWidget(objectName="kovacSketchOffset")
        lay = QtWidgets.QVBoxLayout(w)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Distance"))
        self.field = move._Field(w)
        self.field.setObjectName("kovacValue")
        self.field.returnPressed.connect(self.typed_and_ok)
        self.field.editingFinished.connect(self.typed)
        row.addWidget(self.field, 1)
        lay.addLayout(row)
        flip = QtWidgets.QPushButton("Other side")
        flip.clicked.connect(lambda: self.set(-self.d))
        lay.addWidget(flip)
        self.status = QtWidgets.QLabel(objectName="kovacMuted")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        cancel = QtWidgets.QPushButton("Cancel")
        ok = QtWidgets.QPushButton("OK", objectName="kovacPrimary")
        cancel.clicked.connect(self.cancel)
        ok.clicked.connect(self.ok)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        lay.addLayout(buttons)
        self.dock = panel.dock("SketchOffset", "Offset", w, floating=True)
        self.dock.setWindowTitle("Offset")
        self.dock.setWidget(w)
        self.dock.show()
        self.arrow = _Arrow(self) if picks else None
        self.set(self.d)
        self.field.setFocus()
        self.field.selectAll()
        Gui.Selection.addObserver(self)

    # selection observer: the curves to offset follow what is selected (Ctrl adds more)
    def _changed(self, *_a):
        QtCore.QTimer.singleShot(0, self._repick)

    addSelection = removeSelection = setSelection = clearSelection = _changed

    def _repick(self):
        if _tool is not self or (self.arrow is not None and self.arrow.dragging):
            return
        picks = _picks(self.sk)
        if not picks or picks == self.picks:
            return              # a click on empty space keeps what is already picked
        self.picks, self.geos = picks, [self.sk.Geometry[k] for k in picks]
        if self.arrow is not None:
            self.arrow.detach()
        self.arrow = _Arrow(self)
        self.set(self.d)

    def set(self, d):
        self.d = d
        if not self.field.hasFocus():
            self.field.setText("%.2f mm" % d)
        if not self.geos:
            self.result = None
            self.status.setText("Click the curves to offset (Ctrl adds more).")
        else:
            try:
                self.result = offset(self.geos, d)
                self.status.setText("")
            except Exception as e:
                self.result = None
                self.status.setText(str(e))
        if self.arrow is not None:
            self.arrow.draw()
        self.draw_preview()

    def typed(self):
        try:
            q = App.Units.Quantity(self.field.text().strip().replace(",", "."))
            d = q.Value if q.Unit == App.Units.Unit() else q.getValueAs("mm").Value
        except Exception:
            self.field.setStyleSheet("color: %s;" % palette.SEMANTIC["error"])
            return False
        self.field.setStyleSheet("")
        if abs(d) < 1e-9:
            return False
        if abs(d - self.d) > 1e-12:
            self.set(d)
        return True

    def typed_and_ok(self):
        if self.typed():
            self.ok()

    def draw_preview(self):
        overlay.remove(self.preview_node)
        self.preview_node = None
        if not self.result:
            return
        from pivy import coin
        pl = self.sk.getGlobalPlacement()
        sep = coin.SoAnnotation()
        col = coin.SoBaseColor()
        col.rgb = overlay.rgb(palette.accent())
        st = coin.SoDrawStyle()
        st.lineWidth = 2
        sep.addChild(col)
        sep.addChild(st)
        for g in self.result:
            e = g.toShape()
            pts = [pl.multVec(p) for p in e.discretize(Deflection=max(e.Length / 400, 1e-3))]
            crd = coin.SoCoordinate3()
            crd.point.setValues(0, len(pts), [list(p) for p in pts])
            sep.addChild(crd)
            sep.addChild(coin.SoLineSet())
        self.preview_node = overlay.add(sep)

    def ok(self):
        if not self.result:
            return
        doc = self.sk.Document
        result = self.result
        self.close()
        with commands.transaction("Offset", doc):
            add_to(self.sk, result)
            self.sk.recompute()

    def cancel(self):
        self.close()

    def close(self):
        global _tool
        Gui.Selection.removeObserver(self)
        if self.arrow is not None:
            self.arrow.detach()
        overlay.remove(self.preview_node)
        self.dock.setObjectName("")
        self.dock.close()
        self.dock.deleteLater()
        if _tool is self:
            _tool = None


_tool = None


def command():
    global _tool
    from kovac import sketchmode
    if not sketchmode.in_sketch():
        commands.report("Offset works inside a sketch: select its curves first.")
        return
    from kovac import sketchtools
    sketchtools.end_running()
    sk = Gui.ActiveDocument.getInEdit().Object
    picks = _picks(sk)              # nothing picked yet: the panel opens and waits for the clicks
    if picks and all(isinstance(sk.Geometry[k], NATIVE) for k in picks):
        Gui.runCommand("Sketcher_Offset")   # lines, arcs and circles: the sketcher's own does them well
        return
    if _tool is not None:
        _tool.close()
    _tool = Tool(sk, picks)
    return _tool

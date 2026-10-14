# SPDX-License-Identifier: LGPL-2.1-or-later
"""3D curves: a B-spline whose control points sit anywhere in space, not on a sketch plane.

Made from a sketch's free (unconstrained) B-splines -- the spline leaves the sketch and becomes
one of these -- or from scratch. While editing, every control point is a handle: dragging one
moves it in the plane facing the camera, so turning the view and dragging again moves it in
another direction. Sweep and Pattern take one as their path like a path sketch.
"""
import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtGui, QtWidgets

from kovac import commands, navigation, overlay, palette

V = App.Vector
HIT_PX = 12


def is_curve(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "Curve3DProxy"


def curve_shape(points, degree=3, closed=False, knots=(), mults=(), weights=()):
    """Clamped (open) or periodic (closed) B-spline with these control points. Knots, mults
    and weights, when given and consistent, keep an exact shape (an arc or circle taken out of
    a sketch); otherwise the knots are uniform."""
    pts = [V(p) for p in points]
    n = len(pts)
    if n < 2:
        return Part.Shape()
    c = Part.BSplineCurve()
    if knots and len(mults) == len(knots) and (not weights or len(weights) == n):
        try:
            c.buildFromPolesMultsKnots(pts, list(mults), list(knots), closed, degree, list(weights) or None)
            return c.toShape()
        except Exception:
            c = Part.BSplineCurve()
    if closed and n > 2:
        deg = min(degree, n - 1)
        c.buildFromPolesMultsKnots(pts, [1] * (n + 1), [float(k) for k in range(n + 1)], True, deg)
    else:
        deg = min(degree, n - 1)
        inner = n - deg - 1
        knots = [0.0] + [k / (inner + 1) for k in range(1, inner + 1)] + [1.0]
        c.buildFromPolesMultsKnots(pts, [deg + 1] + [1] * inner + [deg + 1], knots, False, deg)
    return c.toShape()


class Curve3DProxy:
    def __init__(self, obj):
        obj.addProperty("App::PropertyVectorList", "Points", "Curve", "control points")
        obj.addProperty("App::PropertyBool", "Closed", "Curve", "closed loop")
        obj.addProperty("App::PropertyInteger", "Degree", "Curve", "polynomial degree").Degree = 3
        self.exact_props(obj)
        obj.Proxy = self

    @staticmethod
    def exact_props(obj):
        for prop, kind in (("Knots", "FloatList"), ("Mults", "IntegerList"), ("Weights", "FloatList")):
            if not hasattr(obj, prop):
                obj.addProperty("App::Property" + kind, prop, "Curve", "exact shape (cleared when points are added or removed)", 4)

    def execute(self, obj):
        obj.Shape = curve_shape(obj.Points, obj.Degree, obj.Closed, getattr(obj, "Knots", ()),
                                getattr(obj, "Mults", ()), getattr(obj, "Weights", ()))

    def dumps(self):
        return None

    def loads(self, _state):
        return None


def create(doc, points, name="Curve3D", closed=False, degree=3, knots=(), mults=(), weights=()):
    obj = doc.addObject("Part::FeaturePython", name)
    Curve3DProxy(obj)
    obj.Points, obj.Closed, obj.Degree = [V(p) for p in points], closed, degree
    obj.Knots, obj.Mults, obj.Weights = list(knots), list(mults), list(weights)
    vo = getattr(obj, "ViewObject", None)
    if vo is not None:
        vo.Proxy = 0
        vo.LineColor = tuple(c / 255.0 for c in palette.rgb(palette.SEMANTIC["sketch_free"]))
        vo.LineWidth = 3
        vo.PointSize = 1
    obj.recompute()
    return obj


# ---------------------------------------------------------------- from a sketch

def free_splines(sk):
    """Indices of the sketch's B-splines that nothing constrains (their own control-point
    helpers, held by internal alignment, don't count)."""
    out = []
    for i, g in enumerate(sk.Geometry):
        if not isinstance(g, Part.BSplineCurve) or sk.getConstruction(i):
            continue
        held = [c for c in sk.Constraints if c.Type != "InternalAlignment" and i in (c.First, c.Second, c.Third)]
        if not held:
            out.append(i)
    return out


def from_sketch(sk, indices=None):
    """Move free B-splines out of a sketch into 3D curves (one undo step); returns them."""
    doc = sk.Document
    indices = free_splines(sk) if indices is None else indices
    if not indices:
        return []
    from kovac import components
    pl = components.local_placement(sk)          # the curve joins the sketch's component
    home = components.holder(sk)
    made = []
    with commands.transaction("3D curve", doc):
        for i in indices:
            g = sk.Geometry[i]
            made.append(from_geometry(doc, g, pl))
            if home is not None:
                home.addObject(made[-1])
        helpers = [k for k, c in enumerate(sk.Constraints) if c.Type == "InternalAlignment" and c.Second in indices]
        drop = sorted({sk.Constraints[k].First for k in helpers} | set(indices), reverse=True)
        for k in drop:
            sk.delGeometry(k)
    return made


def from_geometry(doc, g, pl):
    """A 3D curve with the exact shape of sketch geometry g (sketch placement pl): a line
    becomes two points, anything else its own B-spline."""
    if isinstance(g, Part.LineSegment):
        return create(doc, [pl.multVec(g.StartPoint), pl.multVec(g.EndPoint)], "Curve3D", degree=1)
    b = g if isinstance(g, Part.BSplineCurve) else g.toBSpline()
    return create(doc, [pl.multVec(p) for p in b.getPoles()], "Curve3D", closed=b.isPeriodic(), degree=b.Degree,
                  knots=b.getKnots(), mults=b.getMultiplicities(), weights=b.getWeights())


def _uniform(obj):
    """Adding or removing a point changes the knot count: back to uniform knots."""
    obj.Knots, obj.Mults, obj.Weights = [], [], []


# ---------------------------------------------------------------- editing

_editor = None


def current():
    return _editor


class Editor:
    """Handles on every control point; drag one to move it facing the camera."""

    def __init__(self, obj):
        self.obj, self.node, self.drag, self.selected = obj, None, None, None
        navigation.hooks.insert(0, self)
        self.panel = self._panel()
        self.redraw()

    # drawing -------------------------------------------------------------------
    def redraw(self):
        overlay.remove(self.node)
        from pivy import coin
        pts = list(self.obj.Points)
        sep = coin.SoAnnotation()
        if len(pts) > 1:
            lines = coin.SoSeparator()
            col = coin.SoBaseColor()
            col.rgb = overlay.rgb(palette.SEMANTIC["sketch_free"])
            style = coin.SoDrawStyle()
            style.lineWidth, style.linePattern = 1, 0x0F0F
            crd = coin.SoCoordinate3()
            loop = pts + ([pts[0]] if self.obj.Closed else [])
            crd.point.setValues(0, len(loop), [list(p) for p in loop])
            for n in (col, style, crd, coin.SoLineSet()):
                lines.addChild(n)
            sep.addChild(lines)
        for k, p in enumerate(pts):
            dot = coin.SoSeparator()
            col = coin.SoBaseColor()
            col.rgb = overlay.rgb(palette.accent() if k == self.selected else palette.SEMANTIC["sketch_free"])
            crd = coin.SoCoordinate3()
            crd.point.setValue(p.x, p.y, p.z)
            m = coin.SoMarkerSet()
            m.markerIndex = coin.SoMarkerSet.CIRCLE_FILLED_9_9
            for n in (col, crd, m):
                dot.addChild(n)
            sep.addChild(dot)
        self.node = overlay.add(sep)

    # viewport hook -------------------------------------------------------------
    def _hit(self, it, pos):
        best = None
        for k, p in enumerate(self.obj.Points):
            x, y = it.qt(it.view.getPointOnViewport(p))
            d = ((x - pos.x()) ** 2 + (y - pos.y()) ** 2) ** 0.5
            if d <= HIT_PX and (best is None or d < best[0]):
                best = (d, k)
        return best and best[1]

    def press(self, it, pos):
        k = self._hit(it, pos)
        if k is None:
            return False
        self.selected = k
        self.drag = (k, V(self.obj.Points[k]), V(*it.view.getViewDirection()))
        self.obj.Document.openTransaction("Move curve point")
        self.redraw()
        return True

    def move(self, it, pos):
        if self.drag is None:
            return
        k, start, n = self.drag
        o, d = overlay.ray(it, pos)
        p = overlay.hit_plane(o, d, start, n)
        if p is None:
            return
        pts = list(self.obj.Points)
        pts[k] = p
        self.obj.Points = pts
        self.obj.recompute()
        self.redraw()

    def release(self, it, pos):
        if self.drag is None:
            return
        self.drag = None
        doc = self.obj.Document
        from kovac import model
        model.commit(doc)
        if doc.HasPendingTransaction:
            doc.commitTransaction()

    # panel ---------------------------------------------------------------------
    def _panel(self):
        from kovac import panel
        w = QtWidgets.QWidget(objectName="kovacCurveEditor")
        lay = QtWidgets.QVBoxLayout(w)
        tip = QtWidgets.QLabel("Drag a point to move it facing you; turn the view to move it another way.",
                               objectName="kovacMuted")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        row = QtWidgets.QHBoxLayout()
        add = QtWidgets.QPushButton("Add point")
        add.clicked.connect(self.add_point)
        rem = QtWidgets.QPushButton("Remove point")
        rem.clicked.connect(self.remove_point)
        row.addWidget(add)
        row.addWidget(rem)
        lay.addLayout(row)
        closed = QtWidgets.QCheckBox("Closed loop")
        closed.setChecked(self.obj.Closed)
        closed.toggled.connect(lambda on: self.change("Closed curve", lambda: setattr(self.obj, "Closed", on)))
        lay.addWidget(closed)
        done = QtWidgets.QPushButton("Done", objectName="kovacPrimary")
        done.clicked.connect(finish)
        lay.addWidget(done)
        self.esc = QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Escape), Gui.getMainWindow())
        self.esc.setContext(QtCore.Qt.ApplicationShortcut)
        self.esc.activated.connect(finish)
        d = panel.dock("Curve3D", "3D curve: " + self.obj.Label, w, floating=True)
        d.setWindowTitle("3D curve: " + self.obj.Label)
        d.setWidget(w)
        d.show()
        d.raise_()
        return d

    def change(self, what, fn):
        from kovac import model
        with commands.transaction(what, self.obj.Document):
            fn()
            model.commit(self.obj.Document)
        self.redraw()

    def add_point(self):
        pts = list(self.obj.Points)
        k = len(pts) - 1 if self.selected is None else self.selected
        if len(pts) < 2:
            new = pts[-1] + V(10, 0, 0) if pts else V()
            at = len(pts)
        elif k >= len(pts) - 1:                    # past the end, continuing its direction
            new, at = pts[-1] + (pts[-1] - pts[-2]), len(pts)
        else:                                       # halfway to the next one
            new, at = (pts[k] + pts[k + 1]) * 0.5, k + 1
        pts.insert(at, new)
        self.selected = at
        self.change("Add curve point", lambda: (_uniform(self.obj), setattr(self.obj, "Points", pts)))

    def remove_point(self):
        pts = list(self.obj.Points)
        if len(pts) <= 2:
            commands.report("A curve needs at least two points.")
            return
        k = len(pts) - 1 if self.selected is None else self.selected
        del pts[k]
        self.selected = None
        self.change("Remove curve point", lambda: (_uniform(self.obj), setattr(self.obj, "Points", pts)))

    def close(self):
        overlay.remove(self.node)
        if self in navigation.hooks:
            navigation.hooks.remove(self)
        self.esc.setEnabled(False)
        self.esc.deleteLater()
        self.panel.setObjectName("")
        self.panel.close()
        self.panel.deleteLater()


def edit(obj):
    global _editor
    finish()
    _editor = Editor(obj)
    return _editor


def finish():
    global _editor
    if _editor is not None:
        ed, _editor = _editor, None
        ed.close()


def _new_in_view(doc):
    """Four points in a row across the middle of the view, facing the camera."""
    view = Gui.activeView()
    it = navigation.install(view)
    cam = view.getCameraNode()
    centre = navigation.camera_focus(cam)
    rot = view.getCameraOrientation()
    right = rot.multVec(V(1, 0, 0))
    up = rot.multVec(V(0, 1, 0))
    s = it.px_size() * 80 if it is not None else 20
    pts = [centre + right * (k - 1.5) * s + up * (s * 0.6 if k in (1, 2) else 0) for k in range(4)]
    with commands.transaction("3D curve", doc):
        return create(doc, pts)


def command():
    """3D curve: in a sketch, its free B-splines become 3D curves; a selected 3D curve opens
    for editing; otherwise a new one is placed across the view."""
    from kovac import sketchmode
    doc = App.ActiveDocument
    if doc is None:
        from kovac import startpage
        doc = startpage.new_design()
    if sketchmode.in_sketch():
        sk = Gui.ActiveDocument.getInEdit().Object
        if not free_splines(sk):
            commands.report("Draw a B-spline (G, B, B) without constraints on it first; it then becomes a 3D curve.")
            return
        sketchmode.finish()
        made = from_sketch(sk)
        if made:
            edit(made[0])
        return
    for s in Gui.Selection.getSelectionEx("", 0):
        if is_curve(s.Object):
            return edit(s.Object)
        if s.Object.TypeId.startswith("Sketcher::") and free_splines(s.Object):
            made = from_sketch(s.Object)
            return edit(made[0])
    edit(_new_in_view(doc))

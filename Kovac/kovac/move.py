# SPDX-License-Identifier: LGPL-2.1-or-later
"""Move: one tool for bodies, construction planes, sketch points and lines, and faces.

What is selected decides what moves. The on-canvas triad has an arrow along each axis (drag to
slide along it) and a turning handle around each one (drag to rotate about it); distances snap
to the grid step, angles to 5 degrees. The amount moved or turned with the last handle shows in
a field next to it: type a value there and Enter moves it exactly that far.
Bodies move as a history feature (Transform, about the bodies' own centre); construction planes
are set free where they are dropped; sketch points and lines move in the sketch plane and turn
about its normal; a face pushes or pulls along its normal (Face Pull).
"""
import math

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

import kovac
from kovac import commands, model, navigation, overlay, palette, topo

V = App.Vector
ARROW_PX, RING_PX, HIT_PX = 150, 108, 12
ANGLE_STEP = 5.0


def _axis_colours():
    t = palette.theme(kovac.theme_name())
    return [t["axis_x"], t["axis_y"], t["axis_z"]]


class Triad:
    """Navigation hook: three axis arrows and three turning handles at a pivot.

    frame()      -> (pivot, [axis vectors]) where it is drawn now
    translate(i, d) / rotate(i, degrees): called live with the total since the press
    begin() / end(): around each drag (one undo step)
    rotations: which axes get a turning handle; translations: which get an arrow."""

    def __init__(self, target, translations=(0, 1, 2), rotations=(0, 1, 2)):
        self.t, self._handles = target, (translations, rotations)
        self.node, self.drag, self.label = None, None, None
        self.last, self.totals = None, {}   # the handle last used, and each handle's total so far
        self.in_edit = True                 # takes clicks inside a sketch too (only on its own handles)
        navigation.hooks.insert(0, self)
        self.redraw()

    def _which(self):
        h = self.t.handles() if hasattr(self.t, "handles") else None
        return h if h is not None else self._handles

    @property
    def translations(self):
        return self._which()[0]

    @property
    def rotations(self):
        return self._which()[1]

    # drawing -------------------------------------------------------------------
    def _px(self):
        it = navigation.install(Gui.activeView()) if Gui.activeView() is not None else None
        return it.px_size() if it is not None else 0.1

    def _ring(self, p, a, b, r, steps=16):
        """Arc between axis a and axis b at radius r, kept clear of both arrows (15 to 75
        degrees); the handle turns about a x b."""
        lo, hi = math.radians(15), math.radians(75)
        return [p + (a * math.cos(lo + (hi - lo) * k / steps) + b * math.sin(lo + (hi - lo) * k / steps)) * r
                for k in range(steps + 1)]

    def redraw(self):
        overlay.remove(self.node)
        from pivy import coin
        frame = self.t.frame()
        if frame is None:
            self.node = None
            return
        p, axes = frame
        px = self._px()
        cols = _axis_colours()
        sep = coin.SoAnnotation()
        for i in self.translations:
            hot = self.drag is not None and self.drag[0] == ("t", i)
            sep.addChild(overlay.arrow_node(p, p + axes[i] * ARROW_PX * px, palette.accent() if hot else cols[i], px))
        for i in self.rotations:
            a, b = axes[(i + 1) % 3], axes[(i + 2) % 3]
            pts = self._ring(p, a, b, RING_PX * px)
            hot = self.drag is not None and self.drag[0] == ("r", i)
            col = palette.accent() if hot else cols[i]
            ring = coin.SoSeparator()
            c = coin.SoBaseColor()
            c.rgb = overlay.rgb(col)
            st = coin.SoDrawStyle()
            st.lineWidth = 5
            crd = coin.SoCoordinate3()
            crd.point.setValues(0, len(pts), [list(q) for q in pts])
            for n in (c, st, crd, coin.SoLineSet()):
                ring.addChild(n)
            sep.addChild(ring)
            sep.addChild(overlay.arrow_node(pts[-2], pts[-1] + (pts[-1] - pts[-2]).normalize() * 16 * px, col, px * 0.55))
        self.node = overlay.add(sep)

    # picking -------------------------------------------------------------------
    def _screen(self, it, q):
        return QtCore.QPointF(*it.qt(it.view.getPointOnViewport(q)))

    @staticmethod
    def _seg_dist(p, a, b):
        ab = b - a
        L = ab.x() ** 2 + ab.y() ** 2
        t = 0 if L < 1e-9 else max(0.0, min(1.0, ((p - a).x() * ab.x() + (p - a).y() * ab.y()) / L))
        q = a + ab * t
        return math.hypot(p.x() - q.x(), p.y() - q.y())

    def handle_at(self, it, pos):
        frame = self.t.frame()
        if frame is None:
            return None
        p, axes = frame
        px = it.px_size()
        pos = QtCore.QPointF(pos)
        best = None
        for i in self.translations:
            d = self._seg_dist(pos, self._screen(it, p + axes[i] * ARROW_PX * px * 0.25),
                               self._screen(it, p + axes[i] * ARROW_PX * px))
            if d <= HIT_PX and (best is None or d < best[0]):
                best = (d, ("t", i))
        for i in self.rotations:
            pts = [self._screen(it, q) for q in self._ring(p, axes[(i + 1) % 3], axes[(i + 2) % 3], RING_PX * px)]
            d = min(self._seg_dist(pos, a, b) for a, b in zip(pts, pts[1:]))
            if d <= HIT_PX and (best is None or d < best[0]):
                best = (d, ("r", i))
        return best and best[1]

    # viewport hook -------------------------------------------------------------
    def press(self, it, pos):
        h = self.handle_at(it, pos)
        if h is None:
            return False
        p, axes = self.t.frame()
        start = None
        if h[0] == "r":
            o, d = overlay.ray(it, pos)
            start = overlay.hit_plane(o, d, p, axes[h[1]])
        self.drag = (h, V(p), [V(a) for a in axes], start)
        self.last, self.drag_value = h, 0.0
        self.t.begin(h)
        self.redraw()
        self._show(self.totals.get(h, 0.0))
        return True

    def move(self, it, pos):
        if self.drag is None:
            return
        (kind, i), p, axes, start = self.drag
        o, d = overlay.ray(it, pos)
        if kind == "t":
            q = overlay.closest_on_line(o, d, p, axes[i])
            value = (q - p).dot(axes[i])
            from kovac import grid
            s = grid.step()
            if s and not QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.AltModifier:
                value = round(value / (s / 2)) * (s / 2)
            self.t.translate(i, value)
            self.drag_value = value
        else:
            q = overlay.hit_plane(o, d, p, axes[i])
            if q is None or start is None:
                return
            a, b = (start - p), (q - p)
            if a.Length < 1e-9 or b.Length < 1e-9:
                return
            ang = math.degrees(math.atan2(a.cross(b).dot(axes[i]), a.dot(b)))
            if not QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.AltModifier:
                ang = round(ang / ANGLE_STEP) * ANGLE_STEP
            self.t.rotate(i, ang)
            self.drag_value = ang
        self.redraw()
        self._show(self.totals.get((kind, i), 0.0) + self.drag_value)

    def release(self, it, pos):
        if self.drag is None:
            return
        h = self.drag[0]
        self.totals[h] = self.totals.get(h, 0.0) + getattr(self, "drag_value", 0.0)
        self.drag, self.drag_value = None, 0.0
        self.t.end()
        self.redraw()
        self._show(self.totals[h])
        if self.label is not None:          # click a handle, type the amount
            self.label.setFocus()
            self.label.selectAll()

    # the value field ----------------------------------------------------------
    def _tip(self, h):
        """Where the field sits: by the arrow's head, or by the end of the turning handle."""
        frame = self.t.frame()
        if frame is None:
            return None
        p, axes = frame
        px = self._px()
        kind, i = h
        if kind == "t":
            return p + axes[i] * ARROW_PX * px
        return self._ring(p, axes[(i + 1) % 3], axes[(i + 2) % 3], RING_PX * px)[-1]

    @staticmethod
    def _text(h, value):
        return ("%.2f mm" % value) if h[0] == "t" else ("%.1f°" % value).replace(".0°", "°")

    def _show(self, value):
        """The amount moved (an arrow: a length) or turned (a handle: an angle) along the last
        handle used, next to it: type another value and Enter moves it there."""
        h = self.last
        view = Gui.activeView()
        if h is None or view is None or not hasattr(view, "graphicsView"):
            return
        vp = view.graphicsView().viewport()
        if self.label is None:
            self.label = _Field(vp)
            self.label.setFixedWidth(110)
            self.label.returnPressed.connect(self._typed)
            self.label.setToolTip("Distance along the arrow, or angle about the handle: type a value, Enter")
        if not (self.label.hasFocus() and self.drag is None):
            self.label.setText(self._text(h, value))
        tip = self._tip(h)
        if tip is not None:
            r = vp.devicePixelRatioF()
            x, y = view.getPointOnViewport(tip)
            self.label.move(int(x / r) + 14, int(vp.height() - y / r) - 30)
        self.label.show()

    def _typed(self):
        h = self.last
        if h is None:
            return
        text = self.label.text().strip()
        try:
            q = App.Units.Quantity(text.replace(",", "."))
            value = q.Value if q.Unit == App.Units.Unit() else q.getValueAs("mm" if h[0] == "t" else "deg").Value
        except Exception:
            self.label.setStyleSheet("color: %s;" % palette.SEMANTIC["error"])
            return
        self.label.setStyleSheet("")
        delta = value - self.totals.get(h, 0.0)
        if abs(delta) > 1e-12:
            self.t.begin(h)                  # one undo step, as a drag of exactly that much
            (self.t.translate if h[0] == "t" else self.t.rotate)(h[1], delta)
            self.t.end()
            self.totals[h] = value
        self.label.clearFocus()
        self.redraw()
        self._show(value)

    def refresh(self):          # an editor hook: redraw after the panel changed something
        self.redraw()
        if self.label is not None and self.label.isVisible():
            self._show(self.totals.get(self.last, 0.0))

    def detach(self):
        overlay.remove(self.node)
        if self.label is not None:
            self.label.deleteLater()
            self.label = None
        if self in navigation.hooks:
            navigation.hooks.remove(self)


class _Field(QtWidgets.QLineEdit):
    """The triad's value field: Enter here applies the value (it never reaches the panel's
    own Enter = OK), Esc gives the keyboard back to the view."""

    def __init__(self, parent):
        super().__init__(parent, objectName="kovacFloatingField")

    def event(self, ev):
        if ev.type() == QtCore.QEvent.ShortcutOverride and ev.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            ev.accept()
            return True
        return super().event(ev)


WORLD = [V(1, 0, 0), V(0, 1, 0), V(0, 0, 1)]


# ---------------------------------------------------------------- bodies (history: Transform)

def bodies_centre(fp):
    box = App.BoundBox()
    state = model.input_state(fp)
    for bid in fp.Bodies:
        if bid in state:
            box.add(state[bid].shape.BoundBox)
    return box.Center if box.isValid() else V()


class BodyTarget:
    """The open Move panel's feature: the triad sits on the moved pivot and edits fp.Move."""

    def __init__(self, ed):
        self.ed = ed

    def frame(self):
        fp = self.ed.fp
        if not fp.Bodies:
            return None
        if not getattr(self, "pivot_for", None) == tuple(fp.Bodies):
            self.pivot_for = tuple(fp.Bodies)
            fp.Pivot = bodies_centre(fp)
        return effective(fp).multVec(fp.Pivot), WORLD

    def begin(self, handle=None):
        self.start = App.Placement(self.ed.fp.Move)

    def translate(self, i, d):
        m = App.Placement(self.start)
        m.Base = m.Base + WORLD[i] * d
        self.ed.set("Move", m)

    def rotate(self, i, ang):
        m = App.Placement(self.start)
        m.Rotation = App.Rotation(WORLD[i], ang).multiply(m.Rotation)
        self.ed.set("Move", m)

    def end(self):
        self.ed.preview()


class FaceTarget(BodyTarget):
    """Move Face: a flat face pushes or pulls along its normal and tilts about the two
    directions in its plane; a round face also slides sideways and tilts its axis."""

    def _face(self):
        try:
            return topo.element(model.input_state(self.ed.fp), self.ed.fp.Face)[1]
        except Exception:
            return None

    def _local(self, f):
        if isinstance(f.Surface, Part.Plane):
            n = f.normalAt(*f.Surface.parameter(f.CenterOfMass))
            centre = f.CenterOfMass
        else:
            s = f.Surface
            n = s.Axis.normalize()
            ts = [(v.Point - s.Center).dot(n) for v in f.Vertexes] or [0.0]
            centre = s.Center + n * ((min(ts) + max(ts)) / 2)
        u = n.cross(V(0, 0, 1)) if abs(n.z) < 0.9 else n.cross(V(1, 0, 0))
        u.normalize()
        return centre, [u, n.cross(u), n]

    def handles(self):
        f = self._face()
        if f is None:
            return (), ()
        return ((2,) if isinstance(f.Surface, Part.Plane) else (0, 1, 2)), (0, 1)

    def frame(self):
        fp = self.ed.fp
        f = self._face() if fp.Face else None
        if f is None:
            return None
        centre, axes = self._local(f)
        if getattr(self, "pivot_for", None) != fp.Face:
            self.pivot_for = fp.Face
            fp.Pivot = centre
        m = App.Placement(fp.Move.Base, fp.Move.Rotation, fp.Pivot)
        self.axes = [m.Rotation.multVec(a) for a in axes]
        return m.multVec(fp.Pivot), self.axes

    def translate(self, i, d):
        m = App.Placement(self.start)
        m.Base = m.Base + self.axes_start[i] * d
        self.ed.set("Move", m)

    def rotate(self, i, ang):
        m = App.Placement(self.start)
        m.Rotation = App.Rotation(self.axes_start[i], ang).multiply(m.Rotation)
        self.ed.set("Move", m)

    def begin(self, handle=None):
        BodyTarget.begin(self)
        self.axes_start = [V(a) for a in self.frame()[1]]


def effective(fp):
    """fp.Move (an offset and a turn) applied about the bodies' pivot."""
    pivot = getattr(fp, "Pivot", V())
    return App.Placement(fp.Move.Base, fp.Move.Rotation, pivot)


# ---------------------------------------------------------------- direct sessions

class Session:
    """A triad outside the feature panels: one undo step per drag, Done or Esc ends it."""

    def __init__(self, target, title, move_type=None, **triad):
        self.target, self.move_type = target, move_type
        target.session = self
        self.triad = Triad(self, **triad)
        from kovac import panel
        from PySide import QtGui
        w = QtWidgets.QWidget(objectName="kovacMoveSession")
        lay = QtWidgets.QVBoxLayout(w)
        if move_type is not None:           # the same "Move" drop-down as the Bodies / Faces panel
            row = QtWidgets.QHBoxLayout()
            row.addWidget(QtWidgets.QLabel("Move"))
            combo = QtWidgets.QComboBox(objectName="kovacMoveType")
            combo.addItems(TYPES)
            combo.setCurrentText(move_type)
            combo.currentTextChanged.connect(lambda t: QtCore.QTimer.singleShot(0, lambda: switch(self, t)))
            row.addWidget(combo, 1)
            lay.addLayout(row)
        tip = QtWidgets.QLabel(("Click the sketch points or lines to move. " if move_type == "Points" else "") +
                               "Drag an arrow to slide, a curved handle to turn; click one to type the amount. "
                               "Alt: no snapping.", objectName="kovacMuted")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        done = QtWidgets.QPushButton("Done", objectName="kovacPrimary")
        done.clicked.connect(finish)
        lay.addWidget(done)
        self.esc = QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Escape), Gui.getMainWindow())
        self.esc.setContext(QtCore.Qt.ApplicationShortcut)
        self.esc.activated.connect(finish)
        self.dock = panel.dock("MoveSession", title, w, floating=True)
        self.dock.setWindowTitle(title)
        self.dock.setWidget(w)
        self.dock.show()

    # the triad's target, forwarded with the undo step around it
    def frame(self):
        return self.target.frame()

    def handles(self):
        return self.target.handles() if hasattr(self.target, "handles") else None

    def begin(self, handle=None):
        self.target.doc.openTransaction("Move")
        self.target.begin(handle)

    def translate(self, i, d):
        self.target.translate(i, d)

    def rotate(self, i, ang):
        self.target.rotate(i, ang)

    def end(self):
        model.commit(self.target.doc)
        if self.target.doc.HasPendingTransaction:
            self.target.doc.commitTransaction()

    def close(self):
        self.triad.detach()
        if hasattr(self.target, "detach"):
            self.target.detach()
        self.esc.setEnabled(False)
        self.esc.deleteLater()
        self.dock.setObjectName("")
        self.dock.close()
        self.dock.deleteLater()


class PlaneTarget:
    """A construction plane: dropped where it is dragged (its mode becomes Free)."""

    def __init__(self, plane):
        self.plane, self.doc = plane, plane.Document

    def frame(self):
        r = self.plane.Placement.Rotation
        return self.plane.Placement.Base, [r.multVec(a) for a in WORLD]

    def begin(self, handle=None):
        if self.plane.Mode != "Free":
            self.plane.FreePlacement = self.plane.Placement
            self.plane.Mode = "Free"
        self.start = App.Placement(self.plane.FreePlacement)
        self.axes = self.frame()[1]

    def translate(self, i, d):
        m = App.Placement(self.start)
        m.Base = m.Base + self.axes[i] * d
        self._set(m)

    def rotate(self, i, ang):
        m = App.Placement(self.start)
        m.Rotation = App.Rotation(self.axes[i], ang).multiply(m.Rotation)
        self._set(m)

    def _set(self, m):
        self.plane.FreePlacement = m
        self.plane.recompute()
        self.plane.Placement = m


class SketchTarget:
    """Picked points and lines of a sketch being edited. Sliding in the plane or turning about
    its normal stays in the sketch. The first drag out of the plane (the Z arrow, or turning
    about X or Y) lifts the picked geometry -- and anything whose end touches a moved point, so
    corners stay joined -- out of the sketch as 3D curves (exact shapes); from then on the
    points move freely in 3D."""

    OUT_OF_PLANE = (("t", 2), ("r", 0), ("r", 1))

    def __init__(self, sk, picks):
        self.sk, self.doc = sk, sk.Document
        self.picks = picks          # [(geo index, pos)] pos 0 = whole curve, 1/2/3 = start/end/centre
        self.lifted = None          # [(3D curve, pole indices that move)] once out of the plane

    def _points(self):
        out = []
        for g, pos in self.picks:
            geo = self.sk.Geometry[g]
            out.append(self.sk.getPoint(g, pos) if pos else (geo.StartPoint if hasattr(geo, "StartPoint") else
                                                              getattr(geo, "Center", V())))
        return out

    def frame(self):
        pl = self.sk.getGlobalPlacement()
        axes = [pl.Rotation.multVec(a) for a in WORLD]
        if self.lifted is not None:
            pts = [c.Points[k] for c, idx in self.lifted for k in idx]
            return (sum(pts, V()) * (1.0 / len(pts)) if pts else pl.Base), axes
        pts = self._points()
        c = sum(pts, V()) * (1.0 / len(pts)) if pts else V()
        return pl.multVec(c), axes

    def begin(self, handle=None):
        if self.lifted is None and handle in self.OUT_OF_PLANE:
            self._lift()
        if self.lifted is not None:
            self.start3d = {c.Name: list(c.Points) for c, _ in self.lifted}
            self.pivot, self.axes = self.frame()
            return
        self.geo = [g.copy() for g in self.sk.Geometry]
        pl = self.sk.getGlobalPlacement()
        self.centre = pl.inverse().multVec(self.frame()[0])

    # -- lifting out of the sketch --------------------------------------------------
    def _lift(self):
        from kovac import curve3d
        sk, pl = self.sk, self.sk.getGlobalPlacement()
        geo = sk.Geometry
        moved = []                                   # sketch-local points that move
        whole = set()
        for g, pos in self.picks:
            if pos in (0, 3):
                whole.add(g)
                g0 = geo[g]
                moved += [p for p in (getattr(g0, "StartPoint", None), getattr(g0, "EndPoint", None)) if p is not None]
            else:
                moved.append(sk.getPoint(g, pos))
        near = lambda a, b: a is not None and (a - b).Length < 1e-6      # noqa: E731
        affected = sorted(whole | {g for g, _ in self.picks} | {
            i for i, g0 in enumerate(geo) if not sk.getConstruction(i) and not isinstance(g0, Part.Point)
            and any(near(getattr(g0, "StartPoint", None), p) or near(getattr(g0, "EndPoint", None), p) for p in moved)})
        affected = [i for i in affected if not isinstance(geo[i], Part.Point)]
        if not affected:
            commands.report("Only lines and curves can leave the sketch plane.")
            return
        self.lifted = []
        for i in affected:
            c = curve3d.from_geometry(self.doc, geo[i], pl)
            n = len(c.Points)
            if i in whole:
                idx = set(range(n))
            else:
                idx = set()
                for p in moved:
                    if near(getattr(geo[i], "StartPoint", None), p):
                        idx.add(0)
                    if near(getattr(geo[i], "EndPoint", None), p):
                        idx.add(n - 1)
            self.lifted.append((c, sorted(idx)))
        for i in sorted(affected, reverse=True):
            sk.delGeometry(i)
        sk.recompute()

    # -- moving -----------------------------------------------------------------
    def _apply3d(self, m):
        for c, idx in self.lifted:
            pts = list(self.start3d[c.Name])
            for k in idx:
                pts[k] = m.multVec(pts[k])
            c.Points = pts
            c.recompute()

    def _apply(self, m):
        geo = [g.copy() for g in self.geo]
        whole = {g for g, pos in self.picks if pos == 0}
        for g in whole:
            geo[g].transform(m.toMatrix())
        self.sk.Geometry = geo
        for g, pos in self.picks:
            if pos and g not in whole:
                self.sk.moveGeometry(g, pos, m.multVec(self.geo_point(g, pos)), False)
        self.sk.recompute()

    def geo_point(self, g, pos):
        geo = self.geo[g]
        return {1: getattr(geo, "StartPoint", None), 2: getattr(geo, "EndPoint", None),
                3: getattr(geo, "Center", None)}.get(pos) or (V(geo.X, geo.Y, geo.Z) if hasattr(geo, "X") else V())

    def translate(self, i, d):
        if self.lifted is not None:
            return self._apply3d(App.Placement(self.axes[i] * d, App.Rotation()))
        if i == 2:
            return
        self._apply(App.Placement(WORLD[i] * d, App.Rotation()))

    def rotate(self, i, ang):
        if self.lifted is not None:
            return self._apply3d(App.Placement(V(), App.Rotation(self.axes[i], ang), self.pivot))
        if i != 2:
            return
        self._apply(App.Placement(V(), App.Rotation(V(0, 0, 1), ang), self.centre))


class PointsTarget:
    """Move's "Points": the sketch points and lines picked -- in the sketch being edited, or
    clicked on a sketch in the view -- moved as a SketchTarget. Until something is picked the
    triad waits; picking other points moves the triad over to them."""

    def __init__(self):
        self.inner, self.session = None, None
        self.pick()
        Gui.Selection.addObserver(self)

    @property
    def doc(self):
        return self.inner.doc if self.inner is not None else App.ActiveDocument

    def pick(self):
        found = current_points()
        if found:
            self.inner = SketchTarget(*found)

    def handles(self):
        return ((0, 1, 2), (0, 1, 2)) if self.inner is not None else ((), ())

    def frame(self):
        return self.inner.frame() if self.inner is not None else None

    def begin(self, handle=None):
        self.inner.begin(handle)

    def translate(self, i, d):
        self.inner.translate(i, d)

    def rotate(self, i, ang):
        self.inner.rotate(i, ang)

    # selection observer
    def _changed(self, *_a):
        QtCore.QTimer.singleShot(0, self._repick)

    addSelection = removeSelection = setSelection = clearSelection = _changed

    def _repick(self):
        s = self.session
        if s is None or s.triad.drag is not None:
            return
        before = self.inner
        self.pick()
        if self.inner is not before:
            s.triad.totals, s.triad.last = {}, None
            if s.triad.label is not None:
                s.triad.label.hide()
        s.triad.redraw()

    def detach(self):
        Gui.Selection.removeObserver(self)


def shape_picks(sk, subs):
    """Sketch elements clicked in the view outside the sketch (names of the sketch's shape) as
    (geo index, point pos): a corner takes every point lying on it, so joined ends stay joined."""
    inv = sk.Placement.inverse()
    out = []
    geo = sk.Geometry
    for sub in subs:
        name = sub.split(".")[-1]
        if name.startswith("Vertex"):
            p = inv.multVec(sk.Shape.Vertexes[int(name[6:]) - 1].Point)
            for g in range(len(geo)):
                for pos in (1, 2, 3):
                    try:
                        q = sk.getPoint(g, pos)
                    except Exception:
                        continue
                    if (q - p).Length < 1e-6 and (g, pos) not in out:
                        out.append((g, pos))
        elif name.startswith("Edge"):
            e = sk.Shape.Edges[int(name[4:]) - 1]
            mid = Part.Vertex(inv.multVec(e.valueAt((e.FirstParameter + e.LastParameter) / 2)))
            for g, g0 in enumerate(geo):
                if sk.getConstruction(g) or isinstance(g0, Part.Point):
                    continue
                if g0.toShape().distToShape(mid)[0] < 1e-6 and (g, 0) not in out:
                    out.append((g, 0))
                    break
    return out


def current_points():
    """(sketch, picks) for the sketch elements selected now, or None."""
    from kovac import sketchmode
    if sketchmode.in_sketch():
        sk = Gui.ActiveDocument.getInEdit().Object
        picks = sketch_picks(sk)
        return (sk, picks) if picks else None
    for s in Gui.Selection.getSelectionEx("", 1):   # resolved names: a click in a sketch gives ';g1.edge1' unresolved
        if s.Object.TypeId.startswith("Sketcher::SketchObject"):
            picks = shape_picks(s.Object, s.SubElementNames)
            if picks:
                return s.Object, picks
    return None


def points():
    from kovac import sketchmode, sketchtools
    if sketchmode.in_sketch():
        sketchtools.end_running()
    return _start(PointsTarget(), "Move sketch points", move_type="Points")


_session = None


def finish():
    global _session
    if _session is not None:
        s, _session = _session, None
        s.close()


def _start(target, title, **triad):
    global _session
    finish()
    from kovac import curve3d, editor
    curve3d.finish()
    if editor.current() is not None:
        editor.close_current()
    _session = Session(target, title, **triad)
    return _session


def sketch_picks(sk):
    """The selected sketch elements as (geo index, point pos)."""
    out = []
    for s in Gui.Selection.getSelectionEx("", 1):   # resolved names: a click in a sketch gives ';g1.edge1' unresolved
        if s.Object is not sk:
            continue
        for sub in s.SubElementNames:
            name = sub.split(".")[-1]
            if name.startswith("Edge"):
                out.append((int(name[4:]) - 1, 0))
            elif name.startswith("Vertex"):
                g, pos = sk.getGeoVertexIndex(int(name[6:]) - 1)
                if g >= 0:
                    out.append((g, pos))
    return out


def command():
    from kovac import design, editor, sketchmode
    if sketchmode.in_sketch() or current_points():
        return points()
    sel = Gui.Selection.getSelectionEx("", 0)
    for s in sel:
        if type(getattr(s.Object, "Proxy", None)).__name__ == "DatumPlane" and not getattr(s.Object, "Auto", False):
            return _start(PlaneTarget(s.Object), "Move " + s.Object.Label)
    faces = [model.pick_ref(s.Object, sub) for s in sel for sub in s.SubElementNames if sub.split(".")[-1].startswith("Face")]
    faces = [f for f in faces if f]
    global _picked_faces
    _picked_faces = faces
    kinds = set(getattr(navigation.select_filter, "kinds", None) or ())
    if faces and "face" in kinds and "body" not in kinds:       # the Faces filter: move or tilt the face
        from kovac import modify
        return editor.start(modify.MoveFace, Face=faces[0])
    ed = editor.start(_transform(), Bodies=design.selected_bodies())
    if ed.fp.Bodies:
        ed.fp.Pivot = bodies_centre(ed.fp)
    return ed


_picked_faces = []      # the faces picked when Move started, for switching to "Faces" in its panel
TYPES = ("Bodies", "Faces", "Points")


def type_of(fp):
    return "Faces" if type(fp.Proxy).kind == "MoveFace" else "Bodies"


def switch(source, what):
    """The "Move" drop-down (in the Bodies / Faces panel and in the Points window): drop the
    move being set up and start the other kind on the same picks -- a face's body for Bodies,
    the picked face (or one to pick) for Faces, the selected sketch points for Points."""
    from kovac import design, editor, modify, sketchmode
    session = isinstance(source, Session)
    if what == (source.move_type if session else type_of(source.fp)):
        return None
    fp = None if session else source.fp
    bodies = list(getattr(fp, "Bodies", []) or [])
    if getattr(fp, "Face", ""):
        bodies = [topo.loads(fp.Face)["b"]]
    if session:
        finish()
    else:
        source.reject()
    if what == "Points":
        return points()
    if sketchmode.in_sketch():
        sketchmode.finish()
    if what == "Faces":
        now = [model.pick_ref(x.Object, sub) for x in Gui.Selection.getSelectionEx("", 0) for sub in x.SubElementNames]
        faces = [f for f in [f for f in now if f] + _picked_faces if topo.loads(f)["k"] == "Face"]
        faces = [f for f in faces if not bodies or topo.loads(f)["b"] in bodies]
        return editor.start(modify.MoveFace, **({"Face": faces[0]} if faces else {}))
    new = editor.start(_transform(), Bodies=bodies or design.selected_bodies())
    if new.fp.Bodies:
        new.fp.Pivot = bodies_centre(new.fp)
    return new


def _transform():
    from kovac import modify
    return modify.Transform

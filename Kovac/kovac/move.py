# SPDX-License-Identifier: LGPL-2.1-or-later
"""Move: one tool for bodies, construction planes, sketch points and lines, and faces.

What is selected decides what moves. The on-canvas triad has an arrow along each axis (drag to
slide along it) and a turning handle around each one (drag to rotate about it); distances snap
to the grid step, angles to 5 degrees, and the value being dragged shows next to the cursor.
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
from kovac import commands, model, navigation, overlay, palette

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
        self.t, self.translations, self.rotations = target, translations, rotations
        self.node, self.drag, self.label = None, None, None
        self.in_edit = True                 # takes clicks inside a sketch too (only on its own handles)
        navigation.hooks.insert(0, self)
        self.redraw()

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
        self.t.begin()
        self.redraw()
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
            self._show(it, pos, "%.2f mm" % value)
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
            self._show(it, pos, "%.0f°" % ang)
        self.redraw()

    def release(self, it, pos):
        if self.drag is None:
            return
        self.drag = None
        if self.label is not None:
            self.label.hide()
        self.t.end()
        self.redraw()

    def _show(self, it, pos, text):
        if self.label is None:
            self.label = QtWidgets.QLabel(it.vp, objectName="kovacFloatingField")
            self.label.setStyleSheet("background: rgba(20,22,25,210); color: white; padding: 3px 6px; border-radius: 4px;")
        self.label.setText(text)
        self.label.adjustSize()
        self.label.move(pos.x() + 18, pos.y() + 14)
        self.label.show()

    def refresh(self):          # an editor hook: redraw after the panel changed something
        self.redraw()

    def detach(self):
        overlay.remove(self.node)
        if self.label is not None:
            self.label.deleteLater()
            self.label = None
        if self in navigation.hooks:
            navigation.hooks.remove(self)


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

    def begin(self):
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


def effective(fp):
    """fp.Move (an offset and a turn) applied about the bodies' pivot."""
    pivot = getattr(fp, "Pivot", V())
    return App.Placement(fp.Move.Base, fp.Move.Rotation, pivot)


# ---------------------------------------------------------------- direct sessions

class Session:
    """A triad outside the feature panels: one undo step per drag, Done or Esc ends it."""

    def __init__(self, target, title, **triad):
        self.target = target
        self.triad = Triad(self, **triad)
        from kovac import panel
        from PySide import QtGui
        w = QtWidgets.QWidget(objectName="kovacMoveSession")
        lay = QtWidgets.QVBoxLayout(w)
        tip = QtWidgets.QLabel("Drag an arrow to slide, a curved handle to turn. Alt: no snapping.", objectName="kovacMuted")
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

    def begin(self):
        self.target.doc.openTransaction("Move")
        self.target.begin()

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

    def begin(self):
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
    """Picked points and lines of a sketch being edited: slide in its plane, turn about its normal."""

    def __init__(self, sk, picks):
        self.sk, self.doc = sk, sk.Document
        self.picks = picks          # [(geo index, pos)] pos 0 = whole curve, 1/2/3 = start/end/centre

    def _points(self):
        out = []
        for g, pos in self.picks:
            geo = self.sk.Geometry[g]
            out.append(self.sk.getPoint(g, pos) if pos else (geo.StartPoint if hasattr(geo, "StartPoint") else
                                                              getattr(geo, "Center", V())))
        return out

    def frame(self):
        pl = self.sk.getGlobalPlacement()
        pts = self._points()
        c = sum(pts, V()) * (1.0 / len(pts)) if pts else V()
        return pl.multVec(c), [pl.Rotation.multVec(a) for a in WORLD]

    def begin(self):
        self.geo = [g.copy() for g in self.sk.Geometry]
        pl = self.sk.getGlobalPlacement()
        self.centre = pl.inverse().multVec(self.frame()[0])

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
        self._apply(App.Placement(WORLD[i] * d, App.Rotation()))

    def rotate(self, i, ang):
        self._apply(App.Placement(V(), App.Rotation(V(0, 0, 1), ang), self.centre))


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
    for s in Gui.Selection.getSelectionEx("", 0):
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
    if sketchmode.in_sketch():
        sk = Gui.ActiveDocument.getInEdit().Object
        picks = sketch_picks(sk)
        if not picks:
            commands.report("Select the points or lines to move first.")
            return
        return _start(SketchTarget(sk, picks), "Move sketch elements", translations=(0, 1), rotations=(2,))
    sel = Gui.Selection.getSelectionEx("", 0)
    for s in sel:
        if type(getattr(s.Object, "Proxy", None)).__name__ == "DatumPlane" and not getattr(s.Object, "Auto", False):
            return _start(PlaneTarget(s.Object), "Move " + s.Object.Label)
    faces = [model.pick_ref(s.Object, sub) for s in sel for sub in s.SubElementNames if sub.split(".")[-1].startswith("Face")]
    faces = [f for f in faces if f]
    kinds = set(getattr(navigation.select_filter, "kinds", None) or ())
    if faces and "face" in kinds and "body" not in kinds:       # the Faces filter: push or pull the face
        from kovac import features
        return editor.start(features.FacePull, Face=faces[0])
    ed = editor.start(_transform(), Bodies=design.selected_bodies())
    if ed.fp.Bodies:
        ed.fp.Pivot = bodies_centre(ed.fp)
    return ed


def _transform():
    from kovac import modify
    return modify.Transform

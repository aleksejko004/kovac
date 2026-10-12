# SPDX-License-Identifier: LGPL-2.1-or-later
"""On-canvas manipulators: an arrow you drag, with a floating numeric field next to its tip.

The arrow keeps one size on screen and sits on the face it moves (an Extrude's end face, a
pulled face): out into free space it starts there, into material it comes in from outside
with its tip there. It is drawn over the model and can be grabbed anywhere along it.

Extrude distance and Face Pull distance get an arrow along the pull direction. Dragging back
through zero flips the direction; with an automatic operation that flips Join <-> Cut live.
The floating field is a FreeCAD quantity field bound to the same property: type a value,
a unit or an expression; Tab moves to the panel, Enter confirms the panel, Esc cancels it.
"""
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore

from kovac import model, navigation, overlay, palette, topo

V = App.Vector
HIT_PX = 14          # pixels from the drawn arrow that still grab it
ARROW_PX = 130       # arrow length on screen


def _extrude_axis(fp):
    from kovac import features
    try:
        rs, n = features.profiles(fp, model.input_state(fp))
    except Exception:
        return None
    c = rs[0].point + n * fp.StartOffset.Value
    return c, n


def _pull_axis(fp):
    try:
        _, f = topo.element(model.input_state(fp), fp.Face)
    except Exception:
        return None
    p = topo.sample_points(f)[0]
    return p, f.normalAt(*f.Surface.parameter(p))


def _convex(e, f1, f2, at):
    """Whether the edge between f1 and f2 is an outside (convex) one: step from the edge into
    f1, across the edge -- if that step runs against f2's outward normal, the faces fold away
    from each other around the material, as on a box corner."""
    t = e.tangentAt(e.Curve.parameter(at))
    n1 = f1.normalAt(*f1.Surface.parameter(at))
    n2 = f2.normalAt(*f2.Surface.parameter(at))
    d = n1.cross(t)
    if d.Length < 1e-9:
        return True
    d.normalize()
    eps = max(e.Length * 1e-3, 1e-3)
    if not f1.isInside(at + d * eps, eps * 0.1, True):
        d = -d
    return n2.dot(d) < 0


def _edge_group_axis(fp):
    """First edge of the first (default) group: its midpoint, and along the bisector of its
    two adjacent faces -- into the material on an outside edge (rounding it off removes
    material there), out into the corner on an inside edge (rounding it fills material in).
    Only the default group gets an arrow; a second value group (add_group) is edited in the
    panel instead."""
    import Part
    try:
        state = model.input_state(fp)
        groups = fp.Proxy.edges_for(fp, state, "Edges", True)
    except Exception:
        return None
    for bid, edges in groups.items():
        if not edges:
            continue
        e = edges[0]
        mid = e.valueAt((e.FirstParameter + e.LastParameter) / 2)
        faces = state[bid].shape.ancestorsOfType(e, Part.Face)[:2]
        n = V(0, 0, 0)
        for f in faces:
            try:
                n += f.normalAt(*f.Surface.parameter(mid))
            except Exception:
                pass
        if n.Length < 1e-9:
            return None
        n.normalize()
        try:
            if len(faces) == 2 and _convex(e, faces[0], faces[1], mid):
                n = -n
        except Exception:
            pass
        return mid, n
    return None


ARROWS = {"Extrude": ("Length", _extrude_axis), "FacePull": ("Distance", _pull_axis),
          "Fillet": ("Radius", _edge_group_axis), "Chamfer": ("Distance", _edge_group_axis)}


class Arrow:
    def __init__(self, ed, prop, axis_fn):
        self.ed, self.prop, self.axis_fn = ed, prop, axis_fn
        self.node, self.axis, self.seg = None, None, None
        self.field = None
        self.px = None
        navigation.hooks.insert(0, self)       # the arrow wins over region picks under it
        self.zoom_watch = QtCore.QTimer(interval=150)   # head size is in screen pixels: redraw after a zoom
        self.zoom_watch.timeout.connect(self._zoomed)
        self.zoom_watch.start()

    def _zoomed(self):
        it = navigation.install(Gui.activeView()) if Gui.activeView() is not None else None
        if it is not None and self.px and abs(it.px_size() - self.px) > self.px * 0.05:
            self.refresh()

    def value(self):
        return getattr(self.ed.fp, self.prop).Value

    def refresh(self):
        if getattr(self, "dragging", False) and self.axis is not None:
            return self._draw(self.value(), self.into)    # mid-drag: the axis stays, only the value moved
        overlay.remove(self.node)
        self.node, self.axis, self.seg = None, self.axis_fn(self.ed.fp), None
        if self.axis is None or Gui.activeView() is None:
            return
        from kovac import components
        self.frame = components.feature_frame(self.ed.fp)   # the model's coordinates -> where it is shown
        o, n = self.axis
        self.axis = o, n = self.frame.multVec(o), self.frame.Rotation.multVec(n)
        it = navigation.install(Gui.activeView())
        self.px = it.px_size() if it is not None else 0.05
        self._draw(self.value(), None)

    def _draw(self, value, into):
        """Put the arrow at value; into (whether it points into material) is worked out here
        unless given -- a drag passes the one from its press, so following the mouse stays a
        cheap redraw of the arrow alone, never a solid-inside test per mouse move."""
        overlay.remove(self.node)
        o, n = self.axis
        px = self.px
        at = o + n * value                       # where the moving face is now
        d = n * (1 if value >= 0 else -1)
        length = ARROW_PX * px                   # a fixed screen size: only its place follows the value
        if into is None or (into[0] != (value >= 0)):
            into = (value >= 0, self._into_part(at, d, px))
        self.into = into
        if into[1]:                              # heading into material: come in from outside, tip on the face
            a, b = at - d * length, at
        else:                                    # out into free space: start on the face
            a, b = at, at + d * length
        self.seg = (a, b)
        self.node = overlay.add(overlay.arrow_node(a, b, palette.accent(), px))
        self.place_field(a if into[1] else b)

    def _into_part(self, o, d, px):
        """Whether the arrow heads into material (a fillet on an outside edge, a cut): it then
        sits outside the part with its tip on the face, reading as an arrow coming in."""
        try:
            p = o + d.normalize() * max(px * 3, 1e-3)
            p = getattr(self, "frame", App.Placement()).inverse().multVec(p)
            return any(b.shape.isInside(p, 1e-6, False) for b in model.input_state(self.ed.fp).values())
        except Exception:
            return False

    def place_field(self, tip):
        view = Gui.activeView()
        if not hasattr(view, "graphicsView"):
            return
        vp = view.graphicsView().viewport()
        if self.field is None:
            from kovac.editor import ValueField
            self.field = ValueField(self.ed, self.prop, vp)
            self.field.setObjectName("kovacFloatingField")
            self.field.setFixedWidth(110)
        self.field.show_value()
        r = vp.devicePixelRatioF()
        x, y = view.getPointOnViewport(tip)
        self.field.move(int(x / r) + 14, int(vp.height() - y / r) - 30)
        self.field.show()

    # viewport hook --------------------------------------------------------------
    def _screen_distance(self, it, pos):
        """Pixels from pos to the drawn arrow, shaft and head alike (it is drawn over the
        model, so it is grabbed over the model too)."""
        (ax, ay), (bx, by) = (it.qt(it.view.getPointOnViewport(p)) for p in self.seg)
        px, py = pos.x(), pos.y()
        dx, dy = bx - ax, by - ay
        ll = dx * dx + dy * dy
        t = 0.0 if ll < 1e-9 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / ll))
        cx, cy = ax + dx * t, ay + dy * t
        return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5

    def press(self, it, pos):
        if self.axis is None or self.seg is None:
            return False
        if self._screen_distance(it, pos) > HIT_PX:
            return False
        o, n = self.axis
        ro, rd = overlay.ray(it, pos)
        q = overlay.closest_on_line(ro, rd, o, n)
        self.grab = self.value() - (q - o).dot(n)   # wherever it was grabbed, the value moves with the mouse, no jump
        self.dragging = True
        return True

    def move(self, it, pos):
        o, n = self.axis
        ro, rd = overlay.ray(it, pos)
        q = overlay.closest_on_line(ro, rd, o, n)
        value = round((q - o).dot(n) + getattr(self, "grab", 0.0), 2)
        from kovac import grid
        s = grid.step()
        k = round(value / s) * s if s else 0
        if s and k and abs(k - value) / it.px_size() <= grid.grid_px(it, s):   # near a whole grid step: take it
            value = k
            it.snap_marker.show_at(grid.screen_of(it, o + n * k), "grid")
        else:
            it.snap_marker.hide()
        if abs(value) < 1e-6:
            value = 0.01 if self.value() > 0 else -0.01
        self.ed.set(self.prop, value)
        self._draw(value, getattr(self, "into", None))   # the arrow follows the mouse at once; the solid catches up

    def release(self, it, pos):
        self.dragging = False
        it.snap_marker.hide()

    def detach(self):
        self.zoom_watch.stop()
        overlay.remove(self.node)
        if self.field is not None:
            self.field.hide()
            self.field.deleteLater()
        if self in navigation.hooks:
            navigation.hooks.remove(self)


def attach(ed):
    from kovac.editor import _kind
    if _kind(ed.fp) in ("Move", "MoveFace"):
        from kovac import move
        target = move.BodyTarget(ed) if _kind(ed.fp) == "Move" else move.FaceTarget(ed)
        ed.hooks = getattr(ed, "hooks", []) + [move.Triad(target)]
        return
    spec = ARROWS.get(_kind(ed.fp))
    if spec:
        ed.hooks = getattr(ed, "hooks", []) + [Arrow(ed, *spec)]

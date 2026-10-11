# SPDX-License-Identifier: LGPL-2.1-or-later
"""On-canvas manipulators: an arrow you drag, with a floating numeric field next to its tip.

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
HIT_PX = 14


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


ARROWS = {"Extrude": ("Length", _extrude_axis), "FacePull": ("Distance", _pull_axis)}


class Arrow:
    def __init__(self, ed, prop, axis_fn):
        self.ed, self.prop, self.axis_fn = ed, prop, axis_fn
        self.node, self.axis = None, None
        self.field = None
        navigation.hooks.insert(0, self)       # the arrow wins over region picks under it

    def value(self):
        return getattr(self.ed.fp, self.prop).Value

    def refresh(self):
        overlay.remove(self.node)
        self.node, self.axis = None, self.axis_fn(self.ed.fp)
        if self.axis is None or Gui.activeView() is None:
            return
        o, n = self.axis
        tip = o + n * self.value()
        size = max(abs(self.value()) * 0.06, 0.6)
        self.node = overlay.add(overlay.arrow_node(o, tip, palette.accent(), size))
        self.place_field(tip)

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
    def press(self, it, pos):
        if self.axis is None:
            return False
        o, n = self.axis
        x, y = it.view.getPointOnViewport(o + n * self.value())
        tx, ty = it.qt((x, y))
        if (tx - pos.x()) ** 2 + (ty - pos.y()) ** 2 > HIT_PX ** 2:
            return False
        self.dragging = True
        return True

    def move(self, it, pos):
        o, n = self.axis
        ro, rd = overlay.ray(it, pos)
        q = overlay.closest_on_line(ro, rd, o, n)
        value = round((q - o).dot(n), 2)
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

    def release(self, it, pos):
        self.dragging = False
        it.snap_marker.hide()

    def detach(self):
        overlay.remove(self.node)
        if self.field is not None:
            self.field.hide()
            self.field.deleteLater()
        if self in navigation.hooks:
            navigation.hooks.remove(self)


def attach(ed):
    from kovac.editor import _kind
    spec = ARROWS.get(_kind(ed.fp))
    if spec:
        ed.hooks = getattr(ed, "hooks", []) + [Arrow(ed, *spec)]

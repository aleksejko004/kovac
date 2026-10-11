# SPDX-License-Identifier: LGPL-2.1-or-later
"""Radial context menu (marking menu, see docs/PROVENANCE.md). The ring keeps the same
places everywhere, so a flick works blind: up = repeat last, up-right = line, right = extrude,
down-right = move, down = undo, left = delete; the two diagonals on the left change with what
is under the cursor, and a plain list below holds the rest for that context.
Expert gesture: press the right button, drag toward a slot, release.
"""
import math
import time

import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from kovac import commands, palette

R_OUT, R_IN, PAD = 112, 28, 6
TRAIL_S = 0.45            # seconds a gesture trail takes to fade
# slots clockwise from north; None = this context's own (south-west, north-west); slot 0 = repeat last
RING = [None, "Kovac_Line", "Kovac_Extrude", "Kovac_Move", "Std_Undo", None, "Kovac_Delete", None]
IN_SKETCH = {"Kovac_Move": "Sketcher_Translate"}          # same place, the sketch's own tool
FINISH_FIRST = {"Kovac_Extrude", "Kovac_Revolve"}         # these leave the sketch, then run
CONTEXT = {   # kind: ([south-west, north-west], list below)
    "sketch": (["Kovac_FinishSketch", "Sketcher_Dimension"],
               ["Kovac_Polyline", "Sketcher_CreateRectangle", "Sketcher_CreateCircle", "Sketcher_CreateArc",
                "Sketcher_Trimming", "Sketcher_CreateFillet", "Sketcher_ConstrainCoincident", "Sketcher_ConstrainHorizontal",
                "Sketcher_ConstrainVertical", "Sketcher_ConstrainEqual", "Sketcher_ConstrainTangent",
                "Sketcher_ToggleConstruction", "Std_Redo"]),
    "face": (["Kovac_Sketch", "Kovac_Fillet"],
             ["Kovac_FacePull", "Kovac_Hole", "Kovac_Shell", "Kovac_Chamfer", "Kovac_Draft", "Kovac_DeleteFace", "Kovac_Plane",
              "Kovac_Measure", "Kovac_LookAt", "Kovac_SelectTangent", "Std_HideSelection", "Kovac_Isolate", "Kovac_Material"]),
    "edge": (["Kovac_Chamfer", "Kovac_Fillet"],
             ["Kovac_SelectTangent", "Kovac_Measure", "Kovac_Axis", "Kovac_Sweep", "Kovac_Plane", "Std_ViewFitSelection",
              "Std_HideSelection", "Kovac_SaveSelectionSet"]),
    "vertex": (["Kovac_Point", "Kovac_Measure"], ["Kovac_Plane", "Kovac_Hole", "Std_ViewFitSelection"]),
    "body": (["Kovac_Mirror", "Kovac_PatternRect"],
             ["Kovac_Material", "Kovac_Isolate", "Std_HideSelection", "Kovac_MassProperties", "Kovac_Combine", "Kovac_Split",
              "Kovac_Scale", "Kovac_PatternCirc", "Kovac_Shell", "Kovac_Fillet", "Kovac_ShowAll"]),
    "none": (["Kovac_Sketch", "Kovac_Box"],
             ["Kovac_Home", "Kovac_FitAll", "Kovac_Search", "Kovac_Parameters", "Kovac_ShowAll", "Kovac_SetHome",
              "Kovac_DefineFront", "Kovac_SaveView", "Std_Redo"]),
}
_menu = None
stats = {"last_open_ms": None}


def context_of(info):
    if not info:
        return "none"
    element = (info.get("SubName") or info.get("Component") or "").split(".")[-1]
    for kind in ("Face", "Edge", "Vertex"):
        if element.startswith(kind):
            return kind.lower()
    return "body"


def _info(cid):
    cmd = Gui.Command.get(cid)
    if cmd is None:
        return None
    i = cmd.getInfo()
    from kovac import sketchmode
    ours = sketchmode.tool_icon(cid)                      # sketch tools: our icons, as on the ribbon
    return i["menuText"].replace("&", ""), ours or i.get("pixmap", "")


def _icon(pixmap):
    if not pixmap:
        return QtGui.QIcon()
    return QtGui.QIcon(pixmap) if pixmap.endswith(".svg") else Gui.getIcon(pixmap) or QtGui.QIcon()


class Radial(QtWidgets.QWidget):
    def __init__(self):
        super().__init__(None, QtCore.Qt.Popup | QtCore.Qt.FramelessWindowHint | QtCore.Qt.NoDropShadowWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setObjectName("kovacRadial")
        self.list = QtWidgets.QListWidget(self)
        self.list.setObjectName("kovacRadialList")
        self.list.itemClicked.connect(lambda it: self.trigger(it.data(QtCore.Qt.UserRole)))
        self.slots, self.hover = [None] * 8, None
        self.trail = []                          # (point, time) of a press-drag gesture, fading out
        self.fade = QtCore.QTimer(self, interval=30)
        self.fade.timeout.connect(self._fade)

    @property
    def center(self):
        return QtCore.QPoint(R_OUT + PAD, R_OUT + PAD)

    def popup(self, at, slots, extras, gesture_to=None):
        self.slots, self.hover = slots, None
        self.trail = [(QtCore.QPointF(self.center), time.perf_counter())]
        self.list.clear()
        for cid in extras:
            i = _info(cid)
            if i:
                it = QtWidgets.QListWidgetItem(_icon(i[1]), i[0])
                it.setData(QtCore.Qt.UserRole, cid)
                self.list.addItem(it)
        ring = 2 * (R_OUT + PAD)
        rows = self.list.count()
        tall = rows * (self.list.sizeHintForRow(0) if rows else 0) + 6
        self.list.setVisible(rows > 0)
        self.list.setGeometry((ring - 220) // 2, ring + 4, 220, tall)
        self.resize(ring, ring + (tall + 8 if rows else 0))
        self.move(at - self.center)
        self.show()
        self.raise_()
        if gesture_to is not None:              # opened mid-drag: start where the mouse already is
            local = self.mapFromGlobal(gesture_to)
            self.trail.append((QtCore.QPointF(local), time.perf_counter()))
            self.hover = self.slot_at(local)
            self.update()

    def slot_at(self, pos):
        d = pos - self.center
        r = math.hypot(d.x(), d.y())
        if r < R_IN or r > R_OUT + 60:
            return None
        a = math.atan2(d.x(), -d.y()) % (2 * math.pi)
        return int((a + math.pi / 8) / (math.pi / 4)) % 8

    def trigger(self, cid):
        self.close()
        if cid:
            QtCore.QTimer.singleShot(0, lambda: _run(cid))

    # Qt events ------------------------------------------------------------------
    def mouseMoveEvent(self, ev):
        s = self.slot_at(ev.position().toPoint())
        if ev.buttons():                         # a gesture: leave a fading trail behind the cursor
            self.trail.append((ev.position(), time.perf_counter()))
            if not self.fade.isActive():
                self.fade.start()
        if s != self.hover or ev.buttons():
            self.hover = s
            self.update()

    def _fade(self):
        now = time.perf_counter()
        self.trail = [(q, t) for q, t in self.trail if now - t < TRAIL_S]
        if len(self.trail) < 2:
            self.fade.stop()
        self.update()

    def mouseReleaseEvent(self, ev):
        s = self.slot_at(ev.position().toPoint())
        if s is not None and self.slots[s]:
            self.trigger(self.slots[s])

    def keyPressEvent(self, ev):
        if ev.key() == QtCore.Qt.Key_Escape:
            self.close()

    def paintEvent(self, _):
        """See-through: no filled wheel, only a thin guide ring, the hovered slice tinted, and each
        command as an icon with its name on a small chip, so the model stays visible behind it."""
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        import kovac
        t = palette.theme(kovac.theme_name())
        c = QtCore.QPointF(self.center)
        guide = QtGui.QColor(t["text_muted"])
        guide.setAlphaF(0.45)
        p.setPen(QtGui.QPen(guide, 1.2))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawEllipse(c, R_OUT, R_OUT)
        p.drawEllipse(c, R_IN - 4, R_IN - 4)
        if self.hover is not None and self.slots[self.hover]:
            start = 112.5 - 45 * self.hover          # Qt angles run counter-clockwise from 3 o'clock
            path = QtGui.QPainterPath()
            box = QtCore.QRectF(c.x() - R_OUT, c.y() - R_OUT, 2 * R_OUT, 2 * R_OUT)
            path.arcMoveTo(box, start)
            path.arcTo(box, start, -45)
            path.arcTo(QtCore.QRectF(c.x() - R_IN, c.y() - R_IN, 2 * R_IN, 2 * R_IN), start - 45, 45)
            path.closeSubpath()
            tint = QtGui.QColor(t["accent"])
            tint.setAlphaF(0.30)
            p.setPen(QtGui.QPen(QtGui.QColor(t["accent"]), 1.5))
            p.setBrush(tint)
            p.drawPath(path)
        f = p.font()
        f.setPointSizeF(8)
        f.setBold(True)
        p.setFont(f)
        metrics = QtGui.QFontMetrics(f)
        for i in range(8):
            if not self.slots[i]:
                continue
            info = _info(self.slots[i])
            if not info:
                continue
            mid = math.radians(90 - 45 * i)
            rr = (R_OUT + R_IN) / 2 + 6
            x, y = c.x() + rr * math.cos(mid), c.y() - rr * math.sin(mid)
            label = ("↻ " if i == 0 else "") + info[0]   # north slot = repeat last
            w = min(metrics.horizontalAdvance(label) + 14, 112)
            chip = QtCore.QRectF(x - w / 2, y - 22, w, 44)
            back = QtGui.QColor(t["accent"] if i == self.hover else t["surface"])
            back.setAlphaF(0.92)
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(back)
            p.drawRoundedRect(chip, 8, 8)
            _icon(info[1]).paint(p, QtCore.QRect(int(x - 10), int(y - 20), 20, 20))
            p.setPen(QtGui.QColor("#FFFFFF" if i == self.hover else t["text"]))
            p.drawText(QtCore.QRectF(x - w / 2 + 4, y + 1, w - 8, 18), QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter,
                       metrics.elidedText(label, QtCore.Qt.ElideRight, int(w - 8)))
        if len(self.trail) > 1:                      # the gesture's trail, newest part brightest
            now = time.perf_counter()
            for (a, ta), (b, _tb) in zip(self.trail, self.trail[1:]):
                k = max(0.0, 1 - (now - ta) / TRAIL_S)
                col = QtGui.QColor(t["accent"])
                col.setAlphaF(0.85 * k)
                p.setPen(QtGui.QPen(col, 2 + 4 * k, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
                p.drawLine(a, b)


def _run(cid):
    from kovac import sketchmode
    if cid in FINISH_FIRST and sketchmode.in_sketch():
        commands.run("Kovac_FinishSketch")
    commands.run(cid)


def slots_for(kind):
    pair, extras = CONTEXT[kind]
    ring = list(RING)
    ring[0] = commands.last
    ring[5], ring[7] = pair
    if kind == "sketch":
        ring = [IN_SKETCH.get(c, c) for c in ring]
    ring = [c if c and Gui.Command.get(c) else None for c in ring]
    return ring, [c for c in extras if Gui.Command.get(c)]


def open_at(global_pos, info=None, sketch=False, gesture_to=None):
    """Open for whatever is under the cursor; a pick on unselected geometry selects it first."""
    global _menu
    t0 = time.perf_counter()
    if info:
        from kovac.navigation import Interactor
        obj, sub = Interactor.target(info)
        if not Gui.Selection.isSelected(obj, sub):
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(obj, sub)
    _menu = _menu or Radial()
    _menu.popup(global_pos, *slots_for("sketch" if sketch else context_of(info)), gesture_to=gesture_to)
    QtWidgets.QApplication.processEvents()
    stats["last_open_ms"] = (time.perf_counter() - t0) * 1000
    return _menu

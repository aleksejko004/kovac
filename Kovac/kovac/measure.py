# SPDX-License-Identifier: LGPL-2.1-or-later
"""Measure: hover gives an instant readout; picking two entities gives distance, minimum
distance and angle. Results can be copied. Pure readout functions are tested headless."""
import math

import FreeCAD as App

stats = {"last_hover_ms": None}


def _mm(x):
    return "%.3f mm" % x


def describe(s):
    import Part
    t = s.ShapeType
    if t == "Vertex":
        p = s.Point
        return "Point  %.3f, %.3f, %.3f" % (p.x, p.y, p.z)
    if t == "Edge":
        c = s.Curve
        if isinstance(c, Part.Circle):
            full = abs(s.Length - 2 * math.pi * c.Radius) < 1e-7
            return "%s  Ø %s  (R %s)%s" % ("Circle" if full else "Arc", _mm(2 * c.Radius), _mm(c.Radius),
                                          "" if full else "  length " + _mm(s.Length))
        return "%s  length %s" % ("Line" if isinstance(c, (Part.Line, Part.LineSegment)) else "Curve", _mm(s.Length))
    if t == "Face":
        f = s.Surface
        if isinstance(f, Part.Cylinder):
            return "Cylinder  Ø %s  area %.3f mm²" % (_mm(2 * f.Radius), s.Area)
        return "%s  area %.3f mm²" % ("Plane" if isinstance(f, Part.Plane) else "Face", s.Area)
    return "Body  volume %.3f mm³  area %.3f mm²" % (s.Volume, s.Area)


def _direction(s):
    import Part
    if s.ShapeType == "Edge" and isinstance(s.Curve, (Part.Line, Part.LineSegment)):
        return s.Curve.Direction, "line"
    if s.ShapeType == "Face" and isinstance(s.Surface, Part.Plane):
        return s.Surface.Axis, "plane"
    return None, None


def between(a, b):
    """Readout lines for two picked shapes."""
    import Part
    out = ["Minimum distance  " + _mm(a.distToShape(b)[0])]
    if a.ShapeType == b.ShapeType == "Vertex":
        d = b.Point - a.Point
        out.append("ΔX %s  ΔY %s  ΔZ %s" % (_mm(d.x), _mm(d.y), _mm(d.z)))
    circles = [s.Curve for s in (a, b) if s.ShapeType == "Edge" and isinstance(s.Curve, Part.Circle)]
    if len(circles) == 2:
        out.append("Centre distance  " + _mm((circles[0].Center - circles[1].Center).Length))
    (da, ka), (db, kb) = _direction(a), _direction(b)
    if da is not None and db is not None:
        ang = math.degrees(da.getAngle(db))
        ang = min(ang, 180 - ang)          # undirected: 0..90
        if ka != kb:                       # line vs plane: angle to the plane, not its normal
            ang = 90 - ang
        out.append("Angle  %.3f°" % ang)
    return out


def element(obj, sub):
    """Global-space shape of a picked element."""
    import Part
    return Part.getShape(obj, sub, needSubElement=True, retType=0)


# ---------------------------------------------------------------- panel

def panel():
    import time

    import FreeCADGui as Gui
    from PySide import QtWidgets

    from kovac import panel as panels

    class Body(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.setObjectName("kovacMeasure")
            lay = QtWidgets.QVBoxLayout(self)
            self.hover = QtWidgets.QLabel("Hover over geometry…", objectName="kovacMuted")
            self.result = QtWidgets.QPlainTextEdit(readOnly=True)
            row = QtWidgets.QHBoxLayout()
            copy = QtWidgets.QPushButton("Copy")
            copy.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(self.result.toPlainText()))
            clear = QtWidgets.QPushButton("Clear picks")
            clear.clicked.connect(Gui.Selection.clearSelection)
            row.addWidget(copy)
            row.addWidget(clear)
            for w in (self.hover, self.result):
                lay.addWidget(w)
            lay.addLayout(row)
            Gui.Selection.addObserver(self)
            self.refresh()

        def setPreselection(self, doc, obj, sub):
            t0 = time.perf_counter()
            try:
                o = App.getDocument(doc).getObject(obj)
                self.hover.setText(describe(element(o, sub)))
            except Exception:
                self.hover.setText("")
            stats["last_hover_ms"] = (time.perf_counter() - t0) * 1000

        def removePreselection(self, *_):
            self.hover.setText("Hover over geometry…")

        def refresh(self, *_):
            picks = [(s.Object, n) for s in Gui.Selection.getSelectionEx("", 0) for n in (s.SubElementNames or [""])]
            shapes = []
            for o, n in picks[-2:]:
                try:
                    shapes.append(element(o, n))
                except Exception:
                    pass
            lines = ["%d: %s" % (i + 1, describe(s)) for i, s in enumerate(shapes)]
            if len(shapes) == 2:
                lines += [""] + between(*shapes)
            self.result.setPlainText("\n".join(lines) or "Pick one or two entities.")

        addSelection = removeSelection = setSelection = clearSelection = refresh

    return panels.show("Measure", "Measure", Body)

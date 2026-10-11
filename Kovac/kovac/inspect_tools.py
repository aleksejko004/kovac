# SPDX-License-Identifier: LGPL-2.1-or-later
"""Check tools: physical properties, interference, section analysis, draft analysis, and
materials/appearance. All panels are floating and non-modal."""
import math

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtGui, QtWidgets

import kovac
from kovac import commands, materials, model, overlay, palette, panel

V = App.Vector


def _bodies():
    """Selected bodies, else every visible body."""
    sel = []
    for s in Gui.Selection.getSelectionEx("", 0):
        if type(getattr(s.Object, "Proxy", None)).__name__ == "BodyProxy" and s.Object not in sel:
            sel.append(s.Object)
    return sel or [b for b in model.bodies(App.ActiveDocument) if not b.Shape.isNull() and b.Visibility]


def _text_panel(pid, title, lines, extra=None):
    def body():
        w = QtWidgets.QWidget(objectName="kovacMeasure")
        lay = QtWidgets.QVBoxLayout(w)
        w.text = QtWidgets.QPlainTextEdit(readOnly=True)
        copy = QtWidgets.QPushButton("Copy")
        copy.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(w.text.toPlainText()))
        lay.addWidget(w.text)
        lay.addWidget(copy)
        return w
    d = panel.show(pid, title, body)
    d.widget().text.setPlainText("\n".join(lines))
    return d


# ---------------------------------------------------------------- physical properties

def mass_properties():
    lines = []
    total = 0.0
    for b in _bodies():
        mp = materials.mass_properties(b.Shape, b.Material)
        c = mp["center"]
        name = materials.LIBRARY[b.Material][0] if b.Material in materials.LIBRARY else "no material"
        lines.append("%s  (%s)" % (b.Label, name))
        lines.append("  volume %.3f cm³   area %.3f cm²" % (mp["volume"] / 1000, mp["area"] / 100))
        if mp["mass"] is not None:
            lines.append("  mass %.4f kg" % mp["mass"])
            total += mp["mass"]
        if c is not None:
            lines.append("  centre of mass %.3f, %.3f, %.3f mm" % (c.x, c.y, c.z))
        lines.append("")
    if total:
        lines.append("Total mass %.4f kg" % total)
    return _text_panel("Mass", "Physical properties", lines or ["No bodies."])


# ---------------------------------------------------------------- interference

_interference = {"node": None}


def interference():
    bodies = [b for b in model.bodies(App.ActiveDocument) if not b.Shape.isNull()]
    lines, faces = [], []
    for i, a in enumerate(bodies):
        for b in bodies[i + 1:]:
            if not a.Shape.BoundBox.intersect(b.Shape.BoundBox):
                continue
            common = a.Shape.common(b.Shape)
            if common.Volume > 1e-9:
                lines.append("%s ∩ %s: %.3f mm³" % (a.Label, b.Label, common.Volume))
                faces += common.Faces
    overlay.remove(_interference["node"])
    _interference["node"] = None
    if faces:
        from pivy import coin
        sep = coin.SoSeparator()
        for f in faces:
            sep.addChild(overlay.face_node(f, palette.SEMANTIC["error"], 0.25))
        _interference["node"] = overlay.add(sep)
    d = _text_panel("Interference", "Interference", lines or ["No interference between bodies."])
    d.visibilityChanged.connect(lambda vis: vis or (overlay.remove(_interference["node"]), _interference.update(node=None)))
    return d


# ---------------------------------------------------------------- section analysis

class SectionProxy:
    """Saved section: the visible bodies cut by a plane, caps included. Showing it hides the
    bodies; hiding it shows them again."""

    def __init__(self, fp):
        fp.Proxy = self
        fp.addProperty("App::PropertyString", "Plane", "Section", "XY/XZ/YZ, a plane, or a flat face").Plane = "XZ"
        fp.addProperty("App::PropertyDistance", "Offset", "Section", "")
        fp.addProperty("App::PropertyBool", "Flip", "Section", "keep the other side")
        fp.addProperty("App::PropertyLinkList", "Bodies", "Section", "", 4)

    def execute(self, fp):
        from kovac import modify
        o, n = modify.plane_of(fp, "Plane", model.state_of(model.tip(fp.Document)))
        n = -n if fp.Flip else n
        o = o + n * fp.Offset.Value
        parts = []
        for b in fp.Bodies:
            if b.Shape.isNull():
                continue
            size = b.Shape.BoundBox.DiagonalLength * 4 + (o - b.Shape.BoundBox.Center).Length
            half = modify._halfspace(o, n, size)
            cut = b.Shape.cut(half)
            if cut.Solids:
                parts.append(cut)
        fp.Shape = Part.makeCompound(parts) if parts else Part.Shape()

    def onChanged(self, fp, prop):
        if prop == "Visibility" and hasattr(fp, "Bodies"):
            for b in fp.Bodies:
                b.Visibility = not fp.Visibility

    def dumps(self):
        return None

    def loads(self, _s):
        return None


def section():
    doc = App.ActiveDocument
    with commands.transaction("Section analysis", doc):
        s = doc.addObject("Part::FeaturePython", "Section")
        SectionProxy(s)
        s.Bodies = [b for b in model.bodies(doc) if not b.Shape.isNull()]
        if s.ViewObject is not None:
            s.ViewObject.ShapeAppearance = [App.Material(DiffuseColor=overlay.rgb(palette.THEMES["light"]["model"]))]
        s.Label = "Section"
        doc.recompute()
        s.Visibility = True

    def body():
        w = QtWidgets.QWidget()
        lay = QtWidgets.QFormLayout(w)
        plane = QtWidgets.QComboBox()
        plane.addItems(["XY", "XZ", "YZ"])
        plane.setCurrentText(s.Plane)
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        bb = App.BoundBox()
        for b in s.Bodies:
            bb.add(b.Shape.BoundBox)
        half = int(max(bb.DiagonalLength, 10))
        slider.setRange(-half, half)
        flip = QtWidgets.QCheckBox()

        def update():
            s.Plane, s.Offset, s.Flip = plane.currentText(), slider.value(), flip.isChecked()
            doc.recompute()
        plane.currentTextChanged.connect(lambda _t: update())
        slider.valueChanged.connect(lambda _v: update())
        flip.toggled.connect(lambda _b: update())
        lay.addRow("Plane", plane)
        lay.addRow("Offset (drag)", slider)
        lay.addRow("Flip", flip)
        lay.addRow(QtWidgets.QLabel("Toggle it any time with its checkbox in Analyses.", objectName="kovacMuted"))
        return w
    panel.show("Section", "Section analysis", body)
    return s


# ---------------------------------------------------------------- draft analysis

_draft = {"node": None}


def draft_angle(face, pull):
    """Draft of a face against a pull direction, degrees (positive = releases from the mould)."""
    p = face.CenterOfMass
    try:
        u, v = face.Surface.parameter(p)
        n = face.normalAt(u, v)
    except Exception:
        return None
    return 90.0 - math.degrees(n.getAngle(pull))


def draft_analysis(pull=V(0, 0, 1), minimum=1.0):
    from pivy import coin
    overlay.remove(_draft["node"])
    sep = coin.SoSeparator()
    counts = {"ok": 0, "low": 0, "under": 0}
    for b in [b for b in model.bodies(App.ActiveDocument) if not b.Shape.isNull() and b.Visibility]:
        for f in b.Shape.Faces:
            a = draft_angle(f, pull)
            if a is None:
                continue
            if abs(abs(a) - 90) < 1e-6 or a >= minimum:
                kind = "ok"            # parting faces (top/bottom) or enough draft
            elif a > -minimum:
                kind = "low"           # walls without enough draft
            else:
                kind = "under"         # leaning the wrong way: undercut
            counts[kind] += 1
            col = {"ok": palette.SEMANTIC["success"], "low": palette.SEMANTIC["warning"], "under": palette.SEMANTIC["error"]}[kind]
            sep.addChild(overlay.face_node(f, col, 0.15))
    _draft["node"] = overlay.add(sep)
    lines = ["Pull direction +Z, minimum draft %.1f°" % minimum,
             "green: enough draft (%d)" % counts["ok"], "amber: too little draft (%d)" % counts["low"],
             "red: undercut / negative draft (%d)" % counts["under"]]
    d = _text_panel("DraftAnalysis", "Draft analysis", lines)
    d.visibilityChanged.connect(lambda vis: vis or (overlay.remove(_draft["node"]), _draft.update(node=None)))
    return d


# ---------------------------------------------------------------- materials & appearance

def apply_material(body, key):
    body.Material = key
    if body.ViewObject is not None:
        body.ViewObject.ShapeAppearance = [App.Material(DiffuseColor=overlay.rgb(materials.LIBRARY[key][3]))]


class _MaterialList(QtWidgets.QListWidget):
    """Drag a material out onto a body in the viewport, or the browser, to assign it there --
    an alternative to select-bodies-then-double-click, not a replacement for it."""

    def startDrag(self, _actions):
        it = self.currentItem()
        if it is None:
            return
        mime = QtCore.QMimeData()
        mime.setData(kovac.MATERIAL_MIME, it.data(QtCore.Qt.UserRole).encode("utf-8"))
        drag = QtGui.QDrag(self)
        drag.setMimeData(mime)
        pm = it.icon().pixmap(18, 18)
        if not pm.isNull():
            drag.setPixmap(pm)
        drag.exec(QtCore.Qt.CopyAction)


def material_panel():
    def body():
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lst = _MaterialList()
        lst.setDragEnabled(True)
        for key, (name, rho, e, col) in materials.LIBRARY.items():
            pm = QtGui.QPixmap(14, 14)
            pm.fill(QtGui.QColor(col))
            it = QtWidgets.QListWidgetItem(QtGui.QIcon(pm), "%s   ·   %g kg/m³" % (name, rho))
            it.setData(QtCore.Qt.UserRole, key)
            lst.addItem(it)

        def assign(it):
            bodies = _bodies()
            if not bodies:
                commands.report("Select bodies first.")
                return
            with commands.transaction("Material", App.ActiveDocument):
                for b in bodies:
                    apply_material(b, it.data(QtCore.Qt.UserRole))
        lst.itemActivated.connect(assign)
        lst.itemDoubleClicked.connect(assign)
        color = QtWidgets.QPushButton("Appearance colour…")

        def pick_color():
            c = QtWidgets.QColorDialog.getColor(parent=w)
            if c.isValid():
                for b in _bodies():
                    if b.ViewObject is not None:
                        b.ViewObject.ShapeAppearance = [App.Material(DiffuseColor=(c.redF(), c.greenF(), c.blueF()))]
        color.clicked.connect(pick_color)
        lay.addWidget(QtWidgets.QLabel("Select bodies then double-click a material, or drag one onto a body.",
                                       objectName="kovacMuted"))
        lay.addWidget(lst)
        lay.addWidget(color)
        return w
    return panel.show("Material", "Material & appearance", body)


def register():
    add = commands.add
    add("Kovac_MassProperties", "Physical properties", "Volume, area, mass and centre of mass", mass_properties,
        icon=kovac.icon("mass"), active=commands.has_doc)
    add("Kovac_Interference", "Interference", "Find where bodies overlap", interference, icon=kovac.icon("interference"),
        active=commands.has_doc)
    add("Kovac_Section", "Section analysis", "Cut the model open with a plane (saved, toggleable)", section,
        icon=kovac.icon("section"), active=commands.has_doc)
    add("Kovac_DraftAnalysis", "Draft analysis", "Colour faces by draft angle", draft_analysis, icon=kovac.icon("draftanalysis"),
        active=commands.has_doc)
    add("Kovac_Material", "Material", "Physical material and appearance of bodies", material_panel, icon=kovac.icon("material"),
        active=commands.has_doc)

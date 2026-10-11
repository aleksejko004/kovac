# SPDX-License-Identifier: LGPL-2.1-or-later
"""Command panels for history features: one schema-driven, floating, non-modal panel.

- A panel holds one transaction: OK/Enter commits it (one undo step), Cancel/Esc rolls it
  back (a new feature disappears, an edited one gets its old values back).
- Every change recomputes for real: the preview is the result.
- Viewport picks go into the active pick input; the view stays free to orbit, the tree to use.
- Numeric fields are FreeCAD quantity fields bound to the property, so units ("2 in"),
  expressions and parameter names (with autocomplete, type "=") work everywhere.
"""
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

import kovac
from kovac import commands, model, palette, topo

_current = None


def current():
    return _current


# ---------------------------------------------------------------- schemas
# (kind, property, label, extra)
#   value / enum / bool / text / int / float
#   picks  — StringList of references, extra = element kinds ("Face", "Edge", "Vertex")
#   pick   — one reference (String), extra = element kinds
#   sketch — Link to a sketch;  sketches — LinkList of sketches
#   bodies — StringList of body ids;  body — one body id
#   plane  — String: XY/XZ/YZ, a plane datum name or a flat-face reference
#   features — LinkList of history features (picked through any face they made)
#   positions — VectorList filled by clicking points on geometry
#   vector — App.Vector;  move — Placement (offset + rotation about an axis)
#   op — Operation with the inferred result shown;  regions — sketch regions picked in the view
SCHEMAS = {
    "Extrude": [("sketch", "Profile", "Profile"), ("regions", "Regions", "Regions"),
                ("picks", "ProfileFaces", "or flat faces", ("Face",)), ("enum", "Extent", "Extent"),
                ("enum", "Sides", "Direction"), ("value", "Length", "Distance"), ("value", "Length2", "Second side"),
                ("pick", "ToFace", "Up to face", ("Face",)), ("value", "Taper", "Taper angle"),
                ("value", "StartOffset", "Start offset"), ("value", "Thin", "Thin wall"), ("op",)],
    "Revolve": [("sketch", "Profile", "Profile"), ("regions", "Regions", "Regions"),
                ("picks", "ProfileFaces", "or flat faces", ("Face",)), ("axis", "Axis", "Axis"),
                ("value", "Angle", "Angle"), ("bool", "Symmetric", "Symmetric"), ("op",)],
    "Sweep": [("sketch", "Profile", "Profile"), ("regions", "Regions", "Regions"), ("sketch", "Path", "Path sketch"),
              ("picks", "PathEdges", "or path edges", ("Edge",)), ("bool", "Frenet", "Follow the path's twist"), ("op",)],
    "Loft": [("sketches", "Sections", "Sections"), ("bool", "Ruled", "Straight walls"), ("bool", "Closed", "Closed loop"), ("op",)],
    "Primitive": [("enum", "PrimitiveType", "Shape"), ("place", "Location", "Place on"), ("value", "Length", "Length"),
                  ("value", "Width", "Width"), ("value", "Height", "Height"), ("value", "Radius", "Radius"),
                  ("value", "Radius2", "Second radius"), ("op",)],
    "Hole": [("pick", "Face", "Start face", ("Face",)), ("positions", "Positions", "Centres (click on the face)"),
             ("sketch", "Points", "or sketch points"), ("enum", "HoleType", "Type"), ("enum", "Size", "Size"),
             ("enum", "Fit", "Clearance"), ("value", "Diameter", "Custom diameter"), ("bool", "ThroughAll", "Through all"),
             ("value", "Depth", "Depth"), ("value", "TipAngle", "Drill point"), ("value", "CounterboreDiameter", "Counterbore Ø"),
             ("value", "CounterboreDepth", "Counterbore depth"), ("value", "CountersinkDiameter", "Countersink Ø"),
             ("value", "ThreadLength", "Thread length"), ("op",)],
    "Fillet": [("picks", "Edges", "Edges", ("Edge",)), ("picks", "Faces", "All edges of faces", ("Face",)),
               ("bodies", "WholeBodies", "Whole bodies"), ("value", "Radius", "Radius"),
               ("bool", "TangentChain", "Tangent chain"), ("groups",)],
    "Chamfer": [("picks", "Edges", "Edges", ("Edge",)), ("picks", "Faces", "All edges of faces", ("Face",)),
                ("enum", "Mode", "Type"), ("value", "Distance", "Distance"), ("value", "Distance2", "Second distance"),
                ("value", "Angle", "Angle"), ("bool", "Flip", "Flip sides"), ("bool", "TangentChain", "Tangent chain"), ("groups",)],
    "Shell": [("picks", "Faces", "Faces to open", ("Face",)), ("bodies", "Bodies", "or bodies to hollow"),
              ("value", "Thickness", "Thickness"), ("bool", "Outside", "Wall outside")],
    "Draft": [("picks", "Faces", "Faces", ("Face",)), ("pick", "Neutral", "Neutral face", ("Face",)),
              ("value", "Angle", "Angle"), ("bool", "Reverse", "Reverse pull")],
    "FacePull": [("pick", "Face", "Face", ("Face",)), ("value", "Distance", "Distance")],
    "DeleteFace": [("picks", "Faces", "Faces", ("Face",))],
    "Combine": [("body", "Target", "Target body"), ("bodies", "Tools", "Tool bodies"), ("enum", "Operation", "Operation"),
                ("bool", "KeepTools", "Keep tools")],
    "SplitBody": [("body", "Body", "Body"), ("plane", "Plane", "Split with")],
    "Move": [("bodies", "Bodies", "Bodies"), ("move", "Move", "Move by"), ("bool", "Copy", "Copy")],
    "Scale": [("bodies", "Bodies", "Bodies"), ("float", "Factor", "Factor"), ("vector", "Center", "About point")],
    "Mirror": [("bodies", "Bodies", "Bodies"), ("plane", "Plane", "Mirror plane"), ("bool", "Join", "Join with the original")],
    "Pattern": [("features", "Sources", "Features"), ("bodies", "Bodies", "or bodies"), ("enum", "Type", "Type"),
                ("vector", "Direction1", "Direction 1"), ("int", "Count1", "Count 1"), ("value", "Spacing1", "Spacing 1"),
                ("vector", "Direction2", "Direction 2"), ("int", "Count2", "Count 2"), ("value", "Spacing2", "Spacing 2"),
                ("axis", "Axis", "Axis"), ("int", "Count", "Count"), ("value", "TotalAngle", "Total angle"),
                ("skip", "Skip", "Skipped (click instances)")],
    "RemoveBody": [("bodies", "Bodies", "Bodies")],
    "Thread": [("picks", "Faces", "Cylindrical faces", ("Face",)), ("text", "Size", "Size"), ("value", "Length", "Length")],
    "Plane": [("enum", "Mode", "Type"), ("plane", "Base", "From"), ("value", "Offset", "Offset"), ("value", "Angle", "Angle"),
              ("picks", "Refs", "Edges / faces / points", ("Face", "Edge", "Vertex")), ("value", "Position", "Along path")],
    "Axis": [("enum", "Mode", "Type"), ("picks", "Refs", "Picks", ("Face", "Edge", "Vertex"))],
    "Point": [("enum", "Mode", "Type"), ("picks", "Refs", "Pick", ("Face", "Edge", "Vertex")), ("vector", "Coordinates", "Coordinates")],
}


# option values shown as icon buttons instead of a drop-down (all values of a property must be here)
CHOICE_ICONS = {
    "Distance": "ext_distance", "To face": "ext_toface", "Through all": "ext_through",
    "One side": "side_one", "Two sides": "side_two", "Symmetric": "side_symmetric",
    "Auto": "op_auto", "Join": "op_join", "Cut": "op_cut", "Intersect": "op_intersect", "New body": "op_newbody",
    "Simple": "hole_simple", "Counterbore": "hole_counterbore", "Countersink": "hole_countersink", "Tapped": "hole_tapped",
    "Box": "box", "Cylinder": "cylinder", "Sphere": "sphere", "Cone": "cone", "Torus": "torus",
}


class IconChoice(QtWidgets.QWidget):
    """A row of icon buttons for one option (the drop-down's API: currentText / setCurrentText)."""
    currentTextChanged = QtCore.Signal(str)

    def __init__(self, values, current):
        super().__init__()
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.group = QtWidgets.QButtonGroup(self)
        self.buttons = {}
        for v in values:
            b = QtWidgets.QToolButton(objectName="kovacChoice", checkable=True, toolTip=v, text=v,
                                      toolButtonStyle=QtCore.Qt.ToolButtonTextUnderIcon)
            b.setIcon(QtGui.QIcon(kovac.icon(CHOICE_ICONS[v])))
            b.setIconSize(QtCore.QSize(28, 28))
            self.group.addButton(b)
            self.buttons[v] = b
            lay.addWidget(b)
        lay.addStretch()
        self.setCurrentText(current)
        self.group.buttonClicked.connect(lambda b: self.currentTextChanged.emit(b.toolTip()))

    def currentText(self):
        b = self.group.checkedButton()
        return b.toolTip() if b else ""

    def setCurrentText(self, v):
        if v in self.buttons and v != self.currentText():
            self.buttons[v].setChecked(True)
            self.currentTextChanged.emit(v)


def _choice(fp, prop):
    values = fp.getEnumerationsOfProperty(prop)
    if all(v in CHOICE_ICONS for v in values):
        return IconChoice(values, getattr(fp, prop))
    w = QtWidgets.QComboBox()
    w.addItems(values)
    w.setCurrentText(getattr(fp, prop))
    return w


def _kind(fp):
    return fp.Kind if getattr(fp, "Kind", "") in SCHEMAS else type(fp.Proxy).kind


class DoubleSpinBox(QtWidgets.QDoubleSpinBox):
    """A QDoubleSpinBox that takes '.' or ',' as the decimal point while typing, regardless of
    which one the locale actually uses -- plain Qt only accepts that one and silently drops
    the other as a stray character (typing "3.5" under a comma locale becomes 35)."""

    def _other(self):
        return "," if self.locale().decimalPoint() == "." else "."

    def validate(self, text, pos):
        state, _, p = super().validate(text.replace(self._other(), self.locale().decimalPoint()), pos)
        return state, text, p            # keep what was actually typed on screen

    def valueFromText(self, text):
        return super().valueFromText(text.replace(self._other(), self.locale().decimalPoint()))


# ---------------------------------------------------------------- value field

class ValueField(QtWidgets.QLineEdit):
    """A number with its unit, or "=expression". Typing units ("2 in"), formulas, or parameter
    names (autocompleted) works; Enter applies; Up/Down step by 1 (Ctrl: 0.1)."""

    def __init__(self, ed, prop, parent=None):
        super().__init__(parent)
        self.ed, self.prop = ed, prop
        self.setObjectName("kovacValue")
        from kovac import params
        names = params.user_params(ed.fp.Document)
        if names:
            comp = QtWidgets.QCompleter(names + ["=" + n for n in names], self)
            comp.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
            self.setCompleter(comp)
        self.editingFinished.connect(self.apply)
        self.show_value()

    def show_value(self):
        from kovac import params
        if self.hasFocus():
            return
        expr = params.expression(self.ed.fp, self.prop)
        self.setText(("=" + expr) if expr else params.describe(self.ed.fp, self.prop))
        self.setToolTip("Bound to: %s" % expr if expr else "Value, unit, formula or parameter name")

    def apply(self):
        from kovac import params
        text = self.text().strip()
        try:
            params.set_value(self.ed.fp, self.prop, text)
            self.setStyleSheet("")
        except Exception as e:
            self.setStyleSheet("color: %s;" % palette.SEMANTIC["error"])
            self.setToolTip(str(e))
            return
        self.ed.changed()

    def keyPressEvent(self, ev):
        if ev.key() in (QtCore.Qt.Key_Up, QtCore.Qt.Key_Down) and not self.text().startswith("="):
            v = getattr(self.ed.fp, self.prop)
            value = v.Value if hasattr(v, "Value") else float(v)
            step = (0.1 if ev.modifiers() & QtCore.Qt.ControlModifier else 1.0) * (1 if ev.key() == QtCore.Qt.Key_Up else -1)
            setattr(self.ed.fp, self.prop, type(value)(round(value + step, 6)) if not hasattr(v, "Value") else value + step)
            self.clearFocus()
            self.show_value()
            self.setFocus()
            self.ed.changed()
            return
        super().keyPressEvent(ev)


# ---------------------------------------------------------------- rows

class _Row:
    active = False
    single = False

    def accepts(self, obj, sub):
        return False

    def empty(self):
        return False

    def take(self, obj, sub, pnt):
        pass


class PickRow(_Row):
    """List of references from viewport picks (or one, single=True)."""

    def __init__(self, ed, prop, kinds, single=False):
        self.ed, self.prop, self.kinds, self.single = ed, prop, kinds, single
        self.list = QtWidgets.QListWidget()
        self.list.setMaximumHeight(28 if single else 84)
        self.list.itemDoubleClicked.connect(self.remove)
        self.list.setToolTip("Click geometry to add · double-click an entry to remove it")
        self.refresh()

    def values(self):
        v = getattr(self.ed.fp, self.prop)
        return ([v] if v else []) if self.single else list(v)

    def empty(self):
        return not self.values()

    def refresh(self):
        self.list.clear()
        doc = self.ed.fp.Document
        for r in self.values():
            try:
                text = topo.describe(r, doc)
            except Exception:
                text = r
            QtWidgets.QListWidgetItem(text, self.list).setData(QtCore.Qt.UserRole, r)

    def accepts(self, obj, sub):
        element = (sub or "").split(".")[-1]
        return model.pick_ref(obj, sub) is not None and any(element.startswith(k) for k in self.kinds)

    def take(self, obj, sub, pnt):
        ref = model.pick_ref(obj, sub)
        if self.single:
            setattr(self.ed.fp, self.prop, ref)
        elif ref not in self.values():
            setattr(self.ed.fp, self.prop, self.values() + [ref])
        self.refresh()

    def remove(self, item):
        r = item.data(QtCore.Qt.UserRole)
        setattr(self.ed.fp, self.prop, "" if self.single else [x for x in self.values() if x != r])
        self.refresh()
        self.ed.changed()


class ObjectRow(_Row):
    """Links or ids picked by clicking a sketch, a body, or a feature's geometry."""

    def __init__(self, ed, prop, what, single):
        self.ed, self.prop, self.what, self.single = ed, prop, what, single
        self.label = QtWidgets.QLabel()
        self.label.setWordWrap(True)
        self.refresh()

    def _items(self):
        v = getattr(self.ed.fp, self.prop)
        if self.what in ("sketch", "sketches", "features"):
            return [v] if self.single and v is not None else ([] if self.single else list(v))
        return ([v] if v else []) if self.single else list(v)

    def empty(self):
        return not self._items()

    def refresh(self):
        doc = self.ed.fp.Document
        names = []
        for x in self._items():
            if hasattr(x, "Label"):
                names.append(x.Label)
            else:
                b = model.body_object(doc, x)
                names.append(b.Label if b else x)
        self.label.setText(", ".join(names) or "<i>click in the view or the tree</i>")

    def resolve(self, obj, sub):
        if self.what in ("sketch", "sketches"):
            return obj if obj.TypeId.startswith("Sketcher::") else None
        if self.what in ("body", "bodies"):
            return obj.BodyId if type(getattr(obj, "Proxy", None)).__name__ == "BodyProxy" else None
        if self.what == "features":
            f = model.owner_of(obj, sub) if sub else (obj if model.is_feature(obj) else None)
            return f if f is not None and f is not self.ed.fp else None
        return None

    def accepts(self, obj, sub):
        return self.resolve(obj, sub) is not None

    def take(self, obj, sub, pnt):
        v = self.resolve(obj, sub)
        if self.single:
            setattr(self.ed.fp, self.prop, v)
        elif v not in self._items():
            setattr(self.ed.fp, self.prop, self._items() + [v])
        self.refresh()


class PlaneRow(_Row):
    single = True

    def __init__(self, ed, prop):
        self.ed, self.prop = ed, prop
        self.combo = QtWidgets.QComboBox()
        self.combo.addItems(["XY", "XZ", "YZ", "picked face / plane"])
        v = getattr(ed.fp, prop)
        self.combo.setCurrentIndex(["XY", "XZ", "YZ"].index(v) if v in ("XY", "XZ", "YZ") else 3)
        self.combo.currentIndexChanged.connect(self.choose)

    def choose(self, i):
        if i < 3:
            setattr(self.ed.fp, self.prop, ["XY", "XZ", "YZ"][i])
            self.ed.changed()

    def accepts(self, obj, sub):
        el = (sub or "").split(".")[-1]
        return (el.startswith("Face") and model.pick_ref(obj, sub) is not None) or \
            type(getattr(obj, "Proxy", None)).__name__ == "DatumPlane"

    def take(self, obj, sub, pnt):
        setattr(self.ed.fp, self.prop, obj.Name if not sub else model.pick_ref(obj, sub))
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(3)
        self.combo.blockSignals(False)


class AxisRow(_Row):
    single = True

    def __init__(self, ed, prop):
        self.ed, self.prop = ed, prop
        self.combo = QtWidgets.QComboBox()
        self.combo.addItems(["X", "Y", "Z", "picked edge / sketch line"])
        v = getattr(ed.fp, prop)
        self.combo.setCurrentIndex(["X", "Y", "Z"].index(v) if v in ("X", "Y", "Z") else 3)
        self.combo.currentIndexChanged.connect(self.choose)

    def choose(self, i):
        if i < 3:
            setattr(self.ed.fp, self.prop, "XYZ"[i])
            self.ed.changed()

    def accepts(self, obj, sub):
        el = (sub or "").split(".")[-1]
        return el.startswith("Edge") and (model.pick_ref(obj, sub) is not None or obj.TypeId.startswith("Sketcher::"))

    def take(self, obj, sub, pnt):
        el = sub.split(".")[-1]
        if obj.TypeId.startswith("Sketcher::"):
            setattr(self.ed.fp, self.prop, "sketch:%d" % obj.getGeometryId(int(el[4:]) - 1))
        else:
            setattr(self.ed.fp, self.prop, model.pick_ref(obj, sub))
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(3)
        self.combo.blockSignals(False)


class _ViewportPoints:
    """Point inputs read clicks straight from the viewport while they are the active input
    (deterministic, and picking a point does not disturb the selection)."""
    direct = True

    def press(self, it, pos):
        info = it.info_at(pos)
        if not info:
            return False
        obj, sub = it.target(info)
        if not self.accepts(obj, sub):
            return False
        self.it, self.pos = it, pos               # the click's screen position drives the snapping
        self.take(obj, sub, (info["x"], info["y"], info["z"]))
        self.ed.changed()
        return True

    def landing(self, obj, sub, pnt):
        """Where a click at this face point lands: (point, face normal, kind) or None if not flat."""
        import Part
        from kovac import grid
        f = Part.getShape(obj, sub, needSubElement=True)
        if not isinstance(f.Surface, Part.Plane):
            return None
        p = App.Vector(*pnt)
        q, kind = grid.face_snap(getattr(self, "it", None), getattr(self, "pos", None), p, f)
        return q, f.normalAt(*f.Surface.parameter(p)), kind

    def hover(self, it, pos):
        """(screen point, kind) of the snap under the cursor, for the snap marker."""
        info = it.info_at(pos)
        if not info:
            return None
        obj, sub = it.target(info)
        if not self.accepts(obj, sub):
            return None
        self.it, self.pos = it, pos
        hit = self.landing(obj, sub, (info["x"], info["y"], info["z"]))
        if hit is None or hit[2] is None:
            return None
        from kovac import grid
        return grid.screen_of(it, hit[0]), hit[2]

    def move(self, it, pos):
        pass

    def release(self, it, pos):
        pass


class PositionsRow(_ViewportPoints, _Row):
    def __init__(self, ed, prop):
        self.ed, self.prop = ed, prop
        self.label = QtWidgets.QLabel()
        clear = QtWidgets.QPushButton("Clear")
        clear.clicked.connect(self.clear)
        self.widget = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(self.widget)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.label, 1)
        lay.addWidget(clear)
        self.refresh()

    def empty(self):
        return not list(getattr(self.ed.fp, self.prop))

    def refresh(self):
        pts = list(getattr(self.ed.fp, self.prop))
        self.label.setText("%d centre%s" % (len(pts), "" if len(pts) == 1 else "s"))

    def clear(self):
        setattr(self.ed.fp, self.prop, [])
        self.refresh()
        self.ed.changed()

    def accepts(self, obj, sub):
        return (sub or "").split(".")[-1].startswith("Face") and model.pick_ref(obj, sub) is not None

    def take(self, obj, sub, pnt):
        if pnt is None:
            return
        hit = self.landing(obj, sub, pnt)
        p = hit[0] if hit else App.Vector(*pnt)
        setattr(self.ed.fp, self.prop, list(getattr(self.ed.fp, self.prop)) + [p])
        self.refresh()


class SkipRow(_Row):
    """Toggle pattern instances off by clicking any face of them."""

    def __init__(self, ed, prop):
        self.ed, self.prop = ed, prop
        self.label = QtWidgets.QLabel()
        self.refresh()

    def refresh(self):
        self.label.setText(", ".join(str(i) for i in getattr(self.ed.fp, self.prop)) or "none")

    def accepts(self, obj, sub):
        ref = model.pick_ref(obj, sub)
        return ref is not None and any("@%s." % self.ed.fp.Name in t for t in topo.loads(ref)["t"])

    def take(self, obj, sub, pnt):
        tag = next(t for t in topo.loads(model.pick_ref(obj, sub))["t"] if "@%s." % self.ed.fp.Name in t)
        k = int(tag.split("@%s." % self.ed.fp.Name)[1].split(":")[0].split("@")[0])
        skip = list(getattr(self.ed.fp, self.prop))
        setattr(self.ed.fp, self.prop, [i for i in skip if i != k] if k in skip else skip + [k])
        self.refresh()


# ---------------------------------------------------------------- the panel

class Editor(QtWidgets.QWidget):
    def __init__(self, fp, new):
        super().__init__()
        self.setObjectName("kovacEditor")
        self.fp, self.new, self.doc = fp, new, fp.Document
        self.rows, self.active = [], None
        self.timer = QtCore.QTimer(self, singleShot=True, interval=60)
        self.timer.timeout.connect(self.preview)
        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        for spec in SCHEMAS[_kind(fp)]:
            self.add_row(form, spec)
        self.status = QtWidgets.QLabel(objectName="kovacMuted")
        self.status.setWordWrap(True)
        ok = QtWidgets.QPushButton("OK", objectName="kovacPrimary")
        cancel = QtWidgets.QPushButton("Cancel")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.status)
        lay.addLayout(buttons)
        for key, slot in ((QtCore.Qt.Key_Return, self.accept), (QtCore.Qt.Key_Enter, self.accept), (QtCore.Qt.Key_Escape, self.reject)):
            sc = QtGui.QShortcut(QtGui.QKeySequence(key), Gui.getMainWindow())
            sc.setContext(QtCore.Qt.ApplicationShortcut)
            sc.activated.connect(slot)
            self.rows.append(sc)
        Gui.Selection.addObserver(self)
        pickers = [r for r in self.rows if isinstance(r, _Row)]
        first = next((r for r in pickers if r.empty()), pickers[0] if pickers else None)
        if first is not None:
            self.activate(first)
        self.show_status()

    # rows ------------------------------------------------------------------
    def add_row(self, form, spec):
        kind, fp = spec[0], self.fp
        if kind == "op":
            combo = _choice(fp, "Operation")
            combo.currentTextChanged.connect(lambda t: self.set("Operation", t))
            self.op_label = QtWidgets.QLabel(objectName="kovacMuted")
            box = QtWidgets.QVBoxLayout()
            box.addWidget(combo)
            box.addWidget(self.op_label)
            form.addRow("Result", box)
            return
        if kind == "groups":
            b = QtWidgets.QPushButton("Add a group with its own size")
            b.clicked.connect(self.add_group)
            form.addRow("", b)
            return
        if kind == "regions":
            from kovac import regionpick
            self.region_picker = regionpick.attach(self)
            form.addRow(spec[2], self.region_picker.label)
            return
        prop, label = spec[1], spec[2]
        if not hasattr(fp, prop):
            return
        if kind == "value":
            w = ValueField(self, prop)
            form.addRow(label, w)
            self.fields = getattr(self, "fields", []) + [(prop, w)]
        elif kind in ("int", "float"):
            w = QtWidgets.QSpinBox() if kind == "int" else DoubleSpinBox()
            w.setRange(1 if kind == "int" else 1e-6, 10000 if kind == "int" else 1e6)
            if kind == "float":
                w.setDecimals(4)
            w.setValue(getattr(fp, prop))
            w.valueChanged.connect(lambda v, p=prop: self.set(p, v))
            form.addRow(label, w)
        elif kind == "enum":
            w = _choice(fp, prop)
            w.currentTextChanged.connect(lambda t, p=prop: self.set(p, t))
            form.addRow(label, w)
        elif kind == "bool":
            w = QtWidgets.QCheckBox()
            w.setChecked(getattr(fp, prop))
            w.toggled.connect(lambda b, p=prop: self.set(p, b))
            form.addRow(label, w)
        elif kind == "text":
            w = QtWidgets.QLineEdit(getattr(fp, prop))
            w.editingFinished.connect(lambda p=prop, w=w: self.set(p, w.text()))
            form.addRow(label, w)
        elif kind == "vector":
            box, spins = QtWidgets.QHBoxLayout(), []
            for i, c in enumerate("xyz"):
                s = DoubleSpinBox()
                s.setRange(-1e6, 1e6)
                s.setDecimals(3)
                s.setValue(getattr(fp, prop)[i])
                s.setPrefix(c + " ")
                spins.append(s)
                box.addWidget(s)
            for s in spins:
                s.valueChanged.connect(lambda _v, p=prop, sp=spins: self.set(p, App.Vector(*[x.value() for x in sp])))
            form.addRow(label, box)
        elif kind == "move":
            box, spins = QtWidgets.QHBoxLayout(), []
            pl = getattr(fp, prop)
            for c, v in zip(("x", "y", "z", "rot Z°"), (pl.Base.x, pl.Base.y, pl.Base.z, pl.Rotation.Angle * 57.29577951308232)):
                s = DoubleSpinBox()
                s.setRange(-1e6, 1e6)
                s.setPrefix(c + " ")
                s.setValue(v)
                spins.append(s)
                box.addWidget(s)
            for s in spins:
                s.valueChanged.connect(lambda _v, p=prop, sp=spins: self.set(
                    p, App.Placement(App.Vector(sp[0].value(), sp[1].value(), sp[2].value()), App.Rotation(App.Vector(0, 0, 1), sp[3].value()))))
            form.addRow(label, box)
        elif kind == "place":
            hint = QtWidgets.QLabel("<i>click a face to place it there</i>")
            row = PlaceRow(self, prop, hint)
            self.rows.append(row)
            form.addRow(label, self._activatable(row, hint))
        elif kind in ("picks", "pick"):
            row = PickRow(self, prop, spec[3], single=(kind == "pick"))
            self.rows.append(row)
            form.addRow(label, self._activatable(row, row.list))
        elif kind in ("sketch", "sketches", "body", "bodies", "features"):
            row = ObjectRow(self, prop, kind, single=kind in ("sketch", "body"))
            self.rows.append(row)
            form.addRow(label, self._activatable(row, row.label))
        elif kind == "plane":
            row = PlaneRow(self, prop)
            self.rows.append(row)
            form.addRow(label, self._activatable(row, row.combo))
        elif kind == "axis":
            row = AxisRow(self, prop)
            self.rows.append(row)
            form.addRow(label, self._activatable(row, row.combo))
        elif kind == "positions":
            row = PositionsRow(self, prop)
            self.rows.append(row)
            form.addRow(label, self._activatable(row, row.widget))
        elif kind == "skip":
            row = SkipRow(self, prop)
            self.rows.append(row)
            form.addRow(label, self._activatable(row, row.label))

    def _activatable(self, row, widget):
        """Wrap an input with a radio-style marker: the active input receives viewport picks."""
        box = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        row.button = QtWidgets.QToolButton(text="●", toolTip="Picks in the view go here", checkable=True)
        row.button.clicked.connect(lambda _=False, r=row: self.activate(r))
        lay.addWidget(row.button)
        lay.addWidget(widget, 1)
        return box

    def activate(self, row):
        from kovac import navigation
        for r in self.rows:                       # only the active point input listens to the view
            if getattr(r, "direct", False) and r in navigation.hooks:
                navigation.hooks.remove(r)
        if getattr(row, "direct", False):
            navigation.hooks.append(row)
        self.active = row
        for r in self.rows:
            if isinstance(r, _Row) and hasattr(r, "button"):
                r.button.setChecked(r is row)
                r.button.setStyleSheet("color: %s;" % (palette.accent() if r is row else palette.THEMES["light"]["border"]))

    def add_group(self):
        from kovac import modify
        modify.add_group(self.fp)
        prop_v, prop_e = modify.edge_groups(self.fp)[-1]
        row = PickRow(self, prop_e, ("Edge",))
        self.rows.append(row)
        form = self.layout().itemAt(0).layout()
        w = ValueField(self, prop_v)
        self.fields = getattr(self, "fields", []) + [(prop_v, w)]
        form.addRow("Group %s size" % prop_v[-1], w)
        form.addRow("Group %s edges" % prop_v[-1], self._activatable(row, row.list))
        self.activate(row)

    # changes ---------------------------------------------------------------
    def set(self, prop, value):
        try:
            setattr(self.fp, prop, value)
        except Exception as e:
            commands.report(e)
        self.changed()

    def changed(self):
        self.timer.start()

    def preview(self):
        model.commit(self.doc)
        self.show_status()
        if hasattr(self, "region_picker"):
            self.region_picker.refresh()
        for _prop, w in getattr(self, "fields", []):
            w.show_value()
        for hook in getattr(self, "hooks", []):
            hook.refresh()

    def show_status(self):
        if hasattr(self, "op_label"):
            self.op_label.setText(self.fp.ResolvedOperation)
        st = self.fp.Status
        self.status.setText(st or "")
        self.status.setStyleSheet("color: %s;" % palette.SEMANTIC["error"] if st else "")

    # selection observer: picks go to the active input ------------------------------
    def addSelection(self, doc, obj_name, sub, pnt=None):
        try:
            self._add_selection(doc, obj_name, sub, pnt)
        except Exception as e:          # observers swallow errors silently; make them visible
            import traceback
            commands.last_trace = traceback.format_exc()
            commands.report("Pick not used: %s" % e)

    def _add_selection(self, doc, obj_name, sub, pnt=None):
        obj = App.getDocument(doc).getObject(obj_name)
        rows = [self.active] + [r for r in self.rows if isinstance(r, _Row) and r is not self.active]
        for r in rows:
            if r is not None and r.accepts(obj, sub):
                r.take(obj, sub, pnt)
                pickers = [x for x in self.rows if isinstance(x, _Row)]
                after = pickers[pickers.index(r) + 1:]
                # a one-pick input is done once filled: the next input takes the following picks
                self.activate(next((x for x in after if x.empty()), after[0]) if r.single and after else r)
                self.changed()
                return

    # finish ------------------------------------------------------------------
    rollback_before = None

    def restore_rollback(self):
        if self.rollback_before is not None:      # outside the undo step: only a view of the history
            model.set_rollback(self.doc, self.rollback_before)
            model.commit(self.doc)

    def close_panel(self):
        global _current
        Gui.Selection.removeObserver(self)
        for r in self.rows:
            if isinstance(r, QtGui.QShortcut):
                r.setEnabled(False)
                r.deleteLater()
        if hasattr(self, "region_picker"):
            self.region_picker.detach()
        from kovac import navigation
        for r in self.rows:
            if getattr(r, "direct", False) and r in navigation.hooks:
                navigation.hooks.remove(r)
        for hook in getattr(self, "hooks", []):
            hook.detach()
        dock = self.parent()
        while dock is not None and not isinstance(dock, QtWidgets.QDockWidget):
            dock = dock.parent()
        if dock is not None:
            dock.setObjectName("")      # never handed to the next panel while it is being deleted
            dock.close()
            dock.deleteLater()
        _current = None

    def accept(self):
        if _current is not self:
            return
        self.hide_consumed()
        model.commit(self.doc)
        if self.new and self.fp.Status:
            # a brand new feature that failed outright has nothing worth keeping -- same as
            # Cancel, not left behind broken. An *edit* that breaks a feature still commits
            # (reject() below): it's not new, and the history after it may depend on its tip.
            self.reject()
            return
        if self.doc.HasPendingTransaction:
            self.doc.commitTransaction()
        self.close_panel()
        self.restore_rollback()
        if self.fp.Status:
            commands.report("%s: %s" % (self.fp.Label, self.fp.Status))

    def hide_consumed(self):
        """Sketches a feature uses (profile, path, sections, points) step out of the way."""
        for prop in ("Profile", "Path", "Points", "Sections"):
            v = getattr(self.fp, prop, None)
            for sk in (v if isinstance(v, list) else [v]):
                if sk is not None and sk.TypeId.startswith("Sketcher::") and sk.ViewObject is not None:
                    sk.ViewObject.Visibility = False

    def reject(self):
        if _current is not self:
            return
        if self.doc.HasPendingTransaction:
            self.doc.abortTransaction()
        self.close_panel()
        self.restore_rollback()
        model.commit(self.doc)


class PlaceRow(_ViewportPoints, _Row):
    """Primitive placement: click a face; the shape sits on it at the clicked point."""

    def __init__(self, ed, prop, label):
        self.ed, self.prop, self.label = ed, prop, label

    def accepts(self, obj, sub):
        return (sub or "").split(".")[-1].startswith("Face")

    def take(self, obj, sub, pnt):
        import Part
        from kovac import datum
        f = Part.getShape(obj, sub, needSubElement=True)
        if not isinstance(f.Surface, Part.Plane):
            return
        p, n, _ = self.landing(obj, sub, pnt or tuple(f.CenterOfMass))
        setattr(self.ed.fp, self.prop, datum.frame(p, n))
        self.label.setText("on %s" % obj.Label)


def point_input():
    """The active input of the open panel when it takes points clicked on faces, else None."""
    ed = _current
    row = getattr(ed, "active", None) if ed is not None else None
    return row if isinstance(row, _ViewportPoints) else None


def close_current():
    """Close whatever panel is already open (OK if it was editing, Cancel if it was new),
    before starting or opening another one. Must run before a new transaction is opened or a
    new feature created: start()/edit() used to do this *after*, inside open_editor() -- late
    enough that Cancelling the panel just opened could abort the transaction the previous
    command's own feature was created under, deleting it out from under its own panel (a
    ReferenceError on fp.Document, since nothing closed the first panel first)."""
    if _current is not None:
        _current.reject() if _current.new else _current.accept()


def open_editor(fp, new):
    """Show the panel for fp (inside a transaction the caller opened)."""
    global _current
    from kovac import panel
    ed = Editor(fp, new)
    title = ("New " if new else "Edit ") + fp.Label
    d = panel.dock("Editor", title, ed, floating=True)
    d.setWindowTitle(title)
    d.setWidget(ed)
    d.show()
    d.raise_()
    _current = ed
    from kovac import manip
    manip.attach(ed)
    ed.preview()
    return ed


def start(proxy, name=None, **props):
    """Create a feature at the rollback marker and open its panel (one transaction)."""
    close_current()
    doc = App.ActiveDocument
    if doc is None:
        from kovac import startpage
        doc = startpage.new_design()
    doc.openTransaction(proxy.kind)
    fp = model.create(doc, proxy, name, **props)
    return open_editor(fp, True)


def edit(fp):
    """Edit a history feature: the model rolls back to it while the panel is open."""
    close_current()
    doc = fp.Document
    before = model.rollback_index(doc)
    its = model.items(doc)
    if fp in its and its.index(fp) + 1 < before:
        model.set_rollback(doc, its.index(fp) + 1)
        model.commit(doc)
    doc.openTransaction("Edit " + fp.Label)
    ed = open_editor(fp, False)
    ed.rollback_before = before if fp in its and its.index(fp) + 1 < before else None
    return ed

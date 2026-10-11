# SPDX-License-Identifier: LGPL-2.1-or-later
"""Sketching. "Create Sketch": the origin planes appear, planar faces highlight on hover; a
click on either (or a face already selected) makes the sketch, the camera turns to face it,
and FreeCAD's sketcher takes over the drawing (inline dimensions, inference glyphs, DOF and
conflict reporting) with Kovač's own tool ribbon and a prominent Finish Sketch. Sketching starts
and ends in the three-quarter overview; the task panel stays closed.

The sketch sits on a hidden plane (DatumPlane, Auto) that follows the picked face through the
Kovač naming layer, so the sketch moves when the model upstream changes."""
import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtGui, QtWidgets

import kovac
from kovac import commands, datum, model, navigation, overlay, palette, sketchtools, views

V = App.Vector
# FreeCAD's sketcher commands on Kovač's sketch ribbon, each with our own icon, in our grouping
SKETCH_TOOLS = [      # an inner list is one button with its variants behind the arrow
    ("Create", [("Sketcher_CreateLine", "line"), [("Kovac_Polyline", "polyline"), ("Sketcher_CreatePolyline", "polyline")],
                [("Sketcher_CreateRectangle", "rectangle"), ("Sketcher_CreateRectangle_Center", "rect_center"),
                 ("Sketcher_CreateOblong", "rect_rounded")],
                [("Sketcher_CreateCircle", "circle"), ("Sketcher_Create3PointCircle", "circle3")],
                [("Sketcher_CreateArc", "arc"), ("Sketcher_Create3PointArc", "arc3")],
                [("Sketcher_CreateRegularPolygon", "polygon"), ("Kovac_PolygonAround", "polygon_out")],
                ("Sketcher_CreateSlot", "slot"),
                ("Sketcher_CreateEllipseByCenter", "ellipse"), ("Sketcher_CreateBSpline", "spline"),
                ("Sketcher_CreatePoint", "spoint")]),
    ("Modify", [[("Sketcher_CreateFillet", "sk_fillet"), ("Sketcher_CreateChamfer", "sk_chamfer")],
                ("Sketcher_Trimming", "trim"), ("Sketcher_Extend", "extend"), ("Sketcher_Split", "sk_split"),
                ("Sketcher_Offset", "offset"), ("Sketcher_Symmetry", "sk_mirror"),
                [("Sketcher_Translate", "sk_move"), ("Sketcher_Rotate", "sk_rotate"), ("Sketcher_Scale", "sk_scale"),
                 ("Sketcher_RectangularArray", "sk_array")],
                ("Sketcher_ToggleConstruction", "construction")]),
    ("Constrain", [("Sketcher_Dimension", "dimension"),
                   [("Sketcher_ConstrainCoincident", "c_coincident"), ("Sketcher_ConstrainPointOnObject", "c_pointon")],
                   [("Sketcher_ConstrainHorizontal", "c_horizontal"), ("Sketcher_ConstrainVertical", "c_vertical")],
                   [("Sketcher_ConstrainParallel", "c_parallel"), ("Sketcher_ConstrainPerpendicular", "c_perpendicular")],
                   ("Sketcher_ConstrainTangent", "c_tangent"),
                   [("Sketcher_ConstrainEqual", "c_equal"), ("Sketcher_ConstrainSymmetric", "c_symmetric")],
                   [("Sketcher_ConstrainBlock", "c_block"), ("Sketcher_ConstrainLock", "c_lock")],
                   [("Sketcher_ConstrainDistanceX", "c_hdist"), ("Sketcher_ConstrainDistanceY", "c_vdist"),
                    ("Sketcher_ConstrainDistance", "c_dist")],
                   [("Sketcher_ConstrainRadius", "c_radius"), ("Sketcher_ConstrainDiameter", "c_diameter")],
                   ("Sketcher_ConstrainAngle", "c_angle"), ("Sketcher_ToggleDrivingConstraint", "c_driving")]),
    ("3D", [("Sketcher_Projection", "project"), ("Sketcher_CarbonCopy", "carbon"), ("Sketcher_ViewSketch", "sk_look"),
            ("Sketcher_ViewSection", "sk_section")]),
]
_ICON_OF = {cid: icon for _, tools in SKETCH_TOOLS for e in tools for cid, icon in (e if isinstance(e, list) else [e])}


def tool_icon(cid):
    """Path of our icon for a sketcher command, or ''."""
    return kovac.icon(_ICON_OF[cid]) if cid in _ICON_OF else ""


KOVAC_KEYS = ("S",)     # sketcher shortcuts that would shadow Kovač's own keys are left off
_ui = {}


def _face_plane(obj, sub):
    if not sub or not sub.split(".")[-1].startswith("Face"):
        return None
    f = Part.getShape(obj, sub, needSubElement=True)
    return f if isinstance(f.Surface, Part.Plane) else None


def _has_model():
    """Anything on screen to fit to (fitting an empty scene zooms somewhere arbitrary)."""
    doc = App.ActiveDocument
    return doc is not None and any(getattr(o, "Visibility", False) and not getattr(o, "Shape", Part.Shape()).isNull()
                                   for o in doc.Objects if o.TypeId != "App::FeaturePython" or hasattr(o, "BodyId"))


def overview(view=None, fit=None):
    """The three-quarter view from top, front and right that sketching starts and ends in."""
    view = view or Gui.activeView()
    if view is not None and hasattr(view, "getCameraNode"):
        views.go(view, views.view_rotation(views.ISO), fit=_has_model() if fit is None else fit)


def start(then=None):
    """Sketch on the selected flat face/plane, or let the user pick one; `then` is a sketch
    tool to start once the sketch is open."""
    doc = App.ActiveDocument
    if doc is None:
        from kovac import startpage
        startpage.new_design()
        doc = App.ActiveDocument
    for s in Gui.Selection.getSelectionEx("", 0):
        for sub in s.SubElementNames or [""]:
            if type(getattr(s.Object, "Proxy", None)).__name__ == "DatumPlane" and not sub:
                return create(base=s.Object.Name, then=then)
            if _face_plane(s.Object, sub) is not None and model.pick_ref(s.Object, sub):
                return create(base=model.pick_ref(s.Object, sub), then=then)
    PlanePicker(then)
    overview(fit=True)                    # all three origin planes in sight


def _rounded_square(lo, hi, r, a, b):
    """Face of a square with rounded corners spanning lo..hi along unit vectors a and b."""
    import math
    P = lambda u, v: V(u, v, 0)  # noqa: E731
    arc = lambda cu, cv, a0: Part.ArcOfCircle(Part.Circle(P(cu, cv), V(0, 0, 1), r), a0, a0 + math.pi / 2)  # noqa: E731
    segs = [Part.LineSegment(P(lo + r, lo), P(hi - r, lo)), arc(hi - r, lo + r, -math.pi / 2),
            Part.LineSegment(P(hi, lo + r), P(hi, hi - r)), arc(hi - r, hi - r, 0),
            Part.LineSegment(P(hi - r, hi), P(lo + r, hi)), arc(lo + r, hi - r, math.pi / 2),
            Part.LineSegment(P(lo, hi - r), P(lo, lo + r)), arc(lo + r, lo + r, math.pi)]
    face = Part.Face(Part.Wire([g.toShape() for g in segs]))
    c = a.cross(b)
    face.transformShape(App.Matrix(a.x, b.x, c.x, 0, a.y, b.y, c.y, 0, a.z, b.z, c.z, 0, 0, 0, 0, 1))
    return face


class PlanePicker:
    """The three origin planes, drawn as rounded squares on the side of the origin that faces the
    overview camera (so none hides another), set in a little from the axes and outlined. The one
    under the cursor lights up; the clicked one takes the accent colour, then the sketch opens on it.
    A click on a flat body face works too."""
    GAP, ROUND = 0.08, 0.12          # share of the square's size

    def __init__(self, then=None):
        from pivy import coin
        self.planes, self.then, self.hot = {}, then, None
        size = 60
        bb = App.BoundBox()
        for b in model.bodies(App.ActiveDocument):
            if not b.Shape.isNull():
                bb.add(b.Shape.BoundBox)
        if bb.isValid():
            size = max(size, bb.DiagonalLength)
        sx, sy, sz = (1 if c >= 0 else -1 for c in views.ISO)
        sep = coin.SoSeparator()
        for name, n, col, (a, b) in (("XY", V(0, 0, 1), palette.SEMANTIC["axis_z"], (V(sx, 0, 0), V(0, sy, 0))),
                                     ("XZ", V(0, -1, 0), palette.SEMANTIC["axis_y"], (V(sx, 0, 0), V(0, 0, sz))),
                                     ("YZ", V(1, 0, 0), palette.SEMANTIC["axis_x"], (V(0, sy, 0), V(0, 0, sz)))):
            f = _rounded_square(self.GAP * size, size, self.ROUND * size, a, b)
            fill = overlay.face_node(f, col, 0.78, offset=False)
            mat = next(fill.getChild(i) for i in range(fill.getNumChildren())
                       if fill.getChild(i).isOfType(coin.SoMaterial.getClassTypeId()))
            edge, line, style = coin.SoSeparator(), coin.SoBaseColor(), coin.SoDrawStyle()
            light = coin.SoLightModel()
            light.model = coin.SoLightModel.BASE_COLOR
            line.rgb = overlay.rgb(col)
            style.lineWidth = 2.5
            pts = f.OuterWire.discretize(96)
            crd = coin.SoCoordinate3()
            crd.point.setValues(0, len(pts), [[q.x, q.y, q.z] for q in pts])
            ls = coin.SoLineSet()
            ls.numVertices.setValue(len(pts))
            for node in (light, line, style, crd, ls):
                edge.addChild(node)
            sep.addChild(fill)
            sep.addChild(edge)
            self.planes[name] = (f, n, col, mat, line, style)
        self.node = overlay.add(sep)
        navigation.hooks.append(self)
        commands.report("Pick a plane or a flat face to sketch on (Esc to cancel)", error=False)
        self.esc = QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Escape), Gui.getMainWindow())
        self.esc.activated.connect(self.cancel)

    def plane_at(self, it, pos):
        o, d = overlay.ray(it, pos)
        best = None
        for name, (f, n, *_rest) in self.planes.items():
            p = overlay.hit_plane(o, d, V(), n)
            if p is not None and f.isInside(p, 1e-6, True):
                t = (p - o).dot(d)
                if best is None or t < best[0]:
                    best = (t, name)
        return best and best[1]

    def paint(self, chosen=None):
        for name, (_f, _n, col, mat, line, style) in self.planes.items():
            if name == chosen:
                fill, edge, alpha, width = palette.accent(), palette.accent(), 0.45, 3.5
            elif name == self.hot:
                fill, edge, alpha, width = col, palette.mix(col, "#FFFFFF", 0.45), 0.6, 3.5
            else:
                fill, edge, alpha, width = col, col, 0.78, 2.5
            mat.diffuseColor = overlay.rgb(fill)
            mat.transparency = alpha
            line.rgb = overlay.rgb(edge)
            style.lineWidth = width

    def highlight(self, it, pos):
        hot = self.plane_at(it, pos)
        if hot != self.hot:
            self.hot = hot
            self.paint()

    def press(self, it, pos):
        info = it.info_at(pos)
        if info:
            obj, sub = it.target(info)
            if _face_plane(obj, sub) is not None and model.pick_ref(obj, sub):
                ref = model.pick_ref(obj, sub)
                self.cancel()
                create(base=ref, then=self.then)
                return True
        name = self.plane_at(it, pos)
        if name is None:
            return False
        self.paint(chosen=name)                       # a short flash of the choice, then the sketch
        if self in navigation.hooks:
            navigation.hooks.remove(self)
        QtCore.QTimer.singleShot(90, lambda: (self.cancel(), create(base=name, then=self.then)))
        return True

    def move(self, it, pos):
        pass

    def release(self, it, pos):
        pass

    def cancel(self):
        overlay.remove(self.node)
        if self in navigation.hooks:
            navigation.hooks.remove(self)
        self.esc.setEnabled(False)
        self.esc.deleteLater()


def create(base="XY", name="Sketch", then=None):
    """One undo step: hidden plane + sketch at the rollback marker; then edit it."""
    doc = App.ActiveDocument
    view = Gui.activeView()
    with commands.transaction("Create sketch", doc):
        mode = base if base in ("XY", "XZ", "YZ") else "Offset"
        plane = model.create(doc, datum.DatumPlane, "SketchPlane", Mode=mode, Base=base, Auto=True)
        if plane.ViewObject is not None:
            plane.ViewObject.Visibility = False
        doc.recompute()
        sk = datum.sketch_on(doc, plane, name)
        model.insert(doc, sk)
        model.commit(doc)
    edit(sk, view)
    if then:
        QtCore.QTimer.singleShot(300, lambda: commands.run(then))
    return sk


def edit(sk, view=None):
    view = view or Gui.activeView()
    if view is not None:
        r = sk.getGlobalPlacement().Rotation
        views.go(view, views.camera_rotation(r.multVec(V(0, 0, 1)), r.multVec(V(0, 1, 0))), fit=_has_model())
    from kovac import grid, shell
    grid.sketch_snap(sk)
    vo = sk.ViewObject
    if vo is not None and hasattr(vo, "EditingWorkbench"):
        vo.EditingWorkbench = ""          # stay in Kovač: no switch to FreeCAD's sketcher workbench
    for prop in ("ShowSupport", "RestoreCamera"):     # no grey sketch plane; Kovač moves the camera
        if vo is not None and hasattr(vo, prop):
            setattr(vo, prop, False)
    sketchtools.install()
    Gui.ActiveDocument.setEdit(sk.Name)
    _ui["sketch"] = sk.Name
    show_bar(True)
    for ms in (0, 300):                   # edit mode may pop up FreeCAD's own sketch toolbars
        QtCore.QTimer.singleShot(ms, shell.apply_visibility)


def finish():
    """Leave the sketch and go back to the three-quarter overview."""
    gd = Gui.ActiveDocument
    name = _ui.pop("sketch", None)
    if gd is not None and gd.getInEdit() is not None:
        gd.resetEdit()
    show_bar(False)
    sketchtools.stop()
    doc = App.ActiveDocument
    if doc is not None:
        model.commit(doc)
        sk = doc.getObject(name) if name else None
        if sk is not None:
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(sk)      # ready for Extrude / Revolve
    overview()


def in_sketch():
    gd = Gui.ActiveDocument
    obj = gd.getInEdit() if gd else None
    return obj is not None and obj.Object.TypeId.startswith("Sketcher::")


def _tool_action(cid, icon, parent):
    """Our own button for a sketcher command (FreeCAD makes its actions only for its own bars)."""
    cmd = Gui.Command.get(cid)
    if cmd is None:
        return None
    info = cmd.getInfo()
    text = info.get("menuText", cid).replace("&", "")
    a = QtGui.QAction(QtGui.QIcon(kovac.icon(icon)), text, parent)
    a.setObjectName(cid)
    key = info.get("shortcut", "")
    a.setToolTip("%s%s\n%s" % (text, "  (%s)" % key if key else "", info.get("toolTip", "")))
    if key and key not in KOVAC_KEYS:
        a.setShortcut(QtGui.QKeySequence(key))
    a.triggered.connect(lambda _=False, c=cid: (sketchtools.stop(), commands.run(c)))   # recorded for "repeat last"
    return a


def show_bar(on):
    from kovac import shell
    mw = Gui.getMainWindow()
    bar = mw.findChild(QtWidgets.QToolBar, "kovacSketchBar")
    if bar is None and on:
        import SketcherGui  # noqa: F401  (registers the sketcher commands)
        bar = shell._toolbar("kovacSketchBar", brk=False)
        btn = QtWidgets.QPushButton(QtGui.QIcon(kovac.icon("finish")), "  Finish Sketch", objectName="kovacFinish")
        btn.setIconSize(QtCore.QSize(24, 24))
        btn.setStyleSheet("QPushButton#kovacFinish { background: %s; color: white; font-weight: 700; font-size: 15px;"
                          " padding: 8px 12px; border-radius: 6px; border: none; margin-right: 4px; }" % palette.accent())
        btn.clicked.connect(lambda: commands.run("Kovac_FinishSketch"))
        bar.addWidget(btn)
        for label, tools in SKETCH_TOOLS:
            bar.addWidget(shell.ribbon_divider())
            buttons = []
            for entry in tools:
                acts = [a for a in (_tool_action(cid, icon, bar) for cid, icon in
                                    (entry if isinstance(entry, list) else [entry])) if a is not None]
                if acts:
                    buttons.append(shell._button(acts if len(acts) > 1 else acts[0]))
            bar.addWidget(shell.ribbon_group(label, buttons))     # the buttons keep shortcuts live
    if bar is not None:
        bar.setVisible(on)
    for tb in shell._ui.get("groups", {}).get(shell.mode(), []) + shell._ui.get("bars", [])[1:2]:
        tb.setVisible(not on)             # Finish Sketch takes the mode button's place

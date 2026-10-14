# SPDX-License-Identifier: LGPL-2.1-or-later
"""Assemble commands (ADR-0004): New Component, New Instance, Joint, Drag, Ground.

Joint: hovering a body shows joint-origin markers where a joint can attach (face centres,
circle centres, edge middles and ends, corners; the one nearest the cursor lights up). Click one
on the part that stays, then one on the part that moves: the second part snaps into place right
away. The panel picks the joint type (what motion is left), a gap, a turn and a flip; OK keeps
it as one undo step. A body that isn't in a component yet gets one of its own.

Drag: grab a jointed part and pull: it moves only the way its joint lets it (a hinge turns, a
slider slides), the rest of the assembly follows through the solver, and every answer is
checked (joints.solve). Not a history step: positions are assembly state.
"""
import math

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from kovac import commands, components, joints, model, navigation, overlay, palette

V = App.Vector
MARK_PX = 11           # joint-origin marker radius on screen


# ---------------------------------------------------------------- picks

def _body_pick(it, pos):
    """(top, sub, leaf body, element) under the cursor when it is a Kovač body, else None."""
    info = it.info_at(pos)
    if not info:
        return None
    top, sub = it.target(info)
    leaf, element = components.resolve(top, sub)
    if type(getattr(leaf, "Proxy", None)).__name__ != "BodyProxy" or not element:
        return None
    return top, sub, leaf, element


def _moving_part(top, sub, leaf):
    """The top-level component or instance a pick moves with (None: not in a component)."""
    if components.is_root(top) and "." in sub:
        c = top.Document.getObject(sub.split(".")[0])
        if components.is_component(c):
            return c
    return components.holder(leaf)


def _candidates(it, top, sub, leaf, element):
    """[(kind, local Placement, global Placement, screen distance)] for the element under the cursor."""
    F = components.path_frame(top, sub)
    out = []
    for kind, pl in joints.snaps(leaf.Shape, element):
        g = F.multiply(pl)
        out.append((kind, pl, g))
    return out


def _screen(it, p):
    from kovac import grid
    return grid.screen_of(it, p)


def origin_node(pl, px, color, hot=False):
    """A joint-origin marker: a ring in the frame's XY plane, its Z axis and a centre dot, drawn
    over the model at a fixed screen size."""
    from pivy import coin
    sep = coin.SoAnnotation()
    style = coin.SoDrawStyle()
    style.lineWidth = 3.0 if hot else 1.6
    sep.addChild(style)
    mat = coin.SoMaterial()
    c = overlay.rgb(color)
    mat.diffuseColor = c
    mat.emissiveColor = c
    sep.addChild(mat)
    r = MARK_PX * px
    o = pl.Base
    x, y, z = (pl.Rotation.multVec(a) for a in (V(1, 0, 0), V(0, 1, 0), V(0, 0, 1)))
    pts = [o + (x * math.cos(2 * math.pi * k / 24) + y * math.sin(2 * math.pi * k / 24)) * r for k in range(25)]
    pts += [o, o + z * r * 2.6]
    crd = coin.SoCoordinate3()
    crd.point.setValues(0, len(pts), [[p.x, p.y, p.z] for p in pts])
    sep.addChild(crd)
    ls = coin.SoLineSet()
    ls.numVertices.setValues(0, 2, [25, 2])
    sep.addChild(ls)
    ps = coin.SoDrawStyle()
    ps.pointSize = 7 if hot else 5
    sep.addChild(ps)
    dot = coin.SoCoordinate3()
    dot.point.setValue(o.x, o.y, o.z)
    sep.addChild(dot)
    sep.addChild(coin.SoPointSet())
    return sep


# ---------------------------------------------------------------- the Joint tool

class JointTool:
    """Pick a joint origin on each of two components; type, gap, turn and flip in a panel."""

    def __init__(self, existing=None):
        from kovac import editor, move, panel
        self.doc = App.ActiveDocument
        self.joint, self.picks, self.nodes, self.hot = existing, [], [], None
        self.kind = joints.kind_of(existing) if existing is not None else _last["kind"]
        self.doc.openTransaction("Edit joint" if existing else "Joint")
        w = QtWidgets.QWidget(objectName="kovacJoint")
        lay = QtWidgets.QVBoxLayout(w)
        self.choice = editor.IconChoice([k for k, _ in joints.TYPES], self.kind)
        self.choice.setObjectName("kovacJointType")
        self.choice.currentTextChanged.connect(self.set_kind)
        lay.addWidget(self.choice)
        self.help = QtWidgets.QLabel(objectName="kovacMuted")
        lay.addWidget(self.help)
        grid = QtWidgets.QGridLayout()
        self.gap, self.turn = move._Field(w), move._Field(w)
        self.gap.setObjectName("kovacJointGap")
        self.turn.setObjectName("kovacJointTurn")
        for r, (label, field) in enumerate((("Gap", self.gap), ("Turn", self.turn))):
            grid.addWidget(QtWidgets.QLabel(label), r, 0)
            grid.addWidget(field, r, 1)
            field.editingFinished.connect(self.typed)
            field.returnPressed.connect(self.typed)
        lay.addLayout(grid)
        row = QtWidgets.QHBoxLayout()
        flip = QtWidgets.QPushButton("Flip", objectName="kovacJointFlip")
        flip.setIcon(QtGui.QIcon(__import__("kovac").icon("flip")))
        flip.clicked.connect(self.flip)
        again = QtWidgets.QPushButton("Pick again")
        again.clicked.connect(self.repick)
        row.addWidget(flip)
        row.addWidget(again)
        lay.addLayout(row)
        self.status = QtWidgets.QLabel(objectName="kovacMuted")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        cancel = QtWidgets.QPushButton("Cancel")
        self.ok_button = QtWidgets.QPushButton("OK", objectName="kovacPrimary")
        cancel.clicked.connect(self.cancel)
        self.ok_button.clicked.connect(self.ok)
        buttons.addWidget(cancel)
        buttons.addWidget(self.ok_button)
        lay.addLayout(buttons)
        self.dock = panel.dock("Joint", "Joint", w, floating=True)
        self.dock.setWindowTitle("Edit joint" if existing else "Joint")
        self.dock.setWidget(w)
        self.dock.show()
        self.esc = QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Escape), Gui.getMainWindow())
        self.esc.setContext(QtCore.Qt.ApplicationShortcut)
        self.esc.activated.connect(self.cancel)
        navigation.hooks.insert(0, self)
        self.running = commands.started(self.end)        # another command or Undo ends the panel
        self.refresh()

    # ------------------------------------------------------------ panel
    def refresh(self):
        self.help.setText("%s: %s." % (self.kind, joints.HELP[self.kind]))
        j = self.joint
        if j is not None:
            self.gap.setText("%.2f mm" % float(j.Gap)) if not self.gap.hasFocus() else None
            self.turn.setText("%.1f°" % float(j.Turn)) if not self.turn.hasFocus() else None
        for f in (self.gap, self.turn):
            f.setEnabled(j is not None)
        self.ok_button.setEnabled(j is not None)
        if j is not None:
            self.status.setText(getattr(self, "problem", "") or "Drag the moving part later with Drag to try the joint.")
        elif not self.picks:
            self.status.setText("Click where the joint sits on the part that stays (a face, circle, edge or corner).")
        else:
            self.status.setText("Now click where it sits on the part that moves: it snaps into place.")

    def set_kind(self, kind):
        self.kind = _last["kind"] = kind
        if self.joint is not None:
            joints.set_kind(self.joint, kind)
            self.apply()
        self.refresh()

    def typed(self):
        if self.joint is None:
            return
        for field, prop, unit in ((self.gap, "Gap", "mm"), (self.turn, "Turn", "deg")):
            try:
                q = App.Units.Quantity(field.text().strip().replace(",", ".").replace("°", " deg"))
                v = q.Value if q.Unit == App.Units.Unit() else q.getValueAs(unit).Value
            except Exception:
                continue
            if abs(float(getattr(self.joint, prop)) - v) > 1e-9:
                setattr(self.joint, prop, v)
        self.apply()
        self.refresh()

    def flip(self):
        if self.joint is not None:
            self.joint.Flip = not self.joint.Flip
            self.apply()

    def apply(self):
        """The joint changed: snap the moving part again and solve (a live preview)."""
        self.problem = joints.snap_into_place(self.joint)
        self.doc.recompute()
        self.refresh()

    def repick(self):
        if self.joint is not None:
            self.doc.removeObject(self.joint.Name)
            self.joint = None
        self.picks = []
        self.refresh()

    # ------------------------------------------------------------ viewport
    def _clear(self):
        for n in self.nodes:
            overlay.remove(n)
        self.nodes = []

    def _draw(self, it, cands, hot):
        self._clear()
        px = it.px_size()
        for c in cands:
            self.nodes.append(overlay.add(origin_node(c[2], px, palette.accent() if c is hot else palette.SEMANTIC["preselect"],
                                                      c is hot)))
        for p in self.picks:                        # what is already picked stays marked
            self.nodes.append(overlay.add(origin_node(p["global"], px, palette.accent(), True)))

    def _hot(self, it, pos):
        pick = _body_pick(it, pos)
        if pick is None:
            return None, [], None
        cands = _candidates(it, *pick)
        if not cands:
            return pick, [], None
        q = QtCore.QPointF(pos)

        def dist(c):
            s = _screen(it, c[2].Base)
            return math.hypot(s.x() - q.x(), s.y() - q.y())
        best = min(cands, key=dist)
        return pick, cands, best

    def highlight(self, it, pos):
        if self.joint is not None:
            return
        _pick, cands, hot = self._hot(it, pos)
        self.hot = hot
        self._draw(it, cands, hot)

    def handle_at(self, it, pos):
        return None

    def press(self, it, pos):
        if self.joint is not None:
            return False
        pick, _cands, hot = self._hot(it, pos)
        if pick is None or hot is None:
            return False
        top, sub, leaf, element = pick
        comp = _moving_part(top, sub, leaf)
        if comp is None:            # a loose body: it gets a component of its own
            comp = components.new_component(self.doc, [leaf], leaf.Label)
        if self.picks and self.picks[0]["origin"].comp == comp:
            self.status.setText("That is the same component. Click a point on the other part.")
            return True
        near = tuple(hot[1].Base)
        o = joints.Origin.at(comp, leaf, element, hot[0], near)
        self.picks.append({"origin": o, "global": hot[2]})
        if len(self.picks) == 2:
            try:
                self.joint = joints.create(self.doc, self.kind, self.picks[0]["origin"], self.picks[1]["origin"])
                self.problem = ""
            except ValueError as e:
                self.picks.pop()
                self.status.setText(str(e))
                return True
            self._clear()
            self.gap.setFocus()
        self.refresh()
        self._draw(it, [], None)
        return True

    def move(self, it, pos):
        pass

    def release(self, it, pos):
        pass

    # ------------------------------------------------------------ finish
    def end(self):
        """Ended from outside (another command, Undo): a joint already made is kept, as OK would."""
        if self.joint is not None:
            self.ok()
        else:
            self.cancel()

    def ok(self):
        if self.joint is None:
            return
        self.typed()
        if self.doc.HasPendingTransaction:
            self.doc.commitTransaction()
        self.close()

    def cancel(self):
        if self.doc.HasPendingTransaction:
            self.doc.abortTransaction()
        self.doc.recompute()
        self.close()

    def close(self):
        global _tool
        commands.ended(self.running)
        self._clear()
        if self in navigation.hooks:
            navigation.hooks.remove(self)
        self.esc.setEnabled(False)
        self.esc.deleteLater()
        self.dock.setObjectName("")
        self.dock.close()
        self.dock.deleteLater()
        _tool = None


_last = {"kind": "Rigid"}
_tool = None


def joint():
    global _tool
    finish()
    from kovac import editor
    if editor.current() is not None:
        editor.close_current()
    _tool = JointTool()
    return _tool


def edit_joint(j):
    global _tool
    finish()
    _tool = JointTool(j)
    return _tool


def finish():
    global _tool, _drag
    if _tool is not None:
        _tool.cancel()
    if _drag is not None:
        _drag.stop()


# ---------------------------------------------------------------- Drag

def _ray_plane(it, pos, point, normal):
    ro, rd = overlay.ray(it, pos)
    return overlay.hit_plane(ro, rd, point, normal)


def _signed_angle(a, b, axis):
    a = a - axis * a.dot(axis)
    b = b - axis * b.dot(axis)
    if a.Length < 1e-9 or b.Length < 1e-9:
        return 0.0
    ang = a.getAngle(b)
    return ang if axis.dot(a.cross(b)) >= 0 else -ang


def motion(comp, grab, it, pos, start):
    """Where a dragged component goes for the cursor at pos: along what its first joint leaves
    free (turn about a hinge axis, slide along a slider), else freely in the view plane.
    grab is the grabbed point (global) at the start, start the component's placement then."""
    view_n = V(*it.view.getViewDirection()).normalize()
    j, mine = None, None
    for x in joints.all_joints(comp.Document):
        try:
            o1, o2 = joints.origins(x)
        except Exception:
            continue
        if o1.comp == comp or o2.comp == comp:
            j, mine = x, (2 if o2.comp == comp else 1)
            break
    if j is None:
        hit = _ray_plane(it, pos, grab, view_n)
        return None if hit is None else App.Placement(hit - grab, App.Rotation()).multiply(start)
    a, b = joints.global_frames(j)
    ref = a if mine == 2 else b                  # the other side's frame holds still
    z, p = ref.Rotation.multVec(V(0, 0, 1)), ref.Base
    t = j.JointType
    if t in ("Revolute", "Cylindrical"):
        hit = _ray_plane(it, pos, grab, z)
        if hit is None:
            return None
        ang = math.degrees(_signed_angle(grab - p, hit - p, z))
        m = App.Placement(V(), App.Rotation(z, ang), p)
        if t == "Cylindrical":                   # and slide along the axis by the cursor's run
            ro, rd = overlay.ray(it, pos)
            q = overlay.closest_on_line(ro, rd, p, z)
            q0 = p + z * (grab - p).dot(z)
            m = App.Placement(z * (q - q0).dot(z), App.Rotation()).multiply(m)
        return m.multiply(start)
    if t == "Slider":
        ro, rd = overlay.ray(it, pos)
        q = overlay.closest_on_line(ro, rd, grab, z)
        return App.Placement(z * (q - grab).dot(z), App.Rotation()).multiply(start)
    if t == "Ball":
        r = (grab - p).Length
        hit = _ray_plane(it, pos, grab, view_n)
        if hit is None or r < 1e-9:
            return None
        rot = App.Rotation(grab - p, hit - p)
        return App.Placement(V(), rot, p).multiply(start)
    if t == "Distance":                          # planar: slide in the plane
        hit = _ray_plane(it, pos, grab, z)
        return None if hit is None else App.Placement(hit - grab, App.Rotation()).multiply(start)
    return None                                  # rigid: nothing to drag


class DragTool:
    """Grab a part and pull it; its joints decide how it moves. Esc or the command again ends."""

    def __init__(self):
        self.doc = App.ActiveDocument
        self.grab = None
        navigation.hooks.insert(0, self)
        self.running = commands.started(self.stop, "Kovac_DragComponent")
        self.esc = QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Escape), Gui.getMainWindow())
        self.esc.setContext(QtCore.Qt.ApplicationShortcut)
        self.esc.activated.connect(self.stop)
        commands.report("Drag: pull a part; its joints decide how it moves. Esc ends.")

    def handle_at(self, it, pos):
        return None

    def press(self, it, pos):
        pick = _body_pick(it, pos)
        if pick is None:
            return False
        top, sub, leaf, _el = pick
        comp = _moving_part(top, sub, leaf)
        if comp is None:
            commands.report("That body isn't in a component. Make one with New Component (or join it) first.")
            return True
        if comp in joints.grounded(self.doc):
            commands.report("%s is grounded: it holds still. Unground it in the browser to move it." % comp.Label)
            return True
        info = it.info_at(pos)
        self.comp, self.start = comp, App.Placement(comp.Placement)
        self.grab = V(info["x"], info["y"], info["z"])
        self.doc.openTransaction("Drag")
        self.last = QtCore.QElapsedTimer()
        self.last.start()
        return True

    def move(self, it, pos):
        if self.grab is None:
            return
        target = motion(self.comp, self.grab, it, pos, self.start)
        if target is not None:
            joints.drag(self.doc, self.comp, target)

    def release(self, it, pos):
        if self.grab is None:
            return
        self.grab = None
        if self.doc.HasPendingTransaction:
            self.doc.commitTransaction()

    def stop(self):
        global _drag
        commands.ended(self.running)
        if self in navigation.hooks:
            navigation.hooks.remove(self)
        self.esc.setEnabled(False)
        self.esc.deleteLater()
        if self.doc.HasPendingTransaction:
            self.doc.commitTransaction()
        _drag = None
        commands.report("")


_drag = None


def drag():
    global _drag
    if _drag is not None:           # the command again ends it
        _drag.stop()
        return None
    if _tool is not None:
        _tool.cancel()
    _drag = DragTool()
    return _drag


# ---------------------------------------------------------------- simple commands

def _selected_bodies():
    out = []
    for leaf, _el, _t, _s in components.selected():
        if type(getattr(leaf, "Proxy", None)).__name__ == "BodyProxy" and leaf not in out:
            out.append(leaf)
    return out


def _selected_components():
    from kovac import move
    return move._components_of()


def new_component():
    """From the selected bodies (and the sketches only they use), else an empty one that becomes
    the active component."""
    doc = App.ActiveDocument
    bodies = _selected_bodies()
    with commands.transaction("New component", doc):
        comp = components.new_component(doc, bodies)
        model.commit(doc)
    if not bodies:
        components.set_active(doc, comp)
        commands.report("%s is active: new sketches and bodies go into it. Double-click it in the browser to leave." % comp.Label)
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(comp)
    return comp


def instance(comps=None):
    doc = App.ActiveDocument
    comps = comps or _selected_components()
    if not comps:
        raise ValueError("Select a component (or a body in one) to make another instance of.")
    with commands.transaction("New instance", doc):
        made = [components.new_instance(c) for c in comps]
        doc.recompute()
    Gui.Selection.clearSelection()
    for m in made:
        Gui.Selection.addSelection(m)
    return made


def copy(comps=None):
    doc = App.ActiveDocument
    comps = comps or _selected_components()
    if not comps:
        raise ValueError("Select a component (or a body in one) to copy.")
    with commands.transaction("Copy component", doc):
        made = [components.copy_component(c) for c in comps]
        model.commit(doc)
    Gui.Selection.clearSelection()
    for m in made:
        Gui.Selection.addSelection(m)
    return made


def move_to(bodies, target):
    """Bodies into component `target` (None: the top of the design), as one undo step."""
    doc = bodies[0].Document
    with commands.transaction("Move to %s" % (target.Label if target is not None else "the design"), doc):
        steps = components.move_bodies(doc, bodies, target)
        model.commit(doc)
    if steps:
        commands.report("%s: a history step keeps %s where %s." % (steps[0].Label, "them" if len(bodies) > 1 else "it",
                                                                   "they are" if len(bodies) > 1 else "it is"), error=False)


def ground(comps=None, on=True):
    doc = App.ActiveDocument
    comps = comps or _selected_components()
    if not comps:
        raise ValueError("Select a component to ground (it then holds still).")
    with commands.transaction("Ground" if on else "Unground", doc):
        for c in comps:
            joints.ground(doc, c) if on else joints.unground(doc, c)
        model.commit(doc)


def toggle_ground():
    doc = App.ActiveDocument
    comps = _selected_components()
    ground(comps, on=not all(c in joints.grounded(doc) for c in comps) if comps else True)


def move_component(c):
    from kovac import move
    return move.move_components([c])


COMMANDS = [
    ("Kovac_NewComponent", "New Component", "A component from the selected bodies, or an empty one to model in",
     new_component, "new_component", "Shift+C"),
    ("Kovac_NewInstance", "New Instance", "Another instance of the selected component: edit one, all change",
     instance, "instance", ""),
    ("Kovac_CopyComponent", "Copy Component", "An independent copy of the selected component, with bodies of its own",
     copy, "copy_component", ""),
    ("Kovac_Joint", "Joint", "Connect two components: pick a point on each, then choose what motion is left",
     joint, "joint", "Shift+J"),
    ("Kovac_DragComponent", "Drag", "Pull jointed parts: they move only as their joints allow (Esc ends)",
     drag, "drag_part", "Shift+D"),
    ("Kovac_Ground", "Ground", "Hold the selected component still (or let it go again)", toggle_ground, "ground", ""),
]


def register():
    import kovac
    for cid, label, tip, fn, icon, key in COMMANDS:
        commands.add(cid, label, tip, fn, icon=kovac.icon(icon), key=key, ends_tools=True)

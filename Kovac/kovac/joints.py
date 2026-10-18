# SPDX-License-Identifier: LGPL-2.1-or-later
"""Joints between components (ADR-0004). Headless logic; the Joint command is in assemble.py.

A joint is FreeCAD's own ``JointObject`` in the design assembly's joint group, but Kovač owns
where its two frames are:

- each side stores a *joint origin*: the component it moves with, the body, an ADR-0003
  reference to the face / edge / corner it was snapped to, and the snap kind;
- at every regeneration (``update``) the reference is resolved in today's body, the frame rebuilt
  from today's geometry and written into the joint (``Detach1/2``: FreeCAD doesn't recompute it);
- a reference that can't be resolved flags the joint ("Missing reference: ..."), and the
  components stay where they were;
- the solver's answer is checked (``verify``): grounded components unmoved, every joint's frames
  meeting the way its type says, and within its limits. A wrong answer is undone and reported,
  never shown.

A turning or sliding joint has a *position*: the turn about and the slide along side 1's axis
of side 2's frame, 0 as jointed. Optional limits keep it in a range; ``set_position`` drives it
and ``clamp`` holds a drag inside the limits.

Frame convention: Z is the outward normal of the face snapped to (a circle edge takes its flat
face's), so two snapped faces *meet* (side 2 is turned over); X follows the body's own axes
projected onto the plane, so it doesn't spin when the part is edited.
"""
import json
import math

import FreeCAD as App
import Part

from kovac import components, model, topo

V = App.Vector
# what the user picks -> FreeCAD's joint type
TYPES = [("Rigid", "Fixed"), ("Revolute", "Revolute"), ("Slider", "Slider"),
         ("Cylindrical", "Cylindrical"), ("Ball", "Ball"), ("Planar", "Distance")]
FREECAD = dict(TYPES)
KOVAC = {v: k for k, v in TYPES}
HELP = {"Rigid": "locked together", "Revolute": "turns about the axis", "Slider": "slides along the axis",
        "Cylindrical": "turns and slides along the axis", "Ball": "turns any way about the point",
        "Planar": "slides and turns on the plane"}
TOL = 1e-5
MOVES = {"Revolute": ("angle",), "Slider": ("slide",), "Cylindrical": ("angle", "slide")}   # FreeCAD type -> free coordinates
# Kovač's own limit properties, measured from the jointed position (FreeCAD's AngleMin/LengthMin
# and their Enable flags stay off: its solver would count from its own zero)
_LIMIT_PROPS = {"angle": ("TurnLimits", "TurnMin", "TurnMax", "App::PropertyAngle", (-90.0, 90.0), "turn"),
                "slide": ("SlideLimits", "SlideMin", "SlideMax", "App::PropertyDistance", (0.0, 10.0), "slide")}


# ---------------------------------------------------------------- frames from geometry

def _normal(face, p=None):
    """Outward normal (normalAt follows the face's orientation)."""
    p = face.CenterOfMass if p is None else p
    return face.normalAt(*face.Surface.parameter(p))


def _x_for(z):
    """In-plane X from the body's own axes: stable when the part changes."""
    for a in (V(1, 0, 0), V(0, 1, 0), V(0, 0, 1)):
        x = a - z * a.dot(z)
        if x.Length > 1e-6:
            return x.normalize()
    return V(1, 0, 0)


def placement(origin, z, x=None):
    z = V(z).normalize()
    x = _x_for(z) if x is None else (V(x) - z * V(x).dot(z)).normalize()
    y = z.cross(x)
    m = App.Matrix(x.x, y.x, z.x, origin.x, x.y, y.y, z.y, origin.y, x.z, y.z, z.z, origin.z, 0, 0, 0, 1)
    return App.Placement(m)


def _unique_faces(shape, edge):
    out = []
    for f in shape.ancestorsOfType(edge, Part.Face):
        if not any(f.isSame(g) for g in out):
            out.append(f)
    return out


def _is_seam(shape, edge):
    """The seam line of a closed round face (both sides are the same face)."""
    return len(_unique_faces(shape, edge)) == 1


def _flat_neighbour(shape, edge):
    for f in shape.ancestorsOfType(edge, Part.Face):
        if isinstance(f.Surface, Part.Plane):
            return f
    return None


def snaps(shape, element):
    """Joint-origin candidates on one element of a body shape: [(kind, Placement)], best first.
    Kinds: 'centre' (face centre, circle centre), 'axis' (a round face's axis), 'mid' (edge
    middle), 'end' (an edge's ends), 'corner'."""
    kind = element.rstrip("0123456789")
    i = int(element[len(kind):])
    out = []
    if kind == "Face":
        f = shape.Faces[i - 1]
        s = f.Surface
        if isinstance(s, Part.Plane):
            out.append(("centre", placement(f.CenterOfMass, _normal(f))))
        elif isinstance(s, (Part.Cylinder, Part.Cone)):
            axis = s.Axis
            mid = s.Center if isinstance(s, Part.Cylinder) else s.Apex
            c = f.CenterOfMass
            base = mid + axis * (c - mid).dot(axis)       # the axis point level with the face's middle
            out.append(("axis", placement(base, axis)))
            for e in f.Edges:                              # and each rim's centre
                if isinstance(e.Curve, Part.Circle):
                    nb = _flat_neighbour(shape, e)
                    out.append(("centre", placement(e.Curve.Center, _normal(nb) if nb else e.Curve.Axis)))
        elif isinstance(s, Part.Sphere):
            out.append(("centre", placement(s.Center, V(0, 0, 1))))
        else:
            out.append(("centre", placement(f.CenterOfMass, _normal(f))))
    elif kind == "Edge":
        e = shape.Edges[i - 1]
        if _is_seam(shape, e):               # the seam of a round face: offer the face's snaps
            f = _unique_faces(shape, e)[0]
            return snaps(shape, "Face%d" % next(n for n, g in enumerate(shape.Faces, 1) if g.isSame(f)))
        c = e.Curve
        nb = _flat_neighbour(shape, e)
        if isinstance(c, Part.Circle):
            out.append(("centre", placement(c.Center, _normal(nb) if nb else c.Axis)))
        else:
            a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
            mid = e.valueAt((e.FirstParameter + e.LastParameter) / 2)
            d = (b - a) if (b - a).Length > 1e-9 else V(0, 0, 1)
            out.append(("mid", placement(mid, d)))
            z = _normal(nb) if nb else d
            out += [("end", placement(a, z)), ("end", placement(b, z))]
    elif kind == "Vertex":
        v = shape.Vertexes[i - 1]
        edges = [e for e in shape.ancestorsOfType(v, Part.Edge) if not _is_seam(shape, e)]
        ring = [e for e in edges if e.isClosed()]
        if ring and len(edges) == len(ring):
            # a circle's seam point means nothing to the user: offer what its circle offers
            k = next(n for n, e in enumerate(shape.Edges, 1) if e.isSame(ring[0]))
            return snaps(shape, "Edge%d" % k)
        p = v.Point
        faces = [f for f in shape.ancestorsOfType(shape.Vertexes[i - 1], Part.Face) if isinstance(f.Surface, Part.Plane)]
        out.append(("corner", placement(p, _normal(faces[0]) if faces else V(0, 0, 1))))
    return out


def frame(shape, element, kind, near=None):
    """The snap of a kind on an element; with several (an edge's two ends) the one nearest
    `near` (body coordinates), else the first."""
    cands = [p for k, p in snaps(shape, element) if k == kind]
    if not cands:
        raise topo.Broken("it no longer has a %s to snap to" % kind)
    if near is not None and len(cands) > 1:
        cands.sort(key=lambda p: (p.Base - V(*near)).Length)
    return cands[0]


# ---------------------------------------------------------------- joint origins

class Origin:
    """One side of a joint: the component that moves with it (the top-level part or instance),
    the body, a reference, the snap kind (and a hint point for edges with two ends)."""

    def __init__(self, comp, body, ref, kind, near=None):
        self.comp, self.body, self.ref, self.kind, self.near = comp, body, ref, kind, near

    @classmethod
    def at(cls, comp, body, element, kind, near=None):
        """From a pick: element of body (as the body shows today)."""
        ref = topo.dumps(topo.make_ref(model.state_of(body.Tip), body.BodyId, element))
        return cls(comp, body, ref, kind, near)

    def dumps(self):
        return json.dumps({"comp": self.comp.Name, "body": self.body.Name, "ref": self.ref,
                           "kind": self.kind, "near": self.near})

    @classmethod
    def loads(cls, doc, text):
        d = json.loads(text)
        return cls(doc.getObject(d["comp"]), doc.getObject(d["body"]), d["ref"], d["kind"], d.get("near"))

    def resolve(self):
        """(element name today, frame in body coordinates); raises topo.Broken."""
        if self.comp is None or self.body is None:
            raise topo.Broken("its component or body was deleted")
        state = model.state_of(self.body.Tip)
        name = topo.resolve(self.ref, state)
        shape = state[topo.loads(self.ref)["b"]].shape
        return name, frame(shape, name, self.kind, self.near)

    def describe(self):
        return topo.describe(self.ref, self.body.Document if self.body is not None else None)


# ---------------------------------------------------------------- joints

def is_joint(o):
    return o is not None and hasattr(o, "KovacOrigin1")


def is_ground(o):
    return o is not None and hasattr(o, "ObjectToGround")


def all_joints(doc):
    jg = components.joint_group(doc)
    return [o for o in jg.Group if is_joint(o)] if jg else []


def grounds(doc):
    jg = components.joint_group(doc)
    return [o for o in jg.Group if is_ground(o)] if jg else []


def grounded(doc):
    return [g.ObjectToGround for g in grounds(doc) if g.ObjectToGround is not None]


def origins(j):
    doc = j.Document
    return Origin.loads(doc, j.KovacOrigin1), Origin.loads(doc, j.KovacOrigin2)


def ground(doc, comp):
    import JointObject
    if comp in grounded(doc):
        return None
    g = components.joint_group(doc).newObject("App::FeaturePython", "Ground")
    JointObject.GroundedJoint(g, comp)
    g.Label = "Ground · %s" % comp.Label
    return g


def unground(doc, comp):
    for g in grounds(doc):
        if g.ObjectToGround == comp:
            doc.removeObject(g.Name)


def create(doc, kind, o1, o2, offset=0.0, angle=0.0, flip=False):
    """A joint of a Kovač kind ('Rigid', 'Revolute', ...): o2's component snaps onto o1's
    (unless it is grounded and o1's isn't: then the other way round). The first joint of a
    design grounds the component that stays."""
    import JointObject
    if o1.comp == o2.comp:
        raise ValueError("Both picks are on the same component. Pick a point on each of the two.")
    fixed = grounded(doc)
    if o2.comp in fixed and o1.comp not in fixed:
        o1, o2 = o2, o1
    if not fixed:
        ground(doc, o1.comp)
    j = components.joint_group(doc).newObject("App::FeaturePython", "Joint")
    JointObject.Joint(j, JointObject.JointTypes.index(FREECAD[kind]))
    j.Detach1 = j.Detach2 = True
    j.addProperty("App::PropertyString", "KovacOrigin1", "Kovac", "", 4)
    j.addProperty("App::PropertyString", "KovacOrigin2", "Kovac", "", 4)
    j.addProperty("App::PropertyDistance", "Gap", "Joint", "distance between the two origins along their axis")
    j.addProperty("App::PropertyAngle", "Turn", "Joint", "turn about the axis")
    j.addProperty("App::PropertyBool", "Flip", "Joint", "turn the moving component over")
    j.addProperty("App::PropertyString", "KovacStatus", "Kovac", "empty when healthy", 1)
    j.KovacOrigin1, j.KovacOrigin2 = o1.dumps(), o2.dumps()
    j.Gap, j.Turn, j.Flip = offset, angle, flip
    j.Label = "%s · %s – %s" % (kind, o1.comp.Label, o2.comp.Label)
    before = {c.Name: c.Placement for c in components.all_components(doc)}
    if not write(j):
        raise ValueError(j.KovacStatus)
    msg = snap_into_place(j)
    if msg:                                  # it can't hold with the others: put everything back
        for c in components.all_components(doc):
            if c.Name in before:
                c.Placement = before[c.Name]
        raise ValueError("This joint can't hold together with the others (%s)." % msg.split(": ", 1)[-1].rstrip("."))
    add_step(j)
    return j


def set_kind(j, kind):
    j.JointType = FREECAD[kind]
    j.Label = "%s · %s" % (kind, j.Label.split(" · ", 1)[-1])
    step = step_of(j)
    if step is not None:
        step.Label = "Joint " + j.Label         # labels are unique: not the joint's own
        vo = getattr(step, "ViewObject", None)
        if vo is not None and hasattr(vo.Proxy, "icon"):
            vo.Proxy.icon = ICONS.get(j.JointType, "joint")


# ---------------------------------------------------------------- the joint's timeline step

ICONS = {"Fixed": "j_rigid", "Revolute": "j_revolute", "Slider": "j_slider", "Cylindrical": "j_cylindrical",
         "Ball": "j_ball", "Distance": "j_planar"}


class JointStep(model.Feature):
    """A joint's place in the history (ADR-0004): rolled back before it, or suppressed, the
    joint is off and its parts move freely; deleting the step deletes the joint. It changes no
    body, and its Status shows the joint's problem in the timeline."""
    kind, icon, state_feature = "Joint", "joint", False

    def setup(self, fp):
        fp.addProperty("App::PropertyString", "Joint", "Joint", "the joint (its name)", 1)

    def execute(self, fp):
        pass                                     # nothing to compute; update() keeps Status

    def removed(self, fp):
        j = fp.Document.getObject(fp.Joint)
        if j is not None:
            fp.Document.removeObject(j.Name)


def _is_step(o):
    return type(getattr(o, "Proxy", None)).__name__ == "JointStep"


def step_of(j):
    return next((o for o in model.items(j.Document) if _is_step(o) and o.Joint == j.Name), None)


def joint_of(step):
    return step.Document.getObject(step.Joint)


def add_step(j, index=None):
    """The joint's step at the rollback marker (or at index)."""
    doc = j.Document
    fp = doc.addObject("App::FeaturePython", "JointStep")
    JointStep(fp)
    if App.GuiUp and fp.ViewObject is not None:
        model.ViewProvider(fp.ViewObject, ICONS.get(j.JointType, "joint"))
    fp.Joint = j.Name
    fp.Label = "Joint " + j.Label
    model.insert(doc, fp, index)
    return fp


def is_on(j):
    """False while the joint's step is rolled back or suppressed."""
    step = step_of(j)
    return step is None or (model.active(step) and not step.Suppressed)


def delete(j):
    """Delete a joint (or a ground) together with its timeline step."""
    doc = j.Document
    step = step_of(j) if is_joint(j) else None
    if step is not None:
        model.remove(doc, step)                  # takes the joint along (JointStep.removed)
    elif doc.getObject(j.Name) is not None:
        doc.removeObject(j.Name)


def kind_of(j):
    return KOVAC.get(j.JointType, j.JointType)


def frames(j):
    """(Placement1, Placement2) of a joint in its bodies' coordinates, from today's geometry,
    with its gap, turn and flip; plus today's element names. Raises topo.Broken."""
    o1, o2 = origins(j)
    n1, f1 = o1.resolve()
    n2, f2 = o2.resolve()
    f1 = f1.multiply(App.Placement(V(0, 0, float(j.Gap)), App.Rotation(V(0, 0, 1), float(j.Turn))))
    f2 = f2.multiply(App.Placement(V(), App.Rotation(V(1, 0, 0), 180)))     # faces meet
    if j.Flip:
        f2 = f2.multiply(App.Placement(V(), App.Rotation(V(1, 0, 0), 180)))
    return (n1, f1), (n2, f2), (o1, o2)


def write(j):
    """Resolve both origins and write them into FreeCAD's joint; flag it if a reference is gone."""
    try:
        (n1, f1), (n2, f2), (o1, o2) = frames(j)
    except topo.Broken as e:
        status = "Missing reference: %s — %s. Edit the joint and pick it again." % (
            e.ref and topo.describe(e.ref, j.Document) or "a picked point", e)
        if j.KovacStatus != status:
            j.KovacStatus = status
        return False
    for i, o, n, f in ((1, o1, n1, f1), (2, o2, n2, f2)):
        sub = "%s.%s" % (o.body.Name, n)
        ref = getattr(j, "Reference%d" % i)
        if ref is None or ref[0] != o.comp or list(ref[1]) != [sub, sub]:
            setattr(j, "Reference%d" % i, [o.comp, [sub, sub]])
        if not getattr(j, "Placement%d" % i).isSame(f, 1e-12):
            setattr(j, "Placement%d" % i, f)
    if j.KovacStatus:
        j.KovacStatus = ""
    return True


def global_frames(j):
    o1, o2 = origins(j)
    return (o1.comp.Placement.multiply(j.Placement1), o2.comp.Placement.multiply(j.Placement2))


def satisfied(j):
    """True if the joint's two frames meet the way its type says."""
    a, b = global_frames(j)
    za, zb = a.Rotation.multVec(V(0, 0, 1)), b.Rotation.multVec(V(0, 0, 1))
    xa, xb = a.Rotation.multVec(V(1, 0, 0)), b.Rotation.multVec(V(1, 0, 0))
    d = b.Base - a.Base
    together = d.Length < TOL
    z_same = za.cross(zb).Length < 1e-6 and za.dot(zb) > 0
    x_same = xa.cross(xb).Length < 1e-6 and xa.dot(xb) > 0
    on_axis = d.cross(za).Length < TOL
    t = j.JointType
    if t == "Fixed":
        return together and z_same and x_same
    if t == "Revolute":
        return together and z_same
    if t == "Cylindrical":
        return on_axis and z_same
    if t == "Slider":
        return on_axis and z_same and x_same
    if t == "Ball":
        return together
    if t == "Distance":
        return za.cross(zb).Length < 1e-6 and abs(d.dot(za)) < TOL
    return True


# ---------------------------------------------------------------- position and limits

def _ensure_limits(j):
    """Limit properties (older joints get them on first use)."""
    for on, lo, hi, typ, (dlo, dhi), what in _LIMIT_PROPS.values():
        if not hasattr(j, on):
            j.addProperty("App::PropertyBool", on, "Limits", "keep the %s within Min and Max" % what)
            j.addProperty(typ, lo, "Limits", "smallest %s" % what)
            j.addProperty(typ, hi, "Limits", "largest %s" % what)
            setattr(j, lo, dlo)
            setattr(j, hi, dhi)


def limits(j):
    """{"angle": (min, max) or None, "slide": (min, max) or None}: the limits that are on."""
    out = {}
    for key, (on, lo, hi, *_rest) in _LIMIT_PROPS.items():
        out[key] = (float(getattr(j, lo)), float(getattr(j, hi))) if getattr(j, on, False) else None
    return out


_KEEP = object()


def set_limits(j, angle=_KEEP, slide=_KEEP):
    """Turn limits on with a (min, max) pair or off with None; leave out to keep as is."""
    _ensure_limits(j)
    for key, value in (("angle", angle), ("slide", slide)):
        if value is _KEEP:
            continue
        on, lo, hi, *_rest = _LIMIT_PROPS[key]
        if value is None:
            setattr(j, on, False)
            continue
        a, b = sorted(float(x) for x in value)
        setattr(j, lo, a)
        setattr(j, hi, b)
        setattr(j, on, True)


def _move(angle, slide):
    return App.Placement(V(0, 0, slide), App.Rotation(V(0, 0, 1), angle))


def position(j, frames=None):
    """(turn in degrees, slide in mm) of side 2's frame against side 1's, about and along side
    1's axis; (0, 0) as jointed."""
    a, b = frames or global_frames(j)
    r = a.inverse().multiply(b)
    x = r.Rotation.multVec(V(1, 0, 0))
    return math.degrees(math.atan2(x.y, x.x)), r.Base.z


def _limited(j, angle, slide):
    lim = limits(j)
    free = MOVES.get(j.JointType, ())
    if "angle" in free and lim["angle"]:
        angle = min(max(angle, lim["angle"][0]), lim["angle"][1])
    if "slide" in free and lim["slide"]:
        slide = min(max(slide, lim["slide"][0]), lim["slide"][1])
    return angle, slide


def within(j, frames=None):
    """True if the joint's position is inside its limits (always, for joints without any)."""
    if j.JointType not in MOVES or not (getattr(j, "TurnLimits", False) or getattr(j, "SlideLimits", False)):
        return True
    ang, sl = position(j, frames)
    a2, s2 = _limited(j, ang, sl)
    return abs(a2 - ang) < 1e-4 and abs(s2 - sl) < TOL


def _frames_with(j, comp, placement):
    o1, o2 = origins(j)
    p1 = placement if o1.comp == comp else o1.comp.Placement
    p2 = placement if o2.comp == comp else o2.comp.Placement
    return p1.multiply(j.Placement1), p2.multiply(j.Placement2)


def _placed(j, comp, frames, angle, slide):
    """comp's placement that brings the joint from its position in `frames` to (angle, slide),
    the other side holding still."""
    a, b = frames
    now = position(j, frames)
    fix = _move(angle, slide).multiply(_move(*now).inverse())       # in side 1's frame
    o1, o2 = origins(j)
    if o2.comp == comp:
        b2 = a.multiply(fix).multiply(a.inverse()).multiply(b)
        return b2.multiply(j.Placement2.inverse())
    r2 = fix.multiply(a.inverse().multiply(b))
    return b.multiply(r2.inverse()).multiply(j.Placement1.inverse())


def clamp(j, comp, placement):
    """The placement for comp nearest to `placement` that keeps joint j within its limits."""
    if j.JointType not in MOVES:
        return placement
    frames = _frames_with(j, comp, placement)
    ang, sl = position(j, frames)
    a2, s2 = _limited(j, ang, sl)
    if abs(a2 - ang) < 1e-9 and abs(s2 - sl) < 1e-12:
        return placement
    return _placed(j, comp, frames, a2, s2)


def moving_side(j):
    """The component that moves when the joint is driven: side 2's, unless it is grounded."""
    o1, o2 = origins(j)
    return o1.comp if o2.comp in grounded(j.Document) and o1.comp not in grounded(j.Document) else o2.comp


def set_position(doc, j, angle=None, slide=None):
    """Drive a turning or sliding joint to (angle, slide), within its limits; None keeps that
    coordinate. The rest of the design follows through the solver; True if it holds."""
    if j.JointType not in MOVES:
        return False
    comp = moving_side(j)
    if comp in grounded(doc):
        return False
    frames = global_frames(j)
    ang, sl = position(j, frames)
    a2, s2 = _limited(j, ang if angle is None else float(angle), sl if slide is None else float(slide))
    return drag(doc, comp, _placed(j, comp, frames, a2, s2))


def snap_into_place(j):
    """Move the joint's second component so the joint holds (what making a joint does), then
    solve. Starting from a joined state keeps the solver from wandering (ADR-0004, E4)."""
    o1, o2 = origins(j)
    if write(j):
        target = o1.comp.Placement.multiply(j.Placement1).multiply(j.Placement2.inverse())
        if o2.comp not in grounded(j.Document):
            o2.comp.Placement = target
    return solve(j.Document)


def solve(doc):
    """Solve the design's joints and check the answer. Returns '' or what went wrong; a wrong
    answer is undone (components back where they were)."""
    asm = components.root(doc)
    js = [j for j in all_joints(doc) if not j.KovacStatus and not j.Suppressed]
    if asm is None or not js:
        return ""
    before = {c.Name: c.Placement for c in components.all_components(doc)}
    code = asm.solve()
    fixed = grounded(doc)
    moved_ground = [c for c in fixed if c.Name in before and not c.Placement.isSame(before[c.Name], 1e-7)]
    bad = [j for j in js if not satisfied(j) or not within(j)]
    if code == 0 and not moved_ground and not bad:
        return ""
    for c in components.all_components(doc):       # undo: the solver's answer is wrong
        if c.Name in before and not c.Placement.isSame(before[c.Name], 1e-12):
            c.Placement = before[c.Name]
    names = ", ".join(j.Label for j in bad) or "the joints"
    return "These joints can't all be satisfied: %s. Edit or delete one of them." % names


def update(doc):
    """After every regeneration: each joint on or off by its timeline step, origins from today's
    geometry, a joint just switched on snapped into place again, then solve and check."""
    if components.root(doc) is None:
        return ""
    for step in [o for o in model.items(doc) if _is_step(o) and joint_of(o) is None]:
        model.remove(doc, step)                  # its joint was deleted elsewhere
    js = all_joints(doc)
    for j in js:
        if step_of(j) is None:                   # made before joints had steps
            add_step(j, len(model.items(doc)))
    back_on = []
    for j in js:
        off = not is_on(j)
        if j.Suppressed != off:
            j.Suppressed = off
            if not off:
                back_on.append(j)
        if not off:
            write(j)
    doc.recompute()
    for j in back_on:
        o1, o2 = origins(j)
        if not j.KovacStatus and o2.comp not in grounded(doc):
            o2.comp.Placement = o1.comp.Placement.multiply(j.Placement1).multiply(j.Placement2.inverse())
    msg = solve(doc)
    for j in js:
        step = step_of(j)
        if step is not None and step.Status != j.KovacStatus:
            step.Status = j.KovacStatus
    return msg


def drag(doc, comp, placement):
    """Try a new placement for a component and let the joints follow; returns True if the result
    holds (else everything goes back)."""
    if comp in grounded(doc):
        return False
    old = comp.Placement
    comp.Placement = placement
    if solve(doc):
        comp.Placement = old
        solve(doc)
        return False
    return True


def degrees_of_freedom(kind):
    """(translations, rotations) a joint type leaves free; for the panel's help text."""
    return {"Rigid": (0, 0), "Revolute": (0, 1), "Slider": (1, 0), "Cylindrical": (1, 1),
            "Ball": (0, 3), "Planar": (2, 1)}[kind]

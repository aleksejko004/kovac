# SPDX-License-Identifier: LGPL-2.1-or-later
"""ADR-0004 prototype: components and joints on Kovač bodies.

Run headless:  py tools/fc.py cmd prototypes/adr0004_assembly.py  [writes prototypes/adr0004_results.json]

E1 frames:    a Kovač body inside an App::Part component: the history still computes in the
              component's own coordinates, the component's Placement moves what is shown.
E2 instances: an App::Link to a component shows the same bodies elsewhere and follows edits;
              a pick through the link resolves to the real Kovač body.
E3 joints:    a plate (one history: extrude, then a cut for two holes) and a pin component.
              Pin and a linked second pin are jointed (Revolute) into the holes. Then upstream
              edits: holes move and grow, a hole is added before them, a fillet is inserted
              upstream. After each edit the pin must sit in its hole (or the joint must say it
              is broken). Two variants: (a) FreeCAD's joint as is (element names like Edge12),
              (b) Kovač joint origins: a topo reference + snap kind, resolved at every
              regeneration and written into the joint (Detach1/2 = FreeCAD doesn't recompute).
E4 solve time for chains of 5 / 20 / 50 linked components (KOVAC_CHAIN=5,20 runs only E4 at
              those sizes), each solve checked by Kovač: ground unmoved, joint frames together.
Findings are written up in docs/adr/0004-components-and-joints.md.
"""
import json
import math
import os
import statistics
import sys
import time

import FreeCAD as App
import Part
import Sketcher

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))
import JointObject                                                    # noqa: E402
from helpers import feature, rect, sketch                            # noqa: E402
from kovac import features, model, modify, topo                      # noqa: E402

V = App.Vector
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "adr0004_results.json")
REVOLUTE = JointObject.JointTypes.index("Revolute")
results = {}


def log(*a):
    App.Console.PrintMessage(" ".join(str(x) for x in a) + "\n")


# ---------------------------------------------------------------- Kovač side: joint origins

def frame(state, ref, snap):
    """Joint frame (Placement, body coordinates) for a Kovač reference + snap kind."""
    body, el = topo.element(state, ref)
    if snap == "centre":                      # circle/arc edge: centre, axis = Z
        c = el.Curve
        z = c.Axis
        return App.Placement(c.Center, App.Rotation(V(0, 0, 1), z)), topo.resolve(ref, state)
    raise ValueError(snap)


class Origin:
    """What a Kovač joint stores for one side: the component that moves, a reference into one of
    its bodies, a snap kind. (FreeCAD 1.1 joints hold [moving component, ["Body.Edge3", ...]].)"""

    def __init__(self, comp, body, element, snap="centre"):
        self.comp, self.body, self.snap = comp, body, snap
        self.ref = topo.dumps(topo.make_ref(model.state_of(body.Tip), body.BodyId, element))

    def write(self, joint, i):
        """Resolve today's element and frame, write both into the FreeCAD joint."""
        state = model.state_of(self.body.Tip)
        plc, name = frame(state, self.ref, self.snap)
        sub = "%s.%s" % (self.body.Name, name)
        setattr(joint, "Reference%d" % i, [self.comp, [sub, sub]])
        setattr(joint, "Placement%d" % i, plc)


def global_tip(body):
    """A body's Tip as a global-scope link: a component (GeoFeatureGroup) pulls in everything its
    members link to with local scope, which would drag the whole history inside it."""
    tip = body.Tip
    body.removeProperty("Tip")
    body.addProperty("App::PropertyLinkGlobal", "Tip", "Kovac", "", 4)
    body.Tip = tip


# ---------------------------------------------------------------- the test design

HOLES = [(15, 20, 5), (45, 20, 5)]


def build(doc, kovac):
    plate_sk = sketch(doc, rect(0, 0, 60, 40), name="PlateSketch")
    plate = feature(doc, features.Extrude, Profile=plate_sk, Length=10)
    hole_sks = []
    for k, (x, y, r) in enumerate(HOLES):
        hole_sks.append(sketch(doc, [("circle", (x, y), r)], name="HoleSketch%d" % k))
        hole_sks[-1].addConstraint(Sketcher.Constraint("Radius", 0, r))
        hole_sks[-1].addConstraint(Sketcher.Constraint("DistanceX", -1, 1, 0, 3, x))
        hole_sks[-1].addConstraint(Sketcher.Constraint("DistanceY", -1, 1, 0, 3, y))
        feature(doc, features.Extrude, Profile=hole_sks[-1], Length=10, Operation="Cut")
    pin_sk = sketch(doc, [("circle", (200, 0), 4.5)], name="PinSketch")
    feature(doc, features.Extrude, Profile=pin_sk, Length=30)
    bodies = [b for b in model.bodies(doc) if not b.Shape.isNull()]
    plate_body = next(b for b in bodies if b.Shape.Volume > 20000)
    pin_body = next(b for b in bodies if b is not plate_body)

    asm = doc.addObject("Assembly::AssemblyObject", "Assembly")
    joints = asm.newObject("Assembly::JointGroup", "Joints")
    comp_a = asm.newObject("App::Part", "Plate")
    comp_b = asm.newObject("App::Part", "Pin")
    for b in (plate_body, pin_body):
        global_tip(b)
    comp_a.addObject(plate_body)
    comp_b.addObject(pin_body)
    assert comp_a.Group == [plate_body] and comp_b.Group == [pin_body], (comp_a.Group, comp_b.Group)
    pin2 = asm.newObject("App::Link", "Pin2")
    pin2.LinkedObject = comp_b
    pin2.Placement = App.Placement(V(0, 80, 0), App.Rotation())
    doc.recompute()

    ground = joints.newObject("App::FeaturePython", "Ground")
    JointObject.GroundedJoint(ground, comp_a)

    hole_edges = [top_circle(plate_body.Shape, x, y, r, 10) for x, y, r in HOLES]
    pin_edge = top_circle(pin_body.Shape, 200, 0, 4.5, 0)
    made = []
    for k, moving in enumerate([comp_b, pin2]):
        j = joints.newObject("App::FeaturePython", "Revolute%d" % k)
        JointObject.Joint(j, REVOLUTE)
        if kovac:
            j.Detach1 = j.Detach2 = True
            o1 = Origin(comp_a, plate_body, hole_edges[k])
            o2 = Origin(moving, pin_body, pin_edge)
            o1.write(j, 1)
            o2.write(j, 2)
            made.append((j, o1, o2))
        else:
            j.Proxy.setJointConnectors(j, [
                [comp_a, ["%s.%s" % (plate_body.Name, hole_edges[k])] * 2],
                [moving, ["%s.%s" % (pin_body.Name, pin_edge)] * 2]])
            made.append((j, None, None))
    asm.solve()
    return dict(asm=asm, plate=plate_body, pin=pin_body, comp_b=comp_b, pin2=pin2, joints=made,
                hole_sks=hole_sks, plate_feature=plate)


def top_circle(shape, x, y, r, z):
    for i, e in enumerate(shape.Edges, 1):
        c = e.Curve
        if isinstance(c, Part.Circle) and abs(c.Radius - r) < 1e-6 and (c.Center - V(x, y, z)).Length < 1e-6:
            return "Edge%d" % i
    raise LookupError((x, y, r, z))


def pin_bottom(placement):
    """Pin bottom centre and axis in global coordinates for its component placement."""
    return placement.multVec(V(200, 0, 0)), placement.Rotation.multVec(V(0, 0, 1))


def regenerate(d, kovac):
    doc = d["asm"].Document
    model.commit(doc)
    if kovac:
        for j, o1, o2 in d["joints"]:
            try:
                o1.write(j, 1)
                o2.write(j, 2)
                j.Label2 = ""
            except topo.Broken as e:
                j.Label2 = "Missing reference: %s" % e
    doc.recompute()
    d["asm"].solve()


def check(d, holes, before=None):
    """Per pin: 'ok' (in its hole), 'wrong' (somewhere else, silently) or 'broken' (says so).
    A hole given as None no longer exists: the pin must say broken or stay where it was."""
    out = []
    for k, (moving, hole) in enumerate(zip([d["comp_b"], d["pin2"]], holes)):
        j = d["joints"][k][0]
        if j.Label2.startswith("Missing") or "Invalid" in j.State:
            out.append("broken: " + (j.Label2 or "FreeCAD marks the joint invalid"))
            continue
        if hole is None:
            stayed = before is not None and moving.Placement.isSame(before[k], 1e-6)
            out.append("stayed (not flagged)" if stayed else "wrong: moved to %s" % moving.Placement.Base)
            continue
        x, y, _r = hole
        p, axis = pin_bottom(moving.Placement)
        ok = (p - V(x, y, 10)).Length < 1e-4 and abs(abs(axis.z) - 1) < 1e-6
        names = (j.Reference1[1][0], j.Reference2[1][0]) if j.Reference1 else None
        out.append(("ok " if ok else "wrong (%.1f, %.1f, %.1f) " % (p.x, p.y, p.z)) + str(names))
    return out


def set_holes(d, holes, redraw=False):
    """Edit as a user does (drag the circle, change its radius dimension), or redraw it."""
    for sk, hole in zip(d["hole_sks"], holes):
        if hole is None:
            continue
        x, y, r = hole
        if redraw:
            sk.deleteAllGeometry()
            sk.addGeometry(Part.Circle(V(x, y, 0), V(0, 0, 1), r))
        else:
            for k, v in enumerate((r, x, y)):
                sk.setDatum(k, App.Units.Quantity("%g mm" % v))


MOVED = [(18, 22, 6), (42, 18, 7)]
EDITS = [
    ("holes move and grow", MOVED, None),
    ("a hole inserted upstream (faces renumber)", MOVED, "hole"),
    ("fillet inserted upstream", MOVED, "fillet"),
    ("saved, reopened, holes moved again", [(16, 21, 5), (44, 19, 6)], "reopen"),
    ("first hole's cut deleted", [None, (44, 19, 6)], "remove"),
    ("second hole deleted and drawn again elsewhere", [None, (40, 25, 5)], "redraw"),
]


def e3():
    out = {}
    for variant, kovac in (("freecad", False), ("kovac", True)):
        doc = App.newDocument("E3" + variant)
        d = build(doc, kovac)
        rows = [("as built", check(d, HOLES))]
        for name, holes, extra in EDITS:
            before = [d["comp_b"].Placement, d["pin2"].Placement]
            if extra == "reopen":
                doc, d = reopen(doc, d)
            if extra == "remove":
                cut = next(o for o in model.items(doc) if getattr(o, "Profile", None) == d["hole_sks"][0])
                model.remove(doc, cut)
            else:
                set_holes(d, holes, extra == "redraw")
            idx = model.items(doc).index(d["plate_feature"]) + 1
            if extra == "hole":
                sk = doc.addObject("Sketcher::SketchObject", "Extra")
                sk.addGeometry(Part.Circle(V(5, 5, 0), V(0, 0, 1), 2))
                model.insert(doc, sk, idx)
                model.create(doc, features.Extrude, index=idx + 1, Profile=sk, Length=10, Operation="Cut")
            if extra == "fillet":     # upstream of the hole cut: insert after the plate extrude
                b = d["plate"]
                st = model.state_of(b.Tip)
                e = next(i for i, ed in enumerate(b.Shape.Edges, 1)
                         if abs(ed.Vertexes[0].Point.x - 60) < 1e-6 and abs(ed.Vertexes[0].Point.y) < 1e-6
                         and abs(ed.Vertexes[-1].Point.x - 60) < 1e-6 and abs(ed.Vertexes[-1].Point.y) < 1e-6)
                ref = topo.dumps(topo.make_ref(st, b.BodyId, "Edge%d" % e))
                model.create(doc, modify.Fillet, index=idx, Edges=[ref], Radius=3)
            regenerate(d, kovac)
            rows.append((name, check(d, holes, before)))
        out[variant] = rows
        for r in rows:
            log(variant, r)
        App.closeDocument(doc.Name)
    results["E3"] = out


def reopen(doc, d):
    """Save, close, open again; find everything by name (Kovač origins too)."""
    path = os.path.join(App.getUserAppDataDir(), "adr0004_%s.FCStd" % doc.Name)
    doc.saveAs(path)
    names = {k: v.Name for k, v in d.items() if hasattr(v, "Name")}
    hole_names = [sk.Name for sk in d["hole_sks"]]
    jn = [(j.Name, o1 and (o1.comp.Name, o1.body.Name, o1.ref, o1.snap), o2 and (o2.comp.Name, o2.body.Name, o2.ref, o2.snap))
          for j, o1, o2 in d["joints"]]
    App.closeDocument(doc.Name)
    doc = App.openDocument(path)
    d = {k: doc.getObject(n) for k, n in names.items()}
    d["hole_sks"] = [doc.getObject(n) for n in hole_names]

    def origin(t):
        if t is None:
            return None
        o = Origin.__new__(Origin)
        o.comp, o.body, o.ref, o.snap = doc.getObject(t[0]), doc.getObject(t[1]), t[2], t[3]
        return o
    d["joints"] = [(doc.getObject(n), origin(a), origin(b)) for n, a, b in jn]
    return doc, d


# ---------------------------------------------------------------- E1, E2

def e1_e2():
    doc = App.newDocument("E1")
    d = build(doc, True)
    comp_b, pin = d["comp_b"], d["pin"]
    local = pin.Shape.BoundBox
    comp_b.Placement = App.Placement(V(0, 0, 50), App.Rotation())
    doc.recompute()
    glob = Part.getShape(d["asm"], "Pin.%s." % pin.Name).BoundBox
    feature(doc, modify.Fillet, Edges=[d["joints"][0][2].ref], Radius=1)   # a feature on the moved body
    r = {"local_unchanged": abs(pin.Shape.BoundBox.ZMin - local.ZMin) < 1e-9 and abs(local.ZMin) < 1e-9,
         "shown_moved": abs(glob.ZMin - (comp_b.Placement.Base.z + local.ZMin)) < 1e-6,
         "feature_in_moved_component": pin.Shape.isValid() and len(pin.Shape.Faces) == 4}
    # E2: the link shows the same (now filleted) pin, and a pick through it finds the body
    link_shape = Part.getShape(d["pin2"])
    sub = d["pin2"].getSubObject("%s.Face1" % pin.Name, 1)
    r2 = {"link_follows_edit": abs(link_shape.Volume - pin.Shape.Volume) < 1e-6,
          "link_placed": link_shape.BoundBox.isInside(pin.Shape.transformGeometry(d["pin2"].Placement.toMatrix()).BoundBox.Center),
          "pick_through_link_is_body": sub is pin,
          "pick_ref_through_link": model.pick_ref(sub, "Face1") is not None}
    log("E1", r)
    log("E2", r2)
    results["E1"], results["E2"] = r, r2
    App.closeDocument(doc.Name)


# ---------------------------------------------------------------- E4

N_CHAIN = [int(x) for x in os.environ.get("KOVAC_CHAIN", "5,20,50").split(",")]


def verify(ground, ground_before, joints):
    """Kovač's own check after a solve (the solver can report success on a wrong answer): the
    grounded component didn't move and each joint's two frames meet (origins together, Z axes
    lined up; Fixed also X)."""
    if not ground.Placement.isSame(ground_before, 1e-7):
        return False
    for j, o1, o2 in joints:
        a = o1.comp.Placement.multiply(j.Placement1)
        b = o2.comp.Placement.multiply(j.Placement2)
        za, zb = a.Rotation.multVec(V(0, 0, 1)), b.Rotation.multVec(V(0, 0, 1))
        if (a.Base - b.Base).Length > 1e-5 or za.cross(zb).Length > 1e-6 or za.dot(zb) < 0:
            return False
        if j.JointType == "Fixed" and a.Rotation.multVec(V(1, 0, 0)).cross(b.Rotation.multVec(V(1, 0, 0))).Length > 1e-6:
            return False
    return True


def chain(n, joint_type, tilt, preplace=False):
    """n linked copies of one component stacked by joints; returns timings and checks."""
    doc = App.newDocument("E4")
    sk = sketch(doc, [("circle", (0, 0), 4)], name="S")
    feature(doc, features.Extrude, Profile=sk, Length=20)
    body = model.bodies(doc)[0]
    asm = doc.addObject("Assembly::AssemblyObject", "Assembly")
    jg = asm.newObject("Assembly::JointGroup", "Joints")
    template = asm.newObject("App::Part", "Template")     # the definition; instances are links
    global_tip(body)
    template.addObject(body)
    top, bottom = top_circle(body.Shape, 0, 0, 4, 20), top_circle(body.Shape, 0, 0, 4, 0)
    comps = []
    for i in range(n):
        link = asm.newObject("App::Link", "C%d" % i)
        link.LinkedObject = template
        link.Placement = App.Placement(V(30 * i, 0, 0), App.Rotation(V(1, 0, 0), tilt * i))
        comps.append(link)
    JointObject.GroundedJoint(jg.newObject("App::FeaturePython", "Ground"), comps[0])
    joints = []
    for i in range(1, n):
        j = jg.newObject("App::FeaturePython", "J%d" % i)
        JointObject.Joint(j, JointObject.JointTypes.index(joint_type))
        j.Detach1 = j.Detach2 = True
        joints.append((j, Origin(comps[i - 1], body, top), Origin(comps[i], body, bottom)))
    doc.recompute()
    t0 = time.perf_counter()
    for j, o1, o2 in joints:
        o1.write(j, 1)
        o2.write(j, 2)
    write_ms = (time.perf_counter() - t0) * 1000
    if preplace:      # what the Joint command does when a joint is made: snap the part into place
        for j, o1, o2 in joints:
            o2.comp.Placement = o1.comp.Placement.multiply(j.Placement1).multiply(j.Placement2.inverse())
    ground0 = comps[0].Placement
    t0 = time.perf_counter()
    code = asm.solve()
    first_ms = (time.perf_counter() - t0) * 1000
    first_ok = code == 0 and verify(comps[0], ground0, joints)
    times, drag_ok = [], True
    for k in range(10):                    # a drag: nudge the free end, solve, as each frame would
        pl = comps[-1].Placement
        pl.Base = pl.Base + V(0.5, 0, 0)
        comps[-1].Placement = pl
        t0 = time.perf_counter()
        code = asm.solve()
        times.append((time.perf_counter() - t0) * 1000)
        drag_ok = drag_ok and code == 0 and verify(comps[0], ground0, joints)
    App.closeDocument(doc.Name)
    return {"first_solve_ms": round(first_ms, 1), "first_solve_verified": first_ok,
            "drag_solve_ms_median": round(statistics.median(times), 1), "drag_solve_ms_max": round(max(times), 1),
            "drag_verified": drag_ok, "write_origins_ms": round(write_ms, 1)}


def e4():
    out = {}
    for joint_type, tilt, pre in (("Fixed", 0, False), ("Revolute", 0, False), ("Revolute", 10, False),
                                  ("Revolute", 10, True)):
        for n in N_CHAIN:
            key = "%s, %d components, start %s" % (joint_type, n, "snapped into place when jointed" if pre else
                                                     "tilted 10° each" if tilt else "untilted")
            out[key] = chain(n, joint_type, tilt, pre)
            log("E4", key, out[key])
    results["E4"] = out


try:
    if "KOVAC_CHAIN" not in os.environ:
        e1_e2()
        e3()
    e4()
except Exception:
    import traceback
    log(traceback.format_exc())
    raise
with open(OUT, "w") as f:
    json.dump(results, f, indent=1)
log("written", OUT)

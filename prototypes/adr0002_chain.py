# SPDX-License-Identifier: LGPL-2.1-or-later
"""ADR-0002 prototype: one "sketch -> extrude -> fillet -> change sketch" chain on two
candidate body models, compared on toponaming robustness, undo and regeneration time.

Run headless:  FreeCADCmd prototypes/adr0002_chain.py  [writes prototypes/adr0002_results.json]

(a) PartDesign: Body + Sketch + Pad + Fillet(Base=(Pad, edge))
(b) Part:       Sketch + Part::Extrusion + Part::Fillet(Edges=[(index, r, r)])

The fillet always targets the vertical edge at sketch corner (40, 20). After every sketch
change the fillet must still sit at that corner (cylinder axis at corner - r) or fail
loudly. "Silently wrong" = valid shape, fillet somewhere else.
"""
import json
import math
import os
import time

import FreeCAD as App
import Part
import Sketcher

R = 3.0
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "adr0002_results.json")


def poly(sk, pts):
    """Closed polyline with coincident constraints; replaces all geometry in the sketch."""
    sk.deleteAllGeometry()
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        sk.addGeometry(Part.LineSegment(App.Vector(*a, 0), App.Vector(*b, 0)))
    for i in range(n):
        sk.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % n, 1))


RECT = [(0, 0), (40, 0), (40, 20), (0, 20)]
V = App.Vector


def chain(sk, pts, first, last):
    """Append a polyline from first geo end -> pts -> last geo start, with coincidences."""
    ids = []
    for a, b in zip(pts, pts[1:]):
        ids.append(sk.addGeometry(Part.LineSegment(V(*a, 0), V(*b, 0))))
    for a, b in zip([first] + ids, ids + [last]):
        sk.addConstraint(Sketcher.Constraint("Coincident", a, 2, b, 1))


def resize(sk):  # drag the right edge +10 mm; neighbours stretch (same geometry ids)
    sk.moveGeometry(1, 0, V(10, 0, 0), 1)


def notch_upstream(sk):  # trim bottom edge, insert a notch: adds faces before the filleted edge
    sk.delConstraint(0)
    sk.moveGeometry(0, 2, V(10, 0, 0))
    chain(sk, [(10, 0), (10, 5), (20, 5), (20, 0), (40, 0)], 0, 1)


def extra_side_face(sk):  # split the top edge: the extrude gains a side face next to the fillet
    sk.delConstraint(2)
    sk.moveGeometry(2, 2, V(25, 28, 0))
    chain(sk, [(25, 28), (0, 20)], 2, 3)


def sketch_redrawn(sk):  # user deletes everything and redraws the same rectangle: new geometry tags
    poly(sk, RECT)


def extrude_length(sk):  # not a sketch edit: the extrude distance 10 -> 12 (filleted edge gets longer)
    ext = [o for o in sk.InList if o.TypeId in ("PartDesign::Pad", "Part::Extrusion")][0]
    if hasattr(ext, "Length"):
        ext.Length = 12
    else:
        ext.Dir = App.Vector(0, 0, 12)


CHANGES = {  # name: (edit, corner the fillet must follow)
    "resize": (resize, (50, 20)),
    "notch_upstream": (notch_upstream, (40, 20)),
    "extra_side_face": (extra_side_face, (40, 20)),
    "sketch_redrawn": (sketch_redrawn, (40, 20)),
    "extrude_length": (extrude_length, (40, 20)),
}


def corner_edge(shape, corner):
    for i, e in enumerate(shape.Edges, 1):
        a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
        if abs(a.x - b.x) < 1e-6 and abs(a.y - b.y) < 1e-6 and abs(a.x - corner[0]) < 1e-6 and abs(a.y - corner[1]) < 1e-6:
            return i
    raise RuntimeError("no vertical edge at %s" % (corner,))


def fillet_at(shape, corner):
    """True if a radius-R cylindrical face lies at the corner (all its vertices within 2.5 R in XY)."""
    for f in shape.Faces:
        if isinstance(f.Surface, Part.Cylinder) and abs(f.Surface.Radius - R) < 1e-6:
            if all(math.hypot(v.Point.x - corner[0], v.Point.y - corner[1]) < 2.5 * R for v in f.Vertexes):
                return True
    return False


def build_partdesign(doc):
    body = doc.addObject("PartDesign::Body", "Body")
    sk = body.newObject("Sketcher::SketchObject", "Sketch")
    sk.AttachmentSupport = [(body.Origin.OriginFeatures[3], "")]  # XY plane
    sk.MapMode = "FlatFace"
    poly(sk, RECT)
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = sk
    pad.Length = 10
    doc.recompute()
    fil = body.newObject("PartDesign::Fillet", "Fillet")
    fil.Base = (pad, ["Edge%d" % corner_edge(pad.Shape, (40, 20))])
    fil.Radius = R
    doc.recompute()
    return sk, fil


def build_part(doc):
    sk = doc.addObject("Sketcher::SketchObject", "Sketch")
    poly(sk, RECT)
    ext = doc.addObject("Part::Extrusion", "Extrude")
    ext.Base = sk
    ext.Dir = App.Vector(0, 0, 10)
    ext.Solid = True
    doc.recompute()
    fil = doc.addObject("Part::Fillet", "Fillet")
    fil.Base = ext
    fil.Edges = [(corner_edge(ext.Shape, (40, 20)), R, R)]
    doc.recompute()
    return sk, fil


def run(model, build):
    rows = []
    for change, (edit, corner) in CHANGES.items():
        doc = App.newDocument("P_%s_%s" % (model, change))
        doc.UndoMode = 1
        sk, fil = build(doc)
        assert fil.Shape.isValid() and fillet_at(fil.Shape, (40, 20)), "baseline broken"
        vol0 = fil.Shape.Volume
        doc.openTransaction("change sketch")
        edit(sk)
        t0 = time.perf_counter()
        doc.recompute()
        regen_ms = (time.perf_counter() - t0) * 1000
        doc.commitTransaction()
        invalid = "Invalid" in fil.State or fil.Shape.isNull()
        error = fil.getStatusString() if invalid else ""
        ok = (not invalid) and fil.Shape.isValid() and fillet_at(fil.Shape, corner)
        verdict = "correct" if ok else ("error (loud)" if invalid else "SILENTLY WRONG")
        doc.undo()
        doc.recompute()
        undo_ok = abs(fil.Shape.Volume - vol0) < 1e-6 and fillet_at(fil.Shape, (40, 20))
        rows.append(dict(model=model, change=change, verdict=verdict, regen_ms=round(regen_ms, 2), undo_restores=undo_ok,
                         error=error))
        App.closeDocument(doc.Name)
    return rows


def regen_benchmark(build, n=20):
    """Median recompute of the whole chain after a dimension change (warm)."""
    doc = App.newDocument("Bench")
    sk, fil = build(doc)
    times = []
    for i in range(n):
        sk.moveGeometry(1, 0, V(1 if i % 2 else -1, 0, 0), 1)
        t0 = time.perf_counter()
        doc.recompute()
        times.append((time.perf_counter() - t0) * 1000)
    # ponytail: the fillet goes invalid after the first edit (see ADR-0002), so this times
    # sketch + extrude + a failing fillet, not a successful full chain.
    App.closeDocument(doc.Name)
    return round(sorted(times)[n // 2], 2)


results = run("partdesign", build_partdesign) + run("part", build_part)
bench = {"partdesign": regen_benchmark(build_partdesign), "part": regen_benchmark(build_part)}
json.dump({"freecad": App.Version()[:3], "rows": results, "median_regen_ms": bench}, open(OUT, "w"), indent=1)
for r in results:
    print("%-11s %-20s %-16s %7.2f ms  undo=%s" % (r["model"], r["change"], r["verdict"], r["regen_ms"], r["undo_restores"]))
print("median full-chain regen ms:", bench)

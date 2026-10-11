# SPDX-License-Identifier: LGPL-2.1-or-later
"""Builders shared by the model tests: sketches and features through the command layer."""
import FreeCAD as App
import Part
import Sketcher

from kovac import commands, model

V = App.Vector


def sketch(doc, geometry, placement=None, name="Sketch", constrain=True):
    """Sketch at placement (default XY) from [('line', a, b) | ('circle', c, r) | ('point', p)]."""
    sk = doc.addObject("Sketcher::SketchObject", name)
    if placement is not None:
        sk.Placement = placement
    lines = []
    for g in geometry:
        if g[0] == "line":
            lines.append(sk.addGeometry(Part.LineSegment(V(*g[1], 0), V(*g[2], 0))))
        elif g[0] == "circle":
            sk.addGeometry(Part.Circle(V(*g[1], 0), V(0, 0, 1), g[2]))
        elif g[0] == "point":
            sk.addGeometry(Part.Point(V(*g[1], 0)))
        elif g[0] == "arc":
            c, r, a0, a1 = g[1:]
            sk.addGeometry(Part.ArcOfCircle(Part.Circle(V(*c, 0), V(0, 0, 1), r), a0, a1))
    if constrain:   # close polylines drawn as consecutive lines
        for a, b in zip(lines, lines[1:] + lines[:1]):
            pa, pb = sk.Geometry[a].EndPoint, sk.Geometry[b].StartPoint
            if (pa - pb).Length < 1e-9:
                sk.addConstraint(Sketcher.Constraint("Coincident", a, 2, b, 1))
    model.insert(doc, sk)
    return sk


def rect(x0, y0, x1, y1):
    p = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return [("line", p[i], p[(i + 1) % 4]) for i in range(4)]


def feature(doc, proxy, name=None, **props):
    with commands.transaction(proxy.kind, doc):
        fp = model.create(doc, proxy, name, **props)
        model.commit(doc)
    return fp


def body_shape(doc, i=0):
    return [b for b in model.bodies(doc) if not b.Shape.isNull()][i].Shape


def live_bodies(doc):
    return [b for b in model.bodies(doc) if not b.Shape.isNull()]


def face_ref(doc, body, pred):
    """Reference to the first face of a body (KovacBody object) matching pred(face)."""
    from kovac import topo
    st = model.state_of(body.Tip)
    i = next(i for i, f in enumerate(body.Shape.Faces, 1) if pred(f))
    return topo.dumps(topo.make_ref(st, body.BodyId, "Face%d" % i))


def edge_ref(doc, body, pred):
    from kovac import topo
    st = model.state_of(body.Tip)
    i = next(i for i, e in enumerate(body.Shape.Edges, 1) if pred(e))
    return topo.dumps(topo.make_ref(st, body.BodyId, "Edge%d" % i))


def normal(f):
    return f.normalAt(*f.Surface.parameter(f.CenterOfMass))


def vertical_edge_at(x, y):
    def pred(e):
        a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
        return abs(a.x - x) < 1e-6 and abs(a.y - y) < 1e-6 and abs(b.x - x) < 1e-6 and abs(b.y - y) < 1e-6
    return pred

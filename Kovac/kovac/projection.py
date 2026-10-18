# SPDX-License-Identifier: LGPL-2.1-or-later
"""Edges projected into a sketch from a body (the sketcher's Projection and Carbon copy).

The sketcher links projected geometry to the object picked: a KovacBody, which always shows
the body as the history tip has it. Once the sketch is extruded, that body depends on the
extrude, which depends on the sketch, which depends on the body: a loop FreeCAD can't
recompute, so the sketch and everything after it stop updating.

Here every such link is moved to a BodyAt: a hidden object showing the body as it is at the
sketch's place in the history (the state of the feature before the sketch). Nothing after
the sketch can change it, so no loop forms, and later steps don't shift the projection.
The picked face, edge or point is found again in that shape by where it is (the body may
look different at the sketch's step when an earlier sketch is edited); geometry that only
exists after the sketch can't be projected and is taken out, with a message.
"""
import FreeCAD as App
import Part

from kovac import model, topo

TOL = 1e-6


class BodyAt:
    """One body as the history has it at a sketch's step (machinery, never shown)."""

    def __init__(self, fp):
        fp.Proxy = self
        fp.addProperty("App::PropertyLinkGlobal", "Previous", "Kovac", "state feature before the sketch", 4)
        fp.addProperty("App::PropertyString", "BodyId", "Kovac", "", 1)
        fp.addProperty("App::PropertyString", "ForSketch", "Kovac", "the sketch it serves (a name, not a link)", 4)

    def execute(self, fp):
        st = model.state_of(fp.Previous)
        fp.Shape = topo.baked(st[fp.BodyId].shape) if fp.BodyId in st else Part.Shape()

    def dumps(self):
        return None

    def loads(self, _state):
        return None


def is_body_at(o):
    return isinstance(getattr(o, "Proxy", None), BodyAt)


def before(sk):
    """The state feature just before sketch sk in the history (None at the start, or when sk
    isn't in the history)."""
    its = model.items(sk.Document)
    if sk not in its:
        return model.tip(sk.Document)
    for o in reversed(its[:its.index(sk)]):
        if model.is_feature(o) and o.Proxy.state_feature:
            return o
    return None


def _body_at(sk, body):
    doc = sk.Document
    for o in doc.Objects:
        if is_body_at(o) and o.ForSketch == sk.Name and o.BodyId == body.BodyId:
            return o
    from kovac import components
    o = doc.addObject("Part::FeaturePython", "BodyAt")
    BodyAt(o)
    o.BodyId, o.ForSketch, o.Previous = body.BodyId, sk.Name, before(sk)
    o.Label = "%s at %s" % (body.Label, sk.Label)
    components.adopt(o, components.holder(body))
    if App.GuiUp and o.ViewObject is not None:
        o.ViewObject.Visibility = False
    o.recompute()
    return o


def _element(shape, sub):
    try:
        return shape.getElement(sub)
    except Exception:
        return None


def _same_place(a, b):
    if a.ShapeType != b.ShapeType:
        return False
    if a.ShapeType == "Vertex":
        return (a.Point - b.Point).Length < TOL * 10
    if a.ShapeType == "Edge" and abs(a.Length - b.Length) > TOL * 10:
        return False
    if a.ShapeType == "Face" and abs(a.Area - b.Area) > TOL * 10:
        return False
    return (a.CenterOfMass - b.CenterOfMass).Length < TOL * 10


def find_again(old, new, sub):
    """The name in shape new of element sub of shape old, found by where it is; None if new
    has nothing there. The same name when it is the same element (the usual case)."""
    e = _element(old, sub)
    if e is None:
        return None
    same = _element(new, sub)
    if same is not None and _same_place(e, same):
        return sub
    kind = sub.rstrip("0123456789")
    pool = {"Face": new.Faces, "Edge": new.Edges, "Vertex": new.Vertexes}.get(kind, [])
    return next(("%s%d" % (kind, k) for k, x in enumerate(pool, 1) if _same_place(e, x)), None)


def _local(sk, at):
    """Matrix from at's shape coordinates to sketch sk's plane coordinates."""
    return sk.getGlobalPlacement().inverse().multiply(at.getGlobalPlacement()).toMatrix()


def _shows(element, m, drawn, flat=True):
    """True if element (moved by m into sketch coordinates) lies on what the sketch already
    shows as projected (drawn: shapes in sketch coordinates). Not flat: it must lie in the
    sketch plane itself (a box's top, not its bottom, for a sketch on the top)."""
    pts = [v.Point for v in element.Vertexes] + [e.valueAt((e.FirstParameter + e.LastParameter) / 2)
                                                  for e in element.Edges]
    for p in pts:
        q = m.multVec(p)
        if not flat and abs(q.z) > 1e-5:
            return False
        v = Part.Vertex(App.Vector(q.x, q.y, 0))
        if not any(v.distToShape(d)[0] < 1e-5 for d in drawn):
            return False
    return bool(pts)


def choose(sk, body, at, sub, drawn):
    """The element of the BodyAt to project for what was picked on the live body as sub: the
    one with that name when it is what the sketch shows, else the one in the same place, else
    any of that kind that the sketch shows. None if the body has nothing like it yet."""
    m = _local(sk, at)
    same = _element(at.Shape, sub)
    n = find_again(body.Shape, at.Shape, sub)
    if not drawn:
        return sub if same is not None else n
    kind = sub.rstrip("0123456789")
    pool = {"Face": at.Shape.Faces, "Edge": at.Shape.Edges, "Vertex": at.Shape.Vertexes}.get(kind, [])
    for flat in (False, True):          # in the sketch plane first, then anywhere it projects to
        if same is not None and _shows(same, m, drawn, flat):
            return sub
        if n is not None and _shows(_element(at.Shape, n), m, drawn, flat):
            return n
        hit = next(("%s%d" % (kind, k) for k, x in enumerate(pool, 1) if _shows(x, m, drawn, flat)), None)
        if hit:
            return hit
    return sub if same is not None else n


def project(sk, body, element):
    """Project element (a face, edge or point picked on body) into sketch sk, from the body at
    the sketch's step. Not part of the sketch's own shape: it is there to snap to and to bound
    the sketch's regions. sk must already be in the history."""
    at = _body_at(sk, body)
    n = find_again(body.Shape, at.Shape, element)
    if n is not None:
        sk.addExternal(at.Name, n)
    return n


def _ext(k):
    return -3 - k                   # geometry id of projected item k (after the two axes)


def _is_ext(g):
    return -2000 < g <= -3          # -1, -2: the axes; -2000: no geometry


def retarget(sk):
    """Move sketch sk's projections off live bodies onto BodyAt objects, with the sketcher's
    own calls: every projection is taken out and made again in the same order, and the
    constraints that used projected items are put back on the matching new items (matched by
    where they lie). Returns how many projected items were taken out for good (they exist
    only after the sketch's step)."""
    links = list(getattr(sk, "ExternalGeometry", []))
    if not any(isinstance(getattr(o, "Proxy", None), model.BodyProxy) for o, _ in links):
        return 0
    old = [g.toShape() for g in sk.ExternalGeo[2:]]
    drawn = [x for x in old if not x.isNull()]
    plan, dropped = [], 0
    for o, subs in links:
        for s in subs:
            if isinstance(getattr(o, "Proxy", None), model.BodyProxy):
                at = _body_at(sk, o)
                n = choose(sk, o, at, s, drawn) if s else s
                if n is None or (n and _element(at.Shape, n) is None):
                    dropped += 1
                    continue
                plan.append((at.Name, n))
            else:
                plan.append((o.Name, s))
    uses = [c for c in sk.Constraints if any(_is_ext(g) for g in (c.First, c.Second, c.Third))]
    for _ in range(len(links) + 1):
        if not sk.ExternalGeometry:
            break
        sk.delExternal(0)
    for name, sub in plan:
        sk.addExternal(name, sub)
    sk.recompute()
    new = [g.toShape() for g in sk.ExternalGeo[2:]]

    def moved(g):
        if not _is_ext(g):
            return g
        k = -3 - g
        if k >= len(old):
            return None
        return next((_ext(j) for j, x in enumerate(new) if _same_curve(old[k], x)), None)
    for c in uses:
        ids = [moved(g) for g in (c.First, c.Second, c.Third)]
        if None in ids:
            continue                # its projected item is gone
        c.First, c.Second, c.Third = ids
        try:
            sk.addConstraint(c)
        except Exception:
            pass
    return dropped


def _same_curve(a, b):
    if a.isNull() or b.isNull() or a.ShapeType != b.ShapeType:
        return False
    if a.ShapeType == "Vertex":
        return (a.Point - b.Point).Length < 1e-6
    return abs(a.Length - b.Length) < 1e-6 and a.distToShape(b)[0] < 1e-6 and \
        all(Part.Vertex(v.Point).distToShape(b)[0] < 1e-6 for v in a.Vertexes)


def sync(doc):
    """After a recompute: every sketch's projections sit on BodyAt objects at its own step;
    each BodyAt follows its sketch's step (the sketch may have moved in the timeline); unused
    ones go. Returns a message when projected items had to be taken out, else ""."""
    dropped = 0
    for sk in [o for o in doc.Objects if o.TypeId.startswith("Sketcher::")]:
        dropped += retarget(sk)
    used = {(o.Name, sk.Name) for sk in doc.Objects if sk.TypeId.startswith("Sketcher::")
            for o, _ in getattr(sk, "ExternalGeometry", []) if is_body_at(o)}
    for o in [x for x in doc.Objects if is_body_at(x)]:
        sk = doc.getObject(o.ForSketch)
        if (o.Name, o.ForSketch) not in used or sk is None:
            doc.removeObject(o.Name)
            continue
        b = before(sk)
        if o.Previous != b:
            o.Previous = b
    if dropped:
        return "%d projected item%s came from a later step and %s taken out of the sketch." % (
            dropped, "" if dropped == 1 else "s", "was" if dropped == 1 else "were")
    return ""

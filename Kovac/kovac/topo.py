# SPDX-License-Identifier: LGPL-2.1-or-later
"""Kovač topological naming (ADR-0002, ADR-0003).

Every face of every body carries a *tag*: a history-derived name such as
``Extrude001:s:3.0`` (side face swept from sketch geometry 3, piece 0) or
``Fillet002:f:<edge>``. The feature that creates a face names it; every later
operation hands tags on by matching each output face to the input face it lies on
(same underlying surface, point inside it). That matching only ever compares one
operation's input with its own output, so it is exact, and it never depends on
dimensions. Edges and vertices are named by the tags of the faces that meet there.

A reference stores those tags plus a geometric signature. Resolution accepts
exactly one match; anything else raises Broken with a plain-language reason. A
pick is never silently re-attached to different geometry.
"""
import hashlib
import json
import math

import FreeCAD as App
import Part

TOL = 1e-6
V = App.Vector


class Broken(Exception):
    """A reference that can no longer be resolved unambiguously."""

    def __init__(self, message, ref=None):
        super().__init__(message)
        self.ref = ref


class Body:
    """A tagged shape: one body's solid(s) plus one tag per face."""
    __slots__ = ("shape", "tags")

    def __init__(self, shape, tags):
        if len(tags) != len(shape.Faces):
            raise ValueError("tag count %d != face count %d" % (len(tags), len(shape.Faces)))
        self.shape, self.tags = shape, list(tags)

    def transformed(self, matrix_or_placement):
        m = matrix_or_placement.toMatrix() if isinstance(matrix_or_placement, App.Placement) else matrix_or_placement
        return Body(baked(self.shape, m), self.tags)      # face order survives a rigid transform


def baked(shape, matrix=None):
    """Copy with any location (and matrix) built into the geometry: FreeCAD resets a feature
    shape's location from its Placement, so body shapes must not rely on one."""
    s = shape.copy()
    m = s.Placement.toMatrix()
    if matrix is not None:
        m = matrix.multiply(m)
    s.Placement = App.Placement()
    s.transformShape(m, True)
    return s


# ---------------------------------------------------------------- surfaces

def _same_line(p1, d1, p2, d2, tol):
    if d1.cross(d2).Length > 1e-9:
        return False
    return (p2 - p1).cross(d1).Length / d1.Length < tol


def same_support(a, b, tol=TOL):
    """True if faces a and b lie on the same underlying surface."""
    sa, sb = a.Surface, b.Surface
    if type(sa) is not type(sb):
        return False
    if isinstance(sa, Part.Plane):
        n = sa.Axis
        return n.cross(sb.Axis).Length < 1e-9 and abs((sb.Position - sa.Position).dot(n)) < tol
    if isinstance(sa, Part.Cylinder):
        return abs(sa.Radius - sb.Radius) < tol and _same_line(sa.Center, sa.Axis, sb.Center, sb.Axis, tol)
    if isinstance(sa, Part.Cone):
        return (sa.Apex - sb.Apex).Length < tol and sa.Axis.cross(sb.Axis).Length < 1e-9 \
            and abs(sa.SemiAngle - sb.SemiAngle) < 1e-9
    if isinstance(sa, Part.Sphere):
        return (sa.Center - sb.Center).Length < tol and abs(sa.Radius - sb.Radius) < tol
    if isinstance(sa, Part.Toroid):
        return (sa.Center - sb.Center).Length < tol and sa.Axis.cross(sb.Axis).Length < 1e-9 \
            and abs(sa.MajorRadius - sb.MajorRadius) < tol and abs(sa.MinorRadius - sb.MinorRadius) < tol
    # free-form: three interior points of a must lie on b's surface
    for p in sample_points(a, 3):
        u, v = sb.parameter(p)
        if (sb.value(u, v) - p).Length > 10 * tol:
            return False
    return True


def sample_points(face, n=1):
    """Points strictly inside a face: its centre of mass when that lies on it (cheap, the
    common case), else centroids of its largest mesh triangles."""
    if n == 1:
        c = face.CenterOfMass
        if on_face(face, c):
            return [c]
    pts, tris = face.tessellate(max(face.BoundBox.DiagonalLength / 20.0, 1e-3))
    if not tris:
        return [face.CenterOfMass]
    ranked = sorted(tris, key=lambda t: -((pts[t[1]] - pts[t[0]]).cross(pts[t[2]] - pts[t[0]])).Length)
    return [(pts[a] + pts[b] + pts[c]) * (1.0 / 3) for a, b, c in ranked[:n]]


def on_face(face, p, tol=TOL):
    u, v = face.Surface.parameter(p)
    if (face.Surface.value(u, v) - p).Length > 10 * tol:
        return False
    return face.isPartOfDomain(u, v)


def inherit(shape, sources, generated=None):
    """Tags for shape.Faces: each face takes the tag of the source face it lies on
    (several hits: the smallest tag, so merged faces get a stable name); unmatched faces
    are named by generated(face) or by a geometry hash."""
    pool, kept = {}, {}
    for body in sources:
        for f, t in zip(body.shape.Faces, body.tags):
            pool.setdefault(type(f.Surface).__name__, []).append((f, t))
            kept.setdefault(f.hashCode(), []).append((f, t))
    tags = []
    for f in shape.Faces:
        same = [t for g, t in kept.get(f.hashCode(), []) if f.isSame(g)]
        if same:            # untouched by the operation: the kernel kept the very same face
            tags.append(min(same))
            continue
        p = sample_points(f)[0]
        hits = sorted(t for g, t in pool.get(type(f.Surface).__name__, []) if same_support(f, g) and on_face(g, p))
        tags.append(hits[0] if hits else (generated(f) if generated else None) or "new:" + geo_hash(f))
    return tags


def geo_hash(shape):
    """Short deterministic hash of rounded geometry (last-resort names)."""
    bb = shape.BoundBox
    key = "%s|%.4f|%.4f,%.4f,%.4f,%.4f,%.4f,%.4f" % (shape.ShapeType, shape.Area if shape.ShapeType == "Face" else shape.Length,
                                                     bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax)
    return hashlib.sha1(key.encode()).hexdigest()[:8]


# ---------------------------------------------------------------- element names

def adjacency(body):
    """{edge hash: sorted face tags}, {vertex hash: sorted face tags}"""
    edges, verts = {}, {}
    for f, t in zip(body.shape.Faces, body.tags):
        for e in f.Edges:
            edges.setdefault(e.hashCode(), set()).add(t)
        for v in f.Vertexes:
            verts.setdefault(v.hashCode(), set()).add(t)
    return ({k: sorted(s) for k, s in edges.items()}, {k: sorted(s) for k, s in verts.items()})


def _split(name):
    for kind in ("Face", "Edge", "Vertex"):
        if name.startswith(kind):
            return kind, int(name[len(kind):])
    raise ValueError("not an element name: %r" % name)


def _signature(kind, el):
    if kind == "Face":
        return {"type": type(el.Surface).__name__, "c": list(el.CenterOfMass), "a": el.Area}
    if kind == "Edge":
        mid = el.valueAt((el.FirstParameter + el.LastParameter) / 2)
        return {"type": type(el.Curve).__name__, "c": list(mid), "l": el.Length,
                "ends": [list(el.Vertexes[0].Point), list(el.Vertexes[-1].Point)]}
    return {"type": "Vertex", "c": list(el.Point)}


def make_ref(state, body_id, element):
    """Stable reference to element ('Face3', 'Edge7', 'Vertex2') of a body in state."""
    body = state[body_id]
    kind, i = _split(element)
    el = getattr(body.shape, kind + ("es" if kind == "Vertex" else "s"))[i - 1]
    if kind == "Face":
        tags = [body.tags[i - 1]]
    else:
        e_adj, v_adj = adjacency(body)
        tags = (e_adj if kind == "Edge" else v_adj).get(el.hashCode(), [])
    return {"b": body_id, "k": kind, "t": tags, "s": _signature(kind, el)}


def dumps(ref):
    return json.dumps(ref, sort_keys=True, separators=(",", ":"))


def loads(s):
    return json.loads(s) if isinstance(s, str) else s


def _elements(body, kind):
    return getattr(body.shape, kind + ("es" if kind == "Vertex" else "s"))


def _distance(sig, el, kind):
    c = V(*sig["c"])
    return (V(*_signature(kind, el)["c"]) - c).Length


def _exact(sig, el, kind):
    s2 = _signature(kind, el)
    if s2["type"] != sig["type"] or (V(*s2["c"]) - V(*sig["c"])).Length > 1e-6:
        return False
    if kind == "Edge":
        return abs(s2["l"] - sig["l"]) < 1e-6
    if kind == "Face":
        return abs(s2["a"] - sig["a"]) < 1e-6
    return True


def resolve(ref, state):
    """Element name ('Edge7') for a reference in state, or raise Broken."""
    ref = loads(ref)
    body = state.get(ref["b"])
    if body is None:
        raise Broken("the body it was on no longer exists", ref)
    kind, tags = ref["k"], ref["t"]
    els = _elements(body, kind)
    if kind == "Face":
        cands = [i for i, t in enumerate(body.tags) if [t] == tags]
    else:
        e_adj, v_adj = adjacency(body)
        adj = e_adj if kind == "Edge" else v_adj
        cands = [i for i, el in enumerate(els) if adj.get(el.hashCode()) == tags]
    if len(cands) > 1:   # split faces / repeated edges: nearest, and only if clearly nearest
        ranked = sorted(cands, key=lambda i: _distance(ref["s"], els[i], kind))
        d0, d1 = (_distance(ref["s"], els[i], kind) for i in ranked[:2])
        if d0 < 0.5 * d1 or d0 < TOL:
            cands = ranked[:1]
        else:
            raise Broken("it is ambiguous now (%d %s look the same)" % (len(cands), kind.lower() + "s"), ref)
    if not cands:   # tags gone: accept only geometry that is exactly unchanged
        cands = [i for i, el in enumerate(els) if _exact(ref["s"], el, kind)]
        if len(cands) != 1:
            raise Broken("the %s it was attached to is gone" % kind.lower(), ref)
    return "%s%d" % (kind, cands[0] + 1)


def element(state, ref):
    """(body, shape element) for a reference."""
    name = resolve(ref, state)
    body = state[loads(ref)["b"]]
    kind, i = _split(name)
    return body, _elements(body, kind)[i - 1]


def describe_tag(tag, doc=None):
    """Human words for a tag, e.g. 'Extrude 1 side face (sketch line 3)'."""
    parts = tag.split(":")
    owner = parts[0]
    if doc is not None and doc.getObject(owner) is not None:
        owner = doc.getObject(owner).Label
    role = {"s": "side face", "start": "start face", "end": "end face", "f": "fillet face", "c": "chamfer face",
            "w": "hole wall", "in": "inner wall", "p": "face", "new": "new face"}.get(parts[1] if len(parts) > 1 else "", "face")
    return "%s %s" % (owner, role)


def describe(ref, doc=None):
    ref = loads(ref)
    names = " and ".join(describe_tag(t, doc) for t in ref["t"]) or "unnamed geometry"
    return {"Face": "the face %s" % names, "Edge": "the edge between %s" % names,
            "Vertex": "the corner of %s" % names}[ref["k"]]


# ---------------------------------------------------------------- state (de)serialization

def pack(state):
    """(compound shape, json) for a state {body_id: Body} (ordered)."""
    ids = list(state)
    comp = Part.makeCompound([state[i].shape for i in ids]) if ids else Part.Shape()
    return comp, json.dumps({"order": ids, "tags": {i: state[i].tags for i in ids}}, separators=(",", ":"))


def unpack(shape, text):
    if not text:
        return {}
    data = json.loads(text)
    kids = shape.childShapes() if not shape.isNull() else []
    if len(kids) != len(data["order"]):
        raise ValueError("stored state does not match its shape")
    return {i: Body(k, data["tags"][i]) for i, k in zip(data["order"], kids)}


def angle_deg(a, b):
    return math.degrees(a.getAngle(b))

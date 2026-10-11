# SPDX-License-Identifier: LGPL-2.1-or-later
"""Selection logic: filters, tangent chains, window/crossing tests, saved selection sets.

Pure geometry/logic here (testable headless); event handling lives in navigation.py.
"""
import json

import FreeCAD as App

KINDS = ("body", "face", "edge", "vertex", "profile", "curve", "component", "joint", "reference")
REFERENCE_TYPES = ("App::Plane", "App::Line", "App::Point", "PartDesign::Plane", "PartDesign::Line",
                   "PartDesign::Point", "PartDesign::CoordinateSystem", "App::LocalCoordinateSystem")
META_SETS = "kovac.selsets"
TOL = 1e-6


def classify(obj, sub):
    """Kind of a pick: one of KINDS, or None for machinery we never expose."""
    tid = obj.TypeId
    element = sub.split(".")[-1] if sub else ""
    sketch = tid.startswith("Sketcher::")
    if element.startswith("Face"):
        return "face"
    if element.startswith("Edge"):
        return "curve" if sketch else "edge"
    if element.startswith("Vertex"):
        return "vertex"
    if sketch:
        return "profile"
    if tid == "App::Part":
        return "component"
    if tid.startswith("Assembly::Joint") or hasattr(obj, "JointType"):
        return "joint"
    if tid in REFERENCE_TYPES:
        return "reference"
    if tid == "App::Origin":
        return None
    return "body"


class Gate:
    """Selection gate for Gui.Selection.addSelectionGate: allows only the enabled kinds."""

    def __init__(self, kinds):
        self.kinds = set(kinds)

    def allow(self, doc, obj, sub):
        return classify(obj, sub) in self.kinds


# ---------------------------------------------------------------- tangent chains

def _parallel(a, b):
    return a.Length > TOL and b.Length > TOL and abs(abs(a.normalize().dot(b.normalize())) - 1) < 1e-6


def tangent_edges(shape, index):
    """1-based indices of the tangent-continuous edge chain (or loop) through Edge<index>."""
    import Part
    edges = shape.Edges
    todo, seen = [index], {index}
    while todo:
        e = edges[todo.pop() - 1]
        for v in e.Vertexes:
            t = e.tangentAt(e.parameterAt(v))
            for other in shape.ancestorsOfType(v, Part.Edge):
                j = next((k for k, x in enumerate(edges, 1) if x.isSame(other)), None)
                if j is None or j in seen or other.isSame(e) or other.Curve is None:
                    continue
                if _parallel(t, other.tangentAt(other.parameterAt(v))):
                    seen.add(j)
                    todo.append(j)
    return sorted(seen)


def _normal_at(face, p):
    u, v = face.Surface.parameter(p)
    return face.normalAt(u, v)


def tangent_faces(shape, index):
    """1-based indices of faces tangent-connected to Face<index> (smooth across shared edges)."""
    import Part
    faces = shape.Faces
    todo, seen = [index], {index}
    while todo:
        f = faces[todo.pop() - 1]
        for e in f.Edges:
            p = e.valueAt((e.FirstParameter + e.LastParameter) / 2)
            for other in shape.ancestorsOfType(e, Part.Face):
                j = next((k for k, x in enumerate(faces, 1) if x.isSame(other)), None)
                if j is None or j in seen:
                    continue
                if _parallel(_normal_at(f, p), _normal_at(other, p)):
                    seen.add(j)
                    todo.append(j)
    return sorted(seen)


# ---------------------------------------------------------------- window selection

def window_hit(points, rect, crossing):
    """points: projected 2D samples of one item; rect: (x0, y0, x1, y1).
    Window (left->right): every sample inside. Crossing (right->left): any sample inside.
    ponytail: crossing tests samples only, so a long edge that passes through the box
    between samples is missed; add segment/box intersection if users hit it."""
    x0, x1 = sorted((rect[0], rect[2]))
    y0, y1 = sorted((rect[1], rect[3]))
    inside = [x0 <= x <= x1 and y0 <= y <= y1 for x, y in points]
    return any(inside) if crossing else (bool(inside) and all(inside))


def samples(shape_or_element, n=12):
    """3D sample points that stand for an element in window selection."""
    s = shape_or_element
    if s.ShapeType == "Vertex":
        return [s.Point]
    if s.ShapeType == "Edge":
        return s.discretize(n)
    pts = []
    for e in s.Edges:
        pts += e.discretize(n)
    return pts or [v.Point for v in s.Vertexes]


# ---------------------------------------------------------------- selection sets

def save_set(doc, name, picks):
    """picks: [(object name, subelement)]"""
    meta = doc.Meta
    sets = json.loads(meta.get(META_SETS, "{}"))
    sets[name] = picks
    meta[META_SETS] = json.dumps(sets)
    doc.Meta = meta


def load_sets(doc):
    return json.loads(doc.Meta.get(META_SETS, "{}"))

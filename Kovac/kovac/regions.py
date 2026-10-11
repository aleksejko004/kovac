# SPDX-License-Identifier: LGPL-2.1-or-later
"""Sketch profiles: every closed region a sketch's curves enclose, individually pickable.

Curves are split where they cross (OCCT general fuse), dangling ends are pruned, and the
bounded faces of the resulting planar graph are traced by always turning to the next
half-edge clockwise from the one we arrived on (interior faces come out counter-clockwise).
Clockwise cycles become holes of the smallest region that contains them. Each region is
keyed by the curve pieces on its boundary ('<geometry id>.<piece>'), which survives edits
that move curves without changing which curves bound the region.
"""
import math

import FreeCAD as App
import Part

from kovac.topo import Broken, sample_points

V = App.Vector
TOL = 1e-7


class Region:
    __slots__ = ("face", "key", "point", "edge_keys", "pieces")

    def __init__(self, face, key, point, edge_keys, pieces=()):
        self.face, self.key, self.point, self.edge_keys = face, key, point, edge_keys
        self.pieces = list(pieces)     # [(boundary edge, piece key)] for naming swept side faces

    def __repr__(self):
        return "Region(%s, area=%.3f)" % (self.key, self.face.Area)


def sketch_curves(sketch):
    """[(edge in sketch-local coordinates, geometry id)] for non-construction curves."""
    out = []
    for i, g in enumerate(sketch.Geometry):
        if sketch.getConstruction(i) or isinstance(g, Part.Point):
            continue
        out.append((g.toShape(), sketch.getGeometryId(i)))
    return out


def sketch_points(sketch):
    """Global positions of non-construction sketch points (hole centres)."""
    pl = sketch.getGlobalPlacement()
    return [pl.multVec(V(g.X, g.Y, g.Z)) for i, g in enumerate(sketch.Geometry)
            if isinstance(g, Part.Point) and not sketch.getConstruction(i)]


def _pieces(curves):
    if not curves:
        return []
    edges = [e for e, _ in curves]
    if len(edges) == 1:
        split = [[edges[0]]]
    else:
        _, split = edges[0].generalFuse(edges[1:])
    out = []
    for (orig, key), parts in zip(curves, split):
        parts = [p for p in parts if p.ShapeType == "Edge"] or [orig]
        parts.sort(key=lambda p: orig.Curve.parameter(p.valueAt((p.FirstParameter + p.LastParameter) / 2)))
        out += [(p, "%s.%d" % (key, k)) for k, p in enumerate(parts)]
    return out


def _vkey(p):
    return (round(p.x / TOL) * TOL, round(p.y / TOL) * TOL)


def _angle(d):
    return math.atan2(d.y, d.x)


def _poly(halfedges):
    pts = []
    for e, fwd, _ in halfedges:
        ds = e.discretize(24)
        pts += ds if fwd else ds[::-1]
    return pts


def _area(pts):
    return 0.5 * sum(a.x * b.y - b.x * a.y for a, b in zip(pts, pts[1:] + pts[:1]))


def _inside(p, poly):
    c = False
    for a, b in zip(poly, poly[1:] + poly[:1]):
        if (a.y > p.y) != (b.y > p.y) and p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x:
            c = not c
    return c


def find(curves):
    """Regions of curves given in a local XY plane: [(edge, key)] -> [Region] (local coords)."""
    pieces = _pieces(curves)
    # half-edges: (edge, forward, key); outgoing direction at its start vertex
    out = {}
    for e, key in pieces:
        a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
        ta, tb = e.tangentAt(e.FirstParameter), e.tangentAt(e.LastParameter)
        out.setdefault(_vkey(a), []).append(((e, True, key), _angle(ta), _vkey(b)))
        out.setdefault(_vkey(b), []).append(((e, False, key), _angle(-tb), _vkey(a)))
    # prune dangling curves (vertices of degree 1), repeatedly
    changed = True
    while changed:
        changed = False
        for v, hs in list(out.items()):
            if len(hs) == 1:
                (e, fwd, key), _, w = hs[0]
                del out[v]
                out[w] = [h for h in out.get(w, []) if h[0][0] is not e]
                changed = True
    for hs in out.values():
        hs.sort(key=lambda h: h[1])
    def hid(h):
        return id(h[0][0]), h[0][1]

    used, cycles = set(), []
    for hs in out.values():
        for cur in hs:
            cycle = []
            while hid(cur) not in used:
                used.add(hid(cur))
                cycle.append(cur[0])
                e, fwd, _ = cur[0]
                at = out[cur[2]]
                twin = next(i for i, x in enumerate(at) if x[0][0] is e and x[0][1] != fwd)
                cur = at[twin - 1]          # next half-edge clockwise from the way back
            if cycle:
                cycles.append(cycle)
    polys = [_poly(c) for c in cycles]
    areas = [_area(p) for p in polys]
    outer = [i for i, a in enumerate(areas) if a > TOL]
    holes = {i: [] for i in outer}
    for j, a in enumerate(areas):
        if a >= -TOL:
            continue
        host = [i for i in outer if abs(areas[i]) > abs(a) + TOL and _inside(polys[j][0], polys[i])]
        if host:
            holes[min(host, key=lambda i: areas[i])].append(j)
    regions = []
    for i in outer:
        wires = [Part.Wire([e for e, _, _ in cycles[k]]) for k in [i] + holes[i]]
        face = Part.makeFace(wires, "Part::FaceMakerBullseye") if len(wires) > 1 else Part.Face(wires[0])
        pieces = [(e, key) for k in [i] + holes[i] for e, _, key in cycles[k]]
        keys = sorted({key for _, key in pieces})
        regions.append(Region(face, "|".join(keys), sample_points(face)[0], keys, pieces))
    regions.sort(key=lambda r: r.key)
    return regions


def of_sketch(sketch):
    """Regions of a sketch in global coordinates."""
    pl = sketch.getGlobalPlacement()
    out = []
    m = pl.toMatrix()

    def moved(shape):
        c = shape.copy()
        c.transformShape(m)
        return c
    for r in find(sketch_curves(sketch)):
        out.append(Region(moved(r.face), r.key, pl.multVec(r.point), r.edge_keys,
                          [(moved(e), k) for e, k in r.pieces]))
    return out


def default(regions):
    """Regions picked when the user picks none: the even-depth ones (a drawn hole stays a hole)."""
    def depth(r):
        return sum(1 for o in regions if o is not r and o.face.Area > r.face.Area
                   and Part.Face(o.face.OuterWire).isInside(r.point, 1e-7, True))
    return [r for r in regions if depth(r) % 2 == 0]


def pick(regions, keys, points=()):
    """Regions for stored keys; a key that vanished falls back to the region containing its
    stored sample point, but only if exactly one does."""
    by_key = {r.key: r for r in regions}
    chosen = []
    for k, p in zip(keys, list(points) + [None] * len(keys)):
        if k in by_key:
            chosen.append(by_key[k])
            continue
        hits = [r for r in regions if p is not None and r.face.isInside(V(*p), 1e-6, True)]
        if len(hits) != 1:
            raise Broken("a picked sketch region no longer exists")
        chosen.append(hits[0])
    return chosen

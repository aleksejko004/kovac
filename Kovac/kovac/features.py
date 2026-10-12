# SPDX-License-Identifier: LGPL-2.1-or-later
"""Shape-creating features: Extrude, Revolve, Sweep, Loft, Primitive, Hole.

Each builds a *tool* body with its faces named by construction (side faces after the sketch
curve piece that swept them, caps start/end, hole walls, ...) and combines it with the state
through model.apply_tool (Join / Cut / Intersect / New body, inferred when Auto).
"""
import math

import FreeCAD as App
import Part

from kovac import model, regions, topo

V = App.Vector
BIG = 1e5


# ---------------------------------------------------------------- shared helpers

def _sketch_regions(fp, sketch):
    found = regions.of_sketch(sketch, local=True)
    if not found:
        raise ValueError("%s has no closed profile. Close the outline in the sketch." % sketch.Label)
    if fp.Regions:
        return regions.pick(found, list(fp.Regions), [tuple(p) for p in getattr(fp, "RegionPoints", [])])
    auto = regions.default(found)
    # A sketch with one region (holes aside) has nothing to choose between, so picking none
    # is as good as picking it -- the common case stays a one-click extrude. More than one and
    # picking none is ambiguous: say so rather than silently combining every one of them.
    if len(auto) > 1:
        raise ValueError("%s has %d separate regions. Click the ones to use." % (sketch.Label, len(auto)))
    return auto


def profiles(fp, state):
    """([Region], profile normal) from the picked sketch regions or flat body faces."""
    if fp.Profile is not None:
        rs = _sketch_regions(fp, fp.Profile)
        n = regions.placement(fp.Profile, True).Rotation.multVec(V(0, 0, 1))
        return rs, n
    if not fp.ProfileFaces:
        raise ValueError("Pick a sketch profile or a flat face to extrude.")
    out, n = [], None
    for r in model.refs(fp, "ProfileFaces"):
        body, face = topo.element(state, r)
        if not isinstance(face.Surface, Part.Plane):
            raise ValueError("Only flat faces can be extruded.")
        e_adj, _ = topo.adjacency(body)
        pieces = [(e, "+".join(e_adj.get(e.hashCode(), []))) for e in face.Edges]
        n = face.normalAt(*face.Surface.parameter(face.CenterOfMass))
        out.append(regions.Region(face, "face", topo.sample_points(face)[0], [], pieces))
    return out, n


def _on(f, ref_face):
    return topo.same_support(f, ref_face) and f.distToShape(Part.Vertex(topo.sample_points(ref_face)[0]))[0] < 1e-6


def name_swept(fp, solid, pieces, start_face, end_face=None):
    """Tags for a swept solid: 'start' / 'end' caps, side faces after the profile piece lying
    on them, anything else (inner walls of a thin extrude) by geometry hash."""
    tags = []
    for f in solid.Faces:
        if _on(f, start_face):
            tags.append("%s:start" % fp.Name)
        elif end_face is not None and _on(f, end_face):
            tags.append("%s:end" % fp.Name)
        else:
            key = next((k for e, k in pieces
                        if f.distToShape(Part.Vertex(e.valueAt((e.FirstParameter + e.LastParameter) / 2)))[0] < 1e-6), None)
            if key is not None:
                tags.append("%s:s:%s" % (fp.Name, key))
            elif end_face is None and isinstance(f.Surface, Part.Plane):
                tags.append("%s:end" % fp.Name)
            else:
                tags.append("%s:s:x%s" % (fp.Name, topo.geo_hash(f)))
    return tags


def _hint(state, region_face, direction):
    """'Join' if the profile sits on a body face and we pull outward, 'Cut' if inward."""
    p = topo.sample_points(region_face)[0]
    for b in state.values():
        for f in b.shape.Faces:
            if isinstance(f.Surface, Part.Plane) and f.Surface.Axis.cross(direction).Length < 1e-9 and topo.on_face(f, p):
                n = f.normalAt(*f.Surface.parameter(p))
                return "Join" if n.dot(direction) > 0 else "Cut"
    return None


def _union(bodies, owner):
    """Fuse several tagged tool bodies (e.g. two regions) into one tagged body."""
    if len(bodies) == 1:
        return bodies[0]
    shape = bodies[0].shape.fuse([b.shape for b in bodies[1:]]).removeSplitter()
    return topo.Body(shape, topo.inherit(shape, bodies))


def _scene_size(state, extra):
    bb = App.BoundBox()
    for b in state.values():
        bb.add(b.shape.BoundBox)
    bb.add(extra.BoundBox)
    return max(bb.DiagonalLength, 1.0) * 2


# ---------------------------------------------------------------- Extrude

class Extrude(model.Feature):
    kind, icon = "Extrude", "extrude"

    def setup(self, fp):
        fp.addProperty("App::PropertyLinkGlobal", "Profile", "Profile", "sketch")
        fp.addProperty("App::PropertyStringList", "Regions", "Profile", "picked region keys (empty = automatic)")
        fp.addProperty("App::PropertyVectorList", "RegionPoints", "Profile", "a point inside each picked region", 4)
        fp.addProperty("App::PropertyStringList", "ProfileFaces", "Profile", "flat faces used as profile")
        fp.addProperty("App::PropertyEnumeration", "Extent", "Extent", "how far")
        fp.Extent = ["Distance", "Through all", "To face"]
        fp.addProperty("App::PropertyEnumeration", "Sides", "Extent", "")
        fp.Sides = ["One side", "Two sides", "Symmetric"]
        fp.addProperty("App::PropertyDistance", "Length", "Extent", "negative = other way").Length = 10
        fp.addProperty("App::PropertyDistance", "Length2", "Extent", "second side").Length2 = 10
        fp.addProperty("App::PropertyAngle", "Taper", "Extent", "draft of the side walls")
        fp.addProperty("App::PropertyDistance", "StartOffset", "Extent", "start this far from the profile")
        fp.addProperty("App::PropertyString", "ToFace", "Extent", "face reference for 'To face'")
        fp.addProperty("App::PropertyLength", "Thin", "Extent", "wall thickness, 0 = solid")
        model.add_operation_properties(fp)

    def tool(self, fp, state):
        rs, n = profiles(fp, state)
        L = fp.Length.Value
        if fp.Extent == "Through all":
            L = math.copysign(_scene_size(state, rs[0].face), L or 1)
        elif fp.Extent == "To face":
            _, target = topo.element(state, fp.ToFace)
            if not isinstance(target.Surface, Part.Plane):
                raise ValueError("'To face' needs a flat face.")
            L = (target.Surface.Position - rs[0].point).dot(n)
        if abs(L) < 1e-9 and fp.Sides == "One side":
            raise ValueError("The distance is zero.")
        d = n * (1 if L >= 0 else -1)
        L = abs(L)
        tools = []
        for r in rs:
            face = r.face
            if fp.Thin.Value > 0:   # a band along the outline
                inner = face.makeOffset2D(-fp.Thin.Value)
                face = Part.makeFace([face.OuterWire, inner.OuterWire], "Part::FaceMakerBullseye")
            start = n * fp.StartOffset.Value
            if fp.Sides == "One side":
                a, b = 0.0, L
            elif fp.Sides == "Symmetric":
                a, b = -L / 2, L / 2
            else:
                a, b = -abs(fp.Length2.Value), L
            base = face.copy()
            base.translate(start + d * a)
            if abs(fp.Taper.Value) > 1e-9:
                solid = self._tapered(base, d, b - a, fp.Taper.Value)
            else:
                solid = base.extrude(d * (b - a))
            pieces = [(self._moved(e, start), k) for e, k in r.pieces]
            end_face = base.copy()
            end_face.translate(d * (b - a))
            if abs(fp.Taper.Value) > 1e-9:
                end_face = None
            tools.append(topo.Body(solid, name_swept(fp, solid, pieces, base, end_face)))
        return _union(tools, fp), _hint(state, rs[0].face, d) if fp.StartOffset.Value == 0 and fp.Sides == "One side" else None

    @staticmethod
    def _moved(e, v):
        c = e.copy()
        c.translate(v)
        return c

    @staticmethod
    def _tapered(face, d, length, angle):
        inset = length * math.tan(math.radians(angle))
        top = face.makeOffset2D(-inset)
        top.translate(d * length)
        outer = Part.makeLoft([face.OuterWire, top.OuterWire], True, True)
        solid = outer
        for w0, w1 in zip(face.Wires[1:], top.Wires[1:]):
            solid = solid.cut(Part.makeLoft([w0, w1], True, True))
        return solid

    def apply(self, fp, state):
        tool, hint = self.tool(fp, state)
        return model.apply_tool(fp, state, tool, hint)


# ---------------------------------------------------------------- Revolve

def axis_line(fp, state, sketch=None):
    """(base, direction) from 'X'/'Y'/'Z', 'sketch:<geometry id>' or an edge reference."""
    a = fp.Axis
    if a in ("X", "Y", "Z"):
        return V(0, 0, 0), V(*[1 if c == a else 0 for c in "XYZ"])
    if a.startswith("sketch:"):
        gid = int(a.split(":")[1])
        sk = sketch or fp.Profile
        for i in range(len(sk.Geometry)):
            if sk.getGeometryId(i) == gid:
                g = sk.Geometry[i]
                pl = regions.placement(sk, True)
                p0, p1 = pl.multVec(g.StartPoint), pl.multVec(g.EndPoint)
                return p0, (p1 - p0).normalize()
        raise topo.Broken("the sketch line used as the axis was deleted")
    _, edge = topo.element(state, a)
    if not isinstance(edge.Curve, (Part.Line, Part.LineSegment)):
        raise ValueError("The axis must be a straight edge.")
    p0, p1 = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
    return p0, (p1 - p0).normalize()


class Revolve(model.Feature):
    kind, icon = "Revolve", "revolve"

    def setup(self, fp):
        fp.addProperty("App::PropertyLinkGlobal", "Profile", "Profile", "sketch")
        fp.addProperty("App::PropertyStringList", "Regions", "Profile", "")
        fp.addProperty("App::PropertyVectorList", "RegionPoints", "Profile", "", 4)
        fp.addProperty("App::PropertyStringList", "ProfileFaces", "Profile", "")
        fp.addProperty("App::PropertyString", "Axis", "Revolve", "X, Y, Z, sketch:<line id> or an edge").Axis = "Y"
        fp.addProperty("App::PropertyAngle", "Angle", "Revolve", "").Angle = 360
        fp.addProperty("App::PropertyBool", "Symmetric", "Revolve", "")
        model.add_operation_properties(fp)

    def tool(self, fp, state):
        rs, _ = profiles(fp, state)
        base, d = axis_line(fp, state)
        ang = fp.Angle.Value
        tools = []
        for r in rs:
            face = r.face.copy()
            pieces = list(r.pieces)
            if fp.Symmetric:
                face.rotate(base, d, -ang / 2)
                pieces = [(self._rot(e, base, d, -ang / 2), k) for e, k in pieces]
            solid = face.revolve(base, d, ang)
            end = self._rot(face, base, d, ang) if ang < 360 else None
            tools.append(topo.Body(solid, name_swept(fp, solid, pieces, face, end)))
        return _union(tools, fp), None

    @staticmethod
    def _rot(e, base, d, a):
        c = e.copy()
        c.rotate(base, d, a)
        return c

    def apply(self, fp, state):
        tool, hint = self.tool(fp, state)
        return model.apply_tool(fp, state, tool, hint)


# ---------------------------------------------------------------- Sweep / Loft

def sketch_wire(sketch):
    from kovac import curve3d
    if curve3d.is_curve(sketch):            # already in place, in 3D
        return Part.Wire(sketch.Shape.Edges)
    edges = [g.toShape() for i, g in enumerate(sketch.Geometry)
             if not sketch.getConstruction(i) and not isinstance(g, Part.Point)]
    w = Part.Wire(Part.__sortEdges__(edges))
    w.transformShape(regions.placement(sketch, True).toMatrix())
    return w


class Sweep(model.Feature):
    kind, icon = "Sweep", "sweep"

    def setup(self, fp):
        fp.addProperty("App::PropertyLinkGlobal", "Profile", "Profile", "sketch")
        fp.addProperty("App::PropertyStringList", "Regions", "Profile", "")
        fp.addProperty("App::PropertyVectorList", "RegionPoints", "Profile", "", 4)
        fp.addProperty("App::PropertyStringList", "ProfileFaces", "Profile", "")
        fp.addProperty("App::PropertyLinkGlobal", "Path", "Sweep", "sketch holding the path")
        fp.addProperty("App::PropertyStringList", "PathEdges", "Sweep", "edges used as the path")
        fp.addProperty("App::PropertyBool", "Frenet", "Sweep", "keep the profile's twist following the path").Frenet = True
        model.add_operation_properties(fp)

    def tool(self, fp, state):
        rs, _ = profiles(fp, state)
        if fp.Path is not None:
            path = sketch_wire(fp.Path)
        elif fp.PathEdges:
            path = Part.Wire(Part.__sortEdges__([topo.element(state, r)[1] for r in model.refs(fp, "PathEdges")]))
        else:
            raise ValueError("Pick a path for the sweep.")
        c = rs[0].face.CenterOfMass
        if (path.Vertexes[-1].Point - c).Length < (path.Vertexes[0].Point - c).Length:
            path.reverse()                      # sweep from the end the profile sits at
        tools = []
        for r in rs:
            solid = path.makePipeShell([r.face.OuterWire], True, fp.Frenet)
            if abs(solid.Volume) < 1e-9:
                raise ValueError("The profile lies along the path. Sketch it across the path's start.")
            for w in r.face.Wires[1:]:
                solid = solid.cut(path.makePipeShell([w], True, fp.Frenet))
            tools.append(topo.Body(solid, name_swept(fp, solid, r.pieces, r.face)))
        return _union(tools, fp), None

    def apply(self, fp, state):
        tool, hint = self.tool(fp, state)
        return model.apply_tool(fp, state, tool, hint)


class Loft(model.Feature):
    kind, icon = "Loft", "loft"

    def setup(self, fp):
        fp.addProperty("App::PropertyLinkListGlobal", "Sections", "Loft", "sketches, in order")
        fp.addProperty("App::PropertyBool", "Ruled", "Loft", "straight walls between sections")
        fp.addProperty("App::PropertyBool", "Closed", "Loft", "connect the last section back to the first")
        model.add_operation_properties(fp)

    def tool(self, fp, state):
        if len(fp.Sections) < 2:
            raise ValueError("A loft needs at least two sections.")
        firsts = [regions.default(regions.of_sketch(s, local=True)) for s in fp.Sections]
        if any(len(r) != 1 for r in firsts):
            raise ValueError("Each loft section must have exactly one closed profile.")
        wires = [r[0].face.OuterWire for r in firsts]
        solid = Part.makeLoft(wires, True, fp.Ruled, fp.Closed)
        end = None if fp.Closed else firsts[-1][0].face
        return topo.Body(solid, name_swept(fp, solid, firsts[0][0].pieces, firsts[0][0].face, end)), None

    def apply(self, fp, state):
        tool, hint = self.tool(fp, state)
        return model.apply_tool(fp, state, tool, hint)


# ---------------------------------------------------------------- Primitive

PRIMITIVES = ["Box", "Cylinder", "Sphere", "Cone", "Torus"]
_AXES = {(-1, 0, 0): "x-", (1, 0, 0): "x+", (0, -1, 0): "y-", (0, 1, 0): "y+", (0, 0, -1): "z-", (0, 0, 1): "z+"}


class Primitive(model.Feature):
    kind, icon = "Primitive", "box"

    def setup(self, fp):
        fp.addProperty("App::PropertyEnumeration", "PrimitiveType", "Primitive", "")
        fp.PrimitiveType = PRIMITIVES
        fp.addProperty("App::PropertyLength", "Length", "Primitive", "").Length = 20
        fp.addProperty("App::PropertyLength", "Width", "Primitive", "").Width = 20
        fp.addProperty("App::PropertyLength", "Height", "Primitive", "").Height = 20
        fp.addProperty("App::PropertyLength", "Radius", "Primitive", "").Radius = 10
        fp.addProperty("App::PropertyLength", "Radius2", "Primitive", "cone top / torus tube").Radius2 = 3
        fp.addProperty("App::PropertyPlacement", "Location", "Primitive", "where it sits")
        model.add_operation_properties(fp)

    def tool(self, fp, state):
        k = fp.PrimitiveType
        L, W, H, R, R2 = (q.Value for q in (fp.Length, fp.Width, fp.Height, fp.Radius, fp.Radius2))
        if k == "Box":
            s = Part.makeBox(L, W, H)
        elif k == "Cylinder":
            s = Part.makeCylinder(R, H)
        elif k == "Sphere":
            s = Part.makeSphere(R)
        elif k == "Cone":
            s = Part.makeCone(R, R2, H)
        else:
            s = Part.makeTorus(R, R2)
        tags = []
        for f in s.Faces:
            if isinstance(f.Surface, Part.Plane):
                n = f.normalAt(*f.Surface.parameter(f.CenterOfMass))
                tags.append("%s:p:%s" % (fp.Name, _AXES.get(tuple(round(c) for c in n), "cap")))
            else:
                tags.append("%s:p:side" % fp.Name)
        return topo.Body(topo.baked(s, fp.Location.toMatrix()), tags), None

    def apply(self, fp, state):
        tool, hint = self.tool(fp, state)
        return model.apply_tool(fp, state, tool, hint)


# ---------------------------------------------------------------- Hole (ISO metric)

# size: (pitch, tap drill, ISO 273 clearance fine/medium/coarse, counterbore Ø/depth for ISO 4762
# socket heads, countersink Ø for ISO 10642 90° heads). Sources: ISO 261/724, ISO 273, ISO 4762,
# ISO 10642 (see docs/PROVENANCE.md).
ISO_METRIC = {
    "M2": (0.4, 1.6, (2.2, 2.4, 2.6), (4.4, 2.4), 4.4),
    "M2.5": (0.45, 2.05, (2.7, 2.9, 3.1), (5.5, 2.9), 5.5),
    "M3": (0.5, 2.5, (3.2, 3.4, 3.6), (6.5, 3.4), 6.9),
    "M4": (0.7, 3.3, (4.3, 4.5, 4.8), (8.0, 4.4), 9.2),
    "M5": (0.8, 4.2, (5.3, 5.5, 5.8), (10.0, 5.4), 11.5),
    "M6": (1.0, 5.0, (6.4, 6.6, 7.0), (11.0, 6.4), 13.7),
    "M8": (1.25, 6.8, (8.4, 9.0, 10.0), (15.0, 8.6), 18.3),
    "M10": (1.5, 8.5, (10.5, 11.0, 12.0), (18.0, 10.6), 22.7),
    "M12": (1.75, 10.2, (13.0, 13.5, 14.5), (20.0, 12.6), 27.2),
    "M16": (2.0, 14.0, (17.0, 17.5, 18.5), (26.0, 16.6), 33.2),
    "M20": (2.5, 17.5, (21.0, 22.0, 24.0), (33.0, 20.6), 40.2),
}
HOLE_TYPES = ["Simple", "Counterbore", "Countersink", "Tapped"]
FITS = ["Close", "Normal", "Loose", "Custom"]


def hole_dims(fp):
    """(drill Ø, counterbore (Ø, depth) or None, countersink Ø or None, thread label or '')"""
    pitch, tap, clear, cb, cs = ISO_METRIC[fp.Size]
    if fp.HoleType == "Tapped":
        return tap, None, None, "%sx%g" % (fp.Size, pitch)
    d = fp.Diameter.Value if fp.Fit == "Custom" else clear[FITS.index(fp.Fit)]
    if fp.HoleType == "Counterbore":
        return d, (fp.CounterboreDiameter.Value or cb[0], fp.CounterboreDepth.Value or cb[1]), None, ""
    if fp.HoleType == "Countersink":
        return d, None, fp.CountersinkDiameter.Value or cs, ""
    return d, None, None, ""


class Hole(model.Feature):
    kind, icon = "Hole", "hole"

    def setup(self, fp):
        fp.addProperty("App::PropertyString", "Face", "Placement", "face the holes start on")
        fp.addProperty("App::PropertyLinkGlobal", "Points", "Placement", "sketch whose points are hole centres")
        fp.addProperty("App::PropertyVectorList", "Positions", "Placement", "hole centres (when no sketch)")
        fp.addProperty("App::PropertyEnumeration", "HoleType", "Hole", "")
        fp.HoleType = HOLE_TYPES
        fp.addProperty("App::PropertyEnumeration", "Size", "Hole", "ISO metric size")
        fp.Size = list(ISO_METRIC)
        fp.Size = "M5"
        fp.addProperty("App::PropertyEnumeration", "Fit", "Hole", "ISO 273 clearance")
        fp.Fit = FITS
        fp.Fit = "Normal"
        fp.addProperty("App::PropertyLength", "Diameter", "Hole", "custom diameter").Diameter = 5
        fp.addProperty("App::PropertyLength", "Depth", "Hole", "").Depth = 10
        fp.addProperty("App::PropertyBool", "ThroughAll", "Hole", "")
        fp.addProperty("App::PropertyAngle", "TipAngle", "Hole", "drill point (0 = flat)").TipAngle = 118
        fp.addProperty("App::PropertyLength", "CounterboreDiameter", "Hole", "0 = from the size table")
        fp.addProperty("App::PropertyLength", "CounterboreDepth", "Hole", "0 = from the size table")
        fp.addProperty("App::PropertyLength", "CountersinkDiameter", "Hole", "0 = from the size table")
        fp.addProperty("App::PropertyLength", "ThreadLength", "Thread", "0 = full depth")
        fp.addProperty("App::PropertyString", "Thread", "Thread", "e.g. M5x0.8 (tapped holes)", 9)
        model.add_operation_properties(fp, default="Cut")

    def centres(self, fp, face):
        if fp.Points is not None:
            pts = regions.sketch_points(fp.Points, local=True)
        else:
            pts = list(fp.Positions)
        if not pts:
            raise ValueError("Place at least one hole centre.")
        n = face.normalAt(*face.Surface.parameter(face.CenterOfMass))
        o = face.Surface.Position
        return [p - n * (p - o).dot(n) for p in pts], n     # projected onto the face plane

    def tool(self, fp, state):
        _, face = topo.element(state, fp.Face)
        if not isinstance(face.Surface, Part.Plane):
            raise ValueError("Holes start on a flat face.")
        centres, n = self.centres(fp, face)
        d, cb, cs, thread = hole_dims(fp)
        if fp.Thread != thread:
            fp.Thread = thread
        depth = _scene_size(state, face) if fp.ThroughAll else fp.Depth.Value
        r = d / 2
        tools = []
        for i, c in enumerate(centres):
            parts = [(Part.makeCylinder(r, depth), "w")]
            if fp.TipAngle.Value > 0 and not fp.ThroughAll:
                h = r / math.tan(math.radians(fp.TipAngle.Value / 2))
                parts.append((Part.makeCone(r, 0, h, V(0, 0, depth)), "tip"))
            if cb:
                parts.append((Part.makeCylinder(cb[0] / 2, cb[1]), "cb"))
            if cs:
                hcs = (cs / 2 - r) / math.tan(math.radians(45))
                parts.append((Part.makeCone(cs / 2, r, hcs), "cs"))
            solid = parts[0][0].fuse([p for p, _ in parts[1:]]).removeSplitter() if len(parts) > 1 else parts[0][0]
            tags = []
            for f in solid.Faces:
                s = f.Surface
                if isinstance(s, Part.Cylinder):
                    role = "cb" if cb and abs(s.Radius - cb[0] / 2) < 1e-9 else "w"
                elif isinstance(s, Part.Cone):
                    role = "cs" if f.BoundBox.ZMin < 1e-9 else "tip"
                else:
                    z = f.CenterOfMass.z
                    role = "top" if z < 1e-9 else ("cbfloor" if cb and abs(z - cb[1]) < 1e-9 else "bottom")
                tags.append("%s:%s:%d" % (fp.Name, role, i))
            pl = App.Placement(c, App.Rotation(V(0, 0, 1), -n))
            tools.append(topo.Body(topo.baked(solid, pl.toMatrix()), tags))
        return _union(tools, fp), "Cut"

    def apply(self, fp, state):
        tool, hint = self.tool(fp, state)
        return model.apply_tool(fp, state, tool, hint)

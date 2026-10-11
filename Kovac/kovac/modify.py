# SPDX-License-Identifier: LGPL-2.1-or-later
"""Features that change existing bodies: Fillet, Chamfer, Shell, Draft, Face Pull, Delete Face,
Combine, Split Body, Move/Copy, Scale, Mirror, Pattern, Thread.

Faces an operation keeps inherit their tags (topo.inherit); faces it creates are named after
what made them (the edge a fillet rolled along, the face a shell wall offsets, ...).
"""
import math

import FreeCAD as App
import Part

from kovac import model, selection, topo

V = App.Vector


def _by_body(state, refs):
    """{body id: [elements]} for resolved references (deduplicated)."""
    out = {}
    for r in refs:
        body, el = topo.element(state, r)
        lst = out.setdefault(topo.loads(r)["b"], [])
        if not any(el.isSame(x) for x in lst):
            lst.append(el)
    return out


def _nearest_tag(fp, role, f, candidates):
    """Name a generated face after the nearest candidate (element, tags)."""
    p = topo.sample_points(f)[0]
    best = min(candidates, key=lambda c: c[0].distToShape(Part.Vertex(p))[0])
    return "%s:%s:%s" % (fp.Name, role, "+".join(best[1]))


def edge_groups(fp):
    """[(value prop, edges prop)] for group 1 ('Radius'/'Edges') and dynamic groups 2.."""
    out = [("Radius" if hasattr(fp, "Radius") else "Distance", "Edges")]
    i = 2
    while hasattr(fp, "Edges%d" % i):
        out.append((("Radius%d" if hasattr(fp, "Radius") else "Distance%d") % i, "Edges%d" % i))
        i += 1
    return out


def add_group(fp):
    """New radius/distance group with its own value (expressions work on it)."""
    i = len(edge_groups(fp)) + 1
    value = ("Radius%d" if hasattr(fp, "Radius") else "Distance%d") % i
    fp.addProperty("App::PropertyLength", value, "Groups", "group %d" % i)
    setattr(fp, value, getattr(fp, value[:-len(str(i))]).Value)
    fp.addProperty("App::PropertyStringList", "Edges%d" % i, "Groups", "group %d" % i)
    return value, "Edges%d" % i


class _EdgeFeature(model.Feature):
    """Shared by Fillet and Chamfer: edge picks, face picks (all their edges), whole bodies,
    tangent chains, several groups each with its own value."""

    def setup_edges(self, fp):
        fp.addProperty("App::PropertyStringList", "Edges", "Edges", "picked edges")
        fp.addProperty("App::PropertyStringList", "Faces", "Edges", "all edges of these faces (group 1)")
        fp.addProperty("App::PropertyStringList", "WholeBodies", "Edges", "every edge of these bodies (group 1)")
        fp.addProperty("App::PropertyBool", "TangentChain", "Edges", "include tangent-connected edges").TangentChain = True

    def edges_for(self, fp, state, prop, first):
        refs = model.refs(fp, prop)
        groups = _by_body(state, refs)
        if first:
            for bid, faces in _by_body(state, model.refs(fp, "Faces")).items():
                lst = groups.setdefault(bid, [])
                for f in faces:
                    lst += [e for e in f.Edges if not any(e.isSame(x) for x in lst)]
            for bid in fp.WholeBodies:
                if bid in state:
                    groups[bid] = list(state[bid].shape.Edges)
        if fp.TangentChain:
            for bid, edges in groups.items():
                shape = state[bid].shape
                idx = {e.hashCode(): i for i, e in enumerate(shape.Edges, 1)}
                more = set()
                for e in edges:
                    more.update(selection.tangent_edges(shape, idx[e.hashCode()]))
                groups[bid] = [shape.Edges[i - 1] for i in sorted(more)]
        return groups

    def apply(self, fp, state):
        picked = False
        for k, (vprop, eprop) in enumerate(edge_groups(fp)):
            value = getattr(fp, vprop).Value
            for bid, edges in self.edges_for(fp, state, eprop, k == 0).items():
                if not edges:
                    continue
                picked = True
                src = state[bid]
                e_adj, _ = topo.adjacency(src)
                cands = [(e, e_adj.get(e.hashCode(), [])) for e in edges]
                shape = self.make(fp, src.shape, value, edges, k)
                if shape.isNull() or not shape.isValid():
                    raise ValueError("The %s did not fit: try a smaller value." % self.kind.lower())
                state[bid] = topo.Body(shape, topo.inherit(shape, [src], lambda f: _nearest_tag(fp, self.role, f, cands)))
        if not picked:
            raise ValueError("Pick at least one edge.")
        return state


class Fillet(_EdgeFeature):
    kind, icon, role = "Fillet", "fillet", "f"

    def setup(self, fp):
        fp.addProperty("App::PropertyLength", "Radius", "Fillet", "").Radius = 1
        self.setup_edges(fp)

    def make(self, fp, shape, r, edges, _k):
        return shape.makeFillet(r, edges)


class Chamfer(_EdgeFeature):
    kind, icon, role = "Chamfer", "chamfer", "c"

    def setup(self, fp):
        fp.addProperty("App::PropertyEnumeration", "Mode", "Chamfer", "")
        fp.Mode = ["Equal distance", "Two distances", "Distance and angle"]
        fp.addProperty("App::PropertyLength", "Distance", "Chamfer", "").Distance = 1
        fp.addProperty("App::PropertyLength", "Distance2", "Chamfer", "second distance").Distance2 = 1
        fp.addProperty("App::PropertyAngle", "Angle", "Chamfer", "").Angle = 45
        fp.addProperty("App::PropertyBool", "Flip", "Chamfer", "swap the two sides")
        self.setup_edges(fp)

    def make(self, fp, shape, d, edges, k):
        if fp.Mode == "Equal distance" or k > 0:
            return shape.makeChamfer(d, edges)
        d2 = fp.Distance2.Value if fp.Mode == "Two distances" else d * math.tan(math.radians(fp.Angle.Value))
        return shape.makeChamfer(d2, d, edges) if fp.Flip else shape.makeChamfer(d, d2, edges)


# ---------------------------------------------------------------- Shell

def _offset_source(f, src, t):
    """Tag of the source face that f is the t-offset of, or None."""
    s = f.Surface
    for g, tag in zip(src.shape.Faces, src.tags):
        h = g.Surface
        if type(s) is not type(h):
            continue
        if isinstance(s, Part.Plane):
            if s.Axis.cross(h.Axis).Length < 1e-9 and abs(abs((s.Position - h.Position).dot(h.Axis)) - t) < 1e-6:
                p = topo.sample_points(f)[0]
                q = p - h.Axis * (p - h.Position).dot(h.Axis)
                u, v = g.Surface.parameter(q)
                if g.isPartOfDomain(u, v):
                    return tag
        elif isinstance(s, (Part.Cylinder, Part.Sphere)):
            same_c = (s.Center - h.Center).Length < 1e-6 if isinstance(s, Part.Sphere) else \
                topo._same_line(s.Center, s.Axis, h.Center, h.Axis, 1e-6)
            if same_c and abs(abs(s.Radius - h.Radius) - t) < 1e-6:
                return tag
        elif isinstance(s, Part.Toroid):
            if (s.Center - h.Center).Length < 1e-6 and abs(abs(s.MinorRadius - h.MinorRadius) - t) < 1e-6:
                return tag
    return None


class Shell(model.Feature):
    kind, icon = "Shell", "shell"

    def setup(self, fp):
        fp.addProperty("App::PropertyStringList", "Faces", "Shell", "faces to open (none = closed hollow)")
        fp.addProperty("App::PropertyStringList", "Bodies", "Shell", "body ids for a closed hollow")
        fp.addProperty("App::PropertyLength", "Thickness", "Shell", "").Thickness = 2
        fp.addProperty("App::PropertyBool", "Outside", "Shell", "add the wall outside")

    def apply(self, fp, state):
        t = fp.Thickness.Value
        groups = _by_body(state, model.refs(fp, "Faces"))
        for bid in fp.Bodies:
            groups.setdefault(bid, [])
        if not groups:
            raise ValueError("Pick the faces to open, or a body to hollow.")
        for bid, faces in groups.items():
            src = state[bid]
            try:
                if faces:
                    shape = src.shape.makeThickness(faces, t if fp.Outside else -t, 1e-6)
                else:
                    shape = src.shape.cut(src.shape.makeOffsetShape(-t, 1e-6))
                if shape.isNull() or not shape.Solids or not shape.isValid():
                    raise ValueError
            except Exception:
                if fp.Outside:
                    raise ValueError("The wall is too thick for this shape.")
                shape = self.sharp_inside(src.shape, faces, t)
            if shape.isNull() or not shape.Solids or not shape.isValid():
                raise ValueError("The wall is too thick for this shape.")

            def gen(f, src=src):
                tag = _offset_source(f, src, t)
                return "%s:in:%s" % (fp.Name, tag) if tag else None
            state[bid] = topo.Body(shape, topo.inherit(shape, [src], gen))
        return state

    @staticmethod
    def sharp_inside(shape, opened, t):
        """Fallback when the kernel's offset fails because a fillet is no bigger than the wall:
        the inside of a fillet with radius <= t is a sharp corner, so offset a copy with those
        fillets removed, extend it out through the opened (flat) faces, and cut it away."""
        small = [f for f in shape.Faces if isinstance(f.Surface, (Part.Cylinder, Part.Sphere)) and f.Surface.Radius <= t + 1e-6
                 or isinstance(f.Surface, Part.Toroid) and f.Surface.MinorRadius <= t + 1e-6]
        core = shape.defeaturing(small) if small else shape
        try:
            inner = core.makeOffsetShape(-t, 1e-6, False, False, 0, 2)      # intersection join: sharp corners
        except Exception:
            raise ValueError("The wall is too thick for this shape.")
        for f in opened:
            if not isinstance(f.Surface, Part.Plane):
                raise ValueError("Opened faces must be flat when the wall is as thick as a fillet.")
            n = f.normalAt(*f.Surface.parameter(f.CenterOfMass))
            d = (f.Surface.Position - n * t).dot(n) - 1e-4        # just inside the inner solid's top
            wires = inner.slice(n, d)
            if not wires:
                raise ValueError("The wall is too thick for this shape.")
            cap = Part.makeFace(wires, "Part::FaceMakerBullseye")
            inner = inner.fuse(cap.extrude(n * (3 * t + 1e-3)))      # the cavity runs out through the opening
        return model._clean(shape.cut(inner))


# ---------------------------------------------------------------- Draft (OCCT draft angle via pythonocc)

class Draft(model.Feature):
    kind, icon = "Draft", "draft"

    def setup(self, fp):
        fp.addProperty("App::PropertyStringList", "Faces", "Draft", "faces to tilt")
        fp.addProperty("App::PropertyString", "Neutral", "Draft", "flat face that keeps its size")
        fp.addProperty("App::PropertyAngle", "Angle", "Draft", "").Angle = 3
        fp.addProperty("App::PropertyBool", "Reverse", "Draft", "pull the other way")

    def apply(self, fp, state):
        from OCC.Core.BRep import BRep_Builder
        from OCC.Core.BRepOffsetAPI import BRepOffsetAPI_DraftAngle
        from OCC.Core.BRepTools import breptools
        from OCC.Core.gp import gp_Dir, gp_Pln, gp_Pnt
        from OCC.Core.TopAbs import TopAbs_FACE
        from OCC.Core.TopExp import topexp
        from OCC.Core.TopoDS import TopoDS_Shape, topods
        from OCC.Core.TopTools import TopTools_IndexedMapOfShape

        _, neutral = topo.element(state, fp.Neutral)
        if not isinstance(neutral.Surface, Part.Plane):
            raise ValueError("The neutral face must be flat.")
        # pull direction: away from the neutral face, into the part (walls narrow as they rise)
        n = -neutral.normalAt(*neutral.Surface.parameter(neutral.CenterOfMass))
        if fp.Reverse:
            n = -n
        o = neutral.Surface.Position
        for bid, faces in _by_body(state, model.refs(fp, "Faces")).items():
            src = state[bid]
            occ = TopoDS_Shape()
            breptools.Read(occ, self._tmp(src.shape), BRep_Builder())   # hand-off via a BREP file
            fmap = TopTools_IndexedMapOfShape()
            topexp.MapShapes(occ, TopAbs_FACE, fmap)
            picked = {i for i, f in enumerate(src.shape.Faces, 1) if any(f.isSame(x) for x in faces)}
            algo = BRepOffsetAPI_DraftAngle(occ)
            plane = gp_Pln(gp_Pnt(o.x, o.y, o.z), gp_Dir(n.x, n.y, n.z))
            for i in sorted(picked):
                algo.Add(topods.Face(fmap.FindKey(i)), gp_Dir(n.x, n.y, n.z), math.radians(fp.Angle.Value), plane)
                if not algo.AddDone():
                    raise ValueError("A picked face cannot be drafted against this neutral face.")
            algo.Build()
            if not algo.IsDone():
                raise ValueError("The draft could not be built.")
            res = algo.Shape()
            rmap = TopTools_IndexedMapOfShape()
            topexp.MapShapes(res, TopAbs_FACE, rmap)
            tags = [None] * rmap.Size()
            for i in range(1, fmap.Size() + 1):     # exact history from the algorithm
                f = fmap.FindKey(i)
                mods = algo.Modified(f)
                targets = [rmap.FindIndex(x) for x in self._iter(mods)] if mods.Size() else [rmap.FindIndex(f)]
                for j in targets:
                    if j > 0 and tags[j - 1] is None:
                        tags[j - 1] = src.tags[i - 1]
            out = Part.Shape()
            out.importBrepFromString(self._brep(res))
            tags = [t or "%s:new:%d" % (fp.Name, k) for k, t in enumerate(tags)]
            state[bid] = topo.Body(out, tags)
        return state

    @staticmethod
    def _iter(lst):
        from OCC.Core.TopTools import TopTools_ListIteratorOfListOfShape
        it = TopTools_ListIteratorOfListOfShape(lst)
        while it.More():
            yield it.Value()
            it.Next()

    @staticmethod
    def _tmp(shape):
        import tempfile, os
        p = os.path.join(tempfile.gettempdir(), "kovac_draft_in.brep")
        shape.exportBrep(p)
        return p

    @staticmethod
    def _brep(occ_shape):
        import tempfile, os
        from OCC.Core.BRepTools import breptools
        p = os.path.join(tempfile.gettempdir(), "kovac_draft_out.brep")
        breptools.Write(occ_shape, p)
        with open(p) as f:
            return f.read()


# ---------------------------------------------------------------- Face Pull / Delete Face

class FacePull(model.Feature):
    """Move a flat face along its normal; the face keeps its name."""
    kind, icon = "FacePull", "facepull"

    def setup(self, fp):
        fp.addProperty("App::PropertyString", "Face", "Face Pull", "")
        fp.addProperty("App::PropertyDistance", "Distance", "Face Pull", "out (+) or in (-)").Distance = 2

    def apply(self, fp, state):
        bid = topo.loads(fp.Face)["b"]
        src, face = topo.element(state, fp.Face)
        if not isinstance(face.Surface, Part.Plane):
            raise ValueError("Face Pull moves flat faces in this version.")
        d = fp.Distance.Value
        n = face.normalAt(*face.Surface.parameter(face.CenterOfMass))
        own = src.tags[[i for i, f in enumerate(src.shape.Faces) if f.isSame(face)][0]]
        prism = face.extrude(n * d)
        moved = face.copy()
        moved.translate(n * d)
        e_adj, _ = topo.adjacency(src)
        tags = []
        for f in prism.Faces:
            if topo.same_support(f, moved):
                tags.append(own)                                   # the moved face keeps its name
            elif topo.same_support(f, face):
                tags.append("%s:base" % fp.Name)
            else:
                e = min(face.Edges, key=lambda e: f.distToShape(e)[0])
                tags.append("%s:s:%s" % (fp.Name, "+".join(e_adj.get(e.hashCode(), []))))
        tool = topo.Body(prism, tags)
        shape = (src.shape.fuse(prism) if d > 0 else src.shape.cut(prism)).removeSplitter()
        state[bid] = topo.Body(shape, topo.inherit(shape, [tool, src] if d > 0 else [src, tool]))
        return state


class DeleteFace(model.Feature):
    kind, icon = "DeleteFace", "deleteface"

    def setup(self, fp):
        fp.addProperty("App::PropertyStringList", "Faces", "Delete Face", "faces to remove (the gap heals)")

    def apply(self, fp, state):
        for bid, faces in _by_body(state, model.refs(fp, "Faces")).items():
            src = state[bid]
            shape = src.shape.defeaturing(faces)
            if shape.isNull() or not shape.isValid() or len(shape.Faces) == len(src.shape.Faces):
                raise ValueError("These faces cannot be removed and healed.")
            state[bid] = topo.Body(shape, topo.inherit(shape, [src]))
        return state


# ---------------------------------------------------------------- body operations

class Combine(model.Feature):
    kind, icon = "Combine", "combine"

    def setup(self, fp):
        fp.addProperty("App::PropertyString", "Target", "Combine", "body id that receives the result")
        fp.addProperty("App::PropertyStringList", "Tools", "Combine", "body ids")
        fp.addProperty("App::PropertyEnumeration", "Operation", "Combine", "")
        fp.Operation = ["Join", "Cut", "Intersect"]
        fp.addProperty("App::PropertyBool", "KeepTools", "Combine", "")

    def apply(self, fp, state):
        if fp.Target not in state or not all(t in state for t in fp.Tools) or not fp.Tools:
            raise topo.Broken("a body picked for Combine no longer exists")
        tgt, tools = state[fp.Target], [state[t] for t in fp.Tools]
        if fp.Operation == "Join":
            shape = tgt.shape.fuse([t.shape for t in tools])
        elif fp.Operation == "Cut":
            shape = tgt.shape.cut([t.shape for t in tools])
        else:
            shape = tgt.shape
            for t in tools:
                shape = shape.common(t.shape)
        shape = model._clean(shape)
        state[fp.Target] = topo.Body(shape, topo.inherit(shape, [tgt] + tools))
        if not fp.KeepTools:
            for t in fp.Tools:
                del state[t]
        return state


def plane_of(fp, prop, state):
    """(origin, normal) of a plane given as 'XY'/'XZ'/'YZ', a datum object name or a face ref."""
    v = getattr(fp, prop)
    if v in ("XY", "XZ", "YZ"):
        return V(), {"XY": V(0, 0, 1), "XZ": V(0, 1, 0), "YZ": V(1, 0, 0)}[v]
    obj = fp.Document.getObject(v) if v and not v.startswith("{") else None
    if obj is not None:
        pl = obj.Placement
        return pl.Base, pl.Rotation.multVec(V(0, 0, 1))
    _, face = topo.element(state, v)
    if not isinstance(face.Surface, Part.Plane):
        raise ValueError("Pick a flat face or a plane.")
    return face.Surface.Position, face.normalAt(*face.Surface.parameter(face.CenterOfMass))


def _halfspace(o, n, size):
    b = Part.makeBox(2 * size, 2 * size, size, V(-size, -size, 0))
    b.transformShape(App.Placement(o, App.Rotation(V(0, 0, 1), n)).toMatrix())
    return b


def _split_tool(fp, prop, state, body_shape):
    """The solid to split body_shape with: a half-space for 'XY'/'XZ'/'YZ', a datum plane or a
    flat face (as plane_of, which a curved face fails); the whole analytic surface's own solid
    -- not just the picked patch -- for a cylindrical or spherical face, sized to reach past
    body_shape everywhere. A full cylinder or sphere already bounds a solid the same way a
    plane already bounds a half-space; there is no equivalent closed form for a cone or a
    freeform face, so those still need a flat face or a plane."""
    bb = body_shape.BoundBox
    size = bb.DiagonalLength * 4
    v = getattr(fp, prop)
    if v in ("XY", "XZ", "YZ") or (fp.Document.getObject(v) if v and not v.startswith("{") else None) is not None:
        o, n = plane_of(fp, prop, state)
        return _halfspace(o, n, size + (o - bb.Center).Length)
    _, face = topo.element(state, v)
    surf = face.Surface
    if isinstance(surf, Part.Plane):
        o, n = surf.Position, face.normalAt(*surf.parameter(face.CenterOfMass))
        return _halfspace(o, n, size + (o - bb.Center).Length)
    if isinstance(surf, Part.Cylinder):
        axis = surf.Axis.normalize()
        return Part.makeCylinder(surf.Radius, size, surf.Center - axis * (size / 2), axis)
    if isinstance(surf, Part.Sphere):
        return Part.makeSphere(surf.Radius, surf.Center)
    raise ValueError("Pick a plane, a flat face, or a cylindrical or spherical face.")


class SplitBody(model.Feature):
    kind, icon = "SplitBody", "split"

    def setup(self, fp):
        fp.addProperty("App::PropertyString", "Body", "Split", "body id")
        fp.addProperty("App::PropertyString", "Plane", "Split",
                       "XY/XZ/YZ, a plane, a flat face, or a cylindrical/spherical face")

    def apply(self, fp, state):
        if fp.Body not in state:
            raise topo.Broken("the body to split no longer exists")
        src = state[fp.Body]
        tool = _split_tool(fp, "Plane", state, src.shape)
        cut = topo.Body(tool, ["%s:split" % fp.Name] * len(tool.Faces))
        pos, neg = src.shape.common(cut.shape), src.shape.cut(cut.shape)
        if not pos.Solids or not neg.Solids:
            raise ValueError("The split tool does not cross the body.")
        state[fp.Body] = topo.Body(pos, topo.inherit(pos, [src, cut]))
        state[model.new_body_id(fp)] = topo.Body(neg, topo.inherit(neg, [src, cut]))
        return state


class Transform(model.Feature):
    """Move or copy bodies (recorded in the history)."""
    kind, icon = "Move", "move"

    def setup(self, fp):
        fp.addProperty("App::PropertyStringList", "Bodies", "Move", "body ids")
        fp.addProperty("App::PropertyPlacement", "Move", "Move", "translation and rotation")
        fp.addProperty("App::PropertyBool", "Copy", "Move", "keep the original")

    def apply(self, fp, state):
        for k, bid in enumerate(fp.Bodies):
            if bid not in state:
                raise topo.Broken("a body to move no longer exists")
            moved = state[bid].transformed(fp.Move)
            if fp.Copy:
                moved = topo.Body(moved.shape, [t + "@" + fp.Name for t in moved.tags])
                state[model.new_body_id(fp, k)] = moved
            else:
                state[bid] = moved
        return state


class Scale(model.Feature):
    kind, icon = "Scale", "scale"

    def setup(self, fp):
        fp.addProperty("App::PropertyStringList", "Bodies", "Scale", "body ids")
        fp.addProperty("App::PropertyFloat", "Factor", "Scale", "").Factor = 1.0
        fp.addProperty("App::PropertyVector", "Center", "Scale", "")

    def apply(self, fp, state):
        if fp.Factor <= 0:
            raise ValueError("The scale factor must be positive.")
        for bid in fp.Bodies:
            if bid not in state:
                raise topo.Broken("a body to scale no longer exists")
            m = App.Matrix()
            m.move(-fp.Center)
            m.scale(fp.Factor, fp.Factor, fp.Factor)
            m.move(fp.Center)
            s = state[bid].shape.copy()
            s.transformShape(m, True)
            state[bid] = topo.Body(s, state[bid].tags)
        return state


class Mirror(model.Feature):
    kind, icon = "Mirror", "mirror"

    def setup(self, fp):
        fp.addProperty("App::PropertyStringList", "Bodies", "Mirror", "body ids")
        fp.addProperty("App::PropertyString", "Plane", "Mirror", "XY/XZ/YZ, a plane, or a flat face").Plane = "YZ"
        fp.addProperty("App::PropertyBool", "Join", "Mirror", "merge the mirror image with the original").Join = True

    def apply(self, fp, state):
        o, n = plane_of(fp, "Plane", state)
        for k, bid in enumerate(fp.Bodies):
            if bid not in state:
                raise topo.Broken("a body to mirror no longer exists")
            src = state[bid]
            img = src.shape.mirror(o, n)
            mirrored = topo.Body(img, [t + "@" + fp.Name for t in src.tags])   # mirror keeps face order
            if fp.Join:
                shape = model._clean(src.shape.fuse(img))
                state[bid] = topo.Body(shape, topo.inherit(shape, [src, mirrored]))
            else:
                state[model.new_body_id(fp, k)] = mirrored
        return state


# ---------------------------------------------------------------- Pattern

class Pattern(model.Feature):
    """Repeat features (their tool shape, same operation) or bodies (as new bodies)."""
    kind, icon = "Pattern", "pattern"

    def setup(self, fp):
        fp.addProperty("App::PropertyLinkList", "Sources", "Pattern", "features to repeat")
        fp.addProperty("App::PropertyStringList", "Bodies", "Pattern", "or: body ids to repeat")
        fp.addProperty("App::PropertyEnumeration", "Type", "Pattern", "")
        fp.Type = ["Rectangular", "Circular"]
        fp.addProperty("App::PropertyVector", "Direction1", "Rectangular", "").Direction1 = V(1, 0, 0)
        fp.addProperty("App::PropertyIntegerConstraint", "Count1", "Rectangular", "").Count1 = (2, 1, 10000, 1)
        fp.addProperty("App::PropertyDistance", "Spacing1", "Rectangular", "").Spacing1 = 10
        fp.addProperty("App::PropertyVector", "Direction2", "Rectangular", "").Direction2 = V(0, 1, 0)
        fp.addProperty("App::PropertyIntegerConstraint", "Count2", "Rectangular", "").Count2 = (1, 1, 10000, 1)
        fp.addProperty("App::PropertyDistance", "Spacing2", "Rectangular", "").Spacing2 = 10
        fp.addProperty("App::PropertyString", "Axis", "Circular", "X, Y, Z or an edge").Axis = "Z"
        fp.addProperty("App::PropertyVector", "AxisPoint", "Circular", "a point on the axis (X/Y/Z)")
        fp.addProperty("App::PropertyIntegerConstraint", "Count", "Circular", "").Count = (4, 1, 10000, 1)
        fp.addProperty("App::PropertyAngle", "TotalAngle", "Circular", "").TotalAngle = 360
        fp.addProperty("App::PropertyIntegerList", "Skip", "Pattern", "instance numbers to leave out")

    def placements(self, fp, state):
        out = []
        if fp.Type == "Rectangular":
            d1, d2 = V(fp.Direction1), V(fp.Direction2)
            d1 = d1.normalize() if d1.Length else V(1, 0, 0)
            d2 = d2.normalize() if d2.Length else V(0, 1, 0)
            for j in range(fp.Count2):
                for i in range(fp.Count1):
                    out.append(App.Placement(d1 * (i * fp.Spacing1.Value) + d2 * (j * fp.Spacing2.Value), App.Rotation()))
        else:
            if fp.Axis in ("X", "Y", "Z"):
                base, axis = V(fp.AxisPoint), V(*[1 if c == fp.Axis else 0 for c in "XYZ"])
            else:
                _, edge = topo.element(state, fp.Axis)
                base = edge.Vertexes[0].Point
                axis = (edge.Vertexes[-1].Point - base).normalize()
            n = fp.Count
            step = fp.TotalAngle.Value / (n if abs(fp.TotalAngle.Value - 360) < 1e-9 else max(n - 1, 1))
            for i in range(n):
                rot = App.Rotation(axis, step * i)
                out.append(App.Placement(base - rot.multVec(base), rot))
        return out

    def apply(self, fp, state):
        pls = self.placements(fp, state)
        instances = [(k, p) for k, p in enumerate(pls) if k > 0 and k not in fp.Skip]
        if fp.Sources:
            for src in fp.Sources:
                if not hasattr(src.Proxy, "tool"):
                    raise ValueError("%s cannot be patterned (no tool shape)." % src.Label)
                tool, hint = src.Proxy.tool(src, model.input_state(src))
                op = src.ResolvedOperation.replace(" (auto)", "") or "Join"

                class _Op:   # apply_tool reads these
                    Operation, Targets, ResolvedOperation, Name = op, [], op, fp.Name
                for k, pl in instances:
                    inst = tool.transformed(pl)
                    inst = topo.Body(inst.shape, ["%s@%s.%d" % (t, fp.Name, k) for t in inst.tags])
                    _Op.Name = "%s.%d" % (fp.Name, k)
                    state = model.apply_tool(_Op, state, inst, hint)
        for bid in fp.Bodies:
            if bid not in state:
                raise topo.Broken("a body to pattern no longer exists")
            for k, pl in instances:
                b = state[bid].transformed(pl)
                state[model.new_body_id(fp, k)] = topo.Body(b.shape, ["%s@%s.%d" % (t, fp.Name, k) for t in b.tags])
        if not fp.Sources and not fp.Bodies:
            raise ValueError("Pick features or bodies to repeat.")
        return state


# ---------------------------------------------------------------- Thread (cosmetic)

class RemoveBody(model.Feature):
    """Bodies taken out of the design from this point of the history on."""
    kind, icon = "RemoveBody", "delete"

    def setup(self, fp):
        fp.addProperty("App::PropertyStringList", "Bodies", "Remove", "body ids")

    def apply(self, fp, state):
        for bid in fp.Bodies:
            state.pop(bid, None)
        return state


class Thread(model.Feature):
    """Cosmetic thread: geometry unchanged; size and length recorded for drawings (M3)."""
    kind, icon = "Thread", "thread"

    def setup(self, fp):
        fp.addProperty("App::PropertyStringList", "Faces", "Thread", "cylindrical faces")
        fp.addProperty("App::PropertyString", "Size", "Thread", "e.g. M8x1.25")
        fp.addProperty("App::PropertyLength", "Length", "Thread", "0 = full face")
        fp.addProperty("App::PropertyBool", "Internal", "Thread", "", 9)

    def apply(self, fp, state):
        for bid, faces in _by_body(state, model.refs(fp, "Faces")).items():
            for f in faces:
                s = f.Surface
                if not isinstance(s, Part.Cylinder):
                    raise ValueError("Threads go on cylindrical faces.")
                p = topo.sample_points(f)[0]
                on_axis = s.Center + s.Axis * (p - s.Center).dot(s.Axis)
                external = state[bid].shape.isInside(on_axis + (p - on_axis) * 0.5, 1e-6, True)
                if fp.Internal == external:
                    fp.Internal = not external
        return state

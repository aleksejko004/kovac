# SPDX-License-Identifier: LGPL-2.1-or-later
"""Reference geometry: planes, axes, points. History items that read the body state at
their position (to follow picked faces/edges) but don't change it. Sketches sit on
planes (attachment 'ObjectXY'), so a sketch on a face moves with that face."""
import math

import FreeCAD as App
import Part

from kovac import model, topo

V = App.Vector
PLANE_MODES = ["XY", "XZ", "YZ", "Offset", "Angle", "Midplane", "ThreePoints", "Tangent", "AlongPath"]
AXIS_MODES = ["X", "Y", "Z", "TwoPoints", "Edge", "Cylinder"]
POINT_MODES = ["Coordinates", "Vertex", "EdgeMiddle", "FaceCenter"]


def frame(origin, normal):
    """Placement whose Z is normal; X follows global X (or Y when X is the normal)."""
    n = V(normal).normalize()
    x = V(1, 0, 0) if abs(n.x) < 0.9 else V(0, 1, 0)
    x = (x - n * x.dot(n)).normalize()
    return App.Placement(origin, App.Rotation(x, n.cross(x), n, "ZXY"))


def _plane_of_ref(doc, value, state):
    """(origin, normal) from 'XY'/'XZ'/'YZ', a datum object name, or a flat face reference."""
    if value in ("XY", "XZ", "YZ"):
        return V(), {"XY": V(0, 0, 1), "XZ": V(0, -1, 0), "YZ": V(1, 0, 0)}[value]
    obj = doc.getObject(value) if value and not value.startswith("{") else None
    if obj is not None:
        return obj.Placement.Base, obj.Placement.Rotation.multVec(V(0, 0, 1))
    _, f = topo.element(state, value)
    if not isinstance(f.Surface, Part.Plane):
        raise ValueError("That face is not flat.")
    n = f.normalAt(*f.Surface.parameter(f.CenterOfMass))
    # anchor at the world origin's projection: sketch coordinates on a horizontal face are
    # world X/Y, and the anchor does not drift when the face changes shape
    return n * f.Surface.Position.dot(n), n


class _Datum(model.Feature):
    state_feature = False

    def show(self, fp, shape, placement):
        fp.Shape = shape
        fp.Placement = placement


class DatumPlane(_Datum):
    kind, icon = "Plane", "plane"

    def setup(self, fp):
        fp.addProperty("App::PropertyEnumeration", "Mode", "Plane", "")
        fp.Mode = PLANE_MODES
        fp.addProperty("App::PropertyString", "Base", "Plane", "plane or flat face it starts from").Base = "XY"
        fp.addProperty("App::PropertyDistance", "Offset", "Plane", "")
        fp.addProperty("App::PropertyAngle", "Angle", "Plane", "")
        fp.addProperty("App::PropertyStringList", "Refs", "Plane", "edges / faces / vertices it uses")
        fp.addProperty("App::PropertyFloatConstraint", "Position", "Plane", "along the path, 0..1").Position = (0.0, 0.0, 1.0, 0.05)
        fp.addProperty("App::PropertyLength", "Size", "Plane", "display size").Size = 60
        fp.addProperty("App::PropertyBool", "Auto", "Plane", "created for a sketch (hidden in the tree)", 4)

    def apply(self, fp, state):
        m = fp.Mode
        refs = model.refs(fp, "Refs")
        if m in ("XY", "XZ", "YZ"):
            o, n = _plane_of_ref(fp.Document, m, state)
        elif m == "Offset":
            o, n = _plane_of_ref(fp.Document, fp.Base, state)
            o = o + n * fp.Offset.Value
        elif m == "Angle":
            o, n = _plane_of_ref(fp.Document, fp.Base, state)
            _, e = topo.element(state, refs[0])
            a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
            n = App.Rotation((b - a).normalize(), fp.Angle.Value).multVec(n)
            o = a
        elif m == "Midplane":
            (_, f1), (_, f2) = topo.element(state, refs[0]), topo.element(state, refs[1])
            p1, p2 = topo.sample_points(f1)[0], topo.sample_points(f2)[0]
            n = f1.normalAt(*f1.Surface.parameter(f1.CenterOfMass))
            o = p1 + n * ((p2 - p1).dot(n) / 2)
        elif m == "ThreePoints":
            p = [topo.element(state, r)[1].Point for r in refs[:3]]
            n = (p[1] - p[0]).cross(p[2] - p[0])
            if n.Length < 1e-9:
                raise ValueError("The three points are in a line.")
            o = p[0]
        elif m == "Tangent":
            _, f = topo.element(state, refs[0])
            s = f.Surface
            if not isinstance(s, Part.Cylinder):
                raise ValueError("Tangent planes need a cylindrical face.")
            x = frame(s.Center, s.Axis).Rotation.multVec(V(1, 0, 0))
            n = App.Rotation(s.Axis, fp.Angle.Value).multVec(x)
            o = s.Center + n * s.Radius
        else:  # AlongPath: normal to an edge
            _, e = topo.element(state, refs[0])
            t = e.FirstParameter + fp.Position * (e.LastParameter - e.FirstParameter)
            o, n = e.valueAt(t), e.tangentAt(t)
        s = fp.Size.Value
        self.show(fp, Part.makePlane(s, s, V(-s / 2, -s / 2, 0)), frame(o, n))
        return state


class DatumAxis(_Datum):
    kind, icon = "Axis", "axis"

    def setup(self, fp):
        fp.addProperty("App::PropertyEnumeration", "Mode", "Axis", "")
        fp.Mode = AXIS_MODES
        fp.addProperty("App::PropertyStringList", "Refs", "Axis", "")
        fp.addProperty("App::PropertyLength", "Size", "Axis", "display length").Size = 80

    def apply(self, fp, state):
        refs = model.refs(fp, "Refs")
        if fp.Mode in ("X", "Y", "Z"):
            o, d = V(), V(*[1 if c == fp.Mode else 0 for c in "XYZ"])
        elif fp.Mode == "TwoPoints":
            a, b = (topo.element(state, r)[1].Point for r in refs[:2])
            o, d = a, b - a
        elif fp.Mode == "Edge":
            _, e = topo.element(state, refs[0])
            o, d = e.Vertexes[0].Point, e.Vertexes[-1].Point - e.Vertexes[0].Point
        else:
            _, f = topo.element(state, refs[0])
            if not isinstance(f.Surface, Part.Cylinder):
                raise ValueError("Pick a cylindrical face.")
            o, d = f.Surface.Center, f.Surface.Axis
        if d.Length < 1e-9:
            raise ValueError("The axis has no direction.")
        s = fp.Size.Value
        self.show(fp, Part.LineSegment(V(0, 0, -s / 2), V(0, 0, s / 2)).toShape(), frame(o, d))
        return state


class DatumPoint(_Datum):
    kind, icon = "Point", "point"

    def setup(self, fp):
        fp.addProperty("App::PropertyEnumeration", "Mode", "Point", "")
        fp.Mode = POINT_MODES
        fp.addProperty("App::PropertyStringList", "Refs", "Point", "")
        fp.addProperty("App::PropertyVector", "Coordinates", "Point", "")

    def apply(self, fp, state):
        refs = model.refs(fp, "Refs")
        if fp.Mode == "Coordinates":
            p = V(fp.Coordinates)
        else:
            _, el = topo.element(state, refs[0])
            if fp.Mode == "Vertex":
                p = el.Point
            elif fp.Mode == "EdgeMiddle":
                p = el.valueAt((el.FirstParameter + el.LastParameter) / 2)
            else:
                p = el.CenterOfMass
        self.show(fp, Part.Vertex(V()), App.Placement(p, App.Rotation()))
        return state


def sketch_on(doc, plane, name="Sketch"):
    """A sketch that sits on a plane datum and follows it."""
    sk = doc.addObject("Sketcher::SketchObject", name)
    sk.AttachmentSupport = [(plane, "")]
    sk.MapMode = "ObjectXY"
    return sk


def angle_between(a, b):
    return math.degrees(a.getAngle(b))

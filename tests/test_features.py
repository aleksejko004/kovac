# SPDX-License-Identifier: LGPL-2.1-or-later
"""Every feature against hand-computed geometry (headless)."""
import math
import unittest

import FreeCAD as App
import Part

from helpers import edge_ref, face_ref, feature, live_bodies, normal, rect, sketch, vertical_edge_at
from kovac import datum, features, model, modify

V = App.Vector
PI = math.pi


class Features(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("F")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def plate(self, w=40, d=20, h=10):
        sk = sketch(self.doc, rect(0, 0, w, d))
        self.ex = feature(self.doc, features.Extrude, Profile=sk, Length=h)
        self.body = live_bodies(self.doc)[0]
        return self.body

    def ok(self, fp):
        self.assertEqual(fp.Status, "", fp.Status)
        return fp

    def vol(self, expected, body=None, places=4):
        self.assertAlmostEqual((body or self.body).Shape.Volume, expected, places)
        self.assertTrue((body or self.body).Shape.isValid())

    def top(self):
        return face_ref(self.doc, self.body, lambda f: normal(f).z > 0.99)

    # ---- create
    def test_extrude_variants(self):
        sk = sketch(self.doc, rect(0, 0, 10, 10))
        e = self.ok(feature(self.doc, features.Extrude, Profile=sk, Length=10, Sides="Symmetric"))
        b = live_bodies(self.doc)[0]
        self.vol(1000, b)
        self.assertAlmostEqual(b.Shape.BoundBox.ZMin, -5, 9)
        e.Sides, e.Length2 = "Two sides", 3
        model.commit(self.doc)
        self.vol(1300, b)
        e.Sides, e.Taper = "One side", 5
        model.commit(self.doc)
        t = 10 * math.tan(math.radians(5))
        a1, a2, am = 100, (10 - 2 * t) ** 2, (10 - t) ** 2
        self.vol(10 / 6 * (a1 + 4 * am + a2), b, 3)
        e.Taper, e.Thin = 0, 1
        model.commit(self.doc)
        self.vol((100 - 64) * 10, b)

    def test_extrude_through_all_and_to_face(self):
        self.plate()
        top = App.Placement(V(0, 0, 10), App.Rotation())
        sk = sketch(self.doc, [("circle", (20, 10), 3)], top, "Thru")
        self.ok(feature(self.doc, features.Extrude, Profile=sk, Length=-1, Extent="Through all"))
        self.vol(8000 - PI * 9 * 10)
        sk2 = sketch(self.doc, rect(45, 0, 50, 5), name="Post")
        e2 = self.ok(feature(self.doc, features.Extrude, Profile=sk2, Extent="To face", ToFace=self.top(),
                             Operation="New body"))
        self.assertAlmostEqual(live_bodies(self.doc)[1].Shape.Volume, 25 * 10, 6)
        self.assertEqual(e2.ResolvedOperation, "New body")

    def test_revolve_sweep_loft(self):
        xy = sketch(self.doc, rect(10, 0, 20, 10), name="Ring")
        self.ok(feature(self.doc, features.Revolve, Profile=xy, Axis="Y", Angle=360))
        self.vol(PI * (400 - 100) * 10, live_bodies(self.doc)[0])
        self.doc.removeObject(live_bodies(self.doc)[0].Name)
        # sweep: circle r2 in XZ-ish plane at x=100, along a straight path of 30 in +Y
        prof = sketch(self.doc, [("circle", (100, 0), 2)], App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90)), "Prof")
        path = sketch(self.doc, [("line", (100, 0), (100, 30))], name="Path")
        self.ok(feature(self.doc, features.Sweep, Profile=prof, Path=path, Operation="New body"))
        swept = [b for b in live_bodies(self.doc) if b.Shape.BoundBox.XMin > 90][0]
        self.assertAlmostEqual(swept.Shape.Volume, PI * 4 * 30, 3)
        s1 = sketch(self.doc, rect(200, 0, 210, 10), name="L1")
        s2 = sketch(self.doc, rect(200, 0, 210, 10), App.Placement(V(0, 0, 10), App.Rotation()), "L2")
        self.ok(feature(self.doc, features.Loft, Sections=[s1, s2], Ruled=True, Operation="New body"))
        lofted = [b for b in live_bodies(self.doc) if b.Shape.BoundBox.XMin > 190][0]
        self.assertAlmostEqual(lofted.Shape.Volume, 1000, 6)

    def test_primitives(self):
        for shape, vol in (("Box", 8000), ("Cylinder", PI * 100 * 20), ("Sphere", 4 / 3 * PI * 1000),
                           ("Cone", PI * 20 / 3 * (100 + 30 + 9)), ("Torus", 2 * PI ** 2 * 10 * 9)):
            loc = App.Placement(V(100 * len(live_bodies(self.doc)), 0, 0), App.Rotation())
            self.ok(feature(self.doc, features.Primitive, PrimitiveType=shape, Location=loc, Operation="New body"))
            self.assertAlmostEqual(live_bodies(self.doc)[-1].Shape.Volume, vol, 4, shape)

    def test_holes(self):
        self.plate()
        top = self.top()
        h = self.ok(feature(self.doc, features.Hole, Face=top, Positions=[V(10, 10, 10)], Size="M5", ThroughAll=True))
        self.vol(8000 - PI * 2.75 ** 2 * 10)
        h.HoleType = "Counterbore"
        model.commit(self.doc)
        self.vol(8000 - PI * (2.75 ** 2 * (10 - 5.4) + 5 ** 2 * 5.4))
        h.HoleType = "Countersink"
        model.commit(self.doc)
        frustum = PI * 3 / 3 * (5.75 ** 2 + 5.75 * 2.75 + 2.75 ** 2)
        self.vol(8000 - PI * 2.75 ** 2 * 7 - frustum)
        h.HoleType, h.ThroughAll, h.Depth = "Tapped", False, 8
        model.commit(self.doc)
        tip = 2.1 / math.tan(math.radians(59))
        self.vol(8000 - PI * 2.1 ** 2 * 8 - PI * 2.1 ** 2 * tip / 3)
        self.assertEqual(h.Thread, "M5x0.8")

    def test_polygon_around_a_circle(self):
        import ProfileLib.RegularPolygon as rp
        from kovac import sketchtools
        sk = self.doc.addObject("Sketcher::SketchObject", "Poly")
        rp.makeRegularPolygon(sk, 6, V(0, 0, 0), V(10, 0, 0))
        self.assertEqual(sketchtools.circumscribe(sk, len(sk.Geometry) - 1), 6)
        self.doc.recompute()
        c = sk.Geometry[6]
        self.assertAlmostEqual(c.Radius, 10, 6)                                           # the drawn circle held
        self.assertAlmostEqual(c.Center.Length, 0, 6)
        for g in sk.Geometry[:6]:
            self.assertAlmostEqual(((g.StartPoint + g.EndPoint) * 0.5 - c.Center).Length, 10, 6)    # sides touch it
            self.assertAlmostEqual((g.StartPoint - c.Center).Length, 10 / math.cos(PI / 6), 6)

    # ---- modify
    def test_fillet_and_chamfer(self):
        self.plate()
        e = edge_ref(self.doc, self.body, vertical_edge_at(40, 20))
        f = self.ok(feature(self.doc, modify.Fillet, Edges=[e], Radius=2))
        self.vol(8000 - (1 - PI / 4) * 4 * 10)
        f.Suppressed = True
        model.commit(self.doc)
        self.vol(8000)
        e2 = edge_ref(self.doc, self.body, vertical_edge_at(0, 0))
        c = self.ok(feature(self.doc, modify.Chamfer, Edges=[e2], Distance=2))
        self.vol(8000 - 0.5 * 4 * 10)
        c.Mode, c.Distance2 = "Two distances", 3
        model.commit(self.doc)
        self.vol(8000 - 0.5 * 6 * 10)

    def test_fillet_groups_and_tangent_chain(self):
        self.plate()
        f = feature(self.doc, modify.Fillet, Edges=[edge_ref(self.doc, self.body, vertical_edge_at(40, 20))], Radius=2)
        rprop, eprop = modify.add_group(f)
        setattr(f, rprop, 4)
        setattr(f, eprop, [edge_ref(self.doc, self.body, vertical_edge_at(0, 0))])
        model.commit(self.doc)
        self.ok(f)
        self.vol(8000 - (1 - PI / 4) * (4 + 16) * 10)

    def test_whole_body_fillet(self):
        self.plate()
        self.ok(feature(self.doc, modify.Fillet, WholeBodies=[self.body.BodyId], Radius=1))
        self.assertEqual(len(self.body.Shape.Faces), 26)

    def test_shell_open_and_closed(self):
        self.plate()
        s = self.ok(feature(self.doc, modify.Shell, Faces=[self.top()], Thickness=2))
        self.vol(8000 - 36 * 16 * 8)
        s.Faces, s.Bodies = [], [self.body.BodyId]
        model.commit(self.doc)
        self.vol(8000 - 36 * 16 * 6)

    def test_shell_wall_as_thick_as_fillets(self):
        self.plate()
        edges = [edge_ref(self.doc, self.body, vertical_edge_at(x, y)) for x, y in ((0, 0), (40, 0), (40, 20), (0, 20))]
        feature(self.doc, modify.Fillet, Edges=edges, Radius=2, TangentChain=False)
        s = self.ok(feature(self.doc, modify.Shell, Faces=[self.top()], Thickness=2))
        outer = 8000 - 4 * (1 - PI / 4) * 4 * 10
        self.vol(outer - 36 * 16 * 8)          # inside corners come out sharp: radius 2 - wall 2 = 0
        self.assertEqual(s.Status, "")

    def test_face_pull_and_delete_face(self):
        self.plate()
        p = self.ok(feature(self.doc, modify.FacePull, Face=self.top(), Distance=3))
        self.vol(40 * 20 * 13)
        p.Distance = -3
        model.commit(self.doc)
        self.vol(40 * 20 * 7)
        p.Suppressed = True
        e = edge_ref(self.doc, self.body, vertical_edge_at(40, 20))
        feature(self.doc, modify.Fillet, Edges=[e], Radius=2)
        fil = face_ref(self.doc, self.body, lambda f: isinstance(f.Surface, Part.Cylinder))
        self.ok(feature(self.doc, modify.DeleteFace, Faces=[fil]))
        self.vol(8000)

    def test_draft(self):
        self.plate()
        sides = [face_ref(self.doc, self.body, lambda f, n=n: (normal(f) - n).Length < 1e-6)
                 for n in (V(1, 0, 0), V(-1, 0, 0), V(0, 1, 0), V(0, -1, 0))]
        bottom = face_ref(self.doc, self.body, lambda f: normal(f).z < -0.99)
        self.ok(feature(self.doc, modify.Draft, Faces=sides, Neutral=bottom, Angle=5))
        t = 10 * math.tan(math.radians(5))
        self.vol(10 / 6 * (800 + 4 * (40 - t) * (20 - t) + (40 - 2 * t) * (20 - 2 * t)), places=3)

    def test_body_operations(self):
        self.plate()
        sk = sketch(self.doc, rect(30, 5, 50, 15), name="Second")
        feature(self.doc, features.Extrude, Profile=sk, Length=10, Operation="New body")
        a, b = live_bodies(self.doc)
        c = self.ok(feature(self.doc, modify.Combine, Target=a.BodyId, Tools=[b.BodyId], Operation="Cut"))
        self.vol(8000 - 10 * 10 * 10, a)
        self.assertEqual(len(live_bodies(self.doc)), 1)
        miss = feature(self.doc, modify.SplitBody, Body=a.BodyId, Plane="YZ")   # x = 0 doesn't cross it
        self.assertEqual(miss.Status, "The plane does not cross the body.")
        self.vol(7000, a)                                                       # state passed through

    def test_split_move_scale_mirror(self):
        self.plate()
        d = feature(self.doc, datum.DatumPlane, Mode="Offset", Base="YZ", Offset=10)
        self.ok(feature(self.doc, modify.SplitBody, Body=self.body.BodyId, Plane=d.Name))
        vols = sorted(round(b.Shape.Volume) for b in live_bodies(self.doc))
        self.assertEqual(vols, [2000, 6000])
        ids = [b.BodyId for b in live_bodies(self.doc)]
        self.ok(feature(self.doc, modify.Transform, Bodies=[ids[1]], Move=App.Placement(V(0, 50, 0), App.Rotation()), Copy=True))
        self.assertEqual(len(live_bodies(self.doc)), 3)
        self.ok(feature(self.doc, modify.Scale, Bodies=[ids[0]], Factor=2))
        self.assertAlmostEqual(live_bodies(self.doc)[0].Shape.Volume, 8 * 6000, 4)
        self.ok(feature(self.doc, modify.Mirror, Bodies=[ids[1]], Plane="YZ", Join=False))
        self.assertEqual(len(live_bodies(self.doc)), 4)

    def test_patterns(self):
        self.plate()
        h = feature(self.doc, features.Hole, Face=self.top(), Positions=[V(5, 10, 10)], Size="M5", ThroughAll=True)
        p = self.ok(feature(self.doc, modify.Pattern, Sources=[h], Count1=4, Spacing1=10))
        self.vol(8000 - 4 * PI * 2.75 ** 2 * 10)
        p.Skip = [2]
        model.commit(self.doc)
        self.vol(8000 - 3 * PI * 2.75 ** 2 * 10)
        boss = sketch(self.doc, [("circle", (100, 0), 2)], name="Pin")
        pin = feature(self.doc, features.Extrude, Profile=boss, Length=5, Operation="New body")
        self.ok(feature(self.doc, modify.Pattern, Bodies=[pin.Name], Type="Circular", Axis="Z", Count=6))
        self.assertEqual(len(live_bodies(self.doc)), 7)

    def test_datum_planes_and_sketch_on_face(self):
        self.plate()
        pl = self.ok(feature(self.doc, datum.DatumPlane, Mode="Offset", Base=self.top(), Offset=0))
        sk = datum.sketch_on(self.doc, pl, "OnTop")
        sk.addGeometry(Part.Circle(V(20, 10, 0), V(0, 0, 1), 3))
        model.insert(self.doc, sk)
        b = self.ok(feature(self.doc, features.Extrude, Profile=sk, Length=4))
        self.assertEqual(b.ResolvedOperation, "Join (auto)")
        self.vol(8000 + PI * 9 * 4)
        self.ex.Length = 15                       # the sketch follows the top face
        model.commit(self.doc)
        self.vol(800 * 15 + PI * 9 * 4)


    def test_thread_marks_internal_and_external(self):
        sk = sketch(self.doc, [("circle", (0, 0), 4)])
        feature(self.doc, features.Extrude, Profile=sk, Length=20)
        self.body = live_bodies(self.doc)[0]
        cyl = face_ref(self.doc, self.body, lambda f: isinstance(f.Surface, Part.Cylinder))
        t = self.ok(feature(self.doc, modify.Thread, Faces=[cyl], Size="M8x1.25"))
        self.assertFalse(t.Internal)


if __name__ == "__main__":
    unittest.main()

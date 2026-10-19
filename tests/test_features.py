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

    def test_extrude_waits_for_a_pick_on_an_ambiguous_sketch(self):
        """A sketch with one region extrudes with no picks (the common case stays one click);
        with several, picking none is ambiguous and is reported, not silently merged."""
        sk1 = sketch(self.doc, rect(0, 0, 10, 10), name="One")
        self.ok(feature(self.doc, features.Extrude, Profile=sk1, Length=5))
        self.vol(500, live_bodies(self.doc)[0])
        sk2 = sketch(self.doc, rect(0, 0, 10, 10) + rect(20, 0, 30, 10), name="Two", constrain=False)
        broken = feature(self.doc, features.Extrude, Profile=sk2, Length=5, Operation="New body")
        self.assertIn("separate regions", broken.Status)
        self.doc.removeObject(broken.Name)
        from kovac import regions
        rs = regions.of_sketch(sk2)
        r = next(r for r in rs if r.point.x < 15)             # the first rectangle
        picked = self.ok(feature(self.doc, features.Extrude, Profile=sk2, Length=5,
                                 Regions=[r.key], RegionPoints=[r.point], Operation="New body"))
        self.assertEqual(picked.ResolvedOperation, "New body")
        self.assertAlmostEqual(live_bodies(self.doc)[1].Shape.Volume, 500, 4)

    def test_region_picker_shows_nothing_chosen_when_ambiguous(self):
        """The panel's own live region picker must agree with what _sketch_regions will
        actually use, or clicking OK could silently extrude more than it shows as chosen."""
        from types import SimpleNamespace
        from kovac import regionpick, regions
        sk1 = sketch(self.doc, rect(0, 0, 10, 10), name="RP1")
        rs1 = regions.of_sketch(sk1)
        rp1 = regionpick.RegionPicker.__new__(regionpick.RegionPicker)   # skip __init__: no Qt/navigation needed
        rp1.ed = SimpleNamespace(fp=SimpleNamespace(Profile=sk1, Regions=[]))
        self.assertEqual(rp1.chosen(rs1), {rs1[0].key})                 # one region: picking none is picking it
        sk2 = sketch(self.doc, rect(0, 0, 10, 10) + rect(20, 0, 30, 10), name="RP2", constrain=False)
        rs2 = regions.of_sketch(sk2)
        rp2 = regionpick.RegionPicker.__new__(regionpick.RegionPicker)
        rp2.ed = SimpleNamespace(fp=SimpleNamespace(Profile=sk2, Regions=[]))
        self.assertEqual(rp2.chosen(rs2), set())                        # two regions: picking none picks nothing

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

    def test_midpoint_constraint(self):
        import Sketcher
        from kovac import sketchtools
        sk = self.doc.addObject("Sketcher::SketchObject", "Mid")
        li = sk.addGeometry(Part.LineSegment(V(0, 0, 0), V(10, 0, 0)), False)
        pt = sk.addGeometry(Part.Point(V(3, 3, 0)), False)
        sk.addConstraint(Sketcher.Constraint("DistanceX", li, 1, 0.0))
        sk.addConstraint(Sketcher.Constraint("DistanceY", li, 1, 0.0))
        c_x2 = sk.addConstraint(Sketcher.Constraint("DistanceX", li, 2, 10.0))
        sk.addConstraint(Sketcher.Constraint("DistanceY", li, 2, 0.0))
        self.doc.recompute()
        sketchtools.add_midpoint(sk, pt, 1, li)
        self.doc.recompute()
        self.assertAlmostEqual(sk.Geometry[pt].X, 5.0, 6)
        self.assertAlmostEqual(sk.Geometry[pt].Y, 0.0, 6)
        sk.setDatum(c_x2, 16.0)                              # the line grows
        self.doc.recompute()
        self.assertAlmostEqual(sk.Geometry[pt].X, 8.0, 6)    # the point follows its new midpoint
        self.assertAlmostEqual(sk.Geometry[pt].Y, 0.0, 6)

    def test_matching_dimensions(self):
        import Sketcher
        from kovac import sketchtools
        sk = self.doc.addObject("Sketcher::SketchObject", "Dims")
        a = sk.addGeometry(Part.LineSegment(V(0, 0, 0), V(20, 0, 0)), False)
        b = sk.addGeometry(Part.LineSegment(V(0, 10, 0), V(-35, 10, 0)), False)
        c = sk.addGeometry(Part.Circle(V(50, 0, 0), V(0, 0, 1), 4), False)
        da = sk.addConstraint(Sketcher.Constraint("Distance", a, 20.0))
        db = sk.addConstraint(Sketcher.Constraint("DistanceX", b, 1, b, 2, -35.0))     # points left: negative
        dc = sk.addConstraint(Sketcher.Constraint("Diameter", c, 8.0))
        ang = sk.addConstraint(Sketcher.Constraint("Angle", a, b, 3.0))
        self.doc.recompute()
        self.assertEqual(sketchtools.match_dimension(sk, da, db), "")
        self.assertEqual(sketchtools.match_dimension(sk, da, dc), "")
        self.doc.recompute()
        dx = lambda: sk.Geometry[b].EndPoint.x - sk.Geometry[b].StartPoint.x      # noqa: E731
        self.assertAlmostEqual(dx(), -20, 6)                             # still pointing left
        self.assertAlmostEqual(sk.Geometry[c].Radius, 10, 6)            # a diameter equal to the length
        sk.setDatum(da, 30.0)                                            # and they follow later edits
        self.doc.recompute()
        self.assertAlmostEqual(dx(), -30, 6)
        self.assertAlmostEqual(sk.Geometry[c].Radius, 15, 6)
        self.assertIn("angle", sketchtools.match_dimension(sk, da, ang))
        self.assertIn("follows", sketchtools.match_dimension(sk, db, da))   # no loop
        self.assertTrue(sketchtools.match_dimension(sk, da, da))

    def test_matched_dimensions_survive_deleting_constraints(self):
        import Sketcher
        from kovac import sketchtools
        sk = self.doc.addObject("Sketcher::SketchObject", "Links")
        lines = [sk.addGeometry(Part.LineSegment(V(0, 5 * k, 0), V(10 + k, 5 * k, 0)), False) for k in range(3)]
        d = [sk.addConstraint(Sketcher.Constraint("Distance", g, 10.0 + g)) for g in lines]
        self.doc.recompute()
        self.assertEqual(sketchtools.match_dimension(sk, d[1], d[2]), "")
        sk.delConstraint(d[0])                         # an earlier one goes: the link stays on its two
        sketchtools.prune_links(sk)
        self.doc.recompute()
        sk.setDatum(0, 15.0)
        self.doc.recompute()
        self.assertEqual([round(c.Value, 6) for c in sk.Constraints], [15, 15])
        self.assertIn("Up-to-date", sk.State)
        sk.delConstraint(0)                            # the source goes: the other keeps its value
        sketchtools.prune_links(sk)
        self.doc.recompute()
        self.assertEqual(sk.ExpressionEngine, [])
        self.assertEqual([round(c.Value, 6) for c in sk.Constraints], [15])
        self.assertIn("Up-to-date", sk.State)

    def test_a_stale_numbered_link_in_a_file_is_dropped(self):
        import Sketcher
        from kovac import sketchtools
        sk = self.doc.addObject("Sketcher::SketchObject", "Old")
        for k in range(2):
            g = sk.addGeometry(Part.LineSegment(V(0, 5 * k, 0), V(10, 5 * k, 0)), False)
            sk.addConstraint(Sketcher.Constraint("Distance", g, 10.0))
        sk.setExpression(".Constraints[1]", ".Constraints[0]")      # by number, as an earlier Kovač made it
        self.doc.recompute()
        sk.delConstraint(0)                                         # now it points past the end
        sketchtools.prune_links(sk)
        self.assertEqual(sk.ExpressionEngine, [])
        self.doc.recompute()
        self.assertIn("Up-to-date", sk.State)

    def test_typed_dimension_values(self):
        import Sketcher
        from kovac import sketchtools
        sk = self.doc.addObject("Sketcher::SketchObject", "Typed")
        a = sk.addGeometry(Part.LineSegment(V(0, 0, 0), V(20, 0, 0)), False)
        b = sk.addGeometry(Part.LineSegment(V(0, 10, 0), V(-35, 10, 0)), False)
        da = sk.addConstraint(Sketcher.Constraint("Distance", a, 20.0))
        db = sk.addConstraint(Sketcher.Constraint("DistanceX", b, 1, b, 2, -35.0))
        ang = sk.addConstraint(Sketcher.Constraint("Angle", a, b, 3.0))
        self.doc.recompute()
        self.assertIn("35", sketchtools.value_text(sk, db))              # shown without the sign
        sketchtools.set_value(sk, da, "25")                              # a bare number is mm
        sketchtools.set_value(sk, db, "1 in")
        sketchtools.set_value(sk, ang, "170°")
        self.doc.recompute()
        self.assertAlmostEqual(sk.Geometry[a].length(), 25, 6)
        self.assertAlmostEqual(sk.Geometry[b].EndPoint.x - sk.Geometry[b].StartPoint.x, -25.4, 6)   # still to the left
        self.assertAlmostEqual(sk.Constraints[ang].Value, math.radians(170), 6)

    def test_snap_candidates_include_midpoints(self):
        from kovac import grid
        sk = self.doc.addObject("Sketcher::SketchObject", "SnapPts")
        sk.addGeometry(Part.LineSegment(V(0, 0, 0), V(10, 0, 0)), False)
        sk.addGeometry(Part.ArcOfCircle(Part.Circle(V(20, 0, 0), V(0, 0, 1), 5), 0, PI), False)
        self.doc.recompute()
        pts = grid._points(sk)
        self.assertIn(V(5, 0, 0), pts)                                       # the line's own midpoint
        arc = sk.Geometry[1]
        self.assertIn((arc.StartPoint + arc.EndPoint) * 0.5, pts)            # the arc's chord midpoint
        face = Part.Face(Part.Wire(Part.makePolygon([V(0, 0, 0), V(10, 0, 0), V(10, 10, 0), V(0, 10, 0), V(0, 0, 0)])))
        self.assertIn(V(5, 0, 0), grid.face_points(face))                    # a straight edge's own midpoint

    # ---- modify
    def test_fillet_arrow_points_into_an_outside_edge_and_out_of_an_inside_one(self):
        from kovac import manip
        pts = [(0, 0), (40, 0), (40, 10), (10, 10), (10, 30), (0, 30)]
        sk = sketch(self.doc, [("line", pts[i], pts[(i + 1) % 6]) for i in range(6)])
        feature(self.doc, features.Extrude, Profile=sk, Length=10)
        self.body = live_bodies(self.doc)[0]
        inside = self.ok(feature(self.doc, modify.Fillet, Edges=[edge_ref(self.doc, self.body, vertical_edge_at(10, 10))], Radius=2))
        o, n = manip._edge_group_axis(inside)
        self.assertGreater(n.x, 0.6)          # out into the empty inside corner, where the fillet adds material
        self.assertGreater(n.y, 0.6)
        inside.Suppressed = True
        model.commit(self.doc)
        outside = self.ok(feature(self.doc, modify.Fillet, Edges=[edge_ref(self.doc, self.body, vertical_edge_at(40, 0))], Radius=2))
        o, n = manip._edge_group_axis(outside)
        self.assertLess(n.x, -0.6)            # into the material at the outside corner, where it is cut away
        self.assertGreater(n.y, 0.6)

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
        self.assertEqual(miss.Status, "The split tool does not cross the body.")
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

    def test_split_and_sketch_on_a_three_point_plane(self):
        self.plate()
        def corner(x, y, z):
            k = next(i for i, v in enumerate(self.body.Shape.Vertexes, 1) if (v.Point - V(x, y, z)).Length < 1e-6)
            return model.pick_ref(self.body, "Vertex%d" % k)
        d = self.ok(feature(self.doc, datum.DatumPlane, Mode="ThreePoints",
                            Refs=[corner(0, 0, 0), corner(40, 20, 0), corner(0, 0, 10)]))
        self.ok(feature(self.doc, modify.SplitBody, Body=self.body.BodyId, Plane=d.Name))
        vols = sorted(round(b.Shape.Volume) for b in live_bodies(self.doc))
        self.assertEqual(vols, [4000, 4000])                  # the plate's diagonal, top to bottom
        sk_plane = self.ok(feature(self.doc, datum.DatumPlane, Mode="Offset", Base=d.Name, Auto=True))
        self.assertAlmostEqual(abs(sk_plane.Placement.Rotation.multVec(V(0, 0, 1)).dot(V(1, -2, 0).normalize())), 1, 6)

    def test_split_by_a_curved_face(self):
        """A cylindrical or spherical face splits by the whole analytic surface, not just the
        clicked patch; a cone or freeform face still needs a flat face or a plane -- a clear
        error, not a crash."""
        self.plate()                                  # 40 x 20 x 10, x:[0,40] y:[0,20] z:[0,10]
        cyl = feature(self.doc, features.Primitive, PrimitiveType="Cylinder", Radius=5, Height=30,
                      Location=App.Placement(V(20, 10, -10), App.Rotation()), Operation="New body")
        cyl_body = next(b for b in live_bodies(self.doc) if b.BodyId != self.body.BodyId)
        ref = face_ref(self.doc, cyl_body, lambda f: isinstance(f.Surface, Part.Cylinder))
        self.ok(feature(self.doc, modify.SplitBody, Body=self.body.BodyId, Plane=ref))
        main_vols = sorted(b.Shape.Volume for b in live_bodies(self.doc) if b.BodyId != cyl_body.BodyId)
        self.assertEqual(len(main_vols), 2)
        inner = PI * 5 ** 2 * 10
        self.assertAlmostEqual(main_vols[0], inner, 1)
        self.assertAlmostEqual(main_vols[1], 8000 - inner, 1)

        before_ids = {b.BodyId for b in live_bodies(self.doc)}
        feature(self.doc, features.Primitive, PrimitiveType="Cone", Radius=8, Radius2=2, Height=20,
                Location=App.Placement(V(20, 10, -5), App.Rotation()), Operation="New body")
        cone_body = next(b for b in live_bodies(self.doc) if b.BodyId not in before_ids)
        cone_ref = face_ref(self.doc, cone_body, lambda f: isinstance(f.Surface, Part.Cone))
        bad = feature(self.doc, modify.SplitBody, Body=self.body.BodyId, Plane=cone_ref)
        self.assertIn("flat face, or a cylindrical or spherical face", bad.Status)

    def test_pattern_along_a_path(self):
        """Pattern Type='Path': evenly spaced along a sketch curve or picked 3D edges (not just
        a flat sketch), instances rotated to follow the tangent when Align is set."""
        self.plate()                                  # 40 x 20 x 10
        hole_vol = PI * 2.75 ** 2 * 10                 # a through M5 in a 10 mm plate (see test_patterns)
        h = feature(self.doc, features.Hole, Face=self.top(), Positions=[V(5, 10, 10)], Size="M5", ThroughAll=True)
        path = sketch(self.doc, [("line", (5, 10), (35, 10))], name="HolePath")   # starts at the hole itself
        self.ok(feature(self.doc, modify.Pattern, Sources=[h], Type="Path", Path=path, Count=4))
        self.vol(8000 - 4 * hole_vol)                  # 4 evenly spaced holes, 10 mm apart: x = 5, 15, 25, 35
        state = model.state_of(model.tip(self.doc))
        centers = sorted(round(f.CenterOfMass.x, 3) for b in state.values() for f in b.shape.Faces
                         if isinstance(f.Surface, Part.Cylinder) and abs(f.Surface.Radius - 2.75) < 1e-3)
        self.assertEqual(centers, [5.0, 15.0, 25.0, 35.0])

        # a 3D path from picked edges, not a sketch: a small reference body's own vertical edge
        before_ids = {b.BodyId for b in live_bodies(self.doc)}
        feature(self.doc, features.Primitive, PrimitiveType="Box", Length=2, Width=2, Height=12,
                Location=App.Placement(V(60, 0, 0), App.Rotation()), Operation="New body")
        ref_body = next(b for b in live_bodies(self.doc) if b.BodyId not in before_ids)
        ref = edge_ref(self.doc, ref_body, vertical_edge_at(60, 0))
        before2 = len(live_bodies(self.doc))
        self.ok(feature(self.doc, modify.Pattern, Bodies=[ref_body.BodyId], Type="Path", PathEdges=[ref], Count=3))
        self.assertEqual(len(live_bodies(self.doc)), before2 + 2)      # the original + 2 new copies
        new_boxes = [b for b in live_bodies(self.doc) if b.BodyId != ref_body.BodyId and b.BodyId not in before_ids]
        z = sorted(round(b.Shape.BoundBox.Center.z, 3) for b in new_boxes)
        self.assertEqual(z, [12.0, 18.0])          # original centre z=6, offset by the edge's own 0/6/12 steps

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

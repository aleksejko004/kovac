# SPDX-License-Identifier: LGPL-2.1-or-later
"""Move: bodies about their centre, construction planes set free, sketch points and lines (headless)."""
import math
import unittest

import FreeCAD as App
import Part

from helpers import feature, live_bodies, rect, sketch
from kovac import datum, features, model, modify, move

V = App.Vector


class Move(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("Mv")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_body_turns_about_its_own_centre(self):
        sk = sketch(self.doc, rect(100, 0, 140, 20))
        feature(self.doc, features.Extrude, Profile=sk, Length=10)
        b = live_bodies(self.doc)[0]
        c0 = b.Shape.BoundBox.Center
        t = feature(self.doc, modify.Transform, Bodies=[b.BodyId], Pivot=c0,
                    Move=App.Placement(V(0, 0, 5), App.Rotation(V(0, 0, 1), 90)))
        self.assertEqual(t.Status, "", t.Status)
        bb = live_bodies(self.doc)[0].Shape.BoundBox
        self.assertLess((bb.Center - (c0 + V(0, 0, 5))).Length, 1e-6)       # turned in place, then lifted
        self.assertAlmostEqual(bb.XLength, 20, 6)
        self.assertAlmostEqual(bb.YLength, 40, 6)

    def test_plane_drops_where_it_is_moved(self):
        pl = feature(self.doc, datum.DatumPlane, Mode="Offset", Base="XY", Offset=10)
        tgt = move.PlaneTarget(pl)
        tgt.begin()
        tgt.translate(0, 25)
        model.commit(self.doc)
        self.assertEqual(pl.Mode, "Free")
        self.assertLess((pl.Placement.Base - V(25, 0, 10)).Length, 1e-9)
        tgt.begin()
        tgt.rotate(0, 90)
        model.commit(self.doc)
        self.assertLess((pl.Placement.Rotation.multVec(V(0, 0, 1)) - V(0, -1, 0)).Length, 1e-9)

    def test_sketch_line_slides_and_a_point_turns(self):
        sk = sketch(self.doc, [("line", (0, 0), (10, 0)), ("line", (20, 0), (30, 0))], constrain=False)
        tgt = move.SketchTarget(sk, [(0, 0)])            # the whole first line
        tgt.begin()
        tgt.translate(1, 5)
        self.assertLess((sk.Geometry[0].StartPoint - V(0, 5, 0)).Length, 1e-9)
        self.assertLess((sk.Geometry[1].StartPoint - V(20, 0, 0)).Length, 1e-9)   # the other line stays
        tgt = move.SketchTarget(sk, [(1, 2)])            # the second line's end point
        tgt.begin()
        tgt.rotate(2, 90)                               # about itself: stays put
        self.assertLess((sk.Geometry[1].EndPoint - V(30, 0, 0)).Length, 1e-6)
        tgt.translate(0, -5)
        self.assertLess((sk.Geometry[1].EndPoint - V(25, 0, 0)).Length, 1e-6)
        self.assertLess((sk.Geometry[1].StartPoint - V(20, 0, 0)).Length, 1e-6)

    def test_sketch_corner_lifts_out_of_the_plane(self):
        sk = sketch(self.doc, rect(0, 0, 20, 10), constrain=False)
        corner = next((i, 2) for i, g in enumerate(sk.Geometry) if (g.EndPoint - V(20, 0, 0)).Length < 1e-9)
        tgt = move.SketchTarget(sk, [corner])
        tgt.begin(("t", 2))
        tgt.translate(2, 5)
        self.assertEqual(len(sk.Geometry), 2)                    # the two lines at that corner left the sketch
        curves = [c for c, _ in tgt.lifted]
        self.assertEqual(len(curves), 2)
        for c in curves:
            ends = [V(p) for p in c.Points]
            self.assertTrue(any((p - V(20, 0, 5)).Length < 1e-9 for p in ends), ends)   # the corner, lifted
            self.assertTrue(any(abs(p.z) < 1e-9 for p in ends), ends)                   # their other ends stay
        tgt.begin(("t", 0))                                      # later drags keep moving it in 3D
        tgt.translate(0, 3)
        self.assertTrue(any((V(p) - V(23, 0, 5)).Length < 1e-9 for p in curves[0].Points))

    def test_an_arc_keeps_its_shape_out_of_the_plane(self):
        import math as m
        sk = self.doc.addObject("Sketcher::SketchObject", "A")
        sk.addGeometry(Part.ArcOfCircle(Part.Circle(V(0, 0, 0), V(0, 0, 1), 10), 0, m.pi / 2))
        self.doc.recompute()
        tgt = move.SketchTarget(sk, [(0, 0)])
        tgt.begin(("t", 2))
        tgt.translate(2, 4)
        c = tgt.lifted[0][0]
        e = c.Shape.Edges[0]
        for t in (0.2, 0.5, 0.8):
            q = e.valueAt(e.FirstParameter + t * (e.LastParameter - e.FirstParameter))
            self.assertAlmostEqual(m.hypot(q.x, q.y), 10, 6)
            self.assertAlmostEqual(q.z, 4, 9)

class MoveFaceTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("MF")
        self.sk = sketch(self.doc, rect(0, 0, 40, 20))
        feature(self.doc, features.Extrude, Profile=self.sk, Length=10)
        self.body = live_bodies(self.doc)[0]

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def face(self, pred):
        from helpers import face_ref
        return face_ref(self.doc, self.body, pred)

    def test_top_face_tilts(self):
        import math
        from helpers import normal
        top = self.face(lambda f: normal(f).z > 0.99)
        mf = feature(self.doc, modify.MoveFace, Face=top, Pivot=V(20, 10, 10),
                     Move=App.Placement(V(), App.Rotation(V(0, 1, 0), 10)))
        self.assertEqual(mf.Status, "", mf.Status)
        b = live_bodies(self.doc)[0].Shape
        self.assertTrue(b.isValid())
        self.assertAlmostEqual(b.Volume, 8000, 3)                       # tilted about its middle: same volume
        self.assertAlmostEqual(b.BoundBox.ZMax, 10 + 20 * math.tan(math.radians(10)), 4)

    def test_hole_slides_and_tilts(self):
        from kovac import model as mdl
        cut = sketch(self.doc, [("circle", (10, 10), 3)], name="H")
        feature(self.doc, features.Extrude, Profile=cut, Length=10, Operation="Cut")
        self.body = live_bodies(self.doc)[0]
        before = self.body.Shape.Volume
        wall = self.face(lambda f: isinstance(f.Surface, Part.Cylinder))
        mf = feature(self.doc, modify.MoveFace, Face=wall, Pivot=V(10, 10, 5), Move=App.Placement(V(8, 0, 0), App.Rotation()))
        self.assertEqual(mf.Status, "", mf.Status)
        b = live_bodies(self.doc)[0].Shape
        self.assertAlmostEqual(b.Volume, before, 3)
        self.assertTrue(b.isInside(V(10, 10, 5), 1e-6, False))          # the old place filled in
        self.assertFalse(b.isInside(V(18, 10, 5), 1e-6, False))         # the hole is here now
        mf.Move = App.Placement(V(8, 0, 0), App.Rotation(V(0, 1, 0), 20))
        mdl.commit(self.doc)
        self.assertEqual(mf.Status, "", mf.Status)
        b = live_bodies(self.doc)[0].Shape
        self.assertTrue(b.isValid())
        for z in (0.2, 9.8):                                            # still open at both ends
            x = 18 + (z - 5) * math.tan(math.radians(20))
            self.assertFalse(b.isInside(V(x, 10, z), 1e-6, False), z)


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: LGPL-2.1-or-later
"""Move: bodies about their centre, construction planes set free, sketch points and lines (headless)."""
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


if __name__ == "__main__":
    unittest.main()

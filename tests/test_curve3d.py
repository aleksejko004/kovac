# SPDX-License-Identifier: LGPL-2.1-or-later
"""3D curves: shape, conversion from a sketch, use as a sweep path (headless)."""
import unittest

import FreeCAD as App
import Part

from helpers import feature, live_bodies, rect, sketch
from kovac import curve3d, features

V = App.Vector


class Curve3D(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("C3")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_open_curve_runs_through_its_end_points_and_leaves_the_plane(self):
        pts = [V(0, 0, 0), V(10, 0, 5), V(20, 10, 15), V(30, 10, 0)]
        c = curve3d.create(self.doc, pts)
        e = c.Shape.Edges[0]
        self.assertLess((e.valueAt(e.FirstParameter) - pts[0]).Length, 1e-9)
        self.assertLess((e.valueAt(e.LastParameter) - pts[-1]).Length, 1e-9)
        self.assertGreater(c.Shape.BoundBox.ZLength, 5)
        c.Closed = True
        self.doc.recompute()
        self.assertTrue(c.Shape.Edges[0].isClosed())

    def test_free_spline_moves_out_of_the_sketch(self):
        sk = sketch(self.doc, rect(0, 0, 5, 5), name="S")
        n = len(sk.Geometry)
        poles = [V(0, 0, 0), V(10, 10, 0), V(20, -10, 0), V(30, 0, 0)]
        sk.addGeometry(Part.BSplineCurve(poles, None, None, False, 3, None, False))
        self.doc.recompute()
        self.assertEqual(curve3d.free_splines(sk), [n])
        made = curve3d.from_sketch(sk)
        self.assertEqual(len(made), 1)
        self.assertEqual(len(sk.Geometry), n)                      # the rectangle stays
        self.assertEqual([V(p) for p in made[0].Points], poles)

    def test_sweep_along_a_3d_curve(self):
        path = curve3d.create(self.doc, [V(0, 0, 0), V(0, 0, 20), V(20, 0, 40), V(40, 20, 50)])
        prof = sketch(self.doc, rect(-2, -2, 2, 2), name="P")
        sw = feature(self.doc, features.Sweep, Profile=prof, Path=path)
        self.assertEqual(sw.Status, "", sw.Status)
        b = live_bodies(self.doc)[0]
        self.assertTrue(b.Shape.isValid())
        self.assertGreater(b.Shape.BoundBox.ZMax, 45)
        self.assertGreater(b.Shape.BoundBox.YMax, 15)


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: LGPL-2.1-or-later
"""Sketch offset for curves the sketcher's own Offset cannot hold (B-splines, ellipses)."""
import unittest

import FreeCAD as App
import Part

from kovac import sketchoffset

V = App.Vector


def spline(*pts):
    b = Part.BSplineCurve()
    b.buildFromPoles(list(pts))
    return b


def gap(geo, base, d):
    """Worst error of geo's distance to base against d, sampled along geo."""
    e, b = geo.toShape(), base.toShape() if hasattr(base, "toShape") else base
    us = [geo.FirstParameter + (geo.LastParameter - geo.FirstParameter) * k / 40 for k in range(41)]
    return max(abs(Part.Vertex(geo.value(u)).distToShape(b)[0] - d) for u in us)


class SketchOffsetTests(unittest.TestCase):
    def test_a_spline_offsets_to_a_spline_at_the_distance(self):
        s = spline(V(0, 0, 0), V(10, 20, 0), V(30, -10, 0), V(40, 10, 0))
        for d in (3, -3):
            out = sketchoffset.offset([s], d)
            self.assertEqual(len(out), 1)
            self.assertIsInstance(out[0], Part.BSplineCurve)
            self.assertLess(gap(out[0], s, 3), 1e-3)
        a, b = sketchoffset.offset([s], 3)[0], sketchoffset.offset([s], -3)[0]
        self.assertGreater((a.value(a.FirstParameter) - b.value(b.FirstParameter)).Length, 5.9)   # opposite sides

    def test_an_ellipse_offsets_to_a_closed_spline(self):
        el = Part.Ellipse(V(0, 0, 0), 20, 10)
        out = sketchoffset.offset([el], 2)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].isClosed())
        self.assertLess(gap(out[0], el, 2), 1e-3)

    def test_a_chain_stays_joined_round_outside_and_trimmed_inside(self):
        # a line into a spline at a corner: one side opens a gap (rounded), the other overlaps (trimmed)
        ln = Part.LineSegment(V(-20, 0, 0), V(0, 0, 0))
        s = spline(V(0, 0, 0), V(5, 10, 0), V(15, 15, 0), V(25, 15, 0))
        base = Part.Wire([ln.toShape(), s.toShape()])
        for d in (2, -2):
            out = sketchoffset.offset([ln, s], d)
            w = Part.Wire(Part.__sortEdges__([g.toShape() for g in out]))
            self.assertEqual(len(w.Edges), len(out), "pieces join end to end")
            us = [(e, e.FirstParameter + (e.LastParameter - e.FirstParameter) * k / 20) for e in w.Edges for k in range(21)]
            worst = max(abs(Part.Vertex(e.valueAt(u)).distToShape(base)[0] - 2) for e, u in us)
            self.assertLess(worst, 1e-3)
        kinds = [type(g).__name__ for g in sketchoffset.offset([ln, s], 2) + sketchoffset.offset([ln, s], -2)]
        self.assertIn("ArcOfCircle", kinds)       # the outside corner is rounded on one of the sides

    def test_added_to_a_sketch_with_joins_coincident(self):
        doc = App.newDocument("OffsetT")
        try:
            sk = doc.addObject("Sketcher::SketchObject", "S")
            ln = Part.LineSegment(V(-20, 0, 0), V(0, 0, 0))
            s = spline(V(0, 0, 0), V(5, 10, 0), V(15, 15, 0), V(25, 15, 0))
            ids = sketchoffset.add_to(sk, sketchoffset.offset([ln, s], 2))
            doc.recompute()
            self.assertGreaterEqual(len(ids), 2)
            self.assertTrue(any(c.Type == "Coincident" for c in sk.Constraints))
            self.assertTrue(sk.Shape.isValid())
        finally:
            App.closeDocument(doc.Name)


if __name__ == "__main__":
    unittest.main()

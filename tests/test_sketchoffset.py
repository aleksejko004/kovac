# SPDX-License-Identifier: LGPL-2.1-or-later
"""Sketch offset for curves the sketcher's own Offset cannot hold (B-splines, ellipses)."""
import math
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

    def rect(self):
        c = [V(0, 0, 0), V(40, 0, 0), V(40, 20, 0), V(0, 20, 0)]
        return [Part.LineSegment(c[k], c[(k + 1) % 4]) for k in range(4)]

    def test_sharp_corners_keep_a_rectangle_a_rectangle(self):
        for d in (3, -3):                         # either side: one is the outside
            out = sketchoffset.offset(self.rect(), d, "Sharp corners")
            self.assertTrue(all(isinstance(g, Part.LineSegment) for g in out))
            self.assertEqual(len(out), 4)
            bb = Part.Wire(Part.__sortEdges__([g.toShape() for g in out])).BoundBox
            grown = abs(bb.XLength - 40) - 6
            self.assertLess(abs(grown), 1e-6, (bb.XLength, bb.YLength))
            self.assertLess(abs(abs(bb.YLength - 20) - 6), 1e-6)
        rounded = sketchoffset.offset(self.rect(), 3) + sketchoffset.offset(self.rect(), -3)
        self.assertEqual(sum(isinstance(g, Part.ArcOfCircle) for g in rounded), 4)   # round: the outside one has 4 arcs

    def test_sharp_corners_on_a_spline_chain_meet_without_arcs(self):
        ln = Part.LineSegment(V(-20, 0, 0), V(0, 0, 0))
        s = spline(V(0, 0, 0), V(5, 10, 0), V(15, 15, 0), V(25, 15, 0))
        for d in (2, -2):
            out = sketchoffset.offset([ln, s], d, "Sharp corners")
            self.assertFalse(any(isinstance(g, Part.ArcOfCircle) for g in out))
            w = Part.Wire(Part.__sortEdges__([g.toShape() for g in out]))
            self.assertEqual(len(w.Edges), len(out), "pieces join end to end")
            self.assertTrue(any(isinstance(g, Part.BSplineCurve) and gap(g, s, 2) < 1e-3 for g in out))

    def test_sharp_corners_on_arcs_extend_the_arc(self):
        a = Part.ArcOfCircle(Part.Circle(V(0, 0, 0), V(0, 0, 1), 10), 0, math.pi / 2)        # (10,0) -> (0,10)
        ln = Part.LineSegment(V(0, 10, 0), V(-20, 10, 0))                                    # a corner at (0,10)
        for d in (2, -2):
            out = sketchoffset.offset([a, ln], d, "Sharp corners")
            self.assertEqual(len(out), 2)
            w = Part.Wire(Part.__sortEdges__([g.toShape() for g in out]))
            self.assertEqual(len(w.Edges), 2)

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

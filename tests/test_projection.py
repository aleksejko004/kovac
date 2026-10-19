# SPDX-License-Identifier: LGPL-2.1-or-later
"""Edges projected into a sketch from a body: no dependency loop, and they stay put (headless)."""
import os
import unittest

import FreeCAD as App

from helpers import feature, live_bodies, rect, sketch
from kovac import features, model, projection

V = App.Vector
HERE = os.path.dirname(os.path.abspath(__file__))


def top_face(body):
    top = body.Shape.BoundBox.ZMax
    return next("Face%d" % k for k, f in enumerate(body.Shape.Faces, 1)
                if abs(f.BoundBox.ZMin - top) < 1e-9 and abs(f.BoundBox.ZMax - top) < 1e-9)


class Projection(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("P")
        self.sk = sketch(self.doc, rect(0, 0, 20, 10), name="Base")
        self.ex = feature(self.doc, features.Extrude, Profile=self.sk, Length=5)
        self.body = live_bodies(self.doc)[0]

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def projected_sketch(self):
        """A sketch on the top, with the top face's outline projected, its own square inside."""
        sk2 = sketch(self.doc, rect(5, 2, 15, 8), App.Placement(V(0, 0, 5), App.Rotation()), name="OnTop")
        sk2.addExternal(self.body.Name, top_face(self.body))
        model.commit(self.doc)
        return sk2

    def test_extruding_a_sketch_with_projected_edges_makes_no_loop(self):
        sk2 = self.projected_sketch()
        n = len(sk2.ExternalGeo)
        ex2 = feature(self.doc, features.Extrude, Profile=sk2, Length=3)
        self.assertEqual(ex2.Status, "")
        self.assertFalse(any(o.isValid() is False for o in (sk2, ex2)))
        self.assertNotIn(self.body, sk2.OutListRecursive)                 # no loop through the body
        self.assertEqual(len(sk2.ExternalGeo), n)                         # the projection is still there
        vols = sorted(round(b.Shape.Volume) for b in live_bodies(self.doc))
        self.assertIn(1000 + 3 * 60, vols + [round(self.body.Shape.Volume)])   # the square was added on top

    def test_projection_ignores_later_steps(self):
        sk2 = self.projected_sketch()
        feature(self.doc, features.Extrude, Profile=sk2, Length=3)
        (at,) = [o for o, _ in sk2.ExternalGeometry]
        self.assertTrue(projection.is_body_at(at))
        self.assertAlmostEqual(at.Shape.Volume, 1000, 6)                  # the body before the sketch
        self.ex.Length = 8                                                # an earlier step changes: it follows
        model.commit(self.doc)
        self.assertAlmostEqual(at.Shape.Volume, 1600, 6)

    def test_a_loop_already_in_a_file_is_repaired(self):
        sk2 = sketch(self.doc, rect(5, 2, 15, 8), App.Placement(V(0, 0, 5), App.Rotation()), name="OnTop")
        sk2.addExternal(self.body.Name, top_face(self.body))              # as an older Kovač left it:
        ex2 = model.create(self.doc, features.Extrude, Profile=sk2, Length=3)   # then extruded
        model.relink(self.doc)                # (no recompute here: on one FreeCAD drops the looping link)
        self.assertIn(self.body, sk2.OutList)                             # the loop: body -> extrude -> sketch -> body
        model.commit(self.doc)
        self.assertNotIn(self.body, sk2.OutListRecursive)
        self.assertEqual(ex2.Status, "")
        self.assertEqual(len(sk2.ExternalGeo) - 2, 4)                     # the 4 top edges (after the 2 axes)

    def test_repair_keeps_constraints_on_projected_edges(self):
        import Part
        import Sketcher
        sk2 = sketch(self.doc, rect(5, 2, 15, 8), App.Placement(V(0, 0, 5), App.Rotation()), name="OnTop")
        sk2.addExternal(self.body.Name, top_face(self.body))
        self.doc.recompute()
        corner = sk2.ExternalGeo[2].StartPoint
        p = sk2.addGeometry(Part.Point(corner + V(1, 1, 0)))
        sk2.addConstraint(Sketcher.Constraint("Coincident", p, 1, -3, 1))      # pinned to a projected corner
        ex2 = model.create(self.doc, features.Extrude, Profile=sk2, Length=3)
        model.relink(self.doc)
        n = len(sk2.Constraints)
        model.commit(self.doc)
        self.assertEqual(ex2.Status, "")
        self.assertEqual(len(sk2.Constraints), n)
        pin = sk2.Constraints[-1]
        self.assertEqual((pin.Type, pin.First), ("Coincident", p))
        self.assertLess((sk2.getPoint(p, 1) - corner).Length, 1e-6)

    def test_a_feature_never_goes_before_its_own_sketch(self):
        sk2 = sketch(self.doc, rect(5, 2, 15, 8), App.Placement(V(0, 0, 5), App.Rotation()), name="OnTop")
        its = model.items(self.doc)
        with self.assertRaises(ValueError):                  # the marker is before the sketch
            model.set_rollback(self.doc, its.index(sk2))
            model.create(self.doc, features.Extrude, Profile=sk2, Length=3)
        self.assertFalse([o for o in self.doc.Objects if o.Name.startswith("Extrude") and o is not self.ex])
        model.set_rollback(self.doc, len(model.items(self.doc)))
        ex2 = model.create(self.doc, features.Extrude, Profile=sk2, Length=3, index=its.index(sk2))
        its = model.items(self.doc)
        self.assertGreater(its.index(ex2), its.index(sk2))   # asked for a place before it: goes after

    def test_a_feature_before_its_sketch_in_a_file_is_moved_after_it(self):
        sk2 = sketch(self.doc, rect(5, 2, 15, 8), App.Placement(V(0, 0, 5), App.Rotation()), name="OnTop")
        ex2 = model.create(self.doc, features.Extrude, Profile=sk2, Length=3)
        h = model.history(self.doc)
        its = list(h.Features)
        its.remove(ex2)
        its.insert(its.index(sk2), ex2)                       # as an older Kovač could leave it
        h.Features = its
        model.commit(self.doc)
        its = model.items(self.doc)
        self.assertGreater(its.index(ex2), its.index(sk2))
        self.assertEqual(ex2.Status, "")
        self.assertAlmostEqual(self.body.Shape.Volume, 1000 + 3 * 60, 6)

    def sketch_on_top(self, geometry):
        """A sketch on the top face as Kovač makes one: the face's outline projected into it."""
        sk2 = sketch(self.doc, geometry, App.Placement(V(0, 0, 5), App.Rotation()), name="OnTop")
        model.insert(self.doc, sk2)
        projection.project(sk2, self.body, top_face(self.body))
        model.commit(self.doc)
        return sk2

    def test_a_sketch_on_a_face_gets_the_face_outline(self):
        sk2 = self.sketch_on_top([])
        (at,) = [o for o, _ in sk2.ExternalGeometry]
        self.assertTrue(projection.is_body_at(at))
        self.assertEqual(len(sk2.ExternalGeo) - 2, 4)
        self.assertEqual(sk2.Shape.Edges, [])                              # not part of the sketch's own shape

    def test_a_line_across_the_face_makes_two_sections_to_extrude(self):
        from kovac import regions
        sk2 = self.sketch_on_top([("line", (10, 0), (10, 10))])
        rs = regions.of_sketch(sk2)
        self.assertEqual(sorted(round(r.face.Area) for r in rs), [100, 100])
        unpicked = feature(self.doc, features.Extrude, Profile=sk2, Length=3)
        self.assertIn("separate regions", unpicked.Status)                # two sections: the user picks
        left = next(r for r in rs if r.point.x < 10)
        unpicked.Regions, unpicked.RegionPoints = [left.key], [tuple(left.point)]
        model.commit(self.doc)
        ex2 = unpicked
        self.assertEqual(ex2.Status, "")
        self.assertAlmostEqual(self.body.Shape.Volume, 1000 + 3 * 100, 6)

    def test_a_shape_drawn_inside_the_face_still_extrudes_without_picking(self):
        sk2 = self.sketch_on_top(rect(5, 2, 15, 8))
        ex2 = feature(self.doc, features.Extrude, Profile=sk2, Length=3)
        self.assertEqual(ex2.Status, "")
        self.assertAlmostEqual(self.body.Shape.Volume, 1000 + 3 * 60, 6)  # the square, not the frame

    def test_tracing_over_the_outline_counts_each_edge_once(self):
        from kovac import regions
        sk2 = self.sketch_on_top(rect(0, 0, 20, 10))
        self.assertEqual([round(r.face.Area) for r in regions.of_sketch(sk2)], [200])
        feature(self.doc, features.Extrude, Profile=sk2, Length=3)
        self.assertAlmostEqual(self.body.Shape.Volume, 1000 + 3 * 200, 6)

    def test_deleting_the_projection_removes_its_body_copy(self):
        sk2 = self.projected_sketch()
        self.assertEqual(len([o for o in self.doc.Objects if projection.is_body_at(o)]), 1)
        sk2.delExternal(0)                                                # the face's projection, all 4 edges
        model.commit(self.doc)
        self.assertEqual([o for o in self.doc.Objects if projection.is_body_at(o)], [])


if __name__ == "__main__":
    unittest.main()

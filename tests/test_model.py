# SPDX-License-Identifier: LGPL-2.1-or-later
"""History model: features, bodies, operation inference, rollback, reorder, undo (headless)."""
import math
import unittest

import FreeCAD as App

from helpers import body_shape, face_ref, feature, live_bodies, normal, rect, sketch
from kovac import features, model

V = App.Vector


class Model(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("M")
        self.doc.UndoMode = 1

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def plate(self, length=10):
        sk = sketch(self.doc, rect(0, 0, 40, 20))
        ex = feature(self.doc, features.Extrude, Profile=sk, Length=length)
        return sk, ex

    def test_extrude_makes_a_named_body(self):
        _, ex = self.plate()
        self.assertEqual(ex.Status, "")
        self.assertEqual(ex.ResolvedOperation, "New body (auto)")
        bodies = live_bodies(self.doc)
        self.assertEqual(len(bodies), 1)
        self.assertAlmostEqual(bodies[0].Shape.Volume, 8000, 6)
        tags = model.state_of(ex)[bodies[0].BodyId].tags
        self.assertEqual(sorted(t.split(":")[1] for t in tags), ["end", "s", "s", "s", "s", "start"])

    def test_join_and_cut_are_inferred_from_direction(self):
        _, ex = self.plate()
        body = live_bodies(self.doc)[0]
        top = App.Placement(V(0, 0, 10), App.Rotation())
        boss = sketch(self.doc, [("circle", (10, 10), 4)], top, "Boss")
        b = feature(self.doc, features.Extrude, Profile=boss, Length=5)
        self.assertEqual(b.ResolvedOperation, "Join (auto)")
        self.assertAlmostEqual(body.Shape.Volume, 8000 + math.pi * 16 * 5, 6)
        pocket = sketch(self.doc, [("circle", (30, 10), 4)], top, "Pocket")
        p = feature(self.doc, features.Extrude, Profile=pocket, Length=-3)
        self.assertEqual(p.ResolvedOperation, "Cut (auto)")
        self.assertAlmostEqual(body.Shape.Volume, 8000 + math.pi * 16 * 5 - math.pi * 16 * 3, 6)
        self.assertEqual(len(live_bodies(self.doc)), 1)

    def test_rollback_and_insert_at_marker(self):
        _, ex = self.plate()
        top = App.Placement(V(0, 0, 10), App.Rotation())
        pocket = sketch(self.doc, [("circle", (20, 10), 4)], top, "Pocket")
        feature(self.doc, features.Extrude, Profile=pocket, Length=-3)
        body = live_bodies(self.doc)[0]
        full = body.Shape.Volume
        model.set_rollback(self.doc, model.items(self.doc).index(ex) + 1)
        model.commit(self.doc)
        self.assertAlmostEqual(body.Shape.Volume, 8000, 6)
        model.set_rollback(self.doc, 99)
        model.commit(self.doc)
        self.assertAlmostEqual(body.Shape.Volume, full, 6)

    def test_reorder_respects_dependencies(self):
        sk, ex = self.plate()
        with self.assertRaises(ValueError):
            model.move(self.doc, ex, 0)          # before its own sketch
        with self.assertRaises(ValueError):
            model.remove(self.doc, sk)           # still used

    def test_one_action_is_one_undo_step(self):
        _, ex = self.plate()
        n = len(self.doc.Objects)
        top = App.Placement(V(0, 0, 10), App.Rotation())
        boss = sketch(self.doc, [("circle", (10, 10), 4)], top, "Boss")   # (sketch: own step)
        feature(self.doc, features.Extrude, Profile=boss, Length=5)
        self.doc.undo()
        model.commit(self.doc)
        self.assertAlmostEqual(live_bodies(self.doc)[0].Shape.Volume, 8000, 6)

    def test_failure_passes_state_through_and_explains(self):
        sk = sketch(self.doc, [("line", (0, 0), (10, 0))])
        ex = feature(self.doc, features.Extrude, Profile=sk, Length=5)
        self.assertIn("no closed profile", ex.Status)
        self.assertEqual(live_bodies(self.doc), [])

    def test_extrude_flat_face_and_new_body(self):
        _, ex = self.plate()
        body = live_bodies(self.doc)[0]
        ref = face_ref(self.doc, body, lambda f: normal(f).z > 0.99)
        up = feature(self.doc, features.Extrude, ProfileFaces=[ref], Length=4)
        self.assertEqual(up.ResolvedOperation, "Join (auto)")
        self.assertAlmostEqual(body.Shape.Volume, 8000 + 800 * 4, 6)
        far = sketch(self.doc, rect(100, 0, 110, 10), name="Far")
        feature(self.doc, features.Extrude, Profile=far, Length=10)
        self.assertEqual(len(live_bodies(self.doc)), 2)

    def test_import_makes_one_body_per_solid(self):
        import Part
        two = Part.makeCompound([Part.makeBox(10, 10, 10), Part.makeBox(5, 5, 5, V(20, 0, 0))])
        feature(self.doc, model.Import, Imported=two)
        self.assertEqual(sorted(round(b.Shape.Volume) for b in live_bodies(self.doc)), [125, 1000])


if __name__ == "__main__":
    unittest.main()

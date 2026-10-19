# SPDX-License-Identifier: LGPL-2.1-or-later
"""Linked and independent copies (ADR-0005), headless."""
import os
import tempfile
import unittest

import FreeCAD as App
import Part

from helpers import feature, live_bodies, rect, sketch
from kovac import components, copies, features, model, modify, topo

V = App.Vector


class Copies(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("K")
        self.sk = sketch(self.doc, rect(0, 0, 20, 10), name="BlockSketch")
        self.ex = feature(self.doc, features.Extrude, Profile=self.sk, Length=5)
        self.body = live_bodies(self.doc)[0]

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def lengthen(self, length):
        self.ex.Length = length
        model.commit(self.doc)

    def edge_ref(self, body, pred):
        st = model.state_of(body.Tip)
        shape = st[body.BodyId].shape
        i = next(k for k, e in enumerate(shape.Edges, 1) if pred(e))
        return topo.dumps(topo.make_ref(st, body.BodyId, "Edge%d" % i))

    def chamfer_top_edge(self, body):
        """A chamfer on a top edge of body (the edge along X at y = 0, z = top)."""
        top = body.Shape.BoundBox.ZMax
        ref = self.edge_ref(body, lambda e: abs(e.BoundBox.ZMin - top) < 1e-6 and abs(e.BoundBox.ZMax - top) < 1e-6
                            and e.BoundBox.YMax < 1e-6 + body.Shape.BoundBox.YMin and e.BoundBox.XLength > 1)
        return feature(self.doc, modify.Chamfer, Edges=[ref], Distance=1)

    def pattern(self, mode, count=3):
        return feature(self.doc, modify.Pattern, Bodies=[self.body.BodyId], Count1=count, Spacing1=30, CopyMode=mode)

    # ------------------------------------------------------------ independent
    def test_new_copies_are_independent_by_default(self):
        p = feature(self.doc, modify.Pattern, Bodies=[self.body.BodyId], Count1=2, Spacing1=30)
        self.assertEqual(p.CopyMode, "Independent")

    def test_independent_pattern_ignores_later_edits_to_the_original(self):
        self.pattern("Independent")
        self.assertEqual(len(live_bodies(self.doc)), 3)
        self.lengthen(12)                                   # the original's own sketch-based step
        vols = sorted(round(b.Shape.Volume) for b in live_bodies(self.doc))
        self.assertEqual(vols, [1000, 1000, 2400])         # only the original grew

    def test_independent_copy_changes_alone(self):
        self.pattern("Independent", 2)
        copy = next(b for b in live_bodies(self.doc) if b is not self.body)
        self.chamfer_top_edge(copy)
        self.assertLess(copy.Shape.Volume, 1000 - 1e-3)
        self.assertAlmostEqual(self.body.Shape.Volume, 1000, 6)

    def test_independent_move_copy_and_mirror(self):
        feature(self.doc, modify.Transform, Bodies=[self.body.BodyId], Copy=True,
                Move=App.Placement(V(0, 40, 0), App.Rotation()), CopyMode="Independent")
        feature(self.doc, modify.Mirror, Bodies=[self.body.BodyId], Plane="YZ", Join=False, CopyMode="Independent")
        self.lengthen(8)
        vols = sorted(round(b.Shape.Volume) for b in live_bodies(self.doc))
        self.assertEqual(vols, [1000, 1000, 1600])

    def test_independent_copies_stay_independent_after_reopening(self):
        self.pattern("Independent", 2)
        path = os.path.join(tempfile.mkdtemp(), "k.FCStd")
        self.doc.saveAs(path)
        name = self.ex.Name
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.ex = self.doc.getObject(name)
        self.lengthen(10)
        vols = sorted(round(b.Shape.Volume) for b in live_bodies(self.doc))
        self.assertEqual(vols, [1000, 2000])

    def test_old_copies_still_follow_the_original(self):
        p = self.pattern("Independent", 2)
        for prop in ("CopyMode", "Frozen", "FrozenState"):     # as made before copy modes existed
            p.removeProperty(prop)
        model.commit(self.doc)
        self.lengthen(10)
        vols = sorted(round(b.Shape.Volume) for b in live_bodies(self.doc))
        self.assertEqual(vols, [2000, 2000])

    # ------------------------------------------------------------ linked
    def test_linked_pattern_makes_links_not_bodies(self):
        p = self.pattern("Linked")
        self.assertEqual(len(live_bodies(self.doc)), 1)
        links = copies.links_of(p)
        self.assertEqual(len(links), 2)
        xs = sorted(round(Part.getShape(lk).BoundBox.XMin) for lk in links)
        self.assertEqual(xs, [30, 60])
        self.assertTrue(all(copies.is_linked_copy(lk) for lk in links))

    def test_linked_copies_follow_every_change(self):
        p = self.pattern("Linked")
        self.lengthen(10)
        self.assertTrue(all(abs(Part.getShape(lk).Volume - 2000) < 1e-6 for lk in copies.links_of(p)))
        lk = copies.links_of(p)[0]
        ref = model.pick_ref(lk, "Face1")                   # a pick on a copy is a pick on the original
        self.assertIsNotNone(ref)
        self.assertEqual(topo.loads(ref)["b"], self.body.BodyId)
        self.chamfer_top_edge(self.body)
        vol = self.body.Shape.Volume
        self.assertLess(vol, 2000 - 1e-3)
        self.assertTrue(all(abs(Part.getShape(x).Volume - vol) < 1e-6 for x in copies.links_of(p)))

    def test_linked_copies_survive_save_and_reopen(self):
        p = self.pattern("Linked", 2)
        path = os.path.join(tempfile.mkdtemp(), "l.FCStd")
        self.doc.saveAs(path)
        names = p.Name, self.ex.Name
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        p, self.ex = (self.doc.getObject(n) for n in names)
        self.lengthen(9)
        (lk,) = copies.links_of(p)
        self.assertAlmostEqual(lk.Shape.Volume, 1800, 6)

    def test_linked_mirror_is_a_mirror_image(self):
        m = feature(self.doc, modify.Mirror, Bodies=[self.body.BodyId], Plane="YZ", Join=False, CopyMode="Linked")
        (lk,) = copies.links_of(m)
        bb = Part.getShape(lk).BoundBox
        self.assertAlmostEqual(bb.XMin, -20, 6)
        self.assertAlmostEqual(bb.XMax, 0, 6)
        self.assertAlmostEqual(Part.getShape(lk).Volume, 1000, 6)

    def test_linked_move_copy(self):
        t = feature(self.doc, modify.Transform, Bodies=[self.body.BodyId], Copy=True,
                    Move=App.Placement(V(0, 40, 0), App.Rotation()), CopyMode="Linked")
        (lk,) = copies.links_of(t)
        self.assertAlmostEqual(Part.getShape(lk).BoundBox.YMin, 40, 6)
        t.Move = App.Placement(V(0, 60, 0), App.Rotation())
        model.commit(self.doc)
        self.assertAlmostEqual(Part.getShape(copies.links_of(t)[0]).BoundBox.YMin, 60, 6)

    def test_rolled_back_or_deleted_linked_feature_takes_its_links(self):
        p = self.pattern("Linked")
        h = model.history(self.doc)
        h.Rollback = model.items(self.doc).index(p)
        model.commit(self.doc)
        self.assertEqual(copies.links_of(p), [])
        h.Rollback = -1
        model.commit(self.doc)
        self.assertEqual(len(copies.links_of(p)), 2)
        model.remove(self.doc, p)
        model.commit(self.doc)
        self.assertFalse(any(copies.is_linked_copy(o) for o in self.doc.Objects))

    def test_switching_linked_to_independent(self):
        p = self.pattern("Linked")
        copies.set_mode(p, "Independent")
        model.commit(self.doc)
        self.assertEqual(copies.links_of(p), [])
        self.assertEqual(len(live_bodies(self.doc)), 3)
        self.lengthen(10)
        self.assertEqual(sorted(round(b.Shape.Volume) for b in live_bodies(self.doc)), [1000, 1000, 2000])

    def test_linked_copies_sit_in_the_originals_component(self):
        comp = components.new_component(self.doc, [self.body], "Block")
        comp.Placement = App.Placement(V(0, 0, 100), App.Rotation())
        p = self.pattern("Linked", 2)
        (lk,) = copies.links_of(p)
        self.assertEqual(components.holder(lk), comp)
        self.assertAlmostEqual(Part.getShape(components.root(self.doc), "%s.%s." % (comp.Name, lk.Name)).BoundBox.ZMin, 100, 6)

    def test_deleting_one_linked_copy_of_a_pattern_skips_it(self):
        p = self.pattern("Linked")
        first = copies.links_of(p)[0]
        copies.remove(first)
        self.assertEqual(list(p.Skip), [1])
        xs = sorted(round(Part.getShape(lk).BoundBox.XMin) for lk in copies.links_of(p))
        self.assertEqual(xs, [60])

    def test_make_independent_keeps_what_was_added_through_the_copies(self):
        p = self.pattern("Linked", 2)
        self.chamfer_top_edge(self.body)
        vol = self.body.Shape.Volume
        copies.make_independent(p)
        model.commit(self.doc)
        self.assertEqual(copies.links_of(p), [])
        copy = next(b for b in live_bodies(self.doc) if b is not self.body)
        self.assertAlmostEqual(copy.Shape.Volume, vol, 6)
        self.lengthen(10)
        self.assertAlmostEqual(copy.Shape.Volume, vol, 6)       # and from now on it is on its own

    # ------------------------------------------------------------ components
    def test_copy_component_is_independent(self):
        comp = components.new_component(self.doc, [self.body], "Block")
        copy = components.copy_component(comp)
        model.commit(self.doc)
        self.lengthen(10)
        new = [b for b in live_bodies(self.doc) if components.holder(b) == copy]
        self.assertEqual(len(new), 1)
        self.assertAlmostEqual(new[0].Shape.Volume, 1000, 6)      # not the original's new 2000
        self.assertAlmostEqual(self.body.Shape.Volume, 2000, 6)


if __name__ == "__main__":
    unittest.main()

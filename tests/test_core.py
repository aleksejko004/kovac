# SPDX-License-Identifier: LGPL-2.1-or-later
"""Headless tests (FreeCADCmd): command layer, standard views/front frame, selection logic."""
import unittest

import FreeCAD as App
import Part

from kovac import commands, selection, views

V = App.Vector


class Fake:
    def __init__(self, tid, **kw):
        self.TypeId = tid
        self.__dict__.update(kw)


class Transactions(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("T")
        self.doc.UndoMode = 1

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_one_action_one_undo_step(self):
        with commands.transaction("Two boxes", self.doc):
            self.doc.addObject("Part::Box", "A")
            self.doc.addObject("Part::Box", "B")
        self.assertEqual(self.doc.UndoCount, 1)
        self.assertNotIn("Touched", self.doc.A.State)      # recomputed before commit
        self.doc.undo()
        self.assertEqual(len(self.doc.Objects), 0)

    def test_nested_actions_stay_one_step(self):
        with commands.transaction("Outer", self.doc):
            self.doc.addObject("Part::Box", "A")
            with commands.transaction("Inner", self.doc):
                self.doc.addObject("Part::Box", "B")
        self.assertEqual(self.doc.UndoCount, 1)

    def test_failure_rolls_back(self):
        with self.assertRaises(ValueError):
            with commands.transaction("Broken", self.doc):
                self.doc.addObject("Part::Box", "A")
                raise ValueError("boom")
        self.assertEqual(len(self.doc.Objects), 0)
        self.assertEqual(self.doc.UndoCount, 0)


class Views(unittest.TestCase):
    def test_26_views_point_the_camera_right(self):
        self.assertEqual(len(views.DIRS), 26)
        self.assertEqual(len({views.name(d) for d in views.DIRS}), 26)
        for d in views.DIRS:
            r = views.camera_rotation(d)
            p, up = r.multVec(V(0, 0, 1)), r.multVec(V(0, 1, 0))
            self.assertLess((p - V(*d).normalize()).Length, 1e-9, d)
            self.assertLess(abs(p.dot(up)), 1e-9, d)
            if d[2] == 0:
                self.assertGreater(up.z, 0.99, d)          # side views stay upright

    def test_front_view_matches_freecad_convention(self):
        r = views.camera_rotation((0, -1, 0))
        self.assertLess((r.multVec(V(1, 0, 0)) - V(1, 0, 0)).Length, 1e-9)   # screen right = +X

    def test_define_front_relabels_cube_and_views(self):
        doc = App.newDocument("F")
        m = views.frame_from_camera(views.camera_rotation((1, 0, 0)))   # looking from +X
        meta = doc.Meta
        meta[views.META_FRAME] = " ".join(str(q) for q in m.Q)
        doc.Meta = meta
        labels = views.cube_labels(views.frame(doc))
        self.assertEqual(labels["TextRight"], "FRONT")
        self.assertEqual(labels["TextFront"], "LEFT")
        self.assertEqual(labels["TextTop"], "TOP")
        p = views.view_rotation((0, -1, 0), doc).multVec(V(0, 0, 1))
        self.assertLess((p - V(1, 0, 0)).Length, 1e-9)              # "Front" now looks from +X
        App.closeDocument(doc.Name)

    def test_default_frame_keeps_stock_labels(self):
        labels = views.cube_labels(App.Rotation())
        self.assertEqual(labels, {p: views.FACES[d].upper() for d, p in views.CUBE_PARAM.items()})

    def test_define_front_snaps_oblique_views(self):
        oblique = views.camera_rotation((0.2, -1, 0.3))
        m = views.frame_from_camera(oblique)
        self.assertEqual(views.cube_labels(m)["TextFront"], "FRONT")


class Selection(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(selection.classify(Fake("Part::Feature"), "Face3"), "face")
        self.assertEqual(selection.classify(Fake("PartDesign::Body"), "Pad.Edge2"), "edge")
        self.assertEqual(selection.classify(Fake("Sketcher::SketchObject"), "Edge1"), "curve")
        self.assertEqual(selection.classify(Fake("Sketcher::SketchObject"), ""), "profile")
        self.assertEqual(selection.classify(Fake("App::Part"), ""), "component")
        self.assertEqual(selection.classify(Fake("Part::Feature"), ""), "body")
        self.assertEqual(selection.classify(Fake("App::Plane"), ""), "reference")
        self.assertIsNone(selection.classify(Fake("App::Origin"), ""))
        self.assertTrue(selection.Gate(["edge"]).allow(None, Fake("Part::Feature"), "Edge1"))
        self.assertFalse(selection.Gate(["edge"]).allow(None, Fake("Part::Feature"), "Face1"))

    def rounded_prism(self):
        w = Part.Face(Part.Wire(Part.makePlane(20, 10).Edges)).makeFillet2D(2, Part.makePlane(20, 10).Vertexes) \
            if hasattr(Part.Face, "makeFillet2D") else None
        if w is None:
            box = Part.makeBox(20, 10, 5)
            vertical = [e for e in box.Edges if abs(e.Vertexes[0].Point.z - e.Vertexes[1].Point.z) > 1]
            return box.makeFillet(2, vertical)
        return w.extrude(V(0, 0, 5))

    def test_tangent_edge_loop(self):
        s = self.rounded_prism()
        top = [i for i, e in enumerate(s.Edges, 1) if all(abs(v.Point.z - 5) < 1e-6 for v in e.Vertexes)]
        self.assertEqual(len(top), 8)
        self.assertEqual(selection.tangent_edges(s, top[0]), sorted(top))

    def test_tangent_faces_skip_sharp_edges(self):
        s = self.rounded_prism()
        side = [i for i, f in enumerate(s.Faces, 1) if abs(f.BoundBox.ZLength - 5) < 1e-6]
        self.assertEqual(selection.tangent_faces(s, side[0]), sorted(side))
        self.assertEqual(len(side), 8)

    def test_window_vs_crossing(self):
        pts = [(1, 1), (5, 5)]
        self.assertFalse(selection.window_hit(pts, (0, 0, 3, 3), crossing=False))
        self.assertTrue(selection.window_hit(pts, (0, 0, 3, 3), crossing=True))
        self.assertTrue(selection.window_hit(pts, (6, 6, 0, 0), crossing=False))

    def test_selection_sets_roundtrip(self):
        doc = App.newDocument("S")
        selection.save_set(doc, "holes", [["Box", "Face1"], ["Box", "Edge3"]])
        self.assertEqual(selection.load_sets(doc)["holes"], [["Box", "Face1"], ["Box", "Edge3"]])
        App.closeDocument(doc.Name)


if __name__ == "__main__":
    unittest.main()

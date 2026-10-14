# SPDX-License-Identifier: LGPL-2.1-or-later
"""Toponaming torture suite (brief M2): after every upstream edit, each downstream feature
must hit the intended geometry or fail with an explicit 'Missing reference' error —
never silently land somewhere else."""
import math
import unittest

import FreeCAD as App
import Part
import Sketcher

from helpers import edge_ref, face_ref, feature, live_bodies, normal, rect, sketch, vertical_edge_at
from kovac import datum, features, model, modify, regions

V = App.Vector
PI = math.pi


def fillet_at(shape, x, y, r):
    """A radius-r fillet face hugging the vertical line at (x, y)."""
    for f in shape.Faces:
        if isinstance(f.Surface, Part.Cylinder) and abs(f.Surface.Radius - r) < 1e-6:
            if all(math.hypot(v.Point.x - x, v.Point.y - y) < 2.5 * r for v in f.Vertexes):
                return True
    return False


def chamfer_faces(shape):
    """Planar faces whose normal is neither axis-aligned (chamfers)."""
    out = []
    for f in shape.Faces:
        if isinstance(f.Surface, Part.Plane):
            n = normal(f)
            if max(abs(n.x), abs(n.y), abs(n.z)) < 0.999:
                out.append(f)
    return out


class Torture(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("T")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    # ------------------------------------------------------------ fixtures
    def plate(self, w=40, d=20, h=10):
        self.sk = sketch(self.doc, rect(0, 0, w, d))
        self.ex = feature(self.doc, features.Extrude, Profile=self.sk, Length=h)
        self.body = live_bodies(self.doc)[0]

    def fillet(self, x=40, y=20, r=2):
        self.fil = feature(self.doc, modify.Fillet, Edges=[edge_ref(self.doc, self.body, vertical_edge_at(x, y))], Radius=r)
        self.assertEqual(self.fil.Status, "")

    def recompute(self):
        model.commit(self.doc)

    def correct(self, fp, check):
        self.assertEqual(fp.Status, "", "expected correct, got: %s" % fp.Status)
        self.assertTrue(self.body.Shape.isValid())
        self.assertTrue(check(), "feature is healthy but not where intended (SILENTLY WRONG)")

    def broken(self, fp):
        self.assertIn("Missing reference", fp.Status)

    def top(self):
        return face_ref(self.doc, self.body, lambda f: normal(f).z > 0.99)

    # ------------------------------------------------------------ scenarios
    def test_01_extrude_length_change(self):
        self.plate()
        self.fillet()
        self.ex.Length = 12
        self.recompute()
        self.correct(self.fil, lambda: fillet_at(self.body.Shape, 40, 20, 2) and abs(self.body.Shape.BoundBox.ZMax - 12) < 1e-9)

    def test_02_sketch_resize(self):
        self.plate()
        self.fillet()
        C = Sketcher.Constraint
        for c in (C("Horizontal", 0), C("Horizontal", 2), C("Vertical", 1), C("Vertical", 3),
                  C("Coincident", 0, 1, -1, 1), C("DistanceX", 0, 1, 0, 2, 40), C("DistanceY", 1, 1, 1, 2, 20)):
            self.sk.addConstraint(c)
        self.recompute()
        self.sk.setDatum(self.sk.ConstraintCount - 2, App.Units.Quantity("50 mm"))   # width 40 -> 50
        self.recompute()
        self.correct(self.fil, lambda: fillet_at(self.body.Shape, 50, 20, 2) and abs(self.body.Shape.Volume - (10000 - (1 - PI / 4) * 40)) < 1e-6)

    def test_03_notch_inserted_upstream(self):
        self.sk = sketch(self.doc, rect(0, 0, 40, 20), constrain=False)    # free points: edit one end only
        self.ex = feature(self.doc, features.Extrude, Profile=self.sk, Length=10)
        self.body = live_bodies(self.doc)[0]
        self.fillet()
        self.sk.moveGeometry(0, 2, V(10, 0, 0))                  # bottom edge now ends at x=10 ...
        pts = [(10, 0), (10, 5), (20, 5), (20, 0), (40, 0)]       # ... and a notch closes the gap
        for a, b in zip(pts, pts[1:]):
            self.sk.addGeometry(Part.LineSegment(V(*a, 0), V(*b, 0)))
        self.recompute()
        self.correct(self.fil, lambda: fillet_at(self.body.Shape, 40, 20, 2)
                     and abs(self.body.Shape.Volume - (8000 - 500 - (1 - PI / 4) * 40)) < 1e-6)

    def test_04_extra_side_face(self):
        self.plate()
        self.fillet()
        self.sk.delConstraint(2)
        self.sk.moveGeometry(2, 2, V(25, 28, 0))
        self.sk.addGeometry(Part.LineSegment(V(25, 28, 0), V(0, 20, 0)))
        self.recompute()
        self.correct(self.fil, lambda: any(isinstance(f.Surface, Part.Cylinder) and f.BoundBox.XMax > 39 for f in self.body.Shape.Faces))

    def test_05_sketch_redrawn_identically(self):
        self.plate()
        self.fillet()
        self.sk.deleteAllGeometry()
        for g in rect(0, 0, 40, 20):
            self.sk.addGeometry(Part.LineSegment(V(*g[1], 0), V(*g[2], 0)))
        self.recompute()
        self.correct(self.fil, lambda: fillet_at(self.body.Shape, 40, 20, 2))

    def test_06_sketch_redrawn_differently(self):
        self.plate()
        self.fillet()
        self.sk.deleteAllGeometry()
        for g in rect(0, 0, 30, 20):
            self.sk.addGeometry(Part.LineSegment(V(*g[1], 0), V(*g[2], 0)))
        self.recompute()
        self.broken(self.fil)
        self.assertFalse(any(isinstance(f.Surface, Part.Cylinder) for f in self.body.Shape.Faces))

    def test_07_hole_added_upstream_of_fillet(self):
        self.plate()
        self.fillet()
        model.set_rollback(self.doc, model.items(self.doc).index(self.ex) + 1)
        self.recompute()
        h = feature(self.doc, features.Hole, Face=self.top(), Positions=[V(20, 10, 10)], Size="M5", ThroughAll=True)
        model.set_rollback(self.doc, 99)
        self.recompute()
        self.assertLess(model.items(self.doc).index(h), model.items(self.doc).index(self.fil))
        self.correct(self.fil, lambda: fillet_at(self.body.Shape, 40, 20, 2)
                     and abs(self.body.Shape.Volume - (8000 - PI * 2.75 ** 2 * 10 - (1 - PI / 4) * 40)) < 1e-6)

    def _holes_with_chamfer(self, instance):
        self.plate(60, 20, 10)
        h = feature(self.doc, features.Hole, Face=self.top(), Positions=[V(5, 10, 10)], Size="M5", ThroughAll=True)
        pat = feature(self.doc, modify.Pattern, Sources=[h], Count1=4, Spacing1=10)
        x = 5 + 10 * instance
        e = edge_ref(self.doc, self.body, lambda e: isinstance(e.Curve, Part.Circle)
                     and abs(e.Curve.Center.x - x) < 1e-6 and e.Curve.Center.z > 9.99)
        ch = feature(self.doc, modify.Chamfer, Edges=[e], Distance=0.5)
        self.assertEqual(ch.Status, "")
        return pat, ch, x

    def test_08_pattern_count_4_6_4(self):
        pat, ch, x = self._holes_with_chamfer(0)
        for n in (6, 4):
            pat.Count1 = n
            self.recompute()
            self.correct(ch, lambda: len(chamfer_faces(self.body.Shape)) == 0 and any(
                isinstance(f.Surface, Part.Cone) and abs(f.Surface.Apex.x - x) < 1e-6 for f in self.body.Shape.Faces))

    def test_09_pattern_instance_removed(self):
        pat, ch, x = self._holes_with_chamfer(3)
        pat.Count1 = 2
        self.recompute()
        self.broken(ch)

    def test_10_chamfer_reordered_before_shell(self):
        self.plate()
        ch = feature(self.doc, modify.Chamfer, Edges=[edge_ref(self.doc, self.body, vertical_edge_at(0, 0))], Distance=2)
        sh = feature(self.doc, modify.Shell, Faces=[self.top()], Thickness=2)
        for order in ("after", "before"):
            model.move(self.doc, ch, model.items(self.doc).index(sh) + (1 if order == "after" else 0))
            self.recompute()
            self.correct(ch, lambda: len(chamfer_faces(self.body.Shape)) >= 1)
            self.assertEqual(sh.Status, "")

    def test_11_extrude_direction_flipped(self):
        self.plate()
        self.fillet()
        self.ex.Length = -10
        self.recompute()
        self.correct(self.fil, lambda: fillet_at(self.body.Shape, 40, 20, 2) and abs(self.body.Shape.BoundBox.ZMin + 10) < 1e-9)

    def test_12_fillet_radius_change_under_shell(self):
        self.plate()
        self.fillet()
        sh = feature(self.doc, modify.Shell, Faces=[self.top()], Thickness=1)
        self.fil.Radius = 4
        self.recompute()
        self.correct(sh, lambda: not any(normal(f).z > 0.99 and f.BoundBox.ZMin > 9.99 and f.Area > 300 for f in self.body.Shape.Faces)
                     and fillet_at(self.body.Shape, 40, 20, 4))

    def test_13_region_pick_stable_when_sketch_grows(self):
        sk = sketch(self.doc, rect(0, 0, 10, 10) + rect(20, 0, 30, 10))
        keys = [r for r in regions.of_sketch(sk) if r.face.BoundBox.XMin < 5]
        ex = feature(self.doc, features.Extrude, Profile=sk, Regions=[keys[0].key], RegionPoints=[keys[0].point], Length=5)
        for g in rect(40, 0, 50, 10):
            sk.addGeometry(Part.LineSegment(V(*g[1], 0), V(*g[2], 0)))
        self.recompute()
        self.body = live_bodies(self.doc)[0]
        self.correct(ex, lambda: abs(self.body.Shape.Volume - 500) < 1e-6 and self.body.Shape.BoundBox.XMax < 10.001)

    def test_14_region_recreated_in_place(self):
        sk = sketch(self.doc, rect(0, 0, 10, 10) + rect(20, 0, 30, 10))
        a = [r for r in regions.of_sketch(sk) if r.face.BoundBox.XMin < 5][0]
        ex = feature(self.doc, features.Extrude, Profile=sk, Regions=[a.key], RegionPoints=[a.point], Length=5)
        for i in (3, 2, 1, 0):
            sk.delGeometry(i)
        for g in rect(-2, -2, 12, 12):
            sk.addGeometry(Part.LineSegment(V(*g[1], 0), V(*g[2], 0)))
        self.recompute()
        self.body = live_bodies(self.doc)[0]
        self.correct(ex, lambda: abs(self.body.Shape.Volume - 14 * 14 * 5) < 1e-6)

    def test_15_face_pull_follows_top(self):
        self.plate()
        fpull = feature(self.doc, modify.FacePull, Face=self.top(), Distance=3)
        self.ex.Length = 12
        self.recompute()
        self.correct(fpull, lambda: abs(self.body.Shape.BoundBox.ZMax - 15) < 1e-9)

    def test_16_hole_follows_top_face(self):
        self.plate()
        h = feature(self.doc, features.Hole, Face=self.top(), Positions=[V(20, 10, 10)], Size="M5", Depth=5, TipAngle=0)
        self.ex.Length = 20
        self.recompute()
        self.correct(h, lambda: abs(self.body.Shape.Volume - (16000 - PI * 2.75 ** 2 * 5)) < 1e-6
                     and any(isinstance(f.Surface, Part.Plane) and abs(f.CenterOfMass.z - 15) < 1e-9 for f in self.body.Shape.Faces))

    def test_17_fillets_inserted_before_shell(self):
        self.plate()
        sh = feature(self.doc, modify.Shell, Faces=[self.top()], Thickness=2)
        model.set_rollback(self.doc, model.items(self.doc).index(self.ex) + 1)
        self.recompute()
        self.fillet(40, 20, 3)
        model.set_rollback(self.doc, 99)
        self.recompute()
        self.correct(sh, lambda: not any(normal(f).z > 0.99 and f.BoundBox.ZMin > 9.99 and f.Area > 300 for f in self.body.Shape.Faces))

    def test_18_split_body_then_fillet_on_half(self):
        self.plate()
        plane = feature(self.doc, datum.DatumPlane, Mode="Offset", Base="YZ", Offset=20)
        feature(self.doc, modify.SplitBody, Body=self.body.BodyId, Plane=plane.Name)
        left = [b for b in live_bodies(self.doc) if b.Shape.BoundBox.XMax < 20.001][0]
        f = feature(self.doc, modify.Fillet, Edges=[edge_ref(self.doc, left, vertical_edge_at(0, 20))], Radius=2)
        plane.Offset = 25
        self.recompute()
        left = [b for b in live_bodies(self.doc) if b.Shape.BoundBox.XMax < 25.001][0]
        self.assertEqual(f.Status, "")
        self.assertTrue(fillet_at(left.Shape, 0, 20, 2))

    def test_19_mirror_join_then_fillet_on_mirrored_edge(self):
        self.plate()
        feature(self.doc, modify.Mirror, Bodies=[self.body.BodyId], Plane="YZ", Join=True)
        self.fillet(-40, 20, 2)
        self.ex.Length = 14
        self.recompute()
        self.correct(self.fil, lambda: fillet_at(self.body.Shape, -40, 20, 2) and abs(self.body.Shape.BoundBox.ZMax - 14) < 1e-9)

    def test_20_cut_tool_resized_under_chamfer(self):
        self.plate()
        tsk = sketch(self.doc, rect(30, -5, 50, 10), App.Placement(V(0, 0, 5), App.Rotation()), "Tool")
        tool = feature(self.doc, features.Extrude, Profile=tsk, Length=10, Operation="New body")
        tb = [b for b in live_bodies(self.doc) if b is not self.body][0]
        feature(self.doc, modify.Combine, Target=self.body.BodyId, Tools=[tb.BodyId], Operation="Cut")
        e = edge_ref(self.doc, self.body, lambda e: abs(e.Vertexes[0].Point.x - 30) < 1e-6 and abs(e.Vertexes[-1].Point.x - 30) < 1e-6
                     and abs(e.Vertexes[0].Point.z - 10) < 1e-6 and abs(e.Vertexes[-1].Point.z - 10) < 1e-6)
        ch = feature(self.doc, modify.Chamfer, Edges=[e], Distance=1)
        tool.Length = 12
        self.recompute()
        self.correct(ch, lambda: len(chamfer_faces(self.body.Shape)) == 1)

    def test_21_draft_survives_length_change(self):
        self.plate()
        sides = [face_ref(self.doc, self.body, lambda f, n=n: (normal(f) - n).Length < 1e-6) for n in (V(1, 0, 0), V(-1, 0, 0))]
        bottom = face_ref(self.doc, self.body, lambda f: normal(f).z < -0.99)
        dr = feature(self.doc, modify.Draft, Faces=sides, Neutral=bottom, Angle=4)
        self.ex.Length = 12
        self.recompute()
        t = 12 * math.tan(math.radians(4))
        self.correct(dr, lambda: abs(self.body.Shape.Volume - 20 * 12 * (40 - t)) < 1e-4)

    def test_22_revolve_angle_change_under_chamfer(self):
        sk = sketch(self.doc, rect(10, 0, 20, 10), name="Ring")
        rv = feature(self.doc, features.Revolve, Profile=sk, Axis="Y", Angle=270)
        self.body = live_bodies(self.doc)[0]
        e = edge_ref(self.doc, self.body, lambda e: isinstance(e.Curve, Part.Circle) and abs(e.Curve.Radius - 20) < 1e-6
                     and abs(e.Curve.Center.y - 10) < 1e-6)
        ch = feature(self.doc, modify.Chamfer, Edges=[e], Distance=1)
        rv.Angle = 180
        self.recompute()
        self.correct(ch, lambda: any(isinstance(f.Surface, Part.Cone) for f in self.body.Shape.Faces))

    def test_23_ambiguous_split_face_is_reported(self):
        self.plate()
        top = self.top()
        h = feature(self.doc, features.Hole, Face=top, Positions=[V(5, 10, 10)], Size="M3", Depth=3)
        model.set_rollback(self.doc, model.items(self.doc).index(self.ex) + 1)
        self.recompute()
        slot = sketch(self.doc, rect(18, -1, 22, 21), App.Placement(V(0, 0, 10), App.Rotation()), "Slot")
        feature(self.doc, features.Extrude, Profile=slot, Length=-10)       # splits the top face in two halves
        model.set_rollback(self.doc, 99)
        self.recompute()
        self.assertIn("Missing reference", h.Status)
        self.assertIn("ambiguous", h.Status)

    def test_24_cut_hole_moved_under_chamfer(self):
        """A round hole cut by an extrude keeps its wall's name when it moves and grows."""
        self.plate()
        hole = sketch(self.doc, [("circle", (20, 10), 4)], name="Hole")
        hole.addConstraint(Sketcher.Constraint("Radius", 0, 4))
        hole.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, 0, 3, 20))
        feature(self.doc, features.Extrude, Profile=hole, Length=10, Operation="Cut")
        e = edge_ref(self.doc, self.body, lambda e: isinstance(e.Curve, Part.Circle) and abs(e.Curve.Center.z - 10) < 1e-6)
        ch = feature(self.doc, modify.Chamfer, Edges=[e], Distance=1)
        hole.setDatum(0, App.Units.Quantity("5 mm"))
        hole.setDatum(1, App.Units.Quantity("25 mm"))
        self.recompute()
        self.correct(ch, lambda: any(isinstance(f.Surface, Part.Cone) and abs(f.Surface.Apex.x - 25) < 1e-6
                                     for f in self.body.Shape.Faces))


if __name__ == "__main__":
    unittest.main()

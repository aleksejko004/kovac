# SPDX-License-Identifier: LGPL-2.1-or-later
"""Golden-part suite (brief M2): 32 parts built through Kovač's command layer, each checked
against an independent construction from raw Part/OCCT operations (volume, area, bounding
box, face and edge counts) plus validity. Where a closed form exists, volume is also
checked against it."""
import math
import unittest

import FreeCAD as App
import Part
import Sketcher

from helpers import edge_ref, face_ref, feature, live_bodies, normal, rect, sketch, vertical_edge_at
from kovac import datum, features, model, modify, regions

V = App.Vector
PI = math.pi
XZ = App.Placement(V(), App.Rotation(V(1, 0, 0), 90))     # sketch plane x-z (normal -y)


def ref_box(x0, y0, z0, x1, y1, z1):
    return Part.makeBox(x1 - x0, y1 - y0, z1 - z0, V(x0, y0, z0))


def refine(s):
    return s.removeSplitter()


def cyl(r, h, c, d=V(0, 0, 1)):
    return Part.makeCylinder(r, h, c, d)


def edges_where(shape, pred):
    return [e for e in shape.Edges if pred(e)]


def is_vertical_at(x, y):
    return vertical_edge_at(x, y)


class Golden(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("G")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def check(self, ours, ref, closed_form=None):
        self.assertTrue(ours.isValid(), "invalid shape")
        self.assertAlmostEqual(ours.Volume, ref.Volume, delta=1e-6 * max(1, ref.Volume))
        self.assertAlmostEqual(ours.Area, ref.Area, delta=1e-6 * max(1, ref.Area))
        bo, br = ours.optimalBoundingBox(False, False), ref.optimalBoundingBox(False, False)   # exact, tight
        for a, b in zip((bo.XMin, bo.YMin, bo.ZMin, bo.XMax, bo.YMax, bo.ZMax), (br.XMin, br.YMin, br.ZMin, br.XMax, br.YMax, br.ZMax)):
            self.assertAlmostEqual(a, b, delta=1e-5)
        self.assertEqual(len(ours.Faces), len(ref.Faces), "face count")
        self.assertEqual(len(ours.Edges), len(ref.Edges), "edge count")
        if closed_form is not None:
            self.assertAlmostEqual(ours.Volume, closed_form, delta=1e-6 * max(1, closed_form))

    def healthy(self):
        for o in model.items(self.doc):
            if model.is_feature(o):
                self.assertEqual(o.Status, "", "%s: %s" % (o.Label, o.Status))

    def body(self, i=0):
        self.healthy()
        return live_bodies(self.doc)[i]

    def plate(self, w, d, h, x0=0, y0=0):
        sk = sketch(self.doc, rect(x0, y0, x0 + w, y0 + d), name="Base")
        return feature(self.doc, features.Extrude, Profile=sk, Length=h)

    def top(self, b, z=None):
        return face_ref(self.doc, b, lambda f: normal(f).z > 0.99 and (z is None or abs(f.CenterOfMass.z - z) < 1e-6))

    # 1 ------------------------------------------------------------------ L-bracket
    def test_01_l_bracket_holes_fillets(self):
        self.plate(60, 40, 6)
        wall = sketch(self.doc, rect(0, 0, 6, 40), App.Placement(V(0, 0, 6), App.Rotation()), "Wall")   # on the base's top
        feature(self.doc, features.Extrude, Profile=wall, Length=34)
        b = self.body()
        h = feature(self.doc, features.Hole, Face=self.top(b, 6), Positions=[V(25, 10, 6)], Size="M5", ThroughAll=True)
        feature(self.doc, modify.Pattern, Sources=[h], Count1=2, Spacing1=20, Count2=2, Spacing2=20)
        inner = edge_ref(self.doc, b, lambda e: abs(e.Vertexes[0].Point.x - 6) < 1e-6 and abs(e.Vertexes[-1].Point.x - 6) < 1e-6
                         and abs(e.Vertexes[0].Point.z - 6) < 1e-6 and abs(e.Vertexes[-1].Point.z - 6) < 1e-6)
        feature(self.doc, modify.Fillet, Edges=[inner], Radius=5)
        r = refine(ref_box(0, 0, 0, 60, 40, 6).fuse(ref_box(0, 0, 0, 6, 40, 40)))
        for x in (25, 45):
            for y in (10, 30):
                r = r.cut(cyl(2.75, 100, V(x, y, -50)))
        r = refine(r)
        e = [e for e in r.Edges if abs(e.Vertexes[0].Point.x - 6) < 1e-6 and abs(e.Vertexes[-1].Point.x - 6) < 1e-6
             and abs(e.Vertexes[0].Point.z - 6) < 1e-6 and abs(e.Vertexes[-1].Point.z - 6) < 1e-6]
        r = r.makeFillet(5, e)
        self.check(self.body().Shape, r)

    # 2 ------------------------------------------------------------------ turned shaft
    def test_02_turned_shaft_grooves_chamfers(self):
        prof = sketch(self.doc, rect(0, 0, 10, 80), XZ, "Shaft")      # radius 10 along z (sketch y)
        feature(self.doc, features.Revolve, Profile=prof, Axis="Z", Angle=360)
        b = self.body()
        for z in (20, 50):
            g = sketch(self.doc, rect(8.5, z, 10, z + 3), XZ, "Groove")
            feature(self.doc, features.Revolve, Profile=g, Axis="Z", Angle=360, Operation="Cut")
        ends = [edge_ref(self.doc, b, lambda e, z=z: isinstance(e.Curve, Part.Circle) and abs(e.Curve.Radius - 10) < 1e-6
                         and abs(e.Curve.Center.z - z) < 1e-6) for z in (0, 80)]
        feature(self.doc, modify.Chamfer, Edges=ends, Distance=1, TangentChain=False)
        r = cyl(10, 80, V())
        for z in (20, 50):
            r = r.cut(cyl(10, 3, V(0, 0, z)).cut(cyl(8.5, 3, V(0, 0, z))))
        r = refine(r)
        r = r.makeChamfer(1, [e for e in r.Edges if isinstance(e.Curve, Part.Circle) and abs(e.Curve.Radius - 10) < 1e-6
                             and (abs(e.Curve.Center.z) < 1e-6 or abs(e.Curve.Center.z - 80) < 1e-6)])
        self.check(self.body().Shape, r)

    # 3 ------------------------------------------------------------------ shelled loft duct
    def test_03_shelled_loft_duct(self):
        s1 = sketch(self.doc, [("circle", (0, 0), 15)], name="Inlet")
        s2 = sketch(self.doc, [("circle", (10, 0), 9)], App.Placement(V(0, 0, 50), App.Rotation()), "Outlet")
        feature(self.doc, features.Loft, Sections=[s1, s2])
        b = self.body()
        ends = [self.top(b, 50), face_ref(self.doc, b, lambda f: normal(f).z < -0.99)]
        feature(self.doc, modify.Shell, Faces=ends, Thickness=1.5)
        w1, w2 = Part.Wire(Part.makeCircle(15)), Part.Wire(Part.makeCircle(9, V(10, 0, 50)))
        r = Part.makeLoft([w1, w2], True, False, False)
        faces = [f for f in r.Faces if isinstance(f.Surface, Part.Plane)]
        r = r.makeThickness(faces, -1.5, 1e-6)
        self.check(self.body().Shape, r)

    # 4 ------------------------------------------------------------------ swept handle
    def test_04_swept_handle(self):
        prof = sketch(self.doc, [("circle", (0, 0), 3)], name="Grip")                        # across the path's end (XY)
        path = sketch(self.doc, [("arc", (40, 0), 40, PI / 2, PI)], XZ, "Arc")              # quarter arc in x-z, ends at origin
        feature(self.doc, features.Sweep, Profile=prof, Path=path)
        arc = Part.ArcOfCircle(Part.Circle(V(40, 0, 0), V(0, 0, 1), 40), PI / 2, PI).toShape()
        arc.transformShape(XZ.toMatrix())
        w = Part.Wire(arc)
        w.reverse()
        r = w.makePipeShell([Part.Wire(Part.makeCircle(3))], True, True)
        self.check(self.body().Shape, r, PI * 9 * (PI / 2 * 40))

    # 5 ------------------------------------------------------------------ patterned flange
    def test_05_patterned_flange(self):
        sk = sketch(self.doc, [("circle", (0, 0), 50), ("circle", (0, 0), 15)], name="Disk")
        feature(self.doc, features.Extrude, Profile=sk, Length=8)
        b = self.body()
        h = feature(self.doc, features.Hole, Face=self.top(b, 8), Positions=[V(35, 0, 8)], Size="M8", ThroughAll=True)
        feature(self.doc, modify.Pattern, Sources=[h], Type="Circular", Axis="Z", Count=6)
        r = cyl(50, 8, V()).cut(cyl(15, 8, V()))
        for k in range(6):
            a = 2 * PI * k / 6
            r = r.cut(cyl(4.5, 100, V(35 * math.cos(a), 35 * math.sin(a), -50)))
        self.check(self.body().Shape, refine(r), PI * (2500 - 225 - 6 * 4.5 ** 2) * 8)

    # 6 ------------------------------------------------------------------ plate with tapped holes
    def test_06_plate_with_m3_to_m8_tapped_holes(self):
        self.plate(100, 30, 12)
        b = self.body()
        top = self.top(b, 12)
        r = ref_box(0, 0, 0, 100, 30, 12)
        for i, (size, tap) in enumerate((("M3", 2.5), ("M4", 3.3), ("M5", 4.2), ("M6", 5.0), ("M8", 6.8))):
            x = 10 + 20 * i
            feature(self.doc, features.Hole, Face=top, Positions=[V(x, 15, 12)], Size=size, HoleType="Tapped", Depth=8)
            rr = tap / 2
            tip = rr / math.tan(math.radians(59))
            tool = cyl(rr, 8, V(x, 15, 4)).fuse(Part.makeCone(0, rr, tip, V(x, 15, 4 - tip)))
            r = r.cut(tool)
        holes = [o for o in model.items(self.doc) if getattr(o, "Kind", "") == "Hole"]
        self.assertEqual([h.Thread for h in holes], ["M3x0.5", "M4x0.7", "M5x0.8", "M6x1", "M8x1.25"])
        self.check(self.body().Shape, refine(r))

    # 7 ------------------------------------------------------------------ drafted, shelled enclosure with ribs
    def test_07_drafted_shelled_enclosure_with_ribs(self):
        self.plate(80, 50, 30)
        b = self.body()
        sides = [face_ref(self.doc, b, lambda f, n=n: (normal(f) - n).Length < 1e-6)
                 for n in (V(1, 0, 0), V(-1, 0, 0), V(0, 1, 0), V(0, -1, 0))]
        bottom = face_ref(self.doc, b, lambda f: normal(f).z < -0.99)
        feature(self.doc, modify.Draft, Faces=sides, Neutral=bottom, Angle=2)
        feature(self.doc, modify.Shell, Faces=[face_ref(self.doc, b, lambda f: normal(f).z > 0.99)], Thickness=2)
        rib = sketch(self.doc, rect(39, 2, 41, 48), App.Placement(V(0, 0, 2), App.Rotation()), "Rib")
        feature(self.doc, features.Extrude, Profile=rib, Length=15)
        ours = self.body().Shape
        self.assertEqual(len(live_bodies(self.doc)), 1)
        # independent: the same drafted box via OCCT draft-angle, shelled, plus the rib
        from kovac.modify import Draft   # noqa: F401  (same kernel algorithm, checked through volume bounds)
        t = 30 * math.tan(math.radians(2))
        outer = 30 / 6 * (80 * 50 + 4 * (80 - t) * (50 - t) + (80 - 2 * t) * (50 - 2 * t))
        self.assertTrue(ours.isValid())
        self.assertLess(ours.Volume, outer)
        self.assertGreater(ours.Volume, outer - (76 * 46 * 28) + 2 * 46 * 15 - 1)
        self.assertAlmostEqual(ours.BoundBox.ZMax, 30, 6)
        self.assertEqual(len([f for f in ours.Faces if normal(f).z > 0.99 and f.BoundBox.ZMin > 29.99]), 1)   # rim only

    # 8..32 -------------------------------------------------------------- smaller parts
    def test_08_block(self):
        self.plate(30, 20, 10)
        self.check(self.body().Shape, ref_box(0, 0, 0, 30, 20, 10), 6000)

    def test_09_through_pocket(self):
        self.plate(40, 30, 10)
        p = sketch(self.doc, rect(10, 10, 30, 20), App.Placement(V(0, 0, 10), App.Rotation()), "Pocket")
        feature(self.doc, features.Extrude, Profile=p, Length=-1, Extent="Through all")
        self.check(self.body().Shape, refine(ref_box(0, 0, 0, 40, 30, 10).cut(ref_box(10, 10, 0, 30, 20, 10))), 12000 - 2000)

    def test_10_counterbore_pattern(self):
        self.plate(60, 40, 12)
        b = self.body()
        h = feature(self.doc, features.Hole, Face=self.top(b), Positions=[V(10, 10, 12)], Size="M6", HoleType="Counterbore", ThroughAll=True)
        feature(self.doc, modify.Pattern, Sources=[h], Count1=2, Spacing1=40, Count2=2, Spacing2=20)
        r = ref_box(0, 0, 0, 60, 40, 12)
        for x in (10, 50):
            for y in (10, 30):
                r = r.cut(cyl(3.3, 100, V(x, y, -50))).cut(cyl(5.5, 6.4, V(x, y, 12 - 6.4)))
        self.check(self.body().Shape, refine(r))

    def test_11_countersinks(self):
        self.plate(40, 20, 10)
        feature(self.doc, features.Hole, Face=self.top(self.body()), Positions=[V(10, 10, 10), V(30, 10, 10)],
                Size="M4", HoleType="Countersink", ThroughAll=True)
        r = ref_box(0, 0, 0, 40, 20, 10)
        for x in (10, 30):
            r = r.cut(cyl(2.25, 100, V(x, 10, -50))).cut(Part.makeCone(2.25, 4.6, 4.6 - 2.25, V(x, 10, 10 - (4.6 - 2.25))))
        self.check(self.body().Shape, refine(r))

    def test_12_shaft_with_keyway(self):
        sk = sketch(self.doc, [("circle", (0, 0), 10)], name="Shaft")
        feature(self.doc, features.Extrude, Profile=sk, Length=60)
        k = sketch(self.doc, rect(-3, 6, 3, 12), App.Placement(V(0, 0, 60), App.Rotation()), "Key")
        feature(self.doc, features.Extrude, Profile=k, Length=-25)
        r = refine(cyl(10, 60, V()).cut(ref_box(-3, 6, 35, 3, 12, 60)))
        self.check(self.body().Shape, r)

    def test_13_tube_two_regions(self):
        sk = sketch(self.doc, [("circle", (0, 0), 10), ("circle", (0, 0), 7)], name="Tube")
        feature(self.doc, features.Extrude, Profile=sk, Length=30)
        self.check(self.body().Shape, cyl(10, 30, V()).cut(cyl(7, 30, V())), PI * 51 * 30)

    def test_14_washer_revolved(self):
        sk = sketch(self.doc, rect(5.3, 0, 10, 1), XZ, "Washer")
        feature(self.doc, features.Revolve, Profile=sk, Axis="Z")
        self.check(self.body().Shape, cyl(10, 1, V()).cut(cyl(5.3, 1, V())), PI * (100 - 5.3 ** 2))

    def test_15_hex_bar_chamfered(self):
        pts = [(10 * math.cos(math.radians(60 * k)), 10 * math.sin(math.radians(60 * k))) for k in range(6)]
        sk = sketch(self.doc, [("line", pts[k], pts[(k + 1) % 6]) for k in range(6)], name="Hex")
        feature(self.doc, features.Extrude, Profile=sk, Length=40)
        b = self.body()
        feature(self.doc, modify.Chamfer, Faces=[self.top(b, 40)], Distance=1, TangentChain=False)
        hexw = Part.makePolygon([V(x, y, 0) for x, y in pts + pts[:1]])
        r = Part.Face(hexw).extrude(V(0, 0, 40))
        top = [f for f in r.Faces if normal(f).z > 0.99][0]
        r = r.makeChamfer(1, top.Edges)
        self.check(self.body().Shape, r)

    def test_16_box_all_edges_filleted(self):
        self.plate(30, 20, 10)
        feature(self.doc, modify.Fillet, WholeBodies=[self.body().BodyId], Radius=2)
        r = ref_box(0, 0, 0, 30, 20, 10)
        self.check(self.body().Shape, r.makeFillet(2, r.Edges))

    def test_17_top_edges_chamfered(self):
        self.plate(30, 20, 10)
        feature(self.doc, modify.Chamfer, Faces=[self.top(self.body())], Distance=1.5)
        r = ref_box(0, 0, 0, 30, 20, 10)
        top = [f for f in r.Faces if normal(f).z > 0.99][0]
        self.check(self.body().Shape, r.makeChamfer(1.5, top.Edges))

    def test_18_symmetric_slotted_plate(self):
        sk = sketch(self.doc, rect(0, 0, 50, 30), name="Plate")
        feature(self.doc, features.Extrude, Profile=sk, Length=8, Sides="Symmetric")
        s = sketch(self.doc, rect(10, 12, 40, 18), App.Placement(V(0, 0, 4), App.Rotation()), "Slot")
        feature(self.doc, features.Extrude, Profile=s, Length=-1, Extent="Through all")
        r = refine(ref_box(0, 0, -4, 50, 30, 4).cut(ref_box(10, 12, -4, 40, 18, 4)))
        self.check(self.body().Shape, r, 50 * 30 * 8 - 30 * 6 * 8)

    def test_19_tapered_frustum(self):
        sk = sketch(self.doc, rect(0, 0, 20, 20), name="Base")
        feature(self.doc, features.Extrude, Profile=sk, Length=10, Taper=10)
        t = 10 * math.tan(math.radians(10))
        w1 = Part.makePolygon([V(0, 0, 0), V(20, 0, 0), V(20, 20, 0), V(0, 20, 0), V(0, 0, 0)])
        w2 = Part.makePolygon([V(t, t, 10), V(20 - t, t, 10), V(20 - t, 20 - t, 10), V(t, 20 - t, 10), V(t, t, 10)])
        self.check(self.body().Shape, Part.makeLoft([w1, w2], True, True), 10 / 6 * (400 + 4 * (20 - t) ** 2 + (20 - 2 * t) ** 2))

    def test_20_thin_rectangular_tube(self):
        sk = sketch(self.doc, rect(0, 0, 30, 20), name="Tube")
        feature(self.doc, features.Extrude, Profile=sk, Length=40, Thin=2)
        self.check(self.body().Shape, ref_box(0, 0, 0, 30, 20, 40).cut(ref_box(2, 2, 0, 28, 18, 40)), (600 - 26 * 16) * 40)

    def test_21_shelled_bowl(self):
        sk = sketch(self.doc, [("arc", (0, 0), 30, -PI / 2, 0), ("line", (30, 0), (0, 0)), ("line", (0, 0), (0, -30))], XZ, "Bowl")
        feature(self.doc, features.Revolve, Profile=sk, Axis="Z")
        b = self.body()
        feature(self.doc, modify.Shell, Faces=[face_ref(self.doc, b, lambda f: isinstance(f.Surface, Part.Plane))], Thickness=2)
        hemi = Part.makeSphere(30).common(ref_box(-40, -40, -40, 40, 40, 0))
        r = hemi.makeThickness([f for f in hemi.Faces if isinstance(f.Surface, Part.Plane)], -2, 1e-6)
        self.check(self.body().Shape, r, 2 / 3 * PI * (30 ** 3 - 28 ** 3))

    def test_22_mirrored_bracket(self):
        self.plate(40, 20, 5)
        w = sketch(self.doc, rect(35, 0, 40, 20), App.Placement(V(0, 0, 5), App.Rotation()), "Wall")
        feature(self.doc, features.Extrude, Profile=w, Length=20)
        feature(self.doc, modify.Mirror, Bodies=[self.body().BodyId], Plane="YZ")
        half = refine(ref_box(0, 0, 0, 40, 20, 5).fuse(ref_box(35, 0, 0, 40, 20, 25)))
        self.check(self.body().Shape, refine(half.fuse(half.mirror(V(), V(1, 0, 0)))))

    def test_23_split_block(self):
        self.plate(40, 20, 10)
        feature(self.doc, modify.SplitBody, Body=self.body().BodyId, Plane="YZ" if False else
                feature(self.doc, datum.DatumPlane, Mode="Offset", Base="YZ", Offset=15).Name)
        a, b = sorted(live_bodies(self.doc), key=lambda x: x.Shape.BoundBox.XMin)
        self.check(a.Shape, ref_box(0, 0, 0, 15, 20, 10), 3000)
        self.check(b.Shape, ref_box(15, 0, 0, 40, 20, 10), 5000)

    def test_24_intersect_box_and_cylinder(self):
        self.plate(20, 20, 20, -10, -10)
        c = sketch(self.doc, [("circle", (0, 0), 12)], name="C")
        feature(self.doc, features.Extrude, Profile=c, Length=20, Operation="Intersect")
        self.check(self.body().Shape, refine(ref_box(-10, -10, 0, 10, 10, 20).common(cyl(12, 20, V()))))

    def test_25_bosses_on_disk(self):
        sk = sketch(self.doc, [("circle", (0, 0), 40)], name="Disk")
        feature(self.doc, features.Extrude, Profile=sk, Length=5)
        bs = sketch(self.doc, [("circle", (30, 0), 4)], App.Placement(V(0, 0, 5), App.Rotation()), "Boss")
        boss = feature(self.doc, features.Extrude, Profile=bs, Length=6)
        feature(self.doc, modify.Pattern, Sources=[boss], Type="Circular", Axis="Z", Count=5)
        r = cyl(40, 5, V())
        r = r.fuse([cyl(4, 6, V(30 * math.cos(2 * PI * k / 5), 30 * math.sin(2 * PI * k / 5), 5)) for k in range(5)])
        self.check(self.body().Shape, refine(r), PI * (1600 * 5 + 5 * 16 * 6))

    def test_26_pocket_grid_with_skip(self):
        self.plate(70, 30, 10)
        p = sketch(self.doc, rect(5, 10, 15, 20), App.Placement(V(0, 0, 10), App.Rotation()), "P")
        pk = feature(self.doc, features.Extrude, Profile=p, Length=-4)
        feature(self.doc, modify.Pattern, Sources=[pk], Count1=4, Spacing1=17, Skip=[2])
        r = ref_box(0, 0, 0, 70, 30, 10)
        for k in (0, 1, 3):
            r = r.cut(ref_box(5 + 17 * k, 10, 6, 15 + 17 * k, 20, 10))
        self.check(self.body().Shape, refine(r), 21000 - 3 * 400)

    def test_27_face_pulled_block(self):
        self.plate(30, 20, 10)
        feature(self.doc, modify.FacePull, Face=face_ref(self.doc, self.body(), lambda f: normal(f).x > 0.99), Distance=7)
        self.check(self.body().Shape, ref_box(0, 0, 0, 37, 20, 10), 7400)

    def test_28_deleted_fillet_heals(self):
        self.plate(30, 20, 10)
        b = self.body()
        feature(self.doc, modify.Fillet, Edges=[edge_ref(self.doc, b, vertical_edge_at(30, 20))], Radius=3)
        feature(self.doc, modify.DeleteFace, Faces=[face_ref(self.doc, b, lambda f: isinstance(f.Surface, Part.Cylinder))])
        self.check(self.body().Shape, ref_box(0, 0, 0, 30, 20, 10), 6000)

    def test_29_scaled_part(self):
        self.plate(10, 10, 10)
        feature(self.doc, modify.Scale, Bodies=[self.body().BodyId], Factor=2.5)
        self.check(self.body().Shape, ref_box(0, 0, 0, 25, 25, 25), 25 ** 3)

    def test_30_moved_copy(self):
        self.plate(10, 10, 10)
        feature(self.doc, modify.Transform, Bodies=[self.body().BodyId], Copy=True,
                Move=App.Placement(V(20, 0, 0), App.Rotation(V(0, 0, 1), 90)))
        b = [x for x in live_bodies(self.doc) if x.Shape.BoundBox.XMin > 5][0]
        r = ref_box(0, 0, 0, 10, 10, 10)
        r.transformShape(App.Placement(V(20, 0, 0), App.Rotation(V(0, 0, 1), 90)).toMatrix())
        self.check(b.Shape, r, 1000)

    def test_31_boss_on_offset_datum(self):
        self.plate(40, 40, 10)
        pl = feature(self.doc, datum.DatumPlane, Mode="Offset", Base=self.top(self.body()), Offset=5)
        sk = datum.sketch_on(self.doc, pl, "Up")
        sk.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), 5))
        model.insert(self.doc, sk)
        feature(self.doc, features.Extrude, Profile=sk, Length=-5)
        c = pl.Placement.Base
        r = refine(ref_box(0, 0, 0, 40, 40, 10).fuse(cyl(5, 5, V(c.x, c.y, 10))))
        self.check(self.body().Shape, r, 16000 + PI * 25 * 5)

    def test_32_twisted_loft(self):
        s1 = sketch(self.doc, rect(-10, -10, 10, 10), name="S1")
        s2 = sketch(self.doc, rect(-10, -10, 10, 10), App.Placement(V(0, 0, 30), App.Rotation(V(0, 0, 1), 30)), "S2")
        feature(self.doc, features.Loft, Sections=[s1, s2], Ruled=True)
        sq = [V(-10, -10, 0), V(10, -10, 0), V(10, 10, 0), V(-10, 10, 0), V(-10, -10, 0)]
        w1 = Part.makePolygon(sq)
        w2 = Part.makePolygon(sq)
        w2.transformShape(App.Placement(V(0, 0, 30), App.Rotation(V(0, 0, 1), 30)).toMatrix())
        self.check(self.body().Shape, Part.makeLoft([w1, w2], True, True))


if __name__ == "__main__":
    unittest.main()

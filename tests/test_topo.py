# SPDX-License-Identifier: LGPL-2.1-or-later
"""Naming layer and sketch regions (headless)."""
import math
import unittest

import FreeCAD as App
import Part

from kovac import regions, topo

V = App.Vector
NAMES = {(-1, 0, 0): "x-", (1, 0, 0): "x+", (0, -1, 0): "y-", (0, 1, 0): "y+", (0, 0, -1): "z-", (0, 0, 1): "z+"}


def box(owner, *args):
    s = Part.makeBox(*args)
    tags = []
    for f in s.Faces:
        n = f.normalAt(*f.Surface.parameter(f.CenterOfMass))
        tags.append("%s:p:%s" % (owner, NAMES[tuple(round(c) for c in n)]))
    return topo.Body(s, tags)


def seg(a, b):
    return Part.LineSegment(V(*a, 0), V(*b, 0)).toShape()


def rect(x0, y0, x1, y1, base=0):
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return [(seg(pts[i], pts[(i + 1) % 4]), base + i) for i in range(4)]


class Regions(unittest.TestCase):
    def test_rectangle(self):
        r = regions.find(rect(0, 0, 40, 20))
        self.assertEqual(len(r), 1)
        self.assertAlmostEqual(r[0].face.Area, 800, 6)

    def test_hole_and_island(self):
        c = Part.Circle(V(20, 10, 0), V(0, 0, 1), 5).toShape()
        r = sorted(regions.find(rect(0, 0, 40, 20) + [(c, 9)]), key=lambda x: x.face.Area)
        self.assertEqual(len(r), 2)
        self.assertAlmostEqual(r[0].face.Area, math.pi * 25, 6)
        self.assertAlmostEqual(r[1].face.Area, 800 - math.pi * 25, 6)

    def test_overlapping_circles(self):
        c1 = Part.Circle(V(0, 0, 0), V(0, 0, 1), 5).toShape()
        c2 = Part.Circle(V(6, 0, 0), V(0, 0, 1), 5).toShape()
        r = regions.find([(c1, 1), (c2, 2)])
        self.assertEqual(len(r), 3)
        self.assertAlmostEqual(sum(x.face.Area for x in r), c1.Length * 0 + Part.Face(Part.Wire(c1)).fuse(Part.Face(Part.Wire(c2))).Area, 5)

    def test_dividing_line_and_dangling_line(self):
        r = regions.find(rect(0, 0, 40, 20) + [(seg((10, -5), (10, 25)), 7), (seg((25, 5), (30, 5)), 8)])
        self.assertEqual(sorted(round(x.face.Area) for x in r), [200, 600])

    def test_keys_survive_moving_curves(self):
        a = {x.key for x in regions.find(rect(0, 0, 40, 20))}
        b = {x.key for x in regions.find(rect(0, 0, 55, 30))}
        self.assertEqual(a, b)


class Naming(unittest.TestCase):
    def test_fuse_inherits_and_merges(self):
        a, b = box("A", 10, 10, 10), box("B", 10, 10, 10)
        b = b.transformed(App.Placement(V(10, 0, 0), App.Rotation()))
        s = a.shape.fuse(b.shape).removeSplitter()
        tags = topo.inherit(s, [a, b])
        self.assertEqual(len(s.Faces), 6)
        self.assertIn("A:p:x-", tags)
        self.assertIn("B:p:x+", tags)
        self.assertIn("A:p:z+", tags)          # merged top: smallest tag wins, stable

    def test_fillet_faces_are_named_by_generator(self):
        a = box("A", 10, 10, 10)
        e = a.shape.Edges[0]
        s = a.shape.makeFillet(2, [e])
        tags = topo.inherit(s, [a], generated=lambda f: "F:f:0")
        self.assertEqual(tags.count("F:f:0"), 1)
        self.assertEqual(len([t for t in tags if t.startswith("A:")]), 6)

    def test_edge_ref_survives_dimension_change(self):
        a = box("A", 10, 10, 10)
        state = {"b": a}
        ref = topo.make_ref(state, "b", "Edge1")
        bigger = {"b": box("A", 25, 12, 7)}
        name = topo.resolve(ref, bigger)
        e = bigger["b"].shape.Edges[int(name[4:]) - 1]
        self.assertEqual(topo.adjacency(bigger["b"])[0][e.hashCode()], ref["t"])

    def test_missing_face_is_loud(self):
        a = box("A", 10, 10, 10)
        ref = topo.make_ref({"b": a}, "b", "Face1")
        other = box("Z", 3, 3, 3)
        with self.assertRaises(topo.Broken):
            topo.resolve(ref, {"b": other})
        with self.assertRaises(topo.Broken):
            topo.resolve(ref, {})

    def test_split_face_disambiguates_or_fails(self):
        a = box("A", 30, 10, 10)
        ref = topo.make_ref({"b": a}, "b", "Face%d" % (a.tags.index("A:p:z+") + 1))
        slot = Part.makeBox(4, 10, 10, V(13, 0, 5))
        s = a.shape.cut(slot)
        cut = topo.Body(s, topo.inherit(s, [a], generated=lambda f: "S:x"))
        self.assertEqual(cut.tags.count("A:p:z+"), 2)
        with self.assertRaises(topo.Broken):     # top split into two equal halves: ambiguous
            topo.resolve(ref, {"b": cut})

    def test_pack_roundtrip(self):
        st = {"b1": box("A", 1, 2, 3), "b2": box("B", 4, 5, 6)}
        shape, text = topo.pack(st)
        back = topo.unpack(shape, text)
        self.assertEqual(list(back), ["b1", "b2"])
        self.assertEqual(back["b2"].tags, st["b2"].tags)
        self.assertAlmostEqual(back["b2"].shape.Volume, 120, 9)


if __name__ == "__main__":
    unittest.main()

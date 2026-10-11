# SPDX-License-Identifier: LGPL-2.1-or-later
"""Headless tests (FreeCADCmd): search ranking, measure readouts, tree roles, mouse presets,
preference packs."""
import unittest
import xml.dom.minidom

import FreeCAD as App
import Part

from kovac import measure, palette, search, theme, tree

V = App.Vector


class Search(unittest.TestCase):
    ENTRIES = [("Kovac_Measure", "Measure", "Hover for a readout"),
               ("Std_MeasureClear", "Clear measurement", ""),
               ("Kovac_View_TopFrontRight", "Top Front Right view", "Look from top front right"),
               ("Kovac_SelectTangent", "Select tangent chain", "Extend selected edges")]

    def test_prefix_beats_scattered(self):
        self.assertEqual(search.rank("mea", self.ENTRIES)[0], "Kovac_Measure")

    def test_subsequence(self):
        self.assertEqual(search.rank("tfr", self.ENTRIES)[0], "Kovac_View_TopFrontRight")
        self.assertEqual(search.rank("sel tan", self.ENTRIES), ["Kovac_SelectTangent"])

    def test_tooltip_matches_rank_lower(self):
        self.assertEqual(search.rank("readout", self.ENTRIES), ["Kovac_Measure"])

    def test_no_match(self):
        self.assertEqual(search.rank("zzz", self.ENTRIES), [])

    def test_favourite_breaks_ties(self):
        self.assertEqual(search.rank("measure", self.ENTRIES, favorites={"Std_MeasureClear"})[0], "Std_MeasureClear")


class Measure(unittest.TestCase):
    def test_describe(self):
        box = Part.makeBox(10, 20, 30)
        self.assertIn("volume 6000.000", measure.describe(box))
        self.assertTrue(measure.describe(box.Faces[0]).startswith("Plane  area 600.000"))
        self.assertTrue(measure.describe(box.Edges[0]).startswith("Line  length"))
        circle = Part.makeCircle(5)
        self.assertEqual(measure.describe(circle), "Circle  Ø 10.000 mm  (R 5.000 mm)")
        self.assertEqual(measure.describe(Part.Vertex(V(1, 2, 3))), "Point  1.000, 2.000, 3.000")

    def test_between_planes_and_lines(self):
        box = Part.makeBox(10, 10, 10)
        top = next(f for f in box.Faces if f.CenterOfMass.z > 9.9)
        side = next(f for f in box.Faces if f.CenterOfMass.x < 0.1)
        out = measure.between(top, side)
        self.assertIn("Minimum distance  0.000 mm", out)
        self.assertIn("Angle  90.000°", out)
        e1 = Part.LineSegment(V(0, 0, 0), V(1, 0, 0)).toShape()
        e2 = Part.LineSegment(V(0, 5, 0), V(1, 6, 0)).toShape()
        self.assertIn("Angle  45.000°", measure.between(e1, e2))
        self.assertIn("Angle  0.000°", measure.between(e1, top))    # line parallel to plane

    def test_between_points_and_circles(self):
        a, b = Part.Vertex(V(0, 0, 0)), Part.Vertex(V(3, 4, 0))
        self.assertIn("Minimum distance  5.000 mm", measure.between(a, b))
        c1, c2 = Part.makeCircle(2, V(0, 0, 0)), Part.makeCircle(3, V(10, 0, 0))
        self.assertIn("Centre distance  10.000 mm", measure.between(c1, c2))


class Roles(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("R")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_machinery_hidden_features_in_timeline(self):
        d = self.doc
        body = d.addObject("PartDesign::Body", "Body")
        sk = body.newObject("Sketcher::SketchObject", "Sketch")
        box = d.addObject("Part::Box", "Box")
        cyl = d.addObject("Part::Cylinder", "Cyl")
        cut = d.addObject("Part::Cut", "Cut")
        cut.Base, cut.Tool = box, cyl
        comp = d.addObject("App::Part", "Comp")
        d.recompute()
        self.assertEqual(tree.role(body.Origin), "machinery")
        self.assertEqual(tree.role(body.Origin.OriginFeatures[0]), "machinery")
        self.assertEqual(tree.role(body), "body")
        self.assertEqual(tree.role(sk), "sketch")
        self.assertEqual(tree.role(box), "feature")       # consumed by the cut
        self.assertEqual(tree.role(cut), "body")
        self.assertEqual(tree.role(comp), "component")
        names = {o.Name for o in tree.children(d)}
        self.assertEqual(names, {"Body", "Cut", "Comp"})
        self.assertEqual([o.Name for o in tree.body_sketches(body)], ["Sketch"])
        from kovac import timeline
        self.assertEqual([o.Name for o in timeline.features(d)], ["Sketch", "Box", "Cyl", "Cut"])   # sketches are history too

    def test_creator_of_element(self):
        from kovac import timeline
        box = self.doc.addObject("Part::Box", "Box")
        self.doc.recompute()
        self.assertIs(timeline.creator(box, "Face1"), box)


class Presets(unittest.TestCase):
    def test_parse(self):
        from kovac import navigation
        b = navigation.parse_preset(navigation.PRESETS["kovac"])
        self.assertEqual(b["pan"], ("Middle", frozenset()))
        self.assertEqual(b["orbit"], ("Middle", frozenset({"Shift"})))
        self.assertEqual(navigation.parse_preset("orbit=Ctrl+Alt+Right")["orbit"], ("Right", frozenset({"Ctrl", "Alt"})))


class PreferencePacks(unittest.TestCase):
    def test_cfg_is_valid_and_carries_palette(self):
        for name in ("light", "dark"):
            dom = xml.dom.minidom.parseString(theme.cfg(name))
            vals = {e.getAttribute("Name"): e.getAttribute("Value") for e in dom.getElementsByTagName("FCUInt")}
            self.assertEqual(int(vals["SelectionColor"]), palette.packed_rgba(palette.SEMANTIC["select"]))
            self.assertEqual(int(vals["BackgroundColor2"]), palette.packed_rgba(palette.THEMES[name]["viewport_top"]))

    def test_template_starts_in_kovac(self):
        self.assertIn('<FCText Name="AutoloadModule">KovacWorkbench</FCText>', theme.user_template())

    def test_packs_on_disk_are_current(self):
        import os
        for name, title in (("light", "Kovac Light"), ("dark", "Kovac Dark")):
            with open(os.path.join(theme.ADDON, title, title + ".cfg"), encoding="utf-8") as f:
                self.assertEqual(f.read(), theme.cfg(name), "run: py tools/build_assets.py")


if __name__ == "__main__":
    unittest.main()


class Fits(unittest.TestCase):
    """ISO 286 limits against values from the standard's tables."""

    def test_holes_and_shafts(self):
        from kovac import iso286
        for size, fit, want in ((10, "H7", (0.015, 0.0)), (25, "g6", (-0.007, -0.020)), (50, "k6", (0.018, 0.002)),
                                (30, "H8", (0.033, 0.0)), (40, "f7", (-0.025, -0.050)), (6, "js6", (0.004, -0.004)),
                                (100, "p6", (0.059, 0.037)), (3, "h9", (0.0, -0.025)), (20, "G7", (0.028, 0.007))):
            up, lo = iso286.limits(size, fit)
            self.assertAlmostEqual(up, want[0], 9, (size, fit))
            self.assertAlmostEqual(lo, want[1], 9, (size, fit))

    def test_bad_input_says_why(self):
        from kovac import iso286
        for size, fit in ((600, "H7"), (10, "Z7"), (10, "H3"), (10, "seven")):
            with self.assertRaises(ValueError):
                iso286.limits(size, fit)

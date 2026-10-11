# SPDX-License-Identifier: LGPL-2.1-or-later
"""Drawings (brief M3), headless: the L-bracket on an A3 sheet with three views, an isometric,
a hatched section through the holes, a detail of the bend, dimensions, thread callouts,
centerlines, a parts list and a balloon. DXF export is checked; changing the thickness updates
everything with no broken or orphaned annotation."""
import os
import tempfile
import unittest

import FreeCAD as App

from helpers import face_ref, feature, live_bodies, normal, rect, sketch
from kovac import datum, drawing, features, iso286, model, modify, topo

V = App.Vector


def vertex_ref(doc, body, p):
    st = model.state_of(body.Tip)
    i = next(i for i, v in enumerate(body.Shape.Vertexes, 1) if (v.Point - p).Length < 1e-6)
    return topo.dumps(topo.make_ref(st, body.BodyId, "Vertex%d" % i))


class Drawing(unittest.TestCase):
    def setUp(self):
        self.doc = doc = App.newDocument("Dwg")
        base = sketch(doc, rect(0, 0, 60, 40), name="Base")
        self.ex = feature(doc, features.Extrude, Profile=base, Length=6)
        body = live_bodies(doc)[0]
        top = face_ref(doc, body, lambda f: normal(f).z > 0.99)
        plane = model.create(doc, datum.DatumPlane, "SketchPlane", Mode="Offset", Base=top, Auto=True)
        doc.recompute()
        wall = datum.sketch_on(doc, plane, "Wall")
        model.insert(doc, wall)
        import Part
        pts = [V(0, 0, 0), V(6, 0, 0), V(6, 40, 0), V(0, 40, 0)]
        for i in range(4):
            wall.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]))
        model.commit(doc)
        feature(doc, features.Extrude, Profile=wall, Length=34)
        self.body = live_bodies(doc)[0]
        top = face_ref(doc, self.body, lambda f: normal(f).z > 0.99 and f.CenterOfMass.x > 10)
        self.hole = feature(doc, features.Hole, Face=top, Positions=[V(25, 20, 6), V(45, 20, 6)], Size="M5",
                            HoleType="Tapped", ThroughAll=True)
        self.assertEqual(self.hole.Status, "")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_l_bracket_drawing_exports_and_follows_the_model(self):
        doc, b = self.doc, self.body
        page = drawing.new_page(doc, "A3", bodies=[b])
        texts = page.Template.EditableTexts
        self.assertEqual(texts["GeneralTolerance"], "ISO 2768-mK")
        self.assertEqual(texts["Title"], doc.Label)
        g = drawing.base_view(page, 110, 200)
        self.assertEqual(texts["Scale"] if False else page.Template.EditableTexts["Scale"], drawing.scale_text(g.Scale))
        front = drawing.front_of(g)
        top = drawing.add_projection(g, "below")
        side = drawing.add_projection(g, "right")
        iso = drawing.add_projection(g, "below-right")
        self.assertEqual((top.Type, side.Type, iso.Type), ("Top", "Left", "FrontTopLeft"))     # first angle
        sec = drawing.section(page, top, horizontal=True, offset=0, x=330, y=200)
        det = drawing.detail(page, front, *self._bend_on(front), radius=6, x=330, y=110)
        doc.recompute()
        for v in (front, top, side, iso, sec, det):
            self.assertTrue(len(v.getVisibleEdges()) > 0, v.Label)
        length = drawing.dimension(page, front, "DistanceX", [vertex_ref(doc, b, V(0, 0, 0)), vertex_ref(doc, b, V(60, 0, 0))], 0, -30)
        thick = drawing.dimension(page, front, "DistanceY", [vertex_ref(doc, b, V(60, 0, 0)), vertex_ref(doc, b, V(60, 0, 6))], 45, 0)
        calls = drawing.hole_callouts(page, top)
        self.assertEqual(len(calls), 1)
        self.assertIn("2× M5x0.8 - 6H", calls[0].FormatSpec)
        self.assertEqual(len(drawing.centerlines(front)), 2)
        drawing.parts_list(page, 250, 60)
        drawing.balloon(page, front, 1, 0, 0, -40, 30)
        doc.recompute()
        self.assertEqual(drawing.broken(page), [])
        self.assertAlmostEqual(length.getRawValue(), 60, 6)
        self.assertAlmostEqual(thick.getRawValue(), 6, 6)
        path = os.path.join(tempfile.mkdtemp(), "bracket.dxf")
        counts, strings = drawing.check_dxf(drawing.export_dxf(page, path))
        self.assertTrue(counts.get("LINE", 0) > 20 and (counts.get("CIRCLE", 0) + counts.get("ARC", 0)) > 2, counts)
        # thickness 6 -> 8: every view and annotation follows, nothing broken or orphaned
        self.ex.Length = 8
        model.commit(doc)
        drawing.refresh(page)
        self.assertEqual(drawing.broken(page), [])
        self.assertAlmostEqual(thick.getRawValue(), 8, 6)
        self.assertAlmostEqual(length.getRawValue(), 60, 6)
        for o in page.Views + [v for v in g.Views]:
            self.assertFalse("Invalid" in o.State or "Error" in o.State, (o.Label, o.State))
        self.assertTrue(drawing._attach_callout(calls[0]))
        counts, _ = drawing.check_dxf(drawing.export_dxf(page, path))
        self.assertTrue(counts.get("LINE", 0) > 20)

    def test_a_reference_that_disappears_is_flagged_not_deleted(self):
        doc, b = self.doc, self.body
        page = drawing.new_page(doc, "A4", bodies=[b])
        front = drawing.front_of(drawing.base_view(page, 100, 150))
        dim = drawing.dimension(page, front, "DistanceY", [vertex_ref(doc, b, V(60, 0, 0)), vertex_ref(doc, b, V(60, 0, 6))], 45, 0)
        self.assertEqual(drawing.broken(page), [], drawing.last_error)
        gone = topo.loads(dim.KovacRefs[1])                 # a corner that no longer exists anywhere
        gone["t"], gone["s"]["c"] = ["Gone:f9"], [999.0, 999.0, 999.0]
        dim.KovacRefs = [dim.KovacRefs[0], topo.dumps(gone)]
        drawing.refresh(page)
        self.assertEqual(drawing.broken(page), [dim])
        self.assertIn(dim, page.Views)

    def test_fits_on_a_diameter(self):
        self.assertEqual(iso286.label(10, "H7"), "10 H7 (+0.015/0)")

    def _bend_on(self, front):
        p = drawing.to_view(front, V(6, 0, 6))
        return p.x, p.y


if __name__ == "__main__":
    unittest.main()

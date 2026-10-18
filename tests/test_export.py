# SPDX-License-Identifier: LGPL-2.1-or-later
"""Export of bodies and components to STEP, STL and 3MF: one file, or one per part (headless)."""
import os
import shutil
import tempfile
import unittest

import FreeCAD as App
import Mesh
import Part

from helpers import feature, live_bodies
from kovac import components, export, features, model

V = App.Vector


class Export(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("X")
        self.dir = tempfile.mkdtemp(prefix="kovac-export-")
        for k, x in enumerate((0, 50)):
            feature(self.doc, features.Primitive, PrimitiveType="Box", Length=10 + 10 * k, Width=10, Height=10,
                    Location=App.Placement(V(x, 0, 0), App.Rotation()), Operation="New body")
        self.a, self.b = sorted(live_bodies(self.doc), key=lambda o: o.Shape.BoundBox.XMin)
        self.a.Label, self.b.Label = "Small block", "Long/block"

    def tearDown(self):
        App.closeDocument(self.doc.Name)
        shutil.rmtree(self.dir, ignore_errors=True)

    def path(self, name):
        return os.path.join(self.dir, name)

    def test_nothing_picked_means_every_shown_part(self):
        self.assertEqual(set(export.items(self.doc, [])), {self.a, self.b})
        self.b.Visibility = False
        self.assertEqual(export.items(self.doc, []), [self.a])

    def test_step_one_file(self):
        (out,) = export.export([self.a, self.b], self.path("both.step"))
        solids = Part.read(out).Solids
        self.assertEqual(sorted(round(s.Volume) for s in solids), [1000, 2000])

    def test_stl_one_file_holds_every_part(self):
        (out,) = export.export([self.a, self.b], self.path("both.stl"), fineness="Fine")
        m = Mesh.Mesh(out)
        self.assertAlmostEqual(m.Volume, 3000, 3)
        self.assertAlmostEqual(m.BoundBox.XMax, 70, 6)

    def test_3mf_one_file_per_part_named_after_it(self):
        outs = export.export([self.a, self.b], self.path("parts.3mf"), separate=True)
        self.assertEqual(sorted(os.path.basename(p) for p in outs), ["parts-Long-block.3mf", "parts-Small block.3mf"])
        vols = sorted(round(Mesh.Mesh(p).Volume) for p in outs)
        self.assertEqual(vols, [1000, 2000])

    def test_a_body_in_a_moved_component_exports_where_it_is_shown(self):
        comp = components.new_component(self.doc, [self.b], "Moved")
        comp.Placement = App.Placement(V(0, 0, 100), App.Rotation())
        model.commit(self.doc)
        (out,) = export.export([self.b], self.path("moved.stl"))
        self.assertAlmostEqual(Mesh.Mesh(out).BoundBox.ZMin, 100, 6)
        (out,) = export.export([comp], self.path("comp.step"))            # the component as one part
        self.assertAlmostEqual(Part.read(out).BoundBox.ZMin, 100, 6)

    def test_finer_meshes_have_more_triangles(self):
        cyl = feature(self.doc, features.Primitive, PrimitiveType="Cylinder", Radius=10, Height=10,
                      Location=App.Placement(V(0, 50, 0), App.Rotation()), Operation="New body")
        body = [b for b in live_bodies(self.doc) if b.Shape.BoundBox.YMin > 30][0]
        self.assertEqual(cyl.Status, "")
        counts = [Mesh.Mesh(export.export([body], self.path("c%s.stl" % f), fineness=f)[0]).CountFacets
                  for f in export.FINENESS]
        self.assertEqual(counts, sorted(counts))
        self.assertLess(counts[0], counts[-1])


if __name__ == "__main__":
    unittest.main()

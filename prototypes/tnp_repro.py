# SPDX-License-Identifier: LGPL-2.1-or-later
"""Minimal reproducer (candidate upstream report), FreeCAD 1.1.4 headless or GUI:

sketch rectangle -> Pad 10 -> Fillet on a pad edge -> Pad.Length = 12  => Fillet "Invalid edge link".
The pad's mapped edge names (e.g. '#11:2;:G;XTR;...') get new string-hash ids on recompute;
the link then only survives through geometric fallback, which fails once the edge itself changes.
A Part::Box -> Part::Fillet chain does not show this.

    FreeCADCmd prototypes/tnp_repro.py
"""
import FreeCAD as App
import Part
import Sketcher

V = App.Vector
doc = App.newDocument("Repro")
body = doc.addObject("PartDesign::Body", "Body")
sk = body.newObject("Sketcher::SketchObject", "Sketch")
sk.AttachmentSupport = [(body.Origin.OriginFeatures[3], "")]
sk.MapMode = "FlatFace"
pts = [V(0, 0, 0), V(40, 0, 0), V(40, 20, 0), V(0, 20, 0)]
for i in range(4):
    sk.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]), False)
for i in range(4):
    sk.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
doc.recompute()
pad = body.newObject("PartDesign::Pad", "Pad")
pad.Profile = sk
pad.Length = 10
doc.recompute()
fil = body.newObject("PartDesign::Fillet", "Fillet")
fil.Base = (pad, ["Edge1"])
fil.Radius = 2
doc.recompute()
before = pad.Shape.getElementMappedName("Edge1")
pad.Length = 12
doc.recompute()
print("Edge1 mapped name before/after:", before, "/", pad.Shape.getElementMappedName("Edge1"))
print("Fillet state after Pad.Length 10 -> 12:", fil.State, fil.getStatusString())

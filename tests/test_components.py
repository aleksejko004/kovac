# SPDX-License-Identifier: LGPL-2.1-or-later
"""Components, instances and joints (ADR-0004), headless."""
import os
import tempfile
import unittest

import FreeCAD as App
import Part
import Sketcher

from helpers import feature, live_bodies, rect, sketch
from kovac import components, features, joints, model, modify, topo

V = App.Vector


def circle_edge(shape, x, y, z, r=None):
    for i, e in enumerate(shape.Edges, 1):
        c = e.Curve
        if isinstance(c, Part.Circle) and (c.Center - V(x, y, z)).Length < 1e-6 and (r is None or abs(c.Radius - r) < 1e-6):
            return "Edge%d" % i
    raise LookupError((x, y, z, r))


def face_at(shape, pred):
    return "Face%d" % next(i for i, f in enumerate(shape.Faces, 1) if pred(f))


class Components(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("C")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def plate(self):
        sk = sketch(self.doc, rect(0, 0, 60, 40), name="PlateSketch")
        self.plate_ex = feature(self.doc, features.Extrude, Profile=sk, Length=10)
        hole = sketch(self.doc, [("circle", (15, 20), 5)], name="HoleSketch")
        hole.addConstraint(Sketcher.Constraint("Radius", 0, 5))
        hole.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, 0, 3, 15))
        hole.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, 0, 3, 20))
        self.hole = hole
        feature(self.doc, features.Extrude, Profile=hole, Length=10, Operation="Cut")
        return live_bodies(self.doc)[0]

    def pin(self, x=200):
        sk = sketch(self.doc, [("circle", (x, 0), 4.5)], name="PinSketch")
        feature(self.doc, features.Extrude, Profile=sk, Length=30, Operation="New body")
        return [b for b in live_bodies(self.doc) if b.Shape.BoundBox.XMin > x - 10][0]

    # ------------------------------------------------------------ components
    def test_component_from_bodies_takes_its_sketches(self):
        plate = self.plate()
        pin = self.pin()
        comp = components.new_component(self.doc, [pin], "Pin")
        self.assertIn(pin, comp.Group)
        self.assertIn(self.doc.getObject("PinSketch"), comp.Group)
        self.assertNotIn(self.doc.getObject("PlateSketch"), comp.Group)
        self.assertIsNone(components.holder(plate))
        self.assertEqual(components.holder(pin), comp)
        self.assertEqual(model.history(self.doc).getParentGeoFeatureGroup(), None)   # history stays outside

    def test_moved_component_keeps_local_shape_and_edits(self):
        self.plate()
        pin = self.pin()
        comp = components.new_component(self.doc, [pin], "Pin")
        comp.Placement = App.Placement(V(0, 0, 50), App.Rotation(V(1, 0, 0), 90))
        model.commit(self.doc)
        self.assertAlmostEqual(pin.Shape.BoundBox.ZMin, 0, 6)            # body coordinates unchanged
        shown = Part.getShape(components.root(self.doc), "%s.%s." % (comp.Name, pin.Name))
        self.assertAlmostEqual(shown.BoundBox.ZMin, 50 - 4.5, 6)          # turned about X: the pin lies along -Y
        ex = [o for o in model.items(self.doc) if getattr(o, "Profile", None) == self.doc.getObject("PinSketch")][0]
        ex.Length = 40                                                   # edit: still local
        model.commit(self.doc)
        self.assertAlmostEqual(pin.Shape.BoundBox.ZMax, 40, 6)

    def test_new_sketch_in_component_makes_body_there_in_local_coordinates(self):
        self.plate()
        comp = components.new_component(self.doc, [], "Bracket")
        comp.Placement = App.Placement(V(500, 0, 0), App.Rotation())
        components.set_active(self.doc, comp)
        try:
            sk = sketch(self.doc, rect(0, 0, 10, 10), name="BracketSketch")
            comp.addObject(sk)
            feature(self.doc, features.Extrude, Profile=sk, Length=5)
        finally:
            components.set_active(self.doc, None)
        b = [b for b in live_bodies(self.doc) if components.holder(b) == comp]
        self.assertEqual(len(b), 1)
        self.assertAlmostEqual(b[0].Shape.BoundBox.XMax, 10, 6)          # local, not 510

    def test_extrude_does_not_join_a_body_of_another_component(self):
        plate = self.plate()
        comp = components.new_component(self.doc, [plate], "Plate")
        comp.Placement = App.Placement(V(0, 0, 100), App.Rotation())     # plate is shown elsewhere now
        sk = sketch(self.doc, rect(10, 10, 20, 20), name="Boss")         # overlaps the plate's own coordinates
        ex = feature(self.doc, features.Extrude, Profile=sk, Length=5)
        self.assertEqual(ex.ResolvedOperation, "New body (auto)")
        self.assertAlmostEqual(plate.Shape.Volume, 60 * 40 * 10 - 3.141592653589793 * 25 * 10, 4)

    def test_pick_through_component_and_instance(self):
        self.plate()
        pin = self.pin()
        comp = components.new_component(self.doc, [pin], "Pin")
        inst = components.new_instance(comp)
        asm = components.root(self.doc)
        self.doc.recompute()
        for top, sub in ((asm, "%s.%s.Face1" % (comp.Name, pin.Name)), (asm, "%s.%s.Face1" % (inst.Name, pin.Name))):
            self.assertIsNotNone(model.pick_ref(top, sub))
            self.assertEqual(components.resolve(top, sub)[0], pin)
        f = components.path_frame(asm, "%s.%s.Face1" % (inst.Name, pin.Name))
        self.assertTrue(f.isSame(inst.Placement, 1e-9))

    def test_instance_follows_definition(self):
        self.plate()
        pin = self.pin()
        comp = components.new_component(self.doc, [pin], "Pin")
        inst = components.new_instance(comp)
        self.doc.recompute()
        ex = [o for o in model.items(self.doc) if getattr(o, "Profile", None) == self.doc.getObject("PinSketch")][0]
        ex.Length = 50
        model.commit(self.doc)
        self.assertAlmostEqual(Part.getShape(inst).BoundBox.ZLength, 50, 6)
        self.assertEqual(inst.Label, "Pin (2)")

    def test_old_design_links_become_global(self):
        sk = sketch(self.doc, rect(0, 0, 10, 10))
        ex = feature(self.doc, features.Extrude, Profile=sk, Length=5)
        ex.removeProperty("Profile")                     # as older Kovač made it
        ex.addProperty("App::PropertyLink", "Profile", "Profile", "sketch")
        ex.Profile = sk
        components.migrate(self.doc)
        self.assertEqual(ex.getTypeIdOfProperty("Profile"), "App::PropertyLinkGlobal")
        self.assertEqual(ex.Profile, sk)
        model.commit(self.doc)
        self.assertEqual(ex.Status, "")

    def shown(self, body):
        """Where a body is on screen: its shape in its component's coordinates, placed."""
        return body.Shape.transformed(components.frame(body).toMatrix()).BoundBox

    def same_box(self, a, b):
        for k in ("XMin", "YMin", "ZMin", "XMax", "YMax", "ZMax"):
            self.assertAlmostEqual(getattr(a, k), getattr(b, k), 5, k)

    def test_body_moved_into_another_component_stays_where_it_is_shown(self):
        plate = self.plate()
        pin = self.pin()
        comp = components.new_component(self.doc, [pin], "Pin")
        comp.Placement = App.Placement(V(0, 0, 50), App.Rotation(V(1, 0, 0), 90))
        model.commit(self.doc)
        before = self.shown(plate)
        components.move_bodies(self.doc, [plate], comp)
        model.commit(self.doc)
        self.assertEqual(components.holder(plate), comp)
        self.same_box(self.shown(plate), before)
        moves = [o for o in model.items(self.doc) if type(getattr(o, "Proxy", None)).__name__ == "Transform"]
        self.assertEqual(len(moves), 1)                                  # one history step carries the change
        self.assertEqual(self.doc.getObject("PlateSketch").getParentGeoFeatureGroup(), None)   # sketches stay put
        ex = [o for o in model.items(self.doc) if getattr(o, "Profile", None) == self.doc.getObject("PlateSketch")][0]
        ex.Length = 20                                                   # an upstream edit still flows through
        model.commit(self.doc)
        self.assertAlmostEqual(self.shown(plate).ZLength, 20, 5)

    def test_body_into_an_unmoved_component_needs_no_history_step(self):
        plate = self.plate()
        comp = components.new_component(self.doc, [], "Empty")
        components.move_bodies(self.doc, [plate], comp)
        self.assertEqual(components.holder(plate), comp)
        self.assertFalse(any(type(getattr(o, "Proxy", None)).__name__ == "Transform" for o in model.items(self.doc)))

    def test_deleting_a_moved_component_keeps_its_bodies_in_place(self):
        self.plate()
        pin = self.pin()
        comp = components.new_component(self.doc, [pin], "Pin")
        comp.Placement = App.Placement(V(10, 0, 50), App.Rotation(V(0, 1, 0), 30))
        model.commit(self.doc)
        before = self.shown(pin)
        note = components.remove(comp)
        model.commit(self.doc)
        self.assertIn("sketches go back", note)                         # the pin's sketch was in it
        self.assertIsNone(components.holder(pin))
        self.same_box(self.shown(pin), before)

    def test_copy_is_a_separate_component_with_its_own_bodies(self):
        self.plate()
        pin = self.pin()
        comp = components.new_component(self.doc, [pin], "Pin")
        comp.Placement = App.Placement(V(0, 0, 50), App.Rotation())
        copy = components.copy_component(comp)
        model.commit(self.doc)
        new = [b for b in live_bodies(self.doc) if components.holder(b) == copy]
        self.assertEqual(len(new), 1)
        self.assertNotEqual(new[0].BodyId, pin.BodyId)
        self.assertEqual(copy.Label, "Pin copy")
        self.assertFalse(copy.Placement.isSame(comp.Placement, 1e-6))    # placed beside it
        self.assertAlmostEqual(new[0].Shape.Volume, pin.Shape.Volume, 6)
        rim = "Edge%d" % (1 + next(i for i, e in enumerate(new[0].Shape.Edges) if e.BoundBox.ZMin > 29))
        feature(self.doc, modify.Chamfer, Edges=[topo.dumps(topo.make_ref(model.state_of(new[0].Tip), new[0].BodyId, rim))],
                Distance=1)
        model.commit(self.doc)
        self.assertLess(new[0].Shape.Volume, pin.Shape.Volume - 1e-3)    # the copy changed alone
        self.assertAlmostEqual(pin.Shape.Volume, 3.141592653589793 * 4.5 ** 2 * 30, 4)

    def test_save_and_reopen(self):
        self.plate()
        pin = self.pin()
        comp = components.new_component(self.doc, [pin], "Pin")
        comp.Placement = App.Placement(V(0, 0, 50), App.Rotation())
        path = os.path.join(tempfile.mkdtemp(), "c.FCStd")
        self.doc.saveAs(path)
        names = comp.Name, pin.Name
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        comp, pin = (self.doc.getObject(n) for n in names)
        self.assertEqual(components.holder(pin), comp)
        model.commit(self.doc)
        self.assertAlmostEqual(pin.Shape.BoundBox.ZMin, 0, 6)
        self.assertAlmostEqual(comp.Placement.Base.z, 50, 6)


class Joints(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("J")
        c = Components()
        c.doc = self.doc
        self.plate_body = c.plate()
        self.pin_body = c.pin()
        self.hole = c.hole
        self.plate = components.new_component(self.doc, [self.plate_body], "Plate")
        self.pin = components.new_component(self.doc, [self.pin_body], "Pin")
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def revolute(self, kind="Revolute"):
        hole = joints.Origin.at(self.plate, self.plate_body, circle_edge(self.plate_body.Shape, 15, 20, 10), "centre")
        pin = joints.Origin.at(self.pin, self.pin_body, circle_edge(self.pin_body.Shape, 200, 0, 0), "centre")
        return joints.create(self.doc, kind, hole, pin)

    def pin_bottom(self):
        return self.pin.Placement.multVec(V(200, 0, 0)), self.pin.Placement.Rotation.multVec(V(0, 0, 1))

    def test_joint_snaps_pin_onto_hole_and_grounds_the_plate(self):
        j = self.revolute()
        self.assertEqual(j.KovacStatus, "")
        self.assertEqual(joints.grounded(self.doc), [self.plate])
        p, z = self.pin_bottom()
        self.assertLess((p - V(15, 20, 10)).Length, 1e-6)       # faces meet: pin stands on the plate
        self.assertGreater(z.z, 0.999)
        self.assertTrue(joints.satisfied(j))

    def test_joint_follows_hole_moved_by_a_dimension(self):
        j = self.revolute()
        self.hole.setDatum(1, App.Units.Quantity("25 mm"))
        self.hole.setDatum(0, App.Units.Quantity("6 mm"))
        msg = model.commit(self.doc)
        self.assertEqual(msg, "")
        self.assertEqual(j.KovacStatus, "")
        p, _ = self.pin_bottom()
        self.assertLess((p - V(25, 20, 10)).Length, 1e-5)

    def test_deleted_hole_flags_the_joint_and_pin_stays(self):
        j = self.revolute()
        before = self.pin.Placement
        cut = [o for o in model.items(self.doc) if getattr(o, "Profile", None) == self.hole][0]
        model.remove(self.doc, cut)
        model.commit(self.doc)
        self.assertIn("Missing reference", j.KovacStatus)
        self.assertTrue(self.pin.Placement.isSame(before, 1e-9))

    def test_cylindrical_slides_and_turns_rigid_holds(self):
        j = self.revolute("Cylindrical")
        self.assertTrue(joints.drag(self.doc, self.pin, App.Placement(V(15 - 200, 20, -5), App.Rotation())))
        p, _ = self.pin_bottom()
        self.assertLess(abs(p.x - 15) + abs(p.y - 20), 1e-5)    # still on the hole's axis
        self.assertAlmostEqual(p.z, -5, 4)                        # slid down through the hole
        joints.set_kind(j, "Rigid")
        model.commit(self.doc)
        self.assertTrue(joints.satisfied(j))

    def test_drag_of_grounded_component_is_refused(self):
        self.revolute()
        self.assertFalse(joints.drag(self.doc, self.plate, App.Placement(V(5, 0, 0), App.Rotation())))
        self.assertTrue(self.plate.Placement.isSame(App.Placement(), 1e-9))

    def test_joint_on_instance(self):
        self.revolute()
        inst = components.new_instance(self.pin)
        self.doc.recompute()
        hole2 = joints.Origin.at(self.plate, self.plate_body, face_at(self.plate_body.Shape,
                                 lambda f: isinstance(f.Surface, Part.Plane) and f.CenterOfMass.z > 9.99), "centre")
        pin2 = joints.Origin.at(inst, self.pin_body, circle_edge(self.pin_body.Shape, 200, 0, 0), "centre")
        j2 = joints.create(self.doc, "Rigid", hole2, pin2)
        self.assertEqual(j2.KovacStatus, "")
        self.assertTrue(joints.satisfied(j2))
        top = self.plate_body.Shape.Faces[int(face_at(self.plate_body.Shape, lambda f: isinstance(f.Surface, Part.Plane) and f.CenterOfMass.z > 9.99)[4:]) - 1]
        self.assertLess((inst.Placement.multVec(V(200, 0, 0)) - top.CenterOfMass).Length, 1e-5)

    def test_impossible_joints_are_undone_and_reported(self):
        self.revolute("Rigid")
        before = self.pin.Placement
        top = joints.Origin.at(self.plate, self.plate_body, face_at(self.plate_body.Shape,
                               lambda f: isinstance(f.Surface, Part.Plane) and f.CenterOfMass.z > 9.99), "centre")
        pin_top = joints.Origin.at(self.pin, self.pin_body, circle_edge(self.pin_body.Shape, 200, 0, 30), "centre")
        with self.assertRaises(ValueError):                  # contradicts the first joint
            joints.create(self.doc, "Rigid", top, pin_top)
        self.assertTrue(self.pin.Placement.isSame(before, 1e-7))

    def test_reopen_keeps_joint_working(self):
        j = self.revolute()
        path = os.path.join(tempfile.mkdtemp(), "j.FCStd")
        self.doc.saveAs(path)
        names = self.pin.Name, self.hole.Name
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.pin, self.hole = (self.doc.getObject(n) for n in names)
        self.hole.setDatum(1, App.Units.Quantity("30 mm"))
        self.assertEqual(model.commit(self.doc), "")
        p, _ = self.pin_bottom()
        self.assertLess((p - V(30, 20, 10)).Length, 1e-5)

    # ------------------------------------------------------------ the timeline
    def test_a_joint_is_a_timeline_step(self):
        j = self.revolute()
        step = joints.step_of(j)
        self.assertIsNotNone(step)
        self.assertIn(step, model.items(self.doc))
        self.assertEqual(step.Kind, "Joint")
        self.assertEqual(joints.joint_of(step), j)

    def test_rolling_back_before_the_step_switches_the_joint_off(self):
        j = self.revolute()
        h = model.history(self.doc)
        h.Rollback = model.items(self.doc).index(joints.step_of(j))
        model.commit(self.doc)
        self.assertTrue(j.Suppressed)
        free = App.Placement(V(300, 0, 0), App.Rotation())
        self.assertTrue(joints.drag(self.doc, self.pin, free))      # nothing holds it now
        h.Rollback = -1
        model.commit(self.doc)
        self.assertFalse(j.Suppressed)
        self.assertTrue(joints.satisfied(j))                          # back on: it snaps into place again
        p, _ = self.pin_bottom()
        self.assertLess((p - V(15, 20, 10)).Length, 1e-5)

    def test_deleting_the_step_deletes_the_joint(self):
        j = self.revolute()
        name = j.Name
        model.remove(self.doc, joints.step_of(j))
        model.commit(self.doc)
        self.assertIsNone(self.doc.getObject(name))

    def test_deleting_the_joint_takes_its_step(self):
        j = self.revolute()
        step = joints.step_of(j).Name
        joints.delete(j)
        model.commit(self.doc)
        self.assertIsNone(self.doc.getObject(step))

    def test_a_broken_joint_shows_on_its_step(self):
        j = self.revolute()
        cut = [o for o in model.items(self.doc) if getattr(o, "Profile", None) == self.hole][0]
        model.remove(self.doc, cut)
        model.commit(self.doc)
        self.assertIn("Missing reference", joints.step_of(j).Status)

    def test_older_joints_get_a_step(self):
        j = self.revolute()
        step = joints.step_of(j)
        h = model.history(self.doc)
        h.Features = [o for o in h.Features if o is not step]          # as made before joints had steps
        self.doc.removeObject(step.Name)
        model.relink(self.doc)
        model.commit(self.doc)
        self.assertIsNotNone(joints.step_of(j))

    # ------------------------------------------------------------ limits and driving
    def test_revolute_position_reads_and_drives(self):
        j = self.revolute()
        ang, _ = joints.position(j)
        self.assertAlmostEqual(ang, 0, 6)                       # as jointed
        self.assertTrue(joints.set_position(self.doc, j, angle=30))
        self.assertAlmostEqual(joints.position(j)[0], 30, 5)
        self.assertTrue(joints.satisfied(j))
        p, _ = self.pin_bottom()
        self.assertLess((p - V(15, 20, 10)).Length, 1e-5)       # turned in place

    def test_angle_limits_hold_driving_and_dragging(self):
        j = self.revolute()
        joints.set_limits(j, angle=(-20, 45))
        joints.set_position(self.doc, j, angle=80)
        self.assertAlmostEqual(joints.position(j)[0], 45, 5)    # stops at the limit
        a, _ = joints.global_frames(j)
        z = a.Rotation.multVec(V(0, 0, 1))
        far = App.Placement(V(), App.Rotation(z, -120), a.Base).multiply(self.pin.Placement)
        held = joints.clamp(j, self.pin, far)                   # a drag past the other limit
        self.pin.Placement = held
        self.assertAlmostEqual(joints.position(j)[0], -20, 5)
        self.assertTrue(joints.satisfied(j))

    def test_out_of_limits_drag_is_refused(self):
        j = self.revolute()
        joints.set_limits(j, angle=(-10, 10))
        before = App.Placement(self.pin.Placement)
        a, _ = joints.global_frames(j)
        z = a.Rotation.multVec(V(0, 0, 1))
        self.assertFalse(joints.drag(self.doc, self.pin, App.Placement(V(), App.Rotation(z, 60), a.Base).multiply(before)))
        self.assertTrue(self.pin.Placement.isSame(before, 1e-7))

    def test_slider_slide_limits(self):
        j = self.revolute("Slider")
        joints.set_limits(j, slide=(0, 12))
        joints.set_position(self.doc, j, slide=20)
        self.assertAlmostEqual(joints.position(j)[1], 12, 5)
        self.assertTrue(joints.satisfied(j))
        joints.set_limits(j, slide=None)                        # limits off again
        joints.set_position(self.doc, j, slide=20)
        self.assertAlmostEqual(joints.position(j)[1], 20, 5)

    def test_limits_survive_save_and_reopen(self):
        j = self.revolute()
        joints.set_limits(j, angle=(-5, 50))
        path = os.path.join(tempfile.mkdtemp(), "l.FCStd")
        self.doc.saveAs(path)
        name = j.Name
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.assertEqual(joints.limits(self.doc.getObject(name)), {"angle": (-5.0, 50.0), "slide": None})


if __name__ == "__main__":
    unittest.main()

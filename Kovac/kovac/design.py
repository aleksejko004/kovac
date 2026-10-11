# SPDX-License-Identifier: LGPL-2.1-or-later
"""Design-mode commands: every modelling command opens its panel pre-filled from what is
selected (a sketch -> profile, edges -> fillet edges, a face -> face pull, ...)."""
import FreeCAD as App
import FreeCADGui as Gui
import Part

import kovac
from kovac import commands, datum, editor, features, model, modify, sketchmode, sketchtools

V = App.Vector


def picks(*kinds):
    """References of the current selection, filtered by element kind."""
    out = []
    for s in Gui.Selection.getSelectionEx("", 0):
        for sub in s.SubElementNames or []:
            if sub.split(".")[-1].startswith(kinds):
                r = model.pick_ref(s.Object, sub)
                if r:
                    out.append(r)
    return out


def selected_sketch():
    for s in Gui.Selection.getSelectionEx("", 0):
        if s.Object.TypeId.startswith("Sketcher::"):
            return s.Object
    return None


def selected_bodies():
    out = []
    for s in Gui.Selection.getSelectionEx("", 0):
        if type(getattr(s.Object, "Proxy", None)).__name__ == "BodyProxy" and s.Object.BodyId not in out:
            out.append(s.Object.BodyId)
    return out


def selected_features():
    out = []
    for s in Gui.Selection.getSelectionEx("", 0):
        f = s.Object if model.is_feature(s.Object) else None
        for sub in s.SubElementNames or []:
            f = f or model.owner_of(s.Object, sub)
        if f is not None and hasattr(f.Proxy, "tool") and f not in out:
            out.append(f)
    return out


def last_sketch():
    """The most recent sketch in the history no feature uses yet (just finished)."""
    doc = App.ActiveDocument
    for o in reversed(model.items(doc)[:model.rollback_index(doc)]):
        if o.TypeId.startswith("Sketcher::") and not [u for u in o.InList if model.is_feature(u)]:
            return o
    return None


# ---------------------------------------------------------------- commands

def extrude():
    from kovac import regionpick
    sk = selected_sketch() or (None if picks("Face") else last_sketch())
    faces = [] if sk else picks("Face")
    chosen = regionpick.hover.take(sk)          # profile areas clicked in the view
    editor.start(features.Extrude, Profile=sk, ProfileFaces=faces, Regions=list(chosen), RegionPoints=list(chosen.values()))


def line():
    """Draw lines: in a sketch straight away, otherwise pick where to sketch first."""
    if sketchmode.in_sketch():
        commands.run("Sketcher_CreateLine")
    else:
        sketchmode.start(then="Sketcher_CreateLine")


def delete():
    """Delete what is selected: sketch elements while sketching; otherwise history items are
    removed, faces deleted (the gap heals) and whole bodies taken out, all as one undo step."""
    if sketchmode.in_sketch():
        Gui.runCommand("Std_Delete")
        return
    doc = App.ActiveDocument
    items, faces, bodies = [], [], []
    for s in Gui.Selection.getSelectionEx("", 0):
        o, subs = s.Object, [n for n in s.SubElementNames if n]
        if o in model.items(doc):
            items.append(o)
        elif hasattr(o, "BodyId"):
            fs = [model.pick_ref(o, n) for n in subs if n.split(".")[-1].startswith("Face")]
            if fs:
                faces += [f for f in fs if f]
            elif not subs:
                bodies.append(o.BodyId)
    if not (items or faces or bodies):
        raise ValueError("Select a body, a face, a sketch or a history item to delete.")
    with commands.transaction("Delete", doc):
        for o in items:
            model.remove(doc, o)
        made = []
        if faces:
            made.append(model.create(doc, modify.DeleteFace, Faces=faces))
        if bodies:
            made.append(model.create(doc, modify.RemoveBody, Bodies=bodies))
        model.commit(doc)
        for fp in made:
            if fp.Status:
                raise ValueError(fp.Status)
    Gui.Selection.clearSelection()


def revolve():
    editor.start(features.Revolve, Profile=selected_sketch() or last_sketch())


def sweep():
    editor.start(features.Sweep, Profile=selected_sketch() or last_sketch())


def loft():
    sks = [s.Object for s in Gui.Selection.getSelectionEx("", 0) if s.Object.TypeId.startswith("Sketcher::")]
    editor.start(features.Loft, Sections=sks)


def hole():
    """A selected face is the start face; centres are then clicked on it."""
    faces = picks("Face")
    editor.start(features.Hole, Face=faces[0] if faces else "")


def primitive(kind):
    return lambda: editor.start(features.Primitive, kind, PrimitiveType=kind)


def fillet():
    editor.start(modify.Fillet, Edges=picks("Edge"), Faces=picks("Face"), WholeBodies=selected_bodies() if not picks("Edge", "Face") else [])


def chamfer():
    editor.start(modify.Chamfer, Edges=picks("Edge"), Faces=picks("Face"))


def shell_():
    editor.start(modify.Shell, Faces=picks("Face"), Bodies=[] if picks("Face") else selected_bodies())


def draft():
    editor.start(modify.Draft, Faces=picks("Face"))


def face_pull():
    """One tool, by context: flat face -> move it; fillet face -> its fillet's radius;
    sketch -> extrude; edge -> fillet."""
    for s in Gui.Selection.getSelectionEx("", 0):
        for sub in s.SubElementNames or []:
            el = sub.split(".")[-1]
            owner = model.owner_of(s.Object, sub)
            if el.startswith("Face") and owner is not None and getattr(owner, "Kind", "") == "Fillet":
                return editor.edit(owner)
            if el.startswith("Face"):
                f = Part.getShape(s.Object, sub, needSubElement=True)
                if isinstance(f.Surface, Part.Plane):
                    return editor.start(modify.FacePull, Face=model.pick_ref(s.Object, sub))
            if el.startswith("Edge"):
                return fillet()
    if selected_sketch() is not None:
        return extrude()
    raise RuntimeError("Select a face, an edge or a sketch.")


def combine():
    ids = selected_bodies()
    editor.start(modify.Combine, Target=ids[0] if ids else "", Tools=ids[1:])


def split():
    ids = selected_bodies()
    editor.start(modify.SplitBody, Body=ids[0] if ids else "")


def move():
    editor.start(modify.Transform, Bodies=selected_bodies())


def scale():
    editor.start(modify.Scale, Bodies=selected_bodies())


def mirror():
    editor.start(modify.Mirror, Bodies=selected_bodies())


def pattern(kind):
    def run():
        srcs, ids = selected_features(), []
        if not srcs:
            ids = selected_bodies()
        editor.start(modify.Pattern, Sources=srcs, Bodies=ids, Type=kind)
    return run


def delete_face():
    editor.start(modify.DeleteFace, Faces=picks("Face"))


def thread():
    editor.start(modify.Thread, Faces=picks("Face"))


def plane():
    faces = picks("Face")
    editor.start(datum.DatumPlane, Mode="Offset" if faces else "XY", Base=faces[0] if faces else "XY", Offset=10 if faces else 0)


def axis():
    refs = picks("Edge", "Face", "Vertex")
    editor.start(datum.DatumAxis, Mode="Edge" if refs else "Z", Refs=refs)


def point():
    refs = picks("Vertex", "Edge", "Face")
    editor.start(datum.DatumPoint, Mode="Vertex" if refs else "Coordinates", Refs=refs)


COMMANDS = [
    # id, label, tip, fn, icon, key
    # Shortcuts avoid: names already in use (Kovac_Search = S, Kovac_NewDesign = Ctrl+N, ...);
    # every bare letter FreeCAD's own sketcher binds while a sketch is being edited; and every
    # letter it uses as the *first* key of a "G, R"-style sequence (G, K, Q, Z), since a bare
    # key clashes with a sequence just as much as a direct repeat does -- Qt can't tell a
    # complete one-key shortcut from the start of a longer one. Commands that only ever show
    # inside a dropdown variant (primitives, patterns, reference geometry, Combine/Split,
    # Move/Mirror) are left without one, same as the 26 standard views: a key per entry there
    # would exhaust the keyboard for little gain.
    ("Kovac_Sketch", "Sketch", "Sketch on a plane or a flat face", sketchmode.start, "sketch", "F2"),
    ("Kovac_Line", "Line", "Draw lines (picks a plane first when not sketching)", line, "line", ""),
    ("Kovac_Polyline", "Polyline", "Connected lines; type each length and angle (Esc or right click ends)",
     sketchtools.polyline, "polyline", ""),
    ("Kovac_PolygonAround", "Polygon around a circle", "Regular polygon whose sides touch the circle you draw (circumscribed)",
     sketchtools.polygon_around, "polygon_out", ""),
    ("Kovac_Delete", "Delete", "Delete the selection", delete, "delete", ""),
    ("Kovac_FinishSketch", "Finish Sketch", "Leave the sketch", sketchmode.finish, "finish", "Return"),
    ("Kovac_Extrude", "Extrude", "Pull a profile or a flat face into a solid", extrude, "extrude", "X"),
    ("Kovac_Revolve", "Revolve", "Turn a profile around an axis", revolve, "revolve", "R"),
    ("Kovac_Sweep", "Sweep", "Move a profile along a path", sweep, "sweep", "U"),
    ("Kovac_Loft", "Loft", "Blend between profiles", loft, "loft", "O"),
    ("Kovac_Hole", "Hole", "Drilled, counterbored, countersunk or tapped holes (ISO metric)", hole, "hole", "B"),
    ("Kovac_Thread", "Thread", "Mark a cylindrical face as threaded", thread, "thread", "Y"),
    ("Kovac_Box", "Box", "Box primitive", primitive("Box"), "box", ""),
    ("Kovac_Cylinder", "Cylinder", "Cylinder primitive", primitive("Cylinder"), "cylinder", ""),
    ("Kovac_Sphere", "Sphere", "Sphere primitive", primitive("Sphere"), "sphere", ""),
    ("Kovac_Cone", "Cone", "Cone primitive", primitive("Cone"), "cone", ""),
    ("Kovac_Torus", "Torus", "Torus primitive", primitive("Torus"), "torus", ""),
    ("Kovac_FacePull", "Face Pull", "Move a face, change a fillet, extrude a sketch, or fillet an edge — by what you picked",
     face_pull, "facepull", ""),
    ("Kovac_Fillet", "Fillet", "Round edges", fillet, "fillet", "F"),
    ("Kovac_Chamfer", "Chamfer", "Bevel edges", chamfer, "chamfer", "M"),
    ("Kovac_Shell", "Shell", "Hollow a body, optionally opening faces", shell_, "shell", "J"),
    ("Kovac_Draft", "Draft", "Tilt faces for moulding", draft, "draft", ""),
    ("Kovac_DeleteFace", "Delete Face", "Remove faces and heal the gap", delete_face, "deleteface", ""),
    ("Kovac_Combine", "Combine", "Join, cut or intersect bodies", combine, "combine", ""),
    ("Kovac_Split", "Split Body", "Cut a body in two with a plane or face", split, "split", ""),
    ("Kovac_Move", "Move / Copy", "Move or copy bodies (recorded in the history)", move, "move", ""),
    ("Kovac_Scale", "Scale", "Scale bodies", scale, "scale", ""),
    ("Kovac_Mirror", "Mirror", "Mirror bodies", mirror, "mirror", ""),
    ("Kovac_PatternRect", "Rectangular Pattern", "Repeat features or bodies in rows", pattern("Rectangular"), "pattern", ""),
    ("Kovac_PatternCirc", "Circular Pattern", "Repeat features or bodies around an axis", pattern("Circular"), "patterncirc", ""),
    ("Kovac_Plane", "Plane", "Construction plane", plane, "plane", ""),
    ("Kovac_Axis", "Axis", "Construction axis", axis, "axis", ""),
    ("Kovac_Point", "Point", "Construction point", point, "point", ""),
]


def register():
    for cid, label, tip, fn, icon, key in COMMANDS:
        commands.add(cid, label, tip, fn, icon=kovac.icon(icon), key=key)

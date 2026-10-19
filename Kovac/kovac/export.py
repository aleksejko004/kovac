# SPDX-License-Identifier: LGPL-2.1-or-later
"""Export bodies and components to STEP, STL or 3MF: everything in one file, or one file per
part. Each part goes where the design shows it (a body in a moved component lands moved)."""
import os
import re

import FreeCAD as App
import Part

from kovac import components, model, tree

FORMATS = {"STEP": ".step", "STL": ".stl", "3MF": ".3mf"}
# triangle size for STL / 3MF: (largest gap from the true surface in mm, largest angle step in rad)
FINENESS = {"Coarse": (0.1, 0.5), "Normal": (0.02, 0.25), "Fine": (0.005, 0.1)}


def items(doc, picked):
    """What to export: the picked bodies and components; with nothing picked, every shown body
    at the top of the design and every shown component."""
    if picked:
        out = []
        for o in picked:
            if tree.role(o) in ("body", "component", "linked") and o not in out:
                out.append(o)
        return out
    out = []
    for o in doc.Objects:
        r = tree.role(o)
        if not getattr(o, "Visibility", True):
            continue
        if r == "body" and components.holder(o) is None and not o.Shape.isNull():
            out.append(o)
        elif r in ("component", "linked") and components.holder(o) is None and not components.is_root(o):
            out.append(o)
    return out


def shape_of(o):
    """o's shape where the design shows it."""
    if isinstance(getattr(o, "Proxy", None), model.BodyProxy):
        s = o.Shape.copy()
    else:
        s = Part.getShape(o, "", transform=True)     # a component (or instance): all it holds
    s.Placement = components.frame(o).multiply(s.Placement)
    return s


def _name(text):
    return re.sub(r'[\\/:*?"<>|]+', "-", text).strip() or "part"


def export(objs, path, separate=False, fineness="Normal"):
    """Write objs to path (format from its extension). separate: one file per object, named
    '<path stem>-<label>'. Returns the files written."""
    stem, ext = os.path.splitext(path)
    ext = ext.lower()
    if ext not in (".step", ".stp", ".stl", ".3mf"):
        raise ValueError("Export as STEP, STL or 3MF.")
    parts = [(o.Label, shape_of(o)) for o in objs]
    parts = [(n, s) for n, s in parts if not s.isNull()]
    if not parts:
        raise ValueError("Nothing to export: pick a body or a component.")
    jobs = [("%s-%s%s" % (stem, _name(n), ext), [s]) for n, s in parts] if separate \
        else [(path, [s for _, s in parts])]
    for out, shapes in jobs:
        _write(shapes, out, ext, fineness)
    return [out for out, _ in jobs]


def _write(shapes, path, ext, fineness):
    if ext in (".step", ".stp"):
        (shapes[0] if len(shapes) == 1 else Part.Compound(shapes)).exportStep(path)
        return
    import Mesh
    import MeshPart
    lin, ang = FINENESS[fineness]
    m = Mesh.Mesh()
    for s in shapes:
        m.addMesh(MeshPart.meshFromShape(Shape=s, LinearDeflection=lin, AngularDeflection=ang, Relative=False))
    m.write(path)


def report(paths):
    where = os.path.dirname(paths[0])
    if len(paths) == 1:
        return "Exported %s" % paths[0]
    return "Exported %d files to %s" % (len(paths), where)


def default_dir():
    """Where the save dialog starts the first time: next to the design file, else home."""
    doc = App.ActiveDocument
    name = getattr(doc, "FileName", "") if doc else ""
    return os.path.dirname(name) if name else os.path.expanduser("~")

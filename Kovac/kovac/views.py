# SPDX-License-Identifier: LGPL-2.1-or-later
"""Standard views (6 faces + 12 edges + 8 corners), home view, and "define current view as Front".

A view is named by the direction from the model toward the camera, e.g. (0, -1, 0) = Front,
(1, -1, 1) = Top Front Right. The document can carry a "logical frame" (doc.Meta["kovac.frame"]):
a rotation from logical to world axes set by "define current view as Front". Every view
command and the orientation-cube labels go through it, so clicking the cube face labelled
FRONT and running "Front view" always agree.
"""
import itertools

import FreeCAD as App

V = App.Vector
DIRS = [d for d in itertools.product((-1, 0, 1), repeat=3) if any(d)]   # 26 standard views
FACES = {(0, -1, 0): "Front", (0, 1, 0): "Rear", (1, 0, 0): "Right", (-1, 0, 0): "Left",
         (0, 0, 1): "Top", (0, 0, -1): "Bottom"}
CUBE_PARAM = {(0, -1, 0): "TextFront", (0, 1, 0): "TextRear", (1, 0, 0): "TextRight",
              (-1, 0, 0): "TextLeft", (0, 0, 1): "TextTop", (0, 0, -1): "TextBottom"}
CUBE_GROUP = "User parameter:BaseApp/Preferences/NaviCube"
META_FRAME = "kovac.frame"
ISO = (1, -1, 1)


def name(d):
    parts = [FACES[a] for a in ((0, 0, d[2]), (0, d[1], 0), (d[0], 0, 0)) if any(a)]
    return " ".join(parts)


def camera_rotation(p, up=None):
    """Rotation of a camera that sits along p (model -> camera) with the given screen-up."""
    p = V(*p).normalize()
    if up is None:
        if abs(p.z) > 0.999:
            up = V(0, 1 if p.z > 0 else -1, 0)   # top: rear edge up; bottom: front edge up
        else:
            up = V(0, 0, 1) - p * p.z
    up = V(*up).normalize()
    return App.Rotation(up.cross(p), up, p, "ZYX")


def frame(doc=None):
    doc = doc or App.ActiveDocument
    s = doc.Meta.get(META_FRAME) if doc else None
    return App.Rotation(*map(float, s.split())) if s else App.Rotation()


def view_rotation(d, doc=None):
    """World camera rotation for logical view direction d, honouring the document frame."""
    m = frame(doc)
    logical = camera_rotation(d)
    return m.multiply(logical)


def _snap(v, exclude=None):
    axes = [V(*a) for a in FACES if exclude is None or abs(V(*a).dot(exclude)) < 0.5]
    return max(axes, key=lambda a: a.dot(v))


def frame_from_camera(rot):
    """Logical->world rotation that makes the current camera (snapped to axes) the Front view."""
    p = _snap(rot.multVec(V(0, 0, 1)))
    up = _snap(rot.multVec(V(0, 1, 0)), exclude=p)
    world = App.Rotation(up.cross(p), up, p, "ZYX")
    logical = camera_rotation((0, -1, 0))
    return world.multiply(logical.inverted())


def cube_labels(m):
    """{NaviCube param: label} for logical->world rotation m."""
    inv = m.inverted()
    out = {}
    for world, param in CUBE_PARAM.items():
        lw = inv.multVec(V(*world))
        logical = min(FACES, key=lambda a: (V(*a) - lw).Length)
        out[param] = FACES[logical].upper()
    return out


def apply_cube_labels(doc=None):
    grp = App.ParamGet(CUBE_GROUP)
    for param, text in cube_labels(frame(doc)).items():
        grp.SetString(param, text)


def define_front(view, doc=None):
    doc = doc or App.ActiveDocument
    m = frame_from_camera(view.getCameraOrientation())
    meta = doc.Meta
    meta[META_FRAME] = " ".join("%.9g" % q for q in m.Q)
    doc.Meta = meta
    apply_cube_labels(doc)


def reset_front(doc=None):
    doc = doc or App.ActiveDocument
    meta = doc.Meta
    meta.pop(META_FRAME, None)
    doc.Meta = meta
    apply_cube_labels(doc)


# ---------------------------------------------------------------- camera moves (GUI)

def _prefs():
    import kovac
    return kovac.prefs()


LIGHT_DIRECTION, LIGHT_INTENSITY = (0.45, 0.35, -0.82), 0.45   # from above, front-left; soft


def add_light(view):
    """A soft light fixed to the world (the camera's own headlight is turned down in the theme), so
    each side of a part gets its own shade: top brightest, sides facing away darker."""
    from pivy import coin
    root = view.getSceneGraph()
    for i in range(root.getNumChildren()):
        if root.getChild(i).getName() == "KovacLight":
            return
    light = coin.SoDirectionalLight()
    light.setName("KovacLight")
    light.direction = LIGHT_DIRECTION
    light.intensity = LIGHT_INTENSITY
    root.insertChild(light, 0)


def go(view, rot, fit=None):
    view.setCameraOrientation(rot)
    if fit if fit is not None else _prefs().GetBool("FitOnViewChange", False):
        view.fitAll()


def standard(view, d):
    go(view, view_rotation(d))


def home_rotation():
    s = _prefs().GetString("HomeView", "")
    return App.Rotation(*map(float, s.split())) if s else view_rotation(ISO)


def home(view):
    go(view, home_rotation(), fit=True)


def set_home(view):
    _prefs().SetString("HomeView", " ".join("%.9g" % q for q in view.getCameraOrientation().Q))


def reset_home():
    _prefs().RemString("HomeView")

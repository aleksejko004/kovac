# SPDX-License-Identifier: LGPL-2.1-or-later
"""Grid: a ground grid on the XY plane that rescales with zoom (1-2-5 steps, every fifth
line stronger) that fades out towards its edge, labelled X/Y/Z axes, and snapping of clicked points.
Sketches get the sketcher's own grid with snap-to-grid on. Toggle: Kovac_Grid (view bar)."""
import math

import FreeCAD as App

import kovac
from kovac import palette

V = App.Vector
TARGET_PX = 28          # minor grid spacing aims for this many screen pixels
_state = {"node": None, "step": None, "timer": None, "view": None}
_clip_saved = {}        # view id -> Coin's own auto-clipping strategy, to give back on Grid off


def enabled():
    return kovac.prefs().GetBool("Grid", True)


def nice_step(world_per_px):
    """Smallest 1-2-5 x 10^k spacing at least TARGET_PX pixels wide."""
    raw = world_per_px * TARGET_PX
    exp = math.floor(math.log10(raw)) if raw > 0 else 0
    for m in (1, 2, 5, 10):
        if m * 10 ** exp >= raw:
            return m * 10 ** exp
    return 10 ** (exp + 1)


def step():
    """The current snapping step (mm), or None when the grid is off."""
    return _state["step"] if enabled() else None


POINT_PX = 14      # an existing point pulls the cursor from this close (screen pixels)...
GRID_PX = 12       # ...a grid point from this close at most (less where grid points are dense)


def grid_px(it, s):
    """Pull radius of grid points: at most GRID_PX, never more than 30 % of their spacing."""
    return min(GRID_PX, 0.3 * s / max(it.px_size(), 1e-12))


def screen_of(it, p):
    """Qt viewport position of world point p."""
    from PySide import QtCore
    x, y = it.view.getPointOnViewport(p)
    r = it.vp.devicePixelRatioF()
    return QtCore.QPointF(x / r, it.vp.height() - y / r)


def nearest(it, pos, points, radius):
    """(world point, screen point) of the candidate closest to pos on screen, if within radius px."""
    best = None
    for p in points:
        q = screen_of(it, p)
        d = ((q.x() - pos.x()) ** 2 + (q.y() - pos.y()) ** 2) ** 0.5
        if d <= radius and (best is None or d < best[0]):
            best = (d, p, q)
    return best and best[1:]


def face_points(face):
    """Candidate snap points on a flat face: its corners, straight-edge midpoints, circle
    centres, and its own centre."""
    import Part
    return ([v.Point for v in face.Vertexes] + [face.CenterOfMass]
            + [e.Curve.Center for e in face.Edges if isinstance(e.Curve, Part.Circle)]
            + [(e.Vertexes[0].Point + e.Vertexes[-1].Point) * 0.5 for e in face.Edges
               if isinstance(e.Curve, Part.Line) and len(e.Vertexes) == 2])


def face_snap(it, pos, p, face):
    """Where a point picked on a flat face lands: one of face_points(face) (within POINT_PX);
    else the grid in the face's plane at half the ground step (when close); else exactly p.
    Returns (point, kind) with kind "point", "grid" or None. Without a view (it is None) the
    old world-space rule applies: the centre within 0.3 steps."""
    s = step()
    n = face.normalAt(*face.Surface.parameter(p))
    origin = n * face.Surface.Position.dot(n)
    points = face_points(face)
    grid_pts = []
    if s:
        q = _snap(p, origin, n, s / 2)      # ponytail: half the visible step, so 5 mm stays reachable on a 2 mm grid
        if face.isInside(q, 1e-6, True):
            grid_pts.append(q)
    if it is None or pos is None:
        if s and (p - face.CenterOfMass).Length < s * 0.3:
            return face.CenterOfMass, "point"
        return (grid_pts[0], "grid") if grid_pts else (p, None)
    hit = nearest(it, pos, points, POINT_PX)
    if hit:
        return hit[0], "point"
    hit = nearest(it, pos, grid_pts, grid_px(it, s / 2)) if s else None
    return (hit[0], "grid") if hit else (p, None)


def _snap(p, origin, normal, s):
    from kovac import datum
    frame = datum.frame(origin, normal)
    local = frame.inverse().multVec(p)
    local = V(round(local.x / s) * s, round(local.y / s) * s, 0)
    return frame.multVec(local)


def _skip_bounds_group():
    """A group that view fitting ignores (FreeCAD's SoSkipBoundingGroup), so the grid never
    makes 'fit all' zoom out to show it."""
    from pivy import coin
    t = coin.SoType.fromName("SoSkipBoundingGroup")
    if t.isBad():
        return coin.SoSeparator()
    node = coin.cast(t.createInstance(), "SoGroup")
    node.set("mode EXCLUDE_BBOX")          # the default includes the bounds
    return node


def _lines(root, polylines, width, pattern=0xFFFF):
    """Polylines of [(point, hex colour[, alpha]), ...]; colour and opacity both blend along
    each one. Real transparency, not a fade toward an approximate flat background colour: the
    actual background is a top-to-bottom gradient (`palette.py`), so mixing toward one flat
    averaged colour left a seam wherever the grid's own fade crossed a part of the screen the
    average didn't match -- most visible at a shallow tilt, where the grid's fade band can span
    much of the screen's own vertical gradient at once. SoMaterial (not SoBaseColor, which has
    no alpha) with transparency bound PER_VERTEX alongside colour fades to nothing against
    whatever is actually behind it."""
    from pivy import coin
    polylines = [pl for pl in polylines if len(pl) > 1]
    if not polylines:
        return
    sep = coin.SoSeparator()
    pts = [q for pl in polylines for q, *_ in pl]
    cols = [tuple(c / 255.0 for c in palette.rgb(h)) for pl in polylines for _, h, *_ in pl]
    alphas = [(a[0] if a else 1.0) for pl in polylines for _, h, *a in pl]
    mat = coin.SoMaterial()
    mat.diffuseColor.setValues(0, len(cols), cols)
    mat.transparency.setValues(0, len(alphas), [1.0 - a for a in alphas])
    bind = coin.SoMaterialBinding()
    bind.value = coin.SoMaterialBinding.PER_VERTEX
    light = coin.SoLightModel()
    light.model = coin.SoLightModel.BASE_COLOR
    style = coin.SoDrawStyle()
    style.lineWidth = width
    style.linePattern = pattern
    crd = coin.SoCoordinate3()
    crd.point.setValues(0, len(pts), [list(q) for q in pts])
    lines = coin.SoLineSet()
    lines.numVertices.setValues(0, len(polylines), [len(pl) for pl in polylines])
    for node in (mat, bind, light, style, crd, lines):
        sep.addChild(node)
    root.addChild(sep)


def _label(root, text, at, color):
    from pivy import coin
    sep = coin.SoSeparator()
    col = coin.SoBaseColor()
    col.rgb = tuple(c / 255.0 for c in palette.rgb(color))
    tr = coin.SoTranslation()
    tr.translation = at
    font = coin.SoFont()
    font.name = "Arial:Bold"
    font.size = 22
    txt = coin.SoText2()
    txt.string = text
    for node in (col, tr, font, txt):
        sep.addChild(node)
    root.addChild(sep)


FADE = 0.6        # the grid is at full strength out to this share of its size, then fades away


def _build(view, s, half, centre=(0.0, 0.0)):
    """Lines every step (every fifth stronger) that fade into the background towards the edge;
    X and Y axes solid on their positive side and dashed on the negative side, with ticks every
    five steps and their letter; a short Z axis."""
    from pivy import coin
    t = palette.theme(kovac.theme_name())
    outer = _skip_bounds_group()          # a plain group: keep our unlit, unpickable state inside a separator
    root = coin.SoSeparator()
    outer.addChild(root)
    sink = coin.SoTranslation()               # a hair below z = 0: no flicker against faces lying on the ground
    sink.translation = (0, 0, -s * 1e-3)
    root.addChild(sink)
    cx, cy = centre
    pick = coin.SoPickStyle()
    pick.style = coin.SoPickStyle.UNPICKABLE
    root.addChild(pick)
    light = coin.SoLightModel()
    light.model = coin.SoLightModel.BASE_COLOR
    root.addChild(light)

    def shade(colour, x, y):
        """(colour, opacity): real transparency, faded to nothing by the edge, not a fade
        toward an approximate flat background -- the viewport is a top-to-bottom gradient
        (`palette.py`), and a fade toward one flat averaged colour left a visible seam
        wherever its own gradient didn't match that average, most noticeable at a shallow
        tilt where the fade band can span much of the screen's own gradient at once."""
        r = max(abs(x - cx), abs(y - cy)) / half
        return colour, min(1.0, max(0.0, (1 - r) / (1 - FADE)))

    def faded(colour, a, b, steps=(0.0, FADE, 1.0)):
        """Polyline from a to b with the fade applied at each stop."""
        out = []
        for k in steps:
            q = tuple(x + (y - x) * k for x, y in zip(a, b))
            c, alpha = shade(colour, q[0], q[1])
            out.append((q, c, alpha))
        return out
    n = int(round(half / s))
    i0, j0 = int(round(cx / s)), int(round(cy / s))
    minor = palette.mix(t["viewport_bottom"], t["text_muted"], 0.22)
    major = palette.mix(t["viewport_bottom"], t["text_muted"], 0.32)
    groups = {"minor": [], "major": []}
    cuts = (0.0, (1 - FADE) / 2, (1 + FADE) / 2, 1.0)
    for k in range(-n, n + 1):
        for i, along_y in ((i0 + k, True), (j0 + k, False)):
            if i == 0:
                continue                  # the axes themselves are drawn below
            g = "major" if i % 5 == 0 else "minor"
            c = major if g == "major" else minor
            if along_y:                   # the line x = i*s
                groups[g].append(faded(c, (i * s, cy - half, 0), (i * s, cy + half, 0), cuts))
            else:                         # the line y = i*s
                groups[g].append(faded(c, (cx - half, i * s, 0), (cx + half, i * s, 0), cuts))
    _lines(root, groups["minor"], 1.0)
    _lines(root, groups["major"], 1.4)
    tick = s * 0.6
    for axis, d, o in (("X", (1, 0, 0), (0, 1, 0)), ("Y", (0, 1, 0), (1, 0, 0))):
        col = t["axis_" + axis.lower()]
        across = cy if axis == "X" else cx          # how far the axis is from the grid's middle
        if abs(across) > half:
            continue
        mid = cx if axis == "X" else cy
        lo, hi = mid - half, mid + half
        on_axis = lambda u: tuple(u * k for k in d)  # noqa: E731

        def seg(u0, u1):
            return [(on_axis(u), *shade(col, *on_axis(u)[:2])) for u in (u0, (u0 + u1) / 2, u1)] if u1 > u0 else []
        _lines(root, [seg(max(lo, 0), hi)], 2.4)                       # positive side solid
        _lines(root, [seg(lo, min(hi, 0))], 1.6, 0x0F0F)              # negative side dashed
        ticks = []
        for i in range(int(lo // s), int(hi // s) + 1):
            u = i * s
            if i and i % 5 == 0 and abs(u - mid) <= FADE * half:
                c = on_axis(u)
                ticks.append([(tuple(a - tick * b for a, b in zip(c, o)), col), (tuple(a + tick * b for a, b in zip(c, o)), col)])
        _lines(root, ticks, 1.6)
        end = mid + FADE * half
        if end > s:
            _label(root, axis, on_axis(end), col)
    _lines(root, [[((0, 0, 0), t["axis_z"]), ((0, 0, 4 * s), t["axis_z"])]], 2.4)
    _label(root, "Z", (0, 0, 4.8 * s), t["axis_z"])
    return outer


def refresh(force=False):
    """(Re)draw for the active view if the zoom moved the spacing to another step."""
    import FreeCADGui as Gui
    view = Gui.activeView()
    if view is None or not hasattr(view, "graphicsView"):
        return
    from kovac import navigation
    it = navigation.install(view)
    if it is None:
        return
    s = nice_step(it.px_size())
    editing = Gui.ActiveDocument is not None and Gui.ActiveDocument.getInEdit() is not None
    if editing:
        _sketch_grid(Gui.ActiveDocument.getInEdit(), s)
    if not enabled() or editing:            # a sketch draws its own grid
        remove()
        _restore_clip(it)
        _state["step"] = s
        return
    # the grid follows the view: centred under it, big enough to fill it, so it never runs out
    centre = _ground_centre(it)
    c = (round(centre.x / (5 * s)) * 5 * s, round(centre.y / (5 * s)) * 5 * s)
    reach = max(it.vp.width(), it.vp.height()) * it.px_size()
    half = max(s * 30, reach * 1.6)
    half = min(math.ceil(half / (5 * s)) * 5 * s, s * 400)
    _clip_for(it, c, half)             # every tick: the grid reaches past what auto-clip would allow
    moved = _state.get("centre") is None or max(abs(c[0] - _state["centre"][0]), abs(c[1] - _state["centre"][1])) > half * 0.2
    if not force and s == _state["step"] and _state["node"] is not None and _state["view"] is view and not moved:
        return
    remove()
    _state["node"] = _build(view, s, half, c)
    view.getSceneGraph().insertChild(_state["node"], 0)
    _state["step"], _state["view"], _state["centre"] = s, view, c


def _corners(box):
    return [V(x, y, z) for x in (box.XMin, box.XMax) for y in (box.YMin, box.YMax) for z in (box.ZMin, box.ZMax)]


def _clip_for(it, centre, half):
    """Push the far clip plane out to cover the grid, not just the model; the near plane stays
    sized to the model alone.

    The grid sits in a SoSkipBoundingGroup (EXCLUDE_BBOX) so 'fit all' never zooms out to show
    it -- but Coin's automatic near/far clipping (Gui::View3DInventorViewer runs it every
    frame, strategy BOUNDING_BOX by default) walks the very same scene bounding box, so it
    never saw the grid either. It then clips the far plane right at the model's edge; at some
    camera tilts that clip plane crosses the ground close to the camera, and the grid vanishes
    beyond it, with the cut line's position and angle on screen changing with the view. We take
    over clipping while the grid is on: auto-clipping off, near/far set from the camera's own
    view direction, each tick.

    A first version sized both planes from one bounding sphere around model and grid together
    -- wrong, because a far-off grid corner inflates that sphere's radius enough to push the
    *near* plane out past the model itself, slicing it (seen live, not assumed: a screenshot
    showed a model with its near side sheared off). Near and far are different problems: near
    must stay tight to the model alone, far has to reach the grid. Measuring the depth of each
    bounding-box corner along the camera's own view direction, not a sphere radius, keeps them
    properly separate -- near is the closest model corner, regardless of where the grid's are.
    Keyed by the cached Interactor, not the view: FreeCAD can hand back a fresh Python wrapper
    for the same view on each Gui.activeView() call (navigation.install() exists for the same
    reason), so the view object itself is not a safe dict key across calls."""
    from pivy import coin
    from kovac import navigation
    view = it.view
    rm = view.getViewer().getSoRenderManager()
    if it not in _clip_saved:
        _clip_saved[it] = rm.getAutoClipping()
    rm.setAutoClipping(coin.SoRenderManager.NO_AUTO_CLIPPING)
    cam = view.getCameraNode()
    pos = V(*cam.position.getValue().getValue())
    forward = navigation.camera_focus(cam) - pos
    forward = forward.normalize() if forward.Length > 1e-9 else V(0, 0, -1)
    model_box = App.BoundBox()
    doc = App.ActiveDocument
    for o in doc.Objects if doc else []:
        vo = getattr(o, "ViewObject", None)
        shape = getattr(o, "Shape", None)
        if vo is not None and vo.Visibility and shape is not None and not shape.isNull():
            model_box.add(shape.BoundBox)
    cx, cy = centre
    grid_corners = [V(x, y, 0) for x in (cx - half, cx + half) for y in (cy - half, cy + half)]
    model_corners = _corners(model_box) if model_box.isValid() else [pos + forward]
    near = min((c - pos).dot(forward) for c in model_corners)
    far = max((c - pos).dot(forward) for c in model_corners + grid_corners)
    model_size = model_box.DiagonalLength if model_box.isValid() else 0.0
    margin = max(model_size, half) * 0.02 + 1e-3    # a hair of slack either side
    near, far = max(near - margin, 1e-3), far + margin
    if far <= near:
        far = near + 1.0
    cam.nearDistance.setValue(near)
    cam.farDistance.setValue(far)


def _restore_clip(it):
    """Give Coin back its own auto-clipping once the grid is off or a sketch is open."""
    if it not in _clip_saved:
        return
    try:
        it.view.getViewer().getSoRenderManager().setAutoClipping(_clip_saved.pop(it))
    except Exception:
        _clip_saved.pop(it, None)


def _ground_centre(it):
    """Point of the ground (z = 0) under the middle of the view; the camera's look-at point if
    the view is edge-on. Near a grazing angle the ray-ground intersection runs arbitrarily far
    away (dividing by a near-zero d.z), which used to carry the whole grid off screen with it
    -- the camera's own focus point stays close to the model at any tilt, so the grid never
    drifts out of view just because the view angle got shallow."""
    from kovac import overlay
    from PySide import QtCore
    o, d = overlay.ray(it, QtCore.QPoint(it.vp.width() // 2, it.vp.height() // 2))
    p = overlay.hit_plane(o, d, V(0, 0, 0), V(0, 0, 1)) if abs(d.z) > 0.05 else None
    if p is not None:
        return p
    from kovac import navigation
    return navigation.camera_focus(it.camera())


def remove():
    if _state["node"] is not None and _state["view"] is not None:
        try:
            _state["view"].getSceneGraph().removeChild(_state["node"])
        except Exception:
            pass
    _state["node"] = None


def start():
    """Keep the grid matched to the zoom (cheap poll: rebuilds only when the step changes)."""
    from PySide import QtCore
    if _state["timer"] is None:
        _state["timer"] = QtCore.QTimer(interval=250)
        _state["timer"].timeout.connect(lambda: _safe_refresh())
        _state["timer"].start()
    refresh(force=True)


def _safe_refresh():
    try:
        refresh()
    except Exception:
        pass


def toggle():
    p = kovac.prefs()
    p.SetBool("Grid", not enabled())
    sketch_snap()
    refresh(force=True)
    from kovac import commands
    commands.report("Grid and snapping %s" % ("on" if enabled() else "off"), error=False)


def _sketch_grid(vo, s):
    """The sketch's grid uses our zoom-dependent step (FreeCAD then snaps exactly onto it)."""
    if hasattr(vo, "GridSize") and abs(vo.GridSize.Value - s) > 1e-9:
        vo.GridAuto = False
        vo.GridSize = s


def _points(sk):
    """Points worth landing on: ends of lines and arcs, their midpoints, centres, free points,
    the origin. A curve's midpoint here is the midpoint of its two endpoints (what Midpoint
    constrains to), not a point on the curve itself -- the same thing for a line, the chord's
    middle for an arc."""
    out = [V(0, 0, 0)]
    for g in sk.Geometry:
        for attr in ("StartPoint", "EndPoint", "Center"):
            if hasattr(g, attr):
                out.append(getattr(g, attr))
        if hasattr(g, "StartPoint") and hasattr(g, "EndPoint"):
            out.append((g.StartPoint + g.EndPoint) * 0.5)
        if g.TypeId == "Part::GeomPoint":
            out.append(V(g.X, g.Y, g.Z))
    return out


def sketch_target(it, pos):
    """Where the cursor should jump to in a sketch: (screen point, kind) or None to leave it.
    An existing sketch point within POINT_PX ("point"); else, with the grid on and not over a line,
    a grid point when close ("grid"). FreeCAD's own snapping then makes the point exact."""
    import FreeCADGui as Gui
    from kovac import overlay
    vo = Gui.ActiveDocument.getInEdit() if Gui.ActiveDocument else None
    if vo is None or not hasattr(vo, "GridSize"):
        return None
    sk = vo.Object
    pl = sk.getGlobalPlacement()
    hit = nearest(it, pos, [pl.multVec(q) for q in _points(sk)], POINT_PX)
    if hit:
        return hit[1], "point"
    info = it.view.getObjectInfo(it.coin(pos))
    if not enabled() or (info and info.get("Component", "").startswith("Edge")):
        return None
    g = vo.GridSize.Value
    o, d = overlay.ray(it, pos)
    p = overlay.hit_plane(o, d, pl.Base, pl.Rotation.multVec(V(0, 0, 1)))
    if p is None or g <= 0:
        return None
    local = pl.inverse().multVec(p)
    hit = nearest(it, pos, [pl.multVec(V(round(local.x / g) * g, round(local.y / g) * g, 0))], grid_px(it, g))
    return (hit[1], "grid") if hit else None


def sketch_snap(sketch=None):
    """Sketcher: show its grid and snap to it while the Kovač grid is on."""
    on = enabled()
    snap = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Sketcher/Snap")
    snap.SetBool("Snap", True)
    snap.SetBool("SnapToGrid", on)
    snap.SetBool("SnapToObjects", True)
    App.ParamGet("User parameter:BaseApp/Preferences/Mod/Sketcher").SetBool("ContinuousCreationMode", True)  # tools stay on
    vo = getattr(sketch, "ViewObject", None)
    if vo is not None and hasattr(vo, "ShowGrid"):
        vo.ShowGrid = on
        if _state["step"]:
            _sketch_grid(vo, _state["step"])

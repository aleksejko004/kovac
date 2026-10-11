# SPDX-License-Identifier: LGPL-2.1-or-later
"""Small Coin3D overlay helpers: translucent faces, lines, cones, view rays."""
import FreeCAD as App
import FreeCADGui as Gui

from kovac import palette

V = App.Vector


def _coin():
    from pivy import coin
    return coin


def rgb(hex_color):
    return tuple(c / 255.0 for c in palette.rgb(hex_color))


def face_node(face, color, transparency=0.5, offset=True, pickable=True):
    coin = _coin()
    sep = coin.SoSeparator()
    if not pickable:
        ps = coin.SoPickStyle()
        ps.style = coin.SoPickStyle.UNPICKABLE
        sep.addChild(ps)
    if offset:
        po = coin.SoPolygonOffset()
        po.factor, po.units = -1.0, -1.0
        sep.addChild(po)
    mat = coin.SoMaterial()
    mat.diffuseColor = rgb(color)
    mat.transparency = transparency
    sep.addChild(mat)
    pts, tris = face.tessellate(max(face.BoundBox.DiagonalLength / 80.0, 0.05))
    crd = coin.SoCoordinate3()
    crd.point.setValues(0, len(pts), [[p.x, p.y, p.z] for p in pts])
    fs = coin.SoIndexedFaceSet()
    idx = []
    for t in tris:
        idx += [t[0], t[1], t[2], -1]
    fs.coordIndex.setValues(0, len(idx), idx)
    sep.addChild(crd)
    sep.addChild(fs)
    return sep


def shape_node(shape, color, transparency=0.75, pickable=False):
    """Every face of shape tessellated into one translucent wash -- a whole-object highlight,
    dim enough to sit under the crisper per-face one FreeCAD's own selection colour draws,
    not replace it."""
    coin = _coin()
    sep = coin.SoSeparator()
    if not pickable:
        ps = coin.SoPickStyle()
        ps.style = coin.SoPickStyle.UNPICKABLE
        sep.addChild(ps)
    po = coin.SoPolygonOffset()
    po.factor, po.units = -1.0, -1.0
    sep.addChild(po)
    mat = coin.SoMaterial()
    mat.diffuseColor = rgb(color)
    mat.transparency = transparency
    sep.addChild(mat)
    pts, idx = [], []
    for face in shape.Faces:
        base = len(pts)
        fp, tris = face.tessellate(max(face.BoundBox.DiagonalLength / 80.0, 0.05))
        pts += fp
        for t in tris:
            idx += [base + t[0], base + t[1], base + t[2], -1]
    if not pts:
        return sep
    crd = coin.SoCoordinate3()
    crd.point.setValues(0, len(pts), [[p.x, p.y, p.z] for p in pts])
    fs = coin.SoIndexedFaceSet()
    fs.coordIndex.setValues(0, len(idx), idx)
    sep.addChild(crd)
    sep.addChild(fs)
    return sep


def arrow_node(origin, tip, color, radius):
    """Line from origin to tip with a cone at the tip, drawn on top of the model."""
    coin = _coin()
    sep = coin.SoAnnotation()
    mat = coin.SoBaseColor()
    mat.rgb = rgb(color)
    sep.addChild(mat)
    style = coin.SoDrawStyle()
    style.lineWidth = 3
    sep.addChild(style)
    crd = coin.SoCoordinate3()
    crd.point.setValues(0, 2, [[origin.x, origin.y, origin.z], [tip.x, tip.y, tip.z]])
    sep.addChild(crd)
    sep.addChild(coin.SoLineSet())
    d = tip - origin
    if d.Length > 1e-9:
        tr = coin.SoTransform()
        rot = App.Rotation(V(0, 1, 0), d)
        tr.translation = (tip.x, tip.y, tip.z)
        tr.rotation.setValue(*rot.Q)
        cone_sep = coin.SoSeparator()
        cone_sep.addChild(tr)
        cone = coin.SoCone()
        cone.bottomRadius, cone.height = radius, radius * 2.6
        cone_sep.addChild(cone)
        sep.addChild(cone_sep)
    return sep


def add(node, view=None):
    (view or Gui.activeView()).getSceneGraph().addChild(node)
    return node


def remove(node, view=None):
    try:
        (view or Gui.activeView()).getSceneGraph().removeChild(node)
    except Exception:
        pass


def ray(it, qpos):
    """(origin, direction) of the view ray through a viewport position (Qt coordinates)."""
    view = it.view
    x, y = it.coin(qpos)
    p = V(*view.getPointOnFocalPlane(x, y))
    cam = it.camera()
    if hasattr(cam, "height"):              # orthographic
        return p, V(*view.getViewDirection()).normalize()
    eye = V(*cam.position.getValue().getValue())
    return eye, (p - eye).normalize()


def hit_plane(origin, direction, point, normal):
    den = direction.dot(normal)
    if abs(den) < 1e-12:
        return None
    return origin + direction * ((point - origin).dot(normal) / den)


def closest_on_line(origin, direction, base, axis):
    """Point on the line (base, axis) closest to the ray (origin, direction)."""
    w0 = base - origin
    a, b, c = axis.dot(axis), axis.dot(direction), direction.dot(direction)
    d, e = axis.dot(w0), direction.dot(w0)
    den = a * c - b * b
    if abs(den) < 1e-12:
        return base
    s = (b * e - c * d) / den
    return base + axis * s

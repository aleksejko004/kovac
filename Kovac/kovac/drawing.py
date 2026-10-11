# SPDX-License-Identifier: LGPL-2.1-or-later
"""Drawings on TechDraw, the Kovač way (headless logic; the guided flow is in drawmode.py).

- A sheet = TechDraw page on one of our ISO 5457 / ISO 7200 templates, title block filled from
  the design (title, number, date, author, material, mass, scale, ISO 2768-mK).
- Views: a projection group (first angle by default) whose base view is placed first; projected
  and isometric views are added by the direction they are dragged out to.
- Section (hatched) and detail views from points picked on a view.
- Dimensions keep Kovač references (topo.py) to the model's vertices and edges and are re-attached
  to the view's 2D geometry after every regeneration; one that cannot be re-attached is flagged
  (red, "broken" in its label), never deleted.
- Hole and thread callouts come from the hole features; centerlines are drawn for holes seen
  from the side; ISO 286 fits on dimensions; parts list and balloons; PDF and DXF export.
"""
import datetime
import getpass
import os

import FreeCAD as App
import Part

import kovac
from kovac import iso286, model, topo

V = App.Vector
TEMPLATES = os.path.join(kovac.ROOT, "Resources", "templates")
SHEET_MM = {"A4": (210, 297), "A3": (297, 420), "A2": (420, 594), "A1": (594, 841), "A0": (841, 1189)}
SCALES = [(50, 1), (20, 1), (10, 1), (5, 1), (2, 1), (1, 1), (1, 2), (1, 5), (1, 10), (1, 20), (1, 50), (1, 100)]  # ISO 5455
# slot the view is dragged out to -> TechDraw projection name, per projection method
SLOTS = {"First angle": {"right": "Left", "left": "Right", "below": "Top", "above": "Bottom",
                         "below-right": "FrontTopLeft", "below-left": "FrontTopRight",
                         "above-right": "FrontBottomLeft", "above-left": "FrontBottomRight"},
         "Third angle": {"right": "Right", "left": "Left", "below": "Bottom", "above": "Top",
                         "above-right": "FrontTopRight", "above-left": "FrontTopLeft",
                         "below-right": "FrontBottomRight", "below-left": "FrontBottomLeft"}}
last_error = ""         # why the last dimension could not be attached (diagnostics)
errors = []
DEPTH, CBORE, CSINK = "↧", "⌴", "⌵"     # ISO 129 symbols: depth, counterbore, countersink


def _td():
    import TechDraw  # noqa: F401  (registers the TechDraw types)


# ---------------------------------------------------------------- sheets

def template_path(size, orientation):
    if size != "A4":
        orientation = "Landscape"
    return os.path.join(TEMPLATES, "Kovac_%s_%s.svg" % (size, orientation))


def sheet_size(page):
    tpl = page.Template
    return (tpl.Width.Value, tpl.Height.Value) if tpl is not None else SHEET_MM["A3"][::-1]


def new_page(doc, size="A3", orientation="Landscape", bodies=None, projection="First angle"):
    """A sheet with the title block filled in; returns the page."""
    _td()
    page = doc.addObject("TechDraw::DrawPage", "Drawing")
    tpl = doc.addObject("TechDraw::DrawSVGTemplate", "Sheet")
    tpl.Template = template_path(size, orientation)
    page.Template = tpl
    page.addProperty("App::PropertyString", "Projection", "Kovac", "First angle (ISO E) or Third angle")
    page.Projection = projection
    page.addProperty("App::PropertyStringList", "Bodies", "Kovac", "body ids drawn on this sheet")
    page.Bodies = [b.BodyId for b in (bodies or model.bodies(doc)) if not b.Shape.isNull()]
    page.Label = "Drawing %s" % doc.Label
    fill_title_block(page)
    return page


def page_bodies(page):
    return [b for b in (model.body_object(page.Document, i) for i in page.Bodies) if b is not None and not b.Shape.isNull()]


def fill_title_block(page, scale=None):
    doc = page.Document
    bodies = page_bodies(page)
    from kovac import materials
    mats = sorted({materials.LIBRARY[b.Material][0] for b in bodies if getattr(b, "Material", "") in materials.LIBRARY})
    masses = [materials.mass_properties(b.Shape, getattr(b, "Material", "")).get("mass") for b in bodies]
    fields = {
        "Title": doc.Label, "Subtitle": ", ".join(b.Label for b in bodies)[:60],
        "DrawingNumber": "KV-%s-001" % "".join(c for c in doc.Label.upper() if c.isalnum())[:10],
        "Date": datetime.date.today().isoformat(),
        "CreatedBy": getattr(doc, "CreatedBy", "") or getpass.getuser(),
        "Company": getattr(doc, "Company", ""),
        "Material": ", ".join(mats) or "—",
        "Mass": "%.3f kg" % sum(masses) if masses and None not in masses else "—",
        "GeneralTolerance": "ISO 2768-mK",
    }
    if scale is not None:
        fields["Scale"] = scale_text(scale)
    texts = dict(page.Template.EditableTexts)
    texts.update({k: v for k, v in fields.items() if k in texts})
    page.Template.EditableTexts = texts


def scale_text(s):
    return "%g:1" % s if s >= 1 else "1:%g" % round(1 / s)


def fit_scale(page, bodies, views=(1, 1)):
    """Largest ISO 5455 scale at which a grid of views (columns, rows) of the bodies fits the sheet,
    leaving room for the title block and dimensions."""
    w, h = sheet_size(page)
    box = App.BoundBox()
    for b in bodies:
        box.add(b.Shape.BoundBox)
    span = max(box.XLength, box.YLength, box.ZLength, 1e-6)
    room = min((w - 30 - 30 * views[0]) / views[0], (h - 20 - 50 - 30 * views[1]) / views[1])
    for num, den in SCALES:
        if span * num / den <= room:
            return num / den
    return SCALES[-1][0] / SCALES[-1][1]


# ---------------------------------------------------------------- views

def base_view(page, x, y, scale=None, direction=V(0, -1, 0)):
    """The first view: a projection group (the page's projection method) holding the front view."""
    doc = page.Document
    bodies = page_bodies(page)
    g = doc.addObject("TechDraw::DrawProjGroup", "Views")
    page.addView(g)
    g.Source = bodies
    g.ProjectionType = page.Projection
    g.ScaleType = "Custom"
    g.Scale = scale or fit_scale(page, bodies, (3, 2))
    front = g.addProjection("Front")
    front.Direction = direction
    g.X, g.Y = x, y
    doc.recompute()
    fill_title_block(page, g.Scale)
    return g


def add_projection(group, slot):
    """The view dragged out to slot ('right', 'below', 'below-right', ...): its projection by the
    group's method (first angle: the view from the left goes on the right, and so on)."""
    name = SLOTS[group.ProjectionType if group.ProjectionType in SLOTS else "First angle"][slot]
    have = [v for v in group.Views if v.Type == name]
    if have:
        return have[0]
    v = group.addProjection(name)
    group.Document.recompute()
    return v


def front_of(group):
    return next(v for v in group.Views if v.Type == "Front")


def _axes(view):
    """Model directions of the view's paper x and y."""
    d = V(view.Direction).normalize()
    x = V(view.XDirection).normalize() if getattr(view, "XDirection", None) and V(view.XDirection).Length > 1e-9 else None
    if x is None or abs(x.dot(d)) > 1e-6:
        x = V(1, 0, 0) if abs(d.x) < 0.9 else V(0, 1, 0)
        x = (x - d * x.dot(d)).normalize()
    return x, d.cross(x)


def _offset(view):
    """Where TechDraw put the projected model in the view's 2D coordinates: the outline of the
    view's own corners against the outline of the projected model corners (TechDraw centres on a
    box of its own; its reported centre can be off by a hundredth)."""
    s = view.getScale()
    proj = [view.projectPoint(v.Point) for o in view.Source for v in o.Shape.Vertexes]
    seen = view.getVisibleVertexes()
    if not proj or not seen:
        c = view.projectPoint(view.getGeometricCenter())
        return -c.x * s, c.y * s
    px, py = [q.x * s for q in proj], [-q.y * s for q in proj]
    vx, vy = [q.x for q in seen], [q.y for q in seen]
    return ((min(vx) + max(vx)) - (min(px) + max(px))) / 2, ((min(vy) + max(vy)) - (min(py) + max(py))) / 2


def to_view(view, p):
    """Model point -> the view's own 2D coordinates, the ones its edges use (scaled, y down)."""
    q = view.projectPoint(p)
    s = view.getScale()
    dx, dy = _offset(view)
    return V(q.x * s + dx, -q.y * s + dy, 0)


def view_point_to_model(view, u, v, depth_point=None):
    """A point on a view (its 2D coordinates) -> model point, the exact inverse of to_view
    (on the plane through depth_point, else through the origin)."""
    x, y = _axes(view)
    s = view.getScale()
    dx, dy = _offset(view)
    p = x * ((u - dx) / s) + y * (-(v - dy) / s)
    if depth_point is not None:
        d = V(view.Direction).normalize()
        p = p + d * (depth_point - p).dot(d)
    return p


def section(page, view, horizontal, offset, x, y, symbol="A"):
    """A section through `view`: a cutting line across the paper (horizontal or vertical) at
    `offset` in the view's own 2D coordinates (y down; 0 is the middle); hatched cut faces (ISO 45° lines)."""
    doc = page.Document
    ax, ay = _axes(view)
    normal = ay if horizontal else ax          # looking along the cut, away from the cutting line
    c = view.getGeometricCenter()
    on_line = view_point_to_model(view, 0 if horizontal else offset, offset if horizontal else 0, c)
    origin = c + normal * (on_line - c).dot(normal)
    s = doc.addObject("TechDraw::DrawViewSection", "Section")
    page.addView(s)
    s.BaseView = view
    s.Source = view.Source
    s.SectionNormal = normal
    s.Direction = normal
    s.SectionOrigin = origin
    s.SectionSymbol = symbol
    s.Scale, s.ScaleType = view.getScale(), "Custom"
    s.CutSurfaceDisplay = "PatHatch"
    s.NameGeomPattern = "ansi31"                # 45° lines, as ISO 128-50 general cuts
    s.X, s.Y = x, y
    doc.recompute()
    return s


def detail(page, view, u, v, radius, x, y, factor=2.0, symbol="B"):
    """An enlarged detail of `view` around its 2D point (u, v) with the given radius (paper mm)."""
    doc = page.Document
    d = doc.addObject("TechDraw::DrawViewDetail", "Detail")
    page.addView(d)
    d.BaseView = view
    d.Source = view.Source
    d.Direction = view.Direction
    if hasattr(view, "XDirection"):
        d.XDirection = view.XDirection
    d.AnchorPoint = V(u / view.getScale(), v / view.getScale(), 0)
    d.Radius = radius / view.getScale()
    d.Scale, d.ScaleType = view.getScale() * factor, "Custom"
    d.Reference = symbol
    d.X, d.Y = x, y
    doc.recompute()
    return d


def views_of(page):
    out = []
    for v in page.Views:
        if v.TypeId == "TechDraw::DrawProjGroup":
            out += list(v.Views)
        elif v.isDerivedFrom("TechDraw::DrawViewPart"):
            out.append(v)
    return out


# ---------------------------------------------------------------- associative dimensions

def _edge_2d(view, edge, tol=1e-3):
    """Index of the view's 2D edge that is the projection of model edge `edge`, or None."""
    pts = [to_view(view, v.Point) for v in edge.Vertexes]
    is_circle = isinstance(edge.Curve, Part.Circle)
    for i, e in enumerate(view.getVisibleEdges()):
        if is_circle:
            if isinstance(e.Curve, Part.Circle):
                c = to_view(view, edge.Curve.Center)
                if (V(e.Curve.Center.x, e.Curve.Center.y, 0) - c).Length < tol \
                        and abs(e.Curve.Radius - edge.Curve.Radius * view.getScale()) < tol:
                    return i
            continue
        ends = [V(p.Point.x, p.Point.y, 0) for p in e.Vertexes]
        if len(ends) == len(pts) and all(min((q - p).Length for q in ends) < tol for p in pts):
            return i
    return None


def _vertex_2d(view, p, tol=1e-3):
    q = to_view(view, p)
    for i, w in enumerate(view.getVisibleVertexes()):
        if (V(w.x, w.y, 0) - q).Length < tol:
            return i
    return None


def dimension(page, view, kind, refs, x, y, fit=""):
    """A dimension on `view` between model elements given as Kovač references (from
    topo.make_ref): kind 'DistanceX' / 'DistanceY' / 'Distance' between two vertices, or
    'Diameter' / 'Radius' on a circular edge. It stays attached through regenerations."""
    doc = page.Document
    d = doc.addObject("TechDraw::DrawViewDimension", "Dimension")
    d.Type = kind
    d.addProperty("App::PropertyStringList", "KovacRefs", "Kovac", "model references the dimension measures")
    d.addProperty("App::PropertyString", "KovacFit", "Kovac", "ISO 286 fit, e.g. H7")
    d.addProperty("App::PropertyLink", "KovacView", "Kovac", "the view the dimension is drawn in")
    d.KovacRefs = list(refs)
    d.KovacView = view
    d.KovacFit = fit
    page.addView(d)
    d.X, d.Y = x, y
    attach(d, view)
    doc.recompute()
    return d


def attach(dim, view=None):
    """(Re)bind a Kovač dimension's 2D references from its model references. True if it is whole;
    otherwise it is flagged as broken and left in place."""
    view = view or getattr(dim, "KovacView", None) or (dim.References2D[0][0] if dim.References2D else None)
    try:
        subs = []
        for ref in dim.KovacRefs:
            r = topo.loads(ref)
            body = model.body_object(dim.Document, r["b"])
            el = topo.element(model.state_of(body.Tip), ref)[1]
            if el.ShapeType == "Vertex":
                i = _vertex_2d(view, el.Point)
                subs.append("Vertex%d" % i if i is not None else None)
            else:
                i = _edge_2d(view, el)
                subs.append("Edge%d" % i if i is not None else None)
        if None in subs:
            raise topo.Broken(None, "not visible in this view")
        dim.References2D = [(view, s) for s in subs]
        if getattr(dim, "KovacFit", ""):
            apply_fit(dim, dim.KovacFit)
        _flag(dim, False)
        return True
    except (topo.Broken, KeyError, IndexError, AttributeError, ValueError) as e:
        global last_error
        last_error = "%s: %s" % (dim.Label, e)
        errors.append(last_error)
        _flag(dim, True)
        return False


def _flag(dim, broken):
    base = dim.Label.replace(" (broken)", "")
    dim.Label = base + (" (broken)" if broken else "")
    vo = getattr(dim, "ViewObject", None)
    if vo is not None and hasattr(vo, "Color"):
        vo.Color = (0.84, 0.27, 0.27) if broken else (0.0, 0.0, 0.0)


def broken(page):
    return [o for o in page.Views if o.TypeId == "TechDraw::DrawViewDimension" and o.Label.endswith("(broken)")]


def refresh(page):
    """After the model changed: views regenerate, then every Kovač dimension and callout
    re-attaches to the new 2D geometry."""
    doc = page.Document
    doc.recompute()
    for o in page.Views:
        if o.TypeId == "TechDraw::DrawViewDimension" and hasattr(o, "KovacRefs"):
            attach(o)
        if o.TypeId == "TechDraw::DrawViewDimension" and hasattr(o, "KovacHole"):
            _attach_callout(o)
    fill_title_block(page, next((v.Scale for v in page.Views if v.TypeId == "TechDraw::DrawProjGroup"), None))
    doc.recompute()


def apply_fit(dim, fit):
    """ISO 286 fit on a dimension: the class after the value, limits as tolerances."""
    size = dim.getRawValue() if hasattr(dim, "getRawValue") else None
    if not size:
        return
    up, lo = iso286.limits(size, fit)
    dim.FormatSpec = ("⌀%.2f " if dim.Type in ("Diameter",) else "%.2f ") + fit
    dim.OverTolerance, dim.UnderTolerance = up, lo
    dim.EqualTolerance = False


# ---------------------------------------------------------------- hole and thread callouts, centerlines

def holes(doc):
    """(feature, [(centre, axis)], drill Ø, callout text) for every working Hole feature."""
    from kovac import features
    out = []
    for fp in model.items(doc):
        if getattr(fp, "Kind", "") != "Hole" or fp.Status or fp.Suppressed or not model.active(fp):
            continue
        _, face = topo.element(model.input_state(fp), fp.Face)
        centres, n = fp.Proxy.centres(fp, face)
        d, cb, cs, thread = features.hole_dims(fp)
        n_txt = "%d× " % len(centres) if len(centres) > 1 else ""
        deep = "THRU" if fp.ThroughAll else "%s%g" % (DEPTH, fp.Depth.Value)
        if thread:
            tl = fp.ThreadLength.Value or fp.Depth.Value
            text = "%s%s - 6H %s%g" % (n_txt, thread, DEPTH, tl) if not fp.ThroughAll else "%s%s - 6H THRU" % (n_txt, thread)
        elif cb:
            text = "%s⌀%g %s  %s⌀%g %s%g" % (n_txt, d, deep, CBORE, cb[0], DEPTH, cb[1])
        elif cs:
            text = "%s⌀%g %s  %s⌀%g × 90°" % (n_txt, d, deep, CSINK, cs)
        else:
            text = "%s⌀%g %s" % (n_txt, d, deep)
        out.append((fp, [(c, -n) for c in centres], d, text))
    return out


def hole_callouts(page, view, offset=(12, 12)):
    """One callout per hole feature, on the first of its circles seen end-on in `view`."""
    doc = page.Document
    made = []
    for fp, axes, d, text in holes(doc):
        if abs(abs(axes[0][1].dot(V(view.Direction).normalize())) - 1) > 1e-6:
            continue                                   # holes seen from the side get centerlines instead
        dim = doc.addObject("TechDraw::DrawViewDimension", "Callout")
        dim.Type = "Diameter"
        dim.addProperty("App::PropertyString", "KovacHole", "Kovac", "hole feature this callout describes")
        dim.addProperty("App::PropertyFloat", "KovacDiameter", "Kovac", "")
        dim.KovacHole, dim.KovacDiameter = fp.Name, d
        dim.Arbitrary = True
        dim.FormatSpec = text
        page.addView(dim)
        dim.References2D = [(view, "Edge0")]
        _attach_callout(dim, view)
        c2 = to_view(view, axes[0][0])
        dim.X, dim.Y = c2.x + offset[0], c2.y + offset[1]
        made.append(dim)
    doc.recompute()
    return made


def _attach_callout(dim, view=None):
    view = view or dim.References2D[0][0]
    fp = dim.Document.getObject(dim.KovacHole)
    found = None
    if fp is not None:
        for f, axes, d, text in holes(dim.Document):
            if f is not fp:
                continue
            dim.FormatSpec = text
            dim.KovacDiameter = d
            for c, _ in axes:
                q = to_view(view, c)
                for i, e in enumerate(view.getVisibleEdges()):
                    if isinstance(e.Curve, Part.Circle) and (V(e.Curve.Center.x, e.Curve.Center.y, 0) - q).Length < 1e-3 \
                            and abs(e.Curve.Radius - d / 2 * view.getScale()) < 1e-3:
                        found = i
                        break
                if found is not None:
                    break
    if found is None:
        _flag(dim, True)
        return False
    dim.References2D = [(view, "Edge%d" % found)]
    _flag(dim, False)
    return True


def centerlines(view):
    """Dash-dot centerlines (ISO 128) for holes seen from the side, a little past each end."""
    made = []
    d = V(view.Direction).normalize()
    for fp, axes, dia, _ in holes(view.Document):
        for c, axis in axes:
            if abs(axis.dot(d)) > 1e-6:
                continue
            depth = _hole_depth(fp)
            a, b = to_view(view, c - axis * 2), to_view(view, c + axis * (depth + 2))
            made.append(view.makeCosmeticLine(_unscale(view, a), _unscale(view, b), 4, 0.18))
    return made


def _hole_depth(fp):
    if fp.ThroughAll:
        bodies = model.bodies(fp.Document)
        box = App.BoundBox()
        for b in bodies:
            box.add(b.Shape.BoundBox)
        return box.DiagonalLength
    return fp.Depth.Value


def _unscale(view, p):
    """Cosmetic geometry is given unscaled, in the view's own (y down) coordinates."""
    s = view.getScale()
    return V(p.x / s, p.y / s, 0)


# ---------------------------------------------------------------- parts list, balloons

def bom_rows(page):
    """One row per distinct body on the sheet: (item, qty, name, material, mass)."""
    from kovac import materials
    rows = []
    for i, b in enumerate(page_bodies(page), 1):
        m = materials.mass_properties(b.Shape, getattr(b, "Material", "")).get("mass")
        mat = materials.LIBRARY[b.Material][0] if getattr(b, "Material", "") in materials.LIBRARY else "—"
        rows.append((str(i), "1", b.Label, mat, "%.3f kg" % m if m else "—"))
    return rows


def parts_list(page, x=None, y=None, rows=None):
    """Parts list as a drawn table (ISO 7573 column order: item, quantity, name, material, mass),
    by default straight above the title block, right-aligned with it."""
    rows = rows or bom_rows(page)
    widths = (12, 12, 60, 50, 26)
    head = ("Item", "Qty", "Name", "Material", "Mass")
    rh, w = 7.0, sum(widths)
    hgt = rh * (len(rows) + 1)
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" viewBox="0 0 %g %g">' % (w, hgt, w, hgt)]
    for r, cells in enumerate([head] + list(rows)):
        y0 = r * rh
        x0 = 0
        for cw, txt in zip(widths, cells):
            svg.append('<rect x="%g" y="%g" width="%g" height="%g" fill="none" stroke="#000" stroke-width="%g"/>'
                       % (x0, y0, cw, rh, 0.5 if r == 0 else 0.25))
            svg.append('<text x="%g" y="%g" font-family="Inter, Segoe UI, sans-serif" font-size="3" font-weight="%d">%s</text>'
                       % (x0 + 1.5, y0 + rh - 2.2, 700 if r == 0 else 400, txt))
            x0 += cw
    svg.append("</svg>")
    t = page.Document.addObject("TechDraw::DrawViewSymbol", "PartsList")
    t.Symbol = "\n".join(svg)
    page.addView(t)
    if x is None:
        pw, _ph = sheet_size(page)
        x, y = pw - 10 - w / 2, 10 + 40 + hgt / 2          # frame 10 mm, title block 40 mm high
    t.X, t.Y = x, y
    return t


def balloon(page, view, item, u, v, x, y):
    """A balloon with `item` pointing at the view's 2D point (u, v)."""
    b = page.Document.addObject("TechDraw::DrawViewBalloon", "Balloon")
    b.SourceView = view
    b.OriginX, b.OriginY = u, v
    b.Text = str(item)
    b.BubbleShape = "Circular"
    page.addView(b)
    b.X, b.Y = x, y
    return b


# ---------------------------------------------------------------- export

def export_dxf(page, path):
    import TechDraw
    page.Document.recompute()
    TechDraw.writeDXFPage(page, path)
    return path


def export_pdf(page, path):
    """Needs the GUI (TechDraw prints the page view)."""
    import TechDrawGui
    page.Document.recompute()
    TechDrawGui.exportPageAsPdf(page, path)
    return path


def check_dxf(path):
    """(entity counts, texts) of a DXF file; raises if it is not a well-formed DXF."""
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = [ln.strip() for ln in f.read().splitlines()]
    pairs = list(zip(lines[0::2], lines[1::2]))
    if not pairs or pairs[-1] != ("0", "EOF") or ("2", "ENTITIES") not in pairs:
        raise ValueError("not a complete DXF")
    counts, texts = {}, []
    for (code, value), (code2, value2) in zip(pairs, pairs[1:] + [("", "")]):
        if code == "0" and value not in ("SECTION", "ENDSEC", "EOF", "TABLE", "ENDTAB"):
            counts[value] = counts.get(value, 0) + 1
        if code == "1":
            texts.append(value)
    return counts, texts


def check_pdf(path):
    with open(path, "rb") as f:
        data = f.read()
    if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-1024:]:
        raise ValueError("not a complete PDF")
    return data.count(b"/Type /Page") - data.count(b"/Type /Pages")

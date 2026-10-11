# SPDX-License-Identifier: LGPL-2.1-or-later
"""Drawing mode: the guided flow on a TechDraw sheet, in Kovač's look and logic.

New drawing -> a small panel (sheet, projection, scale) -> the base view follows the cursor and
a click puts it down -> drag from the base view to the right, down or diagonally to drop in the
projected or isometric view there. Sections, details, dimensions, balloons and the parts list
are made by clicking on the sheet; a dashed accent ghost previews every step, the snap marker
shows when a click catches a corner, Esc steps out. Everything is one undo step per action.
Dimensions and callouts re-attach to the model after every regeneration (drawing.refresh).
"""
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

import kovac
from kovac import commands, drawing, model, palette

V = App.Vector
REZ = 10.0          # TechDraw scene units per paper millimetre (scene y points down)
SNAP_PX = 14
_flows = {}


# ---------------------------------------------------------------- the sheet on screen

def page_view_widget():
    """(page, QGVPage) of the active drawing tab, or (None, None)."""
    v = Gui.activeView()
    if v is None or not hasattr(v, "getPage"):
        return None, None
    gv = next((w for w in Gui.getMainWindow().findChildren(QtWidgets.QGraphicsView)
               if w.metaObject().className() == "TechDrawGui::QGVPage" and w.isVisible()), None)
    return v.getPage(), gv


def to_paper(gv, pos):
    s = gv.mapToScene(pos)
    return s.x() / REZ, -s.y() / REZ


def to_screen(gv, x, y):
    return gv.mapFromScene(QtCore.QPointF(x * REZ, -y * REZ))


def view_origin(view):
    """Paper position of a view's centre (items of a projection group are relative to it)."""
    group = next((o for o in view.InList if o.TypeId == "TechDraw::DrawProjGroup"), None)
    x, y = view.X.Value if hasattr(view.X, "Value") else view.X, view.Y.Value if hasattr(view.Y, "Value") else view.Y
    if group is not None:
        return group.X.Value + x, group.Y.Value + y
    return x, y


def view_local(view, x, y):
    """Paper point -> the view's own 2D coordinates (y down)."""
    ox, oy = view_origin(view)
    return x - ox, oy - y


def view_at(page, gv, pos, margin=3.0):
    """The drawing view (DrawViewPart) whose outline (plus a margin, paper mm) is under the cursor,
    the smallest if several; by geometry, not by TechDraw's scene items (rebuilt on every recompute)."""
    from kovac import drawing
    x, y = to_paper(gv, pos)
    best = None
    for v in drawing.views_of(page):
        w, h = _view_size(v)
        ox, oy = view_origin(v)
        if abs(x - ox) <= w / 2 + margin and abs(y - oy) <= h / 2 + margin and (best is None or w * h < best[0]):
            best = (w * h, v)
    return best and best[1]


def open_page(page):
    """Show the sheet in its tab and make it the active one (staying in Kovač); returns its QGVPage."""
    page.ViewObject.show()
    mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    for _ in range(100):                 # the tab appears a few event-loop turns later
        QtWidgets.QApplication.processEvents()
        for sub in mdi.subWindowList():
            w = sub.widget()
            if w.metaObject().className() == "TechDrawGui::MDIViewPage" and sub.windowTitle().startswith(page.Label):
                if mdi.activeSubWindow() is not sub:
                    mdi.setActiveSubWindow(sub)
                gv = next((g for g in w.findChildren(QtWidgets.QGraphicsView)
                           if g.metaObject().className() == "TechDrawGui::QGVPage"), None)
                if gv is not None and gv.isVisible():
                    return gv
    return None


def ensure_page(doc):
    """The active drawing, opening the document's first one if needed."""
    page, gv = page_view_widget()
    if page is None:
        pages = [o for o in doc.Objects if o.TypeId == "TechDraw::DrawPage"]
        if not pages:
            raise ValueError("Make a drawing first (New drawing).")
        gv = open_page(pages[0])
        page = pages[0] if gv is not None else None
    return page, gv


# ---------------------------------------------------------------- ghosts (previews on the sheet)

def _pen():
    pen = QtGui.QPen(QtGui.QColor(palette.accent()), 2.0)
    pen.setCosmetic(True)
    pen.setStyle(QtCore.Qt.DashLine)
    return pen


class Ghost:
    """A dashed accent outline on the sheet: rectangle, circle or line, in paper mm."""

    def __init__(self, gv):
        self.gv, self.item = gv, None

    def _set(self, item):
        self.clear()
        item.setPen(_pen())
        item.setZValue(10000)
        self.gv.scene().addItem(item)
        self.item = item

    def rect(self, x, y, w, h):
        self._set(QtWidgets.QGraphicsRectItem((x - w / 2) * REZ, -(y + h / 2) * REZ, w * REZ, h * REZ))

    def circle(self, x, y, r):
        self._set(QtWidgets.QGraphicsEllipseItem((x - r) * REZ, -(y + r) * REZ, 2 * r * REZ, 2 * r * REZ))

    def line(self, x1, y1, x2, y2):
        self._set(QtWidgets.QGraphicsLineItem(x1 * REZ, -y1 * REZ, x2 * REZ, -y2 * REZ))

    def clear(self):
        if self.item is not None:
            self.gv.scene().removeItem(self.item)
            self.item = None


def _view_size(view):
    """Paper size (w, h) of a view's drawing."""
    xs = [p.x for p in view.getVisibleVertexes()] or [0]
    ys = [p.y for p in view.getVisibleVertexes()] or [0]
    return max(xs) - min(xs), max(ys) - min(ys)


# ---------------------------------------------------------------- the flow

class Flow(QtCore.QObject):
    """One guided step sequence on the sheet; installed on the page view while it runs."""

    def __init__(self, page, gv, steps):
        super().__init__(gv.viewport())
        self.page, self.gv, self.steps = page, gv, list(steps)
        self.ghost = Ghost(gv)
        from kovac.navigation import SnapMarker
        self.marker = SnapMarker(gv.viewport())
        self.data = {}
        gv.viewport().installEventFilter(self)
        gv.viewport().setMouseTracking(True)
        _flows[id(gv)] = self
        self.esc = QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Escape), gv)
        self.esc.activated.connect(self.finish)
        self.tab = QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Tab), gv)
        self.tab.activated.connect(self.toggle)
        self.hint()

    @property
    def step(self):
        return self.steps[0] if self.steps else None

    def hint(self):
        text = HINTS.get(self.step, "")
        if text:
            commands.report(text + "  (Esc to stop)", error=False)

    def advance(self, *more):
        self.steps = list(more) + self.steps[1:]
        self.ghost.clear()
        self.marker.hide()
        if not self.steps:
            self.finish()
        else:
            self.hint()

    def finish(self):
        self.ghost.clear()
        self.marker.hide()
        self.gv.viewport().removeEventFilter(self)
        self.esc.setEnabled(False)
        self.tab.setEnabled(False)
        _flows.pop(id(self.gv), None)
        commands.report("", error=False)

    def toggle(self):
        self.data["vertical"] = not self.data.get("vertical", False)
        self.preview(self.data.get("last"))

    # Qt -------------------------------------------------------------------------
    def eventFilter(self, _o, ev):
        t = ev.type()
        try:
            if t == QtCore.QEvent.MouseMove:
                self.data["last"] = ev.position().toPoint()
                self.preview(self.data["last"])
                return self.data.get("dragging", False)
            if t == QtCore.QEvent.MouseButtonPress and ev.button() == QtCore.Qt.LeftButton:
                return self.press(ev.position().toPoint())
            if t == QtCore.QEvent.MouseButtonRelease and ev.button() == QtCore.Qt.LeftButton:
                return self.release(ev.position().toPoint())
        except Exception as e:      # say so, never leave the sheet stuck in a half-done step
            import traceback
            commands.last_trace = traceback.format_exc()
            commands.report("Drawing step failed: %s" % e)
            self.finish()
            return True
        return False

    # steps ------------------------------------------------------------------------
    def preview(self, pos):
        if pos is None:
            return
        x, y = to_paper(self.gv, pos)
        s = self.step
        if s in ("place_base", "place_section", "place_detail", "place_list", "place_balloon", "place_dim"):
            w, h = self.data.get("size", (40, 30))
            if s == "place_balloon":
                self.ghost.circle(x, y, 4)
            else:
                self.ghost.rect(x, y, w, h)
        elif s == "drag_out" and self.data.get("dragging"):
            slot = self.slot(x, y)
            if slot:
                gx, gy, w, h = self.slot_box(slot)
                self.ghost.rect(gx, gy, w, h)
            else:
                self.ghost.clear()
        elif s == "section_line":
            v = self.data["view"]
            ox, oy = view_origin(v)
            w, h = _view_size(v)
            off, snapped = self.cut_snap(v, *view_local(v, x, y))
            if self.data.get("vertical"):
                x = ox + off
                self.ghost.line(x, oy - h / 2 - 6, x, oy + h / 2 + 6)
            else:
                y = oy - off
                self.ghost.line(ox - w / 2 - 6, y, ox + w / 2 + 6, y)
            if snapped:
                self.marker.show_at(QtCore.QPointF(to_screen(self.gv, x if self.data.get("vertical") else ox,
                                                             oy if self.data.get("vertical") else y)), "point")
            else:
                self.marker.hide()
        elif s == "detail_radius":
            cx, cy = self.data["centre_paper"]
            self.ghost.circle(cx, cy, max(2.0, ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5))
        elif s in ("dim_first", "dim_second"):
            hit = self.vertex_near(pos)
            if hit:
                self.marker.show_at(QtCore.QPointF(to_screen(self.gv, *hit[2])), "point")
            else:
                self.marker.hide()

    def press(self, pos):
        x, y = to_paper(self.gv, pos)
        s = self.step
        doc = self.page.Document
        if s == "place_base":
            with commands.transaction("Base view", doc):
                g = drawing.base_view(self.page, x, y, scale=self.data.get("scale"))
            self.data["group"] = g
            self.advance("drag_out")
            return True
        if s == "drag_out":
            v = view_at(self.page, self.gv, pos)
            g = self.data.get("group")
            if g is not None and v is not None and v.Type == "Front":
                self.data["dragging"] = True
                return True
            return False                                    # let TechDraw handle other clicks
        if s == "section_pick":
            v = view_at(self.page, self.gv, pos)
            if v is None:
                return True
            self.data["view"] = v
            self.advance("section_line", "place_section")
            return True
        if s == "section_line":
            v = self.data["view"]
            off, _ = self.cut_snap(v, *view_local(v, x, y))
            self.data["cut"] = (not self.data.get("vertical"), off)
            self.data["size"] = _view_size(v)
            self.advance()
            return True
        if s == "place_section":
            horizontal, off = self.data["cut"]
            v = self.data["view"]
            # view y points down; the section's offset is along the cut normal in model terms
            with commands.transaction("Section view", doc):
                drawing.section(self.page, v, horizontal, off, x, y, symbol=self.next_symbol())
            self.advance()
            return True
        if s == "detail_centre":
            v = view_at(self.page, self.gv, pos)
            if v is None:
                return True
            self.data["view"], self.data["centre_paper"] = v, (x, y)
            self.advance("detail_radius", "place_detail")
            return True
        if s == "detail_radius":
            cx, cy = self.data["centre_paper"]
            r = max(2.0, ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5)
            self.data["radius"] = r
            self.data["size"] = (4 * r, 4 * r)
            self.advance()
            return True
        if s == "place_detail":
            v = self.data["view"]
            u, w = view_local(v, *self.data["centre_paper"])
            with commands.transaction("Detail view", doc):
                drawing.detail(self.page, v, u, w, self.data["radius"], x, y, symbol=self.next_symbol())
            self.advance()
            return True
        if s in ("dim_first", "dim_second"):
            hit = self.vertex_near(pos)
            if hit is None:
                return True
            self.data.setdefault("picks", []).append(hit)
            if s == "dim_second":
                self.data["size"] = (30, 8)
            self.advance()
            return True
        if s == "place_dim":
            (v, ref1, _), (_, ref2, _) = self.data["picks"][:2]
            a, b = (drawing.to_view(v, _point(doc, ref)) for ref in (ref1, ref2))
            kind = "DistanceX" if abs(a.y - b.y) < 1e-6 else "DistanceY" if abs(a.x - b.x) < 1e-6 else "Distance"
            u, w = view_local(v, x, y)
            with commands.transaction("Dimension", doc):
                drawing.dimension(self.page, v, kind, [ref1, ref2], u, -w)
            self.data.pop("picks", None)
            self.steps = ["dim_first", "dim_second", "place_dim"]       # keep dimensioning until Esc
            self.ghost.clear()
            self.hint()
            return True
        if s == "balloon_pick":
            v = view_at(self.page, self.gv, pos)
            if v is None:
                return True
            self.data["view"], self.data["origin"] = v, view_local(v, x, y)
            self.advance()
            return True
        if s == "place_balloon":
            v = self.data["view"]
            u, w = view_local(v, x, y)
            item = self.data.setdefault("item", 1)
            with commands.transaction("Balloon", doc):
                drawing.balloon(self.page, v, item, self.data["origin"][0], -self.data["origin"][1], u, -w)
            self.data["item"] = item + 1
            self.steps = ["balloon_pick", "place_balloon"]
            self.ghost.clear()
            self.hint()
            return True
        if s == "place_list":
            with commands.transaction("Parts list", doc):
                drawing.parts_list(self.page, x, y)
            self.advance()
            return True
        return False

    def release(self, pos):
        if self.step == "drag_out" and self.data.pop("dragging", False):
            self.ghost.clear()
            x, y = to_paper(self.gv, pos)
            slot = self.slot(x, y)
            if slot:
                with commands.transaction("Projected view", self.page.Document):
                    drawing.add_projection(self.data["group"], slot)
            return True
        return False

    # helpers ----------------------------------------------------------------------------
    def slot(self, x, y):
        """Which neighbour of the base view the cursor is dragged to (None near the base)."""
        g = self.data.get("group")
        if g is None:
            return None
        front = drawing.front_of(g)
        ox, oy = view_origin(front)
        w, h = _view_size(front)
        dx, dy = x - ox, y - oy
        if abs(dx) < w / 2 + 5 and abs(dy) < h / 2 + 5:
            return None
        horiz = "right" if dx > w / 2 else "left" if dx < -w / 2 else ""
        vert = "above" if dy > h / 2 else "below" if dy < -h / 2 else ""
        return "-".join(p for p in (vert, horiz) if p) or None

    def slot_box(self, slot):
        front = drawing.front_of(self.data["group"])
        ox, oy = view_origin(front)
        w, h = _view_size(front)
        gap = 15
        dx = (w + gap) * (1 if "right" in slot else -1 if "left" in slot else 0)
        dy = (h + gap) * (1 if "above" in slot else -1 if "below" in slot else 0)
        return ox + dx, oy + dy, w, h

    def cut_snap(self, v, u, w):
        """Cut line position (view coordinates along the cut's normal) snapped to the view's middle,
        a hole centre or a corner when within SNAP_PX; (position, snapped)."""
        vertical = self.data.get("vertical")
        val = u if vertical else w
        cands = [0.0]
        for _fp, axes, _d, _t in drawing.holes(self.page.Document):
            cands += [(drawing.to_view(v, c).x if vertical else drawing.to_view(v, c).y) for c, _a in axes]
        for b in drawing.page_bodies(self.page):
            cands += [(drawing.to_view(v, p.Point).x if vertical else drawing.to_view(v, p.Point).y) for p in b.Shape.Vertexes]
        best = min(cands, key=lambda c: abs(c - val))
        px_per_mm = self.gv.transform().m11() * REZ
        return (best, True) if abs(best - val) * px_per_mm <= SNAP_PX else (val, False)

    def next_symbol(self):
        used = {getattr(o, "SectionSymbol", "") or getattr(o, "Reference", "") for o in self.page.Views}
        return next(c for c in "ABCDEFGHJKLMNPRSTUVWXYZ" if c not in used)

    def vertex_near(self, pos):
        """(view, model vertex reference, paper point) of a view corner within SNAP_PX of pos."""
        v = view_at(self.page, self.gv, pos)
        if v is None:
            return None
        best = None
        for b in drawing.page_bodies(self.page):
            st = model.state_of(b.Tip)
            for i, vx in enumerate(b.Shape.Vertexes, 1):
                q = drawing.to_view(v, vx.Point)
                ox, oy = view_origin(v)
                px, py = ox + q.x, oy - q.y
                sp = to_screen(self.gv, px, py)
                d = ((sp.x() - pos.x()) ** 2 + (sp.y() - pos.y()) ** 2) ** 0.5
                toward = -vx.Point.dot(V(v.Direction))          # the corner nearest the viewer wins a tie
                if d <= SNAP_PX and (best is None or (d, toward) < best[0]):
                    from kovac import topo
                    best = ((d, toward), v, topo.dumps(topo.make_ref(st, b.BodyId, "Vertex%d" % i)), (px, py))
        return best and best[1:]


def _point(doc, ref):
    from kovac import topo
    r = topo.loads(ref)
    body = model.body_object(doc, r["b"])
    return topo.element(model.state_of(body.Tip), ref)[1].Point


HINTS = {
    "place_base": "Click on the sheet to put the base view down",
    "drag_out": "Drag from the base view to the right, down or diagonally for projected and isometric views",
    "section_pick": "Click the view to cut",
    "section_line": "Move the cut line and click (Tab: vertical / horizontal)",
    "place_section": "Click where the section goes",
    "detail_centre": "Click the centre of the detail on a view",
    "detail_radius": "Move to size the detail circle and click",
    "place_detail": "Click where the detail goes",
    "dim_first": "Click the first corner",
    "dim_second": "Click the second corner",
    "place_dim": "Click where the dimension goes",
    "balloon_pick": "Click the part the balloon points at",
    "place_balloon": "Click where the balloon goes",
    "place_list": "Click where the parts list goes",
}


def start(*steps, **data):
    doc = App.ActiveDocument
    if doc is None:
        raise ValueError("Open a design first.")
    page, gv = ensure_page(doc)
    old = _flows.get(id(gv))
    if old is not None:
        old.finish()
    f = Flow(page, gv, steps)
    f.data.update(data)
    if "group" not in f.data:
        f.data["group"] = next((o for o in page.Views if o.TypeId == "TechDraw::DrawProjGroup"), None)
    return f


# ---------------------------------------------------------------- commands

def new_drawing():
    """Panel: sheet, projection, scale -> the sheet opens and the base view follows the cursor."""
    doc = App.ActiveDocument
    if doc is None or not [b for b in model.bodies(doc) if not b.Shape.isNull()]:
        raise ValueError("Model a body first; a drawing shows bodies.")
    from kovac import panel
    w = QtWidgets.QWidget()
    form = QtWidgets.QFormLayout(w)
    sheet = QtWidgets.QComboBox()
    sheet.addItems(["A3 landscape", "A4 landscape", "A4 portrait", "A2 landscape", "A1 landscape", "A0 landscape"])
    proj = QtWidgets.QComboBox()
    proj.addItems(["First angle (ISO E)", "Third angle (ISO A)"])
    scale = QtWidgets.QComboBox()
    scale.addItems(["Fit the sheet"] + [drawing.scale_text(n / d) for n, d in drawing.SCALES])
    form.addRow("Sheet", sheet)
    form.addRow("Projection", proj)
    form.addRow("Scale", scale)
    ok, cancel = QtWidgets.QPushButton("OK", objectName="kovacOK"), QtWidgets.QPushButton("Cancel")
    row = QtWidgets.QHBoxLayout()
    row.addStretch()
    row.addWidget(cancel)
    row.addWidget(ok)
    form.addRow(row)
    d = panel.dock("NewDrawing", "New drawing", w, floating=True)
    d.setWidget(w)
    d.show()

    def accept():
        size, orient = sheet.currentText().split()
        with commands.transaction("New drawing", doc):
            page = drawing.new_page(doc, size, orient.capitalize(),
                                    projection="First angle" if proj.currentIndex() == 0 else "Third angle")
        d.close()
        open_page(page)
        from kovac import shell
        shell.set_mode("Drawing")
        bodies = drawing.page_bodies(page)
        sc = drawing.fit_scale(page, bodies, (3, 2)) if scale.currentIndex() == 0 else \
            (lambda n, dd: n / dd)(*drawing.SCALES[scale.currentIndex() - 1])
        f = start("place_base", scale=sc)
        box = App.BoundBox()
        for b in bodies:
            box.add(b.Shape.BoundBox)
        f.data["size"] = (box.XLength * sc, box.ZLength * sc)
    ok.clicked.connect(accept)
    cancel.clicked.connect(d.close)
    w.accept = accept               # tests and Enter
    return w


def base_view():
    page, _ = ensure_page(App.ActiveDocument)
    bodies = drawing.page_bodies(page)
    sc = drawing.fit_scale(page, bodies, (3, 2))
    box = App.BoundBox()
    for b in bodies:
        box.add(b.Shape.BoundBox)
    start("place_base", scale=sc, size=(box.XLength * sc, box.ZLength * sc))


def projected_view():
    f = start("drag_out")
    if f.data.get("group") is None:
        f.finish()
        raise ValueError("Put a base view down first.")


def callouts():
    page, _ = ensure_page(App.ActiveDocument)
    with commands.transaction("Hole callouts", page.Document):
        made = []
        for v in drawing.views_of(page):
            if v.TypeId in ("TechDraw::DrawProjGroupItem", "TechDraw::DrawViewPart"):     # not sections or details
                made += drawing.hole_callouts(page, v)
                made += drawing.centerlines(v) or []
        page.Document.recompute()
    commands.report("%d callouts and centerlines added" % len(made), error=False)


def parts_list():
    page, _ = ensure_page(App.ActiveDocument)
    with commands.transaction("Parts list", page.Document):
        drawing.parts_list(page)
        page.Document.recompute()


def export(kind):
    page, _ = ensure_page(App.ActiveDocument)
    path, _ = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Export drawing", page.Document.Label + "." + kind,
                                                    "%s (*.%s)" % (kind.upper(), kind))
    if path:
        (drawing.export_pdf if kind == "pdf" else drawing.export_dxf)(page, path)
        commands.report("Exported %s" % path, error=False)


COMMANDS = [
    ("Kovac_NewDrawing", "New drawing", "A sheet with title block; put the base view down, drag out the others",
     new_drawing, "new_drawing"),
    ("Kovac_BaseView", "Base view", "Another base view on this sheet", base_view, "view_base"),
    ("Kovac_ProjectedView", "Projected view", "Drag from the base view to add projected and isometric views",
     projected_view, "view_proj"),
    ("Kovac_SectionView", "Section", "Cut a view: click it, place the cut line, place the section",
     lambda: start("section_pick"), "section_view"),
    ("Kovac_DetailView", "Detail", "Enlarge part of a view: centre, radius, place", lambda: start("detail_centre"),
     "detail_view"),
    ("Kovac_DrawDimension", "Dimension", "Click two corners, then where the dimension goes",
     lambda: start("dim_first", "dim_second", "place_dim"), "dimension"),
    ("Kovac_HoleCallouts", "Hole callouts", "Callouts for every hole and thread, centerlines for holes seen from the side",
     callouts, "callout"),
    ("Kovac_Balloon", "Balloon", "Item balloons: click the part, then where the balloon goes",
     lambda: start("balloon_pick", "place_balloon"), "balloon"),
    ("Kovac_PartsList", "Parts list", "Parts list above the title block", lambda: parts_list(), "parts_list"),
    ("Kovac_ExportPDF", "Export PDF", "Save the sheet as PDF", lambda: export("pdf"), "export_pdf"),
    ("Kovac_ExportDXF", "Export DXF", "Save the sheet as DXF", lambda: export("dxf"), "export_dxf"),
]


def register():
    for cid, label, tip, fn, icon in COMMANDS:
        commands.add(cid, label, tip, fn, icon=kovac.icon(icon))


# ---------------------------------------------------------------- associativity

class _Follower:
    """After the model regenerates, Kovač dimensions and callouts re-attach (drawing.refresh)."""
    busy = False

    def slotRecomputedDocument(self, doc):
        if self.busy or not any(o.TypeId == "TechDraw::DrawPage" for o in doc.Objects):
            return
        self.busy = True
        try:
            for page in [o for o in doc.Objects if o.TypeId == "TechDraw::DrawPage"]:
                for o in page.Views:
                    if o.TypeId != "TechDraw::DrawViewDimension":
                        continue
                    before = [s for _, s in o.References2D] if o.References2D else []
                    if hasattr(o, "KovacRefs"):
                        drawing.attach(o)
                    elif hasattr(o, "KovacHole"):
                        drawing._attach_callout(o)
                    after = [s for _, s in o.References2D] if o.References2D else []
                    if before != after:
                        o.touch()
            if any("Touched" in o.State for o in doc.Objects):
                doc.recompute()
        finally:
            self.busy = False


_follower = None


def install():
    global _follower
    if _follower is None:
        _follower = _Follower()
        App.addDocumentObserver(_follower)

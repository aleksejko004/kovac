# SPDX-License-Identifier: LGPL-2.1-or-later
"""While a sketch-based feature's panel is open, the sketch's closed regions are shaded in
the view; clicking one adds it to the profile or takes it out."""
from PySide import QtWidgets

from kovac import navigation, overlay, palette, regions


class RegionPicker:
    def __init__(self, ed):
        self.ed, self.node = ed, None
        self.label = QtWidgets.QLabel(objectName="kovacMuted")
        navigation.hooks.append(self)

    def regions(self):
        sk = getattr(self.ed.fp, "Profile", None)
        try:
            return regions.of_sketch(sk) if sk is not None else []
        except Exception:
            return []

    def chosen(self, rs):
        """Highlighted as already part of the profile: the stored keys; failing that, the
        single default region when there is only one to choose -- matching _sketch_regions,
        so the preview never silently includes more than the panel shows as chosen."""
        keys = list(self.ed.fp.Regions)
        if keys:
            return set(keys)
        auto = regions.default(rs)
        return {r.key for r in auto} if len(auto) == 1 else set()

    def refresh(self):
        overlay.remove(self.node)
        rs = self.regions()
        self.node = None
        if not rs:
            self.label.setText("—")
            return
        chosen = self.chosen(rs)
        from pivy import coin
        sep = coin.SoSeparator()
        for r in rs:
            on = r.key in chosen
            sep.addChild(overlay.face_node(r.face, palette.accent() if on else "#9AA3AE", 0.45 if on else 0.75))
        self.node = overlay.add(sep)
        self.label.setText("%d of %d · click regions in the view" % (len(chosen & {r.key for r in rs}), len(rs)))

    def press(self, it, pos):
        rs = self.regions()
        if not rs:
            return False
        origin, d = overlay.ray(it, pos)
        n = self.ed.fp.Profile.getGlobalPlacement().Rotation.multVec(overlay.V(0, 0, 1))
        p = overlay.hit_plane(origin, d, self.ed.fp.Profile.getGlobalPlacement().Base, n)
        hit = [r for r in rs if p is not None and r.face.isInside(p, 1e-6, True)]
        if not hit:
            return False
        r = min(hit, key=lambda x: x.face.Area)          # innermost region under the cursor
        chosen = self.chosen(rs)
        chosen ^= {r.key}
        keep = [x for x in rs if x.key in chosen]
        self.ed.fp.Regions = [x.key for x in keep]
        self.ed.fp.RegionPoints = [x.point for x in keep]
        self.ed.changed()
        return True

    def move(self, it, pos):
        pass

    def release(self, it, pos):
        pass

    def detach(self):
        overlay.remove(self.node)
        if self in navigation.hooks:
            navigation.hooks.remove(self)


def attach(ed):
    p = RegionPicker(ed)
    return p


class ProfileHover:
    """Outside sketches: the closed area of a visible sketch under the cursor is shaded like a
    hovered face, unless a body is in front of it; a click selects that area (Shift/Ctrl add),
    and Extrude then uses exactly the clicked areas."""

    def __init__(self):
        self.node = self.sel_node = None
        self.current = None              # (sketch, region) under the cursor
        self.picked = {}                 # sketch name -> {region key: sample point}
        self.cache = {}

    def regions(self, sk):
        try:                     # an empty sketch (only construction lines, or one the solver failed) has no shape
            length = round(sk.Shape.Length, 6) if not sk.Shape.isNull() else 0.0
        except Exception:
            length = None
        if length is None or length == 0.0:
            return []
        key = (sk.Name, len(sk.Geometry), length, str(sk.getGlobalPlacement()))
        if self.cache.get(sk.Name, (None,))[0] != key:
            try:
                rs = regions.of_sketch(sk)
            except Exception:
                rs = []
            self.cache[sk.Name] = (key, rs)
        return self.cache[sk.Name][1]

    def at(self, it, pos):
        import FreeCAD as App
        doc = App.ActiveDocument
        if doc is None:
            return None
        o, d = overlay.ray(it, pos)
        best = None
        for sk in doc.Objects:
            if not sk.TypeId.startswith("Sketcher::") or not sk.Visibility:
                continue
            pl = sk.getGlobalPlacement()
            p = overlay.hit_plane(o, d, pl.Base, pl.Rotation.multVec(overlay.V(0, 0, 1)))
            if p is None:
                continue
            hits = [r for r in self.regions(sk) if r.face.isInside(p, 1e-6, True)]
            t = (p - o).dot(d)
            if hits and (best is None or t < best[0]):
                best = (t, sk, min(hits, key=lambda r: r.face.Area))     # innermost area
        if best is None:
            return None
        info = it.view.getObjectInfo(it.coin(pos))
        if info and not info["Object"].startswith("Sketch"):
            front = (overlay.V(info["x"], info["y"], info["z"]) - o).dot(d)
            if front < best[0] - 1e-3 * max(1.0, abs(best[0])):
                return None                                               # a body hides it
        return best[1], best[2]

    def move(self, it, pos):
        self._prune()
        hit = self.at(it, pos)
        key = (hit[0].Name, hit[1].key) if hit else None
        if key == (self.current and (self.current[0].Name, self.current[1].key)):
            return
        overlay.remove(self.node)
        self.node, self.current = None, hit
        if hit:
            self.node = overlay.add(overlay.face_node(hit[1].face, palette.SEMANTIC["preselect"], 0.5, pickable=False))

    def click(self, mods, it=None, pos=None):
        """Select the area under the click; True when the click was ours."""
        import FreeCADGui as Gui
        if it is not None and pos is not None:
            self.current = self.at(it, pos)           # what is under the click now, not the last hover
        if not self.current:
            return False
        sk, r = self.current
        if not mods:
            Gui.Selection.clearSelection()
            self.picked = {}
        chosen = self.picked.setdefault(sk.Name, {})
        if r.key in chosen and "Ctrl" in mods:
            del chosen[r.key]
        else:
            chosen[r.key] = r.point
        if not Gui.Selection.isSelected(sk):
            Gui.Selection.addSelection(sk)
        self._show()
        return True

    def take(self, sk):
        """The clicked areas of sketch sk (for a feature being started), then forget them."""
        chosen = self.picked.pop(sk.Name, {}) if sk is not None else {}
        self._show()
        return chosen

    def _prune(self):
        import FreeCAD as App
        import FreeCADGui as Gui
        doc = App.ActiveDocument
        gone = [n for n in self.picked if doc is None or doc.getObject(n) is None or not Gui.Selection.isSelected(doc.getObject(n))]
        for n in gone:
            del self.picked[n]
        if gone:
            self._show()

    def _show(self):
        import FreeCAD as App
        overlay.remove(self.sel_node)
        self.sel_node = None
        faces = [r.face for name, keys in self.picked.items() if App.ActiveDocument.getObject(name)
                 for r in self.regions(App.ActiveDocument.getObject(name)) if r.key in keys]
        if faces:
            from pivy import coin
            sep = coin.SoSeparator()
            for f in faces:
                sep.addChild(overlay.face_node(f, palette.SEMANTIC["select"], 0.45, pickable=False))
            self.sel_node = overlay.add(sep)


hover = ProfileHover()

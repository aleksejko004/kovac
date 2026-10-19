# SPDX-License-Identifier: LGPL-2.1-or-later
"""Linked and independent copies (ADR-0005).

A history feature that makes copies of bodies (Move with Copy, Mirror without Join, Pattern of
bodies, Copy Component) makes them one of two ways, its ``CopyMode``:

- **Independent**: each copy is a body of its own from the moment it is made. The feature keeps
  a snapshot of the bodies it copied (``Frozen`` / ``FrozenState``, taken at the first commit),
  so later edits to an original no longer reach its copies, and edits to a copy stay on it.
- **Linked**: the copies show the original body (``LinkedCopy`` objects: the original's shape,
  placed, recomputed whenever it changes), so a change to any of them shows on all: a feature
  picked on a copy goes to the original (same face numbers). They are drawn in the linked
  colour. They are not bodies of the history: they can't be joined or cut with other bodies
  (make them independent first). FreeCAD's ``App::Link`` would share the drawing too, but it
  drops its own colour whenever the original is redrawn, so the copies wouldn't look linked.

Features made before copy modes existed keep their old behaviour: copies follow the
original's earlier steps.
"""
import FreeCAD as App

from kovac import components, model, topo

MODES = ["Independent", "Linked"]
V = App.Vector
MIRROR_X = App.Matrix(-1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)


def add_props(fp):
    """CopyMode and the snapshot, on a feature that can make copies (Independent at first)."""
    if not hasattr(fp, "CopyMode"):
        fp.addProperty("App::PropertyEnumeration", "CopyMode", "Copy",
                       "Independent: copies of their own; Linked: change one, all change")
        fp.CopyMode = MODES
        fp.addProperty("Part::PropertyPartShape", "Frozen", "Copy", "", 4)
        fp.addProperty("App::PropertyString", "FrozenState", "Copy", "", 4)


def makes_copies(fp):
    """True for a feature whose job (as set now) is making copies of bodies."""
    kind = type(getattr(fp, "Proxy", None)).__name__
    if kind == "Transform":
        return bool(getattr(fp, "Copy", False))
    if kind == "Mirror":
        return not getattr(fp, "Join", True)
    if kind == "Pattern":
        return bool(getattr(fp, "Bodies", []))
    return False


def mode(fp):
    """'Independent', 'Linked', or '' for a feature made before copy modes existed."""
    return getattr(fp, "CopyMode", "")


def linked(fp):
    return makes_copies(fp) and mode(fp) == "Linked"


def set_mode(fp, m):
    add_props(fp)
    if fp.CopyMode != m:
        fp.CopyMode = m
        if m != "Independent":
            fp.Frozen, fp.FrozenState = topo.pack({})


def source(fp, state, bid):
    """The body a copy is made from: the snapshot for an independent copy, else today's."""
    if mode(fp) == "Independent" and getattr(fp, "FrozenState", ""):
        frozen = topo.unpack(fp.Frozen, fp.FrozenState)
        if bid in frozen:
            return frozen[bid]
    if bid not in state:
        raise topo.Broken("a body to copy no longer exists")
    return state[bid]


def freeze(doc):
    """Take the snapshot of every independent copy feature that copies a body it has none of
    yet (just made, or a body added to it). Returns True if anything was taken."""
    changed = False
    for fp in model.items(doc):
        if not (model.is_feature(fp) and makes_copies(fp) and mode(fp) == "Independent" and model.active(fp)):
            continue
        frozen = topo.unpack(fp.Frozen, fp.FrozenState) if fp.FrozenState else {}
        want = list(fp.Bodies)
        if sorted(frozen) == sorted(want):
            continue
        now = model.input_state(fp)
        snap = {bid: frozen[bid] if bid in frozen else now[bid] for bid in want if bid in frozen or bid in now}
        fp.Frozen, fp.FrozenState = topo.pack(snap)
        changed = True
    return changed


# ---------------------------------------------------------------- linked copies

class LinkedCopy:
    """A linked copy: the original body's shape under a fixed matrix (a mirror too)."""

    def __init__(self, fp):
        fp.Proxy = self
        fp.addProperty("App::PropertyLinkGlobal", "Original", "Copy", "the body this copy shows", 1)
        fp.addProperty("App::PropertyMatrix", "CopyMatrix", "Copy", "where the copy sits, in the original's coordinates", 1)
        fp.addProperty("App::PropertyString", "KovacCopyOf", "Kovac", "feature that makes this copy", 4)
        fp.addProperty("App::PropertyString", "KovacCopyKey", "Kovac", "body id # copy number", 4)

    def execute(self, fp):
        import Part
        src = fp.Original
        if src is None or src.Shape.isNull():
            fp.Shape = Part.Shape()
            return
        s = topo.baked(src.Shape)
        s.transformShape(fp.CopyMatrix, True)          # rigid or a mirror: face order is kept
        fp.Shape = s

    def dumps(self):
        return None

    def loads(self, _state):
        return None


class LinkedCopyView(model.ViewProvider):
    def __init__(self, vobj):
        super().__init__(vobj, "instance")
        model.show(vobj)


def is_linked_copy(o):
    return o is not None and isinstance(getattr(o, "Proxy", None), LinkedCopy)


def links_of(fp):
    doc = fp.Document
    out = [o for o in doc.Objects if is_linked_copy(o) and o.KovacCopyOf == fp.Name]
    return sorted(out, key=lambda o: o.KovacCopyKey)


def original(link):
    """The body a linked copy shows (a KovacBody), or None."""
    return getattr(link, "Original", None)


def matrix_placement(link):
    """The copy's placement against its original, leaving out a mirror (for previews)."""
    m = App.Matrix(link.CopyMatrix)
    if m.determinant() < 0:
        m = m.multiply(MIRROR_X)
    return App.Placement(m)


def mirror_matrix(o, n):
    """Matrix of the mirror in the plane through o with normal n (I - 2nn^T, about o)."""
    n = V(n).normalize()
    a = [[(1.0 if r == c else 0.0) - 2 * n[r] * n[c] for c in range(3)] for r in range(3)]
    t = [o[r] - sum(a[r][c] * o[c] for c in range(3)) for r in range(3)]
    return App.Matrix(a[0][0], a[0][1], a[0][2], t[0], a[1][0], a[1][1], a[1][2], t[1],
                      a[2][0], a[2][1], a[2][2], t[2], 0, 0, 0, 1)


def wanted(fp):
    """{(body id, n): matrix} of the linked copies a feature wants, in the bodies' coordinates."""
    kind = type(fp.Proxy).__name__
    out = {}
    if kind == "Transform":
        from kovac import move
        for bid in fp.Bodies:
            out[(bid, 1)] = move.effective(fp).toMatrix()
    elif kind == "Mirror":
        from kovac import modify
        o, n = modify.plane_of(fp, "Plane", model.input_state(fp))
        for bid in fp.Bodies:
            out[(bid, 1)] = mirror_matrix(o, n)
    elif kind == "Pattern":
        pls = fp.Proxy.placements(fp, model.input_state(fp))
        for bid in fp.Bodies:
            for k, pl in enumerate(pls):
                if k > 0 and k not in fp.Skip:
                    out[(bid, k)] = pl.toMatrix()
    return out


def sync_links(doc):
    """Make the document's linked copies match its active linked features: create the missing
    ones, move the others, remove those no feature wants any more (feature deleted, rolled
    back, switched to independent, or its original gone). Returns True if anything changed."""
    want = {}
    for fp in model.items(doc):
        if model.is_feature(fp) and linked(fp) and model.active(fp) and not getattr(fp, "Suppressed", False) \
                and not fp.Status:
            for (bid, k), m in wanted(fp).items():
                body = model.body_object(doc, bid)
                if body is not None and not body.Shape.isNull():
                    want[(fp.Name, "%s#%d" % (bid, k))] = (fp, body, k, m)
    changed = False
    have = {(o.KovacCopyOf, o.KovacCopyKey): o for o in doc.Objects if is_linked_copy(o)}
    for key, o in have.items():
        if key not in want:
            doc.removeObject(o.Name)
            changed = True
    for key, (fp, body, k, m) in want.items():
        link = have.get(key)
        if link is None:
            link = doc.addObject("Part::FeaturePython", "LinkedCopy")
            LinkedCopy(link)
            if App.GuiUp and link.ViewObject is not None:
                LinkedCopyView(link.ViewObject)
            link.KovacCopyOf, link.KovacCopyKey = key
            link.Label = "%s (linked %d)" % (body.Label, k)
            components.adopt(link, components.holder(body))
            _fresh.append(link.Name)
            changed = True
        if link.Original != body:
            link.Original = body
            changed = True
        if not _same_matrix(link.CopyMatrix, m):
            link.CopyMatrix = m
            changed = True
    return changed


def _same_matrix(a, b):
    return all(abs(x - y) < 1e-12 for x, y in zip(a.A, b.A))


_fresh = []


def style_fresh(doc):
    """Colour the linked copies made since the last call (once they are drawn)."""
    for name in list(_fresh):
        o = doc.getObject(name)
        if o is not None:
            style(o)
    del _fresh[:]


def style(link):
    """Linked copies look linked: the model colour tinted toward the accent."""
    vo = getattr(link, "ViewObject", None)
    if vo is None:
        return
    import kovac
    from kovac import overlay, palette
    colour = palette.mix(palette.THEMES.get(kovac.theme_name(), palette.THEMES["dark"])["model"], palette.accent(), 0.45)
    vo.ShapeAppearance = [App.Material(DiffuseColor=overlay.rgb(colour))]


def make_independent(fp):
    """Turn a linked feature's copies into bodies of their own, as the originals look today
    (with what was added to them through the copies)."""
    doc = fp.Document
    today = model.state_of(model.tip(doc))
    set_mode(fp, "Independent")
    fp.Frozen, fp.FrozenState = topo.pack({bid: today[bid] for bid in fp.Bodies if bid in today})


def remove(link):
    """Delete one linked copy: a pattern leaves that instance out (its Skip); a moved or
    mirrored copy goes with the feature that makes it."""
    doc = link.Document
    fp = doc.getObject(link.KovacCopyOf)
    if fp is None:
        doc.removeObject(link.Name)
        return
    k = int(link.KovacCopyKey.rsplit("#", 1)[1])
    if type(fp.Proxy).__name__ == "Pattern":
        fp.Skip = sorted(set(list(fp.Skip) + [k]))
    else:
        model.remove(doc, fp)
    model.commit(doc)

# SPDX-License-Identifier: LGPL-2.1-or-later
"""Kovač history model (ADR-0002).

One linear history per document (the KovacHistory object). Every *state feature* turns the
body state of the feature before it (``Previous``) into a new state: an ordered set of
tagged bodies (topo.Body), stored as a compound plus a JSON tag table. Bodies are what the
user sees and picks: KovacBody objects that show one body of the history tip's state.

A feature that fails or loses a reference passes its input state through unchanged and
records a plain-language Status. It turns red in the timeline and later features still
compute, so nothing downstream ever runs on silently wrong geometry.
"""
import FreeCAD as App
import Part

from kovac import topo

V = App.Vector
OPS = ["Auto", "Join", "Cut", "Intersect", "New body"]


# ---------------------------------------------------------------- proxies

class Feature:
    """Base proxy for Part::FeaturePython history features."""
    kind = "Feature"
    icon = ""
    state_feature = True
    damaged = False         # set by execute when healing failed

    def __init__(self, fp):
        fp.Proxy = self
        fp.addProperty("App::PropertyLinkGlobal", "Previous", "Kovac", "feature before this one in the history", 4)
        fp.addProperty("App::PropertyBool", "Suppressed", "Kovac", "skip this feature")
        # attribute bits: 1 read-only, 4 hidden, 8 output (setting it in execute doesn't re-touch)
        fp.addProperty("App::PropertyString", "Status", "Kovac", "empty when healthy", 9)
        fp.addProperty("App::PropertyString", "BodyState", "Kovac", "tag table of the output state", 12)
        fp.addProperty("App::PropertyString", "Kind", "Kovac", "", 1).Kind = self.kind
        fp.addProperty("App::PropertyString", "Home", "Kovac", "component active when it was made", 4)
        self.setup(fp)

    def setup(self, fp):
        pass

    def apply(self, fp, state):
        return state

    def execute(self, fp):
        state = input_state(fp)
        status = ""
        del _damaged[:]
        if not fp.Suppressed and active(fp):
            try:
                state = self.apply(fp, dict(state))
            except topo.Broken as e:
                status = "Missing reference: %s — %s. Edit the feature and pick it again." % (
                    topo.describe(e.ref, fp.Document) if e.ref else "a picked item", e)
            except Exception as e:  # kernel failures in plain words
                status = friendly(e)
        self.damaged = bool(_damaged)          # the timeline shows a warning (not persisted)
        if self.state_feature:
            fp.Shape, fp.BodyState = topo.pack(state)
        if fp.Status != status:
            fp.Status = status

    def dumps(self):
        return None

    def loads(self, _state):
        return None


class BodyProxy:
    """What the user sees: one body of the history tip's state."""

    def __init__(self, fp):
        fp.Proxy = self
        fp.addProperty("App::PropertyString", "BodyId", "Kovac", "", 1)
        fp.addProperty("App::PropertyLinkGlobal", "Tip", "Kovac", "", 4)
        fp.addProperty("App::PropertyString", "Material", "Kovac", "material key (kovac.materials)")

    def execute(self, fp):
        st = state_of(fp.Tip)
        fp.Shape = topo.baked(st[fp.BodyId].shape) if fp.BodyId in st else Part.Shape()

    def dumps(self):
        return None

    def loads(self, _state):
        return None


class HistoryProxy:
    def __init__(self, fp):
        fp.Proxy = self
        fp.addProperty("App::PropertyLinkListGlobal", "Features", "Kovac", "ordered history", 4)
        fp.addProperty("App::PropertyInteger", "Rollback", "Kovac", "active features (-1 = all)").Rollback = -1

    def execute(self, fp):
        pass

    def dumps(self):
        return None

    def loads(self, _state):
        return None


class ViewProvider:
    """Icon for history items; hidden machinery stays out of FreeCAD's own tree look."""

    def __init__(self, vobj, icon=""):
        vobj.Proxy = self
        self.icon = icon

    def getIcon(self):
        import kovac
        return kovac.icon(self.icon or "feature") or ""

    def attach(self, vobj):
        self.Object = vobj.Object

    def dumps(self):
        return {"icon": self.icon}

    def loads(self, state):
        self.icon = (state or {}).get("icon", "")


class BodyView(ViewProvider):
    """Bodies need an explicit display mode: a Python feature without a view proxy gets none,
    and is then neither drawn nor pickable."""

    def __init__(self, vobj):
        super().__init__(vobj, "feature")
        show(vobj)


def show(vobj, mode="Flat Lines", transparency=None):
    try:
        vobj.DisplayMode = mode
        if transparency is not None:
            vobj.Transparency = transparency
    except Exception:
        pass


def friendly(e):
    text = str(e) or type(e).__name__
    kernel = ("BRep_API", "Standard_", "command not done", "StdFail", "TopoDS", "BRepAlgo", "Geom_")
    if any(k in text for k in kernel):
        return "The geometry could not be built with these values. Try a smaller value or different picks."
    return text[0].upper() + text[1:] if text else "Failed."


# ---------------------------------------------------------------- state access

def state_of(fp):
    if fp is None or not getattr(fp, "BodyState", ""):
        return {}
    return topo.unpack(fp.Shape, fp.BodyState)


def input_state(fp):
    return state_of(fp.Previous)


def history(doc, create=True):
    for o in doc.Objects:
        if getattr(o, "Proxy", None).__class__.__name__ == "HistoryProxy":
            return o
    if not create:
        return None
    h = doc.addObject("App::FeaturePython", "History")
    HistoryProxy(h)
    return h


def items(doc):
    h = history(doc, create=False)
    return list(h.Features) if h else []


def is_feature(o):
    return isinstance(getattr(o, "Proxy", None), Feature)


def rollback_index(doc):
    h = history(doc, create=False)
    n = len(items(doc))
    return n if h is None or h.Rollback < 0 or h.Rollback > n else h.Rollback


def active(fp):
    its = items(fp.Document)
    return fp not in its or its.index(fp) < rollback_index(fp.Document)


def tip(doc):
    """Last active state feature (the state the bodies show)."""
    its = items(doc)[:rollback_index(doc)]
    for o in reversed(its):
        if is_feature(o) and o.Proxy.state_feature:
            return o
    return None


def bodies(doc):
    return [o for o in doc.Objects if isinstance(getattr(o, "Proxy", None), BodyProxy)]


def body_object(doc, body_id):
    return next((b for b in bodies(doc) if b.BodyId == body_id), None)


# ---------------------------------------------------------------- editing the history

def relink(doc):
    """Previous links follow history order; bodies follow the tip. Only touches what changed."""
    last = None
    for o in items(doc):
        if is_feature(o):
            if o.Previous != last:
                o.Previous = last
            if o.Proxy.state_feature:
                last = o
    t = tip(doc)
    for b in bodies(doc):
        if b.Tip != t:
            b.Tip = t


def create(doc, proxy, name=None, index=None, **props):
    """Add a feature at the rollback marker (or index) and set its properties."""
    fp = doc.addObject("Part::FeaturePython", name or proxy.kind)
    proxy(fp)
    from kovac import components
    act = components.active(doc)
    if act is not None:
        fp.Home = act.Name
    if App.GuiUp and fp.ViewObject is not None:
        ViewProvider(fp.ViewObject, proxy.icon)
        if proxy.state_feature:
            fp.ViewObject.Visibility = False      # features show through their bodies
        else:
            show(fp.ViewObject, transparency=70)   # reference geometry is drawn, see-through
    for k, v in props.items():
        setattr(fp, k, v)
    if not proxy.state_feature and components.root(doc) is not None:
        components.adopt(fp, components.ref_home(doc, list(props.values())))   # reference geometry
    insert(doc, fp, index)
    return fp


def insert(doc, obj, index=None):
    h = history(doc)
    its = list(h.Features)
    at = rollback_index(doc) if index is None else index
    its.insert(at, obj)
    if h.Rollback >= 0 and at <= h.Rollback:
        h.Rollback = h.Rollback + 1      # the new item is active: it sits at the marker
    h.Features = its
    relink(doc)


def dependencies(obj):
    """History items this one uses (beyond its Previous link)."""
    its = items(obj.Document)
    return [o for o in obj.OutList if o in its and o is not getattr(obj, "Previous", None)]


def dependents(obj):
    its = items(obj.Document)
    return [o for o in obj.InList if o in its and getattr(o, "Previous", None) is not obj]


def move(doc, obj, new_index):
    """Reorder; refuses moves that would put an item before something it uses."""
    its = items(doc)
    its.remove(obj)
    new_index = max(0, min(new_index, len(its)))
    its.insert(new_index, obj)
    pos = {o: i for i, o in enumerate(its)}
    for d in dependencies(obj):
        if pos[d] > new_index:
            raise ValueError("%s uses %s, so it cannot come before it." % (obj.Label, d.Label))
    for d in dependents(obj):
        if pos[d] < new_index:
            raise ValueError("%s is used by %s, so it cannot come after it." % (obj.Label, d.Label))
    history(doc).Features = its
    relink(doc)


def remove(doc, obj):
    """Delete a history item; refuses while later items still use it."""
    users = dependents(obj)
    if users:
        raise ValueError("%s is used by %s. Delete or edit those first." % (obj.Label, ", ".join(u.Label for u in users)))
    h = history(doc)
    its = list(h.Features)
    i = its.index(obj)
    its.remove(obj)
    if h.Rollback >= 0 and i < h.Rollback:
        h.Rollback = h.Rollback - 1
    h.Features = its
    relink(doc)
    doc.removeObject(obj.Name)
    sync_bodies(doc, prune=True)


def set_rollback(doc, k):
    """Show the model as it was after the first k history items (k = len -> everything)."""
    h = history(doc)
    n = len(h.Features)
    h.Rollback = -1 if k >= n else max(0, k)
    for o in h.Features:
        if is_feature(o):
            o.touch()
    relink(doc)


def sync_bodies(doc, prune=False):
    """One KovacBody per body id that exists in any active feature output; Labels 'Body N'.
    prune: also delete bodies no feature produces any more (after deleting a feature)."""
    seen = []
    for o in items(doc)[:rollback_index(doc)]:
        if is_feature(o) and o.Proxy.state_feature and o.BodyState:
            import json
            for i in json.loads(o.BodyState)["order"]:
                if i not in seen:
                    seen.append(i)
    have = {b.BodyId: b for b in bodies(doc)}
    t = tip(doc)
    for i in seen:
        if i not in have:
            b = doc.addObject("Part::FeaturePython", "Body")
            BodyProxy(b)
            if App.GuiUp and b.ViewObject is not None:
                BodyView(b.ViewObject)
            b.BodyId, b.Tip = i, t
            b.Label = "Body %d" % (len(have) + 1)
            have[i] = b
            from kovac import components
            maker = doc.getObject(i.split(".")[0])
            comp = components.home(maker) if maker is not None else None
            if comp is not None:          # a new body joins the component its feature works in
                comp.addObject(b)
    if prune:
        for i, b in list(have.items()):
            if i not in seen and all(i not in (o.BodyState or "") for o in items(doc) if is_feature(o)):
                doc.removeObject(b.Name)
                del have[i]
    return [have[i] for i in seen]


def commit(doc):
    """Recompute, create any bodies the history produced, recompute those (cheap if none);
    then joints follow today's geometry (ADR-0004). Returns what the joints reported."""
    from kovac import copies, joints
    doc.recompute()
    if copies.freeze(doc):                # independent copies: their snapshot (ADR-0005)
        doc.recompute()
    sync_bodies(doc)
    relink(doc)
    doc.recompute()
    if copies.sync_links(doc):            # linked copies: links that show the original
        doc.recompute()
        copies.style_fresh(doc)
    return joints.update(doc)


# ---------------------------------------------------------------- operations (Join/Cut/...)

def _touching(state, tool, scope=None):
    out = []
    for bid, b in state.items():
        if scope is not None and bid not in scope:
            continue
        if b.shape.BoundBox.intersect(tool.shape.BoundBox) and b.shape.distToShape(tool.shape)[0] < 1e-7:
            out.append(bid)
    return out


def infer(state, tool, hint=None, scope=None):
    """Operation from context (brief §3.6): touching nothing -> New body; a profile on a body
    face pulled outward -> Join, pushed inward -> Cut (so dragging back through zero flips
    Join <-> Cut); without such a face, mostly inside material -> Cut, else Join."""
    touching = _touching(state, tool, scope)
    if not touching:
        return "New body", []
    if hint in ("Join", "Cut"):
        return hint, touching
    inside = sum(state[b].shape.common(tool.shape).Volume for b in touching) / max(tool.shape.Volume, 1e-12)
    return ("Cut" if inside > 0.5 else "Join"), touching


def _clean(shape, sources=()):
    try:
        shape = shape.removeSplitter()
    except Exception:
        pass
    if not _valid(shape, sources):
        shape.fix(1e-7, 1e-7, 1e-7)
        if not _valid(shape, sources):
            _damaged.append(shape)
    if shape.isNull() or not shape.Solids:
        raise ValueError("The operation left no solid material.")
    return shape


_damaged = []          # shapes the running feature could not heal


def _valid(shape, sources=()):
    """The kernel's full check, or, given the operation's input bodies, a check of only the
    faces the operation made (faces it kept unchanged were checked before) plus closed shells.
    ponytail: misses a shell orientation flip along old/new seams; check the tip fully if that bites."""
    if not sources:
        return shape.isValid()
    old = {f.hashCode(): f for b in sources for f in b.shape.Faces}
    made = [f for f in shape.Faces if not (f.hashCode() in old and f.isSame(old[f.hashCode()]))]
    return all(sh.isClosed() for sh in shape.Shells) and (not made or Part.Compound(made).isValid())


def apply_tool(fp, state, tool, hint=None):
    """Combine a tagged tool body with the state using fp.Operation / fp.Targets.
    Sets fp.ResolvedOperation for the panel ("Join (auto)")."""
    op = fp.Operation
    targets = list(fp.Targets)
    scope = in_scope(fp, state)
    if op == "Auto":
        op, auto_targets = infer(state, tool, hint, scope)
        targets = targets or auto_targets
        resolved = "%s (auto)" % op
    else:
        targets = targets or _touching(state, tool, scope)
        resolved = op
    if fp.ResolvedOperation != resolved:
        fp.ResolvedOperation = resolved
    targets = [t for t in targets if t in state]
    if op == "New body" or (op == "Join" and not targets):
        state[new_body_id(fp)] = tool
        return state
    if not targets:
        raise ValueError("Nothing to %s: the shape doesn't touch any body." % op.lower())
    if op == "Join":
        first, rest = targets[0], targets[1:]
        shape = state[first].shape.fuse([tool.shape] + [state[r].shape for r in rest]) if rest else \
            state[first].shape.fuse(tool.shape)
        sources = [state[first], tool] + [state[r] for r in rest]
        shape = _clean(shape, sources)
        state[first] = topo.Body(shape, topo.inherit(shape, sources))
        for r in rest:
            del state[r]
        return state
    for t in targets:
        src = state[t]
        shape = src.shape.cut(tool.shape) if op == "Cut" else src.shape.common(tool.shape)
        if op == "Cut" and (shape.isNull() or not shape.Solids):
            del state[t]          # cut away completely
            continue
        shape = _clean(shape, [src, tool])
        state[t] = topo.Body(shape, topo.inherit(shape, [src, tool]))
    return state


def in_scope(fp, state):
    """Body ids a feature's tool may combine with: those in the component it works in (shapes
    of other components are in other coordinates, ADR-0004). None = no components, all."""
    from kovac import components
    if components.root(fp.Document) is None:
        return None
    home = components.home(fp)
    holders = {b.BodyId: components.holder(b) for b in bodies(fp.Document)}
    return {i for i in state if holders.get(i, home) == home}


def new_body_id(fp, k=None):
    return fp.Name if k is None else "%s.%d" % (fp.Name, k)


def add_operation_properties(fp, default="Auto"):
    fp.addProperty("App::PropertyEnumeration", "Operation", "Result", "Join, Cut, Intersect or New body")
    fp.Operation = OPS
    fp.Operation = default
    fp.addProperty("App::PropertyStringList", "Targets", "Result", "affected body ids (empty = all touched)")
    fp.addProperty("App::PropertyString", "ResolvedOperation", "Result", "", 9)


def refs(fp, prop):
    return [topo.loads(r) for r in getattr(fp, prop)]


def pick_ref(obj, sub):
    """Reference (JSON) for a viewport pick on a Kovač body, or None for anything else. The pick
    may go through components and instances ('Assembly', 'Pin.Body.Face3')."""
    from kovac import components
    if not sub:
        return None
    obj, element = components.resolve(obj, sub)
    if not isinstance(getattr(obj, "Proxy", None), BodyProxy):
        return None
    if not element[:4] in ("Face", "Edge") and not element.startswith("Vertex"):
        return None
    return topo.dumps(topo.make_ref(state_of(obj.Tip), obj.BodyId, element))


def owner_of(obj, sub):
    """History feature that made a picked element (the first tag around it)."""
    ref = pick_ref(obj, sub)
    if ref is None:
        return None
    tags = topo.loads(ref)["t"]
    return obj.Document.getObject(tags[0].split(":")[0].split("@")[0]) if tags else None


class Import(Feature):
    """Imported solids as bodies of the history (faces named by index; the shape is fixed)."""
    kind, icon = "Import", "import_step"

    def setup(self, fp):
        fp.addProperty("Part::PropertyPartShape", "Imported", "Import", "", 4)
        fp.addProperty("App::PropertyString", "SourceFile", "Import", "", 1)

    def apply(self, fp, state):
        for k, solid in enumerate(fp.Imported.Solids or [fp.Imported]):
            state[new_body_id(fp, k)] = topo.Body(solid, ["%s:f%d" % (fp.Name, i) for i in range(len(solid.Faces))])
        return state

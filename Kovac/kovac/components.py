# SPDX-License-Identifier: LGPL-2.1-or-later
"""Components (ADR-0004): named containers with their own position, holding bodies, sketches and
reference geometry. Headless logic; commands are in assemble.py.

- All components of a design sit in one ``Assembly::AssemblyObject`` (machinery, made with the
  first component) so FreeCAD's joints and solver can work on them.
- A component is an ``App::Part``. An *instance* is an ``App::Link`` to one: same definition,
  own position.
- History stays one list for the whole design (ADR-0002). A body's shape is in the coordinates
  of the component holding it; the component's placement only moves what is shown. So a feature
  computes with its sketch's placement *inside its component* (``local_placement``), never the
  global one, and a new body goes into the component its sketch is in.
- Kovač's link properties are global-scope: a component (a GeoFeatureGroup) would otherwise pull
  in everything its members link to, the whole history included.
"""
import FreeCAD as App

ROOT = "KovacRoot"
_GLOBAL = {"App::PropertyLink": "App::PropertyLinkGlobal",
           "App::PropertyLinkList": "App::PropertyLinkListGlobal",
           "App::PropertyLinkSub": "App::PropertyLinkSubGlobal",
           "App::PropertyLinkSubList": "App::PropertyLinkSubListGlobal"}
_BITS = {"ReadOnly": 1, "Transient": 2, "Hidden": 4, "Output": 8, "NoRecompute": 16}


# ---------------------------------------------------------------- the design's assembly

def root(doc, create=False):
    """The design's assembly (machinery holding components and joints), or None."""
    for o in doc.Objects:
        if o.TypeId == "Assembly::AssemblyObject" and getattr(o, ROOT, False):
            return o
    if not create:
        return None
    migrate(doc)
    asm = doc.addObject("Assembly::AssemblyObject", "Assembly")
    asm.addProperty("App::PropertyBool", ROOT, "Kovac", "the design's own assembly", 4)
    setattr(asm, ROOT, True)
    asm.newObject("Assembly::JointGroup", "Joints")
    return asm


def is_root(o):
    return o is not None and getattr(o, ROOT, False) is True


def joint_group(doc):
    asm = root(doc)
    return next((o for o in asm.Group if o.TypeId == "Assembly::JointGroup"), None) if asm else None


def is_component(o):
    """An App::Part, or an instance (App::Link to one)."""
    return o is not None and (o.TypeId == "App::Part" or is_instance(o))


def is_instance(o):
    return o is not None and o.TypeId == "App::Link" and getattr(o.getLinkedObject(), "TypeId", "") == "App::Part"


def definition(o):
    return o.getLinkedObject() if is_instance(o) else o


def all_components(doc):
    """Every component and instance in the design, outermost first."""
    asm = root(doc)
    out = []

    def walk(group):
        for o in group:
            if is_component(o):
                out.append(o)
                if o.TypeId == "App::Part":
                    walk(o.Group)
    if asm is not None:
        walk(asm.Group)
    return out


def instances(comp):
    """The component itself and every link to it."""
    return [comp] + [o for o in comp.InList if o.TypeId == "App::Link" and o.getLinkedObject() == comp]


_active = {}          # headless: document name -> active component name


def active(doc):
    """The active component (new sketches and features go there), or None for the top."""
    try:
        import FreeCADGui as Gui
        gd = Gui.getDocument(doc.Name) if App.GuiUp else None
        view = gd.ActiveView if gd is not None else None
        if view is not None and hasattr(view, "getActiveObject"):
            o = view.getActiveObject("part")
            return o if o is not None and o.Document == doc and not is_root(o) else None
    except Exception:
        pass
    name = _active.get(doc.Name)
    return doc.getObject(name) if name else None


def set_active(doc, comp):
    _active[doc.Name] = comp.Name if comp is not None else None
    if App.GuiUp:
        import FreeCADGui as Gui
        gd = Gui.getDocument(doc.Name)
        if gd is not None and gd.ActiveView is not None and hasattr(gd.ActiveView, "setActiveObject"):
            gd.ActiveView.setActiveObject("part", comp)


# ---------------------------------------------------------------- frames

def holder(obj):
    """The component (App::Part) holding obj, or None at the top of the design."""
    try:
        p = obj.getParentGeoFeatureGroup()
    except Exception:
        return None
    return None if p is None or is_root(p) else p


def frame(obj):
    """Global placement of the coordinates obj's own geometry is in (its component's)."""
    try:
        p = obj.getParentGeoFeatureGroup()
    except Exception:
        p = None
    return p.getGlobalPlacement() if p is not None else App.Placement()


def local_placement(obj):
    """obj's placement inside its component: what features compute with (ADR-0004)."""
    return frame(obj).inverse().multiply(obj.getGlobalPlacement())


def to_local(obj, p):
    """A global point (a pick) into the coordinates obj's geometry is in."""
    return frame(obj).inverse().multVec(p)


def path_frame(top, sub):
    """Global placement of the coordinates a selection's element is in. The component
    *instance* the click went through counts: a link has its own position."""
    leaf, element = resolve(top, sub)
    path = (sub or "")[:len(sub or "") - len(element)]
    if not path:
        return frame(leaf)
    return top.getSubObject(path, 3).multiply(leaf.Placement.inverse())


def resolve(obj, sub):
    """(leaf object, element name) for a selection (obj, subname), through components and
    instances: ('Assembly', 'Plate.Body.Face3') -> (Body, 'Face3')."""
    sub = sub or ""
    element = sub.split(".")[-1]
    path = sub[:len(sub) - len(element)]
    if not path:
        return obj, element
    leaf = obj.getSubObject(path, 1)
    return (leaf if leaf is not None else obj), element


def home(fp):
    """The component a feature's new bodies go into: its sketch's, else the one active when it
    was made (stored in ``Home``)."""
    for prop in ("Profile", "Points", "Path"):
        sk = getattr(fp, prop, None)
        if sk is not None and hasattr(sk, "getParentGeoFeatureGroup"):
            return holder(sk)
    secs = getattr(fp, "Sections", None)
    if secs:
        return holder(secs[0])
    name = getattr(fp, "Home", "")
    return fp.Document.getObject(name) if name else None


def same_frame(a, b):
    """True if bodies a and b (KovacBody objects) are in the same component."""
    return holder(a) == holder(b)


# ---------------------------------------------------------------- global-scope links

def globalise(obj):
    """Turn obj's dynamic link properties into global-scope ones (value, group, docs, status kept)."""
    for p in list(obj.PropertiesList):
        t = obj.getTypeIdOfProperty(p)
        if t not in _GLOBAL:
            continue
        status = obj.getPropertyStatus(p)
        value = getattr(obj, p)
        group, doc = obj.getGroupOfProperty(p), obj.getDocumentationOfProperty(p)
        bits = sum(v for k, v in _BITS.items() if k in status)
        try:
            obj.removeProperty(p)
        except Exception:
            continue
        obj.addProperty(_GLOBAL[t], p, group, doc, bits)
        setattr(obj, p, value)


def migrate(doc):
    """Older designs: Kovač objects' links become global-scope (needed once components exist)."""
    from kovac import model
    for o in doc.Objects:
        if model.is_feature(o) or type(getattr(o, "Proxy", None)).__name__ in ("BodyProxy", "HistoryProxy"):
            globalise(o)


# ---------------------------------------------------------------- making components

def _owners(body):
    """Names of the history features whose faces a body carries."""
    from kovac import model
    st = model.state_of(body.Tip)
    b = st.get(body.BodyId)
    return {t.split(":")[0].split("@")[0] for t in (b.tags if b else [])}


def _sketches_of(doc, moving, staying):
    """Sketches only the moving bodies were built from (they go along); a sketch also used for
    a body that stays, stays."""
    from kovac import model
    mine = set().union(*[_owners(b) for b in moving]) if moving else set()
    theirs = set().union(*[_owners(b) for b in staying]) if staying else set()
    out = []
    for o in doc.Objects:
        if not o.TypeId.startswith("Sketcher::") and type(getattr(o, "Proxy", None)).__name__ != "Curve3DProxy":
            continue
        users = {u.Name for u in o.InList if model.is_feature(u)}
        if users and users <= mine and not users & theirs:
            out.append(o)
    return out


def new_component(doc, bodies=(), label=None):
    """A new component in the design, holding the given bodies (KovacBody objects) and the
    sketches only they were made from. Bodies keep their place: the component starts where
    their coordinates are."""
    from kovac import model
    asm = root(doc, create=True)
    homes = {holder(b) for b in bodies}
    if len(homes) > 1:
        raise ValueError("These bodies are in different components. Pick bodies from one component.")
    old = homes.pop() if homes else None
    comp = asm.newObject("App::Part", "Component")      # top level (nesting comes later)
    comp.Label = label or "Component %d" % len([c for c in all_components(doc) if c.TypeId == "App::Part"])
    if old is not None:
        comp.Placement = old.getGlobalPlacement()       # same coordinates as the bodies had
    staying = [b for b in model.bodies(doc) if b not in bodies]
    for o in list(bodies) + _sketches_of(doc, list(bodies), staying):
        comp.addObject(o)
    return comp


def new_instance(comp, offset=None):
    """Another instance of a component (a link: edit one, all change), placed beside it."""
    doc = comp.Document
    target = definition(comp)
    link = root(doc, create=True).newObject("App::Link", "Instance")
    link.LinkedObject = target
    if offset is None:
        bb = _bound(target)
        offset = App.Vector((bb.XLength if bb else 10) + 10, 0, 0)
    link.Placement = App.Placement(comp.Placement.Base + offset, comp.Placement.Rotation)
    n = len(instances(target))
    link.Label = "%s (%d)" % (target.Label, n)
    return link


def _bound(comp):
    import Part
    try:
        s = Part.getShape(comp)
        return s.BoundBox if not s.isNull() else None
    except Exception:
        return None

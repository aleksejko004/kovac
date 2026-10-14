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


def selected():
    """[(leaf object, element, top object, subname)] for the current selection, through
    components and instances (a whole object selected gives element '')."""
    import FreeCADGui as Gui
    out = []
    for s in Gui.Selection.getSelectionEx("", 0):
        for sub in s.SubElementNames or [""]:
            leaf, el = resolve(s.Object, sub)
            out.append((leaf, el, s.Object, sub))
    return out


def ref_home(doc, values):
    """The component a new object built on these values belongs in: that of the first body a
    reference among them points at, of the first object named among them, else the active one."""
    import json
    from kovac import model
    for v in values:
        for x in (v if isinstance(v, (list, tuple)) else [v]):
            if isinstance(x, str) and x.startswith("{"):
                try:
                    b = model.body_object(doc, json.loads(x).get("b"))
                except (ValueError, AttributeError):
                    b = None
                if b is not None:
                    return holder(b)
            elif isinstance(x, str) and x and doc.getObject(x) is not None and hasattr(doc.getObject(x), "getParentGeoFeatureGroup"):
                return holder(doc.getObject(x))
    return active(doc)


def feature_frame(fp):
    """Global placement of the coordinates a feature works in (its bodies' component): for
    drawing its arrows and previews where the model is shown."""
    if root(fp.Document) is None:
        return App.Placement()
    vals = [getattr(fp, p) for p in ("Face", "Edges", "Faces", "Base", "Refs", "ProfileFaces") if hasattr(fp, p)]
    comp = None
    ids = list(getattr(fp, "Bodies", []) or []) + [getattr(fp, p) for p in ("Target", "Body") if getattr(fp, p, "")]
    if ids:
        from kovac import model
        b = model.body_object(fp.Document, ids[0])
        comp = holder(b) if b is not None else None
    elif any(vals):
        comp = ref_home(fp.Document, vals)
    else:
        comp = home(fp)
    return comp.getGlobalPlacement() if comp is not None else App.Placement()


def adopt(obj, comp):
    """Put obj into comp (None: leave it at the top)."""
    if comp is not None and holder(obj) != comp:
        comp.addObject(obj)


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


def _body_objects(comp):
    from kovac import model
    return [o for o in comp.Group if isinstance(getattr(o, "Proxy", None), model.BodyProxy)]


def _jointed(doc, bodies):
    from kovac import joints
    used = set()
    for j in joints.all_joints(doc):
        try:
            used.update(o.body for o in joints.origins(j))
        except Exception:
            pass
    return [b for b in bodies if b in used]


def move_bodies(doc, bodies, target):
    """Move bodies (KovacBody objects) into component `target`, or to the top of the design
    (None), keeping them where they are shown. A body's shape is in its component's
    coordinates, so between components that sit differently a history step (a Move by the
    fixed difference) carries the change (ADR-0004: membership is history state). The
    sketches they were made from stay where they are. Returns the steps added."""
    from kovac import model, modify
    bodies = [b for b in bodies if holder(b) != target]
    if not bodies:
        return []
    if target is not None and not (is_component(target) and target.TypeId == "App::Part"):
        raise ValueError("Bodies go into a component itself, not into one of its instances.")
    jointed = _jointed(doc, bodies)
    if jointed:
        raise ValueError("%s has joints. Delete them first, or move the whole component."
                         % ", ".join(b.Label for b in jointed))
    to = target.getGlobalPlacement() if target is not None else App.Placement()
    groups = {}
    for b in bodies:
        groups.setdefault(holder(b), []).append(b)
    made = []
    for old, bs in groups.items():
        src = old.getGlobalPlacement() if old is not None else App.Placement()
        step = to.inverse().multiply(src)
        if not step.isSame(App.Placement(), 1e-9):
            fp = model.create(doc, modify.Transform, "Rehome", Bodies=[b.BodyId for b in bs], Move=step)
            fp.Label = "Into %s" % (target.Label if target is not None else "the design")
            made.append(fp)
        for b in bs:
            if target is not None:
                target.addObject(b)
            elif old is not None:
                old.removeObject(b)
    return made


def copy_component(comp, offset=None):
    """An independent copy of a component, placed beside it: new bodies (a history step that
    copies them), so features added to the copy change only the copy. The copy still follows
    edits made to the original's history before the copy step, as any copied body does."""
    from kovac import model, modify
    doc = comp.Document
    src = definition(comp)
    bodies = _body_objects(src)
    if not bodies:
        raise ValueError("%s has no bodies to copy." % src.Label)
    new = root(doc, create=True).newObject("App::Part", "Component")
    new.Label = "%s copy" % src.Label
    if offset is None:
        bb = _bound(src)
        offset = App.Vector((bb.XLength if bb else 10) + 10, 0, 0)
    new.Placement = App.Placement(comp.Placement.Base + offset, comp.Placement.Rotation)
    fp = model.create(doc, modify.Transform, "Copy", Bodies=[b.BodyId for b in bodies], Copy=True)
    fp.Home = new.Name                   # the copied bodies are made into the new component
    fp.Label = "Copy %s" % src.Label
    return new


def _bound(comp):
    import Part
    try:
        s = Part.getShape(comp)
        return s.BoundBox if not s.isNull() else None
    except Exception:
        return None


def remove(comp):
    """Delete a component or an instance. An instance goes with its joints. A component's
    contents go back to the top of the design (bodies are history results, they stay), its
    instances and every joint touching it go. Returns a note for the status bar, or ''."""
    from kovac import joints
    doc = comp.Document
    gone = [comp] + ([] if is_instance(comp) else [i for i in instances(comp) if i is not comp])
    for j in joints.all_joints(doc):
        try:
            o1, o2 = joints.origins(j)
        except Exception:
            o1 = o2 = None
        if o1 is None or o1.comp in gone or o2.comp in gone:
            doc.removeObject(j.Name)
    for g in joints.grounds(doc):
        if g.ObjectToGround in gone:
            doc.removeObject(g.Name)
    note = ""
    if not is_instance(comp):
        moved = not comp.getGlobalPlacement().isSame(App.Placement(), 1e-9)
        move_bodies(doc, _body_objects(comp), None)        # bodies stay where they are shown
        rest = [k for k in comp.Group if k.TypeId != "App::Origin" and k not in _body_objects(comp)]
        if moved and rest:
            note = "%s had been moved: its bodies stay where they are; its sketches go back to where they were drawn." \
                % comp.Label
        comp.Group = [k for k in comp.Group if k.TypeId == "App::Origin"]    # the rest go to the top
    for o in gone:
        if doc.getObject(o.Name) is not None:
            if o.TypeId == "App::Part":
                origin = getattr(o, "Origin", None)
                origin = origin.Name if origin is not None else None
                doc.removeObject(o.Name)
                origin = doc.getObject(origin) if origin else None     # FreeCAD may have taken it along
                if origin is not None:
                    for f in list(origin.OriginFeatures):
                        doc.removeObject(f.Name)
                    doc.removeObject(origin.Name)
            else:
                doc.removeObject(o.Name)
    return note

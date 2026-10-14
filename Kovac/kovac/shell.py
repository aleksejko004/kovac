# SPDX-License-Identifier: LGPL-2.1-or-later
"""The Kovač shell: app bar, mode selector, function-grouped command bars, view bar,
"Advanced" switch, automatic regeneration, and wiring of tree, timeline, search,
radial menu and viewport interaction. FreeCAD workbenches stay behind "Advanced".
"""
import importlib

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtGui, QtWidgets

import kovac
from kovac import commands, navigation, selection, theme, views

VERSION = "0.1.0"
MODES = ("Design", "Drawing", "Make", "Simulate", "Render")
# mode -> [(group label, [command ids])]; our own group names, by function
# an entry that is a list becomes one dropdown button
GROUPS = {
    "Design": [("Sketch", ["Kovac_Sketch", "Kovac_Curve3D"]),
               ("Move", ["Kovac_Move"]),
               ("Form", ["Kovac_Extrude", "Kovac_Revolve", "Kovac_Sweep", "Kovac_Loft", "Kovac_Hole", "Kovac_Thread",
                         ["Kovac_Box", "Kovac_Cylinder", "Kovac_Sphere", "Kovac_Cone", "Kovac_Torus"]]),
               ("Shape", ["Kovac_FacePull", "Kovac_Fillet", "Kovac_Chamfer", "Kovac_Shell", "Kovac_Draft", "Kovac_DeleteFace",
                          ["Kovac_Combine", "Kovac_Split"], ["Kovac_Scale", "Kovac_Mirror"],
                          ["Kovac_PatternRect", "Kovac_PatternCirc"]]),
               ("Reference", [["Kovac_Plane", "Kovac_Axis", "Kovac_Point"]]),
               ("Assemble", [["Kovac_NewComponent", "Kovac_NewInstance"], "Kovac_Joint", "Kovac_DragComponent", "Kovac_Ground"]),
               ("Check", ["Kovac_Measure", ["Kovac_MassProperties", "Kovac_Interference", "Kovac_Section", "Kovac_DraftAnalysis"]]),
               ("Model", ["Kovac_Parameters", "Kovac_Material"]),
               ("Bring in", [["Kovac_ImportStep", "Kovac_ExportStep"]]),
               ("Select", ["Kovac_SelectTangent", ["Kovac_SaveSelectionSet", "Kovac_RestoreSelectionSet"]])],
    "Drawing": [("Create", ["Kovac_NewDrawing", "Kovac_BaseView", "Kovac_ProjectedView", "Kovac_SectionView", "Kovac_DetailView"]),
                ("Annotate", ["Kovac_DrawDimension", "Kovac_HoleCallouts", "Kovac_Balloon"]),
                ("Table", ["Kovac_PartsList"]),
                ("Export", ["Kovac_ExportPDF", "Kovac_ExportDXF"])],
    "Make": [("Make", [])], "Simulate": [("Simulate", [])], "Render": [("Render", [])],
}
LATER = {"Make": "Make (CAM) arrives in milestone 4.",
         "Simulate": "Simulation arrives in milestone 5d.", "Render": "Rendering arrives in milestone 5e."}
VIEW_QUICK = ["Kovac_Home", "Kovac_FitAll", "Kovac_Grid"]     # right end of the app bar
MODE_ICONS = {"Design": "extrude", "Drawing": "drawing", "Make": "toolpath", "Simulate": "simulate", "Render": "render"}
RIBBON_ICON = 26        # command icons, 30 % above the 20 px they started at
STOCK_DOCKS = ("Model", "Report view", "Python console", "Selection view", "Property view", "DAG View")
FILTERS = (("body", "Bodies"), ("face", "Faces"), ("edge", "Edges"), ("vertex", "Vertices"), ("profile", "Sketch profiles"),
           ("curve", "Sketch curves"), ("component", "Components"), ("joint", "Joints"), ("reference", "Reference geometry"))

_ui = {}
_hidden = {"toolbars": [], "docks": [], "menubar": False}


def mode():
    return kovac.prefs().GetString("Mode", "Design")


def advanced():
    return kovac.prefs().GetBool("Advanced", False)


def _lazy(module, fn, *args):
    return lambda: getattr(importlib.import_module("kovac." + module), fn)(*args)


def _view():
    return Gui.activeView() if Gui.activeView() is not None and hasattr(Gui.activeView(), "graphicsView") else None


def _with_view(fn):
    def run():
        v = _view()
        if v is None:
            raise RuntimeError("Open a design first.")
        fn(v)
    return run


# ---------------------------------------------------------------- commands

def _import_step():
    path, _ = QtWidgets.QFileDialog.getOpenFileName(Gui.getMainWindow(), "Import STEP", "", "STEP (*.step *.stp)")
    if path:
        import_step(path)


def import_step(path, doc=None):
    """STEP solids become an Import feature of the history: one body per solid."""
    import os
    from kovac import model
    doc = doc or App.ActiveDocument or App.newDocument("Design")
    shape = Part.read(path)
    if not shape.Solids:
        raise RuntimeError("No solids in %s." % os.path.basename(path))
    with commands.transaction("Import STEP", doc):
        fp = model.create(doc, model.Import, "Import", Imported=shape, SourceFile=path)
        fp.Label = os.path.splitext(os.path.basename(path))[0]
        model.commit(doc)
    if _view():
        views.home(_view())
    return doc


def _export_step():
    doc = App.ActiveDocument
    objs = [s.Object for s in Gui.Selection.getSelectionEx()] or [o for o in doc.Objects if _is_body(o)]
    path, _ = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Export STEP", doc.Name + ".step", "STEP (*.step *.stp)")
    if path:
        import Import
        Import.export(objs, path)


def _is_body(o):
    from kovac import tree
    return tree.role(o) == "body"


def _show_all():
    from kovac import tree
    for o in App.ActiveDocument.Objects:
        if tree.role(o) in ("body", "component"):
            o.Visibility = True


def _isolate():
    keep = {s.Object.Name for s in Gui.Selection.getSelectionEx()}
    if not keep:
        raise RuntimeError("Select what to isolate first.")
    for o in App.ActiveDocument.Objects:
        if _is_body(o):
            o.Visibility = o.Name in keep


def _select_tangent():
    picks = [(s.Object, n) for s in Gui.Selection.getSelectionEx("", 0) for n in s.SubElementNames]
    for obj, sub in picks:
        element = sub.split(".")[-1]
        prefix = sub[:-len(element)]
        shape = (obj.getSubObject(prefix) if prefix else obj).Shape
        idx = int(element[4:])
        chain = selection.tangent_edges(shape, idx) if element.startswith("Edge") else \
            selection.tangent_faces(shape, idx) if element.startswith("Face") else []
        for i in chain:
            Gui.Selection.addSelection(obj, "%s%s%d" % (prefix, element[:4], i))


def _look_at(view):
    import Part
    sel = Gui.Selection.getSelectionEx("", 0)
    for s in sel:
        for n in s.SubElementNames:
            f = Part.getShape(s.Object, n, needSubElement=True)
            if f.ShapeType == "Face":
                u, v = f.Surface.parameter(f.CenterOfMass)
                views.go(view, views.camera_rotation(f.normalAt(u, v)))
                return
    raise RuntimeError("Select a face to look at.")


def _save_selection_set():
    doc = App.ActiveDocument
    picks = [[s.Object.Name, n] for s in Gui.Selection.getSelectionEx("", 0) for n in (s.SubElementNames or [""])]
    if not picks:
        raise RuntimeError("Select something to save first.")
    name, ok = QtWidgets.QInputDialog.getText(Gui.getMainWindow(), "Save selection set", "Name:",
                                              text="Set %d" % (len(selection.load_sets(doc)) + 1))
    if ok and name:
        with commands.transaction("Save selection set", doc):
            selection.save_set(doc, name, picks)


def _restore_selection_set():
    doc = App.ActiveDocument
    sets = selection.load_sets(doc)
    if not sets:
        raise RuntimeError("This document has no saved selection sets.")
    menu = QtWidgets.QMenu(Gui.getMainWindow())
    for name in sets:
        menu.addAction(name)
    act = menu.exec(QtGui.QCursor.pos())
    if act:
        Gui.Selection.clearSelection()
        for obj, sub in sets[act.text()]:
            if doc.getObject(obj):
                Gui.Selection.addSelection(doc.getObject(obj), sub)


def _toggle_orbit_mode():
    p = kovac.prefs()
    p.SetString("OrbitMode", "free" if p.GetString("OrbitMode", "free") == "turntable" else "turntable")
    commands.report("Orbit: %s" % p.GetString("OrbitMode"), error=False)


def _left_drag(kind):
    def run():
        p = kovac.prefs()
        p.SetString("LeftDrag", "select" if p.GetString("LeftDrag", "select") == kind else kind)
        commands.report("Left drag: %s" % p.GetString("LeftDrag"), error=False)
    return run


def _can_step(cid):
    def active():
        doc = App.ActiveDocument
        return bool(commands._running) or (doc is not None and (doc.UndoCount if cid == "Std_Undo" else doc.RedoCount) > 0)
    return active


def _take_step_keys():
    """Undo and Redo keys move from FreeCAD's commands to ours (two actions on one key fire
    neither); ours sit on the main window too, so the keys work wherever the bars are hidden."""
    mw = Gui.getMainWindow()
    for cid in ("Std_Undo", "Std_Redo"):
        stock = Gui.Command.get(cid)
        key = stock.getShortcut() if stock else ""
        for a in (stock.getAction() if stock else []):
            a.setShortcut(QtGui.QKeySequence())
        for a in _actions(cid.replace("Std_", "Kovac_")):
            if key:
                a.setShortcut(QtGui.QKeySequence(key))
                a.setToolTip("%s  (%s)" % (a.text(), key))
            if a not in mw.actions():
                mw.addAction(a)


def _toggle_advanced():
    kovac.prefs().SetBool("Advanced", not advanced())
    apply_visibility()


def _toggle_theme():
    name = "dark" if kovac.theme_name() == "light" else "light"
    theme.apply(name)
    Gui.getMainWindow().setStyleSheet(theme.qss(name))


def about():
    d = QtWidgets.QDialog(Gui.getMainWindow())
    d.setWindowTitle("About Kovač")
    lay = QtWidgets.QVBoxLayout(d)
    logo = QtWidgets.QLabel()
    logo.setPixmap(QtGui.QIcon(kovac.icon("app")).pixmap(64, 64))
    text = QtWidgets.QLabel(
        "<h2>Kovač %s</h2><p><b>Built on <a href='https://www.freecad.org'>FreeCAD</a> %s</b> — the open-source "
        "parametric modeller that provides Kovač's geometry kernel integration, document model, solvers and "
        "workbenches.</p><p>Kovač is an independent distribution and not an official FreeCAD product.</p>"
        "<p>Licensed LGPL-2.1-or-later, like FreeCAD.</p>" % (VERSION, ".".join(App.Version()[:3])))
    text.setOpenExternalLinks(True)
    text.setWordWrap(True)
    lay.addWidget(logo)
    lay.addWidget(text)
    d.resize(420, 260)
    d.show()
    return d


def register():
    from kovac import design, drawmode, inspect_tools, params
    design.register()
    from kovac import assemble
    assemble.register()
    drawmode.register()
    inspect_tools.register()
    params.register()
    add = commands.add
    view = lambda f: _with_view(f)  # noqa: E731
    add("Kovac_NewDesign", "New design", "Start a new design", _lazy("startpage", "new_design"),
        key="Ctrl+N")
    add("Kovac_ImportStep", "Import STEP…", "Bring a STEP model into the design", _import_step, icon=kovac.icon("import_step"))
    add("Kovac_ExportStep", "Export STEP…", "Export the selected (or all) bodies as STEP", _export_step, active=commands.has_doc)
    for cid, text, icon in (("Std_Undo", "Undo", "edit-undo"), ("Std_Redo", "Redo", "edit-redo")):
        add(cid.replace("Std_", "Kovac_"), text, "%s the last step; while a tool is running, leave the tool instead" % text,
            lambda c=cid: commands.step(c), icon=icon, active=_can_step(cid))
    add("Kovac_Start", "Start page", "Show the start page", _lazy("startpage", "create"))
    add("Kovac_About", "About Kovač", "Version and credits", about)
    add("Kovac_Advanced", "Advanced / Expert", "Show or hide FreeCAD's own workbenches, menus and panels", _toggle_advanced)
    add("Kovac_Theme", "Light / dark", "Switch between the light and dark look", _toggle_theme)
    add("Kovac_Search", "Search commands", "Find any command by name", _lazy("search", "popup"),
        key=kovac.prefs().GetString("SearchKey", "S"))
    add("Kovac_Measure", "Measure", "Hover for a readout, pick two for distance and angle",
        _lazy("measure", "panel"), icon=kovac.icon("measure"), active=commands.has_doc)
    add("Kovac_SelectTangent", "Select tangent chain", "Extend selected edges/faces to everything tangent to them",
        _select_tangent, active=Gui.Selection.hasSelection)
    add("Kovac_SaveSelectionSet", "Save selection set…", "Store the current selection in the document",
        _save_selection_set, active=Gui.Selection.hasSelection)
    add("Kovac_RestoreSelectionSet", "Restore selection set…", "Select a saved set again", _restore_selection_set,
        active=commands.has_doc)
    add("Kovac_ShowAll", "Show all", "Show every body", _show_all, active=commands.has_doc)
    add("Kovac_Isolate", "Isolate", "Hide every body except the selected ones", _isolate, active=Gui.Selection.hasSelection)
    add("Kovac_LookAt", "Look at", "Turn the view to face the selected face", view(_look_at), active=Gui.Selection.hasSelection)
    add("Kovac_Home", "Home view", "Return to the home view", view(views.home), icon=kovac.icon("home"))
    add("Kovac_SetHome", "Set current view as home", "Make this view the home view", view(views.set_home))
    add("Kovac_ResetHome", "Reset home view", "Home view back to isometric", views.reset_home)
    add("Kovac_DefineFront", "Define current view as Front", "Re-orient the view cube so this view is Front",
        view(views.define_front), active=commands.has_doc)
    add("Kovac_ResetFront", "Reset Front", "Back to the document's own Front", lambda: views.reset_front(), active=commands.has_doc)
    add("Kovac_SaveView", "Save view…", "Save the current camera as a named view",
        lambda: _ui["tree"].widget().save_view(), active=commands.has_doc)
    add("Kovac_FitAll", "Fit all", "Zoom to show the whole model", view(lambda v: v.fitAll()), icon=kovac.icon("zoom"))
    add("Kovac_Grid", "Grid and snap", "Show the grid; clicked points and sketch drawing snap to it",
        _lazy("grid", "toggle"), icon=kovac.icon("grid"), key="F3")
    add("Kovac_OrbitMode", "Free / turntable orbit", "Switch between free and turntable (around Z) orbit", _toggle_orbit_mode)
    for kind in ("Orbit", "Pan", "Zoom"):
        add("Kovac_LeftDrag_" + kind, kind, "Left-drag %ss (click again for selection)" % kind.lower(),
            _left_drag(kind.lower()), icon=kovac.icon(kind.lower()))
    for d in views.DIRS:
        n = views.name(d)
        add("Kovac_View_" + n.replace(" ", ""), "%s view" % n, "Look from %s" % n.lower(),
            view(lambda v, d=d: views.standard(v, d)))
    for m in MODES:
        add("Kovac_Mode_" + m, "%s mode" % m, "Switch to %s mode" % m, lambda m=m: set_mode(m))
    for kind, label in FILTERS:
        add("Kovac_Filter_" + kind, "Select only: " + label, "Selection filter", lambda k=kind: _toggle_filter(k))
    add("Kovac_Filter_Clear", "Select anything", "Clear the selection filter", lambda: _set_filters(set()))


# ---------------------------------------------------------------- UI construction

def _actions(cid):
    cmd = Gui.Command.get(cid)
    return cmd.getAction() if cmd else []


def _add(tb, cid):
    """Add a command to a toolbar; a list of ids or a group command becomes one dropdown."""
    acts = [a for c in cid for a in _actions(c)] if isinstance(cid, list) else _actions(cid)
    if len(acts) <= 1:
        for a in acts:
            tb.addAction(a)
        return
    b = QtWidgets.QToolButton(popupMode=QtWidgets.QToolButton.MenuButtonPopup)
    m = QtWidgets.QMenu(b)
    for a in acts:
        m.addAction(a)
    b.setMenu(m)
    b.setDefaultAction(next((a for a in acts if a.isChecked()), acts[0]))
    m.triggered.connect(b.setDefaultAction)
    tb.addWidget(b)


def _toolbar(name, area=QtCore.Qt.TopToolBarArea, brk=False):
    mw = Gui.getMainWindow()
    tb = mw.findChild(QtWidgets.QToolBar, name)
    if tb is None:
        tb = QtWidgets.QToolBar(name, mw)
        tb.setObjectName(name)
        tb.setMovable(False)
        tb.setIconSize(QtCore.QSize(RIBBON_ICON, RIBBON_ICON))
        if brk:
            mw.addToolBarBreak(area)
        mw.addToolBar(area, tb)
    return tb


def _button(action_or_actions):
    """A ribbon button for one action, or a dropdown for several (the last used one shows)."""
    acts = action_or_actions if isinstance(action_or_actions, list) else [action_or_actions]
    b = QtWidgets.QToolButton(autoRaise=True)
    b.setIconSize(QtCore.QSize(RIBBON_ICON, RIBBON_ICON))
    side = RIBBON_ICON + 10
    b.setFixedSize(side + (14 if len(acts) > 1 else 0), side)
    if len(acts) > 1:
        m = QtWidgets.QMenu(b)
        for a in acts:
            m.addAction(a)
        b.setMenu(m)
        b.setPopupMode(QtWidgets.QToolButton.MenuButtonPopup)
        m.triggered.connect(b.setDefaultAction)
    if acts:
        b.setDefaultAction(next((a for a in acts if a.isChecked()), acts[0]))
    return b


def ribbon_group(label, buttons):
    """Buttons in a row with the group name centred underneath (keeps the bar short)."""
    w = QtWidgets.QWidget(objectName="kovacRibbonGroup")
    v = QtWidgets.QVBoxLayout(w)
    v.setContentsMargins(3, 2, 3, 0)
    v.setSpacing(0)
    row = QtWidgets.QHBoxLayout()
    row.setSpacing(1)
    for b in buttons:
        row.addWidget(b)
    v.addLayout(row)
    name = QtWidgets.QLabel(label.upper(), objectName="kovacGroupLabel")
    name.setAlignment(QtCore.Qt.AlignHCenter)
    v.addWidget(name)
    return w


def ribbon_divider():
    """A light, softly fading bar between groups (styled in theme.qss)."""
    line = QtWidgets.QFrame(objectName="kovacRibbonDivider")
    line.setFixedWidth(2)
    return line


def _command_buttons(cids):
    out = []
    for cid in cids:
        acts = [a for c in cid for a in _actions(c)] if isinstance(cid, list) else _actions(cid)
        if acts:
            out.append(_button(acts if len(acts) > 1 else acts[0]))
    return out


def _select_button():
    """One dropdown for selection tools and filters; the tooltip names the active filter."""
    b = QtWidgets.QToolButton(autoRaise=True, popupMode=QtWidgets.QToolButton.InstantPopup, toolTip="Select: anything")
    b.setIcon(QtGui.QIcon(kovac.icon("select")))
    b.setIconSize(QtCore.QSize(RIBBON_ICON, RIBBON_ICON))
    b.setFixedSize(RIBBON_ICON + 24, RIBBON_ICON + 10)
    m = QtWidgets.QMenu(b)
    for cid in ("Kovac_SelectTangent", "Kovac_SaveSelectionSet", "Kovac_RestoreSelectionSet"):
        for a in _actions(cid):
            m.addAction(a)
    fm = m.addMenu("Select only")
    for kind, text in FILTERS:
        a = fm.addAction(text)
        a.setCheckable(True)
        a.setData(kind)
        a.triggered.connect(lambda _=False, k=kind: _toggle_filter(k))
    m.addAction("Select anything", lambda: _set_filters(set()))
    b.setMenu(m)
    _ui["filter_button"], _ui["filter_menu"] = b, fm
    return b


def _mode_button():
    """The big button at the left of the command row: which kind of work (Design, Make, …)."""
    b = QtWidgets.QToolButton(objectName="kovacModeButton", popupMode=QtWidgets.QToolButton.InstantPopup,
                              toolButtonStyle=QtCore.Qt.ToolButtonTextBesideIcon)
    b.setIconSize(QtCore.QSize(32, 32))
    m = QtWidgets.QMenu(b)
    for name in MODES:
        a = m.addAction(QtGui.QIcon(kovac.icon(MODE_ICONS[name])), name)
        a.setCheckable(True)
        a.triggered.connect(lambda _=False, n=name: set_mode(n))
    b.setMenu(m)
    return b


def _filter_kinds():
    return set(navigation.select_filter.kinds)


def _set_filters(kinds):
    navigation.set_filter(kinds)
    if "filter_button" in _ui:
        names = [label for k, label in FILTERS if k in kinds]
        _ui["filter_button"].setToolTip("Select: " + (", ".join(names) if names else "anything"))
        for a in _ui["filter_menu"].actions():
            a.setChecked(a.data() in kinds)


def _toggle_filter(kind):
    _set_filters(_filter_kinds() ^ {kind})


def build_ui():
    if "bars" in _ui:
        return
    mw = Gui.getMainWindow()
    # row 1: menu, file, undo/redo ... view helpers, search
    app = _toolbar("kovacAppBar")
    menu_btn = QtWidgets.QToolButton(text="☰", toolTip="Menu", popupMode=QtWidgets.QToolButton.InstantPopup)
    menu = QtWidgets.QMenu(menu_btn)
    for cid in ("Kovac_NewDesign", "Std_Open", "Kovac_ImportStep", "Std_Save", "Std_SaveAs", "Kovac_ExportStep",
                None, "Kovac_Start", "Std_DlgPreferences", "Kovac_Theme", "Kovac_Advanced", None, "Kovac_About", "Std_Quit"):
        if cid is None:
            menu.addSeparator()
        else:
            for a in _actions(cid):
                menu.addAction(a)
    menu_btn.setMenu(menu)
    app.addWidget(menu_btn)
    _take_step_keys()
    for cid in ("Std_Save", "Kovac_Undo", "Kovac_Redo"):
        for a in _actions(cid):
            app.addAction(a)
    spacer = QtWidgets.QWidget()
    spacer.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
    app.addWidget(spacer)
    for cid in VIEW_QUICK:
        _add(app, cid)
    for a in _actions("Kovac_Search"):
        app.addAction(a)
    # row 2: the big mode button, then the current mode's command groups
    modes = _toolbar("kovacModes", brk=True)
    _ui["mode_button"] = _mode_button()
    modes.addWidget(_ui["mode_button"])
    _ui["groups"] = {}
    for m, groups in GROUPS.items():
        tb = _toolbar("kovacGroup_%s_0" % m)
        tb.setProperty("kovacGroup", True)
        for i, (label, cids) in enumerate(groups):
            if i:
                tb.addWidget(ribbon_divider())
            buttons = [_select_button()] if label == "Select" else _command_buttons(cids)
            if not cids and m in LATER:
                buttons = [QtWidgets.QLabel("  " + LATER[m], objectName="kovacMuted")]
            tb.addWidget(ribbon_group(label, buttons))
        _ui["groups"][m] = [tb]
    from kovac import timeline, tree
    _ui["tree"] = tree.create()
    _ui["timeline"] = timeline.create()
    mdi = mw.findChild(QtWidgets.QMdiArea)
    mdi.subWindowActivated.connect(_tab_changed)
    _ui["bars"] = [app, modes]


def _tab_changed(*_):
    """A drawing tab brings Drawing mode; a 3D tab brings back Design from it."""
    navigation.install()
    _lazy("grid", "refresh", True)()
    v = Gui.activeView()
    if v is not None and hasattr(v, "getPage"):
        if mode() != "Drawing":
            set_mode("Drawing")
    elif mode() == "Drawing" and v is not None and hasattr(v, "graphicsView"):
        set_mode("Design")


def set_mode(m):
    """Modes change only the command set; model, tree, history and selection stay."""
    kovac.prefs().SetString("Mode", m)
    for name, bars in _ui.get("groups", {}).items():
        for tb in bars:
            tb.setVisible(name == m)
    b = _ui.get("mode_button")
    if b is not None:
        b.setText(m.upper())
        b.setIcon(QtGui.QIcon(kovac.icon(MODE_ICONS[m])))
        for a in b.menu().actions():
            a.setChecked(a.text() == m)


def apply_visibility():
    """Hide FreeCAD's own UI unless Advanced is on; restore exactly what was visible."""
    mw = Gui.getMainWindow()
    ours = lambda w: w.objectName().startswith("kovac")  # noqa: E731
    if advanced():
        for w in _hidden["toolbars"] + _hidden["docks"]:
            try:
                w.show()
            except RuntimeError:
                pass
        _hidden["toolbars"], _hidden["docks"] = [], []
        mw.menuBar().show()
        nav = mw.statusBar().findChild(QtWidgets.QWidget, "NavigationIndicator")
        if nav is not None:
            nav.show()
        return
    for tb in mw.findChildren(QtWidgets.QToolBar):
        if not ours(tb) and tb.isVisible() and tb.parent() is mw:
            tb.hide()
            _hidden["toolbars"].append(tb)
    for d in mw.findChildren(QtWidgets.QDockWidget):
        if d.objectName() in STOCK_DOCKS and d.isVisible():
            d.hide()
            _hidden["docks"].append(d)
    mw.menuBar().hide()
    nav = mw.statusBar().findChild(QtWidgets.QWidget, "NavigationIndicator")
    if nav is not None:
        nav.hide()
    _sync_tasks()


def _sync_tasks():
    """FreeCAD's task panel shows only while one of its dialogs is open.
    Polled every 300 ms, and re-checked on the next event-loop turn whenever FreeCAD shows it."""
    tasks = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Tasks")
    from kovac import sketchmode
    if tasks is not None and not advanced():
        tasks.setVisible(Gui.Control.activeDialog() and not sketchmode.in_sketch())
        if not tasks.property("kovacSynced"):
            tasks.setProperty("kovacSynced", True)
            tasks.visibilityChanged.connect(lambda shown: shown and QtCore.QTimer.singleShot(0, _sync_tasks))
    from kovac import sketchtools
    sketchtools.poll()
    bar = Gui.getMainWindow().findChild(QtWidgets.QToolBar, "kovacSketchBar")
    if bar is not None and bar.isVisible() and not sketchmode.in_sketch():   # sketch closed some other way
        sketchmode.finish()
    if "tasks_timer" not in _ui:
        _ui["tasks_timer"] = QtCore.QTimer(interval=300)
        _ui["tasks_timer"].timeout.connect(_sync_tasks)
        _ui["tasks_timer"].start()


# ---------------------------------------------------------------- automatic regeneration

class AutoRecompute:
    """No manual recompute: anything left touched (property edits, undo/redo) regenerates
    on the next event-loop turn. Edits inside an open transaction or edit mode wait."""

    def __init__(self):
        self.timer = QtCore.QTimer(singleShot=True, interval=0)
        self.timer.timeout.connect(self.run)
        App.addDocumentObserver(self)

    def slotChangedObject(self, *_):     # (obj, prop); undo/redo pass (doc)
        self.timer.start()

    slotUndoDocument = slotRedoDocument = slotChangedObject

    def run(self):
        doc = App.ActiveDocument
        if doc is None or doc.HasPendingTransaction or navigation.in_edit():
            return
        if any("Touched" in o.State for o in doc.Objects):
            from kovac import model
            model.commit(doc)


# ---------------------------------------------------------------- workbench hooks

def initialize(wb):
    register()
    # FreeCAD creates a command's QAction only once a menu or toolbar uses it; this menu
    # does that (and is the full command list when Advanced shows the menu bar).
    ours = [c for c in commands.REGISTRY if not c.startswith(("Kovac_View_", "Kovac_Filter_", "Kovac_Mode_"))]
    wb.appendMenu("&Kovač", ours)
    wb.appendMenu(["&Kovač", "Views"], [c for c in commands.REGISTRY if c.startswith("Kovac_View_")])
    wb.appendMenu(["&Kovač", "Selection filter"], [c for c in commands.REGISTRY if c.startswith("Kovac_Filter_")])
    wb.appendMenu(["&Kovač", "Mode"], [c for c in commands.REGISTRY if c.startswith("Kovac_Mode_")])
    # Same for the sketcher's tools: sketches stay in Kovač (no switch to FreeCAD's sketcher
    # workbench), so without this their default keys ("G, L", ...) were never registered at all.
    import SketcherGui  # noqa: F401  (registers the sketcher commands)
    from kovac import sketchmode
    wb.appendMenu(["&Kovač", "Sketch"], [c for c in sketchmode.tool_ids() if not c.startswith("Kovac_")])


def activated():
    if kovac.prefs().GetInt("LookVersion", 0) < theme.LOOK_VERSION:   # profile from before dark was the default
        theme.apply("dark")
    build_ui()
    if _ui.get("recompute") is None:
        _ui["recompute"] = AutoRecompute()
    name = kovac.theme_name()
    Gui.getMainWindow().setStyleSheet(theme.qss(name))
    for w in _ui["bars"]:
        w.show()
    _ui["tree"].show()
    _ui["timeline"].show()
    set_mode(mode())
    apply_visibility()
    # ponytail: at startup FreeCAD restores its saved window state after Activated(); hiding
    # again on the next event-loop turns is simpler than hooking the restore.
    for ms in (0, 400):
        QtCore.QTimer.singleShot(ms, lambda: (arrange(), apply_visibility()))
    navigation.install()
    navigation.install_selection_highlight()
    from kovac import drawmode, grid
    grid.start()
    drawmode.install()
    if App.ActiveDocument:
        views.apply_cube_labels()
    elif kovac.prefs().GetBool("ShowStartPage", True):
        from kovac import startpage
        startpage.create()


def arrange():
    """Kovač's two top rows in order, whatever toolbar layout FreeCAD restored from an older
    profile (it would otherwise put bars where an earlier Kovač had them)."""
    mw = Gui.getMainWindow()
    area = QtCore.Qt.TopToolBarArea
    sketch = mw.findChild(QtWidgets.QToolBar, "kovacSketchBar")
    order = _ui["bars"][:1] + [None] + _ui["bars"][1:] + [tb for m in MODES for tb in _ui["groups"][m]] + ([sketch] if sketch else [])
    shown = {tb: tb.isVisible() for tb in order if tb is not None}
    for tb in shown:
        mw.removeToolBarBreak(tb)
    for tb in order:
        if tb is None:
            mw.addToolBarBreak(area)
        else:
            mw.addToolBar(area, tb)
    for tb, on in shown.items():
        tb.setVisible(on)


def deactivated():
    for w in _ui.get("bars", []):
        w.hide()
    for bars in _ui.get("groups", {}).values():
        for tb in bars:
            tb.hide()
    for k in ("tree", "timeline"):
        if k in _ui:
            _ui[k].hide()
    navigation.uninstall_all()
    Gui.getMainWindow().setStyleSheet("")
    Gui.getMainWindow().menuBar().show()

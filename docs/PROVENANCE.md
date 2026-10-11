# Provenance

Public source of every non-trivial algorithm and interaction design in Kovač. No proprietary software, its files, UI or documentation was used (brief §1).

| Where | What | Source |
|---|---|---|
| `kovac/radial.py` | Radial (marking) menu: 8 slots, press-drag-release expert gesture, fixed "repeat last" slot | G. Kurtenbach, W. Buxton, "The limits of expert performance using hierarchic marking menus", CHI '93; J. Callahan et al., "An empirical comparison of pie vs. linear menus", CHI '88 |
| `kovac/search.py` | Fuzzy subsequence command search with word-start and run bonuses | G. Navarro, "A guided tour to approximate string matching", ACM Computing Surveys 33(1), 2001; heuristics our own |
| `kovac/navigation.py` | Orbit about a picked pivot (rotate camera position and orientation about a point), free and turntable modes | Rigid-body rotation, e.g. Foley, van Dam et al., *Computer Graphics: Principles and Practice*; turntable = yaw about world Z then pitch about camera X |
| `kovac/navigation.py` | Zoom toward cursor (point under cursor stays fixed) | Affine scaling about a point; derivation in code comments |
| `kovac/navigation.py`, `kovac/selection.py` | Window (enclosed) vs crossing (touched) selection by drag direction | A widespread convention in technical drawing software; implementation from first principles (projected samples + picks) |
| `kovac/selection.py` | Tangent chains of edges/faces (G1 continuity across shared vertices/edges) | G. Farin, *Curves and Surfaces for CAGD*, 5th ed., ch. on geometric continuity |
| `kovac/views.py` | 26 standard views, view naming, isometric | ISO 5456-2 (orthographic) / ISO 5456-3 (axonometric) |
| `kovac/views.py` | "Define current view as Front": snap the camera frame to the nearest of 24 axis-aligned rotations, relabel the cube | Our own, from rotation-group basics |
| Orientation cube behaviour | 26 clickable regions, drag-orbit, roll/step buttons | FreeCAD `src/Gui/NaviCube.cpp` (LGPL-2.0-or-later), used unchanged |
| `kovac/commands.py` | One transaction per user action | FreeCAD `App::Document` transactions (LGPL) |
| `kovac/timeline.py` | Creating feature of a picked element | FreeCAD element history (`getElementHistory`, LGPL) |
| `tools/icongen.py` | Isometric icon projection, Newell normals, painter's ordering, Sutherland–Hodgman clipping, three-tone shading | ISO 5456-3; M. Newell, R. Newell, T. Sancha, "A solution to the hidden surface problem", ACM '72; I. Sutherland, G. Hodgman, "Reentrant polygon clipping", CACM 1974; A. Gooch et al., "A non-photorealistic lighting model for automatic technical illustration", SIGGRAPH '98 |
| `tools/icongen.py` app mark | Anvil pictogram (Kovač = smith) | Original drawing, generic object |
| `kovac/theme.py`, `dist/make_dist.py` | Preference packs, `branding.xml`, user-parameter template | FreeCAD source: `src/App/Branding.cpp`, `src/App/Application.cpp`, `src/Gui/StartupProcess.cpp`, `data/Gui/PreferencePacks` (LGPL) |
| `prototypes/adr0002_chain.py` | Toponaming robustness probe | Our own test design; FreeCAD 1.1.4 behaviour |

## Added in M2

| Where | What | Source |
|---|---|---|
| `kovac/topo.py` | Persistent naming: faces tagged by the feature and profile element that made them, inherited through later operations by surface support plus an interior point; edges and vertices named by their adjacent face tags; resolution by unique match, then a clearly nearest candidate, then exact geometry, else an explicit broken reference | J. Kripac, "A mechanism for persistently naming topological entities in history-based parametric solid models", CAD 29(2), 1997; V. Capoyleas, X. Chen, C. M. Hoffmann, "Generic naming in generative, constraint-based design", CAD 28(1), 1996; implementation our own |
| `kovac/topo.py` | Faces an operation left untouched keep their tag directly (same kernel face) | OCCT Boolean Operations user guide (open source): unmodified arguments' sub-shapes are passed to the result as they are |
| `kovac/model.py` | Validity check limited to the faces an operation made, plus closed shells | OCCT `BRepCheck_Analyzer` (open source); restriction our own |
| `kovac/regions.py` | Sketch regions: split all curves at their intersections, walk the planar arrangement face by face (half-edge traversal), nest holes by containment | M. de Berg et al., *Computational Geometry: Algorithms and Applications*, 3rd ed., ch. 2 (doubly-connected edge lists, overlay of subdivisions) |
| `kovac/model.py` | Operation inference: a profile on a body face pulled outward joins, pushed inward cuts, touching nothing makes a new body; otherwise by the share of the tool inside material | Our own, from brief §3.6 |
| `kovac/features.py` | Thin extrude as a band between offset profile curves; taper as a loft to the offset end profile | Our own, on OCCT offset/loft (open source) |
| `kovac/features.py` | ISO metric holes: pitch, tap drill, clearance classes, counterbore and countersink sizes | ISO 261 / ISO 724 (metric threads), ISO 273 (clearance holes), ISO 4762 (socket head cap screws), ISO 10642 (countersunk socket screws); tap drill = nominal − pitch |
| `kovac/modify.py` | Shell when the wall equals a fillet radius: offset a copy with those fillets removed (the inner corner is sharp), extend it out through the opened faces, subtract | Our own, on OCCT defeaturing and offset (open source) |
| `kovac/modify.py` | Draft | OCCT `BRepOffsetAPI_DraftAngle` via pythonocc-core (LGPL-3.0) |
| `kovac/modify.py` | Patterns of features (re-apply the feature's tool at each instance), of bodies and faces; skipped instances | Our own |
| `kovac/datum.py` | Planes from a face, offset, angle about an edge, mid-plane, three points; plane frames | Analytic geometry; our own |
| `kovac/materials.py` | Densities and stiffness of the material library | Typical room-temperature values from public references: EN 10025-2 (S235), EN 10088 (1.4301), EN 573 / EN 485 (aluminium alloys), EN 12164 (brass), EN 13601 (copper), ASTM B348 (titanium grade 5); polymer values are typical published ranges |
| `kovac/grid.py` | Ground grid spacing on a 1-2-5 sequence chosen from zoom; snapping to half a step, to a face's centre nearby, never off the clicked face | 1-2-5 preferred-number scales (cf. ISO 3 / IEC 60063 practice); behaviour our own |
| `kovac/navigation.py` | Dragging the orientation cube orbits about the model centre; a plain click is replayed to the cube | Our own, on FreeCAD's NaviCube (LGPL) |
| `kovac/tree.py` | See-through browser panel floating over the 3D view, sized to its rows, visibility eyes per row and folder | Our own design |
| `kovac/timeline.py` | Rollback marker, drag reorder with dependency checks, suppress, groups | Our own, on FreeCAD document transactions (LGPL) |
| `kovac/params.py` | Named parameters and expressions | FreeCAD `App::VarSet` and expression engine (LGPL) |
| `kovac/navigation.py`, `kovac/grid.py` | Magnetic grid cursor in sketches: the pointer is moved to the screen position of the nearest grid point unless it is over geometry; FreeCAD's sketch snapping (within a fifth of a grid step) then lands exactly | Our own; FreeCAD `src/Mod/Sketcher/Gui/SnapManager.cpp` (LGPL) read for its snapping rules |
| `kovac/shell.py` | Command ribbon: groups of icon buttons with the group name centred underneath, variants behind a dropdown, one big mode button | Our own design from the owner's description |
| `tools/icongen.py` | Sketch tool, constraint, feature-option and mode icons | Original drawings on the existing icon rules (`docs/icons/STYLE.md`) |
| `kovac/radial.py` | Fixed-position ring (same direction = same command in every context) with context slots and a list below | Kurtenbach & Buxton (CHI '93) on marking-menu stability; layout our own from the owner's description |
| `kovac/regionpick.py` | Hover shading and click selection of sketch regions outside panels, hidden by bodies in front | Our own, on the region traversal above and FreeCAD picking (LGPL) |
| `kovac/sketchtools.py` | Polyline as a chained line tool (synthetic click at each new end); circumscribed regular polygon by re-constraining FreeCAD's polygon (corners onto an outer circle, one side tangent to the drawn circle) | Our own; FreeCAD `Mod/Sketcher/ProfileLib/RegularPolygon.py` (LGPL) read for the polygon's structure |
| `kovac/views.py` | World-fixed directional light plus a dimmed headlight for shading | Standard OpenGL/Coin lighting (Coin3D BSD); values our own |
| `kovac/radial.py` | Gesture trail and opening the menu mid-drag | Our own |
| `kovac/navigation.py` | Snap marker and one snapping rule (existing points, then nearby grid points, else exact) across sketch tools, face points and manipulators | Our own, from the owner's description |
| `kovac/sketchmode.py` | Plane picker: rounded squares in the octant facing the camera, hover and click feedback | Our own, from the owner's description |
| `kovac/sketchtools.py` | Midpoint constraint: a point and a curve's own two endpoints, symmetric about the point | FreeCAD's own Sketcher Symmetric constraint (`Sketcher::Constraint` type `Symmetric`, LGPL) covers this directly -- three-point form, point3 the mirror centre of point1/point2; no new solver code |
| `kovac/grid.py` | Ground-grid clipping: disable Coin's automatic near/far clipping while the grid is on and size the planes from the camera to a sphere around the model and the grid's own footprint | Open Inventor / Coin3D `SoRenderManager::setAutoClipping` (BSD), documented public API; the bbox-exclusion trick it works around is FreeCAD's own `SoSkipBoundingGroup` |
| `kovac/design.py`, `kovac/shell.py` | Keyboard shortcuts for the most-used commands: single letters free of both FreeCAD's own bindings and any letter it uses as the first key of a multi-key sequence (a bare key is ambiguous against a sequence sharing its first key, not just an exact repeat) | Checked against the live command registry (`Gui.listCommands()`) with the Sketcher workbench loaded; FreeCAD's own multi-key sequence convention (`"G, R"`-style, `src/Gui/Command.cpp`, LGPL) used for the reasoning, not copied |
| `kovac/navigation.py`, `kovac/overlay.py` | Whole-object selection wash: every face of a selected object's shape tessellated into one translucent overlay, under FreeCAD's own per-element selection colour | Our own, on the existing `overlay.face_node` tessellation approach |

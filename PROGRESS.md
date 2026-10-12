# Progress

## Milestone 1 — Foundation (implemented 2026-10-08, awaiting owner review)

| Item | State |
|---|---|
| FreeCAD 1.1.4 binary as the engine (source build deferred by owner) | done |
| Minimal addon workbench, loads into stock FreeCAD | done |
| ADR-0001 addon vs core patches | accepted |
| ADR-0002 body/feature model, prototype on two models | accepted for M2 (see M2) |
| Branded distribution: name, splash, About credit, start page, profile template, stock UI behind Advanced | done (Windows verified; Linux path written, not run) |
| Palette (3 accent options), typography, light/dark themes, preference packs | done; **accent choice pending** |
| Icon STYLE.md, generator, contact sheet, first 12 icons (+ app mark) | done; **approval pending** |
| Orientation-cube design doc + 3 rendered variants | done; **choice pending** |
| Shell: modes, function-grouped bars, command search + favourites, floating panels, model tree, timeline (read-only), radial menu | done |
| Navigation & selection (§3.3) incl. orientation cube (§3.4) | done (cube styling limits → core-patch candidates) |
| Auto-recompute; autosave + crash recovery verified | done |
| CI on Windows + Linux | workflow written; **not run** (no remote repository) |

## Milestone 2 — Sketching and part modeling (implemented 2026-10-10, awaiting owner review)

Report: `docs/milestones/M2-report.md`.

| Item | State |
|---|---|
| ADR-0002 hybrid model; ADR-0003 reference layer | accepted, implemented |
| History: rollback, insert, reorder with dependency checks, suppress, edit, groups, error states | done |
| Sketch entry on planes/faces/datums, regions, Finish Sketch | done; inline dimensions and our own inference **not yet** |
| Extrude, Revolve, Sweep, Loft, primitives, Hole (ISO), cosmetic Thread, operation inference | done; rails/guide/twist options, coil/pipe, modeled thread **not yet** |
| Face Pull, Fillet/Chamfer (groups), Shell, Draft, Delete Face, Combine, Split Body, Move/Copy, Scale, Mirror, Patterns | done; variable radius, Split/Replace Face, Align, path pattern, Rib/Web/Emboss **not yet** |
| Reference geometry, parameters, inspect, section, materials | done; curvature/zebra **not yet** |
| UI round 1 toward the owner's direction: see-through browser, cube drag-orbit, grid + snapping | done; "big button" **waits for the owner's description** |
| Golden suite (32), torture suite (23), GUI end to end, benchmark counts | pass |
| Interaction target ≥ 40 % fewer | **not met** (~11 %, stock side estimated) |
| Regeneration < 1 s on 50 features | **not met** (2.5 s tip edit, 31 s full replay, under heavy machine load) |

## UI round 2 (owner's direction, 2026-10-10)

Recorded in `CLAUDE.md` → "UI direction".

| Item | State |
|---|---|
| Dark theme by default; deeper background; brighter, non-neon axis colours | done |
| Top rows ~30 % larger; big mode button at the left of the command row | done |
| Group names centred under their icons; view bar removed (Home / Fit / Grid next to Search) | done |
| Sketch: overview → pick plane or face → camera faces it → Finish returns to the overview | done |
| Sketch ribbon: 49 sketcher tools with our icons (Create / Modify / Constrain / Project / View); sketcher task panel closed | done |
| Grid: bounded with an edge, patterned and labelled axes; magnetic grid cursor in sketches (lands exactly) | done |
| Icon choices in feature panels (extent, direction, result, hole type, primitive) | done |
| Mouse: middle pan, Shift+middle orbit, wheel zoom, double middle click fits; FreeCAD's navigation picker hidden | done |
| 70 new icons from `tools/icongen.py` | done; **approval pending** with the rest |

## UI round 3 (owner, 2026-10-10)

| Item | State |
|---|---|
| Blue sketch lines (edited, being drawn); drawing tools stay on | done |
| Radial menu with fixed places (left = Delete), also inside sketches | done |
| Delete command: sketch elements, history items, faces (healed), whole bodies (one undo step) | done |
| Line command from anywhere (picks a plane first when not sketching) | done |
| Hover shading and click selection of a sketch's closed areas; Extrude uses the clicked areas | done |
| Extrude arrow drags (it now takes the mouse before the region picker under it) | done |
| Older profiles switch to the dark look once | done |

## UI round 4 (owner, 2026-10-10)

| Item | State |
|---|---|
| Right drag opens the radial menu even while a sketch tool runs; a plain right click still ends the tool; fading gesture trail | done |
| See-through radial menu (guide ring, hovered slice, chips) | done |
| Snapping only near grid points; existing sketch points pull first | done |
| Polyline with typed lengths and angles (chained line tool) | done |
| Polygon inscribed and circumscribed as two tools | done |
| Kovač's toolbar rows restored over older profiles (the dist looked different) | done |
| Grid fades out at its edge; short Z axis | done |
| Shading: world light + softer headlight; fixed a bug that drew all parts unlit since the grid arrived | done |
| Lighter dividers between ribbon groups | done |
| On-view dimension boxes styled to the theme | done (placement is FreeCAD's) |

## UI round 5 (owner, 2026-10-11)

| Item | State |
|---|---|
| One snapping rule for all sketch tools, face points (hole centres, placement) and the extrude arrow; checked tool by tool in the GUI test | done |
| Snap marker (square, side ticks, centre dot; yellow = point, teal = grid) | done |
| Right click while drawing no longer leaves FreeCAD's sketch menu open | done |
| Duplicate viewport handlers (flaky hover/selection) fixed | done |
| White major lines removed from the sketch and ground grids | done |
| Ground grid follows the view (effectively infinite); no flicker at z = 0 | done |
| Plane picker: outlined rounded squares on the camera side, hover light-up, click flash | done |

## Bug-fix pass (2026-10-11)

A batch of fixes and small features from the owner's own testing, worked item by item.

| Item | State |
|---|---|
| Ground grid vanishing at some camera angles: Coin's own near/far auto-clipping starved by the same bounding-box exclusion that keeps "fit all" from zooming out for the grid | fixed; GUI regression test sweeps several tilts |
| Hovering a command shows its shortcut; shortcuts added for the commands used most (sketch, the five Create ops, Fillet/Chamfer/Shell, Finish Sketch, Grid) | done; dropdown-nested and structurally-generated commands (primitives, patterns, reference geometry, the 26 views, the 9 filters) left without one, same reasoning as the existing shortcut-free commands |
| Midpoint constraint (select a point and a line/arc, it snaps to the midpoint and stays there); mouse snapping lands on line and arc midpoints too, in sketches and on 3D faces | done (`Kovac_ConstrainMidpoint`, own icon); tested headless and in the sketch ribbon end to end |
| Extrude (and Revolve, Sweep, sharing the same code) assumed a multi-region sketch meant "all of it": picking none silently combined every region. Now requires a pick only when there is more than one to choose between; a single-region sketch still needs none, so the common one-click case is unchanged | fixed in the shared profile resolver, not per-command; the panel's own region picker shows the same "nothing chosen" state live, so a click is never a surprise |
| Panel number fields (Pattern counts, Move/Scale offsets, ...) only took the locale's own decimal point; the other character wasn't just rejected, it silently vanished and ran the digits together ("3.5" became 35 under a comma locale) | fixed (`editor.DoubleSpinBox`); the sketch/feature value fields (`ValueField`, FreeCAD's own quantity parser) were already locale-flexible and needed no change |
| Cancel on a feature panel could still leave the feature behind -- found the real trigger: opening a second panel (clicking another command) while a first one was still open crashed outright, because the new panel's own open could abort the transaction the first panel's feature was just created under, out from under its own open panel | fixed (`editor.close_current`, run before a new transaction opens or feature is created, not after); reproduced the exact crash with the fix reverted, confirmed it's gone with the fix back |
| Delete/Backspace did nothing in the browser or the timeline, with one or many items selected -- neither widget had any key handling at all; the browser's own right-click Delete, and the timeline's single-item one, only ever acted on the one row clicked, never the rest of a multi-selection | fixed (`tree.delete_selected`, `timeline.delete_selected`), one undo step either way, later history items removed first so a freshly-selected dependent doesn't block its own batch |
| "Group selected" in the timeline did set one shared group on every picked feature -- correctly, checked directly -- but every member showed only a bare "▾", identical whichever group it was in or whether it was grouped at all, reading as "each on its own" rather than "these belong together" | fixed: every member now names its group and shares a tint, so the group reads as one row of things even without collapsing it |
| Selecting a face only shaded that one face, not the body it belongs to | fixed: a translucent wash over the whole selected shape (`overlay.shape_node`, a selection observer in `navigation.py`), under FreeCAD's own crisper per-face highlight, not replacing it |
| Sketch Offset ("in sketch mode, offset does not work") | investigated at length (single edge, closed 4-edge profile, both through a real simulated click reaching FreeCAD's own tool, not a shortcut) -- works correctly both times; could not reproduce a defect |
| A brand-new feature that failed outright (OK clicked on something already broken) stayed in the history forever, same as one broken later by an upstream change | fixed: OK on a *new*, already-failed feature now discards it, same as Cancel; editing an *existing* feature into failure still keeps it, Status set, shown red -- that part already worked |
| Materials: drag and drop a material from its panel onto a body | added, as well as (not instead of) the existing select-bodies-then-double-click; works in the viewport |
| Split Body only ever worked with a flat plane or face; a cylindrical or spherical face did nothing (silently fell through to "pick a flat face") | fixed: a cylindrical or spherical face now splits by the whole analytic surface, not just the clicked patch, the same way a plane already bounds a half-space; a cone or freeform face still needs a flat face or a plane -- no closed-form equivalent for those -- and says so clearly rather than failing silently |
| Pattern along a curve; 3D curves | added as one feature (Pattern's third Type, "Path"): evenly spaced along a sketch curve *or* picked 3D edges -- the same dual path input Sweep already has -- with instances rotated to follow the local tangent when Align is set. This is my own reading of "allow for 3D curves" given its place in the list right after "pattern on curve"; flagged in case a different, dedicated 3D-curve capability was meant instead |
| Fillet and Chamfer "need grab arrows like in Fusion" | added a drag arrow for the default value (Fillet's Radius, Chamfer's Distance), at the first picked edge's midpoint, outward along the bisector of its two adjacent faces -- the same arrow-plus-floating-field manipulator Extrude and Face Pull already use, now in `manip.ARROWS`. Scoped to the one shared value per group, not a separate handle at every point along an edge for a continuously *variable* radius along its length -- that's a materially bigger feature (a different OCCT fillet API entirely, per-point radius storage, one handle per point) and still not built; this is the everyday case the request names, not full Fusion parity |

## Bug-fix pass, round 2 (owner re-test, 2026-10-11)

The owner tested round 1 and reported several items still not right, plus one new regression. Worked item by item against that feedback.

| Item | State |
|---|---|
| Round 1's grid-clipping fix (`_clip_for`) sized both near and far planes from one bounding sphere around model *and* grid together -- a far-off grid corner could inflate that sphere enough to push the *near* plane past the model itself, slicing it off (seen live in the owner's own screenshot) | fixed: near and far are measured separately, each bounding-box corner's depth along the camera's own view direction (not a sphere radius) -- near from the model's corners alone, far from model-and-grid corners together. Checked against a small object positioned well away from the origin (the owner's own reproduction hint) at both close and far zoom, including FreeCAD's own orthographic "fit all" occasionally placing the camera essentially on the model's own bounding-box corner for a small object -- even there the residual overlap is the clamp floor itself (a thousandth of a millimetre), not a visible clip |
| "Better but not perfect" on the grid's edge, suggested changing opacity instead of a hard cutoff | the grid already faded, but toward one flat colour approximating the viewport's own top-to-bottom gradient background -- a visible seam wherever that average didn't match the real gradient behind it, worst at a shallow tilt. Switched to real transparency (`SoMaterial`, per-vertex, fading to fully transparent at the edge) so it matches whatever is actually behind it, gradient included |
| Hovering a sketch tool showed no shortcut, and the keys themselves did nothing | sketches stay in Kovač (no switch to FreeCAD's sketcher workbench), so FreeCAD never built the sketcher's own actions -- which is where it registers default keys ("G, L", ...). Kovač's menu now lists the sketch tools, the same way it already does for its own commands, so the keys exist; the sketch ribbon takes each key over from FreeCAD's action (two actions on one key would fire neither). Kovač's own Polyline and Polygon around a circle got keys too (G, U and G, P, C). GUI test: every sketch tool's tooltip names its key, and typing G, L starts the line tool |
| Group select in the browser did nothing | no row could be selected by mouse at all, one or many: the tree widget was also FreeCAD's selection observer, and that observer's callbacks are named `setSelection` / `clearSelection` -- the same names as Qt's own item-view methods, which they silently replaced. A click asked Qt to select the row, Qt called our re-sync instead, and that read back FreeCAD's still-empty selection. The observer now lives on its own small object. Round 1 missed it because its test selected rows in code (`setSelected`), never by clicking; the GUI test now clicks and Ctrl+clicks |
| Grouping features still looked like each feature was its own group | every member was still its own item, each labelled with the group name. A group is now one item: a new group shows closed, as a single "▸ Name (n)" item; opened, it is one "▾ Name" header in front of its members, which share its tint and carry no label of their own. Double-click toggles; a selected group item stands for all its members (group again, delete). GUI test picks the features with real Ctrl+clicks |
| Cancel on a new feature's panel still left the feature | FreeCAD runs every toolbar click and shortcut inside its own automatic transaction and commits it when the command returns, which committed the panel's step the moment the panel opened. Cancel only worked when a command was called directly, as the tests did. The panel now asks for its step to persist past the command (`App.setActiveTransaction(name, True)`). The panel window's close button now also means Cancel. Checked through FreeCAD's real command path: Cancel, Escape and the close button all leave nothing behind |
| Grid gone outside sketches after the transparency change | Coin delays see-through shapes to a sorted pass that dropped the grid, because the grid is kept out of the scene bounding box. It now blends in place |
| Models far from the origin still sliced | fit-all leaves an orthographic camera at the model's edge, and orbiting swings it inside the part, so any near plane in front of the camera slices it. Orthographic near planes may be negative, so the near plane now sits behind the model. Kovač's clipping also stays on with the grid off and in sketches, sized from the whole scene. Checked by rendering after a real orbit 800 mm from the origin, before (sliced) and after (whole) |
| Arrows: grow only along their length, bigger by default; fillet and chamfer arrows point the right way | head and shaft are fixed in screen size and only the length follows the value. On an outside edge the arrow points into the part, and on an inside edge out into the corner. Revolve has no drag arrow yet (an angle needs a curved handle), and a fillet's extra radius groups still have no arrows of their own |
| Split by a three-point plane; sketch on reference planes | the geometry already worked (now tested headless for a three-point plane). A reference plane clicked in the 3D view arrives as "Face1" and was taken for a body face, so Split, Mirror and Sketch ignored it. All three take the plane now |
| 3D curves | new "3D curve" (G, 3, D), in the Sketch group and the sketch ribbon. In a sketch, its unconstrained B-splines leave the sketch and become 3D curves. With a curve selected it opens for editing, and with nothing selected a new one is placed across the view. Every control point is a handle that drags in the plane facing the camera, so turning the view and dragging again moves it in another direction. A small panel adds and removes points and closes the loop. Sweep and Pattern take a curve as their path. Headless and GUI tests cover the conversion, a drag out of the plane, and a sweep along a non-planar curve |
| Grid still cut off in some views | with no model (or a small one) the near clip plane sat just in front of the camera and cut away the half of the grid nearer the viewer. The near plane now takes in the grid's corners too |
| Arrows wider and larger; an arrow pointing into the part starts further out | head 16 px wide by 46 px, a 4 px shaft, glowing in the accent colour. When it heads into material (a fillet on an outside edge, a cut) the shaft starts 90 px outside the part |
| Move: its own group between Sketch and Form, with a triad | arrows along X, Y and Z, plus a turning handle about each axis. Distances snap to half the grid step and angles to 5 degrees, Alt turns snapping off, and the value shows by the cursor. What is selected decides what moves. Bodies move as a history feature about their own centre, with x, y, z and turn X, Y, Z in the panel. A construction plane is set free where it is dropped. Points and lines of a sketch slide in its plane and turn about its normal. With the Faces filter on, a face pushes or pulls along its normal (Face Pull). Moving faces sideways or tilting them, and moving the edges of solids, are not supported. Shortcut Shift+M |
| Face tilting | Move Face, made by Move with the Faces filter on. A flat face pushes, pulls and tilts: the part's material over the face is rebuilt up to the face's new plane, and the faces around it stretch to meet it, staying straight along the old normal (exact for square sides, approximate for drafted ones). A hole or boss slides sideways and tilts, and a hole open at an end stays open there. Other curved faces (cones, spheres, freeform) are not supported. Also fixed: the selection wash showed a body's old shape after a change |
| Sketch points moved in 3D | in a sketch, Move has all three arrows and turning handles. Sliding in the plane and turning about its normal stay in the sketch. The first drag out of the plane takes the picked geometry, and every line or curve whose end touches a moved point, out of the sketch as 3D curves, so corners stay joined. Arcs, circles and splines keep their exact shape (knots and weights carried over), and later drags keep moving them in 3D. Sketch points (not lines) cannot leave the plane yet |
| Extrude arrow | one fixed size on screen, sitting on the face being extruded: out into free space it starts on that face, into material (a cut) it comes in from outside with its tip on it. Drawn over the model and grabbed anywhere along its length, so it works when it lies over the body; dragging moves the value from where it was grabbed, with no jump. Same for Face Pull, Fillet and Chamfer arrows |
| Move: what to move | the Move panel opens with a "Move" drop-down: Bodies or Faces. A clicked face starts as a bodies move (its body); choosing Faces turns it into a move of that face (tilt, push, pull), and Bodies turns it back. Construction planes and sketch elements keep their own Move session |
| Extrude arrow drag | the arrow follows every mouse move at once (a redraw of the arrow alone); the solid's preview now runs every 60 ms during a drag instead of only once the mouse stops |
| Move: typed amounts | the triad shows a field by the last handle used: the length moved along an arrow, or the angle turned about a handle. Click a handle (or finish a drag) and type a value, Enter moves it exactly there, as one undo step. Enter in that field never confirms the panel |
| Move: Points | the drop-down has Points: sketch points and lines, picked inside a sketch or clicked on a sketch in the view, move with the triad (a corner takes every end lying on it). Picking other points moves the triad over to them; the window's drop-down switches back to Bodies or Faces |
| Sketch offset of B-splines | the sketcher's own Offset added nothing for a B-spline or an ellipse (its result is an offset-curve type a sketch can't hold). Offset in the sketch ribbon (Z, T) now opens Kovač's own for those: a distance field (negative or "Other side" flips), a drag arrow on the curve, a live preview; Enter or OK adds it as one undo step. Lines and arcs stay exact; other curves become a cubic B-spline within 1e-5 of the size off the true offset, control points shown. Joined curves offset as one chain, trimmed at inside corners, rounded at outside ones, ends constrained coincident. Selections of only lines, arcs and circles still go to the sketcher's Offset |
| GUI tests in segments | `tests/gui_m2.py` runs as segments (bracket, curve3d, move, offset): `KOVAC_SEGMENTS=move,offset py tests/run_gui.py gui_m2.py` runs only those |
| Offset waits for a pick | Offset with nothing selected opens its panel and waits: the curves clicked next are offset (Ctrl adds more), instead of "Select the curves to offset first." Also fixed: hovering a sketch with no shape (only construction lines, or a failed solve) stopped view interaction with "shape is invalid" |
| Offset / Move picks by clicking | two causes: a drawing tool left running (tools stay on after each shape) kept taking the clicks -- Offset and Move now end it first; and a real click in a sketch selects ";g1.edge1" (unresolved), which the picking ignored -- sketch picks now read resolved names ("Edge1"). Tested with a spline tool left on, then a real click on the curve |
| Offset corners: round or sharp | the Offset panel chooses how an outside corner closes: Round corners (an arc about the old corner: every point exactly the distance away) or Sharp corners (the intersection join: neighbours carried on until they meet -- lines and arcs lengthened, a spline continued straight along its end tangent -- so lines and curves move parallel and corners stay corners; falls back to round where they would meet absurdly far out). The choice carries over. Kovač's Offset now handles every selection, lines and arcs too, so there is one tool |

## Next
Milestone 3 — drawings, in the same look and logic.

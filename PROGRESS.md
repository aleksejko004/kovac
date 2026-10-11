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

## Next
Milestone 3 — drawings, in the same look and logic.

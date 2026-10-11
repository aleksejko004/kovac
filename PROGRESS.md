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

## Next
Milestone 3 — drawings, in the same look and logic.

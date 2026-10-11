# Milestone 2 report — Sketching and part modeling

**Date:** 2026-10-10 · **Engine:** FreeCAD 1.1.4 (portable binary, Windows 11) · **Kovač:** 0.1.0 (version bump after your review)

## Decisions you need to make

1. **ADR-0002.** I treated "implement the second features" as accepting the proposed hybrid model, and wrote it up as Accepted. ADR-0003 records how references actually work. Say so if you meant otherwise.
2. **UI direction.** You asked for a more direct, less FreeCAD-like experience and said you would describe it, including "a big button on the left side". This round shipped the parts you named: a see-through browser, a draggable cube, and a grid with snapping. The big button waits for your description.
3. **Interaction-cost target (≥ 40 % fewer) is not met.** The estimate is about 11 % fewer than stock (table below). The largest wins would come from inline sketch dimensions and a one-click hole. Do you want those next, or the UI redesign first?
4. **Regeneration budget (< 1 s) is not met** on a 50-feature part (measured below). Allowed next steps: cheaper validity checks, or a core patch for background regeneration. Which do you prefer?
5. **Still open from M1:** brand accent, the first 12 icons, cube variant, bundling Inter, GPL executables in the build.

## What was built

| Area | Delivered |
|---|---|
| **History model** | One linear history per document. Every feature reads the previous feature's state (all bodies, with face tags) and writes its own. Body objects show the tip. A failing feature passes its input through and explains itself in plain words. Rollback marker, insert at the marker, reorder with dependency checks, suppress, delete with pruning, edit in place. |
| **Reference layer** (ADR-0003) | Faces are tagged by the feature that made them. Later operations inherit the tags. Edges and vertices are named by their faces. Resolution is a unique match, else the clearly nearest candidate, else an explicit "Missing reference". It is never a silent guess. |
| **Sketching** | Sketch on an origin plane (picker overlay) or any flat face or datum plane. The camera turns to face it and the grid snaps. A **✓ Finish Sketch** button returns the camera. Regions are computed from all curves (half-edge traversal), so overlapping shapes give pickable regions. Drawing uses FreeCAD's sketcher tools inside our bar. |
| **Create** | **Extrude:** regions or flat faces; distance, to face, or through all; one side, two sides, or symmetric; start offset; taper; thin. **Revolve** about X/Y/Z, a sketch line or an edge, optionally symmetric. **Sweep** with an optional Frenet frame. **Loft**, ruled or closed. **Primitives:** box, cylinder, sphere, cone, torus. **Hole:** simple, counterbore, countersink and tapped; ISO metric M2–M20; ISO 273 clearance classes; centres from clicks or sketch points; thread metadata. **Thread:** cosmetic. |
| **Operations** | Join, Cut, Intersect and New body, inferred and overridable. A profile on a body face pulled outward joins; pushed inward, it cuts. Touching nothing makes a new body. The panel shows "Join (auto)". |
| **Modify** | **Face Pull** (context-sensitive). **Fillet** and **Chamfer** (equal distance, two distances, distance + angle), each with several radius groups, tangent chains and a whole-body option. **Shell**: open or closed, inside or outside, and it survives walls as thick as a fillet. **Draft**. **Delete Face** with healing. **Combine**: join, cut or intersect bodies. **Split Body**. **Move/Copy** and **Scale**, recorded. **Mirror**. Rectangular and circular **Patterns** of features, bodies or faces, with skipped instances. |
| **Reference geometry** | Planes: from a face, offset, at an angle about an edge, mid-plane, three points. Axes and points. Each takes one or two clicks with no attachment dialog. |
| **Panels** | Every feature edits in a floating, non-modal panel with live preview. Value fields take units, expressions and parameter names (with autocomplete), and arrow keys step the value. Point inputs take clicks straight from the viewport. The arrow manipulator has a floating value field. OK commits one undo step; Cancel leaves nothing behind. |
| **Timeline** | Interactive: drag the rollback marker, drag to reorder, suppress, edit, group, and error/warning states. Hovering a feature highlights its faces. |
| **Parameters** | User parameters plus every feature dimension, searchable. Favourites. Promote a dimension to a named parameter. Expressions. |
| **Inspect** | Mass properties, interference, section (a draggable plane, saved as a toggleable analysis), draft analysis, materials and appearance (a library with physical properties). |
| **This round's UI changes** | **Browser:** a see-through panel floating over the left of the 3D view. It is sized to its rows and foldable, with an icon per item and an eye per row and folder (no checkboxes). **Cube:** dragging it orbits about the model; a plain click still turns to that face. **Grid:** a ground grid that rescales with zoom (1-2-5 steps). Clicked points snap to half a grid step, or to a face's centre when the click is near it, and never off the clicked face. Sketches use the sketcher's own snapping grid. Toggle it in the view bar. |

## Demo, step by step

1. Run `py tools/fc.py gui`. Choose **New design**.
2. **Sketch** → click the XY plane. Draw a rectangle, then **✓ Finish Sketch**.
3. **Extrude** → type `5` and press **OK**. The panel shows "New body (auto)".
4. Click the top face, then **Sketch**, and draw the wall profile. Finish, then **Extrude** up 35. The panel shows "Join (auto)".
5. Click the base top face, then **Hole**. Click two centres; they snap to the grid. Tick **Through all**, then **OK**.
6. Click the inner bend edge, then **Fillet** `3`.
7. In **Parameters**, change `Thickness` from 5 to 8. Everything regenerates, and the holes and fillet stay put.
8. Drag the timeline marker to the start, then back.
9. Drag the cube to orbit, then click a cube face. Fold the browser and toggle a body's eye.

## Test results (2026-10-10)

| Suite | Result |
|---|---|
| Headless (`py tools/fc.py cmd tests/run.py`) | **127/127 pass.** Includes every feature against hand-computed geometry, the history model, the reference layer, a **23-scenario toponaming torture suite** and **32 golden parts**. |
| Torture scenarios | Extrude length change, sketch resize, upstream notch, extra side face, sketch redrawn identically and differently, hole upstream of a fillet, pattern count 4 → 6 → 4, pattern instance removed, chamfer reordered before shell, extrude flipped, fillet radius under a shell, region picks stable while the sketch grows, face pull and hole follow their face, fillets inserted before a shell, split then fillet one half, mirror-join then fillet a mirrored edge, cut tool resized under a chamfer, draft through a length change, revolve angle under a chamfer, and an ambiguous split face that is **reported**, not guessed. |
| Golden parts | All seven named in the brief (L-bracket with hole pattern and fillets, turned shaft, shelled loft duct, swept handle, patterned flange, plate with M3–M8 tapped holes, drafted shelled enclosure with ribs) plus 25 more. Each is checked for volume, area, bounding box, face and edge counts, and validity. |
| M2 GUI end to end (`py tests/run_gui.py gui_m2.py`) | **20/20 pass.** It builds the L-bracket purely through the UI, changes thickness 5 → 8 with fillet and holes surviving (volume matches the reference), places hole centres by clicking with grid snap, checks rollback, checks that panels never block orbiting or the tree, and runs the benchmark tasks. |
| M1 GUI acceptance (`py tests/run_gui.py`) | **32/32 pass.** Updated for the history model. It now also checks cube drag-orbit, that a cube drag selects nothing, and that a cube click still snaps to a view. |
| Branded build (`py tests/run_dist.py`) | Pass. Rebuilt today. |

## Measured performance

Measured today with the machine under heavy background load (CPU at 59 % before the runs). Bare FreeCAD started in 23–25 s, against 9.9 s during M1, so absolute times are about 2.4× worse than in M1.

| Budget | Measured | |
|---|---|---|
| Open a 50-feature part < 3 s | **1.22 s** (plate + 45 holes + 4 fillets; reopened shape identical) | met |
| Commit regeneration < 1 s | Edit at the end of the history: **2.49 s**. Edit at the start (all 50 replay): **31.4 s**. | **not met** |
| Start to usable < 6 s | Warm 19.5–20.6 s, first 18.3 s. Under the same load bare FreeCAD took 23–25 s. | not met (load; see M1) |
| Hover < 16 ms | 0.33 ms | met |
| Radial < 50 ms | median 54 ms, max 65 ms (M1: under budget) | not met under today's load |
| Search < 50 ms | 25 ms worst over 315 commands | met |
| Manipulator preview ≥ 30 fps | not measured yet | — |

Where regeneration time goes on the 50-feature part (profiled):

| Share of time | What |
|---|---|
| ~30 % | Kernel validity checks. Faces with 45 hole loops are expensive to check. |
| ~20 % | Booleans |
| ~8 % | Fillets |
| ~17 % | Our tag inheritance, already cut from 47 % with an identity fast path |
| rest | Contact tests and splitter removal |

The timeline no longer re-checks every feature's validity on each refresh, which would have cost seconds per refresh. Features now record whether healing failed while they regenerate.

## Interaction-cost benchmark

Our counts are recorded by the GUI test. The stock counts are **estimated from FreeCAD 1.1's documented Part Design workflow, not scripted**; a scripted stock run is still to do.

| Task | Kovač clicks / keys | Stock (estimated) clicks / keys | Notes |
|---|---|---|---|
| Sketch a 40 × 20 rectangle on XY | 6 / 6 | 6 / 6 | Stock: create sketch, pick plane, OK, rectangle, corner, type both sizes, close |
| Extrude 10 mm | 2 / 5 | 3 / 2 | Our test types `10 mm`; a bare `10` (default unit) would be 2 keys + Enter |
| Fillet 4 edges at 2 mm | 3 / 2 | 4 / 1 | Both pick the top face for its 4 edges |
| M5 tapped hole | 6 / 0 | 10 / 0 | Stock needs a sketch with a point first |
| Shell at 2 mm | 3 / 0 | 4 / 1 | Our default wall is 2 mm |
| **Total** | **33** | **37** | **≈ 11 % fewer; target ≥ 40 %** |

## Limitations

- **Not built yet from §3.6/3.7:**
  - Rib, Web, Emboss/Deboss
  - coil and pipe primitives; primitives by click-drag (today: placed by value)
  - Split Face, Replace Face, Align, pattern along a path, point-to-point move
  - variable-radius fillets with on-edge handles
  - sweep guide rail, twist and scale; loft rails, centerline and end conditions
  - the New Component operation
  - modeled threads (cosmetic only)
  - curvature/zebra analysis
- **Sketching** uses FreeCAD's sketcher tools inside our bar. Inline dimension input and our own inference are not built yet; they are the biggest lever on the benchmark.
- **The validity check** after booleans covers only the faces an operation made, plus closed shells (`model._valid`). It can miss a shell orientation flip along old/new seams. Fillet, shell and the other modify features still run the full check.
- **Hole on a thin wall:** an M5 hole in a 2 mm wall of a 10 mm-high block cannot be shelled at 2 mm, because the wall around the hole would stick out of the part. This is correct behaviour, so the benchmark hole sits on the top face.
- **Screenshots** in the GUI tests paste the 3D render over the window, so the orientation cube is missing from the saved images. It is there on screen.

## Deviations from the brief

- **Reference layer:** FreeCAD's mapped names are not stored (ADR-0003), because they are re-hashed on every recompute and never decide a match.
- **Draft** uses pythonocc-core (LGPL-3.0), which ships inside the FreeCAD build, because FreeCAD's Python API has no draft-angle operation. This adds no new licence; `THIRD_PARTY.md` is updated.
- **Interaction benchmark:** the stock side is estimated, not scripted.

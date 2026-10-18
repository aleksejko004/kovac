# ADR-0004 — Components and joints

- **Status:** Accepted 2026-10-12 (owner: "build it as you see fit"); first version built, see "Built so far". Owner decisions already taken: components live in the same design by default, with other files linked in later (plan step 5); positions that joints drive stay out of the history; drawings wait, assemblies come first.
- **Plan:** `docs/design/assemblies-plan.md`
- **Prototype:** `prototypes/adr0004_assembly.py` (results in `prototypes/adr0004_results.json`); run with `py tools/fc.py cmd prototypes/adr0004_assembly.py`
- **Builds on:** ADR-0002 (one history per document; bodies are what the user sees), ADR-0003 (references)

## Context

ADR-0002 promised "documents → (optional) components → bodies". FreeCAD 1.1.4 provides the pieces:
- `App::Part`: a container with its own placement;
- `App::Link`: an instance;
- the Assembly workbench, whose `Assembly::AssemblyObject`, `JointObject` and the bundled solver (OndselSolver 1.0.1, LGPL-2.1) work headless.

Kovač's bodies are not FreeCAD bodies, though: they are the results of one document-wide history, shown by `KovacBody` objects. The prototype had to answer:
1. Can those bodies sit in movable containers?
2. Can they be instanced?
3. Can they be jointed?
4. Do joints survive edits?
5. Is solving fast enough to drag?

## Prototype results (FreeCAD 1.1.4, headless)

**E1, frames.** A Kovač body inside an `App::Part` component:
- its shape stays in the component's own coordinates;
- moving the component moves only what is shown;
- a fillet added to the body afterwards computes normally.

All three checks passed.

**What E1 found:** a component (a FreeCAD `GeoFeatureGroup`) pulls in everything its members link to with local scope. Adding a body therefore dragged the **whole history** into the component, producing "out of scope" and "graph must be a DAG" errors. The fix is to make the body's `Tip` an `App::PropertyLinkGlobal`. Existing files need a migration on load.

**E2, instances.** An `App::Link` to a component:
- shows the same body at the link's placement;
- follows edits to the definition;
- resolves a pick through the link to the real Kovač body, and `model.pick_ref` works on it.

All checks passed.

**E3, joints through edits.** The setup:
- a plate made by one extrude, with two holes made by cut extrudes;
- a pin component in one hole and a linked second pin in the other, both Revolute joints;
- the edits run one after another, in the order listed.

The comparison: (a) FreeCAD's joint as it is (element names), against (b) Kovač joint origins, with references re-resolved at every regeneration and written into the joint with `Detach1/2 = True`.

| edit | (a) FreeCAD names | (b) Kovač references |
|---|---|---|
| as built | both pins in place | both pins in place |
| holes moved and enlarged (dimensions) | in place (names tracked: Edge15 ↔ Edge16 swapped) | in place |
| a hole cut inserted upstream (edges renumber) | in place | in place |
| a fillet inserted upstream | in place | in place |
| saved, closed, reopened, holes moved again | in place | in place |
| first hole's cut deleted | that joint flagged invalid | that joint flagged "Missing reference: the edge it was attached to is gone" |
| second hole deleted from its sketch and drawn again elsewhere | pin follows the new circle without saying anything | joint flagged missing (the ADR-0003 rule: a redrawn sketch is new geometry) |

**What E3 found:**
- **FreeCAD's naming is better than expected.** FreeCAD 1.1's own element naming tracked Kovač bodies through every ordinary edit, including save and reopen. The plan's "main risk" (joints break on edits) is therefore smaller than feared.
- **Kovač had a naming bug, now fixed.** Before commit `af023d9`, Kovač's references failed this test. A round hole cut by an extrude got a throw-away hash name, because the test point used to match a curved face lay off its surface. That is fixed, with a new torture test.

**E4, solve time.** The setup:
- a chain of N linked copies of one component, each jointed to the one before;
- a "drag" is ten solves, each after a 0.5 mm nudge of the free end, as each frame would do;
- "verified" means the ground didn't move and every joint's two frames meet.

| joints | N | first solve | drag solve (median / max) | verified |
|---|---|---|---|---|
| Fixed | 5 / 20 / 50 | 2.5 / 8.1 / 36 ms | 1.8 / 9.0 / 34 ms (max 37) | yes |
| Revolute, starting untilted | 5 / 20 / 50 | 2.8 / 18 / 174 ms | 1.7 / 8.5 / 29 ms (max 32) | yes |
| Revolute, starting tilted 10° per part | 5 / 20 / 50 | 8 / 260 / 3825 ms | 2.9 / 68 / 2735 ms | **no** |
| Revolute, each part snapped into place when jointed | 5 / 20 / 50 | 1.7 / 4.2 / 11 ms | 1.7 / 8.1 / 28 ms (max 30) | yes |

Writing all joint origins from references takes about 1.3 ms per joint, once per regeneration (not per drag frame).

**What E4 found:**
- **The solver can report success on a wrong answer.** From tilted starting positions it returned 0 ("solved") with the grounded part rotated by 90°.
- **Pre-placing fixes it.** Snapping each part into place when its joint is made (`P_moving = P_other · Placement1 · Placement2⁻¹`) gives correct results at every size.
- **There is no Python drag API.** FreeCAD's incremental drag solver is C++ only. A full `solve()` per frame fits the 30 fps budget up to a 50-joint serial chain, the worst case, so no core patch is needed.

## Decision

1. **Components.**
   - **Container:** a component is an `App::Part` inside one `Assembly::AssemblyObject` per design, created when the first component is. The assembly is machinery (`tree.role`); the design is the top component.
   - **Coordinates:** bodies stay results of the one history (ADR-0002). A body's shape is in its component's coordinates, and the component's placement is applied for display, picking and measuring.
   - **Global link:** `KovacBody.Tip` becomes a global-scope link, migrated on load.
   - **Membership is history state.** The feature that makes a body records the active component. Moving a body to another component is a history step carrying a fixed transform, so undo, rollback and reorder stay consistent.
2. **Instances** are `App::Link`s to a component; "Copy" makes an independent component.
3. **Joints**
   - **FreeCAD objects:** each joint is a FreeCAD `JointObject` in the assembly's joint group, referenced the FreeCAD 1.1 way: `[moving component, ["Body.Edge3", …]]`, with `Detach1/2 = True`.
   - **What Kovač stores:** for each side, the component, the body, an ADR-0003 reference, the snap kind (face centre, circle centre, edge midpoint, vertex, cylinder axis) and an offset.
   - **At every regeneration:**
     1. resolve each reference;
     2. rebuild the frame from today's geometry;
     3. write today's element name and frame into the joint;
     4. solve.
   - **If a reference is broken:** the joint is flagged with the reference's own words, and the component stays where it was.
   - **Why Kovač references, when FreeCAD's names did as well in E3:**
     - one rule for every feature and joint;
     - plain-language messages;
     - snap kinds FreeCAD doesn't offer;
     - no silent following of a redrawn sketch.
     If the owner prefers FreeCAD's names, points 1, 2, 4 and 5 still stand.
4. **Solving.** The solver is FreeCAD's `AssemblyObject.solve()`.
   - **Pre-placing:** making or editing a joint first snaps the moving component into place.
   - **Checking:** after every solve, Kovač checks that grounded components didn't move and that every joint's frames meet. A solve that fails the check is undone (`undoSolve`) and named in the status bar ("These joints can't all be satisfied: …"). It is never shown silently wrong.
5. **Positions are not history** (owner decision 2). Free moves and joint-driven motion change component placements in one undo step each, but never add a timeline item. Creating, editing or deleting a joint is a history step.

## Consequences

- **No new dependencies or core patches.** OndselSolver (LGPL-2.1) is already bundled and is now used directly.
- **Code that assumes world coordinates must learn component transforms:**
  - viewport picks, hole and point placement on faces;
  - measure, section and interference;
  - the Move tool.
  Every one of these is a Step 1 test.
- **Not tested yet** (planned):
  - picking through nested components in the GUI (selection paths);
  - undo of a solve;
  - storing Kovač joint data in the file;
  - external files (step 5).

## Alternatives considered

- **One history per component.** Simpler instancing, but it breaks ADR-0002's single history and the owner's "one file, one history" choice. Not chosen for internal components. External components (step 5) are naturally their own documents with their own history.
- **FreeCAD's element names as the joint's truth.** Works for ordinary edits (E3), but follows a redrawn sketch without saying so, and gives FreeCAD's messages instead of ours. Kept as the fallback if the owner prefers it.
- **Our own solver.** No reason: the bundled one is fast enough once it starts from a pre-placed state and Kovač checks its answers.

## Built so far (2026-10-12)

- `components.py`: the design assembly, components and instances, frames, picks through paths,
  global-scope links with a migration for older designs, deleting a component.
- `joints.py`: snaps, joint origins, writing them into FreeCAD's joints, snapping parts into
  place, the solve check, ground and drag.
- `assemble.py`: the Assemble ribbon group (New Component, New Instance, Joint, Drag, Ground).
- `move.py`: Move with "Components".
- Moving bodies between components (`components.move_bodies`, browser "Move to"): a Move step
  by the fixed difference between the two components' placements keeps them where they are
  shown; deleting a moved component uses the same step. Copy Component (`copy_component`): a
  history step that copies the bodies into a new component.
- Joint limits and driving (`joints.position`, `set_limits`, `set_position`, `clamp`): a turning
  or sliding joint's position is side 2's frame against side 1's, counted from the jointed
  position. Limits are Kovač's own properties (FreeCAD's limit properties stay off, its solver
  counts from another zero); the solve check rejects positions outside them, Drag clamps to
  them, and the Joint panel types, limits and plays the position.
- Tests: `tests/test_components.py` (16 headless tests) and GUI segment `assembly`.

Deviations from the decision above:
- **Joints are timeline steps** (`joints.JointStep`, a history item that changes no body). Rolled
  back before its step, or with the step suppressed, a joint is off and its parts move freely;
  deleting the step deletes the joint; double-clicking it opens the Joint panel; a joint's
  problem shows on its step. Creating or editing a joint is still one undo step.
- **No nested components yet.** New components always sit at the top of the design.
- **Sketches don't move with their bodies** between components: they stay where they were
  drawn, and the features built on them compute as before. A body with joints can't move to
  another component (its joints would have to follow it); delete the joints first.
- **A copy follows edits made before the copy step** (it is made from the original's history),
  like any copied body; features added to either one afterwards change only that one.
- **A seam is not a snap point.** A round face's seam edge, and the seam vertex of a circle, offer
  their face's snaps (axis, rim centres) instead of points nobody means to pick.

# Bodies, components and assemblies — plan (proposal, 2026-10-12)

Status: **proposal**; owner decisions 1–3 taken 2026-10-12 (see "Decisions needed"). Step 0 done, awaiting review: ADR-0004 (proposed) with the prototype's measurements. Nothing user-facing is built yet.

Sources, per the clean-room rules: FreeCAD 1.1.4's Assembly workbench and its bundled solver
(OndselSolver, both LGPL, already inside the build Kovač runs on), classical kinematics (the lower
pairs: revolute, prismatic, cylindrical, spherical, planar, helical — any mechanisms textbook),
ADR-0002's "documents → components → bodies", and the owner's own descriptions. No commercial
product, its documentation or its tutorials were consulted.

## Where we are

- **Bodies** exist (ADR-0002): result shapes of one document-wide history, shown by `BodyProxy`.
- The browser already has a `component` role (`App::Part`, `Assembly::AssemblyObject`) and a
  `joint` role, an "active component" shown in bold, and Components / Joints selection filters.
  Nothing yet creates components or joints through Kovač.
- FreeCAD's Assembly module works in this build, headless too (probed 2026-10-12): an
  `Assembly::AssemblyObject` solves; joint types available are Fixed, Revolute, Cylindrical,
  Slider, Ball, Distance, Parallel, Perpendicular, Angle, RackPinion, Screw, Gears, Belt.

## Vocabulary (what the user sees)

| Word | Meaning |
|---|---|
| Body | one solid (or sheet) the history makes — unchanged |
| Component | a named container with its own position: bodies, sketches, reference geometry and sub-components. It can appear several times (**instances** share one definition: edit one, all change) |
| External component | a component whose definition lives in another Kovač design file, inserted by link |
| Joint | how two components connect: a **joint origin** on each (a point and orientation snapped to geometry: face centre, circle centre, edge midpoint, vertex) plus a type that says what motion is left |
| Ground | a component held still; everything else is solved relative to it |
| Assembly | a design with components positioned by joints (the design itself is the top component) |

## Steps

Each step ends like a milestone: tests first for the logic, GUI segment checks, a short report,
then a stop for owner review.

### Step 0 — ADR-0004 and a spike — done 2026-10-12, see ADR-0004
- Prototype the three risky pieces headless: Kovač bodies inside `App::Part` containers (placement
  of the container moves the bodies; history features still compute correctly), instances via
  `App::Link`, and a FreeCAD joint whose references point at Kovač body faces, re-resolved through
  Kovač's reference layer after an upstream edit (FreeCAD stores element names like `Face6`;
  result: FreeCAD 1.1 tracks them through ordinary edits too, see ADR-0004).
- Measure solve time for 5 / 20 / 50 components (budget: drag at ≥ 30 fps, so a solve < 30 ms).
- Write ADR-0004 (component and joint model) with the measured results; add OndselSolver to
  `THIRD_PARTY.md` (bundled, no new download).

### Step 1 — Components inside one design — built, except dragging bodies between components in the browser (Move to menu instead)
- **New Component**: empty, or from the selected bodies. Double-click makes it active (bold);
  new sketches and features go into the active component and work in its own coordinates.
- Drag bodies between components in the browser; the history records it (one undo step).
- **Copy** (independent) vs **New instance** (linked, shares the definition).
- The Move tool gets "Components" in its drop-down (the triad moves a component's position,
  outside the history while it is not jointed).
- Tests: placement round-trips, features in a moved component, instance edits propagate, undo.

### Step 2 — Browser and timeline for components
- Nesting with eye toggles per component, isolate (show only this), rename, a component colour.
- Timeline shows the active component's features (or all, toggle), so a big design stays readable.
- Section and measure work across components (global coordinates).

### Step 3 — Joints
- **Joint** command: hover shows joint-origin glyphs snapping to centres, midpoints and vertices
  (same snap marker as sketching); pick one on each component.
- Type as icon buttons (`editor.IconChoice`): Rigid, Revolute, Slider, Cylindrical, Ball, Planar,
  plus Distance / Angle offsets and a flip. Live preview: the moving component jumps into place
  and the remaining motion is shown by an animated nudge.
- **Ground** a component (the first one is grounded automatically).
- Built on `Assembly::AssemblyObject` + `JointObject`, hidden as machinery; joint references are
  stored as Kovač references (ADR-0003) and written into FreeCAD's joint at each recompute, so
  an upstream edit that renumbers faces doesn't break the joint (or breaks it loudly with a re-pick).
- Tests: each joint type's remaining degrees of freedom, references surviving the toponaming
  torture edits, one undo step per joint.

### Step 4 — Motion
- Drag a component in the view: the solver keeps its joints (a hinge swings, a slider slides).
- Joint limits (min/max angle or distance), and "drive" a joint from its panel to animate it.
- Contact check while dragging (uses the existing interference tool), optional.

### Step 5 — External components
- Insert a component from another Kovač design file (link). Updates when that file changes;
  "Open" edits it in its own window; "Make internal" copies it in.
- Missing files show plainly in the browser with a "locate" action, never a modal wall.

### Step 6 — Assembly tools
- Bill of materials (FreeCAD's BOM object, Kovač's look): components, instance counts, materials.
- Exploded views (FreeCAD's view object), saved with the design, usable on drawings.
- Drawings (M3) get assembly views, balloons and a parts list from the BOM.

### Step 7 — Designing in context
- Sketch in one component on, or projecting, geometry of another (live link, or frozen copy).
- The reference layer learns cross-component transforms, so in-context references survive the
  referenced component being moved by a joint.

### Step 8 — Hardening
- Performance budgets with 50 components; torture tests for joints; a milestone report.

## Decisions needed (owner)

1. **One file or many by default?** *Accepted.* Proposal: components live in the same design by default
   (simplest to start, one history); external components (step 5) for parts reused across designs.
2. **Are joint-driven positions part of the history?** *Accepted.* Proposal: no. Positions are assembly state
   (moving a hinged lid shouldn't add a timeline step); creating or editing a joint is.
3. **Where does this go in the milestones?** *Decided: assemblies first; drawings (mostly built) wait.*

## How joints survive changes to the bodies

A joint never stores coordinates or FreeCAD element names as its truth. Each joint origin stores:

- a **Kovač reference** (ADR-0003, `{"b","k","t","s"}`) to the face, edge or vertex it was snapped to;
- the **snap kind**: face centre, circle/arc centre, edge midpoint, vertex, axis of a cylinder;
- an optional **offset and rotation** relative to that frame (the panel's Distance / Angle / flip).

At every regeneration, before the solve:

1. Resolve the reference (`topo`): the tag (`Hole002:wall:0`, `Extrude003:s:g2`, …) finds today's
   face whatever its index is now.
2. Rebuild the frame from today's geometry and the snap kind: the hole's axis and centre *now*,
   the face's normal *now*. The in-plane direction comes from the geometry too (a straight edge of
   the face, or the body's axes), so it doesn't spin when the part changes.
3. Write the result into FreeCAD's joint (Reference = today's `Face6`, Placement = the frame).
   FreeCAD's names become a cache, rewritten every time, never read back.
4. Solve.

So a hole grown from 10 to 12 mm, a plate made thicker, a feature inserted upstream, or faces
renumbered all keep the joint, and the joint follows the geometry (the pin stays in the hole's new
centre). If the reference can't be resolved (`topo.Broken`: the face was deleted, or a pattern lost
the instance), the joint goes red in the browser with "Missing reference: edit the joint and pick
it again". The component stays where it was last solved instead of jumping. It is never a silent
guess.

References live in body coordinates; the component's placement is applied after. A joint moving a
component therefore doesn't disturb its own references. Step 7 extends the same rule to
in-context references.

Tests: the torture suite (`tests/test_torture.py`) gets a joint variant of each scenario. Every
edit runs on a jointed pair, then checks that the joint resolves to the same tag and that the
solved position matches the expected one.

## Main risk (after Step 0)

The feared one, joints breaking when faces renumber, turned out small: FreeCAD 1.1's own naming
and Kovač's references both kept the joints through every ordinary edit in the prototype
(ADR-0004, E3). The real risk found is the solver: from badly placed starting positions it can
report success on a wrong answer. Hence: snap parts into place when they are jointed, and check
every solve ourselves (ADR-0004, decision 4).

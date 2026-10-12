# Bodies, components and assemblies — plan (proposal, 2026-10-12)

Status: **proposal, awaiting owner decisions** (see "Decisions needed"). Nothing here is built yet.

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

### Step 0 — ADR-0004 and a spike (about 1 session)
- Prototype the three risky pieces headless: Kovač bodies inside `App::Part` containers (placement
  of the container moves the bodies; history features still compute correctly), instances via
  `App::Link`, and a FreeCAD joint whose references point at Kovač body faces, re-resolved through
  Kovač's reference layer after an upstream edit (FreeCAD stores plain element names like `Face6`,
  which break on edits — the same weakness ADR-0002 measured).
- Measure solve time for 5 / 20 / 50 components (budget: drag at ≥ 30 fps, so a solve < 30 ms).
- Write ADR-0004 (component and joint model) with the measured results; add OndselSolver to
  `THIRD_PARTY.md` (bundled, no new download).

### Step 1 — Components inside one design
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

1. **One file or many by default?** Proposal: components live in the same design by default
   (simplest to start, one history); external components (step 5) for parts reused across designs.
2. **Are joint-driven positions part of the history?** Proposal: no. Positions are assembly state
   (moving a hinged lid shouldn't add a timeline step); creating or editing a joint is.
3. **Where does this go in the milestones?** The README lists "drawings, assemblies" as M3.
   Proposal: finish M3 drawings first, then run these steps as M4, unless assemblies come first.

## Main risk

FreeCAD's joints name geometry by element index (`Face6`), which changes when a part is edited.
Step 0 must prove that Kovač's reference layer can sit in front of it; if it can't, joints keep
working for unchanged parts but break on edits, loudly, with a re-pick — never silently wrong.

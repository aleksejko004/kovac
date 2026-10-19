# ADR-0005 — Linked and independent copies

- **Status:** Accepted 2026-10-14 (owner request: "make 2 ways for copied object to behave … if
  parented they continue to behave together, if one is changed they all change; if unparented
  they are each an independent body after the copy was made; denote some way to visually
  separate them; the same for arrays and other multi-body features").
- **Builds on:** ADR-0002 (one history; bodies are its results), ADR-0003 (references),
  ADR-0004 (components and instances).

## Context

Before this, a copy made by Move (Copy), Mirror (not joined), Pattern of bodies or Copy
Component was a new body of the history, *derived* from the original at that step. It followed
edits made to the original's earlier steps, while features added later to either one changed
only that one. That is neither of the two behaviours the owner asked for.

## Decision

Every feature that makes copies of bodies has a **CopyMode** (panel: "Copies"):

1. **Independent** (the default; the owner's "unparented").
   - The feature keeps a snapshot of the bodies it copies: `Frozen` (shape) and `FrozenState`
     (face tags), taken at the commit that first sees them (`copies.freeze`).
   - Its copies are made from the snapshot from then on, so later edits to the original don't
     reach them. Features added to a copy change only that copy.
   - Face tags are kept from the snapshot, so references to a copy's faces stay valid.
2. **Linked** (the owner's "parented").
   - The copies are not bodies of the history. Each is a `LinkedCopy` object: the original
     body's shape under a fixed matrix (rigid, or a mirror), recomputed whenever the original
     changes (`copies.sync_links` keeps them in step with the feature).
   - A pick on a copy resolves to the original body with the same face number
     (`components.resolve`), so a feature made on any copy changes the original, and with it
     every copy.
   - Copies are drawn in the **linked colour** (the model colour tinted toward the accent) and
     listed with the link icon in the browser's Bodies folder.
   - Deleting one copy of a pattern skips that instance. Deleting a moved or mirrored copy
     deletes its feature. **Make independent** (browser) switches the feature to Independent,
     with a snapshot of the originals as they are today.
3. **Components** keep their two ways: New Instance is linked (an `App::Link`, ADR-0004);
   Copy Component is independent (a copying Move step with a snapshot).
4. **Older files.** Features made before copy modes have no `CopyMode`. They keep the old
   derived behaviour, and their panels don't show the choice.

## Consequences

- A snapshot stores a second copy of the copied bodies in the file (shape and tags).
- Linked copies can't be joined, cut or intersected with other bodies, because they aren't
  bodies of the history. Make them independent first.
- A hole or point placed on a *mirrored* linked copy is placed as if the copy were not mirrored
  (`copies.matrix_placement` leaves the mirror out).
- Component instances (`App::Link`) are not tinted yet, because FreeCAD's link drops its own
  colour whenever the original is redrawn. They keep the instance icon in the browser.

## Alternatives considered

- **FreeCAD `App::Link` for linked body copies.** It shares the drawing, but its colour override
  is lost whenever the original body is redrawn (found while testing), so the copies wouldn't look
  linked. It also makes a mirror an awkward negative scale.
- **Linked copies as history bodies, with edits redirected to the original.** That would let
  them take part in Booleans, but it needs a face-naming scheme shared across every copy.
  Possible later if Booleans on linked copies are needed.

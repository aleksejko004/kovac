# ADR-0003 — Reference layer (persistent naming)

- **Status:** Accepted 2026-10-10 (implements point 3 of ADR-0002)
- **Code:** `Kovac/kovac/topo.py`, used by every feature in `features.py`, `modify.py`, `datum.py`
- **Tests:** `tests/test_topo.py`, `tests/test_torture.py` (23 scenarios), `tests/test_golden.py` (32 parts)

## Context

ADR-0002 proposed storing three things per pick: our own semantic name, FreeCAD's mapped name and a geometric signature. Building it showed that FreeCAD's mapped names add nothing: they are re-hashed on every recompute (the M1 finding), so they never decide a match. A simpler scheme carries all the information we need.

## Decision

1. **Every face of every body carries a tag**, set by the feature that made it: `Extrude003:s:g2` (side from sketch edge g2), `Extrude003:start`, `Fillet001:f:<edge name>`, `Hole002:wall:0`, … A feature's output is its *state*: tagged bodies packed into the feature's shape (a compound) plus a JSON tag table (`BodyState`).
2. **Later operations inherit tags.** A result face keeps the tag of the input face it lies on (same underlying surface and an interior point inside it); several hits give the smallest tag, so merged faces have a stable name. Faces the kernel kept unchanged take their tag directly. Faces nobody claims are named by the feature (`generated`) or, last resort, by a geometry hash.
3. **Edges and vertices are named by their faces:** the sorted tags of their adjacent faces, plus the geometry kind. A reference stores body id, kind, tags and a geometric signature (`{"b","k","t","s"}`).
4. **Resolution** at regeneration: a unique tag match wins; among several, the one clearly nearest to the stored signature; then an exact-geometry match; otherwise **`topo.Broken`**. The feature then passes its input state through and shows "Missing reference: … Edit the feature and pick it again." Never a silent guess.

## Consequences

- Dimension changes, upstream inserts, reorders, pattern-count changes and flipped directions keep references (torture suite).
- References are independent of FreeCAD's element map, so they survive whatever FreeCAD does to its own names.
- Cost: tag inheritance runs once per feature; with the identity fast path it is a minor share of regeneration (see the M2 report).
- Opening a file needs no recompute: the tag tables are stored.

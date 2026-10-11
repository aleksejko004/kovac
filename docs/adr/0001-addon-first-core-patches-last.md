# ADR-0001 — Addon first, core patches last

- **Status:** Accepted (M1)
- **Date:** 2026-10-08

## Context

Kovač puts a new user experience on top of FreeCAD. Every change to FreeCAD core is a future merge conflict (brief §0.4). For M1 the owner chose to target the **stock FreeCAD 1.1.4 binary**. Building FreeCAD from source is deferred, so no C++ change can ship in M1 anyway.

The M1 spike checked which UX goals the addon layer (Python + PySide6 + pivy against FreeCAD 1.1.4) can reach:

| Goal | Reachable from the addon? | How |
|---|---|---|
| Hide workbenches, menus, stock panels | yes | Qt visibility on the main window; restored by the "Advanced" switch |
| Own tree, timeline, panels, start page | yes | Qt widgets fed by FreeCAD document and selection observers |
| One undo step per action | yes | `openTransaction` / `commitTransaction` in `kovac.commands.transaction` |
| Navigation preset, orbit pivot, zoom to cursor | yes | Qt event filter on the 3D viewport, camera moved through pivy |
| Selection (click/Shift/Ctrl, hold pick list, window/crossing, tangent chain) | yes | same event filter, `Gui.Selection`, picking via `getObjectInfo(s)` |
| Orientation cube function (26 views, drag orbit, roll, step) | yes | FreeCAD NaviCube, unchanged |
| Cube styling (colours, chamfer, font, opacity, labels) | yes | NaviCube parameters; labels re-written live for "define as Front" |
| Axis-tinted cube hover, our own cube control glyphs, Home and "define as Front" *on the cube's own menu* | **no** | NaviCube draws these in C++. Recorded as core-patch candidates |
| Non-modal command panels | yes | Qt dock widgets (float, move, dock, remember geometry) |
| Automatic regeneration | yes | document observer, recompute on the next event-loop turn |
| Regeneration in the background with progress | **no** (synchronous) | FreeCAD recomputes on the GUI thread; `CanAbortRecompute` (Esc) is on. Core-patch candidate |
| Branded distribution | yes | `bin/branding.xml` + profile template; no binary changes |

## Decision

1. Kovač is a FreeCAD **addon** (`Kovac/`, loadable with `FreeCAD -M <path>` or from `Mod/`). The branded build is the same addon plus `branding.xml`, images and a first-start profile placed next to an unmodified FreeCAD tree.
2. **No core patches in M1.** Each gap that needs one is written up in `docs/core-patches.md` as a *candidate*, with the user-visible cost of not having it.
3. A core patch is allowed only when a brief requirement cannot be met from the addon. It must be isolated and prepared as an upstream PR.
4. Kovač owns **viewport input** through an event filter rather than a C++ navigation style. Python cannot register a FreeCAD navigation style, and this keeps presets in our code and remappable. FreeCAD still receives everything we don't bind (edit modes, keyboard).

## Consequences

- We depend on FreeCAD internals that are not API: the 3D view's `graphicsView().viewport()`, dock object names (`Model`, `Tasks`, …), NaviCube parameter names, and FreeCAD restoring window state after `Activated()`. All of these are pinned to 1.1.x, and `tests/run_gui.py` fails if they move.
- FreeCAD 1.1 already has a long-press "clarify selection" feature (`EnableLongPressClarifySelection`). Ours replaces it while Kovač owns the left button. Upstreaming improvements there is preferable to keeping two.
- When the source build lands (deferred), the core-patch candidates can be prototyped against `main`.

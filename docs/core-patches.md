# FreeCAD core patches

**Applied: none.** M1 runs on the stock FreeCAD 1.1.4 binary (ADR-0001).

## Candidates (not applied)

Each one would be a small, isolated C++ change, prepared as an upstream pull request first.

| # | Area | What | Why (user-visible cost today) | Upstream? |
|---|---|---|---|---|
| 1 | `Gui/NaviCube.cpp` | Optional per-region hover colour from the axis colours (faces: their axis; edges/corners: accent) | Cube variant A specifies axis-tinted hover. Today: one `HiliteColor` for everything | generally useful; propose |
| 2 | `Gui/NaviCube.cpp` | Hook to add entries to the cube's own menu, plus an optional Home button | "Set home / Define current view as Front / Hide cube" live in Kovač's view bar and radial menu, not on the cube | propose as a generic "extra menu actions" API |
| 3 | `Gui/NaviCube.cpp` | Restyleable control glyphs (roll/step/menu) via SVG resources | The cube buttons keep FreeCAD's drawings, not our icon style | propose |
| 4 | `App/Document.cpp` | Recompute on a worker thread with progress and cancel, GUI stays live | Long regenerations block the UI; today only Esc-abort (`CanAbortRecompute`) | large; discuss upstream first |
| 5 | Toponaming | Sketch-generated side-edge names get new hash ids each recompute (`prototypes/tnp_repro.py`) | Fillets on extrude edges break on dimension changes (loudly) | bug report + fix; check against `main` first |
| 6 | `Gui/NavigationStyle` | Python-registrable navigation styles | Kovač uses a viewport event filter instead (works, but bypasses FreeCAD's style system) | propose |

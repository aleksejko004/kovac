# Architecture

Kovač is a FreeCAD addon (`Kovac/`) plus a branding layer (`dist/`). FreeCAD 1.1.4 is the engine; Kovač is the user experience. See ADR-0001 (addon first), ADR-0002 (body/feature model), ADR-0003 (reference layer) and ADR-0004 (components and joints, proposed).

```
FreeCAD 1.1.4 (unmodified)                Kovač addon (Kovac/kovac/)
──────────────────────────                ─────────────────────────────────────────────
App: documents, transactions,  ◄──────── commands.py   one action = one transaction, errors → status bar
     recompute, element maps              shell.py      app bar · modes · command bars · view bar ·
Gui: main window, MDI, NaviCube,                         Advanced switch · auto-recompute · all M1 commands
     selection, 3D viewer       ◄──────── navigation.py viewport event filter: mouse preset, pivot orbit,
Part / Sketcher / PartDesign / …                         zoom to cursor, click/Shift/Ctrl, hold/Alt pick list,
                                                         window/crossing, tangent double-click, radial hook
                                          selection.py  filters, tangent chains, window tests, selection sets
                                          views.py      26 views, home, "define as Front", cube labels
                                          tree.py       model tree (machinery hidden) + role() classification
                                          timeline.py   history strip, hover/selection sync, step controls
                                          radial.py     marking menu
                                          search.py     command search + favourites
                                          panel.py      floating/dockable non-modal panels
                                          measure.py    hover readout, two-pick measure
                                          startpage.py  start page
                                          theme.py      QSS + preference packs, from palette.py
                                          palette.py    design tokens (pure Python)
                                          ── M2: modeling ──────────────────────────────
                                          model.py      history (one linear list per document), feature
                                                        base class, body objects, rollback/insert/reorder,
                                                        Join/Cut/Intersect/New body inference
                                          topo.py       reference layer: face tags, edge/vertex names,
                                                        resolve or Broken (ADR-0003)
                                          regions.py    closed sketch regions (half-edge traversal)
                                          features.py   Extrude, Revolve, Sweep, Loft, primitives, Hole
                                          modify.py     Fillet, Chamfer, Shell, Draft, Face Pull, Delete
                                                        Face, Combine, Split, Move, Scale, Mirror,
                                                        Patterns, Thread
                                          datum.py      planes, axes, points; sketch planes
                                          design.py     the Design commands
                                          editor.py     feature panels (live preview, viewport picks,
                                                        unit/expression fields)
                                          sketchmode.py sketch entry and Finish Sketch
                                          manip.py      arrow manipulator with floating value field
                                          grid.py       ground grid and snapping
                                          ── assemblies (ADR-0004) ─────────────────────────
                                          components.py components, instances, frames, picks through them
                                          joints.py     joint origins, snaps, solve check, drag
                                          assemble.py   New Component / Instance, Joint, Drag, Ground
                                          params.py     named parameters
                                          inspect_tools.py mass properties, interference, section,
                                                        draft analysis, materials panel
```

A feature's output is a *state*: all bodies with their face tags, stored as the feature's shape (a compound) plus a tag table. Each feature reads the previous feature's state, so the history is a chain linked by `Previous`; body objects show the tip's state. A failing feature passes its input through and explains itself in `Status`.

## Rules the code follows

- **Every user action goes through `commands.transaction()` or `commands.add()`**: one undo step, recomputed before commit, plain-language errors, no modal dialogs.
- **Modes swap command bars only.** Model, tree, timeline and selection are shared (`shell.set_mode`).
- **Machinery stays hidden.** `tree.role()` is the single place that decides what the user sees as component / body / sketch / reference / joint / analysis / feature (timeline only) / machinery (never shown).
- **Kovač owns viewport input outside edit modes.** In a FreeCAD edit mode (e.g. a sketch), left and right buttons pass through to FreeCAD.
- **Design tokens have one source.** `palette.py` feeds the icon generator, QSS, preference packs, cube styling, splash and the review sheet.
- **Pure logic is separate from Qt** (views, selection, search ranking, measure readouts, roles, presets, palette), so it runs headless in tests.

## Delivery targets

1. **Addon:** `FreeCAD -M <repo>/Kovac`, or copy `Kovac/` into FreeCAD's `Mod/`. Applying the "Kovac Light/Dark" preference pack gives the full look.
2. **Branded build:** `dist/make_dist.py` copies the FreeCAD tree and adds `bin/branding.xml` (name, splash, About image, start workbench, its own user-data folder `Kovac`), `bin/kovac-user.cfg` (first-start profile: our look, Kovač workbench, no FreeCAD start page, no FreeCAD version in the title) and `Mod/Kovac`. FreeCAD's files and licences are unchanged. Stock workbenches stay reachable behind **☰ → Advanced / Expert**.

## Tests

| Command | What | Where it runs |
|---|---|---|
| `py tools/fc.py cmd tests/run.py` | 127 headless tests: M1 logic plus every feature against hand-computed geometry, model/history, reference layer, 23-scenario toponaming torture suite, 32 golden parts, parameters | FreeCADCmd |
| `py tests/run_gui.py` | M1 GUI acceptance (32 checks + latency metrics) | FreeCAD GUI, fresh profile |
| `py tests/run_gui.py gui_m2.py` | M2 end to end: L-bracket through the UI, thickness 5 → 8, benchmark interaction counts | FreeCAD GUI, fresh profile |
| `py tools/fc.py cmd tests/perf_m2.py` | 50-feature part: open and regeneration times | FreeCADCmd |
| `py tests/run_recovery.py` | autosave → simulated crash → recovery offered | FreeCAD GUI ×2 (Windows) |
| `py tests/run_dist.py` | branded build starts as Kovač on an empty profile | branded build |
| `py tests/run_startup.py` | first/warm start time | FreeCAD GUI ×4 |
| `py tools/fc.py cmd prototypes/adr0002_chain.py` | ADR-0002 toponaming / undo / regen comparison | FreeCADCmd |

`tools/fc.py` finds FreeCAD (`$KOVAC_FREECAD`, the portable copy in `%LOCALAPPDATA%/Kovac/tools`, or `PATH`), loads the addon with `-M` and gives every run a throwaway profile seeded with the Kovač first-start template.

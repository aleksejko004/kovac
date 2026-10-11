# Milestone 1 report — Foundation

**Date:** 2026-10-08 · **Engine:** FreeCAD 1.1.4 (portable binary, Windows 11) · **Kovač:** 0.1.0

## Decisions you need to make

1. **ADR-0002, body/feature model:** I propose (c) — a hybrid of Part-based Kovač features plus our own reference layer. The prototype found a FreeCAD 1.1.4 toponaming weakness that affects both models equally (`docs/adr/0002-body-and-feature-model.md`).
2. **Brand accent:** patina `#14857D` (current), temper `#6B4FD8`, or straw `#B07F22`.
3. **First 12 icons + app mark:** approve or redline (`docs/icons/contact-sheet.html`, rules in `docs/icons/STYLE.md`).
4. **Orientation cube:** variant A (current), B or C (`docs/design/orientation-cube.md`, renders in the contact sheet).
5. **Inter font:** OK to download and bundle it (SIL OFL-1.1)?
6. **GPL executables** shipped inside FreeCAD's tree (CalculiX, Gmsh): OK as aggregation for the branded build? (`THIRD_PARTY.md`)

## What was built

| Area | Delivered |
|---|---|
| Spike | FreeCAD 1.1.4 portable binary, SHA-256 verified. Addon loads via `-M` or `Mod/`. ADR-0001 (addon first, zero core patches) accepted. ADR-0002 prototyped on two models (proposed). |
| Branding | `dist/make_dist.py` builds `Kovac-0.1.0-windows-amd64` from the unmodified FreeCAD tree: `branding.xml` (name, splash, About image, window icon, start workbench, its own user-data folder), first-start profile, `Kovac.exe` launcher. In-app About with the "Built on FreeCAD" credit. Start page: new design, open, import STEP, mm/inch templates, L-bracket example, recent files with thumbnails. Stock UI behind ☰ → Advanced. |
| Design system | `palette.py` (3 accent proposals, neutrals, semantic colours, font stack). Light/dark Qt stylesheets and two FreeCAD preference packs generated from it. Icon generator with isometric primitives; first 12 icons plus app mark, light and dark. Contact sheet. Three cube variants rendered. |
| Shell | App bar, mode tabs (Design · Drawing · Make · Simulate · Render — only the command set changes), function-grouped bars ("Bring in", "Check", "Select"), bottom view bar. Command search on **S** with fuzzy ranking, favourites and recents. Floating, non-modal, position-remembering, dockable panels. Model tree with machinery hidden, visibility checkboxes, inline rename, component activation, named views, context menu, two-way selection sync. Read-only history timeline with error/warning/suppressed states, step/play controls, hover → geometry, geometry → creating feature. Radial menu with context sets, a fixed "repeat last" slot, an extras list and press-drag-release. |
| Navigation | Preset: middle pan, Shift+middle orbit, wheel zoom toward cursor. Presets are remappable (`MouseBindings` / `MousePreset`; "middle-orbit" and "touchpad" also ship). Orbit pivot under the cursor (or selection centre) with a marker; free and turntable modes. Left-drag orbit/pan/zoom toggles for touchpads. Animated camera moves (280 ms). |
| Selection | Click, Shift add, Ctrl toggle, Esc clear. Hold or Alt+click gives a pick list. Window (left→right, enclosed) and crossing (right→left, touched) with distinct rectangles. Double-click gives the tangent chain of an edge or face. Filters for all nine kinds. Selection sets saved in the document. |
| Orientation cube | FreeCAD NaviCube styled as variant A. All 26 views as animated commands. Home: go, set, reset. "Define current view as Front" relabels the cube live and re-maps every view command. Perspective/orthographic, fit-on-view-change, hide. |
| Regeneration & recovery | Automatic recompute of anything left touched (property edits, undo/redo). One undo step per action. Autosave every 5 min, recovery and backups on, Esc aborts long recomputes. Crash recovery verified end to end. |

## Demo, step by step

1. `py tools/fc.py gui` — Kovač opens on its start page; no FreeCAD menus, toolbars or workbench selector.
2. Click **L-bracket with holes** — the tree shows one body ("Drilled"); the timeline shows its 9 features.
3. Middle-drag pans, Shift+middle-drag orbits about the point under the cursor (marker), and the wheel zooms toward the cursor.
4. Click the top face, then Shift+click a side face. Press **S**, type `mea`, Enter. The Measure panel floats beside the view: distance and 90° angle; hovering gives instant readouts.
5. Right-click a face for the radial menu. Drag toward "Select tangent chain" and release.
6. Click the cube's RIGHT face, then ☰ → search "Define current view as Front": the cube now says FRONT there, and "Front view" goes there.
7. Drag left→right around the part (window), then right→left across it (crossing). Alt+click for the pick list.
8. **Make** tab: the bars change, the model stays. ☰ → **Advanced / Expert** brings FreeCAD back.

## Test results (all on the final code)

| Suite | Result |
|---|---|
| Headless (`tools/fc.py cmd tests/run.py`) | **31 / 31 pass**: transactions/undo, 26 views + front frame, selection logic, search ranking, measure, tree roles, presets, preference packs, icon rules, icon **raster regression** at 16/24/32 px × 2 themes |
| GUI acceptance (`tests/run_gui.py`) | **29 / 29 pass**: start → open STEP → orbit/pan/zoom → select faces → measure with **no stock workbench UI visible**; 26 animated views; set/reset home; define/reset Front; window, crossing, filtered window, tangent double-click, pick list; radial context; search; auto-recompute; STEP import = 1 undo step; modes keep the model |
| Crash recovery (`tests/run_recovery.py`) | **pass**: autosave wrote `fc_recovery_file.*`; restart after a hard kill offered "Document Recovery" |
| Branded build (`tests/run_dist.py`) | **5 / 5 pass**: title "Kovač" without a FreeCAD version, starts in Kovač, stock UI hidden, Kovač start page, profile from our template |
| ADR-0002 prototype | see the ADR (5 edits × 2 models, undo restores in all 10) |
| CI (Windows + Linux) | **not run** — `.github/workflows/ci.yml` written, but there is no remote repository yet |

## Measured performance (this PC, FreeCAD 1.1.4)

| Budget (§5) | Measured | Verdict |
|---|---|---|
| Hover pre-highlight < 16 ms | pick + preselect **0.1 ms** median; measure readout **0.4–1.2 ms** (the redraw itself is FreeCAD's) | met |
| Radial menu < 50 ms | **35–42 ms** median incl. first paint; max 47–65 ms across runs | median met; worst case occasionally over |
| Command search < 50 ms | **16–35 ms** worst query over 279 commands | met |
| Start to usable < 6 s | warm **6.5–7.3 s**; first launch 8.5 s. Stock FreeCAD on the same PC: warm **9.9 s** | **not met**, though about 35 % faster than stock FreeCAD |
| View animation ~250–300 ms | 280 ms configured; 0.35 s command-to-settled | met |
| 50-feature open, ≥ 30 fps manipulators, < 1 s commit regen | — | M2 (no modeling yet) |

## Limitations

- **Toponaming:** FreeCAD 1.1.4 loses sketch-generated edge references on dimension changes (loudly). M2 must build the reference layer from ADR-0002 before modeling features are trustworthy.
- **Cube:** axis-tinted hover, our own control glyphs, and Home / "define as Front" *on the cube's own menu* need core patches (`docs/core-patches.md` #1–3). Today those commands live in the view bar, radial menu and search.
- **Regeneration** is synchronous, so a slow recompute blocks the UI (Esc aborts). Background recompute needs a core patch (#4).
- **Commands** without an approved icon show text labels. The rest of the icon set waits for your approval.
- **Window/crossing** uses projected samples plus a 5×5 pick grid. Thin features between samples can be missed; a precise segment/box test can come later.
- **Inter** isn't bundled, so the UI shows the first installed fallback font.
- The timeline is read-only. Rollback, reorder, suppress, edit and groups arrive in M2.
- Viewport input is owned by Kovač outside edit modes. Inside a FreeCAD sketch edit, FreeCAD's own mouse handling applies until M2 replaces sketching.
- Linux: the code paths are written (AppImage layout in `tools/fc.py`, CI job), but nothing has run on Linux yet.

## Deviations from the brief

- **No source build of FreeCAD** (you chose to defer it) — M1 targets the stock 1.1.4 binary, so there are no core patches.
- **No plan-mode stop before implementing** — you asked for the first implementation directly.
- **CI not green** — the workflow exists but there's no repository to run it in.
- **Startup budget missed** — measured above.
- **ADR-0002 is "Proposed", not decided** — the prototype showed both candidate models break the same way, so the choice is yours.
- **Big binaries live outside the project folder** — FreeCAD and the branded build are in `%LOCALAPPDATA%\Kovac\` so OneDrive doesn't sync about 3 GB.

## Screens

`docs/milestones/m1-screens/`: start page, measure, radial menu, search, splash.

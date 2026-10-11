# Kovač — working rules (condensed from the build brief §0–§2)

## Process
- One milestone at a time. End each with `docs/milestones/M<n>-report.md` (built, demo steps, test results, measured performance, limitations, deviations), then **stop for owner review**.
- Keep current: `docs/ARCHITECTURE.md`, `docs/adr/NNNN-*.md`, `docs/core-patches.md`, `docs/PROVENANCE.md`, `THIRD_PARTY.md`, `PROGRESS.md`.
- Tests first for feature logic, toponaming handling, CAM and post-processors. Never call a task done with failing or skipped tests.
- Verify versions, maintenance and licences yourself.
- Same problem fails three times → stop, write up what was tried, ask.
- Ask before: changing an ADR's architecture, adding a dependency with a licence not yet in `THIRD_PARTY.md`, anything irreversible.

## Clean room (non-negotiable)
- Allowed sources: FreeCAD source/docs, other open-source projects (under their licences), textbooks, papers, HCI research, open standards (STEP, IGES, STL, 3MF, OBJ, DXF public reference, SVG, PDF, RS-274/NGC, ISO 128/129/5456/7200/2768/286, ISO metric threads).
- Never inspect proprietary software, its files, traffic, screenshots, videos, tutorials, help, icons or UI. If a search surfaces such material, don't open it.
- **Never name a commercial CAD/CAM/CAE product or vendor** anywhere: code, comments, docs, commits, UI, file names. Never describe Kovač as a clone, lookalike or alternative of anything.
- Original identity: our name, logo, palette, typography, icons, manipulators. Icons come only from `tools/icongen.py` following `docs/icons/STYLE.md`.
- Interop only via open or publicly documented formats.
- Features primarily known from a patent or vendor-branded technology → stop and flag.
- Every non-trivial algorithm or interaction → an entry in `docs/PROVENANCE.md`.
- Keep FreeCAD copyright headers. Credit "Built on FreeCAD" in About, docs and README; never present Kovač as official FreeCAD. Use FreeCAD's logo only to credit FreeCAD.
- Our code: **LGPL-2.1-or-later** (SPDX header in every file). GPL addons → ask first.

## Architecture (ADR-0001; ADR-0002 proposed)
- Addon first (`Kovac/`), core patches last and only when the addon can't do it; every patch documented and prepared for upstream.
- All user actions go through `kovac.commands` (one transaction = one undo step; plain-language errors, no modal walls).
- Modes change the command set only. FreeCAD machinery is hidden (`tree.role`). Stock workbenches sit behind "Advanced".
- Kovač owns viewport input outside edit modes (`kovac.navigation`).
- Design tokens only from `kovac/palette.py`; regenerate assets with `py tools/build_assets.py`.

## UI direction (owner, 2026-10-10) — keep to this when adding or changing UI
- **Dark by default**: deep near-black background, high contrast; axis colours bright but not neon (`palette.py`). Light stays available (☰ → Light / dark).
- **Top area is ~30 % larger than stock**: icons 26 px (`shell.RIBBON_ICON`), 16 px text.
  - Row 1: menu, save, undo/redo … Home, Fit, Grid, Search.
  - Row 2: the **big mode button** at the far left (DESIGN ▾ → Drawing, Make, Simulate, Render), then the command groups.
- **Ribbon groups**: icons in a row, the group's name **centred underneath** (`shell.ribbon_group`), never as text beside the icons. Variants go behind a dropdown arrow so a mode's commands fit one row at 1700 logical px.
- **No bottom view bar.** View helpers live at the right end of row 1; FreeCAD's navigation-style picker stays hidden (Kovač owns the mouse).
- **Browser**: see-through panel over the left of the 3D view, an icon per item, eye toggles (no checkboxes). The owner likes it as it is.
- **Sketching**:
  - **Sketch** turns to the top-front-right overview and offers the origin planes and any flat face.
  - The planes are rounded, outlined squares on the camera side of the origin, set in from the axes. The one under the cursor lights up; the clicked one flashes the accent colour.
  - Picking one turns the camera to face it.
  - **Finish Sketch** returns to the overview.
  - While sketching, Finish Sketch takes the mode button's place and the ribbon shows FreeCAD's sketch tools with our icons, grouped Create / Modify / Constrain / Project / View.
  - The sketcher's task panel stays closed.
- **Grid**: follows the view, so it never runs out; it fades into the background towards its edge and sits a hair below z = 0. Axes are solid on the positive side and dashed on the negative side, with ticks and X/Y/Z labels; Z is a short stub. The 1-2-5 step follows zoom.
- **One snapping rule everywhere** (sketch tools, points picked on faces such as hole centres and placement, the extrude arrow's distance):
  - Existing sketch points (ends, centres, origin) pull the cursor within 14 px.
  - Grid points pull within 9 px, and not over a line.
  - Elsewhere the click lands where it is.
  - FreeCAD's snap then makes pulled points exact. Alt turns pulling off.
  - The **snap marker** shows each snap: a square with a tick across the middle of each side and a centre dot; yellow on an existing point, teal on the grid.
- **Panels**: options with a few choices (extent, direction, result, hole type, primitive) are icon buttons (`editor.IconChoice`), not drop-downs.
- **Sketch lines are blue** while sketching and drawing (`palette.SEMANTIC["sketch_free"]`); drawing tools stay on after each shape.
- **Right-click radial menu is see-through and has fixed places** (muscle memory): up = repeat last, up-right = Line, right = Extrude, down-right = Move, down = Undo, **left = Delete**; the two left diagonals and the list below change with context (face, edge, body, sketch, empty). It works inside sketches too.
  - No tool running: it opens on the click.
  - A tool running: a plain right click ends the tool, and a right **drag** opens the menu mid-gesture.
  - The gesture leaves a fading trail. The ring has no fill: only a guide circle, the hovered slice and small chips.
  - FreeCAD's own sketch context menu never shows.
- **Hover feedback everywhere**: a sketch's closed area under the cursor is shaded like a body face; clicking selects it and Extrude uses exactly that area.
- **Sketch tools of our own** (`sketchtools.py`):
  - Polyline = the line tool chained, so each segment takes typed length and angle.
  - Polygon inscribed (corners on the circle) and circumscribed (sides touch the circle), each set by its circle's radius.
- **Shading**: a soft world-fixed light from above-front-left plus a dimmer headlight, so each side of a part reads differently. Any unlit overlay must keep its state inside a separator.
- **Group dividers** in the ribbon are light, softly fading bars.
- **Kovač's toolbar rows are enforced** (`shell.arrange`) over whatever layout an older profile restores.
- **One viewport handler per view**, keyed by the widget itself (`shiboken6.getCppPointer`): duplicates split hover/selection state.
- **Manipulators always drag**: an on-canvas arrow takes the mouse before anything under it.
- **Mouse** (default preset): pan = middle drag, orbit = Shift + middle drag, zoom = wheel toward the cursor, double middle click = fit. Same inside sketches.
- The owner describes behaviours they want in their own words. Build them with Kovač's own look and **never** write the product they compare against into code, docs, commits or UI.

## Running things
- `py tools/fc.py cmd <script>` — headless FreeCAD with the addon and a throwaway profile; `py tools/fc.py gui [script]` — GUI.
- Use `py` (python.org 3.13) on this machine; `python` is the Microsoft Store build, which sandboxes AppData.
- FreeCAD 1.1.4 portable: `%LOCALAPPDATA%\Kovac\tools`. Keep big binaries out of the OneDrive project folder.
- In GUI test scripts, end with `os._exit()`. Closing the window can leave FreeCAD waiting on a dialog.

## Quality budgets (brief §5)
Start < 6 s; open a 50-feature part < 3 s; manipulator preview ≥ 30 fps; commit regen < 1 s; hover < 16 ms; radial < 50 ms; search < 50 ms; nothing blocks > 100 ms without feedback.

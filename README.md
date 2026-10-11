# Kovač

An integrated design-to-manufacture environment — **built on [FreeCAD](https://www.freecad.org)**.

FreeCAD provides the engine: geometry kernel integration, documents and transactions, sketcher, solvers, workbenches. Kovač adds a new user experience on top: one environment with modes, a clean model tree, a history timeline, floating panels, a radial menu, command search and our own visual design. Kovač is an independent distribution and **not an official FreeCAD product**.

> Status: Milestones 1 (foundation) and 2 (modelling) done; Milestone 3 (drawings, assemblies) in progress. Early software: expect rough edges. See `PROGRESS.md` and `docs/milestones/`.

## Try it

Needs FreeCAD 1.1.x and Python 3. Tested on Windows and Linux.

**Windows**: unzip the portable FreeCAD 1.1 into `%LOCALAPPDATA%\Kovac\tools` (or set `KOVAC_FREECAD` to its folder), then:

```bash
py tools/fc.py gui
```

**Linux**: install FreeCAD 1.1 from your distribution, or extract the AppImage (`./FreeCAD_1.1.4-Linux-x86_64-py311.AppImage --appimage-extract`) and point `KOVAC_FREECAD` at the `squashfs-root` folder. Then:

```bash
python3 tools/fc.py gui
```

This starts FreeCAD with the Kovač addon in a throwaway profile. Use `--real-home` to keep your normal FreeCAD settings. To install permanently, copy `Kovac/` into FreeCAD's `Mod` folder and apply the **Kovac Light** or **Kovac Dark** preference pack (Preferences → General).

Branded build (copies FreeCAD and adds Kovač's branding; output in `%LOCALAPPDATA%\Kovac\dist`):

```bash
py tools/fc.py cmd dist/make_dist.py
```

## Using it (M1)
- **S** — search every command; **Ctrl+D** in the list pins a favourite.
- **Middle-drag** pan · **Shift+middle-drag** orbit around the point under the cursor · **wheel** zooms toward the cursor.
- **Click** select · **Shift** add · **Ctrl** toggle · **Esc** clear · **hold** or **Alt+click** for a pick list · **drag left→right** window select, **right→left** crossing select · **double-click** an edge or face for its tangent chain.
- **Right-click** opens the radial menu (drag toward a command and release for speed).
- ☰ → **Advanced / Expert** brings back FreeCAD's own workbenches, menus and panels.

## Tests
```bash
py tools/fc.py cmd tests/run.py
```
```bash
py tests/run_gui.py
```
More in `docs/ARCHITECTURE.md`.

## Licence
LGPL-2.1-or-later (`LICENSE`), matching FreeCAD. Third-party components: `THIRD_PARTY.md`. Sources of algorithms and interaction designs: `docs/PROVENANCE.md`.

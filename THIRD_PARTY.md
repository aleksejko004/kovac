# Third-party software

Kovač's own code is **LGPL-2.1-or-later** (see `LICENSE`). M1 and M2 add **no new downloads**: everything below arrives inside the FreeCAD 1.1.4 binary Kovač runs on. Versions come from that build's `packages.txt` (verified 2026-10-08). Developer tools use only the Python standard library.

## Runtime (shipped by FreeCAD, used directly by Kovač)

| Component | Version | License | Used for |
|---|---|---|---|
| FreeCAD | 1.1.4 | LGPL-2.0-or-later | engine: documents, transactions, Part/Sketcher, NaviCube, selection, branding |
| Open CASCADE Technology | 7.8.1 | LGPL-2.1 with OCCT exception | geometry kernel (via FreeCAD) |
| Coin3D | 4.0.3 | BSD-3-Clause | scene graph (pivot marker) |
| pivy | 0.6.9 | ISC | Python access to the camera node |
| Qt | 6.8.3 | LGPL-3.0-only (open-source option) | all widgets |
| PySide6 | 6.8.3 | LGPL-3.0-only | Qt from Python |
| Python | 3.11.14 | PSF-2.0 | addon runtime |
| OndselSolver | 1.0.1 | LGPL-2.1 (FreeCAD's `ThirdPartyLibraries.html`) | assemblies: the joint solver behind FreeCAD's Assembly workbench, called through `Assembly::AssemblyObject.solve()` (ADR-0004, proposed) |
| pythonocc-core | 7.8.1.1 | LGPL-3.0 (verified from `OCC/LICENSE` in the build) | M2: OCCT draft-angle operation (`BRepOffsetAPI_DraftAngle`), which FreeCAD's Python API does not expose |

LGPL-2.1-or-later code may be combined with LGPL-3.0 libraries (the "or later" clause allows LGPL-3.0 terms).

## Shipped in the branded build without Kovač using them yet

The branded build is the unmodified FreeCAD tree, so it carries everything FreeCAD bundles (full list: `doc/ThirdPartyLibraries.html` in the build). Two items for the owner's attention:

| Component | Version | License | Note |
|---|---|---|---|
| CalculiX (ccx.exe) | 2.22 | GPL-2.0 | separate executable, called by FEM (M5d). Aggregation, not linking. **Owner review before release.** |
| Gmsh | 4.15.0 | GPL-2.0-or-later with exceptions | separate executable, mesher for FEM (M5d). Same note. |

## Referenced, not bundled

| Item | License | Status |
|---|---|---|
| Inter typeface | SIL OFL-1.1 | named first in our font stack; falls back to Segoe UI / Noto Sans / DejaVu Sans. Bundling needs a download — **owner approval pending**. |

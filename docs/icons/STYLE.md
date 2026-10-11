# Kovač icon style

Every icon comes out of `tools/icongen.py` (shared primitives plus one short recipe per icon). Restyling means changing a constant or `palette.py` and running `py tools/build_assets.py`. Review page: `docs/icons/contact-sheet.html`.

## Grid and sizes
- **24 px master grid**, **20 px live area** (2 px margin). The generator refuses icons that leave the live area, and never scales an icon to fit, so detail density stays equal across the set.
- Exported as SVG and checked at **16 / 24 / 32 px**, each at **100 / 150 / 200 %** (contact sheet + raster regression test).

## Strokes, corners, fills
- **Action strokes 1.5 px**: arrows, sketch curves, the removed face of a shell, the rim of a hole.
- **Face edges 1.0 px**, outline colour (`icon_line`).
- Round joins and caps everywhere. Flat fills, no gradients, no shadows.
- Sketch points are **2.6 px square handles**: surface fill, 1 px outline.
- Only polygons and polylines (SVG Tiny subset): no clip paths, filters, masks or gradients, so Qt's renderer in FreeCAD draws exactly what a browser does (enforced by a test).

## How 3D form is suggested
- Feature, assembly and CAM icons use a **true isometric** projection (ISO 5456-3), 1 model unit ≈ 1 px.
- **Three tones from the theme:** `icon_top` for upward faces, and `icon_left` / `icon_right` for side faces by which side of the screen they turn to. Curved faces blend tones by their normal and are drawn without facet seams.
- Hidden surfaces never show; holes and cavities show their far walls clipped to the opening.

## The accent marks the action
The brand accent appears **only** on the part that *is* the command: the extrude arrow, the fillet's rounded strip, the hole rim, the shell's open face, the revolve and joint motion arc, the measure dimension, the toolpath, the drawn sketch geometry. Everything else is neutral. A test checks that every icon contains the accent.

## Families
| Family | Motif | First batch |
|---|---|---|
| Feature | small isometric solid + accent action | extrude, revolve, fillet, hole, shell |
| Sketch | flat 2D, accent geometry, square handles | sketch, line, rectangle, circle |
| Assembly | two parts + accent relation | joint |
| Inspect | measuring motif | measure |
| CAM | tool + accent path | toolpath |
| App | accent tile + white anvil | app mark (identity, approved separately) |

## Themes
Light and dark variants are generated from the same recipe with that theme's tones; the accent is shared.

## Status
**First batch of 12 awaiting owner approval** (brief §4). No further icons will be drawn until then. Commands without an approved icon show their text label.

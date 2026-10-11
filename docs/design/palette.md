# Palette and typography

Source of truth: `Kovac/kovac/palette.py`. Swatches and every icon in all three accents: `docs/icons/contact-sheet.html`.

## Brand accent — three proposals (owner picks one)

Named after colours a smith sees on steel. All three were chosen to stay clear of colours commonly tied to other CAD brands.

| Key | Hex | Character |
|---|---|---|
| **patina** (current default) | `#14857D` | weathered-copper green-teal; calm, reads well on light and dark |
| temper | `#6B4FD8` | tempered-steel violet; distinctive, slightly cooler |
| straw | `#B07F22` | straw temper colour; warm, closest to "hot metal" |

## Neutrals
Light: background `#F4F5F7`, surface `#FFFFFF`, border `#D5D9DE`, text `#1C2026`. Dark: background `#1A1D21`, surface `#23272D`, border `#3A4048`, text `#E7E9EC`. The viewport uses a vertical gradient (`viewport_top` → `viewport_bottom`) from the same family.

## Semantic colours
| Role | Hex |
|---|---|
| preselect (hover) | `#FFC857` |
| select | `#00A3D9` |
| error | `#D64545` |
| warning | `#E39B21` |
| success | `#2E9E6A` |
| sketch — free | `#3557E0` |
| sketch — fully constrained | `#2E9E6A` |
| axis X / Y / Z | `#E5484D` / `#46A758` / `#3E63DD` |

## Typography
UI font stack: **Inter** (SIL OFL-1.1) → Segoe UI → Noto Sans → DejaVu Sans. Inter is not bundled yet (needs a download, pending approval), so today's builds show the first installed fallback.

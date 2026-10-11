# SPDX-License-Identifier: LGPL-2.1-or-later
"""Kovač drawing sheets: ISO 5457 frame (20 mm filing margin, 10 mm elsewhere, centring marks,
grid reference zones) and an ISO 7200 title block (180 mm wide) whose fields are TechDraw
editable texts, filled from the design by kovac.drawing. Original layout.

    py tools/build_assets.py          # writes Kovac/Resources/templates/*.svg
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SIZES = {"A4": (210, 297), "A3": (297, 420), "A2": (420, 594), "A1": (594, 841), "A0": (841, 1189)}
SHEETS = [("A4", "Portrait"), ("A4", "Landscape"), ("A3", "Landscape"), ("A2", "Landscape"), ("A1", "Landscape"),
          ("A0", "Landscape")]
NS = 'xmlns="http://www.w3.org/2000/svg" xmlns:freecad="http://www.freecad.org/wiki/index.php?title=Svg_Namespace"'
INK, MUTED, FONT = "#000000", "#5B636E", "Inter, Segoe UI, DejaVu Sans, sans-serif"
TB_W, TB_H = 180.0, 40.0

# title block cells: (x, y, w, h, label, field, value, value size) relative to the block's top-left
CELLS = [
    (0, 0, 60, 16, "Legal owner", "Company", "", 5.0),
    (0, 16, 60, 8, "Material", "Material", "", 3.2),
    (0, 24, 30, 8, "Mass", "Mass", "", 3.2),
    (30, 24, 30, 8, "Surface", "Surface", "Ra 3.2", 3.2),
    (0, 32, 60, 8, "General tolerances", "GeneralTolerance", "ISO 2768-mK", 3.2),
    (60, 0, 75, 16, "Title", "Title", "", 6.0),
    (60, 16, 75, 8, "Supplementary title", "Subtitle", "", 3.2),
    (60, 24, 37.5, 8, "Created by", "CreatedBy", "", 3.2),
    (97.5, 24, 37.5, 8, "Approved by", "ApprovedBy", "", 3.2),
    (60, 32, 37.5, 8, "Date of issue", "Date", "", 3.2),
    (97.5, 32, 37.5, 8, "Scale", "Scale", "1:1", 3.2),
    (135, 0, 45, 16, "Identification number", "DrawingNumber", "", 4.5),
    (135, 16, 22.5, 8, "Revision", "Revision", "A", 3.2),
    (157.5, 16, 22.5, 8, "Sheet", "Sheet", "1/1", 3.2),
    (135, 24, 22.5, 8, "Document type", "DocumentType", "Part drawing", 2.6),
    (157.5, 24, 22.5, 8, "Status", "Status", "Released", 2.6),
]


def _line(x1, y1, x2, y2, w=0.35, col=INK):
    return '<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f" stroke="%s" stroke-width="%.2f"/>' % (x1, y1, x2, y2, col, w)


def _text(x, y, s, size, col=INK, anchor="start", weight=400, field=None):
    attr = ' freecad:editable="%s"' % field if field else ""
    return ('<text%s x="%.2f" y="%.2f" font-family="%s" font-size="%.2f" font-weight="%d" fill="%s" text-anchor="%s">'
            '<tspan x="%.2f" y="%.2f">%s</tspan></text>' % (attr, x, y, FONT, size, weight, col, anchor, x, y, s))


def projection_symbol(x, y, k=1.0):
    """ISO first-angle projection symbol (method E): side view of a truncated cone, then its end view."""
    out = ['<path d="M %.2f %.2f L %.2f %.2f L %.2f %.2f L %.2f %.2f Z" fill="none" stroke="%s" stroke-width="0.35"/>'
           % (x, y + 1.5 * k, x + 7 * k, y, x + 7 * k, y + 6 * k, x, y + 4.5 * k, INK)]
    cx, cy = x + 12 * k, y + 3 * k
    out.append('<circle cx="%.2f" cy="%.2f" r="%.2f" fill="none" stroke="%s" stroke-width="0.35"/>' % (cx, cy, 3 * k, INK))
    out.append('<circle cx="%.2f" cy="%.2f" r="%.2f" fill="none" stroke="%s" stroke-width="0.35"/>' % (cx, cy, 1.5 * k, INK))
    out.append(_line(x - 1, y + 3 * k, cx + 4 * k, y + 3 * k, 0.18))
    return out


def sheet(size, orientation):
    w, h = SIZES[size]
    if orientation == "Landscape":
        w, h = h, w
    left, other = 20.0, 10.0
    fx0, fy0, fx1, fy1 = left, other, w - other, h - other
    out = ['<svg %s width="%dmm" height="%dmm" viewBox="0 0 %d %d">' % (NS, w, h, w, h),
           '<rect x="0" y="0" width="%d" height="%d" fill="#FFFFFF"/>' % (w, h),
           '<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="none" stroke="%s" stroke-width="0.7"/>'
           % (fx0, fy0, fx1 - fx0, fy1 - fy0, INK)]
    # centring marks: the middle of each side, from the trimmed edge to 5 mm inside the frame
    out += [_line(w / 2, 0, w / 2, fy0 + 5, 0.7), _line(w / 2, h, w / 2, fy1 - 5, 0.7),
            _line(0, h / 2, fx0 + 5, h / 2, 0.7), _line(w, h / 2, fx1 - 5, h / 2, 0.7)]
    # grid reference zones (about 50 mm): numbers along top and bottom, letters down the sides
    nx, ny = max(2, round((fx1 - fx0) / 50 / 2) * 2), max(2, round((fy1 - fy0) / 50 / 2) * 2)
    for i in range(nx):
        x0 = fx0 + (fx1 - fx0) * i / nx
        if i:
            out += [_line(x0, fy0 - 5, x0, fy0, 0.25), _line(x0, fy1, x0, fy1 + 5, 0.25)]
        xm = x0 + (fx1 - fx0) / nx / 2
        out += [_text(xm, fy0 - 1.6, str(i + 1), 3, MUTED, "middle"), _text(xm, fy1 + 3.8, str(i + 1), 3, MUTED, "middle")]
    for j in range(ny):
        y0 = fy0 + (fy1 - fy0) * j / ny
        if j:
            out += [_line(fx0 - 5, y0, fx0, y0, 0.25), _line(fx1, y0, fx1 + 5, y0, 0.25)]
        ym = y0 + (fy1 - fy0) / ny / 2 + 1
        letter = "ABCDEFGHJKLMNPQRSTUVWXYZ"[j]
        out += [_text(fx0 - 2.5, ym, letter, 3, MUTED, "middle"), _text(fx1 + 2.5, ym, letter, 3, MUTED, "middle")]
    # ISO 7200 title block, bottom right inside the frame
    bx, by = fx1 - TB_W, fy1 - TB_H
    out.append('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="none" stroke="%s" stroke-width="0.7"/>'
               % (bx, by, TB_W, TB_H, INK))
    for x, y, cw, ch, label, field, value, vs in CELLS:
        out.append('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="none" stroke="%s" stroke-width="0.25"/>'
                   % (bx + x, by + y, cw, ch, INK))
        out.append(_text(bx + x + 1.2, by + y + 2.6, label, 1.8, MUTED))
        out.append(_text(bx + x + 1.2, by + y + ch - 1.6, value, vs, INK, weight=600 if vs >= 4.5 else 400, field=field))
    out += projection_symbol(bx + 137, by + 33)
    out.append(_text(bx + TB_W - 1.2, by + TB_H - 1.4, "Kovač", 2.2, MUTED, "end", 600))
    out.append("</svg>")
    return "\n".join(out)


def write_all(out=ROOT / "Kovac" / "Resources" / "templates"):
    out.mkdir(parents=True, exist_ok=True)
    for size, orientation in SHEETS:
        (out / ("Kovac_%s_%s.svg" % (size, orientation))).write_text(sheet(size, orientation), encoding="utf-8")
    return out


if __name__ == "__main__":
    print(write_all())

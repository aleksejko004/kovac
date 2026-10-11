# SPDX-License-Identifier: LGPL-2.1-or-later
"""Renders the orientation-cube design variants (docs/design/orientation-cube.md) as SVG."""
import itertools
import math

from icongen import Icon, centroid, dot, mul, palette

CANVAS, SCALE = 220, 50
AXES = ("axis_x", "axis_y", "axis_z")
VARIANTS = {
    "A · Forged": dict(chamfer=0.16, face="surface2", label="text_muted", weight=600, tint="axis", border=1.0),
    "B · Facet": dict(chamfer=0.34, face="model", label="surface", weight=700, tint="accent", border=1.4),
    "C · Wire": dict(chamfer=0.07, face="surface", label="text", weight=500, tint="axis", border=0.8, axis_edges=True),
}
LABELS = {(0, 1): "RIGHT", (0, -1): "LEFT", (1, 1): "REAR", (1, -1): "FRONT", (2, 1): "TOP", (2, -1): "BOTTOM"}


def regions(c):
    """24-vertex chamfered cube: 6 squares, 12 edge strips, 8 corner triangles -> [(key, poly)]."""
    a = 1 - c
    out = []
    for i, s in itertools.product(range(3), (1, -1)):
        j, k = [x for x in range(3) if x != i]
        quad = []
        for u, v in ((-a, -a), (a, -a), (a, a), (-a, a)):
            p = [0, 0, 0]
            p[i], p[j], p[k] = s, u, v
            quad.append(tuple(p))
        out.append((((i, s),), quad))
    for (i, si), (j, sj) in itertools.combinations([(i, s) for i in range(3) for s in (1, -1)], 2):
        if i == j:
            continue
        k = 3 - i - j
        quad = []
        for (ci, cj), ck in (((si, sj * a), -a), ((si, sj * a), a), ((si * a, sj), a), ((si * a, sj), -a)):
            p = [0, 0, 0]
            p[i], p[j], p[k] = ci, cj, ck
            quad.append(tuple(p))
        out.append((((i, si), (j, sj)), quad))
    for sx, sy, sz in itertools.product((1, -1), repeat=3):
        out.append((((0, sx), (1, sy), (2, sz)), [(sx, sy * a, sz * a), (sx * a, sy, sz * a), (sx * a, sy * a, sz)]))
    return out


def cube_svg(cfg, theme, hover=None, idle=False):
    t = palette.theme(theme)
    g = Icon(t, view=(1, -1, 0.85))
    polys = [(key, [mul(q, SCALE) for q in poly]) for key, poly in regions(cfg["chamfer"])]
    vis = []
    for key, poly in polys:
        n = tuple(sum(s for i, s in key if i == ax) for ax in range(3))
        if sum(x * y for x, y in zip(n, g.view)) <= 0:
            continue
        base = t[cfg["face"]] if len(key) == 1 else palette.mix(t[cfg["face"]], t["edge"], 0.12 * len(key))
        if key == hover:
            # faces take their axis colour; edges/corners (between axes) take the accent
            tint = t[AXES[key[0][0]]] if cfg["tint"] == "axis" and len(key) == 1 else t["accent"]
            base = palette.mix(base, tint, 0.55)
        vis.append((round(dot(centroid(poly), g.view), 6), key, poly, base))
    for _, key, poly, fill in sorted(vis):
        g.poly([g.p(q) for q in poly], fill=fill, stroke=t["border"] if not cfg.get("axis_edges") else
               t[AXES[3 - sum(i for i, _ in key[:2])]] if len(key) == 2 else t["border"], width=cfg["border"])
        if len(key) == 1:
            (i, s), = key
            right = {0: (0, s, 0), 1: (-s, 0, 0), 2: (1, 0, 0)}[i]
            up = (0, 0, 1) if i != 2 else (0, s, 0)
            c = [0, 0, 0]
            c[i] = s * SCALE
            g.text(tuple(c), right, up, LABELS[(i, s)], 13, t[cfg["label"]], cfg["weight"])
    # controls: home (origin target), roll arrows, step chevrons, menu dots — our own glyphs
    col = t["text_muted"]
    cx, cy = 0.0, 0.0
    r = SCALE * 1.95
    g.poly(g.ellipse2d((cx - r, cy + r), 7, 7), stroke=col, width=1.4)
    g.poly(g.ellipse2d((cx - r, cy + r), 1.6, 1.6), fill=col)
    for sgn in (1, -1):
        arc = [(cx + sgn * (r - 4) + 7 * math.cos(a / 10), cy - r + 7 * math.sin(a / 10) * sgn) for a in range(-25, 12)]
        g.poly(arc, stroke=col, width=1.4, closed=False)
        g.arrow(arc[-3], arc[-1], color=col, width=1.4, head=3.5)
    for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
        px, py = cx + dx * (r + 4), cy + dy * (r + 4)
        g.poly([(px - dy * 5 - dx * 3, py + dx * 5 - dy * 3), (px + dx * 3, py + dy * 3), (px + dy * 5 - dx * 3, py - dx * 5 - dy * 3)],
               stroke=col, width=1.6, closed=False)
    for k in (-5, 0, 5):
        g.poly(g.ellipse2d((cx + r + k - 2, cy + r), 1.3, 1.3), fill=col)
    body = g.svg(CANVAS, CANVAS, CANVAS - 8)
    op = 0.55 if idle else 1.0
    return body.replace('viewBox', 'style="background:%s;border-radius:8px;opacity:1" viewBox' % t["viewport_top"], 1) \
        .replace("<polygon", '<polygon opacity="%.2f"' % op).replace("<polyline", '<polyline opacity="%.2f"' % op).replace("<text", '<text opacity="%.2f"' % op)


def all_variants():
    out = []
    for name, cfg in VARIANTS.items():
        for theme in ("light", "dark"):
            out.append(("%s — %s, idle" % (name, theme), cube_svg(cfg, theme, idle=True)))
            out.append(("%s — %s, hover FRONT face" % (name, theme), cube_svg(cfg, theme, hover=((1, -1),))))
            out.append(("%s — %s, hover FRONT-RIGHT edge" % (name, theme), cube_svg(cfg, theme, hover=((0, 1), (1, -1)))))
    return out

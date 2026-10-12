# SPDX-License-Identifier: LGPL-2.1-or-later
"""Kovač icon generator: shared primitives + one recipe per icon -> SVG.

Rules live in docs/icons/STYLE.md. Restyling = change the constants below or
kovac/palette.py and re-run. Output is plain SVG Tiny (no clipPath, no filters)
so Qt's SVG renderer inside FreeCAD draws it exactly like a browser does.

    py tools/build_assets.py          # icons, contact sheet, preference packs
"""
import base64
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Kovac"))
from kovac import palette  # noqa: E402

GRID = 24          # master grid, px
LIVE = 20          # live area: every icon must fit 20x20 at scale 1 (2 px margin)
STROKE = 1.5       # action strokes (arrows, sketch curves)
HAIR = 1.0         # face edges / secondary lines
HANDLE = 2.6       # sketch point handle size
ISO = (1.0, 1.0, 1.0)  # icon view direction: +x left-front, +y right-front, +z up
K = math.sqrt(1.5)     # makes iso units ~1 px


# ---------------------------------------------------------------- vector math
def sub(a, b): return tuple(x - y for x, y in zip(a, b))
def add(a, b): return tuple(x + y for x, y in zip(a, b))
def mul(a, s): return tuple(x * s for x in a)
def dot(a, b): return sum(x * y for x, y in zip(a, b))
def cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def norm(a): return mul(a, 1.0 / math.sqrt(dot(a, a)))
def centroid(ps): return mul(tuple(map(sum, zip(*ps))), 1.0 / len(ps))


def newell(poly):
    n = [0.0, 0.0, 0.0]
    for p, q in zip(poly, poly[1:] + poly[:1]):
        n[0] += (p[1] - q[1]) * (p[2] + q[2])
        n[1] += (p[2] - q[2]) * (p[0] + q[0])
        n[2] += (p[0] - q[0]) * (p[1] + q[1])
    return tuple(n)


def clip(poly, window):
    """Sutherland-Hodgman: clip 2D polygon by a convex 2D window (any winding)."""
    sign = 1 if sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(window, window[1:] + window[:1])) > 0 else -1

    def inside(p, a, b):
        return sign * ((b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])) >= 0

    def hit(p, q, a, b):
        x1, y1, x2, y2 = p[0], p[1], q[0], q[1]
        x3, y3, x4, y4 = a[0], a[1], b[0], b[1]
        d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / d
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))

    out = poly
    for a, b in zip(window, window[1:] + window[:1]):
        src, out = out, []
        for p, q in zip(src, src[1:] + src[:1]):
            if inside(q, a, b):
                if not inside(p, a, b):
                    out.append(hit(p, q, a, b))
                out.append(q)
            elif inside(p, a, b):
                out.append(hit(p, q, a, b))
        if not out:
            break
    return out


def rect_xy(x, y, z, dx, dy):
    return [(x, y, z), (x + dx, y, z), (x + dx, y + dy, z), (x, y + dy, z)]


def arc_pts(c, r, a0, a1, n=24, plane="xy"):
    pts = []
    for i in range(n + 1):
        a = math.radians(a0 + (a1 - a0) * i / n)
        u, v = r * math.cos(a), r * math.sin(a)
        pts.append(add(c, (u, v, 0) if plane == "xy" else (u, 0, v)))
    return pts


# ---------------------------------------------------------------- icon canvas
class Icon:
    """Collects 2D primitives; render() centers them in the grid without scaling."""

    def __init__(self, tone, view=ISO):
        self.t = tone
        self.view = norm(view)
        self.r = norm(cross((0, 0, 1), self.view))  # screen right (true camera, not mirrored)
        self.s = cross(self.view, self.r)            # screen up
        self.items = []
        self.texts = []

    # projection -----------------------------------------------------------
    def p(self, pt):
        return (K * dot(self.r, pt), -K * dot(self.s, pt))

    # raw emitters ---------------------------------------------------------
    def poly(self, pts, fill="none", stroke=None, width=HAIR, closed=True, dash=None):
        self.items.append(("poly", [tuple(q) for q in pts], fill, stroke, width, closed, dash))

    def line(self, a, b, stroke, width=STROKE, dash=None):
        self.poly([a, b], stroke=stroke, width=width, closed=False, dash=dash)

    def arrow(self, a, b, color=None, width=STROKE, head=3.4):
        color = color or self.t["accent"]
        d = norm(sub(b, a) + (0,))[:2]
        n = (-d[1], d[0])
        base = (b[0] - d[0] * head, b[1] - d[1] * head)
        self.line(a, (b[0] - d[0] * head * 0.7, b[1] - d[1] * head * 0.7), color, width)
        w = head * 0.62
        self.poly([b, (base[0] + n[0] * w, base[1] + n[1] * w), (base[0] - n[0] * w, base[1] - n[1] * w)],
                  fill=color, stroke=color, width=0.6)

    def handle(self, c):
        h = HANDLE / 2
        self.poly([(c[0] - h, c[1] - h), (c[0] + h, c[1] - h), (c[0] + h, c[1] + h), (c[0] - h, c[1] + h)],
                  fill=self.t["surface"], stroke=self.t["icon_line"], width=HAIR)

    def ellipse2d(self, c, rx, ry, n=36):
        return [(c[0] + rx * math.cos(2 * math.pi * i / n), c[1] + ry * math.sin(2 * math.pi * i / n)) for i in range(n)]

    def circle_axes(self, r):
        """Screen semi-axes of a horizontal circle (r is horizontal, s carries the tilt)."""
        return K * r, K * r * math.hypot(self.s[0], self.s[1])

    # 3D primitives --------------------------------------------------------
    def shade(self, n):
        """Three-tone flat shading: top tone by n.z^2, side tone by which screen side the face turns to."""
        side = "icon_right" if dot(n, self.r) > 0 else "icon_left"
        w = (n[0] ** 2 + n[1] ** 2, n[2] ** 2)
        cols = [palette.rgb(self.t[k]) for k in (side, "icon_top")]
        return "#%02X%02X%02X" % tuple(round(sum(c[i] * wi for c, wi in zip(cols, w))) for i in range(3))

    def faces(self, faces, accent=(), smooth=()):
        c = centroid([q for f in faces for q in f])
        vis = []
        for i, f in enumerate(faces):
            n = norm(newell(f))
            if dot(n, sub(centroid(f), c)) < 0:
                n = mul(n, -1)
            if dot(n, self.view) <= 1e-6:
                continue
            fill = self.t["accent"] if i in accent else self.shade(n)
            vis.append((round(dot(centroid(f), self.view), 6), i, f, fill))   # rounded: ties sort by index on any Python
        for _, i, f, fill in sorted(vis):
            if i in smooth:  # no seams on curved surfaces
                self.poly([self.p(q) for q in f], fill=fill, stroke=fill, width=0.5)
            else:
                self.poly([self.p(q) for q in f], fill=fill, stroke=self.t["icon_line"])

    def prism(self, base, ext, accent=(), smooth=()):
        """Extrude a planar 3D polygon. accent/smooth index the side faces (0 = base[0]->base[1])."""
        top = [add(q, ext) for q in base]
        n = len(base)
        sides = [[base[i], base[(i + 1) % n], top[(i + 1) % n], top[i]] for i in range(n)]
        self.faces([base[::-1], top] + sides, accent={i + 2 for i in accent}, smooth={i + 2 for i in smooth})
        if smooth:  # silhouette of a smooth run on the hidden cap
            run = sorted(smooth)
            self.poly([self.p(base[i]) for i in run] + [self.p(base[(run[-1] + 1) % n])],
                      stroke=self.t["icon_line"], closed=False)

    def cylinder(self, c, r, h, fill=None, top=None):
        """Upright cylinder, axis +z, base center c."""
        rx, ry = self.circle_axes(r)
        b, t = self.p(c), self.p(add(c, (0, 0, h)))
        lower = [q for q in self.ellipse2d(b, rx, ry) if q[1] >= b[1] - 1e-9]
        lower.sort(key=lambda q: q[0])
        side = fill or palette.mix(self.t["icon_left"], self.t["icon_right"], 0.5)
        self.poly([(b[0] - rx, t[1])] + lower + [(b[0] + rx, t[1])], fill=side, stroke=self.t["icon_line"])
        self.poly(self.ellipse2d(t, rx, ry), fill=top or self.t["icon_top"], stroke=self.t["icon_line"])
        return t, rx, ry

    # output ---------------------------------------------------------------
    def text(self, c, e1, e2, label, size, fill, weight=600, opacity=1.0):
        """Label lying on a 3D plane: e1 = text right, e2 = text up (unit model vectors)."""
        o = self.p(c)
        a, b = sub(self.p(add(c, e1)), o), sub(self.p(sub(c, e2)), o)
        self.texts.append((o, a, b, label, size, fill, weight, opacity))

    def svg(self, size=GRID, grid=GRID, live=LIVE):
        pts = [q for it in self.items for q in it[1]]
        xs, ys = [q[0] for q in pts], [q[1] for q in pts]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if w > live + 0.01 or h > live + 0.01:
            raise ValueError("icon exceeds %dpx live area: %.1f x %.1f" % (live, w, h))
        ox, oy = grid / 2 - (min(xs) + max(xs)) / 2, grid / 2 - (min(ys) + max(ys)) / 2
        out = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">'
               % (size, size, grid, grid)]
        for _, q, fill, stroke, width, closed, dash in self.items:
            coords = " ".join("%.2f,%.2f" % (x + ox, y + oy) for x, y in q)
            attrs = 'points="%s" fill="%s"' % (coords, fill if closed else "none")
            if stroke:
                attrs += ' stroke="%s" stroke-width="%.2f" stroke-linejoin="round" stroke-linecap="round"' % (stroke, width)
            if dash:
                attrs += ' stroke-dasharray="%s"' % dash
            out.append("<%s %s/>" % ("polygon" if closed else "polyline", attrs))
        for o, a, b, label, fs, fill, weight, op in self.texts:
            out.append('<text transform="matrix(%.4f %.4f %.4f %.4f %.2f %.2f)" font-family="%s" font-size="%.1f" '
                       'font-weight="%d" fill="%s" fill-opacity="%.2f" text-anchor="middle" dominant-baseline="central">%s</text>'
                       % (a[0], a[1], b[0], b[1], o[0] + ox, o[1] + oy, palette.FONT_UI.replace('"', ""), fs, weight, fill, op, label))
        out.append("</svg>")
        return "\n".join(out)


# ---------------------------------------------------------------- recipes
# Feature family: small isometric solid + accent action.

def extrude(g):
    g.prism(rect_xy(0, 0, 0, 9, 9), (0, 0, 5))
    g.arrow(g.p((4.5, 4.5, 5)), g.p((4.5, 4.5, 13.5)))


def revolve(g):
    g.line(g.p((0, 0, -3)), g.p((0, 0, 11)), g.t["icon_line"], HAIR, dash="2,1.5")
    g.cylinder((0, 0, 0), 4, 7)
    arc = [g.p(q) for q in arc_pts((0, 0, 3.5), 6.6, -40, 125)]
    g.poly(arc[:-2], stroke=g.t["accent"], width=STROKE, closed=False)
    g.arrow(arc[-4], arc[-1])


def fillet(g):
    prof = [(0, 0, 0), (9, 0, 0)] + arc_pts((5.5, 0, 2.5), 3.5, 0, 90, 8, plane="xz") + [(0, 0, 6)]
    g.prism(prof, (0, 9, 0), accent=range(1, 10), smooth=range(1, 10))


def hole(g):
    g.prism(rect_xy(0, 0, 0, 11, 11), (0, 0, 3.5))
    c = g.p((5.5, 5.5, 3.5))
    rx, ry = g.circle_axes(3.2)
    g.poly(g.ellipse2d(c, rx, ry), fill=g.t["icon_hole"])
    depth = 2.0  # drawn shallower than the slab so the dark bore reads at 16 px
    top = [q for q in g.ellipse2d(c, rx, ry, 48) if q[1] <= c[1]]
    top.sort(key=lambda q: q[0])
    back = []
    for x, _ in reversed(top):
        f = math.sqrt(max(0.0, 1 - ((x - c[0]) / rx) ** 2))
        back.append((x, min(c[1] + depth - ry * f, c[1] + ry * f)))
    g.poly(top + back, fill=g.t["icon_left"])
    g.poly(g.ellipse2d(c, rx, ry), stroke=g.t["accent"], width=STROKE)


def shell(g):
    a, b, z, f = 1.5, 10.0, 6.0, 1.5
    g.prism(rect_xy(0, 0, 0, b + a, b + a), (0, 0, z))
    opening = [g.p(q) for q in rect_xy(a, a, z, b - a, b - a)]
    inner = [
        (rect_xy(a, a, f, b - a, b - a), g.shade((0, 0, 1)), 0.18),  # floor (in shadow)
        ([(a, a, f), (a, b, f), (a, b, z), (a, a, z)], g.shade((1, 0, 0)), 0.0),  # far wall, faces +x
        ([(a, a, f), (b, a, f), (b, a, z), (a, a, z)], g.shade((0, 1, 0)), 0.0),  # far wall, faces +y
    ]
    for face, col, dim in inner:
        poly = clip([g.p(q) for q in face], opening)
        if poly:
            g.poly(poly, fill=palette.mix(col, g.t["icon_line"], dim), stroke=g.t["icon_line"], width=0.6)
    g.poly(opening, stroke=g.t["accent"], width=STROKE)


# Sketch family: flat 2D.

def sketch(g):
    g.poly([g.p(q) for q in rect_xy(0, 0, 0, 11, 11)], fill=g.t["icon_top"], stroke=g.t["icon_line"])
    g.poly([g.p(q) for q in rect_xy(2.5, 2.5, 0, 6, 4)], stroke=g.t["accent"], width=STROKE)
    g.poly([g.p(q) for q in arc_pts((5.5, 8, 0), 1.6, 0, 360, 16)][:-1], stroke=g.t["accent"], width=STROKE)


def line(g):
    a, b = (4, 19), (20, 5)
    g.line(a, b, g.t["accent"])
    g.handle(a)
    g.handle(b)


def rectangle(g):
    g.poly([(4, 6), (20, 6), (20, 18), (4, 18)], stroke=g.t["accent"], width=STROKE)
    g.handle((4, 18))
    g.handle((20, 6))


def circle(g):
    g.poly(g.ellipse2d((12, 12), 8, 8, 48), stroke=g.t["accent"], width=STROKE)
    g.line((10.5, 12), (13.5, 12), g.t["icon_line"], HAIR)
    g.line((12, 10.5), (12, 13.5), g.t["icon_line"], HAIR)
    g.handle((12 + 8 * 0.7071, 12 - 8 * 0.7071))


# Assembly family: two parts + relation.

def joint(g):
    g.line(g.p((5, 5, -1)), g.p((5, 5, 12)), g.t["icon_line"], HAIR, dash="2,1.5")
    g.prism(rect_xy(0, 0, 0, 10, 10), (0, 0, 2.5))
    g.prism(rect_xy(2.5, 2.5, 5.5, 5, 5), (0, 0, 3.5))
    arc = [g.p(q) for q in arc_pts((5, 5, 4), 5.6, -40, 125)]
    g.poly(arc[:-2], stroke=g.t["accent"], width=STROKE, closed=False)
    g.arrow(arc[-4], arc[-1])


# Inspect family: measuring motifs.

def measure(g):
    for x in (4, 20):
        g.line((x, 7), (x, 19), g.t["icon_line"], HAIR)
    g.arrow((12, 11), (4.5, 11))
    g.arrow((12, 11), (19.5, 11))
    g.poly([(4, 19), (20, 19)], stroke=g.t["icon_line"], width=HAIR, closed=False, dash="1.5,1.5")


# CAM family: tool + path.

def toolpath(g):
    g.prism(rect_xy(0, 0, 0, 11, 11), (0, 0, 2))
    path = [(2, 2), (9, 2), (9, 5), (2, 5), (2, 8), (9, 8)]
    g.poly([g.p((x, y, 2)) for x, y in path], stroke=g.t["accent"], width=STROKE, closed=False)
    g.cylinder((9, 8, 2), 1.5, 6.5)


# App mark: an anvil on an accent tile (Kovač = smith). Original drawing.

def app(g):
    def rounded(x0, y0, x1, y1, r, n=6):
        pts = []
        for cx, cy, a0 in ((x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)):
            pts += [(cx + r * math.cos(math.radians(a0 + 90 * i / n)), cy + r * math.sin(math.radians(a0 + 90 * i / n)))
                    for i in range(n + 1)]
        return pts
    g.poly(rounded(2, 2, 22, 22, 4.5), fill=g.t["accent"])
    g.poly([(4.0, 8.6), (8.5, 7.5), (19.5, 7.5), (19.5, 10.5), (16.0, 10.5), (14.5, 13.0), (14.5, 14.5),
            (17.5, 14.5), (17.5, 17.5), (6.5, 17.5), (6.5, 14.5), (9.5, 14.5), (9.5, 13.0), (8.5, 10.5),
            (7.0, 10.0)], fill="#FFFFFF")


# ---------------------------------------------------------------- M2 set (same rules, after approval)

def chamfer(g):
    prof = [(0, 0, 0), (9, 0, 0), (9, 0, 3), (6, 0, 6), (0, 0, 6)]
    g.prism(prof, (0, 9, 0), accent=[2])


def draft(g):
    w1 = rect_xy(0, 0, 0, 10, 10)
    w2 = rect_xy(1.6, 1.6, 7, 6.8, 6.8)
    g.faces([w1[::-1], w2] + [[w1[i], w1[(i + 1) % 4], w2[(i + 1) % 4], w2[i]] for i in range(4)], accent={3})


def facepull(g):
    g.faces([rect_xy(0, 0, 0, 9, 9)[::-1], rect_xy(0, 0, 5, 9, 9)] +
            [[a, b, (b[0], b[1], 5), (a[0], a[1], 5)] for a, b in zip(rect_xy(0, 0, 0, 9, 9), rect_xy(0, 0, 0, 9, 9)[1:] + rect_xy(0, 0, 0, 9, 9)[:1])],
            accent={1})
    g.arrow(g.p((4.5, 4.5, 5)), g.p((4.5, 4.5, 12)), color=g.t["icon_line"])


def deleteface(g):
    g.prism(rect_xy(0, 0, 0, 10, 10), (0, 0, 6))
    top = [g.p(q) for q in rect_xy(0, 0, 6, 10, 10)]
    g.poly(top, fill=g.t["surface"], stroke=g.t["accent"], width=STROKE, dash="2,1.5")
    c = g.p((5, 5, 6))
    g.line((c[0] - 2.5, c[1] - 1.4), (c[0] + 2.5, c[1] + 1.4), g.t["accent"])
    g.line((c[0] - 2.5, c[1] + 1.4), (c[0] + 2.5, c[1] - 1.4), g.t["accent"])


def combine(g):
    g.prism(rect_xy(0, 0, 0, 8, 8), (0, 0, 6))
    g.prism(rect_xy(4, 4, 2, 8, 8), (0, 0, 6), accent=[1, 2])      # visible sides of the added body


def split(g):
    g.prism(rect_xy(0, 0, 0, 11, 8), (0, 0, 6))
    g.poly([g.p(q) for q in [(5.5, -2, -1), (5.5, 10, -1), (5.5, 10, 8), (5.5, -2, 8)]],
           fill=g.t["accent"], stroke=g.t["accent"], width=HAIR)


def move(g):
    g.prism(rect_xy(0, 0, 0, 7, 7), (0, 0, 5))
    c = g.p((3.5, 3.5, 5))
    for dx, dy in ((7, 0), (-7, 0), (0, 6), (0, -6)):
        g.arrow(c, (c[0] + dx, c[1] + dy), head=2.8)


def scale(g):
    g.prism(rect_xy(0, 0, 0, 5, 5), (0, 0, 4))
    g.poly([g.p(q) for q in rect_xy(0, 0, 9, 11, 11)], stroke=g.t["accent"], width=HAIR, dash="1.5,1.5")
    g.arrow(g.p((5, 5, 4)), g.p((10, 10, 9)))


def mirror(g):
    g.prism(rect_xy(0, 0, 0, 4, 8), (0, 0, 6))
    g.prism(rect_xy(8, 0, 0, 4, 8), (0, 0, 6))
    g.poly([g.p(q) for q in [(6, -1, -1), (6, 9, -1), (6, 9, 8), (6, -1, 8)]], stroke=g.t["accent"], width=STROKE, dash="2,1.5")


def pattern(g):
    for i in range(3):
        g.prism(rect_xy(i * 5, 0, 0, 3, 3), (0, 0, 3), accent=[1, 2] if i == 0 else [])
    for i in range(3):
        g.prism(rect_xy(i * 5, 6, 0, 3, 3), (0, 0, 3))


def patterncirc(g):
    g.poly([g.p(q) for q in arc_pts((0, 0, 0), 6, 0, 360, 32)][:-1], stroke=g.t["accent"], width=HAIR, dash="1.5,1.5")
    for k in range(6):
        a = math.radians(60 * k + 15)
        g.cylinder((6 * math.cos(a), 6 * math.sin(a), 0), 1.3, 3, fill=g.t["accent"] if k == 0 else None)


def thread(g):
    t, rx, ry = g.cylinder((0, 0, 0), 4.5, 11)
    for k in range(5):
        y = t[1] + 2.2 + k * 2.1
        g.line((t[0] - rx + 0.6, y + 1.2), (t[0] + rx - 0.6, y - 0.8), g.t["accent"], HAIR + 0.2)


def sweep(g):
    path = [g.p(q) for q in arc_pts((0, 0, 0), 8, 0, 120, 20)]
    g.poly(path, stroke=g.t["accent"], width=STROKE, closed=False)
    c = path[0]
    g.poly(g.ellipse2d(c, 2.2, 3.4), fill=g.t["icon_left"], stroke=g.t["icon_line"])
    g.arrow(path[-4], path[-1])


def loft(g):
    sq = [g.p(q) for q in rect_xy(0, 0, 0, 10, 10)]
    circ = [g.p(q) for q in arc_pts((5, 5, 10), 3, 0, 360, 24)][:-1]
    for a, b in ((sq[0], circ[6]), (sq[1], circ[0]), (sq[2], circ[18]), (sq[3], circ[12])):
        g.line(a, b, g.t["accent"], HAIR)
    g.poly(sq, fill=g.t["icon_top"], stroke=g.t["icon_line"])
    g.poly(circ, fill=g.t["icon_top"], stroke=g.t["icon_line"])


def box(g):
    g.faces([rect_xy(0, 0, 0, 10, 8)[::-1], rect_xy(0, 0, 8, 10, 8)] +
            [[a, b, (b[0], b[1], 8), (a[0], a[1], 8)] for a, b in zip(rect_xy(0, 0, 0, 10, 8), rect_xy(0, 0, 0, 10, 8)[1:] + rect_xy(0, 0, 0, 10, 8)[:1])],
            accent={1})


def cylinder(g):
    g.cylinder((0, 0, 0), 5, 9, top=g.t["accent"])


def sphere(g):
    c = (12, 12)
    g.poly(g.ellipse2d(c, 8, 8, 48), fill=g.shade((0.3, 0.3, 0.9)), stroke=g.t["icon_line"])
    g.poly(g.ellipse2d(c, 8, 2.6, 48), stroke=g.t["accent"], width=STROKE)


def cone(g):
    b = g.p((0, 0, 0))
    rx, ry = g.circle_axes(5)
    apex = g.p((0, 0, 11))
    lower = sorted([q for q in g.ellipse2d(b, rx, ry) if q[1] >= b[1] - 1e-9], key=lambda q: q[0])
    g.poly([apex] + lower, fill=palette.mix(g.t["icon_left"], g.t["icon_right"], 0.5), stroke=g.t["icon_line"])
    g.poly(g.ellipse2d(b, rx, ry), stroke=g.t["accent"], width=STROKE, dash="2,1.5")


def torus(g):
    c = (12, 12)
    g.poly(g.ellipse2d(c, 9, 5.2, 48), fill=g.shade((0.2, 0.2, 0.95)), stroke=g.t["icon_line"])
    g.poly(g.ellipse2d((12, 11.4), 3.6, 1.8, 32), fill=g.t["surface"], stroke=g.t["accent"], width=STROKE)


def plane(g):
    g.poly([g.p(q) for q in rect_xy(0, 0, 0, 11, 11)], fill=palette.mix(g.t["accent"], g.t["surface"], 0.75),
           stroke=g.t["accent"], width=STROKE)


def axis(g):
    g.line(g.p((0, 0, -4)), g.p((0, 0, 14)), g.t["accent"], STROKE, dash="3,1.5")
    g.prism(rect_xy(-2, -2, 3, 4, 4), (0, 0, 4))


def point(g):
    g.line((5, 12), (19, 12), g.t["icon_line"], HAIR)
    g.line((12, 5), (12, 19), g.t["icon_line"], HAIR)
    g.poly(g.ellipse2d((12, 12), 3, 3), fill=g.t["accent"], stroke=g.t["accent"], width=HAIR)


def parameters(g):
    for y, x in ((7, 15), (12, 8), (17, 12)):
        g.line((4, y), (20, y), g.t["icon_line"], HAIR)
        g.poly(g.ellipse2d((x, y), 2.2, 2.2), fill=g.t["accent"], stroke=g.t["accent"], width=HAIR)


def material(g):
    c = (12, 12)
    g.poly(g.ellipse2d(c, 8, 8, 48), fill=g.shade((0.3, 0.3, 0.9)), stroke=g.t["icon_line"])
    g.poly([(c[0] + 8 * math.cos(math.radians(a)), c[1] + 8 * math.sin(math.radians(a))) for a in range(-90, 91, 10)] + [c],
           fill=g.t["accent"], stroke=g.t["icon_line"], width=HAIR)


def mass(g):
    g.poly([(7, 10), (17, 10), (20, 20), (4, 20)], fill=g.t["accent"], stroke=g.t["icon_line"])
    g.poly(g.ellipse2d((12, 7), 3, 3), stroke=g.t["icon_line"], width=STROKE)


def interference(g):
    g.prism(rect_xy(0, 0, 0, 8, 8), (0, 0, 6))
    g.prism(rect_xy(4, 4, 2, 8, 8), (0, 0, 6))
    ov = [g.p(q) for q in rect_xy(4, 4, 6, 4, 4)]
    g.poly(ov, fill=g.t["accent"], stroke=g.t["accent"], width=HAIR)


def section(g):
    prof = [(0, 0, 0), (10, 0, 0), (10, 0, 7), (0, 0, 7)]
    g.prism(prof, (0, 5, 0))
    cap = [g.p(q) for q in [(0, 5, 0), (10, 5, 0), (10, 5, 7), (0, 5, 7)]]
    g.poly(cap, fill=g.t["accent"], stroke=g.t["icon_line"])
    for k in range(1, 5):
        g.line(g.p((2 * k, 5, 0)), g.p((2 * k - 2, 5, 2.5)), g.t["surface"], HAIR)


def draftanalysis(g):
    w1 = rect_xy(0, 0, 0, 10, 10)
    w2 = rect_xy(1.6, 1.6, 7, 6.8, 6.8)
    g.faces([w1[::-1], w2] + [[w1[i], w1[(i + 1) % 4], w2[(i + 1) % 4], w2[i]] for i in range(4)], accent={2, 3})
    g.items.append(("poly", [g.p(q) for q in [w1[2], w1[3], w2[3], w2[2]]], palette.SEMANTIC["warning"], g.t["icon_line"], HAIR, True, None))


def finish(g):
    g.poly(g.ellipse2d((12, 12), 9, 9, 48), fill=g.t["accent"])
    g.poly([(7.5, 12.5), (10.8, 15.8), (16.8, 8.8)], stroke="#FFFFFF", width=2.2, closed=False)


def home(g):
    g.poly(g.ellipse2d((12, 12), 8, 8, 48), stroke=g.t["icon_line"], width=STROKE)
    g.poly(g.ellipse2d((12, 12), 3, 3), fill=g.t["accent"], stroke=g.t["accent"], width=HAIR)


def orbit(g):
    arc = [(12 + 8 * math.cos(math.radians(a)), 12 + 5 * math.sin(math.radians(a))) for a in range(200, 520, 10)]
    g.poly(arc[:-2], stroke=g.t["accent"], width=STROKE, closed=False)
    g.arrow(arc[-4], arc[-1])
    g.poly(g.ellipse2d((12, 12), 2, 2), fill=g.t["icon_line"])


def pan(g):
    for d in ((8, 0), (-8, 0), (0, 8), (0, -8)):
        g.arrow((12, 12), (12 + d[0], 12 + d[1]), head=3)


def zoom(g):
    g.poly(g.ellipse2d((10, 10), 6, 6, 40), stroke=g.t["icon_line"], width=STROKE)
    g.line((14.5, 14.5), (20, 20), g.t["accent"], 2.4)
    g.line((7, 10), (13, 10), g.t["accent"], STROKE)
    g.line((10, 7), (10, 13), g.t["accent"], STROKE)


def import_step(g):
    g.prism(rect_xy(2, 2, 0, 9, 9), (0, 0, 5))
    g.arrow((3, 3), (9, 9))


def feature(g):
    g.prism(rect_xy(0, 0, 0, 9, 9), (0, 0, 6), accent=[1])


# Browser family: what the model browser shows.

def body(g):
    g.faces([rect_xy(0, 0, 0, 10, 10)[::-1], rect_xy(0, 0, 9, 10, 10)] +
            [[a, b, (b[0], b[1], 9), (a[0], a[1], 9)] for a, b in zip(rect_xy(0, 0, 0, 10, 10), rect_xy(0, 0, 0, 10, 10)[1:] + rect_xy(0, 0, 0, 10, 10)[:1])])
    g.poly([g.p(q) for q in rect_xy(0, 0, 9, 10, 10)], stroke=g.t["accent"], width=STROKE)


def component(g):
    g.prism(rect_xy(0, 0, 0, 9, 9), (0, 0, 3))
    g.prism(rect_xy(2, 2, 3, 5, 5), (0, 0, 4), accent=[1, 2])


def folder(g):
    g.poly([(3, 7), (9, 7), (11, 9), (21, 9), (21, 19), (3, 19)], fill=g.t["icon_left"], stroke=g.t["icon_line"])
    g.poly([(3, 7), (9, 7), (11, 9), (3, 9)], fill=g.t["accent"], stroke=g.t["icon_line"])


def settings(g):
    pts = []
    for k in range(32):
        a = 2 * math.pi * k / 32
        r = 8.5 if (k // 2) % 2 == 0 else 6.5
        pts.append((12 + r * math.cos(a), 12 + r * math.sin(a)))
    g.poly(pts, fill=g.t["icon_left"], stroke=g.t["icon_line"])
    g.poly(g.ellipse2d((12, 12), 3, 3), fill=g.t["accent"], stroke=g.t["icon_line"])


def views(g):
    g.poly([(3, 8), (16, 8), (16, 18), (3, 18)], fill=g.t["icon_left"], stroke=g.t["icon_line"])
    g.poly([(16, 11), (21, 8), (21, 18), (16, 15)], fill=g.t["accent"], stroke=g.t["icon_line"])


def eye(g):
    top = [(12 + 9 * math.cos(math.radians(a)), 12 - 5.5 * math.sin(math.radians(a))) for a in range(0, 181, 15)]
    g.poly(top + [(12 + 9 * math.cos(math.radians(a)), 12 + 5.5 * math.sin(math.radians(a))) for a in range(180, 361, 15)][1:-1],
           fill=g.t["surface"], stroke=g.t["icon_line"])
    g.poly(g.ellipse2d((12, 12), 3, 3), fill=g.t["accent"], stroke=g.t["accent"], width=HAIR)


def grid(g):
    plane = [g.p(q) for q in rect_xy(0, 0, 0, 11, 11)]
    g.poly(plane, fill=g.t["icon_top"], stroke=g.t["icon_line"])
    for k in (2.75, 5.5, 8.25):
        g.line(g.p((k, 0, 0)), g.p((k, 11, 0)), g.t["icon_line"], 0.6)
        g.line(g.p((0, k, 0)), g.p((11, k, 0)), g.t["icon_line"], 0.6)
    g.poly(g.ellipse2d(g.p((5.5, 5.5, 0)), 1.6, 1.6), fill=g.t["accent"], stroke=g.t["accent"], width=HAIR)


def eyeoff(g):
    top = [(12 + 9 * math.cos(math.radians(a)), 12 - 5.5 * math.sin(math.radians(a))) for a in range(0, 181, 15)]
    g.poly(top + [(12 + 9 * math.cos(math.radians(a)), 12 + 5.5 * math.sin(math.radians(a))) for a in range(180, 361, 15)][1:-1],
           stroke=g.t["text_muted"], width=HAIR)
    g.line((5, 19), (19, 5), g.t["accent"], STROKE)


# ---------------------------------------------------------------- sketch ribbon, feature options, modes
# Flat 2D in screen coordinates (y down). Geometry in icon_line, the action in accent.

def _arc2(c, r, a0, a1, n=20):
    """Screen-space arc, angles counter-clockwise as seen (y down)."""
    return [(c[0] + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             c[1] - r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]


def _rect2(a, b):
    return [a, (b[0], a[1]), b, (a[0], b[1])]


def _dot(g, c, r=2.2, color=None):
    color = color or g.t["accent"]
    g.poly(g.ellipse2d(c, r, r, 20), fill=color, stroke=color, width=HAIR)


def _ghost(g, a, b):
    g.line(a, b, g.t["text_muted"], HAIR, dash="1.5,1.5")


def _dim(g, a, b, color=None):
    """Dimension line between a and b with arrow heads at both ends."""
    m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    g.arrow(m, a, color, head=3)
    g.arrow(m, b, color, head=3)


# draw
def polyline(g):
    pts = [(4, 18), (9, 7), (14, 15), (20, 6)]
    g.poly(pts, stroke=g.t["accent"], width=STROKE, closed=False)
    for q in pts:
        g.handle(q)


def rect_center(g):
    g.poly(_rect2((4, 6), (20, 18)), stroke=g.t["accent"], width=STROKE)
    g.line((10, 12), (14, 12), g.t["icon_line"], HAIR)
    g.line((12, 10), (12, 14), g.t["icon_line"], HAIR)
    g.handle((20, 6))


def rect_rounded(g):
    r, (x0, y0, x1, y1) = 3.5, (4, 6, 20, 18)
    pts = (_arc2((x1 - r, y0 + r), r, 0, 90, 6) + _arc2((x0 + r, y0 + r), r, 90, 180, 6)
           + _arc2((x0 + r, y1 - r), r, 180, 270, 6) + _arc2((x1 - r, y1 - r), r, 270, 360, 6))
    g.poly(pts, stroke=g.t["accent"], width=STROKE)


def circle3(g):
    g.poly(g.ellipse2d((12, 12), 8, 8, 48), stroke=g.t["accent"], width=STROKE)
    for a in (200, 330, 80):
        g.handle((12 + 8 * math.cos(math.radians(a)), 12 - 8 * math.sin(math.radians(a))))


def arc(g):
    pts = _arc2((12, 16), 8, 15, 165)
    g.poly(pts, stroke=g.t["accent"], width=STROKE, closed=False)
    g.line((10.5, 16), (13.5, 16), g.t["icon_line"], HAIR)
    g.line((12, 14.5), (12, 17.5), g.t["icon_line"], HAIR)
    g.handle(pts[0])
    g.handle(pts[-1])


def arc3(g):
    pts = _arc2((12, 16), 8, 15, 165)
    g.poly(pts, stroke=g.t["accent"], width=STROKE, closed=False)
    for q in (pts[0], pts[len(pts) // 2], pts[-1]):
        g.handle(q)


def polygon(g):
    """Corners on the circle (inscribed)."""
    g.poly(g.ellipse2d((12, 12), 9, 9, 40), stroke=g.t["text_muted"], width=HAIR, dash="1.5,1.5")
    pts = [(12 + 9 * math.cos(math.radians(30 + 60 * k)), 12 + 9 * math.sin(math.radians(30 + 60 * k))) for k in range(6)]
    g.poly(pts, stroke=g.t["accent"], width=STROKE)
    _dot(g, (12, 12), 1.2, g.t["icon_line"])


def polygon_out(g):
    """Sides touching the circle (circumscribed)."""
    g.poly(g.ellipse2d((12, 12), 7.6, 7.6, 40), stroke=g.t["text_muted"], width=HAIR, dash="1.5,1.5")
    pts = [(12 + 8.77 * math.cos(math.radians(30 + 60 * k)), 12 + 8.77 * math.sin(math.radians(30 + 60 * k))) for k in range(6)]
    g.poly(pts, stroke=g.t["accent"], width=STROKE)
    _dot(g, (12, 12), 1.2, g.t["icon_line"])


def slot(g):
    pts = _arc2((16, 12), 4.5, -90, 90, 10) + _arc2((8, 12), 4.5, 90, 270, 10)
    g.poly(pts, stroke=g.t["accent"], width=STROKE)
    g.line((8, 12), (16, 12), g.t["icon_line"], HAIR, dash="1.5,1.5")


def ellipse(g):
    g.poly(g.ellipse2d((12, 12), 9, 5.5, 48), stroke=g.t["accent"], width=STROKE)
    g.line((10.5, 12), (13.5, 12), g.t["icon_line"], HAIR)
    g.line((12, 10.5), (12, 13.5), g.t["icon_line"], HAIR)


def spline(g):
    c = [(4, 17), (8, 4), (16, 20), (20, 7)]
    g.poly(c, stroke=g.t["text_muted"], width=HAIR, closed=False, dash="1.5,1.5")
    curve = []
    for i in range(25):
        t = i / 24.0
        k = ((1 - t) ** 3, 3 * t * (1 - t) ** 2, 3 * t * t * (1 - t), t ** 3)
        curve.append((sum(w * q[0] for w, q in zip(k, c)), sum(w * q[1] for w, q in zip(k, c))))
    g.poly(curve, stroke=g.t["accent"], width=STROKE, closed=False)
    for q in c:
        g.handle(q)


def spoint(g):
    g.line((5, 12), (19, 12), g.t["icon_line"], HAIR, dash="1.5,1.5")
    g.line((12, 5), (12, 19), g.t["icon_line"], HAIR, dash="1.5,1.5")
    _dot(g, (12, 12), 3)


# modify
def sk_fillet(g):
    g.line((5, 4), (5, 13), g.t["icon_line"])
    g.line((11, 19), (20, 19), g.t["icon_line"])
    g.poly(_arc2((11, 13), 6, 180, 270, 10), stroke=g.t["accent"], width=2.2, closed=False)
    _ghost(g, (5, 13), (5, 19))
    _ghost(g, (5, 19), (11, 19))


def sk_chamfer(g):
    g.line((5, 4), (5, 13), g.t["icon_line"])
    g.line((11, 19), (20, 19), g.t["icon_line"])
    g.line((5, 13), (11, 19), g.t["accent"], 2.2)
    _ghost(g, (5, 13), (5, 19))
    _ghost(g, (5, 19), (11, 19))


def trim(g):
    g.line((12, 4), (12, 20), g.t["icon_line"])
    g.line((4, 12), (12, 12), g.t["icon_line"])
    g.line((12, 12), (20, 12), g.t["accent"], STROKE, dash="2,2")
    g.line((15, 9), (19, 15), g.t["accent"], STROKE)
    g.line((15, 15), (19, 9), g.t["accent"], STROKE)


def extend(g):
    g.line((19, 4), (19, 20), g.t["icon_line"])
    g.line((4, 12), (10, 12), g.t["icon_line"])
    g.arrow((10, 12), (18.5, 12), head=3)


def sk_split(g):
    g.line((4, 19), (10.5, 13.5), g.t["icon_line"])
    g.line((13.5, 10.5), (20, 5), g.t["icon_line"])
    g.handle((10.5, 13.5))
    g.handle((13.5, 10.5))
    g.line((8, 8), (16, 16), g.t["accent"], STROKE, dash="2,1.5")


def offset(g):
    g.poly(_rect2((8.5, 9), (15.5, 15)), stroke=g.t["icon_line"], width=STROKE)
    g.poly(_rect2((4, 4.5), (20, 19.5)), stroke=g.t["accent"], width=STROKE)


def offset_round(g):
    """Offset corner choice: the outer copy's corners rounded (arc join)."""
    g.poly(_rect2((8.5, 9), (15.5, 15)), stroke=g.t["icon_line"], width=STROKE)
    r, (x0, y0, x1, y1) = 4.5, (4, 4.5, 20, 19.5)
    pts = (_arc2((x1 - r, y0 + r), r, 0, 90, 6) + _arc2((x0 + r, y0 + r), r, 90, 180, 6)
           + _arc2((x0 + r, y1 - r), r, 180, 270, 6) + _arc2((x1 - r, y1 - r), r, 270, 360, 6))
    g.poly(pts, stroke=g.t["accent"], width=STROKE)


def offset_sharp(g):
    """Offset corner choice: the outer copy's sides extended until they meet (intersection join)."""
    g.poly(_rect2((8.5, 9), (15.5, 15)), stroke=g.t["icon_line"], width=STROKE)
    g.poly(_rect2((4, 4.5), (20, 19.5)), stroke=g.t["accent"], width=STROKE)
    g.handle((20, 4.5))


def sk_mirror(g):
    g.line((12, 3), (12, 21), g.t["icon_line"], HAIR, dash="2,1.5")
    g.poly([(4, 17), (10, 17), (10, 7)], stroke=g.t["icon_line"], width=STROKE)
    g.poly([(20, 17), (14, 17), (14, 7)], stroke=g.t["accent"], width=STROKE)


def sk_move(g):
    g.poly(_rect2((4, 11), (11, 18)), stroke=g.t["icon_line"], width=STROKE)
    g.arrow((9, 13), (19, 5))


def sk_rotate(g):
    g.line((6, 18), (20, 18), g.t["icon_line"])
    g.line((6, 18), (15, 7), g.t["accent"])
    g.poly(_arc2((6, 18), 10, 5, 42, 8), stroke=g.t["accent"], width=HAIR, closed=False)
    _dot(g, (6, 18), 1.6, g.t["icon_line"])


def sk_scale(g):
    g.poly(_rect2((4, 12), (10, 18)), stroke=g.t["icon_line"], width=STROKE)
    g.poly(_rect2((4, 4), (18, 18)), stroke=g.t["accent"], width=STROKE, dash="2,1.5")
    g.arrow((10, 12), (16.5, 5.5), head=3)


def sk_array(g):
    for i in range(3):
        for j in range(2):
            a = (4 + 6 * i, 6 + 7 * j)
            col = g.t["accent"] if (i, j) == (0, 0) else g.t["icon_line"]
            g.poly(_rect2(a, (a[0] + 4, a[1] + 4)), stroke=col, width=STROKE)


def construction(g):
    g.line((4, 19), (20, 5), g.t["accent"], STROKE, dash="2.5,2")
    g.handle((4, 19))
    g.handle((20, 5))


def project(g):
    g.poly(_rect2((7, 4), (17, 9)), fill=g.t["icon_left"], stroke=g.t["icon_line"])
    g.line((7, 9), (7, 18), g.t["text_muted"], HAIR, dash="1.5,1.5")
    g.line((17, 9), (17, 18), g.t["text_muted"], HAIR, dash="1.5,1.5")
    g.line((4, 19), (20, 19), g.t["icon_line"], HAIR)
    g.line((7, 19), (17, 19), g.t["accent"], 2.4)


def carbon(g):
    g.poly(_rect2((4, 4), (15, 15)), stroke=g.t["icon_line"], width=STROKE)
    g.poly(_rect2((9, 9), (20, 20)), stroke=g.t["accent"], width=STROKE)


def sk_look(g):
    g.poly([(3, 15), (15, 15), (21, 20), (9, 20)], fill=g.t["icon_top"], stroke=g.t["icon_line"])
    g.arrow((12, 3), (12, 13))


def sk_section(g):
    g.poly(_rect2((4, 6), (20, 18)), fill=g.t["icon_left"], stroke=g.t["icon_line"])
    g.poly(_rect2((4, 6), (12, 18)), fill=g.t["icon_top"], stroke=g.t["icon_line"])
    for k in range(3):
        g.line((4, 10 + 4 * k), (8, 6 + 4 * k), g.t["accent"], HAIR)
    g.line((12, 3), (12, 21), g.t["accent"], 2.2)


# constrain
def dimension(g):
    g.line((5, 17), (19, 17), g.t["icon_line"])
    g.line((5, 17), (5, 6), g.t["icon_line"], HAIR)
    g.line((19, 17), (19, 6), g.t["icon_line"], HAIR)
    _dim(g, (5.6, 9), (18.4, 9))


def c_coincident(g):
    g.line((4, 18), (12, 12), g.t["icon_line"])
    g.line((12, 12), (20, 16), g.t["icon_line"])
    g.line((12, 12), (16, 4), g.t["icon_line"])
    _dot(g, (12, 12), 2.8)


def c_pointon(g):
    g.line((4, 19), (20, 5), g.t["icon_line"])
    g.poly(g.ellipse2d((12, 12), 3.6, 3.6, 24), stroke=g.t["accent"], width=HAIR)
    _dot(g, (12, 12), 1.8)


def c_horizontal(g):
    _ghost(g, (4, 18), (20, 8))
    g.line((4, 12), (20, 12), g.t["accent"], 2.2)
    g.handle((4, 12))
    g.handle((20, 12))


def c_vertical(g):
    _ghost(g, (6, 4), (17, 20))
    g.line((12, 4), (12, 20), g.t["accent"], 2.2)
    g.handle((12, 4))
    g.handle((12, 20))


def c_parallel(g):
    g.line((4, 15), (14, 5), g.t["accent"], 2.2)
    g.line((10, 19), (20, 9), g.t["accent"], 2.2)


def c_perpendicular(g):
    g.line((4, 19), (20, 19), g.t["icon_line"])
    g.line((9, 19), (9, 4), g.t["accent"], 2.2)
    g.poly([(9, 15), (13, 15), (13, 19)], stroke=g.t["icon_line"], width=HAIR, closed=False)


def c_tangent(g):
    g.poly(g.ellipse2d((11, 14), 6, 6, 40), stroke=g.t["icon_line"], width=STROKE)
    g.line((3, 8), (20, 8), g.t["accent"], 2.2)
    _dot(g, (11, 8), 1.5, g.t["icon_line"])


def c_equal(g):
    for y in (7, 17):
        g.line((4, y), (20, y), g.t["icon_line"])
        for x in (10.5, 13.5):
            g.line((x, y - 3), (x, y + 3), g.t["accent"], STROKE)


def c_symmetric(g):
    g.line((12, 3), (12, 21), g.t["icon_line"], HAIR, dash="2,1.5")
    g.line((5, 12), (19, 12), g.t["text_muted"], HAIR)
    _dot(g, (5, 12), 2.4)
    _dot(g, (19, 12), 2.4)


def c_midpoint(g):
    g.line((4, 18), (20, 6), g.t["icon_line"])
    g.handle((4, 18))
    g.handle((20, 6))
    _dot(g, (12, 12), 3.2)


def c_block(g):
    g.line((4, 19), (20, 5), g.t["icon_line"])
    g.poly(_rect2((8.5, 8.5), (15.5, 15.5)), fill=g.t["accent"], stroke=g.t["icon_line"], width=HAIR)


def c_lock(g):
    g.handle((6, 17))
    g.poly(_arc2((15, 11), 3.2, 0, 180, 10), stroke=g.t["accent"], width=STROKE, closed=False)
    g.poly(_rect2((10.5, 11), (19.5, 19)), fill=g.t["accent"], stroke=g.t["accent"], width=HAIR)


def c_hdist(g):
    g.handle((5, 17))
    g.handle((19, 17))
    g.line((5, 15), (5, 6), g.t["icon_line"], HAIR)
    g.line((19, 15), (19, 6), g.t["icon_line"], HAIR)
    _dim(g, (5.6, 9), (18.4, 9))


def c_vdist(g):
    g.handle((17, 5))
    g.handle((17, 19))
    g.line((15, 5), (6, 5), g.t["icon_line"], HAIR)
    g.line((15, 19), (6, 19), g.t["icon_line"], HAIR)
    _dim(g, (9, 5.6), (9, 18.4))


def c_dist(g):
    g.handle((6, 19))
    g.handle((19, 6))
    _dim(g, (4, 14), (14, 4))


def c_radius(g):
    g.poly(_arc2((5, 19), 14, 0, 90, 16), stroke=g.t["icon_line"], width=STROKE, closed=False)
    g.arrow((5, 19), (5 + 14 * 0.7071, 19 - 14 * 0.7071))
    _dot(g, (5, 19), 1.4, g.t["icon_line"])


def c_diameter(g):
    g.poly(g.ellipse2d((12, 12), 8.5, 8.5, 48), stroke=g.t["icon_line"], width=STROKE)
    _dim(g, (6.3, 17.7), (17.7, 6.3))


def c_angle(g):
    g.line((4, 19), (20, 19), g.t["icon_line"])
    g.line((4, 19), (16, 5), g.t["icon_line"])
    g.poly(_arc2((4, 19), 10, 0, 49, 10), stroke=g.t["accent"], width=STROKE, closed=False)


def c_driving(g):
    g.line((5, 17), (5, 6), g.t["icon_line"], HAIR)
    g.line((19, 17), (19, 6), g.t["icon_line"], HAIR)
    g.line((5, 17), (19, 17), g.t["icon_line"])
    g.line((6, 9), (18, 9), g.t["accent"], STROKE, dash="2,1.5")
    g.poly([(8, 6.5), (6, 9), (8, 11.5)], stroke=g.t["accent"], width=HAIR, closed=False)
    g.poly([(16, 6.5), (18, 9), (16, 11.5)], stroke=g.t["accent"], width=HAIR, closed=False)


# feature options
def _slab(g, a, b):
    g.poly(_rect2(a, b), fill=g.t["icon_left"], stroke=g.t["icon_line"])


def ext_distance(g):
    _slab(g, (4, 15), (20, 20))
    g.arrow((12, 15), (12, 5))
    g.line((8, 4), (16, 4), g.t["icon_line"], HAIR)


def ext_toface(g):
    _slab(g, (4, 15), (20, 20))
    g.poly(_rect2((3, 4), (21, 7)), fill=g.t["icon_right"], stroke=g.t["icon_line"])
    g.arrow((12, 15), (12, 7.5))


def ext_through(g):
    _slab(g, (4, 9), (20, 15))
    g.arrow((12, 21), (12, 3))


def side_one(g):
    g.line((4, 18), (20, 18), g.t["icon_line"], 2.4)
    g.arrow((12, 18), (12, 4))


def side_two(g):
    g.line((4, 14), (20, 14), g.t["icon_line"], 2.4)
    g.arrow((12, 14), (12, 3))
    g.arrow((12, 14), (12, 21))


def side_symmetric(g):
    g.line((4, 12), (20, 12), g.t["icon_line"], 2.4)
    g.arrow((12, 12), (12, 3))
    g.arrow((12, 12), (12, 21))
    g.line((5, 3), (8, 3), g.t["icon_line"], HAIR)
    g.line((5, 21), (8, 21), g.t["icon_line"], HAIR)


_A, _B = ((4, 8), (14, 18)), ((10, 4), (20, 14))


def op_auto(g):
    g.poly(_rect2(*_A), stroke=g.t["icon_line"], width=STROKE)
    g.poly(_rect2(*_B), stroke=g.t["icon_line"], width=STROKE, dash="2,1.5")
    star = [(17 + (3.5 if k % 2 == 0 else 1.2) * math.cos(math.pi * k / 4),
             17 + (3.5 if k % 2 == 0 else 1.2) * math.sin(math.pi * k / 4)) for k in range(8)]
    g.poly(star, fill=g.t["accent"], stroke=g.t["accent"], width=HAIR)


def op_join(g):
    g.poly([(4, 8), (10, 8), (10, 4), (20, 4), (20, 14), (14, 14), (14, 18), (4, 18)], fill=g.t["accent"], stroke=g.t["icon_line"])


def op_cut(g):
    g.poly([(4, 8), (10, 8), (10, 14), (14, 14), (14, 18), (4, 18)], fill=g.t["icon_left"], stroke=g.t["icon_line"])
    g.poly(_rect2(*_B), stroke=g.t["accent"], width=STROKE, dash="2,1.5")


def op_intersect(g):
    g.poly(_rect2(*_A), stroke=g.t["icon_line"], width=HAIR)
    g.poly(_rect2(*_B), stroke=g.t["icon_line"], width=HAIR)
    g.poly(_rect2((10, 8), (14, 14)), fill=g.t["accent"], stroke=g.t["accent"], width=HAIR)


def op_newbody(g):
    g.poly(_rect2((4, 10), (12, 18)), fill=g.t["icon_left"], stroke=g.t["icon_line"])
    g.poly(_rect2((14, 12), (20, 18)), fill=g.t["accent"], stroke=g.t["icon_line"])
    g.line((17, 4), (17, 10), g.t["accent"], STROKE)
    g.line((14, 7), (20, 7), g.t["accent"], STROKE)


def hole_simple(g):
    _slab(g, (4, 6), (10, 20))
    _slab(g, (14, 6), (20, 20))
    g.line((10, 6), (10, 20), g.t["accent"], STROKE)
    g.line((14, 6), (14, 20), g.t["accent"], STROKE)


def hole_counterbore(g):
    g.poly([(4, 6), (8, 6), (8, 11), (10, 11), (10, 20), (4, 20)], fill=g.t["icon_left"], stroke=g.t["icon_line"])
    g.poly([(20, 6), (16, 6), (16, 11), (14, 11), (14, 20), (20, 20)], fill=g.t["icon_left"], stroke=g.t["icon_line"])
    g.poly([(8, 6), (8, 11), (10, 11), (10, 20)], stroke=g.t["accent"], width=STROKE, closed=False)
    g.poly([(16, 6), (16, 11), (14, 11), (14, 20)], stroke=g.t["accent"], width=STROKE, closed=False)


def hole_countersink(g):
    g.poly([(4, 6), (7, 6), (10, 9), (10, 20), (4, 20)], fill=g.t["icon_left"], stroke=g.t["icon_line"])
    g.poly([(20, 6), (17, 6), (14, 9), (14, 20), (20, 20)], fill=g.t["icon_left"], stroke=g.t["icon_line"])
    g.poly([(7, 6), (10, 9), (10, 20)], stroke=g.t["accent"], width=STROKE, closed=False)
    g.poly([(17, 6), (14, 9), (14, 20)], stroke=g.t["accent"], width=STROKE, closed=False)


def hole_tapped(g):
    hole_simple(g)
    for y in range(8, 20, 3):
        g.line((10, y), (11.5, y + 1.5), g.t["accent"], HAIR)
        g.line((14, y), (12.5, y + 1.5), g.t["accent"], HAIR)


# modes and selection
def drawing(g):
    g.poly(_rect2((3, 4), (21, 20)), fill=g.t["surface"], stroke=g.t["icon_line"])
    g.poly(_rect2((6, 9), (13, 15)), stroke=g.t["icon_line"], width=HAIR)
    _dim(g, (6.3, 7), (12.7, 7))
    g.line((14, 17), (21, 17), g.t["icon_line"], HAIR)
    g.line((14, 17), (14, 20), g.t["icon_line"], HAIR)


def simulate(g):
    g.line((4, 4), (4, 20), g.t["icon_line"], 2.4)
    g.poly(_rect2((4, 10), (18, 14)), fill=g.t["icon_left"], stroke=g.t["icon_line"])
    g.poly([(4, 10), (11, 11), (18, 14)], stroke=g.t["accent"], width=HAIR, closed=False, dash="1.5,1.5")
    g.arrow((18, 3), (18, 9.5))


def render_mode(g):
    g.poly(g.ellipse2d((11, 13), 8, 8, 48), fill=g.t["icon_left"], stroke=g.t["icon_line"])
    g.poly(g.ellipse2d((8.5, 10.5), 2.6, 2, 20), fill=g.t["icon_top"], stroke=g.t["icon_top"], width=HAIR)
    for a in (0, 45, 90):
        c, s = math.cos(math.radians(a)), math.sin(math.radians(a))
        g.line((19 - 1.5 * c, 5 + 1.5 * s), (19 - 4 * c, 5 + 4 * s), g.t["accent"], STROKE)
    _dot(g, (19.5, 4.5), 1.6)


def delete(g):
    g.poly([(6.5, 8), (17.5, 8), (16.5, 21), (7.5, 21)], fill=g.t["icon_left"], stroke=g.t["icon_line"])
    g.line((4, 6), (20, 6), g.t["icon_line"], STROKE)
    g.line((10, 4), (14, 4), g.t["icon_line"], STROKE)
    g.line((9.5, 11), (14.5, 18), g.t["accent"], 2.2)
    g.line((14.5, 11), (9.5, 18), g.t["accent"], 2.2)


def select(g):
    g.poly([(6, 3), (6, 18), (9.8, 14.5), (12.5, 20.5), (15, 19.4), (12.3, 13.5), (17.5, 13.3)],
           fill=g.t["accent"], stroke=g.t["icon_line"], width=HAIR)


# drawing mode: a sheet, its views and annotations
def _sheet(g, a=(4, 3), b=(20, 21)):
    g.poly(_rect2(a, b), fill=g.t["surface"], stroke=g.t["icon_line"])


def new_drawing(g):
    _sheet(g, (3, 4), (17, 21))
    g.line((17, 4), (21, 4), g.t["accent"], 2.2)
    g.line((19, 2), (19, 6), g.t["accent"], 2.2)
    g.poly(_rect2((6, 9), (12, 14)), stroke=g.t["icon_line"], width=HAIR)
    g.line((9, 17), (17, 17), g.t["icon_line"], HAIR)


def view_base(g):
    _sheet(g)
    g.poly(_rect2((7, 8), (16, 15)), fill=g.t["accent"], stroke=g.t["icon_line"])


def view_proj(g):
    _sheet(g)
    g.poly(_rect2((6, 7), (11, 12)), fill=g.t["icon_left"], stroke=g.t["icon_line"])
    g.poly(_rect2((14, 7), (18, 12)), stroke=g.t["accent"], width=STROKE, dash="1.5,1")
    g.poly(_rect2((6, 15), (11, 19)), stroke=g.t["accent"], width=STROKE, dash="1.5,1")
    g.arrow((11.5, 9.5), (14.5, 9.5), head=2.4)


def section_view(g):
    g.poly(_rect2((4, 7), (20, 17)), fill=g.t["icon_left"], stroke=g.t["icon_line"])
    for k in range(4):
        g.line((5 + 3.6 * k, 16), (9 + 3.6 * k, 8), g.t["icon_line"], HAIR)
    g.line((3, 4), (21, 4), g.t["accent"], STROKE, dash="3,1.5")
    g.arrow((3.5, 4), (3.5, 1.5), head=2)
    g.arrow((20.5, 4), (20.5, 1.5), head=2)


def detail_view(g):
    _sheet(g)
    g.poly([(6, 17), (6, 9), (14, 9)], stroke=g.t["icon_line"], width=STROKE, closed=False)
    g.poly(g.ellipse2d((8, 11), 4, 4, 32), stroke=g.t["accent"], width=STROKE)
    g.line((11, 14), (15, 18), g.t["accent"], STROKE)
    g.poly(g.ellipse2d((16.5, 17.5), 2.6, 2.6, 24), fill=g.t["accent"], stroke=g.t["accent"], width=HAIR)


def callout(g):
    g.poly(g.ellipse2d((8, 15), 4, 4, 32), stroke=g.t["icon_line"], width=STROKE)
    g.line((10.8, 12.2), (15, 6), g.t["accent"], STROKE)
    g.line((15, 6), (21, 6), g.t["accent"], STROKE)
    g.poly(g.ellipse2d((17, 3.6), 1.4, 1.4, 16), stroke=g.t["accent"], width=HAIR)
    g.line((15.6, 5), (18.4, 2.2), g.t["accent"], HAIR)


def balloon(g):
    g.poly(g.ellipse2d((15, 8), 5.5, 5.5, 36), fill=g.t["surface"], stroke=g.t["accent"], width=STROKE)
    g.line((10.5, 11.5), (5, 19), g.t["icon_line"])
    _dot(g, (5, 19), 1.4, g.t["icon_line"])
    g.line((15, 5.5), (15, 10.5), g.t["accent"], STROKE)


def parts_list(g):
    g.poly(_rect2((3, 5), (21, 19)), fill=g.t["surface"], stroke=g.t["icon_line"])
    g.poly(_rect2((3, 5), (21, 9)), fill=g.t["accent"], stroke=g.t["icon_line"])
    for y in (12.5, 16):
        g.line((3, y), (21, y), g.t["icon_line"], HAIR)
    g.line((8, 5), (8, 19), g.t["icon_line"], HAIR)


def _export(g, label_lines):
    _sheet(g, (4, 3), (16, 19))
    for y in label_lines:
        g.line((6.5, y), (13.5, y), g.t["icon_line"], HAIR)
    g.arrow((12, 15), (21, 15), head=3)


def export_pdf(g):
    _export(g, (7, 9.5))


def export_dxf(g):
    _export(g, (7,))
    g.poly(g.ellipse2d((10, 10), 2, 2, 16), stroke=g.t["icon_line"], width=HAIR)


ICONS = {
    "extrude": (extrude, "feature"), "revolve": (revolve, "feature"), "fillet": (fillet, "feature"),
    "hole": (hole, "feature"), "shell": (shell, "feature"),
    "sketch": (sketch, "sketch"), "line": (line, "sketch"), "rectangle": (rectangle, "sketch"),
    "circle": (circle, "sketch"),
    "joint": (joint, "assembly"), "measure": (measure, "inspect"), "toolpath": (toolpath, "cam"),
    "app": (app, "app"),
    # M2
    "chamfer": (chamfer, "feature"), "draft": (draft, "feature"), "facepull": (facepull, "feature"),
    "deleteface": (deleteface, "feature"), "combine": (combine, "feature"), "split": (split, "feature"),
    "move": (move, "feature"), "scale": (scale, "feature"), "mirror": (mirror, "feature"),
    "pattern": (pattern, "feature"), "patterncirc": (patterncirc, "feature"), "thread": (thread, "feature"),
    "sweep": (sweep, "feature"), "loft": (loft, "feature"), "box": (box, "feature"), "cylinder": (cylinder, "feature"),
    "sphere": (sphere, "feature"), "cone": (cone, "feature"), "torus": (torus, "feature"),
    "plane": (plane, "reference"), "axis": (axis, "reference"), "point": (point, "reference"),
    "parameters": (parameters, "app"), "material": (material, "app"),
    "mass": (mass, "inspect"), "interference": (interference, "inspect"), "section": (section, "inspect"),
    "draftanalysis": (draftanalysis, "inspect"), "finish": (finish, "sketch"), "home": (home, "view"),
    "orbit": (orbit, "view"), "pan": (pan, "view"), "zoom": (zoom, "view"), "import_step": (import_step, "file"),
    "feature": (feature, "feature"),
    # browser
    "body": (body, "browser"), "component": (component, "browser"), "folder": (folder, "browser"),
    "settings": (settings, "browser"), "views": (views, "browser"), "eye": (eye, "browser"), "eyeoff": (eyeoff, "browser"),
    "grid": (grid, "view"),
    # sketch ribbon, feature options, modes
    "polyline": (polyline, "sketch"), "rect_center": (rect_center, "sketch"), "rect_rounded": (rect_rounded, "sketch"), "circle3": (circle3, "sketch"),
    "arc": (arc, "sketch"), "arc3": (arc3, "sketch"), "polygon": (polygon, "sketch"), "slot": (slot, "sketch"),
    "ellipse": (ellipse, "sketch"), "spline": (spline, "sketch"), "spoint": (spoint, "sketch"), "sk_fillet": (sk_fillet, "sketch"),
    "sk_chamfer": (sk_chamfer, "sketch"), "trim": (trim, "sketch"), "extend": (extend, "sketch"), "sk_split": (sk_split, "sketch"),
    "offset": (offset, "sketch"), "offset_round": (offset_round, "sketch"), "offset_sharp": (offset_sharp, "sketch"), "sk_mirror": (sk_mirror, "sketch"), "sk_move": (sk_move, "sketch"), "sk_rotate": (sk_rotate, "sketch"),
    "sk_scale": (sk_scale, "sketch"), "sk_array": (sk_array, "sketch"), "construction": (construction, "sketch"), "project": (project, "sketch"),
    "carbon": (carbon, "sketch"), "sk_look": (sk_look, "sketch"), "sk_section": (sk_section, "sketch"), "dimension": (dimension, "sketch"),
    "c_coincident": (c_coincident, "sketch"), "c_pointon": (c_pointon, "sketch"), "c_midpoint": (c_midpoint, "sketch"),
    "c_horizontal": (c_horizontal, "sketch"), "c_vertical": (c_vertical, "sketch"),
    "c_parallel": (c_parallel, "sketch"), "c_perpendicular": (c_perpendicular, "sketch"), "c_tangent": (c_tangent, "sketch"), "c_equal": (c_equal, "sketch"),
    "c_symmetric": (c_symmetric, "sketch"), "c_block": (c_block, "sketch"), "c_lock": (c_lock, "sketch"), "c_hdist": (c_hdist, "sketch"),
    "c_vdist": (c_vdist, "sketch"), "c_dist": (c_dist, "sketch"), "c_radius": (c_radius, "sketch"), "c_diameter": (c_diameter, "sketch"),
    "c_angle": (c_angle, "sketch"), "c_driving": (c_driving, "sketch"), "ext_distance": (ext_distance, "option"), "ext_toface": (ext_toface, "option"),
    "ext_through": (ext_through, "option"), "side_one": (side_one, "option"), "side_two": (side_two, "option"), "side_symmetric": (side_symmetric, "option"),
    "op_auto": (op_auto, "option"), "op_join": (op_join, "option"), "op_cut": (op_cut, "option"), "op_intersect": (op_intersect, "option"),
    "op_newbody": (op_newbody, "option"), "hole_simple": (hole_simple, "option"), "hole_counterbore": (hole_counterbore, "option"), "hole_countersink": (hole_countersink, "option"),
    "hole_tapped": (hole_tapped, "option"), "drawing": (drawing, "mode"), "simulate": (simulate, "mode"), "render": (render_mode, "mode"),
    "select": (select, "app"), "delete": (delete, "app"), "polygon_out": (polygon_out, "sketch"),
    "new_drawing": (new_drawing, "drawing"), "view_base": (view_base, "drawing"), "view_proj": (view_proj, "drawing"),
    "section_view": (section_view, "drawing"), "detail_view": (detail_view, "drawing"), "callout": (callout, "drawing"),
    "balloon": (balloon, "drawing"), "parts_list": (parts_list, "drawing"), "export_pdf": (export_pdf, "file"),
    "export_dxf": (export_dxf, "file"),
}


def render(name, theme, accent=None):
    tone = palette.theme(theme)
    if accent:
        tone["accent"] = palette.accent(accent)
    g = Icon(tone)
    ICONS[name][0](g)
    return g.svg()


def write_all(out=ROOT / "Kovac" / "Resources" / "icons"):
    for theme in palette.THEMES:
        d = out / theme
        d.mkdir(parents=True, exist_ok=True)
        for name in ICONS:
            (d / ("%s.svg" % name)).write_text(render(name, theme), encoding="utf-8")
    return out


# ---------------------------------------------------------------- review pages

def _img(svg, px):
    return '<img width="%s" height="%s" alt="" src="data:image/svg+xml;base64,%s">' % (
        px, px, base64.b64encode(svg.encode()).decode())


def contact_sheet():
    import cubevariants  # same folder
    rows = []
    for theme in palette.THEMES:
        t = palette.theme(theme)
        cells = []
        for name, (_, family) in ICONS.items():
            svg = render(name, theme)
            sizes = "".join('<div class="sz">%s<span>%d@%g×</span></div>' % (_img(svg, s * k), s, k)
                            for k in (1, 1.5, 2) for s in (16, 24, 32))
            cells.append('<div class="icon"><b>%s</b> <i>%s</i><div class="row">%s</div></div>' % (name, family, sizes))
        big = "".join('<figure>%s<figcaption>%s</figcaption></figure>' % (_img(render(n, theme), 96), n) for n in ICONS)
        rows.append('<section style="background:%s;color:%s"><h2>%s theme · accent “%s”</h2>%s%s</section>'
                    % (t["bg"], t["text"], theme, palette.ACCENT, big, "".join(cells)))
    accents = []
    for key, col in palette.ACCENTS.items():
        strip = "".join(_img(render(n, th, key), 32) for th in palette.THEMES for n in ICONS)
        accents.append('<div class="acc"><span class="sw" style="background:%s"></span><b>%s</b> %s<div>%s</div></div>'
                       % (col, key, col, strip))
    sem = "".join('<span class="chip"><span class="sw" style="background:%s"></span>%s</span>' % (v, k)
                  for k, v in palette.SEMANTIC.items())
    cubes = "".join('<figure>%s<figcaption>%s</figcaption></figure>' % (svg, cap) for cap, svg in cubevariants.all_variants())
    return """<!doctype html><html><head><meta charset="utf-8"><title>Kovač icon sheet</title>
<style>
body{font:14px %s;margin:0;background:#fff;color:#1C2026}
h1,h2{font-weight:600} h1{padding:16px 24px 0}
section{padding:8px 24px 24px}
.icon{display:inline-block;margin:8px 12px 8px 0;vertical-align:top}
.icon i{opacity:.6;font-size:12px}
.row{display:flex;align-items:flex-end;gap:10px;margin-top:4px}
.sz{display:flex;flex-direction:column;align-items:center;font-size:10px;opacity:.9}
.acc{margin:10px 0}.acc div{margin-top:6px;display:flex;gap:6px;flex-wrap:wrap}
.sw{display:inline-block;width:14px;height:14px;border-radius:3px;vertical-align:-2px;margin-right:6px}
.chip{display:inline-block;margin:0 14px 6px 0}
figure{display:inline-block;margin:8px 16px 8px 0;text-align:center} figcaption{font-size:12px;max-width:340px}
</style></head><body>
<h1>Kovač — icon and cube review sheet</h1>
<section><h2>Accent proposals (pick one)</h2>%s<h2>Semantic colors</h2>%s</section>
%s
<section><h2>Orientation cube variants (pick one)</h2>%s</section>
</body></html>""" % (palette.FONT_UI, "".join(accents), sem, "".join(rows), cubes)


if __name__ == "__main__":
    sys.exit("use: py tools/build_assets.py")

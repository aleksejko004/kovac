# SPDX-License-Identifier: LGPL-2.1-or-later
"""ISO 286 limits and fits for nominal sizes up to 500 mm: standard tolerance grades IT5–IT11
and the fundamental deviations of the common hole (D–H, JS) and shaft (d–h, js, k–p) classes.
Pure Python. Values in micrometres from the ISO 286-1/-2 tables."""
import bisect
import re

# upper limits of the nominal size ranges (a size equal to a limit belongs to that range)
RANGES = [3, 6, 10, 18, 30, 50, 80, 120, 180, 250, 315, 400, 500]
IT = {
    5: [4, 5, 6, 8, 9, 11, 13, 15, 18, 20, 23, 25, 27],
    6: [6, 8, 9, 11, 13, 16, 19, 22, 25, 29, 32, 36, 40],
    7: [10, 12, 15, 18, 21, 25, 30, 35, 40, 46, 52, 57, 63],
    8: [14, 18, 22, 27, 33, 39, 46, 54, 63, 72, 81, 89, 97],
    9: [25, 30, 36, 43, 52, 62, 74, 87, 100, 115, 130, 140, 155],
    10: [40, 48, 58, 70, 84, 100, 120, 140, 160, 185, 210, 230, 250],
    11: [60, 75, 90, 110, 130, 160, 190, 220, 250, 290, 320, 360, 400],
}
# shafts: upper deviation es (d–h) or lower deviation ei (k–p)
SHAFT_ES = {
    "d": [-20, -30, -40, -50, -65, -80, -100, -120, -145, -170, -190, -210, -230],
    "e": [-14, -20, -25, -32, -40, -50, -60, -72, -85, -100, -110, -125, -135],
    "f": [-6, -10, -13, -16, -20, -25, -30, -36, -43, -50, -56, -62, -68],
    "g": [-2, -4, -5, -6, -7, -9, -10, -12, -14, -15, -17, -18, -20],
    "h": [0] * 13,
}
SHAFT_EI = {     # k for grades 4–7
    "k": [0, 1, 1, 1, 2, 2, 2, 3, 3, 4, 4, 4, 5],
    "m": [2, 4, 6, 7, 8, 9, 11, 13, 15, 17, 20, 21, 23],
    "n": [4, 8, 10, 12, 15, 17, 20, 23, 27, 31, 34, 37, 40],
    "p": [6, 12, 15, 18, 22, 26, 32, 37, 43, 50, 56, 62, 68],
}
FIT = re.compile(r"^\s*([A-Za-z]{1,2})\s*(\d{1,2})\s*$")


def _row(size):
    if not 0 < size <= RANGES[-1]:
        raise ValueError("ISO 286 here covers sizes up to %d mm." % RANGES[-1])
    return bisect.bisect_left(RANGES, size)


def tolerance(size, grade):
    """IT value in mm."""
    if grade not in IT:
        raise ValueError("Grade IT%s is not in the table (IT5–IT11)." % grade)
    return IT[grade][_row(size)] / 1000.0


def limits(size, fit):
    """(upper, lower) deviation in mm for e.g. limits(10, "H7") -> (0.015, 0.0)."""
    m = FIT.match(fit)
    if not m:
        raise ValueError("A fit looks like H7 or g6.")
    letter, grade = m.group(1), int(m.group(2))
    t = tolerance(size, grade)
    i = _row(size)
    if letter.lower() == "js":
        return t / 2, -t / 2
    if letter.isupper():                       # holes mirror the shafts of the same letter (D–H)
        shaft = letter.lower()
        if shaft not in SHAFT_ES:
            raise ValueError("Hole class %s is not in the table (D–H, JS)." % letter)
        ei = -SHAFT_ES[shaft][i] / 1000.0
        return ei + t, ei
    if letter in SHAFT_ES:
        es = SHAFT_ES[letter][i] / 1000.0
        return es, es - t
    if letter in SHAFT_EI:
        ei = SHAFT_EI[letter][i] / 1000.0
        return ei + t, ei
    raise ValueError("Shaft class %s is not in the table (d–h, js, k–p)." % letter)


def label(size, fit):
    """'Ø10 H7 (+0.015/0)' style text for a callout or dimension."""
    up, lo = limits(size, fit)
    f = lambda v: "0" if abs(v) < 1e-9 else "%+.3f" % v  # noqa: E731
    return "%s %s (%s/%s)" % (("%g" % size), fit, f(up), f(lo))


if __name__ == "__main__":
    assert limits(10, "H7") == (0.015, 0.0)
    assert limits(25, "g6") == (-0.007, -0.020)
    print("ok")

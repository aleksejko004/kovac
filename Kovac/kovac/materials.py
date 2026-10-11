# SPDX-License-Identifier: LGPL-2.1-or-later
"""Material library: physical properties (typical room-temperature values from public
engineering handbooks, see docs/PROVENANCE.md) and a default appearance colour."""

# key: (name, density kg/m³, Young's modulus GPa, colour)
LIBRARY = {
    "steel": ("Structural steel S235", 7850, 210, "#8A9199"),
    "stainless": ("Stainless steel 1.4301 (304)", 8000, 193, "#B4BAC1"),
    "aluminium_6061": ("Aluminium 6061-T6", 2700, 68.9, "#C9CED4"),
    "aluminium_7075": ("Aluminium 7075-T6", 2810, 71.7, "#BEC4CB"),
    "brass": ("Brass CuZn39Pb3", 8470, 97, "#C8A44A"),
    "copper": ("Copper Cu-ETP", 8960, 117, "#C27A4E"),
    "titanium": ("Titanium Grade 5", 4430, 114, "#9EA1A6"),
    "pla": ("PLA", 1240, 3.5, "#E8E4D8"),
    "petg": ("PETG", 1270, 2.1, "#D6E4EA"),
    "abs": ("ABS", 1040, 2.3, "#E9E6E0"),
    "nylon": ("Nylon PA6", 1140, 2.8, "#EFEBDD"),
    "pom": ("POM (acetal)", 1410, 2.9, "#F2F0EA"),
    "birch_plywood": ("Birch plywood", 680, 8.0, "#D9B98A"),
    "oak": ("Oak", 750, 11.0, "#B48A5A"),
    "mdf": ("MDF", 750, 3.5, "#B89B78"),
}


def density(key):
    """kg/m³; None if unknown."""
    return LIBRARY[key][1] if key in LIBRARY else None


def mass_properties(shape, key=None):
    """Volume (mm³), area (mm²), mass (kg, needs a material), centre of mass, principal moments."""
    rho = density(key)
    solids = shape.Solids
    centre = None
    if solids:          # a compound has no centre of mass of its own: weight its solids by volume
        vol = sum(s.Volume for s in solids)
        centre = sum((s.CenterOfMass * s.Volume for s in solids[1:]), solids[0].CenterOfMass * solids[0].Volume) * (1 / vol)
    out = {"volume": shape.Volume, "area": shape.Area, "center": centre}
    out["mass"] = rho * shape.Volume * 1e-9 if rho else None
    if shape.Solids:
        props = shape.Solids[0].PrincipalProperties if len(shape.Solids) == 1 else None
        out["moments"] = props["Moments"] if props else None
    return out

# SPDX-License-Identifier: LGPL-2.1-or-later
"""Regenerate every generated asset: icons, review sheet, preference packs, drawing sheets.

    py tools/build_assets.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "Kovac")]

import icongen  # noqa: E402
import templategen  # noqa: E402
from kovac import theme  # noqa: E402

print("icons ->", icongen.write_all())
sheet = os.path.join(os.path.dirname(HERE), "docs", "icons", "contact-sheet.html")
os.makedirs(os.path.dirname(sheet), exist_ok=True)
with open(sheet, "w", encoding="utf-8") as f:
    f.write(icongen.contact_sheet())
print("sheet ->", sheet)
theme.write_prefpacks()
print("preference packs ->", theme.ADDON)
print("drawing sheets ->", templategen.write_all())

# SPDX-License-Identifier: LGPL-2.1-or-later
"""Launch the branded build (dist/make_dist.py output) on an empty profile and check it
comes up as Kovač.    py tests/run_dist.py"""
import glob
import io
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "Kovac"))
from kovac import palette  # noqa: E402

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

dist = sorted(glob.glob(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Kovac", "dist", "Kovac-*")))[-1]
out = os.path.join(ROOT, "build", "m1", "dist.json")
home = tempfile.mkdtemp(prefix="kovac-dist-")      # empty: the branded template must fill it
env = dict(os.environ, FREECAD_USER_HOME=home, KOVAC_RESULT=out)
exe = os.path.join(dist, "bin", "FreeCAD.exe" if os.name == "nt" else "FreeCAD")
proc = subprocess.Popen([exe, os.path.join(ROOT, "tests", "gui_dist_probe.py")], env=env)
try:
    proc.wait(timeout=120)
except subprocess.TimeoutExpired:
    subprocess.call(["taskkill", "/F", "/T", "/PID", str(proc.pid)])
res = json.load(open(out))
checks = {
    "title is Kovač, without a FreeCAD version": "Kovač" in res["window_title"] and "1.1" not in res["window_title"],
    "starts in the Kovač workbench": res["workbench"] == "KovacWorkbench",
    "stock UI hidden": not res["menubar_visible"] and not res["stock_toolbars_visible"],
    "Kovač start page shown": res["start_page"],
    "first-start profile from the Kovač template": res["selection_color"] == palette.packed_rgba(palette.SEMANTIC["select"]),
}
print(json.dumps(res, indent=1, ensure_ascii=False))
for k, v in checks.items():
    print("PASS" if v else "FAIL", k)
sys.exit(0 if all(checks.values()) else 1)

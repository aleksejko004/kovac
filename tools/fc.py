# SPDX-License-Identifier: LGPL-2.1-or-later
"""Run FreeCAD (GUI or headless) with the Kovač addon loaded via -M and an isolated user home.

    python tools/fc.py cmd  script.py      # headless FreeCADCmd
    python tools/fc.py gui  [script.py]    # GUI; the script runs after startup
    python tools/fc.py gui  --real-home    # use your normal FreeCAD settings

FreeCAD is found via $KOVAC_FREECAD (folder containing bin/), else the portable copy in
%LOCALAPPDATA%/Kovac/tools, else FreeCAD on PATH.
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON = os.path.join(ROOT, "Kovac")


def freecad_bin(gui):
    names = ["FreeCAD", "freecad"] if gui else ["FreeCADCmd", "freecadcmd"]
    names = [n + ".exe" for n in names] if os.name == "nt" else names
    roots = [os.environ.get("KOVAC_FREECAD", "")]
    roots += sorted(glob.glob(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Kovac", "tools", "FreeCAD_*")), reverse=True)
    for r in filter(None, roots):
        for sub in ("bin", os.path.join("usr", "bin")):   # portable zip / extracted AppImage
            for n in names:
                if os.path.isfile(os.path.join(r, sub, n)):
                    return os.path.join(r, sub, n)
    for n in names:
        if shutil.which(n):
            return shutil.which(n)
    sys.exit("FreeCAD not found: set KOVAC_FREECAD to the folder that contains bin/")


def main(argv):
    gui = argv[0] == "gui"
    args = [a for a in argv[1:] if a != "--real-home"]
    env = dict(os.environ)
    if "--real-home" not in argv:
        home = env.get("KOVAC_TEST_HOME") or tempfile.mkdtemp(prefix="kovac-home-")
        os.makedirs(home, exist_ok=True)
        cfg = os.path.join(home, "user.cfg")
        if not os.path.exists(cfg):  # fresh profile = what the branded build starts with
            sys.path.insert(0, ADDON)
            from kovac import theme
            with open(cfg, "w", encoding="utf-8") as f:
                f.write(theme.user_template("dark"))
        env["FREECAD_USER_HOME"] = home
    cmd = [freecad_bin(gui), "-M", ADDON] + [os.path.abspath(a) if a.endswith(".py") else a for a in args]
    return subprocess.call(cmd, env=env, cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["gui"]))

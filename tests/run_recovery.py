# SPDX-License-Identifier: LGPL-2.1-or-later
"""Autosave + crash-recovery check (Windows; ~2.5 min):

1. FreeCAD edits an unsaved document, waits for autosave, then dies without cleanup.
2. FreeCAD starts again on the same profile; it must offer "Document Recovery".

    py tests/run_recovery.py
"""
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "Kovac"))
from kovac import theme  # noqa: E402

OUT = os.path.join(ROOT, "build", "m1", "recovery.json")
os.makedirs(os.path.dirname(OUT), exist_ok=True)
home = tempfile.mkdtemp(prefix="kovac-recovery-")
with open(os.path.join(home, "user.cfg"), "w", encoding="utf-8") as f:
    f.write(theme.user_template().replace('<FCInt Name="AutoSaveTimeout" Value="5"/>',
                                          '<FCInt Name="AutoSaveTimeout" Value="1"/>'))
env = dict(os.environ, KOVAC_TEST_HOME=home, KOVAC_RESULT=OUT)
fc = [sys.executable, os.path.join(ROOT, "tools", "fc.py"), "gui"]


def window_titles(pid_root):
    """Visible top-level window titles of FreeCAD processes (Windows)."""
    titles = []
    user32 = ctypes.windll.user32

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if buf.value:
                titles.append((pid.value, buf.value))
        return True
    user32.EnumWindows(cb, 0)
    return titles


def kill(proc):
    subprocess.call(["taskkill", "/F", "/T", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


p1 = subprocess.Popen(fc + [os.path.join(ROOT, "tests", "gui_crash.py")], env=env)
try:
    p1.wait(timeout=180)
except subprocess.TimeoutExpired:
    kill(p1)
first = json.load(open(OUT)) if os.path.exists(OUT) else {}
autosaved = any(f.lower().startswith("fc_recovery_file") for f in first.get("files", []))

p2 = subprocess.Popen(fc, env=env)
offered, deadline = False, time.time() + 90
while time.time() < deadline and not offered:
    time.sleep(1)
    offered = any("recovery" in t.lower() for _, t in window_titles(p2.pid))
kill(p2)

result = {"autosave_wrote_recovery_file": autosaved, "files": first.get("files"), "recovery_offered_on_restart": offered}
json.dump(result, open(OUT, "w"), indent=1)
print(json.dumps(result, indent=1))
sys.exit(0 if autosaved and offered else 1)

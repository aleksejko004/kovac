# SPDX-License-Identifier: LGPL-2.1-or-later
"""Run a GUI test script in a fresh profile and print the results.

    py tests/run_gui.py                  M1 acceptance (gui_acceptance.py)
    py tests/run_gui.py gui_m2.py        M2 end-to-end
(exit code 0 = all checks passed)
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = sys.argv[1] if len(sys.argv) > 1 else "gui_acceptance.py"
OUT = os.path.join(ROOT, "build", "m3" if "m3" in SCRIPT else "m2" if "m2" in SCRIPT else "m1", SCRIPT.replace(".py", ".json"))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
os.makedirs(os.path.dirname(OUT), exist_ok=True)
if os.path.exists(OUT):
    os.remove(OUT)
env = dict(os.environ, KOVAC_RESULT=OUT, KOVAC_LAUNCH_T=repr(time.time()),
           KOVAC_TEST_HOME=tempfile.mkdtemp(prefix="kovac-gui-"))
proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "tools", "fc.py"), "gui",
                         os.path.join(ROOT, "tests", SCRIPT)], env=env)
try:
    proc.wait(timeout=300)
except subprocess.TimeoutExpired:
    subprocess.call(["taskkill", "/F", "/T", "/PID", str(proc.pid)] if os.name == "nt" else ["kill", "-9", str(proc.pid)])
if not os.path.exists(OUT):
    sys.exit("no result written (FreeCAD crashed or hung)")
res = json.load(open(OUT))
for c in res["checks"]:
    print("%s  %s%s" % ("PASS" if c["ok"] else "FAIL", c["name"], "" if c["ok"] else "   -> " + c["detail"][:300]))
for k, v in res["metrics"].items():
    print("metric  %-34s %s" % (k, v))
for k, v in res.get("interactions", {}).items():
    print("interactions  %-28s %s" % (k, v))
for m in res.get("messages", []):
    print("message", m)
for e in res["errors"]:
    print("ERROR", e)
print("PASSED" if res.get("passed") else "FAILED")
sys.exit(0 if res.get("passed") else 1)

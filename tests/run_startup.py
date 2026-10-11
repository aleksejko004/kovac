# SPDX-License-Identifier: LGPL-2.1-or-later
"""Startup time to a usable Kovač window: first launch (fresh profile) and warm launches.
    py tests/run_startup.py"""
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = os.path.join(tempfile.mkdtemp(), "t.txt")
home = tempfile.mkdtemp(prefix="kovac-start-")
times = []
for _ in range(4):
    env = dict(os.environ, KOVAC_TEST_HOME=home, KOVAC_RESULT=out, KOVAC_LAUNCH_T=repr(time.time()))
    subprocess.call([sys.executable, os.path.join(ROOT, "tools", "fc.py"), "gui",
                     os.path.join(ROOT, "tests", "gui_startup_probe.py")], env=env, timeout=120)
    times.append(round(float(open(out).read()), 2))
res = {"first_launch_s": times[0], "warm_launches_s": times[1:]}
json.dump(res, open(os.path.join(ROOT, "build", "m1", "startup.json"), "w"), indent=1)
print(res)

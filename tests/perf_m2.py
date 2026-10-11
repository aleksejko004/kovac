# SPDX-License-Identifier: LGPL-2.1-or-later
"""M2 budgets, headless:  py tools/fc.py cmd tests/perf_m2.py
50-feature part (plate + 45 holes + 4 fillets): open time, regeneration after an edit at the end
of the history and after one at the start (everything replays).
Writes build/m2/perf.json."""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "Kovac")]
import FreeCAD as App  # noqa: E402

from helpers import edge_ref, face_ref, feature, live_bodies, normal, rect, sketch, vertical_edge_at  # noqa: E402
from kovac import features, model, modify  # noqa: E402

V = App.Vector
doc = App.newDocument("Perf")
sk = sketch(doc, rect(0, 0, 200, 200))
ex = feature(doc, features.Extrude, Profile=sk, Length=10)
body = live_bodies(doc)[0]
top = face_ref(doc, body, lambda f: normal(f).z > 0.99)
for i in range(45):
    feature(doc, features.Hole, Face=top, Positions=[V(20 + 20 * (i % 9), 30 + 30 * (i // 9), 10)], Size="M5", ThroughAll=True)
for x, y in ((0, 0), (200, 0), (200, 200), (0, 200)):
    last = feature(doc, modify.Fillet, Edges=[edge_ref(doc, body, vertical_edge_at(x, y))], Radius=5)
n = len([o for o in model.items(doc)])
broken = [o.Label for o in model.items(doc) if getattr(o, "Status", "")]

t0 = time.perf_counter()
last.Radius = 4                                   # edit at the end of the history
model.commit(doc)
tip = time.perf_counter() - t0

t0 = time.perf_counter()
ex.Length = 12                                    # edit at the start: all 50 replay
model.commit(doc)
regen = time.perf_counter() - t0
broken += [o.Label for o in model.items(doc) if getattr(o, "Status", "")]

volume = body.Shape.Volume
path = os.path.join(tempfile.mkdtemp(), "perf50.FCStd")
doc.saveAs(path)
App.closeDocument(doc.Name)
t0 = time.perf_counter()
doc = App.openDocument(path)
opened = time.perf_counter() - t0
ok = abs(live_bodies(doc)[0].Shape.Volume - volume) < 1e-6 if live_bodies(doc) else False

res = {"history_items": n, "regen_after_tip_edit_s": round(tip, 3), "regen_after_upstream_edit_s": round(regen, 3), "open_s": round(opened, 3),
       "reopened_shape_matches": ok, "features_with_errors": broken}
out = os.path.join(os.path.dirname(HERE), "build", "m2")
os.makedirs(out, exist_ok=True)
json.dump(res, open(os.path.join(out, "perf.json"), "w"), indent=1)
os._exit(0 if ok and not broken else 1)

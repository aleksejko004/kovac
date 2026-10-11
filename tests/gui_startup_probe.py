# SPDX-License-Identifier: LGPL-2.1-or-later
"""Writes seconds from launch (KOVAC_LAUNCH_T) to the first idle event-loop turn with Kovač up."""
import os
import time

from PySide import QtCore


def done():
    with open(os.environ["KOVAC_RESULT"], "w") as f:
        f.write(repr(time.time() - float(os.environ["KOVAC_LAUNCH_T"])))
    os._exit(0)


QtCore.QTimer.singleShot(0, done)

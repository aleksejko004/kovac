# SPDX-License-Identifier: LGPL-2.1-or-later
"""Headless test runner:  py tools/fc.py cmd tests/run.py   (exit code = failures)"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "Kovac"), os.path.join(os.path.dirname(HERE), "tools")]
suite = unittest.defaultTestLoader.discover(HERE, pattern="test_*.py")
result = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(suite)
sys.stdout.flush()
os._exit(0 if result.wasSuccessful() and not result.skipped else 1)

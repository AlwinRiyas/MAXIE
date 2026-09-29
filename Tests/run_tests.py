#!/usr/bin/env python3
"""MAXIE test runner.

Runs every ``Tests/*_test.py`` module with ``unittest`` discovery and
injects the project root onto ``sys.path`` so ``Core``/``Brain``/...
imports work from any working directory.

Usage:
    python Tests/run_tests.py            # all tests, default verbosity
    python Tests/run_tests.py -v         # verbose
    python Tests/run_tests.py Tests/vad_test.py   # one file

All tests must pass on a headless machine (no sounddevice, torch,
whisper, or Ollama required).
"""

import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.join(PROJECT_ROOT, "Tests")


def main():
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)

    args = [a for a in sys.argv[1:]]

    # A specific file was passed, e.g. `python Tests/run_tests.py Tests/vad_test.py`
    specific = [a for a in args if a.endswith("_test.py") or a.endswith(".py")]
    if specific:
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        for path in specific:
            if not os.path.isabs(path):
                path = os.path.join(PROJECT_ROOT, path)
            module_name = os.path.splitext(os.path.basename(path))[0]
            sys.path.insert(0, os.path.dirname(path))
            suite.addTests(loader.loadTestsFromName(module_name))
    else:
        loader = unittest.TestLoader()
        suite = loader.discover(
            start_dir=TESTS_DIR, pattern="*_test.py", top_level_dir=PROJECT_ROOT
        )

    verbosity = 2 if "-v" in args else 1
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())